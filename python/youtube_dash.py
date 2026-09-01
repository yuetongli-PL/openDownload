# -*- coding: utf-8 -*-
"""解析 YouTube DASH 最高分辨率音视频轨。

用法:
  python youtube_dash.py https://www.youtube.com/watch?v=zawGTDLtWFY
  python youtube_dash.py zawGTDLtWFY --save
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from youtube_parse import VIDEO_KINDS, die, extract_info, pick_dash_best


def write_dash_txt(item: dict, dest: Path) -> None:
    dash = item.get("dash") or {}
    video = dash.get("video") or {}
    audio = dash.get("audio") or {}
    lines = [
        f"# {item.get('id')}  {item.get('title')}",
        f"# {item.get('url')}",
        f"# DASH {dash.get('format')}  {dash.get('resolution')}",
        "",
        f"# video  itag {video.get('id')}  {video.get('resolution')}  {video.get('ext')}  {video.get('vcodec')}",
        video.get("url") or "",
        "",
        f"# audio  itag {audio.get('id')}  {audio.get('ext')}  {audio.get('acodec')}",
        audio.get("url") or "",
        "",
    ]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract highest-resolution YouTube DASH tracks.")
    parser.add_argument("url", nargs="?", help="YouTube URL or video id")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--save",
        nargs="?",
        const=".",
        metavar="DIR",
        help="write dash.txt (default: cwd/<id>/dash.txt)",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    raw = args.url
    if not raw:
        try:
            raw = input("url: ").strip()
        except EOFError:
            raw = ""
    if not raw:
        die("need a YouTube url or video id")
    item = extract_info(raw)
    if item.get("kind") not in VIDEO_KINDS:
        die("DASH extract needs a single video url")
    if not item.get("dash"):
        formats = item.get("formats") or []
        item["dash"] = pick_dash_best(formats)
    if not item.get("dash"):
        die("no DASH video+audio tracks")

    if args.save is not None:
        root = Path(args.save).expanduser()
        if args.save in {".", ""}:
            root = Path.cwd() / str(item["id"])
        dest = root / "dash.txt"
        write_dash_txt(item, dest)
        item["saved"] = str(dest)

    if args.json:
        payload = {
            "id": item.get("id"),
            "title": item.get("title"),
            "url": item.get("url"),
            "dash": item.get("dash"),
            "saved": item.get("saved"),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    dash = item["dash"]
    video = dash["video"]
    audio = dash["audio"]
    print(f"id: {item.get('id')}")
    print(f"title: {item.get('title')}")
    print(f"dash: {dash.get('format')}  {dash.get('resolution')}")
    print(f"video_id: {video.get('id')}")
    print(f"video: {video.get('url')}")
    print(f"audio_id: {audio.get('id')}")
    print(f"audio: {audio.get('url')}")
    if item.get("saved"):
        print(f"saved: {item['saved']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
