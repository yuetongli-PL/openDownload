# -*- coding: utf-8 -*-
"""从 YouTube 点播提取 HLS / m3u8（web_safari 客户端）。

用法:
  python youtube_hls.py https://www.youtube.com/watch?v=zawGTDLtWFY
  python youtube_hls.py zawGTDLtWFY --save
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yt_dlp

from youtube_parse import VIDEO_KINDS, die, parse_target, ytdlp_base_opts


def _collect_hls(info: dict) -> list[dict]:
    playlists = []
    for fmt in info.get("formats") or []:
        proto = fmt.get("protocol") or ""
        u = fmt.get("url") or ""
        if "m3u8" not in proto and "m3u8" not in u.lower():
            continue
        expire = None
        if "/expire/" in u:
            try:
                expire = int(u.split("/expire/", 1)[1].split("/", 1)[0])
            except ValueError:
                expire = None
        playlists.append(
            {
                "id": fmt.get("format_id"),
                "resolution": fmt.get("resolution"),
                "fps": fmt.get("fps"),
                "vcodec": fmt.get("vcodec"),
                "acodec": fmt.get("acodec"),
                "protocol": proto,
                "url": u,
                "expire": expire,
                "expire_utc": (
                    datetime.fromtimestamp(expire, tz=timezone.utc).strftime(
                        "%Y-%m-%d %H:%M:%S UTC"
                    )
                    if expire
                    else None
                ),
            }
        )
    return playlists


def extract_hls(url: str, ffmpeg: str | None = None) -> dict:
    client_sets = [
        ["web_safari"],
        ["web_safari", "ios", "mweb"],
        ["ios", "mweb"],
        ["mweb", "web_safari"],
    ]
    info = None
    playlists: list[dict] = []
    used: list[str] = []
    last_err: Exception | None = None
    for clients in client_sets:
        opts = ytdlp_base_opts(ffmpeg)
        opts.update(
            {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "format": "all",
                "extractor_args": {"youtube": {"player_client": clients}},
            }
        )
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:  # noqa: BLE001 - retry other clients
            last_err = exc
            continue
        playlists = _collect_hls(info or {})
        if playlists:
            used = clients
            break
    if not info:
        die(f"failed to extract YouTube info ({last_err})")
    if not playlists:
        die(
            "no HLS/m3u8 (YouTube VOD usually uses DASH; HLS only appears on "
            "web_safari/ios clients and may be missing this session)"
        )
    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "url": info.get("webpage_url") or url,
        "client": used,
        "hls": playlists,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract YouTube HLS/m3u8 playlists.")
    parser.add_argument("url", nargs="?", help="YouTube URL or video id")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--save",
        nargs="?",
        const=".",
        metavar="DIR",
        help="write hls.txt (default: cwd/<id>/hls.txt)",
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
    target = parse_target(raw)
    if target.kind not in VIDEO_KINDS:
        die("HLS extract needs a single video url")
    data = extract_hls(target.url)
    if args.save is not None:
        root = Path(args.save).expanduser()
        if args.save in {".", ""}:
            root = Path.cwd() / str(data["id"])
        root.mkdir(parents=True, exist_ok=True)
        dest = root / "hls.txt"
        lines = [
            f"# {data['id']}  {data.get('title')}",
            f"# {data.get('url')}",
        ]
        for item in data["hls"]:
            lines.append("")
            lines.append(
                f"# itag {item['id']}  {item.get('resolution')}  "
                f"{item.get('vcodec')} + {item.get('acodec')}  expire {item.get('expire_utc')}"
            )
            lines.append(item["url"])
        dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        data["saved"] = str(dest)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print(f"id: {data['id']}")
    print(f"title: {data.get('title')}")
    print(f"client: {', '.join(data.get('client') or [])}")
    print(f"hls_count: {len(data['hls'])}")
    for item in data["hls"]:
        print(
            f"{item['id']:>4}  {item.get('resolution') or '-':>10}  "
            f"{item.get('vcodec')}+{item.get('acodec')}  expire {item.get('expire_utc')}"
        )
        print(item["url"])
        print()
    if data.get("saved"):
        print(f"saved: {data['saved']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
