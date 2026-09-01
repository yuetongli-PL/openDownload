# -*- coding: utf-8 -*-
"""解析抖音链接：推荐流、作品页、用户弹窗、短链。

推荐页走 aweme.snssdk.com 移动端接口（无需登录 cookie）。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from douyin_filter import classify_item, extract_topic_fields

APP_UA = (
    "okhttp/3.12.1 com.ss.android.ugc.aweme/130601 "
    "(Linux; U; Android 13; zh_CN; Pixel 7; Build/TD1A.220804.031)"
)
WEB_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
FEED_URL = "https://aweme.snssdk.com/aweme/v1/feed/"
VIDEO_RE = re.compile(r"(?:video|note)/(\d{5,})")
USER_RE = re.compile(r"/user/([^/?#]+)")
HASHTAG_RE = re.compile(r"/(?:hashtag|challenge)/([^/?#]+)")
SHORT_HOSTS = {"v.douyin.com", "www.iesdouyin.com"}
COOKIE_FILE: Path | None = None


def set_cookie_file(path: Path | None) -> None:
    global COOKIE_FILE
    COOKIE_FILE = path


def _runtime_cookie_jar() -> Path:
    return Path(tempfile.gettempdir()) / "douyin.runtime.cookies"


def is_netscape_cookie_file(text: str) -> bool:
    return "\t" in text and text.count("\t") >= 6


def cookie_header_string(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if is_netscape_cookie_file(text):
        return ""
    parts = []
    blob = " ".join(
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    )
    for part in blob.split(";"):
        part = part.strip()
        if part and "=" in part:
            parts.append(part)
    return "; ".join(parts)


def write_netscape_jar(cookies: list[dict], path: Path) -> None:
    lines = ["# Netscape HTTP Cookie File", "# runtime jar; do not edit"]
    for item in cookies:
        name = item.get("name") or ""
        if not name:
            continue
        domain = item.get("domain") or ".douyin.com"
        flag = "TRUE" if str(domain).startswith(".") else "FALSE"
        secure = "TRUE" if item.get("secure") else "FALSE"
        expires = str(int(item.get("expires") or 0))
        path_c = item.get("path") or "/"
        value = str(item.get("value") or "")
        lines.append(f"{domain}\t{flag}\t{path_c}\t{secure}\t{expires}\t{name}\t{value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def curl_cookie_args() -> list[str]:
    runtime = _runtime_cookie_jar()
    args = ["-c", str(runtime), "-b", str(runtime)]
    if not (COOKIE_FILE and COOKIE_FILE.is_file()):
        return args
    from douyin_web import load_netscape_cookies

    cookies = load_netscape_cookies(COOKIE_FILE)
    if not cookies:
        return args
    write_netscape_jar(cookies, runtime)
    return ["-c", str(runtime), "-b", str(runtime)]


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def http_get(url: str, ua: str = APP_UA, timeout: int = 25) -> bytes:
    req = Request(
        url,
        headers={
            "User-Agent": ua,
            "Accept": "*/*",
            "Referer": "https://www.douyin.com/",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        return resp.read() or b""


def _curl_bin() -> str | None:
    for name in ("curl.exe", "curl"):
        found = shutil.which(name)
        if found:
            return found
    return None


def curl_get(url: str, ua: str = APP_UA, timeout: int = 25) -> bytes:
    curl = _curl_bin()
    if not curl:
        return b""
    cmd = [
        curl,
        "-sL",
        "--max-time",
        str(timeout),
        "-A",
        ua,
        "-H",
        "Referer: https://www.douyin.com/",
        *curl_cookie_args(),
        url,
    ]
    try:
        result = subprocess.run(cmd, check=False, capture_output=True)
    except OSError:
        return b""
    return result.stdout or b""


def fetch_bytes(url: str, ua: str = APP_UA, timeout: int = 30) -> bytes:
    data = curl_get(url, ua, timeout)
    if data:
        return data
    try:
        return http_get(url, ua, timeout)
    except Exception:
        return b""


def resolve_short(url: str) -> str:
    curl = _curl_bin()
    if curl:
        result = subprocess.run(
            [curl, "-sI", "-L", "--max-time", "20", "-A", WEB_UA, url],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        locs = re.findall(r"(?i)^location:\s*(\S+)", result.stdout or "", re.M)
        if locs:
            return locs[-1].strip()
    return url


def classify(raw: str) -> dict[str, str]:
    text = raw.strip()
    if not text:
        die("empty url")
    if text.startswith("#") and len(text.lstrip("#").strip()) >= 1:
        tag = text.lstrip("#").strip()
        return {
            "kind": "hashtag",
            "id": tag,
            "url": f"https://www.douyin.com/hashtag/{tag}",
        }
    if re.fullmatch(r"\d{5,}", text):
        return {"kind": "video", "id": text, "url": f"https://www.douyin.com/video/{text}"}
    found = re.search(r"https?://[^\s]+", text)
    if found:
        text = found.group(0)
    parsed = urlparse(text)
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    qs = parse_qs(parsed.query)
    if host in SHORT_HOSTS and "douyin" in host:
        resolved = resolve_short(text)
        return classify(resolved)
    if "douyin.com" not in host and host not in {"iesdouyin.com"}:
        die(f"not a douyin url: {raw}")
    path = parsed.path or "/"
    if path in {"/", ""} or path.rstrip("/") in {"/recommend", "/jingxuan"} or "recommend" in qs:
        return {"kind": "feed", "id": "recommend", "url": "https://www.douyin.com/?recommend=1"}
    if path.rstrip("/") == "/follow":
        return {
            "kind": "follow_feed",
            "id": "follow-feed",
            "url": "https://www.douyin.com/follow",
        }
    hm = HASHTAG_RE.search(path)
    if hm:
        tag = hm.group(1)
        kind_path = "hashtag" if "/hashtag/" in path else "challenge"
        return {
            "kind": "hashtag",
            "id": tag,
            "url": f"https://www.douyin.com/{kind_path}/{tag}",
        }
    m = VIDEO_RE.search(path)
    if m:
        vid = m.group(1)
        return {"kind": "video", "id": vid, "url": f"https://www.douyin.com/video/{vid}"}
    modal = (qs.get("modal_id") or qs.get("vid") or [None])[0]
    if modal and re.fullmatch(r"\d{5,}", modal):
        return {"kind": "video", "id": modal, "url": f"https://www.douyin.com/video/{modal}"}
    um = USER_RE.search(path)
    if um:
        uid = um.group(1)
        show_tab = ((qs.get("showTab") or qs.get("show_tab") or [""])[0] or "").lower()
        if show_tab in {"like", "favorite"}:
            return {
                "kind": "like",
                "id": uid,
                "url": f"https://www.douyin.com/user/{uid}?showTab=like",
            }
        if show_tab in {"following", "follow"}:
            return {
                "kind": "following",
                "id": uid,
                "url": f"https://www.douyin.com/user/{uid}",
            }
        if show_tab in {"fans", "follower", "followers"}:
            return {
                "kind": "followers",
                "id": uid,
                "url": f"https://www.douyin.com/user/{uid}",
            }
        return {
            "kind": "user",
            "id": uid,
            "url": f"https://www.douyin.com/user/{uid}",
        }
    die(f"unsupported douyin url: {raw}")
    return {"kind": "unknown", "id": "", "url": text}


def pick_best_play(video: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for br in video.get("bit_rate") or []:
        play = br.get("play_addr") or {}
        urls = [u for u in (play.get("url_list") or []) if u]
        if not urls:
            continue
        w = int(play.get("width") or 0)
        h = int(play.get("height") or 0)
        candidates.append(
            {
                "gear": br.get("gear_name"),
                "quality": br.get("quality_type"),
                "width": w,
                "height": h,
                "size": int(play.get("data_size") or 0),
                "url": urls[0],
                "urls": urls,
                "codec": br.get("codec_type") or play.get("url_key"),
            }
        )
    if not candidates:
        play = video.get("play_addr_h264") or video.get("play_addr") or {}
        urls = [u for u in (play.get("url_list") or []) if u]
        if urls:
            w = int(play.get("width") or 0)
            h = int(play.get("height") or 0)
            candidates.append(
                {
                    "gear": "play_addr",
                    "width": w,
                    "height": h,
                    "size": int(play.get("data_size") or 0),
                    "url": urls[0],
                    "urls": urls,
                }
            )
    if not candidates:
        return None
    candidates.sort(key=lambda x: (max(x["width"], x["height"]), x["size"]), reverse=True)
    return candidates[0]


def cover_url(video: dict[str, Any], aweme: dict[str, Any]) -> str | None:
    for key in ("origin_cover", "cover", "dynamic_cover"):
        urls = ((video.get(key) or {}).get("url_list")) or []
        if urls:
            return urls[0]
    return None


def _first_url(obj: Any) -> str | None:
    if isinstance(obj, str) and obj:
        return obj
    if not isinstance(obj, dict):
        return None
    urls = [u for u in (obj.get("url_list") or []) if u]
    if urls:
        return urls[0]
    return obj.get("url") or obj.get("uri") or None


def _as_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def summarize_author(author: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(author, dict):
        return None
    sec = author.get("sec_uid") or author.get("sec_user_id") or author.get("secUid")
    if not sec:
        return None
    stats = author.get("statistics") if isinstance(author.get("statistics"), dict) else {}
    uid = author.get("uid") or author.get("user_id")
    return {
        "kind": "user",
        "nickname": author.get("nickname") or author.get("nick_name"),
        "sec_uid": str(sec),
        "uid": str(uid) if uid else None,
        "unique_id": author.get("unique_id") or author.get("uniqueId") or author.get("short_id"),
        "signature": author.get("signature"),
        "avatar": _first_url(
            author.get("avatar_larger")
            or author.get("avatar_300x300")
            or author.get("avatar_medium")
            or author.get("avatar_thumb")
            or author.get("avatar_168x168")
        ),
        "follower_count": _as_int(
            author.get("follower_count")
            or stats.get("follower_count")
            or author.get("mplatform_followers_count")
            or stats.get("mplatform_followers_count")
        ),
        "following_count": _as_int(author.get("following_count") or stats.get("following_count")),
        "aweme_count": _as_int(author.get("aweme_count") or stats.get("aweme_count")),
        "total_favorited": _as_int(author.get("total_favorited") or stats.get("total_favorited")),
        "custom_verify": author.get("custom_verify") or "",
        "enterprise_verify_reason": author.get("enterprise_verify_reason") or "",
        "url": f"https://www.douyin.com/user/{sec}",
    }


def parse_profile_payload(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    for key in ("user", "user_info", "user_detail"):
        hit = summarize_author(data.get(key) if isinstance(data.get(key), dict) else None)
        if hit:
            extra = {}
            for count_key in ("user_collect_count", "user_watchlater_count"):
                if count_key in data:
                    extra[count_key] = data.get(count_key)
            if extra:
                hit = dict(hit, **extra)
            return hit
    return summarize_author(data)


def summarize_aweme(aweme: dict[str, Any]) -> dict[str, Any]:
    video = aweme.get("video") or {}
    best = pick_best_play(video)
    author = aweme.get("author") or {}
    aweme_id = str(aweme.get("aweme_id") or "")
    title = (aweme.get("desc") or aweme_id).strip() or aweme_id
    mix = aweme.get("mix_info") or {}
    topic = extract_topic_fields(aweme, title)
    stats = aweme.get("statistics") if isinstance(aweme.get("statistics"), dict) else {}
    music = aweme.get("music") if isinstance(aweme.get("music"), dict) else {}
    profile = summarize_author(author) or {}
    item = {
        "id": aweme_id,
        "title": title,
        "author": author.get("nickname") or profile.get("nickname"),
        "sec_uid": author.get("sec_uid") or profile.get("sec_uid"),
        "uid": author.get("uid") or profile.get("uid"),
        "unique_id": author.get("unique_id") or profile.get("unique_id"),
        "duration": (video.get("duration") or 0) / 1000 if video.get("duration") else None,
        "cover": cover_url(video, aweme),
        "url": f"https://www.douyin.com/video/{aweme_id}" if aweme_id else None,
        "best": best,
        "allow_download": ((aweme.get("video_control") or {}).get("allow_download")),
        "topics": topic["topics"],
        "hashtags": topic["hashtags"],
        "video_tags": topic["video_tags"],
        "tags": topic["tags"],
        "is_ads": bool(aweme.get("is_ads") or aweme.get("is_advertisement")),
        "mix": mix.get("mix_name") if isinstance(mix, dict) else None,
        "mix_id": mix.get("mix_id") if isinstance(mix, dict) else None,
        "aweme_type": aweme.get("aweme_type"),
        "create_time": _as_int(aweme.get("create_time")),
        "statistics": {
            "digg_count": _as_int(stats.get("digg_count")),
            "comment_count": _as_int(stats.get("comment_count")),
            "share_count": _as_int(stats.get("share_count")),
            "collect_count": _as_int(stats.get("collect_count")),
            "play_count": _as_int(stats.get("play_count") or stats.get("aweme_play_count")),
        },
        "music": {
            "id": music.get("mid") or music.get("id"),
            "title": music.get("title"),
            "author": music.get("author"),
        }
        if music
        else None,
        "author_profile": profile or None,
    }
    return classify_item(item)


def summarize_comment(comment: dict[str, Any]) -> dict[str, Any]:
    user = comment.get("user") if isinstance(comment.get("user"), dict) else {}
    return {
        "cid": comment.get("cid") or comment.get("comment_id"),
        "text": comment.get("text") or "",
        "digg_count": _as_int(comment.get("digg_count")),
        "reply_count": _as_int(
            comment.get("reply_comment_total") or comment.get("reply_count")
        ),
        "create_time": _as_int(comment.get("createTime") or comment.get("create_time")),
        "ip_label": comment.get("ip_label"),
        "user": user.get("nickname"),
        "unique_id": user.get("unique_id") or user.get("short_id"),
        "sec_uid": user.get("sec_uid") or user.get("sec_user_id"),
    }


def fetch_comments(aweme_id: str, count: int = 20) -> list[dict[str, Any]]:
    """Unsigned ies comment list: typically the first page (~10)."""
    want = max(0, int(count))
    if want <= 0 or not aweme_id:
        return []
    query = urlencode(
        {"aweme_id": str(aweme_id), "count": min(want, 50), "cursor": 0}
    )
    raw = fetch_bytes(
        f"https://www.iesdouyin.com/web/api/v2/comment/list/?{query}", WEB_UA, 20
    )
    if not raw:
        return []
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for comment in data.get("comments") or []:
        if not isinstance(comment, dict):
            continue
        item = summarize_comment(comment)
        cid = str(item.get("cid") or "")
        if cid and cid in seen:
            continue
        if cid:
            seen.add(cid)
        if item.get("text") or cid:
            out.append(item)
        if len(out) >= want:
            break
    return out


def fetch_user_info(
    *,
    unique_id: str | None = None,
    sec_uid: str | None = None,
) -> dict[str, Any]:
    """Resolve 抖音号 / sec_uid via unsigned ies user info."""
    uid = (unique_id or "").strip().lstrip("@")
    sec = (sec_uid or "").strip()
    if sec.startswith("MS4wLjAB"):
        query = urlencode({"sec_uid": sec})
    elif uid.startswith("MS4wLjAB"):
        query = urlencode({"sec_uid": uid})
    elif uid:
        query = urlencode({"unique_id": uid})
    elif sec:
        query = urlencode({"unique_id": sec})
    else:
        die("need a 抖音号 or sec_uid")
    raw = fetch_bytes(
        f"https://www.iesdouyin.com/web/api/v2/user/info/?{query}", WEB_UA, 20
    )
    if not raw:
        die("user info request failed (empty response)")
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        die("user info is not JSON")
    status = data.get("status_code")
    if status not in (0, None, "0"):
        die(f"找不到该抖音号 status={status} {data.get('status_msg') or ''}".strip())
    info = data.get("user_info") or data.get("user") or {}
    if not isinstance(info, dict) or not (
        info.get("sec_uid") or info.get("sec_user_id")
    ):
        die("找不到该抖音号（user_info 为空）")
    author = summarize_author(info)
    if not author:
        die("找不到该抖音号（缺少 sec_uid）")
    author["unique_id"] = info.get("unique_id") or author.get("unique_id")
    author["show_favorite_list"] = bool(info.get("show_favorite_list"))
    author["favoriting_count"] = _as_int(info.get("favoriting_count"))
    return author


def fetch_feed(count: int = 100) -> dict[str, Any]:
    want = max(1, min(int(count), 200))
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    cursor = 0
    rounds = 0
    while len(items) < want and rounds < 30:
        rounds += 1
        batch = min(20, want - len(items))
        query = urlencode(
            {
                "count": batch,
                "type": 0,
                "pull_type": 2 if cursor == 0 else 1,
                "max_cursor": cursor,
            }
        )
        raw = fetch_bytes(f"{FEED_URL}?{query}", APP_UA)
        if not raw:
            break
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            break
        if data.get("status_code") not in (0, None):
            if not items:
                die(f"feed status {data.get('status_code')} {data.get('status_msg')}")
            break
        added = 0
        for aweme in data.get("aweme_list") or []:
            if not aweme.get("aweme_id"):
                continue
            item = summarize_aweme(aweme)
            if not item.get("id") or item["id"] in seen or not item.get("best"):
                continue
            seen.add(item["id"])
            items.append(item)
            added += 1
            if len(items) >= want:
                break
        nxt = data.get("max_cursor") or data.get("min_cursor") or 0
        try:
            nxt = int(nxt)
        except (TypeError, ValueError):
            nxt = 0
        if added == 0 or not data.get("has_more") or nxt == cursor:
            break
        cursor = nxt
    if not items:
        die("recommend feed is empty")
    return {
        "kind": "feed",
        "id": "recommend",
        "url": "https://www.douyin.com/?recommend=1",
        "count": len(items),
        "items": items[:want],
    }


def fetch_video(video_id: str) -> dict[str, Any]:
    # App feed does not take aweme_id; try detail then scan a few feed pages.
    for extra in (
        f"https://aweme.snssdk.com/aweme/v1/aweme/detail/?aweme_id={video_id}&aid=1128&device_platform=android",
        f"https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/?item_ids={video_id}",
    ):
        raw = fetch_bytes(extra, APP_UA)
        if not raw:
            continue
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            continue
        aweme = data.get("aweme_detail") or {}
        if not aweme and data.get("item_list"):
            aweme = data["item_list"][0]
        if aweme.get("aweme_id"):
            item = summarize_aweme(aweme)
            item["kind"] = "video"
            return item
    die(
        f"cannot load video {video_id} without web cookies "
        "(yt-dlp needs s_v_web_id). Use a /?recommend=1 feed link, or pass --cookies."
    )
    return {}


def print_feed(data: dict[str, Any]) -> None:
    print(f"kind: feed")
    print(f"count: {data.get('count')}")
    for item in data.get("items") or []:
        best = item.get("best") or {}
        print(
            f"{item.get('id')}  {best.get('width')}x{best.get('height')}  "
            f"{best.get('gear')}  {item.get('author')}  {(item.get('title') or '')[:40]}"
        )


def print_video(item: dict[str, Any]) -> None:
    best = item.get("best") or {}
    print(f"id: {item.get('id')}")
    print(f"title: {item.get('title')}")
    print(f"author: {item.get('author')}")
    print(f"url: {item.get('url')}")
    print(f"cover: {item.get('cover')}")
    print(
        f"best: {best.get('width')}x{best.get('height')}  "
        f"{best.get('gear')}  {best.get('size')} bytes"
    )
    if best.get("url"):
        print(f"play: {best.get('url')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Parse Douyin recommend feed or video URL.")
    parser.add_argument("url", nargs="?", help="Douyin URL")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--count", type=int, default=100, help="recommend feed size (default 100)")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    raw = args.url
    if not raw:
        try:
            raw = input("url: ").strip()
        except EOFError:
            raw = ""
    if not raw:
        die("need a douyin url")
    info = classify(raw)
    if info["kind"] == "feed":
        data = fetch_feed(args.count)
    elif info["kind"] == "video":
        data = fetch_video(info["id"])
    else:
        die(
            "user / likes / following need login cookies; "
            "use douyin.bat <user-url>  or  douyin.bat --likes  or  douyin.bat --following"
        )
        data = {}
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif data.get("kind") == "feed" or "items" in data:
        print_feed(data)
    else:
        print_video(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
