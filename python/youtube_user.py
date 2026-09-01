# -*- coding: utf-8 -*-
"""List every public upload of a YouTube user/channel (videos + shorts + streams).

Saves channel About, subscriber count, avatar, and (by default) each video's
full description, tags, like count, and real upload date. Does not download
media. Use youtube_run.py --channel HANDLE --download for that.

  python youtube_user.py @OutdoorBoys
  python youtube_user.py OutdoorBoys --tab shorts --limit 20
  python youtube_user.py UCxxxxxx --playlists --no-enrich
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from youtube_parse import (
    CHANNEL_LIST_TABS,
    extract_user_catalog,
    parse_target,
    save_item,
    safe_dirname,
)


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _csv_cell(entry: dict, key: str) -> str:
    value = entry.get(key)
    if value is None:
        return ""
    if key == "tags" and isinstance(value, list):
        return ", ".join(str(part) for part in value)
    if key == "description":
        return str(value).replace("\r\n", "\n").strip()
    return str(value)


def write_csv(entries: list[dict], dest: Path) -> Path:
    fields = [
        "tab",
        "media_type",
        "id",
        "duration_string",
        "upload_date",
        "view_count",
        "like_count",
        "comment_count",
        "tags",
        "title",
        "url",
        "description",
    ]
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for entry in entries:
            writer.writerow({key: _csv_cell(entry, key) for key in fields})
    return dest


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List all public works of a YouTube user/channel (no media download)."
    )
    parser.add_argument(
        "channel",
        nargs="?",
        help="@handle, channel id (UC...), or channel URL (PowerShell-safe without @)",
    )
    parser.add_argument(
        "--tab",
        default="all",
        choices=tuple(CHANNEL_LIST_TABS),
        help="all = videos+shorts+streams (default)",
    )
    parser.add_argument("--limit", type=int, default=0, help="max entries per tab (0 = all)")
    parser.add_argument(
        "--playlists",
        action="store_true",
        help="also list playlists created by the channel",
    )
    parser.add_argument(
        "--community",
        action="store_true",
        help="also try community / posts tab",
    )
    parser.add_argument(
        "--no-enrich",
        action="store_true",
        help="skip per-video full description / tags / likes / real upload date",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=6,
        help="parallel yt-dlp metadata workers (default 6; unused if Data API key is set)",
    )
    parser.add_argument("--json", action="store_true", help="print catalog JSON to stdout")
    parser.add_argument("--out", metavar="DIR", help="output directory (default: cwd/<channel_id>)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    raw = (args.channel or "").strip()
    if not raw:
        try:
            raw = input("用户/频道 [@handle 或 UC id]: ").strip()
        except EOFError:
            raw = ""
    if not raw:
        die("need a channel @handle or UC id")
    target = parse_target(raw, as_channel=True)
    if target.kind != "channel":
        die("not a channel; pass @handle or UC id (use youtube_run.py for a single video)")
    extras: list[str] = []
    if args.playlists:
        extras.append("playlists")
    if args.community:
        extras.append("community")
    limit = args.limit if args.limit and args.limit > 0 else None
    print(f"user: {target.handle or target.channel_id or raw}", flush=True)
    print(f"url: {target.url}", flush=True)
    item = extract_user_catalog(
        raw,
        tab=args.tab,
        limit=limit,
        extras=tuple(extras),
        enrich=not args.no_enrich,
        workers=args.workers if args.workers and args.workers > 0 else 6,
    )
    work = Path(args.out).expanduser() if args.out else Path.cwd() / safe_dirname(item)
    paths = save_item(item, work)
    csv_path = write_csv(item.get("entries") or [], work / "works.csv")
    extras_blob = item.get("extras") or {}
    extra_files: list[str] = []
    for name, payload in extras_blob.items():
        if not isinstance(payload, dict):
            continue
        out = work / f"{name}.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        extra_files.append(str(out))
    print(f"channel: {item.get('channel') or item.get('uploader')}", flush=True)
    print(f"channel_id: {item.get('channel_id')}", flush=True)
    if item.get("channel_follower_count") is not None:
        print(f"subscribers: {item.get('channel_follower_count')}", flush=True)
    about = item.get("about") if isinstance(item.get("about"), dict) else {}
    desc = str((about or {}).get("description") or item.get("description") or "").strip()
    if desc:
        snippet = desc.splitlines()[0][:160]
        print(f"about: {snippet}", flush=True)
    if paths.get("avatar"):
        print(f"avatar: {paths['avatar']}", flush=True)
    elif item.get("avatar_url"):
        print(f"avatar: {item.get('avatar_url')}", flush=True)
    print(f"entries: {item.get('entry_count')}", flush=True)
    for entry in (item.get("entries") or [])[:3]:
        likes = entry.get("like_count")
        date = entry.get("upload_date") or "-"
        tags = entry.get("tags") or []
        tag_s = ",".join(str(t) for t in tags[:4])
        desc_len = len(str(entry.get("description") or ""))
        print(
            f"  {entry.get('id')}  {date}  likes={likes}  tags={tag_s or '-'}  desc={desc_len}c  {entry.get('title')}",
            flush=True,
        )
    fetched = item.get("tab_fetched_counts") or {}
    if fetched:
        print(
            "tabs: "
            + ", ".join(f"{name} {fetched.get(name, 0)}" for name in ("videos", "shorts", "streams") if name in fetched),
            flush=True,
        )
    print(f"dir: {work}", flush=True)
    print(f"meta: {paths.get('meta')}", flush=True)
    if paths.get("videos"):
        print(f"json: {paths['videos']}", flush=True)
    if paths.get("txt"):
        print(f"txt: {paths['txt']}", flush=True)
    print(f"csv: {csv_path}", flush=True)
    if paths.get("about"):
        print(f"about_json: {paths['about']}", flush=True)
    if paths.get("about_txt"):
        print(f"about_txt: {paths['about_txt']}", flush=True)
    if paths.get("banner"):
        print(f"banner: {paths['banner']}", flush=True)
    enrich = item.get("enrich") or {}
    if enrich:
        print(
            f"enrich: {enrich.get('ok')}/{enrich.get('wanted')} via {enrich.get('source')}",
            flush=True,
        )
    for path in extra_files:
        print(f"extra: {path}", flush=True)
    if args.json:
        print(json.dumps(item, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
