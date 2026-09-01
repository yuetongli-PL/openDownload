# -*- coding: utf-8 -*-
"""由 douyin.bat 调用：解析抖音推荐流/作品并下载最高清晰度 mp4。"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from douyin_filter import (
    CATEGORIES,
    LABELS,
    analyze_native_tags,
    apply_filters,
    category_counts,
    classify_items,
    item_native_tags,
    resolve_name,
    split_csv,
)
from douyin_parse import (
    WEB_UA,
    classify,
    curl_cookie_args,
    die,
    fetch_bytes,
    fetch_feed,
    fetch_video,
    set_cookie_file,
)
from douyin_web import (
    cookie_help,
    default_cookie_path,
    fetch_follow_feed,
    fetch_followers,
    fetch_following,
    fetch_hashtag,
    fetch_likes,
    fetch_logged_in_feed,
    fetch_user_posts,
    fetch_video_page,
)


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


_CURL_HELP = ""


def curl_has_flag(curl: str, flag: str) -> bool:
    global _CURL_HELP
    if not _CURL_HELP:
        try:
            result = subprocess.run(
                [curl, "--help", "all"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            _CURL_HELP = (result.stdout or "") + (result.stderr or "")
        except OSError:
            _CURL_HELP = ""
    return flag in _CURL_HELP


def curl_download(url: str, dest: Path, timeout: int = 120) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    curl = shutil.which("curl.exe") or shutil.which("curl")
    tmp = dest.with_suffix(dest.suffix + ".part")
    if curl:
        cmd = [
            curl,
            "-sSL",
            "--max-time",
            str(timeout),
            "--connect-timeout",
            "8",
            "-A",
            WEB_UA,
            "-H",
            "Referer: https://www.douyin.com/",
            "-H",
            "Accept: */*",
            *curl_cookie_args(),
            "-o",
            str(tmp),
            url,
        ]
        if curl_has_flag(curl, "--tcp-nodelay"):
            cmd.append("--tcp-nodelay")
        if curl_has_flag(curl, "--ssl-no-revoke"):
            cmd.append("--ssl-no-revoke")
        result = subprocess.run(cmd, check=False)
        if result.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 1000:
            tmp.replace(dest)
            return True
        if tmp.is_file():
            try:
                tmp.unlink()
            except OSError:
                pass
    data = fetch_bytes(url, WEB_UA, timeout)
    if len(data) < 1000:
        return False
    dest.write_bytes(data)
    return True


def save_cover(url: str | None, dest: Path) -> Path | None:
    if not url:
        return None
    try:
        curl_download(url, dest, timeout=30)
    except SystemExit:
        return None
    return dest if dest.is_file() else None


def _curl_bin() -> str | None:
    return shutil.which("curl.exe") or shutil.which("curl")


def write_curl_config(jobs: list[tuple[str, Path]], cfg: Path) -> None:
    lines: list[str] = []
    for url, dest in jobs:
        dest.parent.mkdir(parents=True, exist_ok=True)
        lines.append(f'url = "{url.replace(chr(34), "%22")}"')
        lines.append(f'output = "{dest.as_posix().replace(chr(34), "_")}"')
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")


def play_urls(item: dict) -> list[str]:
    best = item.get("best") or {}
    urls: list[str] = []
    for u in best.get("urls") or []:
        if u and u not in urls:
            urls.append(u)
    play = best.get("url")
    if play and play not in urls:
        urls.insert(0, play)
    return urls


def file_ok(path: Path, min_size: int = 1000) -> bool:
    try:
        return path.is_file() and path.stat().st_size > min_size
    except OSError:
        return False


def build_curl_parallel_cmd(curl: str, cfg: Path, parallel_max: int, timeout: int) -> list[str]:
    pmax = str(max(1, parallel_max))
    cmd = [
        curl,
        "-sS",
        "-L",
        "-Z",
        "--parallel-max",
        pmax,
        "--retry",
        "2",
        "--retry-delay",
        "0",
        "--connect-timeout",
        "8",
        "--max-time",
        str(max(timeout, 60)),
        "-A",
        WEB_UA,
        "-H",
        "Accept: */*",
        "-H",
        "Referer: https://www.douyin.com/",
        *curl_cookie_args(),
        "-K",
        str(cfg),
    ]
    if curl_has_flag(curl, "--parallel-immediate"):
        cmd.append("--parallel-immediate")
    if curl_has_flag(curl, "--parallel-max-host"):
        cmd.extend(["--parallel-max-host", pmax])
    if curl_has_flag(curl, "--tcp-nodelay"):
        cmd.append("--tcp-nodelay")
    if curl_has_flag(curl, "--ssl-no-revoke"):
        cmd.append("--ssl-no-revoke")
    if curl_has_flag(curl, "--retry-all-errors"):
        cmd.append("--retry-all-errors")
    return cmd


def _staged_ok(staged: Path, dest: Path) -> bool:
    return file_ok(staged) or file_ok(dest)


def _run_curl_batch(
    curl: str,
    pending: list[tuple[list[str], Path, Path]],
    stage: Path,
    workers: int,
    label: str,
) -> None:
    if not pending:
        return
    jobs = [(urls[0], staged) for urls, staged, _dest in pending]
    cfg = stage / f"curl-{label}.cfg"
    write_curl_config(jobs, cfg)
    pmax = max(1, min(workers, len(jobs)))
    print(
        f"download {label}: curl --parallel {len(jobs)} files, connections={pmax}, staging={stage}",
        flush=True,
    )
    cmd = build_curl_parallel_cmd(curl, cfg, pmax, timeout=600)
    t0 = time.time()
    subprocess.run(cmd, check=False)
    elapsed = max(time.time() - t0, 0.001)
    got = sum(1 for _u, staged, dest in pending if _staged_ok(staged, dest))
    total = 0
    for _u, staged, dest in pending:
        src = staged if file_ok(staged) else dest if file_ok(dest) else None
        if src:
            total += src.stat().st_size
    print(
        f"{label}: {got}/{len(pending)} files  {total / 1024 / 1024:.1f} MB  "
        f"in {elapsed:.1f}s  ({total / elapsed / 1024 / 1024:.2f} MB/s)",
        flush=True,
    )
    missing = [row for row in pending if not _staged_ok(row[1], row[2])]
    if missing:
        print(f"retry {len(missing)} {label}", flush=True)
        for urls, staged, _dest in missing:
            for url in urls:
                if curl_download(url, staged, timeout=180):
                    break


def _move_staged(pending: list[tuple[list[str], Path, Path]], work: Path) -> int:
    moved = 0
    for _urls, staged, dest in pending:
        if file_ok(dest) or not file_ok(staged):
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            if dest.exists():
                dest.unlink()
            shutil.move(str(staged), str(dest))
            moved += 1
        except OSError:
            try:
                shutil.copyfile(str(staged), str(dest))
                moved += 1
            except OSError:
                pass
    return moved


def download_parallel(items: list[dict], work: Path, workers: int = 32) -> list[Path]:
    curl = _curl_bin()
    if not curl:
        die("curl not found")
    stage = Path(tempfile.gettempdir()) / "douyin-dl"
    stage.mkdir(parents=True, exist_ok=True)
    videos: list[tuple[list[str], Path, Path]] = []
    covers: list[tuple[list[str], Path, Path]] = []
    dests: list[Path] = []
    for item in items:
        aweme_id = str(item.get("id") or "")
        urls = play_urls(item)
        if not aweme_id or not urls:
            continue
        folder = work / aweme_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "meta.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        dest = folder / f"{aweme_id}.mp4"
        dests.append(dest)
        if not file_ok(dest):
            videos.append((urls, stage / f"{aweme_id}.mp4", dest))
        if item.get("cover"):
            jpg = folder / f"{aweme_id}.jpg"
            if not file_ok(jpg, 200):
                covers.append(([item["cover"]], stage / f"{aweme_id}.jpg", jpg))
    if not videos and not covers:
        print("download: all files already present", flush=True)
        return dests
    _run_curl_batch(curl, videos, stage, workers, "videos")
    _run_curl_batch(curl, covers, stage, min(workers, 16), "covers")
    t1 = time.time()
    moved = _move_staged(videos + covers, work)
    if moved:
        print(f"copied {moved} files to {work} in {time.time() - t1:.1f}s", flush=True)
    return [p for p in dests if file_ok(p)]


def print_tag_analysis(items: list[dict], work: Path | None = None) -> dict:
    report = analyze_native_tags(items)
    print(flush=True)
    print("========== 视频自带话题 ==========", flush=True)
    print(
        f"  {report['with_tags']}/{report['videos']} videos have tags, "
        f"{report['unique']} unique",
        flush=True,
    )
    for row in report["tags"]:
        print(f"  {row['count']:3d}  #{row['name']}", flush=True)
    missing = report.get("without_tags") or []
    if missing:
        print(f"  no tags: {len(missing)} videos", flush=True)
    if work is not None:
        path = work / "tags.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  saved: {path}", flush=True)
    return report


def print_category_stats(items: list[dict]) -> None:
    print(flush=True)
    print("========== categories ==========", flush=True)
    for name, n, parent in category_counts(items):
        if parent:
            print(f"    {name}: {n}", flush=True)
        else:
            print(f"  {name}: {n}", flush=True)
    print(
        "  filter: 大类 / 子类 / 视频自带 #话题   e.g. --tag 韩剧解说",
        flush=True,
    )


def print_item_list(items: list[dict]) -> None:
    print(f"count: {len(items)}", flush=True)
    for i, item in enumerate(items, 1):
        best = item.get("best") or {}
        size = int(best.get("size") or 0)
        size_s = f"{size / 1024 / 1024:.1f}MB" if size else ""
        dur = float(item.get("duration") or 0)
        dur_s = f"{dur / 60:.1f}min" if dur else ""
        title = re.sub(r"\s+", " ", item.get("title") or "")[:28]
        parent = item.get("category") or "-"
        label = item.get("label") or parent
        shown = parent if label == parent else f"{parent}/{label}"
        tags = " ".join(f"#{t}" for t in item_native_tags(item))
        print(
            f"  {i:3d}. {shown}  {item.get('orient') or '-'}  "
            f"{dur_s}  {best.get('width')}x{best.get('height')}  {size_s}  "
            f"{item.get('author')}  {tags}  {title}",
            flush=True,
        )


def prompt_categories(items: list[dict], yes: bool, already_filtered: bool) -> list[dict] | None:
    if yes or already_filtered or not items:
        return items
    try:
        ans = input("keep categories/tags [all] (e.g. 韩剧,电影解说,#悬疑): ").strip()
    except EOFError:
        ans = ""
    if not ans or ans.lower() in {"all", "a", "全部"}:
        return items
    if ans.lower() in {"n", "no", "q", "cancel"}:
        return None
    wanted = [resolve_name(x.lstrip("#")) for x in split_csv(ans)]
    picked = apply_filters(items, categories=wanted)
    print(f"filter: {len(items)} -> {len(picked)} ({', '.join(wanted)})", flush=True)
    if not picked:
        print("no match. try 韩剧 / 电影解说 / 动漫解说 / #抖音精选", flush=True)
    return picked


def confirm_download(items: list[dict], yes: bool) -> bool:
    total = sum(int((i.get("best") or {}).get("size") or 0) for i in items)
    print(flush=True)
    print("========== parse done ==========", flush=True)
    if total > 0:
        print(
            f"keep {len(items)} videos, ~{total / 1024 / 1024:.0f} MB",
            flush=True,
        )
    else:
        print(f"keep {len(items)} videos", flush=True)
    print("confirm to start parallel download (target ~13 MB/s)", flush=True)
    if yes:
        return True
    try:
        ans = input("download these videos? [y/N]: ").strip().lower()
    except EOFError:
        ans = ""
    return ans in {"y", "yes", "是"}


def download_item(item: dict, work: Path) -> Path:
    best = item.get("best") or {}
    play = best.get("url")
    if not play:
        die(f"no play url for {item.get('id')}")
    aweme_id = str(item["id"])
    folder = work / aweme_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "meta.json").write_text(
        json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if item.get("cover"):
        save_cover(item["cover"], folder / f"{aweme_id}.jpg")
    mp4 = folder / f"{aweme_id}.mp4"
    print(
        f"download {aweme_id}  {best.get('width')}x{best.get('height')}  {best.get('gear')}",
        flush=True,
    )
    if not curl_download(play, mp4):
        die(f"download too small: {play[:80]}")
    return mp4


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse Douyin recommend, posts, likes, following, followers, follow-feed, related, hashtags."
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="Douyin URL (optional with --likes / --following / --followers / --follow-feed)",
    )
    parser.add_argument("--info", action="store_true", help="parse only")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="max items to parse (default: 100 for recommend, all for lists; 0 = all)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="max videos to download after confirm (0 = all parsed)",
    )
    parser.add_argument("--yes", action="store_true", help="skip confirm and download immediately")
    parser.add_argument("--workers", type=int, default=32, help="curl parallel connections")
    parser.add_argument(
        "--cookies",
        help="cookie file (default: 抖音/cookie.txt or cookies.txt)",
    )
    parser.add_argument(
        "--guest",
        action="store_true",
        help="use anonymous app feed, not logged-in recommend",
    )
    parser.add_argument("--headed", action="store_true", help="show browser when fetching login pages")
    parser.add_argument(
        "--likes",
        action="store_true",
        help="liked videos (own account, or another user's public likes tab)",
    )
    parser.add_argument(
        "--following",
        action="store_true",
        help="following users (own account, or another user's public following)",
    )
    parser.add_argument(
        "--followers",
        action="store_true",
        help="followers (own account, or another user's public fans)",
    )
    parser.add_argument(
        "--follow-feed",
        action="store_true",
        help="videos from accounts you follow (https://www.douyin.com/follow)",
    )
    parser.add_argument(
        "--related",
        action="store_true",
        help="related videos for a /video/<id> URL",
    )
    parser.add_argument(
        "--from-feed",
        help="reuse recommend/feed.json, skip parse (re-filter / re-download)",
    )
    parser.add_argument(
        "--category",
        help="keep 大类/子类/标签, comma-separated: 影视解说,韩剧,电影解说,#悬疑",
    )
    parser.add_argument("--exclude", help="drop these categories or tags, comma-separated")
    parser.add_argument(
        "--tag",
        help="keep videos that carry this native topic tag, comma-separated, e.g. 韩剧解说,抖音精选",
    )
    parser.add_argument("--orient", help="横屏 or 竖屏")
    parser.add_argument("--min-minutes", type=float, default=0, help="keep videos longer than N minutes")
    parser.add_argument("--max-minutes", type=float, default=0, help="keep videos shorter than N minutes")
    parser.add_argument("--keyword", help="keep if title/tags contain this (comma = OR)")
    parser.add_argument("--author", help="keep if author name contains this")
    return parser.parse_args(argv)


def cli_filters(args: argparse.Namespace) -> dict:
    cats = [x.lstrip("#") for x in split_csv(args.category)]
    return {
        "categories": cats or None,
        "exclude": [x.lstrip("#") for x in split_csv(args.exclude)] or None,
        "tags": [x.lstrip("#") for x in split_csv(args.tag)] or None,
        "orient": args.orient,
        "min_duration": (args.min_minutes * 60) if args.min_minutes else None,
        "max_duration": (args.max_minutes * 60) if args.max_minutes else None,
        "keyword": args.keyword,
        "author": args.author,
    }


def filters_requested(filt: dict) -> bool:
    return any(
        [
            filt.get("categories"),
            filt.get("exclude"),
            filt.get("tags"),
            filt.get("orient"),
            filt.get("min_duration") is not None,
            filt.get("max_duration") is not None,
            filt.get("keyword"),
            filt.get("author"),
        ]
    )


def resolve_count(kind: str, count: int | None) -> int:
    if count is not None:
        return max(0, int(count))
    if kind in {
        "user",
        "like",
        "following",
        "followers",
        "follow_feed",
        "hashtag",
        "related",
    }:
        return 0
    return 100


def count_label(count: int) -> str:
    return "all" if count <= 0 else str(count)


def _safe_id(value: str) -> str:
    text = re.sub(r"[^\w.-]+", "_", str(value or "unknown")).strip("._")
    return (text or "unknown")[:80]


def work_dir_for(info: dict) -> Path:
    cwd = Path.cwd()
    kind = info.get("kind")
    if kind == "feed":
        return cwd / "recommend"
    if kind == "user":
        return cwd / "users" / _safe_id(info.get("id") or "user")
    if kind == "like":
        return cwd / "likes" / _safe_id(info.get("id") or "self")
    if kind == "following":
        return cwd / "following" / _safe_id(info.get("id") or "self")
    if kind == "followers":
        return cwd / "followers" / _safe_id(info.get("id") or "self")
    if kind == "follow_feed":
        return cwd / "follow-feed"
    if kind == "hashtag":
        return cwd / "hashtag" / _safe_id(info.get("id") or "tag")
    if kind == "related":
        return cwd / "related" / _safe_id(info.get("id") or "video")
    if kind == "video":
        return cwd / "videos" / _safe_id(info.get("id") or "video")
    return cwd


def _user_from_url(raw: str, flag: str) -> dict[str, str]:
    kind = {"likes": "like", "following": "following", "followers": "followers"}.get(
        flag, flag
    )
    info = classify(raw)
    if info["kind"] == "feed":
        url = "https://www.douyin.com/user/self"
        if kind == "like":
            url += "?showTab=like"
        return {"kind": kind, "id": "self", "url": url}
    if info["kind"] == "video":
        die(f"--{flag} needs a user page URL, not a video")
    if info["kind"] in {"user", "like", "following", "followers"}:
        uid = info["id"]
        url = f"https://www.douyin.com/user/{uid}"
        if kind == "like":
            url += "?showTab=like"
        return {"kind": kind, "id": uid, "url": url}
    die(f"--{flag} needs a user page URL")
    return {"kind": kind, "id": "", "url": ""}


def resolve_target(args: argparse.Namespace) -> dict[str, str]:
    flags = [
        name
        for name, on in (
            ("likes", args.likes),
            ("following", args.following),
            ("followers", args.followers),
            ("related", args.related),
            ("follow-feed", args.follow_feed),
        )
        if on
    ]
    if len(flags) > 1:
        die("use only one of --likes / --following / --followers / --related / --follow-feed")
    raw = (args.url or "").strip()
    if args.follow_feed:
        return {
            "kind": "follow_feed",
            "id": "follow-feed",
            "url": "https://www.douyin.com/follow",
        }
    if args.related:
        if not raw:
            die("--related needs a video URL")
        info = classify(raw)
        if info["kind"] != "video":
            die("--related needs a /video/<id> URL")
        return {"kind": "related", "id": info["id"], "url": info["url"]}
    if args.followers:
        if not raw:
            return {
                "kind": "followers",
                "id": "self",
                "url": "https://www.douyin.com/user/self",
            }
        return _user_from_url(raw, "followers")
    if args.following:
        if not raw:
            return {
                "kind": "following",
                "id": "self",
                "url": "https://www.douyin.com/user/self",
            }
        return _user_from_url(raw, "following")
    if args.likes:
        if not raw:
            return {
                "kind": "like",
                "id": "self",
                "url": "https://www.douyin.com/user/self?showTab=like",
            }
        return _user_from_url(raw, "likes")
    if not raw:
        try:
            raw = input("URL: ").strip()
        except EOFError:
            raw = ""
    if not raw:
        die("need a douyin url")
    return classify(raw)


def _write_author(data: dict, work: Path) -> None:
    author = data.get("author")
    if not author:
        return
    path = work / "author.json"
    path.write_text(json.dumps(author, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"author: {author.get('nickname') or '-'}  {author.get('url') or ''}", flush=True)
    print(f"saved: {path}", flush=True)


def handle_users(data: dict, args: argparse.Namespace, work: Path) -> int:
    work.mkdir(parents=True, exist_ok=True)
    items = data.get("items") or []
    data = dict(data)
    data["count"] = len(items)
    kind = data.get("kind") or "following"
    path = work / ("followers.json" if kind == "followers" else "following.json")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"logged_in: {data.get('logged_in')}", flush=True)
    print(f"count: {len(items)}", flush=True)
    _write_author(data, work)
    for i, item in enumerate(items, 1):
        nick = item.get("nickname") or "-"
        unique = item.get("unique_id") or ""
        extra = f"  @{unique}" if unique else ""
        fans = item.get("follower_count")
        fans_s = f"  fans={fans}" if fans is not None else ""
        print(f"  {i:3d}. {nick}{extra}{fans_s}  {item.get('url')}", flush=True)
    print(f"saved: {path}", flush=True)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    print("[2/3] skip download (user list, not videos)", flush=True)
    print("[3/3] done", flush=True)
    return 0


def handle_feed(data: dict, args: argparse.Namespace, work: Path) -> int:
    data["items"] = classify_items(data.get("items") or [])
    data["count"] = len(data["items"])
    work.mkdir(parents=True, exist_ok=True)
    (work / "feed.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"logged_in: {data.get('logged_in')}", flush=True)
    _write_author(data, work)
    print_item_list(data["items"])
    print_tag_analysis(data["items"], work)
    print_category_stats(data["items"])
    filt = cli_filters(args)
    items = data["items"]
    if filters_requested(filt):
        before = len(items)
        items = apply_filters(items, **filt)
        print(f"filter: {before} -> {len(items)}", flush=True)
        if items:
            print_item_list(items)
            print_tag_analysis(items)
            print_category_stats(items)
    elif not args.info:
        picked = prompt_categories(items, args.yes, already_filtered=False)
        if picked is None:
            print("cancelled")
            return 0
        items = picked
        if len(items) != data["count"]:
            print_item_list(items)
    (work / "feed.selected.json").write_text(
        json.dumps(
            {"kind": "feed-selected", "count": len(items), "items": items},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if args.json and args.info:
        print(json.dumps({"count": len(items), "items": items}, ensure_ascii=False, indent=2))
        return 0
    if args.info:
        print("[2/3] skip download (--info)", flush=True)
        print("[3/3] skip", flush=True)
        print(f"saved: {work / 'feed.json'}")
        return 0
    if args.limit and args.limit > 0:
        items = items[: args.limit]
    if not items:
        print("no videos after filter")
        return 0
    if not confirm_download(items, args.yes):
        print("cancelled")
        return 0
    print(f"[2/3] parallel download {len(items)} videos (curl --parallel)", flush=True)
    saved = download_parallel(items, work, workers=max(1, args.workers))
    print("[3/3] done", flush=True)
    print("========== done ==========")
    print(f"dir: {work}")
    for path in saved:
        print(f"video: {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.from_feed:
        path = Path(args.from_feed).expanduser()
        if not path.is_file():
            die(f"feed file not found: {path}")
        print(f"[1/3] load {path}", flush=True)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not data.get("items"):
            die("feed file has no items")
        work = path.parent
        if (data.get("kind") or "") in {"following", "followers"}:
            return handle_users(data, args, work)
        return handle_feed(data, args, work)

    info = resolve_target(args)
    work = work_dir_for(info)
    print(f"kind: {info['kind']}", flush=True)
    print(f"url: {info['url']}", flush=True)

    cookie_path = Path(args.cookies).expanduser() if args.cookies else default_cookie_path()
    if cookie_path:
        set_cookie_file(cookie_path)
        print(f"cookies: {cookie_path}", flush=True)

    want = resolve_count(info["kind"], args.count)
    login_kinds = {
        "user",
        "like",
        "following",
        "followers",
        "follow_feed",
        "hashtag",
        "related",
        "video",
    }
    if info["kind"] in login_kinds and args.guest:
        die(f"{info['kind']} needs login cookies; do not use --guest")

    if info["kind"] in login_kinds - {"video"}:
        if not cookie_path:
            die(cookie_help())
        if info["kind"] == "following":
            print(
                f"[1/3] parse {count_label(want)} following users (cookie + browser)",
                flush=True,
            )
            data = fetch_following(cookie_path, info["id"], want, headed=args.headed)
            return handle_users(data, args, work)
        if info["kind"] == "followers":
            print(
                f"[1/3] parse {count_label(want)} followers (cookie + browser)",
                flush=True,
            )
            data = fetch_followers(cookie_path, info["id"], want, headed=args.headed)
            return handle_users(data, args, work)
        if info["kind"] == "like":
            print(
                f"[1/3] parse {count_label(want)} liked videos (cookie + browser)",
                flush=True,
            )
            data = fetch_likes(cookie_path, info["id"], want, headed=args.headed)
            return handle_feed(data, args, work)
        if info["kind"] == "follow_feed":
            print(
                f"[1/3] parse {count_label(want)} follow-feed videos (cookie + browser)",
                flush=True,
            )
            data = fetch_follow_feed(cookie_path, want, headed=args.headed)
            return handle_feed(data, args, work)
        if info["kind"] == "hashtag":
            print(
                f"[1/3] parse {count_label(want)} hashtag videos (cookie + browser)",
                flush=True,
            )
            data = fetch_hashtag(cookie_path, info["id"], want, headed=args.headed)
            return handle_feed(data, args, work)
        if info["kind"] == "related":
            print(
                f"[1/3] parse {count_label(want)} related videos (cookie + browser)",
                flush=True,
            )
            data = fetch_video_page(
                cookie_path, info["id"], related=True, count=want, headed=args.headed
            )
            return handle_feed(data, args, work)
        if info["kind"] == "user":
            print(
                f"[1/3] parse {count_label(want)} user posts (cookie + browser)",
                flush=True,
            )
            data = fetch_user_posts(cookie_path, info["id"], want, headed=args.headed)
            return handle_feed(data, args, work)

    if info["kind"] == "feed":
        if args.guest:
            print(f"[1/3] parse {count_label(want)} guest recommend videos", flush=True)
            data = fetch_feed(want or 100)
            data["logged_in"] = False
        else:
            if not cookie_path:
                die(cookie_help())
            print(
                f"[1/3] parse {count_label(want)} logged-in recommend videos (cookie + browser)",
                flush=True,
            )
            data = fetch_logged_in_feed(cookie_path, want or 100, headed=args.headed)
        return handle_feed(data, args, work)

    print("[1/3] parse video detail (cookie + browser)", flush=True)
    if cookie_path:
        bundle = fetch_video_page(
            cookie_path, info["id"], related=False, headed=args.headed
        )
        item = bundle.get("detail") or (bundle.get("items") or [{}])[0]
        work.mkdir(parents=True, exist_ok=True)
        (work / "meta.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _write_author(bundle, work)
        extra = bundle.get("items") or []
        related_only = [x for x in extra if x.get("id") != item.get("id")]
        if related_only:
            (work / "related.json").write_text(
                json.dumps(
                    {"kind": "related", "count": len(related_only), "items": related_only},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"related captured: {len(related_only)} (use --related to parse all)", flush=True)
    else:
        item = fetch_video(info["id"])
        work = Path.cwd()
    print(f"id: {item.get('id')}", flush=True)
    print(f"title: {item.get('title')}", flush=True)
    best = item.get("best") or {}
    stats = item.get("statistics") or {}
    print(f"best: {best.get('width')}x{best.get('height')} {best.get('gear')}", flush=True)
    if stats.get("digg_count") is not None:
        print(
            f"stats: likes={stats.get('digg_count')} comments={stats.get('comment_count')} "
            f"collect={stats.get('collect_count')} play={stats.get('play_count')}",
            flush=True,
        )
    if args.info:
        if args.json:
            print(json.dumps(item, ensure_ascii=False, indent=2))
        print("[2/3] skip download (--info)")
        return 0
    print("[2/3] download highest resolution", flush=True)
    mp4 = download_item(item, work)
    print("[3/3] done", flush=True)
    print("========== done ==========")
    print(f"video: {mp4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
