# -*- coding: utf-8 -*-
"""独立直播录制：关注在播、指定作者、直播广场。

不改 douyin.bat / douyin_run.py。打开官网页面拦截 webcast JSON，用 ffmpeg 录拉流。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from douyin_web import (
    default_cookie_path,
    load_netscape_cookies,
    require_login_cookies,
)

HERE = Path(__file__).resolve().parent
LIVE_HINTS = (
    "webcast/web/feed/follow",
    "webcast/feed/follow",
    "webcast/feed/",
    "webcast/room/web/enter",
    "webcast/room/info",
    "webcast/enter",
)
SKIP_URL = (".js", ".css", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".woff", "webmsdk", "sentry")
QUALITY_ORDER = ("FULL_HD1", "HD1", "ORIGION", "ORIGIN", "SD1", "SD2")


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def find_ffmpeg() -> Path | None:
    for name in ("ffmpeg", "ffmpeg.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    local = os.environ.get("LOCALAPPDATA", "")
    hits: list[Path] = []
    if local:
        pkgs = Path(local) / "Microsoft" / "WinGet" / "Packages"
        if pkgs.is_dir():
            hits.extend(pkgs.glob("*FFmpeg*/**/ffmpeg.exe"))
    if not hits:
        return None
    hits.sort(key=lambda p: (0 if "full" in str(p).lower() else 1, len(str(p))))
    return hits[0]


def _safe_name(text: str) -> str:
    out = re.sub(r"[^\w.-]+", "_", str(text or "live"), flags=re.U).strip("._")
    return (out or "live")[:60]


def _domain_cookies(cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        c
        for c in cookies
        if any(
            key in (c.get("domain") or "")
            for key in ("douyin", "snssdk", "amemv", "iesdouyin", "webcast")
        )
    ]


def pick_live_play(stream: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(stream, dict):
        return None
    flv_map = stream.get("flv_pull_url") if isinstance(stream.get("flv_pull_url"), dict) else {}
    hls_map = (
        stream.get("hls_pull_url_map")
        if isinstance(stream.get("hls_pull_url_map"), dict)
        else {}
    )
    for quality in QUALITY_ORDER:
        url = flv_map.get(quality)
        if url:
            return {"protocol": "flv", "quality": quality, "url": url}
    rtmp = stream.get("rtmp_pull_url")
    if rtmp:
        return {"protocol": "flv", "quality": "default", "url": rtmp}
    for quality in QUALITY_ORDER:
        url = hls_map.get(quality)
        if url:
            return {"protocol": "hls", "quality": quality, "url": url}
    hls = stream.get("hls_pull_url")
    if hls:
        return {"protocol": "hls", "quality": "default", "url": hls}
    extra = stream.get("additional_stream_url")
    if isinstance(extra, dict):
        return pick_live_play(extra)
    return None


def summarize_room(obj: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(obj, dict):
        return None
    inner = obj.get("room") if isinstance(obj.get("room"), dict) else obj
    if obj.get("data") and isinstance(obj.get("data"), dict) and obj["data"].get("stream_url"):
        inner = obj["data"]
    stream = inner.get("stream_url") if isinstance(inner.get("stream_url"), dict) else None
    if stream is None and isinstance(obj.get("stream_url"), dict):
        stream = obj.get("stream_url")
        inner = obj
    extra = inner.get("additional_stream_url") if isinstance(inner.get("additional_stream_url"), dict) else None
    play = pick_live_play(stream) or pick_live_play(extra)
    if not play:
        return None
    owner = inner.get("owner") or inner.get("anchor") or {}
    if not isinstance(owner, dict):
        owner = {}
    room_id = str(inner.get("id_str") or inner.get("id") or inner.get("room_id") or "")
    web_rid = str(
        inner.get("web_rid")
        or owner.get("web_rid")
        or inner.get("web_room_id")
        or room_id
    )
    if not room_id and not web_rid:
        return None
    nick = owner.get("nickname") or inner.get("nickname") or web_rid or room_id
    return {
        "room_id": room_id or web_rid,
        "web_rid": web_rid or room_id,
        "title": (inner.get("title") or inner.get("live_title") or "").strip(),
        "nickname": nick,
        "sec_uid": owner.get("sec_uid"),
        "status": inner.get("status"),
        "user_count": inner.get("user_count") or inner.get("viewer_count"),
        "play": play,
        "url": f"https://live.douyin.com/{web_rid or room_id}",
    }


def parse_live_payload(data: Any) -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []

    def walk(obj: Any) -> None:
        if isinstance(obj, dict):
            room = summarize_room(obj)
            if room:
                key = room["room_id"] or room["web_rid"]
                if key not in seen:
                    seen.add(key)
                    items.append(room)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(data)
    return items


def _looks_logged_out(url: str) -> bool:
    ul = (url or "").lower()
    return any(token in ul for token in ("/login", "passport", "sso.")) and "live" not in ul


def _browser_collect(
    cookies_path: Path,
    start_url: str,
    *,
    headed: bool,
    extra_goto: list[str] | None = None,
    scroll_rounds: int = 8,
    open_live_links: bool = False,
) -> list[dict[str, Any]]:
    cookies = _domain_cookies(load_netscape_cookies(cookies_path))
    require_login_cookies(cookies, cookies_path)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        die("需要 playwright：pip install playwright 且已安装浏览器")

    rooms: dict[str, dict[str, Any]] = {}
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    launch_kwargs: dict[str, Any] = {
        "headless": not headed,
        "args": ["--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
    }
    if chrome.is_file():
        launch_kwargs["executable_path"] = str(chrome)

    def ingest(data: Any) -> None:
        for room in parse_live_payload(data):
            rooms[room["room_id"]] = room

    def on_response(resp) -> None:
        url = resp.url or ""
        try:
            if resp.status != 200:
                return
        except Exception:
            return
        hinted = any(h in url for h in LIVE_HINTS)
        if not hinted:
            ul = url.lower()
            if any(s in ul for s in SKIP_URL):
                return
            if "webcast" not in ul and "stream_url" not in ul:
                return
        try:
            ctype = (resp.headers.get("content-type") or "").lower()
        except Exception:
            ctype = ""
        if ctype and "json" not in ctype and "text/plain" not in ctype and not hinted:
            return
        try:
            ingest(resp.json())
        except Exception:
            return

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(**launch_kwargs)
        except Exception:
            launch_kwargs.pop("executable_path", None)
            browser = p.chromium.launch(channel="chrome", headless=not headed)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
            viewport={"width": 1400, "height": 900},
        )
        context.add_cookies(cookies)
        page = context.new_page()
        page.on("response", on_response)
        page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        if _looks_logged_out(page.url or ""):
            browser.close()
            die("cookie 已失效，页面跳到登录。请重新导出 cookie.txt")
        print(f"  parsed {len(rooms)} live rooms", flush=True)
        for _ in range(max(1, scroll_rounds)):
            try:
                page.mouse.wheel(0, 2200)
            except Exception:
                pass
            page.wait_for_timeout(700)
            print(f"  parsed {len(rooms)} live rooms", flush=True)
        hrefs: list[str] = []
        try:
            hrefs = page.eval_on_selector_all(
                'a[href*="live.douyin.com"]',
                "els => els.map(e => e.href)",
            ) or []
        except Exception:
            pass
        extras = list(extra_goto or [])
        if open_live_links or not rooms:
            for href in hrefs:
                if href and "live.douyin.com/" in href and "from_nav" not in href:
                    if href not in extras:
                        extras.append(href)
        for url in extras[:6]:
            if rooms and not open_live_links:
                break
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(3500)
                print(f"  parsed {len(rooms)} live rooms", flush=True)
            except Exception:
                continue
        browser.close()
    return list(rooms.values())


def fetch_follow_lives(cookies_path: Path, headed: bool = False) -> list[dict[str, Any]]:
    return _browser_collect(
        cookies_path,
        "https://www.douyin.com/user/self",
        headed=headed,
        extra_goto=["https://www.douyin.com/follow"],
        scroll_rounds=4,
    )


def fetch_plaza_lives(cookies_path: Path, headed: bool = False) -> list[dict[str, Any]]:
    return _browser_collect(
        cookies_path,
        "https://live.douyin.com/",
        headed=headed,
        scroll_rounds=10,
    )


def fetch_author_live(
    cookies_path: Path,
    target: str,
    headed: bool = False,
) -> list[dict[str, Any]]:
    extras: list[str] = []
    if target.startswith("http") and "live.douyin.com" in target:
        start = target
    else:
        start = target
        extras = []
    return _browser_collect(
        cookies_path,
        start,
        headed=headed,
        extra_goto=extras,
        scroll_rounds=3,
        open_live_links=True,
    )


def classify_live_arg(raw: str | None) -> dict[str, str]:
    if not raw:
        return {"source": "follow", "id": "self", "url": "https://www.douyin.com/user/self"}
    text = raw.strip()
    if text.startswith("#"):
        die("live recorder does not take hashtags; pass a user or live.douyin.com URL")
    found = re.search(r"https?://[^\s]+", text)
    if found:
        text = found.group(0)
    parsed = urlparse(text)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (parsed.path or "/").rstrip("/") or "/"
    if "live.douyin.com" in host or host in {"webcast.amemv.com"}:
        rid = path.strip("/").split("/")[0] if path.strip("/") else ""
        if not rid or rid.lower() in {"live", "index.html"}:
            return {"source": "plaza", "id": "plaza", "url": "https://live.douyin.com/"}
        return {
            "source": "room",
            "id": rid,
            "url": f"https://live.douyin.com/{rid}",
        }
    um = re.search(r"/user/([^/?#]+)", path)
    if um:
        uid = um.group(1)
        return {
            "source": "author",
            "id": uid,
            "url": f"https://www.douyin.com/user/{uid}",
        }
    if re.fullmatch(r"\d{4,}", text):
        return {"source": "room", "id": text, "url": f"https://live.douyin.com/{text}"}
    die(f"not a live/user url: {raw}")
    return {"source": "follow", "id": "self", "url": ""}


def format_hms(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:d}:{secs:02d}"


def find_ffprobe(ffmpeg: Path) -> Path | None:
    sibling = ffmpeg.with_name(ffmpeg.name.replace("ffmpeg", "ffprobe").replace("FFmpeg", "FFprobe"))
    if sibling.is_file():
        return sibling
    alt = ffmpeg.parent / ("ffprobe.exe" if ffmpeg.suffix.lower() == ".exe" else "ffprobe")
    if alt.is_file():
        return alt
    found = shutil.which("ffprobe") or shutil.which("ffprobe.exe")
    return Path(found) if found else None


def probe_duration(ffmpeg: Path, path: Path) -> float | None:
    probe = find_ffprobe(ffmpeg)
    if not probe or not path.is_file():
        return None
    try:
        result = subprocess.run(
            [
                str(probe),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None
    text = (result.stdout or "").strip()
    try:
        value = float(text)
    except ValueError:
        return None
    if value > 0:
        return value
    return None


def remux_with_duration(ffmpeg: Path, src: Path) -> Path:
    """Rewrite container so players can show duration. Live copy often has none."""
    if not src.is_file() or src.stat().st_size < 1000:
        return src
    dest = src.with_suffix(".mp4")
    tmp = src.with_name(src.stem + ".fix.mp4")
    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-fflags",
        "+genpts",
        "-i",
        str(src),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    try:
        result = subprocess.run(cmd, check=False, capture_output=True)
    except OSError:
        return src
    if result.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 1000:
        try:
            if dest.exists():
                dest.unlink()
            tmp.replace(dest)
            src.unlink()
        except OSError:
            return tmp if tmp.is_file() else src
        return dest
    try:
        if tmp.is_file():
            tmp.unlink()
    except OSError:
        pass
    return src


def finish_recording(
    ffmpeg: Path,
    room: dict[str, Any],
    dest: Path,
    started: float,
    code: int | None,
) -> None:
    elapsed = max(0.0, time.time() - started)
    final = remux_with_duration(ffmpeg, dest)
    size = final.stat().st_size if final.is_file() else 0
    file_dur = probe_duration(ffmpeg, final)
    shown = format_hms(file_dur if file_dur else elapsed)
    print(
        f"  done {room.get('nickname')}  recorded {format_hms(elapsed)}"
        f"  file {shown}  {size / 1024 / 1024:.1f} MB  {final}",
        flush=True,
    )


def record_room(ffmpeg: Path, room: dict[str, Any], dest: Path, duration: int) -> subprocess.Popen:
    play = room.get("play") or {}
    url = play.get("url")
    if not url:
        die(f"no stream url for {room.get('nickname')}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(ffmpeg), "-hide_banner", "-loglevel", "error"]
    if duration > 0:
        cmd.extend(["-t", str(duration)])
    cmd.extend(
        [
            "-fflags",
            "+genpts+discardcorrupt",
            "-avoid_negative_ts",
            "make_zero",
            "-rw_timeout",
            "15000000",
            "-i",
            url,
            "-c",
            "copy",
            "-y",
            str(dest),
        ]
    )
    print(
        f"record {room.get('nickname')}  {play.get('quality')} {play.get('protocol')} -> {dest.name}",
        flush=True,
    )
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def prompt_live_target() -> dict[str, str]:
    print(flush=True)
    print("1) following accounts currently live", flush=True)
    print("2) live plaza", flush=True)
    print("3) paste author page or live.douyin.com room URL  (default)", flush=True)
    try:
        choice = input("choose [1/2/3]: ").strip() or "3"
    except EOFError:
        choice = "3"
    if choice == "1":
        return {"source": "follow", "id": "self", "url": "https://www.douyin.com/user/self"}
    if choice == "2":
        return {"source": "plaza", "id": "plaza", "url": "https://live.douyin.com/"}
    try:
        raw = input("live room or user URL: ").strip()
    except EOFError:
        raw = ""
    if not raw:
        die("need a live.douyin.com or user URL")
    return classify_live_arg(raw)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record Douyin live: following-live, one author, or live plaza. Standalone."
    )
    parser.add_argument("url", nargs="?", help="user URL or live.douyin.com URL")
    parser.add_argument("--follow", action="store_true", help="lives from accounts you follow (default)")
    parser.add_argument("--plaza", action="store_true", help="live plaza https://live.douyin.com/")
    parser.add_argument("--info", action="store_true", help="list rooms only, do not record")
    parser.add_argument("--yes", action="store_true", help="start recording without confirm")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--count", type=int, default=0, help="max rooms (0 = all follow/author; plaza default 8)")
    parser.add_argument("--duration", type=int, default=0, help="record seconds per room (0 = until live ends)")
    parser.add_argument("--cookies", help="cookie file (default: cookie.txt beside this script)")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.follow and args.plaza:
        die("use only one of --follow / --plaza")
    cookie_path = Path(args.cookies).expanduser() if args.cookies else default_cookie_path()
    if not cookie_path:
        die(f"need cookie.txt next to {HERE} (same file as douyin.bat)")
    print(f"cookies: {cookie_path}", flush=True)

    if args.plaza:
        info = {"source": "plaza", "id": "plaza", "url": "https://live.douyin.com/"}
    elif args.url:
        info = classify_live_arg(args.url)
    elif args.follow:
        info = {"source": "follow", "id": "self", "url": "https://www.douyin.com/user/self"}
    elif sys.stdin.isatty():
        info = prompt_live_target()
    else:
        info = {"source": "follow", "id": "self", "url": "https://www.douyin.com/user/self"}

    print(f"source: {info['source']}", flush=True)
    print(f"url: {info['url']}", flush=True)

    if info["source"] == "plaza":
        rooms = fetch_plaza_lives(cookie_path, headed=args.headed)
        default_cap = 8
    elif info["source"] == "follow":
        rooms = fetch_follow_lives(cookie_path, headed=args.headed)
        default_cap = 0
    else:
        rooms = fetch_author_live(cookie_path, info["url"], headed=args.headed)
        if info["source"] == "room" and rooms:
            want_id = info["id"]
            matched = [
                r
                for r in rooms
                if want_id in {r.get("web_rid"), r.get("room_id")}
                or want_id in (r.get("url") or "")
            ]
            if matched:
                rooms = matched
        default_cap = 0

    cap = args.count if args.count and args.count > 0 else default_cap
    if cap > 0:
        rooms = rooms[:cap]

    work = Path.cwd() / "live" / _safe_name(info["source"] + "-" + str(info["id"]))
    work.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "live",
        "source": info["source"],
        "url": info["url"],
        "count": len(rooms),
        "items": [
            {k: v for k, v in room.items() if k != "play"}
            | {
                "play": {
                    "protocol": (room.get("play") or {}).get("protocol"),
                    "quality": (room.get("play") or {}).get("quality"),
                    "url": (room.get("play") or {}).get("url"),
                }
            }
            for room in rooms
        ],
    }
    (work / "live.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"count: {len(rooms)}", flush=True)
    for i, room in enumerate(rooms, 1):
        play = room.get("play") or {}
        title = (room.get("title") or "")[:28]
        print(
            f"  {i:3d}. {room.get('nickname')}  {play.get('quality')} {play.get('protocol')}  "
            f"{room.get('url')}  {title}",
            flush=True,
        )
    print(f"saved: {work / 'live.json'}", flush=True)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not rooms:
        if info["source"] == "author" or info["source"] == "room":
            print("warning: this author/room is not live (or stream url was not in the page JSON)", flush=True)
        else:
            print("warning: no live rooms parsed", flush=True)
        return 0
    if args.info:
        print("[2/3] skip record (--info)", flush=True)
        return 0

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        die("ffmpeg not found; install FFmpeg and add it to PATH")
    print(f"ffmpeg: {ffmpeg}", flush=True)
    if not args.yes:
        try:
            ans = input(f"record {len(rooms)} live room(s) until stream ends? [y/N]: ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in {"y", "yes", "是"}:
            print("cancelled")
            return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    procs: list[tuple[dict[str, Any], Path, subprocess.Popen, float]] = []
    for room in rooms:
        nick = _safe_name(str(room.get("nickname") or room.get("web_rid")))
        folder = work / nick
        dest = folder / f"{nick}_{stamp}.mkv"
        started = time.time()
        proc = record_room(ffmpeg, room, dest, args.duration)
        procs.append((room, dest, proc, started))

    print(f"[2/3] recording {len(procs)} stream(s); Ctrl+C stops all", flush=True)
    deadline = time.time() + args.duration + 25 if args.duration > 0 else None
    try:
        while procs:
            still: list[tuple[dict[str, Any], Path, subprocess.Popen, float]] = []
            overtime = deadline is not None and time.time() > deadline
            for room, dest, proc, started in procs:
                code = proc.poll()
                if code is None and overtime:
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    still.append((room, dest, proc, started))
                    continue
                if code is None:
                    still.append((room, dest, proc, started))
                    continue
                finish_recording(ffmpeg, room, dest, started, code)
            procs = still
            if procs:
                time.sleep(1.5)
    except KeyboardInterrupt:
        print("stopping...", flush=True)
        for _room, _dest, proc, _started in procs:
            try:
                proc.terminate()
            except OSError:
                pass
        time.sleep(1)
        leftover = list(procs)
        procs = []
        for room, dest, proc, started in leftover:
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
                time.sleep(0.3)
            finish_recording(ffmpeg, room, dest, started, proc.poll())
    print("[3/3] done", flush=True)
    print(f"dir: {work}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
