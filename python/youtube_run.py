# -*- coding: utf-8 -*-
"""由 youtube.bat 调用：解析 YouTube 并下载合并为 mp4，保存到当前工作目录。"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import yt_dlp

from yt_dlp.utils import DownloadError

from youtube_dash import write_dash_txt
from youtube_parse import (
    LIST_KINDS,
    VIDEO_KINDS,
    detect_source_lang,
    embed_subtitles_mp4,
    extract_info,
    parse_sub_langs,
    parse_target,
    relayout_dir,
    save_item,
    safe_dirname,
    source_lang_name,
    sub_langs_for_source,
    write_subtitles,
    ytdlp_base_opts,
)


QUALITY_HEIGHT = {
    "1": 1080,
    "1080": 1080,
    "1080p": 1080,
    "fhd": 1080,
    "2": 1440,
    "2k": 1440,
    "1440": 1440,
    "1440p": 1440,
    "qhd": 1440,
    "3": 2160,
    "4k": 2160,
    "2160": 2160,
    "2160p": 2160,
    "uhd": 2160,
}

QUALITY_LABEL = {1080: "1080p", 1440: "2K (1440p)", 2160: "4K (2160p)"}


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def parse_quality(text: str | None) -> int | None:
    if text is None:
        return None
    key = str(text).strip().lower().replace(" ", "")
    return QUALITY_HEIGHT.get(key)


def quality_arg(text: str) -> int:
    height = parse_quality(text)
    if height is None:
        raise argparse.ArgumentTypeError("use 1080p, 2k, or 4k")
    return height


def prompt_download_height(*, available: str = "") -> int:
    print("分辨率:", flush=True)
    print("  1) 1080p", flush=True)
    print("  2) 2K  (1440p)", flush=True)
    print("  3) 4K  (2160p)", flush=True)
    if available:
        print(f"片源最高: {available}", flush=True)
    try:
        raw = input("请选择 [1/2/3，默认 1080p]: ").strip()
    except EOFError:
        raw = ""
    height = parse_quality(raw) if raw else 1080
    if height is None:
        print("warning: 无效选择，使用 1080p", file=sys.stderr, flush=True)
        return 1080
    return height


def ensure_download_height(args: argparse.Namespace, *, available: str = "") -> None:
    """Set args.height for a video download. Interactive unless already specified."""
    if args.audio or args.format:
        return
    if args.height:
        return
    quality = getattr(args, "quality", None)
    if quality:
        args.height = int(quality)
        return
    if sys.stdin.isatty():
        args.height = prompt_download_height(available=available)
        return
    args.height = 1080


def find_ffmpeg() -> Path | None:
    for name in ("ffmpeg", "ffmpeg.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    roots: list[Path] = []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        winget = Path(local) / "Microsoft" / "WinGet"
        roots.append(winget / "Links" / "ffmpeg.exe")
        pkgs = winget / "Packages"
        if pkgs.is_dir():
            roots.extend(sorted(pkgs.glob("*FFmpeg*")))
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    roots.append(Path(pf) / "ffmpeg" / "bin" / "ffmpeg.exe")
    roots.append(Path(r"C:\ffmpeg\bin\ffmpeg.exe"))
    hits: list[Path] = []
    for root in roots:
        if root.is_file() and root.name.lower() == "ffmpeg.exe":
            hits.append(root)
            continue
        if root.is_dir():
            hits.extend(root.rglob("ffmpeg.exe"))
    if not hits:
        return None
    hits.sort(key=lambda p: (0 if "full" in str(p).lower() else 1, len(str(p))))
    return hits[0]


def build_format(args: argparse.Namespace, dash: dict | None = None) -> str:
    if args.format:
        return args.format
    if args.audio:
        return "ba[ext=m4a]/bestaudio/best"
    height = args.height
    if height:
        return (
            f"bv*[height<={height}]+ba/"
            f"bestvideo[height<={height}]+bestaudio/"
            f"b[height<={height}]/b"
        )
    pair = (dash or {}).get("format")
    if pair:
        return f"{pair}/bv*+ba/b"
    return "bv*+ba/bestvideo+bestaudio/b"


def download(
    url: str,
    work: Path,
    fmt: str,
    ffmpeg: Path | None,
    audio: bool,
    *,
    subs: bool = True,
    sub_langs: list[str] | None = None,
    auto_subs: bool = True,
    embed_subs: bool = True,
    hardsub: bool = False,
    use_grok: bool = True,
    audio_align: bool = False,
    grok_voice: bool = True,
    item: dict | None = None,
    source_lang: str = "auto",
) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    ffmpeg_loc = str(ffmpeg.parent if ffmpeg and ffmpeg.is_file() else ffmpeg) if ffmpeg else None
    opts = ytdlp_base_opts(ffmpeg_loc, skip_translated_subs=True)
    opts.update(
        {
            "format": fmt,
            "outtmpl": str(work / "%(id)s.%(ext)s"),
            "writethumbnail": True,
            "writeinfojson": True,
            "concurrent_fragment_downloads": 8,
            "noprogress": False,
            "continuedl": True,
            "overwrites": False,
        }
    )
    if audio:
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "0"}
        ]
    else:
        opts["merge_output_format"] = "mp4"
        opts["postprocessors"] = [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}]
    print(f"format: {fmt}", flush=True)
    print(f"ffmpeg: {opts.get('ffmpeg_location') or '(none)'}", flush=True)
    print(f"js runtimes: {', '.join(opts.get('js_runtimes', {}) or ['(none)'])}", flush=True)
    if not opts.get("js_runtimes"):
        print(
            "warning: no JS runtime (install Node.js or Deno). YouTube 403 is likely.",
            file=sys.stderr,
            flush=True,
        )

    def clear_incomplete() -> None:
        for pat in ("*.part", "*.f*.mp4", "*.f*.m4a", "*.f*.webm"):
            for path in work.glob(pat):
                try:
                    path.unlink()
                    print(f"removed incomplete: {path.name}", flush=True)
                except OSError:
                    pass

    fallbacks = [fmt]
    if not audio:
        for extra in (
            "bv*+ba/bestvideo+bestaudio/b",
            "401+140/400+140/399+140/137+140/18/bv*+ba",
            "bv*[height<=1080]+ba/137+140/18/b",
        ):
            if extra not in fallbacks:
                fallbacks.append(extra)

    last_err: Exception | None = None
    for i, selector in enumerate(fallbacks):
        opts["format"] = selector
        if i:
            print(f"retry format after 403: {selector}", flush=True)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            last_err = None
            break
        except DownloadError as exc:
            last_err = exc
            msg = str(exc)
            if "403" not in msg and "Forbidden" not in msg:
                die(msg)
            print(f"warning: {msg}", file=sys.stderr, flush=True)
            clear_incomplete()
    if last_err:
        die(
            "YouTube HTTP 403: DASH URL rejected. "
            "Delete incomplete .f401.mp4/.part and retry, or use --quality 1080p."
        )

    videos = (
        sorted(work.glob("*.mp4"))
        + sorted(work.glob("*.m4a"))
        + sorted(work.glob("*.mkv"))
        + sorted(work.glob("*.webm"))
    )
    videos = [p for p in videos if p.is_file() and p.stat().st_size > 0 and ".f" not in p.stem]
    if not videos:
        videos = [
            p
            for p in work.glob("*")
            if p.is_file()
            and p.suffix.lower() in {".mp4", ".m4a", ".mkv", ".webm"}
            and p.stat().st_size > 1024
        ]
    if not videos:
        die(f"download finished but no media in {work}")
    media = max(videos, key=lambda p: p.stat().st_size)
    if subs:
        print("[subs] after video (failure here does not undo the mp4)", flush=True)
        lang = detect_source_lang(item, explicit=source_lang)
        langs = sub_langs if sub_langs is not None else sub_langs_for_source(lang)
        print(f"subs: source language {lang} ({source_lang_name(lang)})", flush=True)
        write_subtitles(
            url,
            work,
            langs=langs,
            auto=auto_subs,
            ffmpeg=ffmpeg_loc,
            item=item,
        )
        if embed_subs and not audio and ffmpeg:
            vid = (item or {}).get("id") or media.stem
            embed_subtitles_mp4(
                media,
                work,
                str(vid),
                ffmpeg,
                duration=(item or {}).get("duration") if isinstance((item or {}).get("duration"), (int, float)) else None,
                hardsub=hardsub,
                title=str((item or {}).get("title") or ""),
                use_grok=use_grok,
                audio_align=audio_align,
                grok_voice=grok_voice,
                source_lang=source_lang,
                item=item,
            )
    return media


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse and download a YouTube video, or list a channel/playlist."
    )
    parser.add_argument("url", nargs="?", help="YouTube URL, video id, UC id, or @handle")
    parser.add_argument("--info", action="store_true", help="parse only, do not download")
    parser.add_argument("--json", action="store_true", help="print parse JSON")
    parser.add_argument("--audio", action="store_true", help="audio only (m4a)")
    parser.add_argument("--height", type=int, default=0, help="max video height, e.g. 1080")
    parser.add_argument(
        "--quality",
        type=quality_arg,
        metavar="1080p|2k|4k",
        help="download cap: 1080p, 2k (1440p), or 4k (2160p); skips the interactive menu",
    )
    parser.add_argument("-f", "--format", help="raw yt-dlp format selector")
    parser.add_argument("--playlist", action="store_true", help="treat watch?list= as a playlist")
    parser.add_argument(
        "--channel",
        action="store_true",
        help="treat the argument as @handle or channel id (PowerShell-safe)",
    )
    parser.add_argument(
        "--tab",
        choices=("all", "videos", "shorts", "streams"),
        help="channel tab (default: all uploads for a channel root)",
    )
    parser.add_argument("--limit", type=int, default=0, help="max entries for channel/playlist")
    parser.add_argument(
        "--download",
        action="store_true",
        help="also download listed channel/playlist videos (off by default)",
    )
    parser.add_argument(
        "--subs",
        dest="subs",
        action="store_true",
        default=True,
        help="download WebVTT subtitles (default on for a single video)",
    )
    parser.add_argument(
        "--no-subs",
        dest="subs",
        action="store_false",
        help="do not download subtitles",
    )
    parser.add_argument(
        "--lang",
        "--source-lang",
        dest="source_lang",
        default="auto",
        help="spoken language: auto (default), en, ja, ko, es, fr, de, pt, ru, ...",
    )
    parser.add_argument(
        "--sub-langs",
        default="",
        help="YouTube VTT langs (default: source lang + orig; Chinese comes from Grok)",
    )
    parser.add_argument(
        "--no-auto-subs",
        action="store_true",
        help="only official captions, skip YouTube ASR / translations",
    )
    parser.add_argument(
        "--embed-subs",
        dest="embed_subs",
        action="store_true",
        default=True,
        help="mux 中文+原文 VTT into the mp4 (default on)",
    )
    parser.add_argument(
        "--no-embed-subs",
        dest="embed_subs",
        action="store_false",
        help="keep sidecar .vtt only, do not mux into mp4",
    )
    parser.add_argument(
        "--hardsub",
        action="store_true",
        help="burn ASS 中上原文下 into the picture (re-encodes video, 字幕组压制)",
    )
    parser.add_argument(
        "--relayout",
        metavar="DIR",
        help="re-align/translate/embed subs for an existing download folder",
    )
    parser.add_argument(
        "--no-grok-zh",
        action="store_true",
        help="do not call grok CLI for Chinese 对轴/翻译优化",
    )
    parser.add_argument(
        "--force-grok-zh",
        action="store_true",
        help="with --no-grok-voice --relayout, rebuild Chinese from YouTube VTT instead of reusing zh-en.srt",
    )
    parser.add_argument(
        "--audio-align",
        action="store_true",
        help="optional Whisper forced-align of source-language times to spoken audio",
    )
    parser.add_argument(
        "--grok-voice",
        dest="grok_voice",
        action="store_true",
        default=True,
        help="demux audio, Grok STT is the bilingual clock+source text (default on)",
    )
    parser.add_argument(
        "--no-grok-voice",
        dest="grok_voice",
        action="store_false",
        help="do not send demuxed audio to Grok Speech-to-Text",
    )
    return parser.parse_args(argv)


def _print_list_header(item: dict) -> None:
    print(f"kind: {item.get('kind')}", flush=True)
    print(f"id: {item.get('id')}", flush=True)
    print(f"title: {item.get('title')}", flush=True)
    print(f"uploader: {item.get('uploader')}", flush=True)
    if item.get("channel_id"):
        print(f"channel_id: {item.get('channel_id')}", flush=True)
    if item.get("channel_follower_count") is not None:
        print(f"subscribers: {item.get('channel_follower_count')}", flush=True)
    counts = item.get("tab_counts") or {}
    print(f"entries: {item.get('entry_count')}", flush=True)
    if counts:
        print(
            "tabs: "
            + ", ".join(
                f"{name} {counts.get(name, 0)}"
                for name in ("videos", "shorts", "streams")
                if counts.get(name)
            ),
            flush=True,
        )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    ffmpeg = find_ffmpeg()
    if args.relayout:
        dest = Path(args.relayout).expanduser()
        print(f"relayout: {dest}", flush=True)
        result = relayout_dir(
            dest,
            ffmpeg,
            hardsub=args.hardsub,
            use_grok=(
                not args.no_grok_zh
                if args.grok_voice
                else args.force_grok_zh and not args.no_grok_zh
            ),
            audio_align=args.audio_align,
            grok_voice=args.grok_voice,
            source_lang=args.source_lang,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else f"done: {result}")
        return 0 if result.get("ok") else 1
    raw = args.url
    if not raw:
        try:
            raw = input("URL: ").strip()
        except EOFError:
            raw = ""
    if not raw:
        die("need a YouTube url, video id, or @handle")

    target = parse_target(raw, as_playlist=args.playlist, as_channel=args.channel)
    limit = args.limit if args.limit and args.limit > 0 else None
    ffmpeg_loc = str(ffmpeg.parent) if ffmpeg else None
    sub_langs = parse_sub_langs(args.sub_langs) if str(args.sub_langs or "").strip() else None
    auto_subs = not args.no_auto_subs

    if target.kind in LIST_KINDS:
        print("[1/3] list uploads / playlist entries", flush=True)
        item = extract_info(
            raw,
            ffmpeg_loc,
            limit=limit,
            tab=args.tab,
            as_playlist=args.playlist,
            as_channel=args.channel,
        )
        work = Path.cwd() / safe_dirname(item)
        paths = save_item(item, work)
        _print_list_header(item)
        print(f"save dir: {work}", flush=True)
        if args.json:
            print(json.dumps(item, ensure_ascii=False, indent=2))
        if not args.download:
            print("[2/3] skip download (channel/playlist lists only; pass --download)", flush=True)
            print("[3/3] skip merge", flush=True)
            print("========== done ==========")
            print(f"dir: {work}")
            print(f"meta: {paths.get('meta')}")
            if paths.get("videos"):
                print(f"videos: {paths['videos']}")
            if paths.get("txt"):
                print(f"txt: {paths['txt']}")
            return 0
        if not ffmpeg:
            die("ffmpeg not found; install with: winget install Gyan.FFmpeg.Essentials")
        entries = item.get("entries") or []
        if not entries:
            die("no videos in list")
        ensure_download_height(args)
        if args.height:
            print(f"quality: {QUALITY_LABEL.get(args.height, args.height)}", flush=True)
        print(f"[2/3] download {len(entries)} videos", flush=True)
        fmt = build_format(args, None)
        failed = 0
        for i, entry in enumerate(entries, 1):
            vid = entry.get("id")
            url = entry.get("url")
            if not vid or not url:
                failed += 1
                continue
            print(f"----- {i}/{len(entries)} {vid}  {entry.get('title')}", flush=True)
            dest = work / str(vid)
            try:
                media = download(
                    url,
                    dest,
                    fmt,
                    ffmpeg,
                    args.audio,
                    subs=args.subs,
                    sub_langs=sub_langs,
                    auto_subs=auto_subs,
                    embed_subs=args.embed_subs,
                    hardsub=args.hardsub,
                    use_grok=not args.no_grok_zh,
                    audio_align=args.audio_align,
                    grok_voice=args.grok_voice,
                    source_lang=args.source_lang,
                )
            except SystemExit:
                failed += 1
                print(f"warning: skip {vid}", file=sys.stderr, flush=True)
                continue
            print(f"media: {media}", flush=True)
        print("[3/3] merge/remux via ffmpeg (handled by yt-dlp)", flush=True)
        print("========== done ==========")
        print(f"dir: {work}")
        print(f"downloaded: {len(entries) - failed}/{len(entries)}")
        print(f"meta: {paths.get('meta')}")
        return 0 if failed == 0 else 1

    print("[1/3] parse DASH (highest resolution)", flush=True)
    item = extract_info(
        raw,
        ffmpeg_loc,
        limit=limit,
        tab=args.tab,
        as_playlist=args.playlist,
        as_channel=args.channel,
    )
    if item.get("kind") not in VIDEO_KINDS:
        die(f"expected a video, got {item.get('kind')}")
    vid = item["id"]
    work = Path.cwd() / str(vid)
    paths = save_item(item, work)
    if item.get("dash"):
        write_dash_txt(item, work / "dash.txt")
    print(f"id: {vid}", flush=True)
    print(f"title: {item.get('title')}", flush=True)
    print(f"uploader: {item.get('uploader')}", flush=True)
    if item.get("view_count") is not None:
        print(f"views: {item.get('view_count')}", flush=True)
    dash = item.get("dash") or {}
    if dash:
        print(f"dash: {dash.get('format')}  {dash.get('resolution')}", flush=True)
    print(f"save dir: {work}", flush=True)

    if args.json:
        print(json.dumps(item, ensure_ascii=False, indent=2))
    if args.info:
        print(f"url: {item.get('url')}", flush=True)
        print(f"cover: {item.get('thumbnail')}", flush=True)
        if dash:
            print(f"dash_video: {(dash.get('video') or {}).get('url')}", flush=True)
            print(f"dash_audio: {(dash.get('audio') or {}).get('url')}", flush=True)
        if args.subs:
            print("[2/3] download subtitles only (--info)", flush=True)
            info_lang = detect_source_lang(item, explicit=args.source_lang)
            info_langs = sub_langs if sub_langs is not None else sub_langs_for_source(info_lang)
            print(f"subs: source language {info_lang} ({source_lang_name(info_lang)})", flush=True)
            sub_files = write_subtitles(
                target.url,
                work,
                langs=info_langs,
                auto=auto_subs,
                ffmpeg=ffmpeg_loc,
                item=item,
            )
            if sub_files:
                print(f"subs: {len(sub_files)}", flush=True)
                for path in sub_files:
                    print(f"  {path.name}", flush=True)
            else:
                print("subs: none", flush=True)
        else:
            print("[2/3] skip download (--info --no-subs)", flush=True)
        print("[3/3] skip merge", flush=True)
        print("========== done ==========")
        print(f"dir: {work}")
        print(f"meta: {paths.get('meta')}")
        print(f"dash: {work / 'dash.txt'}")
        return 0

    if not ffmpeg:
        die("ffmpeg not found; install with: winget install Gyan.FFmpeg.Essentials")
    ensure_download_height(args, available=str(dash.get("resolution") or ""))
    if args.height:
        print(f"quality: {QUALITY_LABEL.get(args.height, args.height)}", flush=True)
    fmt = build_format(args, dash)
    print("[2/3] download DASH with yt-dlp", flush=True)
    try:
        media = download(
            target.url,
            work,
            fmt,
            ffmpeg,
            args.audio,
            subs=args.subs,
            sub_langs=sub_langs,
            auto_subs=auto_subs,
            embed_subs=args.embed_subs,
            hardsub=args.hardsub,
            use_grok=not args.no_grok_zh,
            audio_align=args.audio_align,
            grok_voice=args.grok_voice,
            item=item,
            source_lang=args.source_lang,
        )
    except DownloadError as exc:
        die(str(exc))
    print("[3/3] merge/remux via ffmpeg (handled by yt-dlp)", flush=True)
    print(flush=True)
    print("========== done ==========")
    print(f"dir:   {work}")
    print(f"media: {media}")
    thumbs = list(work.glob("*.jpg")) + list(work.glob("*.webp")) + list(work.glob("*.png"))
    if thumbs:
        print(f"cover: {thumbs[0]}")
    print(f"meta:  {work / 'meta.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
