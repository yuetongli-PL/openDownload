# -*- coding: utf-8 -*-
"""解析 YouTube 链接：完整元数据、播放列表、频道全部作品。

用法:
  python youtube_parse.py https://www.youtube.com/watch?v=zawGTDLtWFY
  python youtube_parse.py zawGTDLtWFY --json
  python youtube_parse.py @3blue1brown --json
  python youtube_parse.py https://www.youtube.com/@3blue1brown --tab shorts --limit 20
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

import yt_dlp

SUB_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
UC_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
HANDLE_RE = re.compile(r"^@[^/\s?]+$")
YTSEARCH_RE = re.compile(r"^ytsearch\d*:", re.I)
PLAYLIST_ID_RE = re.compile(
    r"^(?:(?:PL|LL|EC|UU|FL|RD|UL|TL|PU|OLAK5uy_)[0-9A-Za-z_-]{10,}|RDMM|WL|LL|LM)$"
)

YOUTUBE_HOSTS = {
    "youtu.be",
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "youtubekids.com",
}

CHANNEL_TABS = {
    "videos",
    "shorts",
    "streams",
    "playlists",
    "community",
    "posts",
    "featured",
    "about",
    "podcasts",
    "releases",
    "live",
    "membership",
}

LIST_KINDS = {"channel", "playlist", "search"}
VIDEO_KINDS = {"video", "clip"}
# English VTT is only a fallback if Grok STT fails. Chinese is translated by Grok.
# Do not default-download zh.* — those 429 and are YouTube machine translations.
DEFAULT_SUB_LANGS = (
    "en",
    "en-orig",
)

# Grok STT formatting codes (transcription itself is multilingual).
STT_LANGS = {
    "ar",
    "cs",
    "da",
    "nl",
    "en",
    "fil",
    "fr",
    "de",
    "hi",
    "id",
    "it",
    "ja",
    "ko",
    "mk",
    "ms",
    "fa",
    "pl",
    "pt",
    "ro",
    "ru",
    "es",
    "sv",
    "th",
    "tr",
    "vi",
}
_LANG_ALIASES = {
    "jp": "ja",
    "jpn": "ja",
    "kr": "ko",
    "kor": "ko",
    "spa": "es",
    "ger": "de",
    "deu": "de",
    "fre": "fr",
    "fra": "fr",
    "chi": "zh",
    "zho": "zh",
    "cmn": "zh",
    "cn": "zh",
    "tl": "fil",
    "tgl": "fil",
    "in": "id",
    "iw": "he",
    "nb": "no",
}
_LANG_REGIONAL = {
    "es": ("es-US", "es-419", "es-MX", "es-ES"),
    "pt": ("pt-BR", "pt-PT"),
    "zh": ("zh-Hans", "zh-Hant", "zh-CN", "zh-TW", "zh-Hans-orig", "zh-Hant-orig"),
    "en": ("en-US", "en-GB"),
}
SOURCE_LANG_NAMES = {
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
    "es": "西班牙语",
    "fr": "法语",
    "de": "德语",
    "pt": "葡萄牙语",
    "ru": "俄语",
    "ar": "阿拉伯语",
    "hi": "印地语",
    "id": "印尼语",
    "it": "意大利语",
    "th": "泰语",
    "vi": "越南语",
    "tr": "土耳其语",
    "pl": "波兰语",
    "nl": "荷兰语",
    "sv": "瑞典语",
    "fil": "菲律宾语",
    "zh": "中文",
    "cs": "捷克语",
    "da": "丹麦语",
    "fa": "波斯语",
    "ms": "马来语",
    "ro": "罗马尼亚语",
    "mk": "马其顿语",
}
_BILINGUAL_SHORT = {
    "en": "英",
    "ja": "日",
    "ko": "韩",
    "es": "西",
    "fr": "法",
    "de": "德",
    "pt": "葡",
    "ru": "俄",
    "ar": "阿",
    "hi": "印",
    "id": "印尼",
    "it": "意",
    "th": "泰",
    "vi": "越",
    "tr": "土",
    "pl": "波",
    "nl": "荷",
    "sv": "瑞典",
    "fil": "菲",
    "zh": "中",
}
_NOSPACE_CHAR = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\u0e00-\u0e7f]")


def normalize_lang(code: str | None) -> str:
    raw = str(code or "").strip().lower().replace("_", "-")
    if raw.endswith("-orig"):
        raw = raw[:-5]
    if not raw or raw in {"auto", "und", "unknown"}:
        return ""
    base = raw.split("-", 1)[0]
    return _LANG_ALIASES.get(base, base)


def source_lang_name(code: str | None) -> str:
    lang = normalize_lang(code) or "en"
    return SOURCE_LANG_NAMES.get(lang, lang)


def bilingual_track_title(code: str | None) -> str:
    lang = normalize_lang(code) or "en"
    return f"简{_BILINGUAL_SHORT.get(lang, '外')}双语"


def source_caption_tags(lang: str | None) -> tuple[str, ...]:
    lang = normalize_lang(lang) or "en"
    tags = [f"{lang}-orig", lang, *(_LANG_REGIONAL.get(lang) or ())]
    if lang == "en":
        tags.extend(["en-US", "en-GB"])
    return tuple(dict.fromkeys(tags))


def sub_langs_for_source(lang: str | None) -> list[str]:
    lang = normalize_lang(lang) or "en"
    if lang == "en":
        return list(DEFAULT_SUB_LANGS)
    return [tag for tag in source_caption_tags(lang)]


def guess_lang_from_text(text: str | None) -> str:
    raw = text or ""
    if re.search(r"[\u3040-\u30ff]", raw):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", raw):
        return "ko"
    if re.search(r"[\u0e00-\u0e7f]", raw):
        return "th"
    if re.search(r"[\u0600-\u06ff]", raw):
        return "ar"
    if re.search(r"[\u0400-\u04ff]", raw):
        return "ru"
    if re.search(r"[\u0900-\u097f]", raw):
        return "hi"
    han = len(re.findall(r"[\u4e00-\u9fff]", raw))
    latin = len(re.findall(r"[A-Za-z]", raw))
    if han >= 8 and han > latin:
        return "zh"
    return ""


def detect_source_lang(
    item: dict[str, Any] | None = None,
    *,
    explicit: str | None = None,
    dest: Path | None = None,
    video_id: str | None = None,
) -> str:
    asked = normalize_lang(explicit)
    if asked:
        return asked
    blob = item or {}
    for key in ("language", "original_language"):
        found = normalize_lang(blob.get(key))
        if found:
            return found
    auto = blob.get("automatic_captions") or {}
    origs = [normalize_lang(k) for k in auto if str(k).endswith("-orig")]
    origs = [code for code in origs if code]
    if len(origs) == 1:
        return origs[0]
    for code in origs:
        if code != "zh":
            return code
    official = blob.get("subtitles") or {}
    for key in official:
        found = normalize_lang(key)
        if found and found != "zh":
            return found
    if dest is not None:
        vid = video_id or str(blob.get("id") or dest.name)
        files = {
            sub_lang_from_filename(path.name, vid): path
            for path in list_subtitle_files(dest, vid)
            if path.suffix.lower() == ".vtt"
        }
        orig_files = [normalize_lang(k) for k in files if str(k).endswith("-orig")]
        orig_files = [code for code in orig_files if code]
        if len(orig_files) == 1:
            return orig_files[0]
        for code in orig_files:
            if code != "zh":
                return code
        stt_cache = dest / f"{vid}.grok-stt.json"
        if stt_cache.is_file():
            try:
                payload = json.loads(stt_cache.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError):
                payload = {}
            found = normalize_lang((payload or {}).get("language"))
            if found:
                return found
            guessed = guess_lang_from_text(str((payload or {}).get("text") or ""))
            if guessed:
                return guessed
    return "en"


def join_spoken(parts: list[str] | tuple[str, ...]) -> str:
    out = ""
    for part in parts:
        piece = (part or "").strip()
        if not piece:
            continue
        if not out:
            out = piece
            continue
        if _NOSPACE_CHAR.search(out[-1]) and _NOSPACE_CHAR.search(piece[0]):
            out += piece
        else:
            out += " " + piece
    return re.sub(r"[ \t]+", " ", out).strip()


def refine_source_lang(hint: str | None, text: str | None) -> str:
    guessed = guess_lang_from_text(text)
    hinted = normalize_lang(hint)
    if guessed and hinted and guessed != hinted:
        if hinted == "en" or not hinted:
            return guessed
        if guessed == "zh" and hinted != "zh":
            return hinted
        return guessed
    return guessed or hinted or "en"

_COPY_VIDEO_KEYS = (
    "id",
    "display_id",
    "title",
    "fulltitle",
    "alt_title",
    "description",
    "duration",
    "uploader",
    "uploader_id",
    "uploader_url",
    "channel",
    "channel_id",
    "channel_url",
    "channel_follower_count",
    "channel_is_verified",
    "creators",
    "view_count",
    "like_count",
    "dislike_count",
    "comment_count",
    "concurrent_view_count",
    "average_rating",
    "playable_in_embed",
    "tags",
    "categories",
    "availability",
    "age_limit",
    "live_status",
    "is_live",
    "was_live",
    "media_type",
    "upload_date",
    "timestamp",
    "release_date",
    "release_timestamp",
    "release_year",
    "modified_date",
    "location",
    "license",
    "language",
    "thumbnail",
    "thumbnails",
    "chapters",
    "heatmap",
    "series",
    "season",
    "season_number",
    "episode",
    "episode_number",
    "track",
    "artists",
    "artist",
    "album",
    "start_time",
    "end_time",
    "section_start",
    "section_end",
    "extractor",
    "extractor_key",
)


@dataclass(frozen=True)
class Target:
    kind: str
    url: str
    raw: str
    video_id: str | None = None
    playlist_id: str | None = None
    handle: str | None = None
    channel_id: str | None = None
    tab: str | None = None


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _host(netloc: str) -> str:
    host = (netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _qs_first(qs: dict[str, list[str]], key: str) -> str | None:
    vals = qs.get(key)
    if vals and vals[0]:
        return vals[0]
    return None


def _watch_url(vid: str, qs: dict[str, list[str]] | None = None) -> str:
    parts: dict[str, str] = {"v": vid}
    if qs:
        for key in ("t", "start", "end", "list", "index"):
            value = _qs_first(qs, key)
            if value:
                parts[key] = value
    return "https://www.youtube.com/watch?" + urlencode(parts)


def _split_tab(parts: list[str]) -> tuple[list[str], str | None]:
    if len(parts) >= 2 and parts[-1] in CHANNEL_TABS:
        return parts[:-1], parts[-1]
    return parts, None


def parse_target(raw: str, *, as_playlist: bool = False, as_channel: bool = False) -> Target:
    text = (raw or "").strip()
    if not text:
        die("empty url")
    if as_channel and not text.startswith("http") and "youtube." not in text.lower():
        if UC_RE.fullmatch(text):
            return Target(
                kind="channel",
                url=f"https://www.youtube.com/channel/{text}",
                raw=text,
                channel_id=text,
            )
        handle = text if text.startswith("@") else f"@{text.lstrip('@')}"
        return Target(
            kind="channel",
            url=f"https://www.youtube.com/{handle}",
            raw=text,
            handle=handle,
        )

    if YTSEARCH_RE.match(text):
        return Target(kind="search", url=text, raw=text)
    if ID_RE.fullmatch(text):
        return Target(
            kind="video",
            url=_watch_url(text),
            raw=text,
            video_id=text,
        )
    if HANDLE_RE.fullmatch(text):
        handle = text if text.startswith("@") else f"@{text}"
        return Target(
            kind="channel",
            url=f"https://www.youtube.com/{handle}",
            raw=text,
            handle=handle,
        )
    if UC_RE.fullmatch(text):
        return Target(
            kind="channel",
            url=f"https://www.youtube.com/channel/{text}",
            raw=text,
            channel_id=text,
        )
    if PLAYLIST_ID_RE.fullmatch(text):
        return Target(
            kind="playlist",
            url=f"https://www.youtube.com/playlist?list={text}",
            raw=text,
            playlist_id=text,
        )

    parsed = urlparse(text)
    host = _host(parsed.netloc)
    if not parsed.scheme and not parsed.netloc and text.startswith("/"):
        parsed = urlparse("https://www.youtube.com" + text)
        host = "youtube.com"
    if host not in YOUTUBE_HOSTS:
        die(f"not a YouTube url: {raw}")

    qs = parse_qs(parsed.query)
    parts = [p for p in parsed.path.split("/") if p]
    video = _qs_first(qs, "v")
    playlist_id = _qs_first(qs, "list")

    if as_playlist and playlist_id:
        return Target(
            kind="playlist",
            url=f"https://www.youtube.com/playlist?list={playlist_id}",
            raw=text,
            playlist_id=playlist_id,
            video_id=video if video and ID_RE.fullmatch(video) else None,
        )

    if host == "youtu.be":
        vid = parts[0] if parts else ""
        if not ID_RE.fullmatch(vid):
            die(f"not a YouTube video url: {raw}")
        return Target(
            kind="video",
            url=_watch_url(vid, qs),
            raw=text,
            video_id=vid,
            playlist_id=playlist_id,
        )

    if video and ID_RE.fullmatch(video):
        return Target(
            kind="video",
            url=_watch_url(video, qs),
            raw=text,
            video_id=video,
            playlist_id=playlist_id,
        )

    if parts:
        head = parts[0].lower()
        if head in {"shorts", "embed", "live", "v", "e", "watch"} and len(parts) >= 2:
            vid = parts[1]
            if vid.endswith(".php"):
                vid = ""
            if ID_RE.fullmatch(vid):
                return Target(
                    kind="video",
                    url=_watch_url(vid, qs),
                    raw=text,
                    video_id=vid,
                    playlist_id=playlist_id,
                )
        if head == "clip" and len(parts) >= 2:
            clip_id = parts[1]
            return Target(
                kind="clip",
                url=f"https://www.youtube.com/clip/{clip_id}",
                raw=text,
            )
        if head == "source" and len(parts) >= 3 and parts[2].lower() == "shorts":
            return Target(
                kind="playlist",
                url=f"https://www.youtube.com/source/{parts[1]}/shorts",
                raw=text,
            )
        if head in {"results", "search"}:
            return Target(kind="search", url=text, raw=text)
        if head == "hashtag" and len(parts) >= 2:
            return Target(
                kind="playlist",
                url=f"https://www.youtube.com/hashtag/{parts[1]}",
                raw=text,
            )
        if head == "feed":
            return Target(kind="playlist", url=text, raw=text)
        if head == "playlist" and playlist_id:
            return Target(
                kind="playlist",
                url=f"https://www.youtube.com/playlist?list={playlist_id}",
                raw=text,
                playlist_id=playlist_id,
            )
        if head in {"channel", "c", "user", "browse"} and len(parts) >= 2:
            ident_parts, tab = _split_tab(parts)
            ident = ident_parts[1] if len(ident_parts) >= 2 else parts[1]
            prefix = "channel" if head == "browse" else head
            path = f"/{prefix}/{ident}"
            if tab:
                path += f"/{tab}"
            kind = "video" if tab == "live" else "channel"
            handle = ident if ident.startswith("@") else None
            channel_id = ident if UC_RE.fullmatch(ident) else None
            return Target(
                kind=kind,
                url=f"https://www.youtube.com{path}",
                raw=text,
                handle=handle,
                channel_id=channel_id,
                tab=None if tab == "live" else tab,
            )
        if parts[0].startswith("@"):
            ident_parts, tab = _split_tab(parts)
            handle = ident_parts[0]
            path = f"/{handle}"
            if tab:
                path += f"/{tab}"
            kind = "video" if tab == "live" else "channel"
            return Target(
                kind=kind,
                url=f"https://www.youtube.com{path}",
                raw=text,
                handle=handle,
                tab=None if tab == "live" else tab,
            )
        if playlist_id:
            return Target(
                kind="playlist",
                url=f"https://www.youtube.com/playlist?list={playlist_id}",
                raw=text,
                playlist_id=playlist_id,
            )
        if ID_RE.fullmatch(parts[-1]):
            return Target(
                kind="video",
                url=_watch_url(parts[-1], qs),
                raw=text,
                video_id=parts[-1],
                playlist_id=playlist_id,
            )

    die(f"not a YouTube url: {raw}")
    return Target(kind="video", url=text, raw=text)


def normalize_url(raw: str, *, as_playlist: bool = False, as_channel: bool = False) -> str:
    return parse_target(raw, as_playlist=as_playlist, as_channel=as_channel).url


def video_id(url: str) -> str:
    target = parse_target(url)
    if target.video_id:
        return target.video_id
    qs = parse_qs(urlparse(url).query)
    return qs.get("v", [""])[0]


CHANNEL_LIST_TABS = (
    "all",
    "videos",
    "shorts",
    "streams",
    "playlists",
    "community",
    "podcasts",
    "releases",
    "about",
)


def apply_tab(target: Target, tab: str | None) -> Target:
    if not tab or target.kind != "channel":
        return target
    tab = tab.lower().strip()
    if tab not in CHANNEL_LIST_TABS:
        die("tab must be " + ", ".join(CHANNEL_LIST_TABS))
    url = target.url.rstrip("/")
    current = None
    for name in CHANNEL_TABS:
        suffix = "/" + name
        if url.lower().endswith(suffix):
            url = url[: -len(suffix)]
            current = name
            break
    if tab == "all":
        return replace(target, url=url, tab=None)
    if current == tab:
        return target
    return replace(target, url=f"{url}/{tab}", tab=tab)


def find_js_runtimes() -> dict[str, dict[str, str]]:
    runtimes: dict[str, dict[str, str]] = {}
    for name in ("deno", "node"):
        exe = shutil.which(name) or shutil.which(f"{name}.exe")
        if exe:
            runtimes[name] = {"path": exe}
    node_pf = Path(r"C:\Program Files\nodejs\node.exe")
    if "node" not in runtimes and node_pf.is_file():
        runtimes["node"] = {"path": str(node_pf)}
    return runtimes


_YOUTUBE_COOKIE: Path | None = None
_YOUTUBE_BROWSER: str | None = None
YOUTUBE_BROWSERS = ("chrome", "edge", "firefox", "brave", "opera", "chromium")


def default_youtube_cookie_path() -> Path | None:
    here = Path(__file__).resolve().parent
    for name in ("youtube_cookie.txt", "youtube.cookies.txt", "yt-cookies.txt"):
        path = here / name
        if path.is_file() and path.stat().st_size > 20:
            return path
    return None


def set_youtube_auth(*, cookiefile: str | Path | None = None, browser: str | None = None) -> None:
    global _YOUTUBE_COOKIE, _YOUTUBE_BROWSER
    path = Path(cookiefile).expanduser() if cookiefile else None
    _YOUTUBE_COOKIE = path if path and path.is_file() else None
    name = (browser or "").strip().lower()
    _YOUTUBE_BROWSER = name if name in YOUTUBE_BROWSERS else None


def youtube_auth_hint() -> str:
    return (
        "YouTube 要求登录确认（机器人验证）。"
        "请在设置里选择从 Chrome / Edge 读取登录态，或粘贴 YouTube 的 cookies.txt 后再解析。"
    )


def is_youtube_bot_check(exc: BaseException | str) -> bool:
    text = str(exc).lower()
    return "not a bot" in text or "sign in to confirm" in text


def explain_youtube_error(exc: BaseException | str) -> str:
    if is_youtube_bot_check(exc):
        return youtube_auth_hint()
    return str(exc)


def ytdlp_base_opts(
    ffmpeg: str | None = None,
    *,
    noplaylist: bool = True,
    skip_translated_subs: bool = True,
    cookiefile: str | Path | None = None,
    browser: str | None = None,
) -> dict[str, Any]:
    youtube_args: dict[str, Any] = {
        # web-first trips "Sign in to confirm you're not a bot"
        "player_client": ["tv", "web_safari", "web"],
    }
    if skip_translated_subs:
        youtube_args["skip"] = ["translated_subs"]
    opts: dict[str, Any] = {
        "noplaylist": noplaylist,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 3,
        "remote_components": ["ejs:github"],
        "extractor_args": {"youtube": youtube_args},
    }
    runtimes = find_js_runtimes()
    if runtimes:
        opts["js_runtimes"] = runtimes
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    cookie: Path | None = None
    if cookiefile:
        cookie = Path(cookiefile).expanduser()
    elif _YOUTUBE_COOKIE is not None:
        cookie = _YOUTUBE_COOKIE
    else:
        cookie = default_youtube_cookie_path()
    if cookie and cookie.is_file():
        opts["cookiefile"] = str(cookie)
    else:
        name = (browser or _YOUTUBE_BROWSER or "").strip().lower()
        if name in YOUTUBE_BROWSERS:
            opts["cookiesfrombrowser"] = (name,)
    return opts


def expire_from_url(url: str | None) -> int | None:
    if not url:
        return None
    if "/expire/" in url:
        try:
            return int(url.split("/expire/", 1)[1].split("/", 1)[0])
        except ValueError:
            return None
    qs = parse_qs(urlparse(url).query)
    raw = _qs_first(qs, "expire")
    if raw and raw.isdigit():
        return int(raw)
    return None


def format_duration(dur: Any) -> str | None:
    if not isinstance(dur, (int, float)):
        return None
    total = int(dur)
    if total < 0:
        return None
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _height(fmt: dict[str, Any]) -> int:
    try:
        return int(fmt.get("height") or 0)
    except (TypeError, ValueError):
        return 0


def _slim_subs(blob: Any) -> dict[str, list[dict[str, Any]]] | None:
    if not blob or not isinstance(blob, dict):
        return None
    out: dict[str, list[dict[str, Any]]] = {}
    for lang, tracks in blob.items():
        slim: list[dict[str, Any]] = []
        for track in tracks or []:
            if not track:
                continue
            slim.append(
                {
                    "ext": track.get("ext"),
                    "url": track.get("url"),
                    "name": track.get("name"),
                    "protocol": track.get("protocol"),
                }
            )
        if slim:
            out[str(lang)] = slim
    return out or None


def _storyboards(formats: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    boards: list[dict[str, Any]] = []
    for fmt in formats or []:
        if not fmt:
            continue
        fid = str(fmt.get("format_id") or "")
        note = fmt.get("format_note") or ""
        proto = fmt.get("protocol") or ""
        if not (fid.startswith("sb") or note == "storyboard" or proto == "mhtml"):
            continue
        boards.append(
            {
                "id": fid,
                "url": fmt.get("url"),
                "width": fmt.get("width"),
                "height": fmt.get("height"),
                "rows": fmt.get("rows"),
                "columns": fmt.get("columns"),
                "fragments": fmt.get("fragments"),
            }
        )
    return boards or None


def _slim_formats(info: dict[str, Any]) -> list[dict[str, Any]]:
    formats: list[dict[str, Any]] = []
    for fmt in info.get("formats") or []:
        if not fmt:
            continue
        vcodec = fmt.get("vcodec") or "none"
        acodec = fmt.get("acodec") or "none"
        fid = str(fmt.get("format_id") or "")
        note = fmt.get("format_note") or ""
        proto = fmt.get("protocol") or ""
        if vcodec == "none" and acodec == "none":
            continue
        if fid.startswith("sb") or note == "storyboard" or proto == "mhtml":
            continue
        kind = "progressive"
        if "m3u8" in proto or "hls" in proto:
            kind = "hls"
        elif vcodec != "none" and acodec == "none":
            kind = "dash_video"
        elif vcodec == "none" and acodec != "none":
            kind = "dash_audio"
        url = fmt.get("url")
        formats.append(
            {
                "id": fmt.get("format_id"),
                "ext": fmt.get("ext"),
                "kind": kind,
                "protocol": proto,
                "width": fmt.get("width"),
                "height": fmt.get("height"),
                "resolution": fmt.get("resolution")
                or (
                    f"{fmt['width']}x{fmt['height']}"
                    if fmt.get("width") and fmt.get("height")
                    else "audio only"
                ),
                "fps": fmt.get("fps"),
                "vcodec": vcodec,
                "acodec": acodec,
                "tbr": fmt.get("tbr"),
                "abr": fmt.get("abr"),
                "filesize": fmt.get("filesize"),
                "filesize_approx": fmt.get("filesize_approx"),
                "note": note,
                "language": fmt.get("language"),
                "language_preference": fmt.get("language_preference"),
                "dynamic_range": fmt.get("dynamic_range"),
                "audio_channels": fmt.get("audio_channels"),
                "has_drm": fmt.get("has_drm"),
                "expire": expire_from_url(url),
                "url": url,
            }
        )
    return formats


def pick_dash_best(formats: list[dict[str, Any]]) -> dict[str, Any] | None:
    videos = [f for f in formats if f.get("kind") == "dash_video" and _height(f) > 0]
    audios = [f for f in formats if f.get("kind") == "dash_audio"]
    if not videos or not audios:
        return None

    def video_key(fmt: dict[str, Any]) -> tuple:
        ext = fmt.get("ext") or ""
        vcodec = (fmt.get("vcodec") or "").lower()
        fid = str(fmt.get("id") or "").lower()
        note = (fmt.get("note") or "").lower()
        mp4 = 1 if ext == "mp4" else 0
        av01 = 1 if vcodec.startswith("av01") else 0
        native = 0 if fid.endswith("-sr") or "upscaled" in note else 1
        tbr = float(fmt.get("tbr") or 0)
        return (_height(fmt), native, mp4, av01, tbr)

    def audio_key(fmt: dict[str, Any]) -> tuple:
        ext = fmt.get("ext") or ""
        fid = str(fmt.get("id") or "").lower()
        note = (fmt.get("note") or "").lower()
        pref = int(fmt.get("language_preference") or 0)
        m4a = 1 if ext in {"m4a", "mp4"} else 0
        orig = 1 if pref >= 10 or "original" in note else 0
        drc = 0 if "drc" in fid else 1
        tbr = float(fmt.get("tbr") or 0)
        return (orig, drc, m4a, tbr)

    video = max(videos, key=video_key)
    audio = max(audios, key=audio_key)
    return {
        "format": f"{video.get('id')}+{audio.get('id')}",
        "resolution": video.get("resolution"),
        "height": _height(video),
        "video": video,
        "audio": audio,
    }


def _tab_of(entry: dict[str, Any], default: str = "videos") -> str:
    url = (entry.get("webpage_url") or entry.get("url") or "").lower()
    title = (entry.get("title") or "").lower()
    for hint, name in (
        ("/shorts", "shorts"),
        ("/streams", "streams"),
        ("/live", "streams"),
        ("/videos", "videos"),
    ):
        if hint in url:
            return name
    if "short" in title:
        return "shorts"
    if "live" in title or "stream" in title:
        return "streams"
    return default


def _entry_url(entry: dict[str, Any]) -> str | None:
    url = entry.get("url") or entry.get("webpage_url")
    if url and url.startswith("http"):
        if "watch?v=" in url or "/shorts/" in url or "/clip/" in url:
            return url
        vid = entry.get("id")
        if vid and ID_RE.fullmatch(str(vid)):
            return _watch_url(str(vid))
        return url
    vid = entry.get("id")
    if vid and ID_RE.fullmatch(str(vid)):
        return _watch_url(str(vid))
    return url


def summarize_entry(entry: dict[str, Any], tab: str = "videos") -> dict[str, Any]:
    url = _entry_url(entry)
    media = entry.get("media_type")
    if PLAYLIST_ID_RE.fullmatch(str(entry.get("id") or "")):
        media = "playlist"
    if not media:
        if (url and "/shorts/" in url) or tab == "shorts":
            media = "short"
        elif tab == "streams" or entry.get("live_status") in {
            "is_live",
            "was_live",
            "post_live",
            "is_upcoming",
        }:
            media = "livestream"
        else:
            media = "video"
    duration = entry.get("duration")
    thumb = entry.get("thumbnail")
    if not thumb:
        thumbs = entry.get("thumbnails") or []
        if thumbs and isinstance(thumbs[-1], dict):
            thumb = thumbs[-1].get("url") or thumbs[0].get("url")
    upload_date = entry.get("upload_date")
    approx = entry.get("upload_date_approx")
    if approx is None and upload_date and not entry.get("enriched"):
        approx = True
    return {
        "id": entry.get("id"),
        "title": entry.get("title"),
        "url": url,
        "duration": duration,
        "duration_string": entry.get("duration_string") or format_duration(duration),
        "uploader": entry.get("uploader") or entry.get("channel"),
        "channel": entry.get("channel"),
        "channel_id": entry.get("channel_id"),
        "channel_url": entry.get("channel_url"),
        "creators": entry.get("creators"),
        "thumbnail": thumb,
        "view_count": entry.get("view_count"),
        "live_status": entry.get("live_status"),
        "availability": entry.get("availability"),
        "upload_date": upload_date,
        "upload_date_approx": approx,
        "timestamp": entry.get("timestamp"),
        "release_timestamp": entry.get("release_timestamp"),
        "description": entry.get("description"),
        "tags": entry.get("tags"),
        "categories": entry.get("categories"),
        "like_count": entry.get("like_count"),
        "comment_count": entry.get("comment_count"),
        "webpage_url": entry.get("webpage_url") or url,
        "media_type": media,
        "tab": tab,
        "enriched": bool(entry.get("enriched")),
    }


def flatten_entries(
    info: dict[str, Any],
    tab: str = "videos",
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(entry: dict[str, Any], current_tab: str) -> None:
        if limit is not None and len(out) >= limit:
            return
        if not entry:
            return
        nested = entry.get("entries")
        etype = entry.get("_type")
        if etype == "playlist" or (nested and etype != "url"):
            child_tab = _tab_of(entry, current_tab)
            for child in nested or []:
                if limit is not None and len(out) >= limit:
                    return
                add(child, child_tab)
            return
        item = summarize_entry(entry, current_tab)
        vid = item.get("id")
        if vid and vid in seen:
            return
        if vid:
            seen.add(str(vid))
        out.append(item)

    for entry in info.get("entries") or []:
        add(entry, _tab_of(info, tab))
        if limit is not None and len(out) >= limit:
            break
    return out


def tab_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"videos": 0, "shorts": 0, "streams": 0, "other": 0}
    for entry in entries:
        tab = entry.get("tab") or "videos"
        if tab in counts:
            counts[tab] += 1
        else:
            counts["other"] += 1
    return counts


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def iso_to_yyyymmdd(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        return text
    matched = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if matched:
        return "".join(matched.groups())
    return None


def iso_to_unix(value: Any) -> int | None:
    if not value:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        try:
            return int(datetime.strptime(text, "%Y%m%d").timestamp())
        except ValueError:
            return None
    text = text.replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(text).timestamp())
    except ValueError:
        return None


def parse_iso8601_duration(value: Any) -> int | None:
    text = str(value or "").strip()
    matched = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", text)
    if not matched:
        return None
    hours = int(matched.group(1) or 0)
    minutes = int(matched.group(2) or 0)
    seconds = float(matched.group(3) or 0)
    return int(hours * 3600 + minutes * 60 + seconds)


def pick_channel_images(thumbnails: Any) -> dict[str, str | None]:
    """Split yt-dlp channel thumbs: avatar_uncropped vs banner_uncropped."""
    avatar: str | None = None
    banner: str | None = None
    best_square: tuple[int, str] | None = None
    best_wide: tuple[int, str] | None = None
    for thumb in thumbnails or []:
        if not isinstance(thumb, dict):
            continue
        url = thumb.get("url")
        if not url:
            continue
        tid = str(thumb.get("id") or "")
        width = _int_or_none(thumb.get("width")) or 0
        height = _int_or_none(thumb.get("height")) or 0
        if tid == "avatar_uncropped":
            avatar = url
            continue
        if tid == "banner_uncropped":
            banner = url
            continue
        if width and height and width == height:
            if not best_square or width > best_square[0]:
                best_square = (width, url)
        elif width and height and width > height * 2:
            if not best_wide or width > best_wide[0]:
                best_wide = (width, url)
    if not avatar and best_square:
        avatar = best_square[1]
    if not banner and best_wide:
        banner = best_wide[1]
    return {"avatar_url": avatar, "banner_url": banner}


def attach_channel_profile(item: dict[str, Any]) -> dict[str, Any]:
    images = pick_channel_images(item.get("thumbnails") or [])
    if images.get("avatar_url"):
        item["avatar_url"] = images["avatar_url"]
        if not item.get("thumbnail"):
            item["thumbnail"] = images["avatar_url"]
    if images.get("banner_url"):
        item["banner_url"] = images["banner_url"]
    item["about"] = {
        "channel": item.get("channel") or item.get("uploader"),
        "channel_id": item.get("channel_id"),
        "handle": item.get("uploader_id"),
        "channel_url": item.get("channel_url"),
        "uploader_url": item.get("uploader_url"),
        "description": item.get("description") or "",
        "subscriber_count": item.get("channel_follower_count"),
        "channel_is_verified": item.get("channel_is_verified"),
        "tags": item.get("tags") or [],
        "avatar_url": item.get("avatar_url"),
        "banner_url": item.get("banner_url"),
        "availability": item.get("availability"),
    }
    return item


def youtube_api_key() -> str | None:
    for name in ("YOUTUBE_API_KEY", "GOOGLE_API_KEY", "YT_API_KEY"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return None


def _guess_image_ext(data: bytes, content_type: str | None, url: str) -> str:
    ctype = (content_type or "").split(";")[0].strip().lower()
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/avif": ".avif",
    }
    if ctype in mapping:
        return mapping[ctype]
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:6] in {b"GIF87a", b"GIF89a"}:
        return ".gif"
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"


def download_image(url: str, dest_stem: Path, retries: int = 3) -> Path:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": SUB_UA,
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    "Referer": "https://www.youtube.com/",
                },
            )
            with urlopen(req, timeout=30) as resp:
                data = resp.read() or b""
                ctype = resp.headers.get("Content-Type") if resp.headers else None
            if len(data) < 32:
                raise ValueError("image too small")
            path = dest_stem.with_suffix(_guess_image_ext(data, ctype, url))
            path.write_bytes(data)
            return path
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            last = exc
            time.sleep(0.6 * (attempt + 1))
    raise last or RuntimeError("image download failed")


_VIDEO_ENRICH_KEYS = (
    "title",
    "description",
    "tags",
    "categories",
    "like_count",
    "comment_count",
    "view_count",
    "upload_date",
    "timestamp",
    "release_timestamp",
    "release_date",
    "channel",
    "channel_id",
    "channel_url",
    "uploader",
    "uploader_id",
    "availability",
    "live_status",
    "thumbnail",
    "duration",
    "duration_string",
)


def apply_video_enrich(entry: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    for key in _VIDEO_ENRICH_KEYS:
        value = meta.get(key)
        if value is None or value == "" or value == []:
            continue
        if key == "duration_string" and entry.get("duration_string"):
            continue
        if key == "title" and entry.get("title"):
            continue
        if key == "thumbnail" and entry.get("thumbnail"):
            continue
        entry[key] = value
    if meta.get("duration") is not None and not entry.get("duration_string"):
        entry["duration_string"] = format_duration(meta.get("duration"))
    if meta.get("upload_date"):
        entry["upload_date"] = meta["upload_date"]
        entry["upload_date_approx"] = False
    entry["enriched"] = True
    return entry


def _http_json(url: str, retries: int = 3) -> dict[str, Any]:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": SUB_UA,
                    "Accept": "application/json",
                },
            )
            with urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if isinstance(payload, dict):
                return payload
            raise ValueError("json object expected")
        except HTTPError as exc:
            last = exc
            if exc.code in {401, 403, 404}:
                break
            time.sleep(1 + attempt)
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(1 + attempt)
    raise last or RuntimeError("json fetch failed")


def _data_api_video_meta(item: dict[str, Any]) -> dict[str, Any]:
    snippet = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    details = item.get("contentDetails") or {}
    thumbs = snippet.get("thumbnails") or {}
    thumb = None
    for name in ("maxres", "standard", "high", "medium", "default"):
        blob = thumbs.get(name)
        if isinstance(blob, dict) and blob.get("url"):
            thumb = blob["url"]
            break
    published = snippet.get("publishedAt")
    duration = parse_iso8601_duration(details.get("duration"))
    return {
        "id": item.get("id"),
        "title": snippet.get("title"),
        "description": snippet.get("description") or "",
        "tags": snippet.get("tags") or [],
        "categories": [snippet["categoryId"]] if snippet.get("categoryId") else None,
        "like_count": _int_or_none(stats.get("likeCount")),
        "comment_count": _int_or_none(stats.get("commentCount")),
        "view_count": _int_or_none(stats.get("viewCount")),
        "upload_date": iso_to_yyyymmdd(published),
        "timestamp": iso_to_unix(published),
        "channel": snippet.get("channelTitle"),
        "channel_id": snippet.get("channelId"),
        "channel_url": (
            f"https://www.youtube.com/channel/{snippet['channelId']}"
            if snippet.get("channelId")
            else None
        ),
        "thumbnail": thumb,
        "duration": duration,
        "duration_string": format_duration(duration),
        "live_status": (
            "is_live"
            if (details.get("duration") == "P0D" or snippet.get("liveBroadcastContent") == "live")
            else None
        ),
        "availability": "public" if item.get("status", {}).get("privacyStatus") == "public" else item.get("status", {}).get("privacyStatus"),
    }


def enrich_videos_data_api(video_ids: list[str], key: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(video_ids), 50):
        batch = video_ids[offset : offset + 50]
        qs = urlencode(
            {
                "part": "snippet,statistics,contentDetails,status",
                "id": ",".join(batch),
                "key": key,
                "maxResults": 50,
            }
        )
        payload = _http_json("https://www.googleapis.com/youtube/v3/videos?" + qs)
        if payload.get("error"):
            message = ((payload.get("error") or {}).get("message")) or "YouTube Data API error"
            raise RuntimeError(str(message))
        for item in payload.get("items") or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            out[str(item["id"])] = _data_api_video_meta(item)
    return out


def _video_meta_opts(ffmpeg: str | None) -> dict[str, Any]:
    opts = ytdlp_base_opts(ffmpeg, noplaylist=True)
    youtube_args = dict(((opts.get("extractor_args") or {}).get("youtube") or {}))
    youtube_args["player_client"] = ["tv", "web_safari"]
    skip = [str(x) for x in (youtube_args.get("skip") or [])]
    for name in ("hls", "dash"):
        if name not in skip:
            skip.append(name)
    youtube_args["skip"] = skip
    youtube_args["player_skip"] = ["js", "configs"]
    opts["extractor_args"] = {"youtube": youtube_args}
    opts.update(
        {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": False,
            "ignoreerrors": False,
            "ignore_no_formats_error": True,
            "noprogress": True,
        }
    )
    return opts


def extract_video_meta(url: str, ffmpeg: str | None = None) -> dict[str, Any]:
    """Watch-page metadata only: full description, tags, likes, real upload date. No media."""
    info = _extract_raw(url, _video_meta_opts(ffmpeg))
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        info = entries[0] if entries else info
    duration = info.get("duration")
    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "description": info.get("description") or "",
        "tags": info.get("tags") or [],
        "categories": info.get("categories"),
        "like_count": info.get("like_count"),
        "comment_count": info.get("comment_count"),
        "view_count": info.get("view_count"),
        "upload_date": info.get("upload_date") or iso_to_yyyymmdd(info.get("release_date")),
        "timestamp": info.get("timestamp") or info.get("release_timestamp"),
        "release_timestamp": info.get("release_timestamp"),
        "release_date": info.get("release_date"),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_id": info.get("channel_id"),
        "channel_url": info.get("channel_url"),
        "uploader": info.get("uploader") or info.get("channel"),
        "uploader_id": info.get("uploader_id"),
        "availability": info.get("availability"),
        "live_status": info.get("live_status"),
        "thumbnail": info.get("thumbnail"),
        "duration": duration,
        "duration_string": info.get("duration_string") or format_duration(duration),
    }


def _catalog_entry_url(entry: dict[str, Any]) -> str | None:
    vid = str(entry.get("id") or "")
    if vid and ID_RE.fullmatch(vid) and entry.get("media_type") != "playlist":
        return _watch_url(vid)
    url = entry.get("url") or entry.get("webpage_url")
    return str(url) if url else None


def enrich_catalog_entries(
    entries: list[dict[str, Any]],
    ffmpeg: str | None = None,
    *,
    workers: int = 6,
) -> dict[str, Any]:
    """Fill per-video full description, tags, likes, real upload_date. No media download."""
    jobs: list[tuple[int, str, str]] = []
    for index, entry in enumerate(entries):
        if entry.get("media_type") == "playlist":
            continue
        vid = str(entry.get("id") or "")
        url = _catalog_entry_url(entry)
        if not vid or not url or not ID_RE.fullmatch(vid):
            continue
        jobs.append((index, vid, url))
    stats: dict[str, Any] = {
        "wanted": len(jobs),
        "ok": 0,
        "failed": 0,
        "source": None,
    }
    if not jobs:
        return stats
    remaining = {vid: index for index, vid, _url in jobs}
    api_key = youtube_api_key()
    if api_key:
        print(f"enrich: YouTube Data API ({len(jobs)} videos)", flush=True)
        try:
            blob = enrich_videos_data_api([vid for _i, vid, _u in jobs], api_key)
            for vid, meta in blob.items():
                index = remaining.pop(vid, None)
                if index is None:
                    continue
                apply_video_enrich(entries[index], meta)
                stats["ok"] += 1
            stats["source"] = "youtube_data_api"
        except Exception as exc:  # noqa: BLE001
            print(f"warning: Data API enrich failed, fallback yt-dlp: {exc}", file=sys.stderr, flush=True)
            remaining = {vid: index for index, vid, _url in jobs}
            stats["ok"] = 0
    leftover = [(index, vid, url) for index, vid, url in jobs if vid in remaining]
    if leftover:
        workers = max(1, int(workers or 1))
        print(f"enrich: yt-dlp watch metadata x{len(leftover)} workers={workers}", flush=True)
        stats["source"] = "yt-dlp" if not stats["source"] else f"{stats['source']}+yt-dlp"

        def one(job: tuple[int, str, str]) -> tuple[int, dict[str, Any]]:
            index, _vid, url = job
            return index, extract_video_meta(url, ffmpeg)

        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(one, job) for job in leftover]
            for future in as_completed(futures):
                done += 1
                try:
                    index, meta = future.result()
                except Exception as exc:  # noqa: BLE001
                    stats["failed"] += 1
                    print(f"warning: enrich failed ({done}/{len(leftover)}): {exc}", file=sys.stderr, flush=True)
                    continue
                apply_video_enrich(entries[index], meta)
                stats["ok"] += 1
                if done == len(leftover) or done % 5 == 0:
                    print(f"enrich: {done}/{len(leftover)}", flush=True)
    stats["failed"] = max(stats["failed"], stats["wanted"] - stats["ok"])
    return stats


def _extract_raw(url: str, opts: dict[str, Any]) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = [opts]
    if not opts.get("cookiefile") and not opts.get("cookiesfrombrowser") and os.name == "nt":
        for name in ("chrome", "edge"):
            retry = dict(opts)
            retry["cookiesfrombrowser"] = (name,)
            attempts.append(retry)
    last: BaseException | None = None
    for i, attempt in enumerate(attempts):
        try:
            with yt_dlp.YoutubeDL(attempt) as ydl:
                info = ydl.extract_info(url, download=False)
            if not info:
                raise RuntimeError("yt-dlp returned no info")
            return info
        except Exception as exc:  # noqa: BLE001
            last = exc
            if not is_youtube_bot_check(exc) or i + 1 >= len(attempts):
                break
            nxt = attempts[i + 1].get("cookiesfrombrowser") or ("?",)
            print(
                f"warning: YouTube bot check, retry cookies-from-browser {nxt[0]}",
                file=sys.stderr,
                flush=True,
            )
    raise RuntimeError(explain_youtube_error(last or RuntimeError("yt-dlp returned no info"))) from last


def _extract_video(target: Target, ffmpeg: str | None) -> dict[str, Any]:
    opts = ytdlp_base_opts(ffmpeg, noplaylist=True)
    opts.update(
        {
            "quiet": True,
            "no_warnings": False,
            "skip_download": True,
            "extract_flat": False,
        }
    )
    info = _extract_raw(target.url, opts)
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            die("playlist/channel has no videos")
        info = entries[0]
    formats = _slim_formats(info)
    dash = pick_dash_best(formats)
    item: dict[str, Any] = {
        "kind": target.kind,
        "original_url": target.raw,
        "url": info.get("webpage_url") or target.url,
        "webpage_url": info.get("webpage_url") or target.url,
    }
    for key in _COPY_VIDEO_KEYS:
        item[key] = info.get(key)
    if not item.get("id"):
        item["id"] = target.video_id or video_id(target.url)
    item["duration_string"] = info.get("duration_string") or format_duration(item.get("duration"))
    item["description"] = info.get("description") or ""
    item["subtitles"] = _slim_subs(info.get("subtitles"))
    item["automatic_captions"] = _slim_subs(info.get("automatic_captions"))
    item["storyboards"] = _storyboards(info.get("formats"))
    item["ext"] = info.get("ext")
    item["resolution"] = (dash or {}).get("resolution") or (
        f"{info.get('width')}x{info.get('height')}"
        if info.get("width") and info.get("height")
        else None
    )
    item["dash"] = dash
    item["formats"] = formats
    return item


def _extract_list(
    target: Target,
    ffmpeg: str | None,
    *,
    limit: int | None,
) -> dict[str, Any]:
    opts = ytdlp_base_opts(ffmpeg, noplaylist=False)
    youtube_args = ((opts.get("extractor_args") or {}).get("youtube") or {}).copy()
    youtube_args["approximate_date"] = ["true"]
    opts["extractor_args"] = {"youtube": youtube_args}
    opts.update(
        {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "ignoreerrors": True,
        }
    )
    if limit is not None:
        opts["playlistend"] = limit
    info = _extract_raw(target.url, opts)
    default_tab = target.tab or "videos"
    entries = flatten_entries(info, default_tab, limit=limit)
    counts = tab_counts(entries)
    channel_id = info.get("channel_id") or target.channel_id
    handle = info.get("uploader_id") or target.handle
    kind = target.kind
    if info.get("_type") == "playlist" and kind == "video":
        kind = "playlist"
    item = {
        "kind": kind,
        "original_url": target.raw,
        "url": info.get("webpage_url") or target.url,
        "webpage_url": info.get("webpage_url") or target.url,
        "id": info.get("id") or channel_id or target.playlist_id,
        "title": info.get("title"),
        "description": info.get("description") or "",
        "uploader": info.get("uploader") or info.get("channel"),
        "uploader_id": handle,
        "uploader_url": info.get("uploader_url"),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_id": channel_id,
        "channel_url": info.get("channel_url"),
        "channel_follower_count": info.get("channel_follower_count"),
        "channel_is_verified": info.get("channel_is_verified"),
        "availability": info.get("availability"),
        "modified_date": info.get("modified_date"),
        "view_count": info.get("view_count"),
        "playlist_count": info.get("playlist_count") or len(entries),
        "tags": info.get("tags"),
        "thumbnail": info.get("thumbnail"),
        "thumbnails": info.get("thumbnails"),
        "extractor": info.get("extractor"),
        "extractor_key": info.get("extractor_key"),
        "tab": target.tab or "all",
        "tab_counts": counts,
        "entry_count": len(entries),
        "entries": entries,
    }
    if kind == "channel":
        attach_channel_profile(item)
    return item


def extract_info(
    url: str,
    ffmpeg: str | None = None,
    *,
    limit: int | None = None,
    tab: str | None = None,
    as_playlist: bool = False,
    as_channel: bool = False,
) -> dict[str, Any]:
    target = apply_tab(
        parse_target(url, as_playlist=as_playlist, as_channel=as_channel),
        tab,
    )
    if target.kind in LIST_KINDS:
        return _extract_list(target, ffmpeg, limit=limit)
    return _extract_video(target, ffmpeg)


UPLOAD_TABS = ("videos", "shorts", "streams")


def extract_user_catalog(
    raw: str,
    ffmpeg: str | None = None,
    *,
    tab: str = "all",
    limit: int | None = None,
    extras: tuple[str, ...] = (),
    enrich: bool = True,
    workers: int = 6,
) -> dict[str, Any]:
    """All public uploads of a channel: videos + shorts + streams (unless tab is set).

    Channel About / subscribers / avatar come from the tab header (no extra download).
    Per-video full description, tags, likes, and real upload_date need a watch-page
    enrich pass (Data API if YOUTUBE_API_KEY is set, else yt-dlp skip_download).
    """
    target = parse_target(raw, as_channel=True)
    if target.kind != "channel":
        die("need a channel @handle or UC id")
    want = tab if tab and tab != "all" else "all"
    tabs: tuple[str, ...]
    if want == "all":
        tabs = UPLOAD_TABS
    else:
        tabs = (want,)
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    fetched: dict[str, int] = {}
    base: dict[str, Any] = {}
    for name in tabs:
        print(f"user: fetch /{name}", flush=True)
        try:
            part = extract_info(
                raw,
                ffmpeg,
                limit=limit,
                tab=name,
                as_channel=True,
            )
        except Exception as exc:  # noqa: BLE001 - one tab must not abort the rest
            print(f"warning: skip tab {name}: {exc}", file=sys.stderr, flush=True)
            fetched[name] = 0
            continue
        if not base:
            base = {key: value for key, value in part.items() if key != "entries"}
        added = 0
        for entry in part.get("entries") or []:
            vid = str(entry.get("id") or "")
            if vid and vid in seen:
                continue
            if vid:
                seen.add(vid)
            merged.append(entry)
            added += 1
        fetched[name] = added
    extra_blob: dict[str, Any] = {}
    for extra in extras:
        extra = extra.strip().lower()
        if extra in {"", "all"} or extra in tabs:
            continue
        print(f"user: fetch /{extra}", flush=True)
        try:
            extra_blob[extra] = extract_info(
                raw,
                ffmpeg,
                limit=limit,
                tab=extra,
                as_channel=True,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"warning: skip extra {extra}: {exc}", file=sys.stderr, flush=True)
    if not base:
        die(f"could not read channel: {raw}")
    if not (base.get("description") or "").strip():
        print("user: fetch /about", flush=True)
        try:
            about_part = extract_info(raw, ffmpeg, tab="about", as_channel=True)
            for key in (
                "description",
                "tags",
                "channel_follower_count",
                "channel_is_verified",
                "thumbnails",
                "thumbnail",
                "channel",
                "channel_id",
                "channel_url",
                "uploader",
                "uploader_id",
                "uploader_url",
            ):
                if about_part.get(key) and not base.get(key):
                    base[key] = about_part[key]
        except Exception as exc:  # noqa: BLE001
            print(f"warning: skip /about: {exc}", file=sys.stderr, flush=True)
    channel = base.get("channel") or base.get("uploader")
    channel_id = base.get("channel_id")
    channel_url = base.get("channel_url")
    uploader = base.get("uploader") or channel
    for entry in merged:
        if not entry.get("channel"):
            entry["channel"] = channel
        if not entry.get("channel_id"):
            entry["channel_id"] = channel_id
        if not entry.get("channel_url"):
            entry["channel_url"] = channel_url
        if not entry.get("uploader"):
            entry["uploader"] = uploader
    enrich_stats = None
    if enrich:
        enrich_stats = enrich_catalog_entries(merged, ffmpeg, workers=workers)
    counts = tab_counts(merged)
    base.update(
        {
            "kind": "channel",
            "original_url": target.raw,
            "tab": want,
            "tab_fetched": list(tabs),
            "tab_fetched_counts": fetched,
            "tab_counts": counts,
            "entry_count": len(merged),
            "entries": merged,
            "extras": extra_blob or None,
            "enrich": enrich_stats,
        }
    )
    attach_channel_profile(base)
    return base


def safe_dirname(item: dict[str, Any]) -> str:
    if item.get("kind") in VIDEO_KINDS:
        raw = item.get("id") or "youtube"
    else:
        raw = item.get("channel_id") or item.get("id") or item.get("uploader_id") or "youtube"
    text = str(raw).strip().lstrip("@")
    cleaned = re.sub(r"[^\w.-]+", "_", text, flags=re.UNICODE)
    return (cleaned[:80] or "youtube").rstrip("._")


def parse_sub_langs(text: str | None) -> list[str]:
    if not text or not str(text).strip():
        return list(DEFAULT_SUB_LANGS)
    parts = [p.strip() for p in str(text).split(",") if p.strip()]
    return parts or list(DEFAULT_SUB_LANGS)


def sub_lang_from_filename(name: str, video_id: str | None = None) -> str:
    stem = Path(name).stem
    if video_id and stem.startswith(f"{video_id}."):
        return stem[len(video_id) + 1 :]
    parts = stem.split(".", 1)
    return parts[1] if len(parts) > 1 else stem


def subtitle_opts(langs: list[str] | None, *, auto: bool = True) -> dict[str, Any]:
    wanted = langs or list(DEFAULT_SUB_LANGS)
    return {
        "writesubtitles": True,
        "writeautomaticsub": auto,
        "subtitlesformat": "vtt",
        "subtitleslangs": wanted,
    }


def _lang_wanted(lang: str, wanted: list[str]) -> bool:
    if lang == "live_chat":
        return False
    for pat in wanted:
        if pat == "all" or pat == lang:
            return True
        try:
            if re.fullmatch(pat, lang):
                return True
        except re.error:
            continue
    return False


def _caption_vtt_url(tracks: list[dict[str, Any]] | None) -> str | None:
    if not tracks:
        return None
    for track in tracks:
        if track and track.get("url") and track.get("ext") == "vtt":
            return track["url"]
    for track in tracks:
        if track and track.get("url"):
            return track["url"]
    return None


def _set_query(url: str, **updates: str | None) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key, value in updates.items():
        if value is None:
            query.pop(key, None)
        else:
            query[key] = [value]
    query.pop("xosf", None)
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _best_source_caption_url(
    item: dict[str, Any],
    source_lang: str | None = None,
) -> str | None:
    official = item.get("subtitles") or {}
    auto = item.get("automatic_captions") or {}
    lang = normalize_lang(source_lang)
    prefer_off = tuple(k for k in official if lang and normalize_lang(k) == lang)
    prefer_auto = tuple(
        sorted(
            (k for k in auto if lang and normalize_lang(k) == lang),
            key=lambda k: (0 if str(k).endswith("-orig") else 1, str(k)),
        )
    )
    for blob, langs in (
        (official, prefer_off or ("en", "en-US", "en-GB")),
        (auto, prefer_auto or ("en-orig", "en", "en-US")),
        (official, tuple(official)),
        (auto, tuple(k for k in auto if str(k).endswith("-orig"))),
        (auto, tuple(auto)),
    ):
        for key in langs:
            url = _caption_vtt_url(blob.get(key))
            if url:
                return url
    return None


def _http_get_vtt(url: str, retries: int = 4) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = Request(
                url,
                headers={
                    "User-Agent": SUB_UA,
                    "Accept": "text/vtt,text/plain,*/*",
                    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
                    "Referer": "https://www.youtube.com/",
                },
            )
            with urlopen(req, timeout=30) as resp:
                data = resp.read() or b""
            text = data.decode("utf-8", errors="replace").lstrip("\ufeff")
            if text.startswith("WEBVTT") or "-->" in text[:4000]:
                return text.encode("utf-8")
            last = ValueError("timedtext response is not WebVTT")
        except HTTPError as exc:
            last = exc
            if exc.code == 429:
                raw = exc.headers.get("Retry-After") if exc.headers else None
                wait = int(raw) if raw and str(raw).isdigit() else (2 ** attempt) * 3
                print(f"warning: subtitles 429, retry in {wait}s", file=sys.stderr, flush=True)
                time.sleep(wait)
                continue
            if exc.code in {401, 403, 404, 410}:
                break
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            last = exc
            time.sleep(1 + attempt)
            continue
        time.sleep(0.4)
    if last:
        raise last
    raise RuntimeError("subtitle download failed")


def list_subtitle_files(dest: Path, video_id: str | None = None) -> list[Path]:
    files: list[Path] = []
    for path in sorted(dest.glob("*")):
        if not path.is_file():
            continue
        if "live_chat" in path.name.lower():
            try:
                path.unlink()
            except OSError:
                pass
            continue
        if path.suffix.lower() not in {".vtt", ".srt", ".ttml", ".srv3", ".json3"}:
            continue
        if video_id and not path.name.startswith(f"{video_id}."):
            continue
        files.append(path)
    return files


EMBED_ZH_HANS = ("zh-Hans", "zh", "zh-Hans-orig", "zh-orig")
EMBED_ZH_HANT = ("zh-Hant", "zh-Hant-orig", "zh-TW")
EMBED_EN = ("en", "en-US", "en-GB", "en-orig")

_VTT_TS = re.compile(
    r"^(?:(\d{2}):)?(\d{2}):(\d{2})[.,](\d{1,3})\s+-->\s+(?:(\d{2}):)?(\d{2}):(\d{2})[.,](\d{1,3})"
)
_VTT_TAG = re.compile(
    r"</?c[^>]*>|<\d{2}:\d{2}:\d{2}[.,]\d{3}>|</?v[^>]*>|</?lang[^>]*>"
)
_VTT_WORD = re.compile(
    r"<(\d{2}):(\d{2}):(\d{2})[.,](\d{3})><c>\s*([^<]*?)</c>",
    re.I,
)


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class BilingualCue:
    start: float
    end: float
    zh: str
    en: str


def pick_embed_tracks(dest: Path, video_id: str) -> list[dict[str, Any]]:
    """Locate source zh/en VTT files (used for 对轴 input)."""
    files = {
        sub_lang_from_filename(path.name, video_id): path
        for path in list_subtitle_files(dest, video_id)
    }
    tracks: list[dict[str, Any]] = []
    used: set[Path] = set()

    def take(cands: tuple[str, ...], lang: str, title: str) -> None:
        for key in cands:
            path = files.get(key)
            if path and path not in used and path.stat().st_size > 20:
                used.add(path)
                tracks.append(
                    {
                        "path": path,
                        "tag": key,
                        "lang": lang,
                        "title": title,
                        "default": False,
                    }
                )
                return

    take(EMBED_ZH_HANS, "chi", "简体中文")
    take(EMBED_ZH_HANT, "chi", "繁体中文")
    take(EMBED_EN, "eng", "English")
    if tracks:
        tracks[0]["default"] = True
    return tracks


def _ts_to_sec(h: str | None, m: str, s: str, frac: str) -> float:
    ms = int(frac.ljust(3, "0")[:3])
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + ms / 1000.0


def clean_caption_text(text: str) -> str:
    text = _VTT_TAG.sub("", text)
    text = re.sub(r"\{[^}]+\}", "", text)
    text = html.unescape(text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if re.fullmatch(r"[\[\(\（]?(music|applause|laughter|音乐|掌声|笑声)[\]\)\）]?", text, re.I):
        return ""
    return text


def parse_vtt(path: Path) -> list[Cue]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", raw):
        lines = [ln.rstrip() for ln in block.splitlines() if ln.strip() != ""]
        time_i = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if time_i is None:
            continue
        match = _VTT_TS.search(lines[time_i])
        if not match:
            continue
        start = _ts_to_sec(match.group(1), match.group(2), match.group(3), match.group(4))
        end = _ts_to_sec(match.group(5), match.group(6), match.group(7), match.group(8))
        body = " ".join(ln for ln in lines[time_i + 1 :] if not ln.startswith("NOTE"))
        text = clean_caption_text(body)
        if not text:
            continue
        if end <= start:
            end = start + 0.5
        cues.append(Cue(start, end, text))
    return cues


def collapse_rolling_cues(cues: list[Cue]) -> list[Cue]:
    """YouTube auto-VTT repeats rolling words; keep the longest line on the same axis."""
    if not cues:
        return []
    out = [cues[0]]
    for cue in cues[1:]:
        prev = out[-1]
        overlap = min(prev.end, cue.end) - max(prev.start, cue.start)
        span = max(min(prev.end - prev.start, cue.end - cue.start), 0.05)
        related = (
            cue.text.startswith(prev.text)
            or prev.text.startswith(cue.text)
            or prev.text in cue.text
            or cue.text in prev.text
        )
        adjacent = abs(cue.start - prev.end) <= 0.02
        if overlap >= 0.12 * span or (cue.start < prev.end and related) or (adjacent and related):
            text = cue.text if len(cue.text) >= len(prev.text) else prev.text
            out[-1] = Cue(prev.start, max(prev.end, cue.end), text)
        else:
            out.append(cue)
    return out


def committed_cues_from_youtube(cues: list[Cue]) -> list[Cue]:
    """Recover finished phrases from YouTube karaoke VTT (10ms commit frames)."""
    if not cues:
        return []
    out: list[Cue] = []
    window_start: float | None = None
    window_end: Cue | None = None
    for cue in cues:
        dur = cue.end - cue.start
        if dur <= 0.05:
            if not cue.text:
                continue
            start = window_start if window_start is not None else cue.start
            end = window_end.end if window_end is not None else cue.end
            out.append(Cue(start, max(end, start + 0.4), cue.text))
            window_start = None
            window_end = None
        else:
            if window_start is None:
                window_start = cue.start
            window_end = cue
    if window_end is not None and window_start is not None:
        out.append(Cue(window_start, window_end.end, window_end.text))
    return out


def merge_cues_to_sentences(
    cues: list[Cue],
    *,
    max_chars: int = 130,
    max_span: float = 8.5,
    pause: float = 0.85,
) -> list[Cue]:
    """Join karaoke fragments into spoken sentences (English clock stays intact)."""
    if not cues:
        return []
    out: list[Cue] = []
    buf: list[Cue] = []

    def flush() -> None:
        if not buf:
            return
        text = re.sub(r"\s+", " ", " ".join(c.text.strip() for c in buf)).strip()
        if text:
            out.append(Cue(buf[0].start, buf[-1].end, text))
        buf.clear()

    for cue in cues:
        if buf and (
            cue.start - buf[-1].end > pause or buf[-1].end - buf[0].start > max_span
        ):
            flush()
        buf.append(cue)
        joined = re.sub(r"\s+", " ", " ".join(c.text for c in buf)).strip()
        span = buf[-1].end - buf[0].start
        if re.search(r'[.!?。！？]["\']?$', joined) or (
            len(joined) >= max_chars and span >= 2.8
        ):
            flush()
    flush()
    return split_on_sentence_punct(out)


def split_on_sentence_punct(cues: list[Cue]) -> list[Cue]:
    """If a cue already contains two spoken sentences, split time by character weight."""
    out: list[Cue] = []
    for cue in cues:
        parts = [p.strip() for p in re.split(r"(?<=[.!?。！？])\s+", cue.text) if p.strip()]
        if len(parts) <= 1:
            out.append(cue)
            continue
        total = sum(max(len(part), 1) for part in parts)
        t = cue.start
        span = max(cue.end - cue.start, 0.4 * len(parts))
        for i, part in enumerate(parts):
            dur = span * (len(part) / total)
            end = cue.end if i == len(parts) - 1 else t + max(dur, 0.45)
            if end > cue.end:
                end = cue.end
            out.append(Cue(t, max(end, t + 0.35), part))
            t = end
    return out


def extract_youtube_words(
    path: Path,
    *,
    skip_music: bool = False,
) -> list[tuple[str, float, float]]:
    """Word clock from YouTube karaoke VTT (<c> timestamps). Dedup rolling repeats."""
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    words: list[tuple[str, float, float]] = []
    last_t = -1.0
    for block in re.split(r"\n\s*\n", raw):
        lines = [ln.rstrip() for ln in block.splitlines()]
        time_i = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if time_i is None:
            continue
        match = _VTT_TS.search(lines[time_i])
        if not match:
            continue
        cue_start = _ts_to_sec(match.group(1), match.group(2), match.group(3), match.group(4))
        cue_end = _ts_to_sec(match.group(5), match.group(6), match.group(7), match.group(8))
        body = "\n".join(lines[time_i + 1 :])
        if skip_music and (
            re.search(r"\[music\]", body, re.I)
            or re.search(r"\bheat\.?\s*heat\b", body, re.I)
        ):
            continue
        tagged: list[tuple[float, str]] = []
        for hit in _VTT_WORD.finditer(body):
            t = _ts_to_sec(hit.group(1), hit.group(2), hit.group(3), hit.group(4))
            w = (hit.group(5) or "").strip()
            if w:
                tagged.append((t, w))
        if not tagged:
            continue
        first_plain = body.split("<", 1)[0].strip()
        seq: list[tuple[float, str]] = []
        if first_plain and cue_start >= last_t - 0.02:
            seq.append((cue_start, first_plain.split()[0] if first_plain.split() else first_plain))
        seq.extend(tagged)
        for i, (t, w) in enumerate(seq):
            if t + 1e-4 < last_t:
                continue
            end = seq[i + 1][0] if i + 1 < len(seq) else min(cue_end, t + 0.35)
            if end <= t:
                end = t + 0.12
            words.append((w, t, end))
            last_t = t
    return words


def phrases_from_words(
    words: list[tuple[str, float, float]],
    *,
    max_span: float = 3.4,
    pause: float = 0.38,
) -> list[Cue]:
    if not words:
        return []
    out: list[Cue] = []
    buf: list[tuple[str, float, float]] = []

    def flush() -> None:
        if not buf:
            return
        text = join_spoken([w[0] for w in buf])
        if text:
            out.append(Cue(buf[0][1], buf[-1][2], text))
        buf.clear()

    for item in words:
        if buf and (
            item[1] - buf[-1][2] > pause or item[2] - buf[0][1] > max_span
        ):
            flush()
        buf.append(item)
        joined = " ".join(w[0] for w in buf)
        if re.search(r'[.!?。！？]["\']?$', joined.strip()):
            flush()
    flush()
    return [cue for cue in out if cue.text.strip()]


_NOISE_CAPTION = re.compile(
    r"^\s*\[(?:music|applause|laughter|cheers|singing)\]\s*$",
    re.I,
)


def _en_token_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text or ""))


def _src_unit_count(text: str) -> int:
    return _en_token_count(text) + len(
        re.findall(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\u0e00-\u0e7f\u0600-\u06ff\u0400-\u04ff]", text or "")
    )


def coalesce_cues(
    cues: list[Cue],
    *,
    max_span: float = 4.2,
    max_pause: float = 0.7,
) -> list[Cue]:
    """Glue leftover fragments (morning, / Alaska.) back onto the previous line."""
    if not cues:
        return []
    out: list[Cue] = [cues[0]]
    for cue in cues[1:]:
        prev = out[-1]
        pause = cue.start - prev.end
        span = cue.end - prev.start
        prev_done = bool(re.search(r'[.!?。！？]["\']?$', prev.text.strip()))
        frag = _src_unit_count(cue.text) <= 2 or len((cue.text or "").strip()) <= 12
        cont = bool(cue.text) and cue.text[0].islower()
        glue = pause <= max_pause and span <= max_span and (
            cont or (frag and (not prev_done or pause <= 0.28))
        )
        if glue:
            text = re.sub(r"\s+", " ", f"{prev.text} {cue.text}").strip()
            out[-1] = Cue(prev.start, max(prev.end, cue.end), text)
            continue
        out.append(cue)
    return out


def fill_word_gaps(
    primary: list[tuple[str, float, float]],
    extra: list[tuple[str, float, float]],
    *,
    min_hole: float = 1.8,
) -> list[tuple[str, float, float]]:
    """Insert YouTube EN words only into STT silence holes. Never uses Chinese VTT."""
    if not extra or not primary:
        return primary
    holes: list[tuple[float, float]] = []
    for (_, _a0, a1), (_, b0, _b1) in zip(primary, primary[1:]):
        lo, hi = a1 + 0.45, b0 - 0.45
        if hi - lo >= min_hole:
            holes.append((lo, hi))
    if primary[0][1] >= min_hole + 0.5:
        holes.insert(0, (0.0, primary[0][1] - 0.45))
    if not holes:
        return primary

    def in_hole(t: float) -> bool:
        return any(lo <= t <= hi for lo, hi in holes)

    grouped: dict[tuple[float, float], list[tuple[str, float, float]]] = {h: [] for h in holes}
    for text, start, end in extra:
        raw = (text or "").strip()
        if not raw or _NOISE_CAPTION.match(raw) or raw.startswith("["):
            continue
        if not re.search(
            r"[A-Za-z0-9\u0400-\u04ff\u0600-\u06ff\u0900-\u097f\u0e00-\u0e7f\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]",
            raw,
        ):
            continue
        mid = (start + end) / 2
        for hole in holes:
            if hole[0] <= mid <= hole[1]:
                grouped[hole].append((raw, start, end))
                break
    filled: list[tuple[str, float, float]] = []
    for _hole, items in grouped.items():
        items.sort(key=lambda item: item[1])
        cluster: list[tuple[str, float, float]] = []

        def keep_cluster(buf: list[tuple[str, float, float]]) -> None:
            if len(buf) >= 4:
                filled.extend(buf)
            elif len(buf) >= 3 and buf[-1][2] - buf[0][1] >= 1.2:
                filled.extend(buf)

        for item in items:
            if cluster and item[1] - cluster[-1][2] > 2.0:
                keep_cluster(cluster)
                cluster = []
            cluster.append(item)
        keep_cluster(cluster)
    if not filled:
        return primary
    merged = list(primary) + filled
    merged.sort(key=lambda item: (item[1], item[2]))
    from youtube_audio_sync import clamp_word_times

    return clamp_word_times(merged)


def rows_from_spoken_words(words: list[tuple[str, float, float]]) -> list[BilingualCue]:
    """Source-language cues + times from Grok STT words. Chinese is filled later."""
    cues = coalesce_cues(phrases_from_words(words))
    return [
        BilingualCue(cue.start, cue.end, "", cue.text)
        for cue in cues
        if cue.text.strip()
    ]


def rows_from_media_speech(
    media: Path,
    dest: Path,
    ffmpeg: Path,
    en_vtt: Path | None = None,
    *,
    language: str = "en",
) -> list[BilingualCue]:
    from youtube_audio_sync import extract_audio_track, grok_stt_words

    audio = extract_audio_track(media, dest, ffmpeg)
    print(f"grok-voice: demux {audio.name} (audio only, not the video)", flush=True)
    words = grok_stt_words(audio, dest, ffmpeg, language=language)
    if en_vtt is not None and Path(en_vtt).is_file():
        vtt_lang = normalize_lang(sub_lang_from_filename(Path(en_vtt).name))
        spoken_lang = guess_lang_from_text("".join(w[0] for w in words[:80])) or normalize_lang(language)
        if vtt_lang and spoken_lang and vtt_lang != spoken_lang:
            print(
                f"subs: skip YouTube {vtt_lang} gap-fill (speech is {spoken_lang})",
                flush=True,
            )
        else:
            yt_words = extract_youtube_words(Path(en_vtt), skip_music=True)
            before = len(words)
            words = fill_word_gaps(words, yt_words)
            extra = len(words) - before
            if extra:
                print(f"subs: fill {extra} YouTube source words into STT gaps", flush=True)
    rows = rows_from_spoken_words(words)
    print(f"subs: grok-voice {len(rows)} cues from {len(words)} spoken words", flush=True)
    if len(rows) < 3:
        raise RuntimeError("grok STT produced too few subtitle cues")
    return rows


def sentence_cues_from_vtt(path: Path) -> list[Cue]:
    words = extract_youtube_words(path)
    if len(words) >= 12:
        cues = phrases_from_words(words)
        if cues:
            return cues
    raw = parse_vtt(path)
    micros = sum(1 for cue in raw if cue.end - cue.start <= 0.05)
    if micros >= max(3, int(len(raw) * 0.2)):
        cues = committed_cues_from_youtube(raw)
    else:
        cues = collapse_rolling_cues(raw)
    return [cue for cue in merge_cues_to_sentences(cues) if cue.text.strip()]


def find_grok() -> Path | None:
    for name in ("grok", "grok.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    home = Path.home() / ".grok" / "bin" / "grok.exe"
    if home.is_file():
        return home
    return None


_GROK_ZH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "cues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "i": {"type": "integer"},
                    "zh": {"type": "string"},
                },
                "required": ["i", "zh"],
            },
        }
    },
    "required": ["cues"],
}

_GROK_ZH_SYSTEM = (
    "你是字幕组翻译。只翻译本条 en，禁止改写、补全或挪用下一句。\n"
    "prev_en/next_en 只是邻句语境，不要翻译它们，不要把它们的意思写进本条 zh。\n"
    "i 从 0 起连续编号，请求的每条 i 都必须输出一句中文。\n"
    "短英文用短中文：yeah/oh/there we go/morning 等语气词不要译成整句。\n"
    "术语：agent/agents=智能体或 Agent，禁止经纪人或特工；skill=技能；tool=工具；Claude=Claude。\n"
    "口播向简体，两行以内，不要解释、不要注音。"
)


def _grok_zh_system(source_lang: str = "en") -> str:
    lang = normalize_lang(source_lang) or "en"
    if lang == "en":
        return _GROK_ZH_SYSTEM
    name = source_lang_name(lang)
    return (
        f"你是字幕组翻译。源语言是{name}。字段 en 是本条原文，不一定是英语。\n"
        "只翻译本条 en，禁止改写、补全或挪用下一句。\n"
        "prev_en/next_en 只是邻句语境，不要翻译它们，不要把它们的意思写进本条 zh。\n"
        "i 从 0 起连续编号，请求的每条 i 都必须输出一句中文。\n"
        "短原文用短中文，语气词不要译成整句。\n"
        "口播向简体，两行以内，不要解释、不要注音、不要把原文抄进 zh。"
    )


def _zh_schema_for_batch(n: int) -> dict[str, Any]:
    schema = json.loads(json.dumps(_GROK_ZH_SCHEMA))
    cues = schema["properties"]["cues"]
    cues["minItems"] = n
    cues["maxItems"] = n
    return schema


def _parse_grok_cues(stdout: str) -> dict[int, str]:
    text = stdout.strip()
    if not text:
        return {}
    try:
        outer = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return {}
        outer = json.loads(match.group(0))
    if isinstance(outer, dict) and isinstance(outer.get("choices"), list) and outer["choices"]:
        msg = outer["choices"][0]
        if isinstance(msg, dict):
            content = (msg.get("message") or {}).get("content") if isinstance(msg.get("message"), dict) else msg.get("content")
            if isinstance(content, str) and content.strip():
                try:
                    outer = json.loads(content)
                except json.JSONDecodeError:
                    match = re.search(r"\{[\s\S]*\}", content)
                    outer = json.loads(match.group(0)) if match else outer
    inner = outer.get("text") if isinstance(outer, dict) else None
    payload = outer
    if isinstance(inner, str):
        try:
            payload = json.loads(inner)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", inner)
            payload = json.loads(match.group(0)) if match else {}
    cues = payload.get("cues") if isinstance(payload, dict) else None
    out: dict[int, str] = {}
    for item in cues or []:
        try:
            idx = int(item.get("i"))
            zh = str(item.get("zh") or "").strip()
        except (TypeError, ValueError, AttributeError):
            continue
        if zh:
            out[idx] = zh
    return out


def _zh_workers() -> int:
    raw = os.environ.get("GROK_ZH_WORKERS") or os.environ.get("YT_GROK_ZH_WORKERS") or "6"
    try:
        n = int(raw)
    except ValueError:
        n = 6
    return max(1, min(n, 8))


def _zh_batch_size(default: int) -> int:
    raw = os.environ.get("GROK_ZH_BATCH") or ""
    if not raw.strip():
        return default
    try:
        n = int(raw)
    except ValueError:
        return default
    return max(8, min(n, 80))


def _normalize_mapped(mapped: dict[int, str], n: int) -> dict[int, str]:
    if not mapped or n <= 0:
        return {}
    keys = set(mapped)
    if 0 not in keys and keys <= set(range(1, n + 1)) and (n in keys or n - 1 in keys):
        mapped = {idx - 1: zh for idx, zh in mapped.items()}
    return {idx: zh for idx, zh in mapped.items() if 0 <= idx < n and zh}


def _apply_zh_map(
    updated: list[BilingualCue],
    offset: int,
    batch: list[BilingualCue],
    mapped: dict[int, str],
) -> None:
    mapped = _normalize_mapped(mapped, len(batch))
    for i, zh in mapped.items():
        src = batch[i]
        updated[offset + i] = BilingualCue(src.start, src.end, zh, src.en)


def _zh_payload_indexed(
    all_rows: list[BilingualCue],
    indices: list[int],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for i, abs_i in enumerate(indices):
        prev_en = [all_rows[j].en for j in range(max(0, abs_i - 2), abs_i)]
        next_en = all_rows[abs_i + 1].en if abs_i + 1 < len(all_rows) else ""
        items.append(
            {
                "i": i,
                "en": all_rows[abs_i].en,
                "prev_en": prev_en,
                "next_en": next_en,
            }
        )
    return items


def _zh_batch_payload(
    all_rows: list[BilingualCue],
    offset: int,
    batch: list[BilingualCue],
) -> list[dict[str, Any]]:
    _ = batch
    return _zh_payload_indexed(all_rows, list(range(offset, offset + len(batch))))


def _run_zh_batch_http(
    offset: int,
    batch: list[BilingualCue],
    title: str,
    total: int,
    all_rows: list[BilingualCue],
    source_lang: str = "en",
) -> tuple[int, list[BilingualCue], dict[int, str]]:
    from youtube_audio_sync import grok_chat_json

    payload = _zh_batch_payload(all_rows, offset, batch)
    user = (
        f"视频标题：{title or '(unknown)'}\n"
        "输入：\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    print(
        f"grok: 中文翻译 {offset + 1}-{offset + len(batch)}/{total} (http)",
        flush=True,
    )
    data = grok_chat_json(
        [
            {"role": "system", "content": _grok_zh_system(source_lang)},
            {"role": "user", "content": user},
        ],
        _zh_schema_for_batch(len(batch)),
    )
    mapped = _parse_grok_cues(json.dumps(data, ensure_ascii=False))
    if not mapped:
        content = ""
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = json.dumps(data, ensure_ascii=False)[:2000]
        mapped = _parse_grok_cues(content if isinstance(content, str) else "")
    return offset, batch, mapped


def _run_zh_batch_cli(
    offset: int,
    batch: list[BilingualCue],
    title: str,
    total: int,
    grok: Path,
    all_rows: list[BilingualCue],
    source_lang: str = "en",
) -> tuple[int, list[BilingualCue], dict[int, str]]:
    payload = _zh_batch_payload(all_rows, offset, batch)
    prompt = (
        _grok_zh_system(source_lang)
        + f"\n视频标题：{title or '(unknown)'}\n输入：\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    prompt_file = Path(os.environ.get("TEMP") or ".") / f"yt-grok-zh-{os.getpid()}-{offset}.txt"
    schema = json.dumps(_zh_schema_for_batch(len(batch)), ensure_ascii=False, separators=(",", ":"))
    try:
        prompt_file.write_text(prompt, encoding="utf-8")
        cmd = [
            str(grok),
            "--prompt-file",
            str(prompt_file),
            "--output-format",
            "json",
            "--json-schema",
            schema,
            "--model",
            "grok-4.6",
            "--reasoning-effort",
            "low",
            "--max-turns",
            "1",
            "--no-subagents",
            "--disable-web-search",
            "--verbatim",
            "--always-approve",
        ]
        print(
            f"grok: 中文翻译 {offset + 1}-{offset + len(batch)}/{total} (cli)",
            flush=True,
        )
        result = subprocess.run(cmd, capture_output=True, timeout=180, check=False)
        stdout = (result.stdout or b"").decode("utf-8", errors="replace")
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace")
            print(
                f"warning: grok batch {offset} exit {result.returncode}: {stderr[-400:]}",
                file=sys.stderr,
                flush=True,
            )
            return offset, batch, {}
        return offset, batch, _parse_grok_cues(stdout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"warning: grok failed: {exc}", file=sys.stderr, flush=True)
        return offset, batch, {}
    finally:
        try:
            prompt_file.unlink(missing_ok=True)
        except OSError:
            pass


_FILLER_EN = {
    "yeah",
    "yep",
    "yup",
    "uh",
    "um",
    "oh",
    "ah",
    "whoo",
    "whoa",
    "wow",
    "hmm",
    "huh",
    "okay",
    "ok",
    "alright",
    "all right",
    "there",
    "there we go",
    "here",
    "well",
    "so",
    "and",
    "but",
    "morning",
    "it",
    "this",
    "that",
    "thank",
}


def _cjk_len(text: str) -> int:
    return sum(1 for ch in text or "" if "\u4e00" <= ch <= "\u9fff")


def _flag_bad_zh(rows: list[BilingualCue], source_lang: str = "en") -> list[int]:
    flagged: list[int] = []
    lang = normalize_lang(source_lang) or "en"
    for i, row in enumerate(rows):
        en = (row.en or "").strip()
        zh = (row.zh or "").strip()
        en_n = _en_token_count(en)
        src_n = _src_unit_count(en)
        cjk = _cjk_len(zh)
        filler = re.sub(r"[^a-z\s]", "", en.lower()).strip() in _FILLER_EN
        bad = False
        if not zh:
            bad = True
        elif lang == "en":
            if filler and cjk >= 6:
                bad = True
            elif en_n <= 2 and cjk >= 10:
                bad = True
            elif len(re.sub(r"[^A-Za-z0-9]", "", en)) >= 40 and cjk <= 4:
                bad = True
        elif src_n >= 8 and cjk <= 1:
            bad = True
        if bad:
            flagged.append(i)
    return flagged


def grok_optimize_zh(
    rows: list[BilingualCue],
    *,
    title: str = "",
    batch_size: int = 24,
    source_lang: str = "en",
) -> list[BilingualCue]:
    """Keep source times/text frozen; Grok HTTP translates Chinese in parallel."""
    if not rows:
        return rows
    lang = normalize_lang(source_lang) or "en"
    if lang == "zh":
        return [
            BilingualCue(row.start, row.end, row.zh or row.en, row.en)
            for row in rows
        ]
    batch_size = _zh_batch_size(batch_size)
    workers = _zh_workers()
    updated = list(rows)
    jobs = [
        (offset, rows[offset : offset + batch_size])
        for offset in range(0, len(rows), batch_size)
    ]
    print(
        f"grok: {len(rows)} cues, {len(jobs)} batches, {workers} workers, src={lang}",
        flush=True,
    )
    use_http = True
    try:
        from youtube_audio_sync import grok_api_token

        grok_api_token()
    except Exception as exc:  # noqa: BLE001
        print(f"warning: grok HTTP auth missing ({exc}); try CLI", file=sys.stderr, flush=True)
        use_http = False

    def run_job(offset: int, batch: list[BilingualCue]) -> tuple[int, list[BilingualCue], dict[int, str]]:
        if use_http:
            return _run_zh_batch_http(offset, batch, title, len(rows), updated, lang)
        grok = find_grok()
        if grok is None:
            return offset, batch, {}
        return _run_zh_batch_cli(offset, batch, title, len(rows), grok, updated, lang)

    try:
        probe_off, probe_batch = jobs[0]
        try:
            offset, batch, mapped = run_job(probe_off, probe_batch)
        except Exception as exc:
            if use_http and find_grok() is not None:
                print(f"warning: grok HTTP failed ({exc}); fall back to CLI", file=sys.stderr, flush=True)
                use_http = False
                offset, batch, mapped = run_job(probe_off, probe_batch)
            else:
                raise
        if use_http and not mapped and find_grok() is not None:
            print("warning: grok HTTP empty; fall back to CLI", file=sys.stderr, flush=True)
            use_http = False
            offset, batch, mapped = run_job(probe_off, probe_batch)
        _apply_zh_map(updated, offset, batch, mapped)
        if not mapped:
            print(f"warning: grok batch {offset} empty parse", file=sys.stderr, flush=True)
        rest = jobs[1:]
        if rest:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [pool.submit(run_job, off, bat) for off, bat in rest]
                for fut in as_completed(futs):
                    try:
                        off, bat, mapped = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        print(f"warning: grok worker failed: {exc}", file=sys.stderr, flush=True)
                        continue
                    if not mapped:
                        print(f"warning: grok batch {off} empty parse", file=sys.stderr, flush=True)
                        continue
                    _apply_zh_map(updated, off, bat, mapped)
        if use_http:
            bad = _flag_bad_zh(updated, lang)
            if bad:
                print(f"grok: zh repair {len(bad)} cues", flush=True)
                from youtube_audio_sync import grok_chat_json

                repair_size = 12
                chunks = [bad[i : i + repair_size] for i in range(0, len(bad), repair_size)]

                def repair_job(indices: list[int]) -> tuple[list[int], dict[int, str]]:
                    payload = _zh_payload_indexed(updated, indices)
                    user = (
                        f"视频标题：{title or '(unknown)'}\n"
                        "只重译下列可疑条，仍只译本条 en。\n输入：\n"
                        + json.dumps(payload, ensure_ascii=False)
                    )
                    data = grok_chat_json(
                        [
                            {"role": "system", "content": _grok_zh_system(lang)},
                            {"role": "user", "content": user},
                        ],
                        _zh_schema_for_batch(len(indices)),
                    )
                    mapped = _parse_grok_cues(json.dumps(data, ensure_ascii=False))
                    if not mapped:
                        try:
                            mapped = _parse_grok_cues(data["choices"][0]["message"]["content"])
                        except (KeyError, IndexError, TypeError):
                            mapped = {}
                    return indices, _normalize_mapped(mapped, len(indices))

                with ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as pool:
                    futs = [pool.submit(repair_job, chunk) for chunk in chunks]
                    for fut in as_completed(futs):
                        try:
                            indices, mapped = fut.result()
                        except Exception as exc:  # noqa: BLE001
                            print(f"warning: grok repair failed: {exc}", file=sys.stderr, flush=True)
                            continue
                        for i, zh in mapped.items():
                            abs_i = indices[i]
                            src = updated[abs_i]
                            updated[abs_i] = BilingualCue(src.start, src.end, zh, src.en)
    except Exception as exc:  # noqa: BLE001
        print(f"warning: grok 中文翻译 skipped: {exc}", file=sys.stderr, flush=True)
    filled = sum(1 for row in updated if row.zh)
    print(f"grok: zh filled {filled}/{len(updated)}", flush=True)
    return updated


def align_cues(
    en: list[Cue],
    zh: list[Cue],
    duration: float | None = None,
) -> list[BilingualCue]:
    """Native English is the time master (对轴); Chinese text is attached by overlap/nearest."""
    if not en and not zh:
        return []
    if not en:
        return [_clamp_bi(BilingualCue(z.start, z.end, z.text, ""), duration) for z in zh]
    unused = set(range(len(zh)))
    rows: list[BilingualCue] = []
    for eng in en:
        best_i = None
        best_ov = 0.0
        for i in unused:
            other = zh[i]
            ov = min(eng.end, other.end) - max(eng.start, other.start)
            if ov > best_ov:
                best_ov = ov
                best_i = i
        zh_text = ""
        if best_i is not None and best_ov >= 0.12:
            zh_text = zh[best_i].text
            unused.discard(best_i)
        elif zh:
            mid = (eng.start + eng.end) / 2
            nearest = None
            nearest_d = 1.2
            for i in unused:
                other = zh[i]
                dist = abs((other.start + other.end) / 2 - mid)
                if dist < nearest_d:
                    nearest_d = dist
                    nearest = i
            if nearest is not None:
                zh_text = zh[nearest].text
                unused.discard(nearest)
        if not eng.text and not zh_text:
            continue
        rows.append(_clamp_bi(BilingualCue(eng.start, eng.end, zh_text, eng.text), duration))
    for i in sorted(unused):
        other = zh[i]
        if len(other.text) < 2:
            continue
        rows.append(_clamp_bi(BilingualCue(other.start, other.end, other.text, ""), duration))
    rows.sort(key=lambda row: (row.start, row.end))
    for i in range(1, len(rows)):
        prev, cur = rows[i - 1], rows[i]
        if cur.start < prev.end:
            new_end = cur.start - 0.02
            if new_end > prev.start + 0.2:
                rows[i - 1] = BilingualCue(prev.start, new_end, prev.zh, prev.en)
    return rows


def _clamp_bi(row: BilingualCue, duration: float | None) -> BilingualCue:
    start, end = row.start, row.end
    if duration is not None:
        start = max(0.0, min(start, duration))
        end = max(start + 0.04, min(max(end, start + 0.35), duration))
    elif end - start < 0.35:
        end = start + 0.35
    return BilingualCue(start, end, row.zh, row.en)


def _ass_time(t: float) -> str:
    total_cs = max(0, int(round(t * 100)))
    hours, rem = divmod(total_cs, 360000)
    minutes, rem = divmod(rem, 6000)
    seconds, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"


def _srt_time(t: float) -> str:
    total_ms = max(0, int(round(t * 1000)))
    hours, rem = divmod(total_ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    seconds, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def _ass_text(text: str) -> str:
    text = text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
    return text.replace("\n", r"\N")


def write_bilingual_ass(
    path: Path,
    rows: list[BilingualCue],
    *,
    source_lang: str = "en",
) -> None:
    # 动漫字幕组常见 1080p 双语：底部双行，中文较大在上、原文较小在下。
    lang = normalize_lang(source_lang) or "en"
    src_font = "Arial" if lang == "en" else "Microsoft YaHei"
    title = f"zh-{lang} bilingual"
    header = f"""[Script Info]
Title: {title}
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CN,Microsoft YaHei,52,&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,2,48,48,78,1
Style: EN,{src_font},32,&H00DDDDDD,&H000000FF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,48,48,22,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for row in rows:
        start, end = _ass_time(row.start), _ass_time(row.end)
        if row.zh:
            lines.append(
                f"Dialogue: 0,{start},{end},CN,,0,0,0,,{_ass_text(row.zh)}\n"
            )
        if row.en:
            lines.append(
                f"Dialogue: 0,{start},{end},EN,,0,0,0,,{_ass_text(row.en)}\n"
            )
    path.write_text("".join(lines), encoding="utf-8")


def write_bilingual_srt(path: Path, rows: list[BilingualCue]) -> None:
    chunks: list[str] = []
    n = 0
    for row in rows:
        body = "\n".join(p for p in (row.zh, row.en) if p)
        if not body:
            continue
        n += 1
        chunks.append(
            f"{n}\n{_srt_time(row.start)} --> {_srt_time(row.end)}\n{body}\n"
        )
    path.write_text("\n".join(chunks) + ("\n" if chunks else ""), encoding="utf-8")


def parse_bilingual_srt(path: Path) -> list[BilingualCue]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    rows: list[BilingualCue] = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip() != ""]
        if len(lines) < 2:
            continue
        match = re.search(
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})\s+-->\s+(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})",
            lines[1] if re.match(r"^\d+$", lines[0]) else lines[0],
        )
        body_lines = lines[2:] if match and re.match(r"^\d+$", lines[0]) else lines[1:]
        if not match:
            continue
        start = _ts_to_sec(match.group(1), match.group(2), match.group(3), match.group(4))
        end = _ts_to_sec(match.group(5), match.group(6), match.group(7), match.group(8))
        zh, en = "", ""
        if len(body_lines) >= 2:
            zh, en = body_lines[0].strip(), " ".join(body_lines[1:]).strip()
        elif body_lines:
            text = body_lines[0].strip()
            has_han = bool(re.search(r"[\u4e00-\u9fff]", text))
            has_src = bool(
                re.search(r"[A-Za-z\u3040-\u30ff\uac00-\ud7af\u0400-\u04ff\u0600-\u06ff\u0e00-\u0e7f]", text)
            )
            if has_src and not has_han:
                en = text
            else:
                zh = text
        if zh or en:
            rows.append(BilingualCue(start, end, zh, en))
    return rows


def _find_vtt(dest: Path, video_id: str, cands: tuple[str, ...]) -> Path | None:
    files = {
        sub_lang_from_filename(path.name, video_id): path
        for path in list_subtitle_files(dest, video_id)
        if path.suffix.lower() == ".vtt"
    }
    for key in cands:
        path = files.get(key)
        if path and path.stat().st_size > 20:
            return path
    return None


def _find_orig_vtt(dest: Path, video_id: str) -> Path | None:
    files = {
        sub_lang_from_filename(path.name, video_id): path
        for path in list_subtitle_files(dest, video_id)
        if path.suffix.lower() == ".vtt"
    }
    for key, path in files.items():
        if str(key).endswith("-orig") and not str(key).lower().startswith("zh") and path.stat().st_size > 20:
            return path
    return None


def _find_source_vtt(dest: Path, video_id: str, source_lang: str | None) -> Path | None:
    path = _find_vtt(dest, video_id, source_caption_tags(source_lang))
    if path:
        return path
    lang = normalize_lang(source_lang)
    if lang and lang != "en":
        orig = _find_orig_vtt(dest, video_id)
        if orig:
            return orig
        return None
    return _find_vtt(dest, video_id, EMBED_EN) or _find_orig_vtt(dest, video_id)


def _youtube_word_clock(en_vtt: Path | None) -> list[tuple[str, float, float]]:
    if en_vtt is None or not Path(en_vtt).is_file():
        return []
    from youtube_audio_sync import _tokens

    clock: list[tuple[str, float, float]] = []
    for raw_w, t0, t1 in extract_youtube_words(en_vtt):
        text = (raw_w or "").strip()
        if text and _tokens(text):
            clock.append((text, t0, t1))
    return clock


def _retighten_from_audio(
    rows: list[BilingualCue],
    dest: Path,
    video_id: str,
    *,
    media: Path | None,
    ffmpeg: Path | None,
    grok_voice: bool,
    audio_align: bool,
    en_vtt: Path | None,
    source_lang: str = "en",
) -> list[BilingualCue]:
    """Prefer Grok listening to demuxed audio; YouTube karaoke clock is fallback."""
    from youtube_audio_sync import apply_word_times

    lang = normalize_lang(source_lang) or "en"
    if grok_voice and media is not None and ffmpeg is not None and Path(media).is_file():
        try:
            from youtube_audio_sync import sync_rows_to_grok_voice

            return sync_rows_to_grok_voice(
                rows, Path(media), dest, Path(ffmpeg), language=lang
            )
        except Exception as exc:  # noqa: BLE001 - keep existing times
            print(f"warning: grok-voice skipped: {exc}", file=sys.stderr, flush=True)
    if en_vtt:
        try:
            clock = _youtube_word_clock(en_vtt)
            if len(clock) >= 12:
                print(f"subs: retighten to YouTube word clock ({len(clock)} words)", flush=True)
                rows = apply_word_times(rows, clock)
        except Exception as exc:  # noqa: BLE001
            print(f"warning: word-clock skipped: {exc}", file=sys.stderr, flush=True)
    if audio_align and media is not None and ffmpeg is not None and Path(media).is_file():
        try:
            from youtube_audio_sync import sync_rows_to_media

            rows = sync_rows_to_media(
                rows, Path(media), dest, Path(ffmpeg), language=lang
            )
        except Exception as exc:  # noqa: BLE001
            print(f"warning: audio-align skipped: {exc}", file=sys.stderr, flush=True)
    return rows


def build_bilingual_subtitles(
    dest: Path,
    video_id: str,
    duration: float | None = None,
    *,
    title: str = "",
    use_grok: bool = True,
    media: Path | None = None,
    ffmpeg: Path | None = None,
    audio_align: bool = False,
    grok_voice: bool = True,
    source_lang: str = "auto",
    item: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    lang = detect_source_lang(item, explicit=source_lang, dest=dest, video_id=video_id)
    src_path = _find_source_vtt(dest, video_id, lang)
    zh_path = _find_vtt(dest, video_id, EMBED_ZH_HANS)
    print(f"subs: source language {lang} ({source_lang_name(lang)})", flush=True)
    rows: list[BilingualCue] = []
    from_speech = False
    if grok_voice and media is not None and ffmpeg is not None and Path(media).is_file():
        try:
            rows = rows_from_media_speech(
                Path(media), dest, Path(ffmpeg), en_vtt=src_path, language=lang
            )
            from_speech = True
            spoken = " ".join(row.en for row in rows[:40])
            lang = refine_source_lang(lang, spoken)
        except Exception as exc:  # noqa: BLE001 - fall back to YouTube source VTT
            print(f"warning: grok-voice captions skipped: {exc}", file=sys.stderr, flush=True)
    if not rows:
        if src_path is None and zh_path is None:
            return None
        src = sentence_cues_from_vtt(src_path) if src_path else []
        zh = sentence_cues_from_vtt(zh_path) if zh_path else []
        print(
            f"subs: sentence axis src={len(src)} zh={len(zh)} "
            f"(src={src_path.name if src_path else '-'}  zh={zh_path.name if zh_path else '-'})",
            flush=True,
        )
        rows = align_cues(src, zh, duration)
        if not rows:
            return None
        rows = _retighten_from_audio(
            rows,
            dest,
            video_id,
            media=media,
            ffmpeg=ffmpeg,
            grok_voice=False,
            audio_align=audio_align,
            en_vtt=src_path,
            source_lang=lang,
        )
    elif audio_align and media is not None and ffmpeg is not None:
        try:
            from youtube_audio_sync import sync_rows_to_media

            rows = sync_rows_to_media(
                rows, Path(media), dest, Path(ffmpeg), language=lang
            )
        except Exception as exc:  # noqa: BLE001
            print(f"warning: audio-align skipped: {exc}", file=sys.stderr, flush=True)
    if use_grok:
        rows = grok_optimize_zh(rows, title=title, source_lang=lang)
    ass_path = dest / f"{video_id}.zh-en.ass"
    srt_path = dest / f"{video_id}.zh-en.srt"
    write_bilingual_ass(ass_path, rows, source_lang=lang)
    write_bilingual_srt(srt_path, rows)
    source = "speech" if from_speech else "youtube"
    print(f"subs: bilingual {len(rows)} cues ({source}, {lang}) -> {ass_path.name}", flush=True)
    return {
        "ass": ass_path,
        "srt": srt_path,
        "cues": len(rows),
        "en": src_path,
        "zh": zh_path,
        "rows": rows,
        "source_lang": lang,
    }


def _ffmpeg_subtitles_arg(ass: Path) -> str:
    text = ass.resolve().as_posix().replace("\\", "/")
    text = text.replace(":", r"\:").replace("'", r"\'")
    return f"subtitles='{text}'"


def embed_subtitles_mp4(
    media: Path,
    dest: Path,
    video_id: str,
    ffmpeg: Path,
    *,
    duration: float | None = None,
    hardsub: bool = False,
    title: str = "",
    use_grok: bool = True,
    audio_align: bool = False,
    grok_voice: bool = True,
    source_lang: str = "auto",
    item: dict[str, Any] | None = None,
) -> bool:
    """对轴后内嵌双语：默认软字幕（中\\n原文）；--hardsub 则按 ASS 烧进画面。"""
    if media.suffix.lower() != ".mp4":
        print(f"warning: embed skip (not mp4): {media.name}", file=sys.stderr, flush=True)
        return False
    if not ffmpeg.is_file():
        print("warning: embed skip (ffmpeg missing)", file=sys.stderr, flush=True)
        return False
    existing = dest / f"{video_id}.zh-en.srt"
    built = None
    lang = detect_source_lang(item, explicit=source_lang, dest=dest, video_id=video_id)
    if existing.is_file() and not use_grok and not grok_voice:
        rows = parse_bilingual_srt(existing)
        if rows:
            print(f"relayout: reuse {existing.name} ({len(rows)} cues)", flush=True)
            src_vtt = _find_source_vtt(dest, video_id, lang)
            rows = _retighten_from_audio(
                rows,
                dest,
                video_id,
                media=media,
                ffmpeg=ffmpeg,
                grok_voice=grok_voice,
                audio_align=audio_align,
                en_vtt=src_vtt,
                source_lang=lang,
            )
            ass_path = dest / f"{video_id}.zh-en.ass"
            write_bilingual_ass(ass_path, rows, source_lang=lang)
            write_bilingual_srt(existing, rows)
            built = {"ass": ass_path, "srt": existing, "cues": len(rows), "source_lang": lang}
    if built is None:
        built = build_bilingual_subtitles(
            dest,
            video_id,
            duration,
            title=title,
            use_grok=use_grok,
            media=media,
            ffmpeg=ffmpeg,
            audio_align=audio_align,
            grok_voice=grok_voice,
            source_lang=source_lang,
            item=item,
        )
    if not built:
        print("warning: embed skip (no source/zh vtt to align)", file=sys.stderr, flush=True)
        return False
    lang = str(built.get("source_lang") or lang or "en")

    tmp = media.with_name(media.stem + ".embed.tmp.mp4")
    if hardsub:
        vf = _ffmpeg_subtitles_arg(built["ass"])
        cmd = [
            str(ffmpeg),
            "-hide_banner",
            "-y",
            "-i",
            str(media),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "fast",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(tmp),
        ]
        print(f"embed: hardsub ASS 中上原文下 -> {media.name}", flush=True)
        timeout = max(300, int(media.stat().st_size / 400_000) + 120)
    else:
        cmd = [
            str(ffmpeg),
            "-hide_banner",
            "-y",
            "-i",
            str(media),
            "-i",
            str(built["srt"]),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-map",
            "1:0",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-c:s",
            "mov_text",
            "-metadata:s:s:0",
            "language=zho",
            "-metadata:s:s:0",
            f"title={bilingual_track_title(lang)}",
            "-disposition:s:0",
            "default",
            "-movflags",
            "+faststart",
            str(tmp),
        ]
        print(f"embed: mux {bilingual_track_title(lang)} ({built['cues']} cues) -> {media.name}", flush=True)
        timeout = max(120, int(media.stat().st_size / 2_000_000) + 60)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"warning: embed failed: {exc}", file=sys.stderr, flush=True)
        if tmp.is_file():
            tmp.unlink(missing_ok=True)
        return False
    if result.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < 1024:
        err = (result.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()
        tail = "\n".join(err[-12:])
        print(f"warning: embed ffmpeg failed\n{tail}", file=sys.stderr, flush=True)
        if tmp.is_file():
            tmp.unlink(missing_ok=True)
        return False
    replaced = False
    last_err: Exception | None = None
    for attempt in range(6):
        try:
            os.replace(tmp, media)
            replaced = True
            break
        except PermissionError as exc:
            last_err = exc
            time.sleep(1.2)
    if not replaced:
        if tmp.is_file():
            tmp.unlink(missing_ok=True)
        print(
            f"warning: embed wrote {built['ass'].name} / {built['srt'].name} "
            f"but could not replace mp4 (file in use): {last_err}",
            file=sys.stderr,
            flush=True,
        )
        return False
    print(f"embed: ok  {built['ass'].name}  {built['srt'].name}", flush=True)
    return True


def relayout_dir(
    dest: Path,
    ffmpeg: Path | None = None,
    *,
    hardsub: bool = False,
    use_grok: bool = True,
    audio_align: bool = False,
    grok_voice: bool = True,
    source_lang: str = "auto",
) -> dict[str, Any]:
    """Re-run 对轴+排版+内嵌 on an already-downloaded video folder."""
    dest = Path(dest)
    if not dest.is_dir():
        die(f"not a directory: {dest}")
    mp4s = sorted(dest.glob("*.mp4"))
    media = dest / f"{dest.name}.mp4"
    if not media.is_file() and mp4s:
        media = mp4s[0]
    video_id = media.stem if media.is_file() else dest.name
    title = ""
    duration = None
    meta: dict[str, Any] = {}
    meta_path = dest / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
        title = str(meta.get("title") or "")
        if isinstance(meta.get("duration"), (int, float)):
            duration = float(meta["duration"])
    if media.is_file() and ffmpeg and ffmpeg.is_file():
        ok = embed_subtitles_mp4(
            media,
            dest,
            video_id,
            ffmpeg,
            duration=duration,
            hardsub=hardsub,
            title=title,
            use_grok=use_grok,
            audio_align=audio_align,
            grok_voice=grok_voice,
            source_lang=source_lang,
            item=meta,
        )
        return {"ok": ok, "media": str(media), "id": video_id}
    built = build_bilingual_subtitles(
        dest,
        video_id,
        duration,
        title=title,
        use_grok=use_grok,
        media=media if media.is_file() else None,
        ffmpeg=ffmpeg,
        audio_align=audio_align,
        grok_voice=grok_voice,
        source_lang=source_lang,
        item=meta,
    )
    if not built:
        die("no source/zh vtt to relayout")
    return {"ok": True, "media": None, "id": video_id, "cues": built["cues"]}


def write_subtitle_index(dest: Path, files: list[Path], video_id: str | None = None) -> Path:
    payload = [
        {
            "lang": sub_lang_from_filename(path.name, video_id),
            "file": path.name,
            "bytes": path.stat().st_size,
        }
        for path in files
    ]
    index = dest / "subtitles.json"
    index.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def _wants_translated_subs(langs: list[str] | None, auto: bool) -> bool:
    if not auto:
        return False
    wanted = langs or list(DEFAULT_SUB_LANGS)
    return any(
        item == "all" or item.startswith("zh")
        for item in wanted
    )


def write_subtitles(
    url: str,
    dest: Path,
    *,
    langs: list[str] | None = None,
    auto: bool = True,
    ffmpeg: str | None = None,
    item: dict[str, Any] | None = None,
) -> list[Path]:
    """Fetch WebVTT via timedtext URLs. Never used inside the video download pass."""
    del ffmpeg  # kept for call-site compatibility
    target = parse_target(url)
    if target.kind not in VIDEO_KINDS:
        die("subtitles need a single video url")
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    wanted = langs or list(DEFAULT_SUB_LANGS)
    info = item
    if info is None or not (info.get("subtitles") or info.get("automatic_captions")):
        info = extract_info(target.url)
    vid = str(info.get("id") or target.video_id or "")
    official = info.get("subtitles") or {}
    automatic = info.get("automatic_captions") or {} if auto else {}

    jobs: list[tuple[str, str]] = []
    seen_lang: set[str] = set()

    def add_job(lang: str, raw_url: str | None) -> None:
        if not raw_url or lang in seen_lang or lang == "live_chat":
            return
        seen_lang.add(lang)
        jobs.append((lang, _set_query(raw_url, fmt="vtt")))

    for lang, tracks in official.items():
        if _lang_wanted(str(lang), wanted):
            add_job(str(lang), _caption_vtt_url(tracks))
    if auto:
        for lang, tracks in automatic.items():
            if _lang_wanted(str(lang), wanted) and str(lang) not in seen_lang:
                add_job(str(lang), _caption_vtt_url(tracks))

    source = _best_source_caption_url(info, detect_source_lang(info))
    if source:
        for lang in wanted:
            if lang in seen_lang or lang in {"all", "en", "en-orig"}:
                continue
            if lang.startswith("zh") or lang in {"zh-Hans", "zh-Hant", "zh"}:
                add_job(lang, _set_query(source, fmt="vtt", tlang=lang))

    saved: list[Path] = []
    for i, (lang, cap_url) in enumerate(jobs):
        out = dest / f"{vid}.{lang}.vtt"
        if out.is_file() and out.stat().st_size > 20:
            saved.append(out)
            continue
        if i:
            time.sleep(0.8)
        try:
            data = _http_get_vtt(cap_url)
        except Exception as exc:  # noqa: BLE001 - one language must not abort the rest
            print(f"warning: skip subtitle {lang}: {exc}", file=sys.stderr, flush=True)
            continue
        out.write_bytes(data)
        print(f"subs: wrote {out.name} ({len(data)} bytes)", flush=True)
        saved.append(out)
    write_subtitle_index(dest, saved, vid)
    return saved


def _save_channel_profile(item: dict[str, Any], dest: Path, paths: dict[str, str]) -> None:
    if item.get("kind") == "channel" and not isinstance(item.get("about"), dict):
        attach_channel_profile(item)
    about = item.get("about") if isinstance(item.get("about"), dict) else {}
    avatar_url = item.get("avatar_url") or about.get("avatar_url")
    banner_url = item.get("banner_url") or about.get("banner_url")
    if avatar_url:
        try:
            avatar = download_image(str(avatar_url), dest / "avatar")
            paths["avatar"] = str(avatar)
            item["avatar_file"] = avatar.name
            if isinstance(item.get("about"), dict):
                item["about"]["avatar_file"] = avatar.name
        except Exception as exc:  # noqa: BLE001
            print(f"warning: skip avatar: {exc}", file=sys.stderr, flush=True)
    if banner_url:
        try:
            banner = download_image(str(banner_url), dest / "banner")
            paths["banner"] = str(banner)
            item["banner_file"] = banner.name
            if isinstance(item.get("about"), dict):
                item["about"]["banner_file"] = banner.name
        except Exception as exc:  # noqa: BLE001
            print(f"warning: skip banner: {exc}", file=sys.stderr, flush=True)
    about = item.get("about") if isinstance(item.get("about"), dict) else None
    if isinstance(about, dict):
        about_json = dest / "about.json"
        about_json.write_text(json.dumps(about, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["about"] = str(about_json)
        desc = str(about.get("description") or item.get("description") or "")
        about_txt = dest / "about.txt"
        about_txt.write_text(desc + ("\n" if desc and not desc.endswith("\n") else ""), encoding="utf-8")
        paths["about_txt"] = str(about_txt)


def save_item(item: dict[str, Any], dest: Path) -> dict[str, str]:
    dest.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    if item.get("kind") in LIST_KINDS:
        _save_channel_profile(item, dest, paths)
        entries = item.get("entries") or []
        videos = dest / "videos.json"
        videos.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        paths["videos"] = str(videos)
        lines = []
        for entry in entries:
            lines.append(
                "\t".join(
                    [
                        str(entry.get("id") or ""),
                        str(entry.get("duration_string") or ""),
                        str(entry.get("tab") or ""),
                        str(entry.get("upload_date") or ""),
                        str(entry.get("like_count") if entry.get("like_count") is not None else ""),
                        str(entry.get("title") or "").replace("\t", " "),
                        str(entry.get("url") or ""),
                    ]
                )
            )
        txt = dest / "videos.txt"
        txt.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        paths["txt"] = str(txt)
        channel_url = item.get("channel_url") or item.get("url")
        if channel_url:
            (dest / "channel.url").write_text(str(channel_url) + "\n", encoding="utf-8")
            paths["channel_url"] = str(dest / "channel.url")
    meta = dest / "meta.json"
    meta.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["meta"] = str(meta)
    watch = item.get("webpage_url") or item.get("url")
    if item.get("kind") in VIDEO_KINDS and watch:
        (dest / "watch.url").write_text(str(watch) + "\n", encoding="utf-8")
        paths["watch_url"] = str(dest / "watch.url")
    return paths


def print_text(item: dict[str, Any]) -> None:
    kind = item.get("kind") or "video"
    print(f"kind: {kind}")
    print(f"id: {item.get('id')}")
    print(f"title: {item.get('title')}")
    uploader = item.get("uploader") or item.get("channel")
    if uploader:
        print(f"uploader: {uploader}")
    if item.get("channel_id"):
        print(f"channel_id: {item.get('channel_id')}")
    if item.get("channel_url"):
        print(f"channel_url: {item.get('channel_url')}")
    followers = item.get("channel_follower_count")
    if followers is not None:
        print(f"subscribers: {followers}")
    if item.get("avatar_url"):
        print(f"avatar: {item.get('avatar_url')}")
    about_desc = ""
    if isinstance(item.get("about"), dict):
        about_desc = str(item["about"].get("description") or "")
    if not about_desc:
        about_desc = str(item.get("description") or "")
    if kind in LIST_KINDS and about_desc:
        snippet = about_desc.strip().splitlines()[0][:160]
        print(f"about: {snippet}")
    if kind in LIST_KINDS:
        counts = item.get("tab_counts") or {}
        print(f"entries: {item.get('entry_count')}")
        if counts:
            print(
                "tabs: "
                + ", ".join(
                    f"{name} {counts.get(name, 0)}"
                    for name in ("videos", "shorts", "streams")
                    if counts.get(name)
                )
            )
        print(f"url: {item.get('url')}")
        for entry in (item.get("entries") or [])[:30]:
            dur = entry.get("duration_string") or "-"
            tab = entry.get("tab") or "-"
            print(f"  {entry.get('id')}  {dur:>8}  {tab:<8}  {entry.get('title')}")
        extra = (item.get("entry_count") or 0) - min(30, item.get("entry_count") or 0)
        if extra > 0:
            print(f"  ... {extra} more")
        return

    dur = item.get("duration_string") or format_duration(item.get("duration"))
    if dur:
        print(f"duration: {dur} ({item.get('duration')}s)")
    if item.get("view_count") is not None:
        print(f"views: {item.get('view_count')}")
    if item.get("like_count") is not None:
        print(f"likes: {item.get('like_count')}")
    if item.get("comment_count") is not None:
        print(f"comments: {item.get('comment_count')}")
    if item.get("upload_date"):
        print(f"upload_date: {item.get('upload_date')}")
    if item.get("live_status"):
        print(f"live_status: {item.get('live_status')}")
    if item.get("availability"):
        print(f"availability: {item.get('availability')}")
    if item.get("tags"):
        print(f"tags: {', '.join(str(t) for t in item['tags'][:12])}")
    print(f"url: {item.get('url')}")
    if item.get("thumbnail"):
        print(f"cover: {item.get('thumbnail')}")
    chapters = item.get("chapters") or []
    if chapters:
        print(f"chapters: {len(chapters)}")
    heatmap = item.get("heatmap") or []
    if heatmap:
        print(f"heatmap: {len(heatmap)} points")
    subs = item.get("subtitles") or {}
    autos = item.get("automatic_captions") or {}
    if subs or autos:
        print(f"subtitles: {len(subs)} manual, {len(autos)} automatic")
        if subs:
            print(f"  manual: {', '.join(list(subs)[:20])}")
        orig_auto = [k for k in autos if str(k).endswith("-orig") or k in {"en", "zh", "zh-Hans", "zh-Hant"}]
        extra = orig_auto or list(autos)[:8]
        if extra:
            print(f"  auto: {', '.join(extra)}")
    boards = item.get("storyboards") or []
    if boards:
        print(f"storyboards: {len(boards)}")
    dash = item.get("dash") or {}
    if dash:
        video = dash.get("video") or {}
        audio = dash.get("audio") or {}
        print(f"dash: {dash.get('format')}  {dash.get('resolution')} (highest DASH)")
        print(
            f"dash_video: {video.get('id')}  {video.get('resolution')}  "
            f"{video.get('ext')}  {video.get('vcodec')}"
        )
        print(
            f"dash_audio: {audio.get('id')}  {audio.get('ext')}  {audio.get('acodec')}  "
            f"{audio.get('tbr')}k"
        )
    fmts = item.get("formats") or []
    dash_videos = sorted(
        (f for f in fmts if f.get("kind") == "dash_video"),
        key=_height,
        reverse=True,
    )
    print(f"formats: {len(fmts)}")
    for fmt in dash_videos[:8]:
        print(
            f"  {str(fmt.get('id') or ''):>8}  {str(fmt.get('resolution') or '-'):>12}  "
            f"{fmt.get('ext')}  {fmt.get('note') or ''}  {fmt.get('vcodec')}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse a YouTube video, playlist, or channel URL."
    )
    parser.add_argument("url", nargs="?", help="YouTube URL, video id, UC id, or @handle")
    parser.add_argument("--json", action="store_true")
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
        "--save",
        nargs="?",
        const=".",
        metavar="DIR",
        help="write meta.json (and videos.json for lists)",
    )
    parser.add_argument(
        "--subs",
        action="store_true",
        help="download WebVTT subtitles after parse (zh/en + auto; implies --save)",
    )
    parser.add_argument(
        "--sub-langs",
        default="",
        help="subtitle langs, comma-separated, regex ok (default: zh-Hans,zh-Hant,zh,en + orig)",
    )
    parser.add_argument(
        "--no-auto-subs",
        action="store_true",
        help="only official captions, skip YouTube ASR / translations",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    raw = args.url
    if not raw:
        try:
            raw = input("url: ").strip()
        except EOFError:
            raw = ""
    if not raw:
        die("need a YouTube url, video id, or @handle")
    limit = args.limit if args.limit and args.limit > 0 else None
    item = extract_info(
        raw,
        limit=limit,
        tab=args.tab,
        as_playlist=args.playlist,
        as_channel=args.channel,
    )
    saved = None
    root = None
    if args.save is not None or args.subs:
        root = Path(args.save).expanduser() if args.save not in {None, ".", ""} else Path.cwd() / safe_dirname(item)
        saved = save_item(item, root)
        item["saved"] = saved
    sub_files: list[Path] = []
    if args.subs:
        if item.get("kind") not in VIDEO_KINDS:
            die("subtitles need a single video url (not a channel/playlist list)")
        assert root is not None
        print("subtitles: downloading vtt (zh/en + auto unless --sub-langs/--no-auto-subs)", flush=True)
        sub_files = write_subtitles(
            item.get("webpage_url") or item.get("url") or raw,
            root,
            langs=parse_sub_langs(args.sub_langs),
            auto=not args.no_auto_subs,
            item=item,
        )
        item["subtitle_files"] = [p.name for p in sub_files]
    if args.json:
        print(json.dumps(item, ensure_ascii=False, indent=2))
    else:
        print_text(item)
        if saved:
            print(f"saved: {saved.get('meta')}")
        if args.subs:
            if sub_files:
                print(f"subs: {len(sub_files)}")
                for path in sub_files:
                    print(f"  {path.name}")
            else:
                print("subs: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
