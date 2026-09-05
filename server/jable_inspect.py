# -*- coding: utf-8 -*-
"""从 jable.tv 作品页解析标题、演员、标签、日期（不依赖 HLS/m3u8）。"""
from __future__ import annotations

import json
import re
import threading
import time
from html import unescape
from typing import Any
from urllib.parse import unquote

CODE_OK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,40}$")
CACHE_TTL = 240.0

TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
OG_TITLE_RE = re.compile(
    r"""<meta\b[^>]*\bproperty=['"]og:title['"][^>]*\bcontent=['"]([^'"]+)['"]""",
    re.I,
)
OG_TITLE_RE_SWAP = re.compile(
    r"""<meta\b[^>]*\bcontent=['"]([^'"]+)['"][^>]*\bproperty=['"]og:title['"]""",
    re.I,
)
TWITTER_TITLE_RE = re.compile(
    r"""<meta\b[^>]*\bname=['"]twitter:title['"][^>]*\bcontent=['"]([^'"]+)['"]""",
    re.I,
)
HEADING_RE = re.compile(r"<h([1-4])\b[^>]*>([\s\S]*?)</h\1>", re.I)

OG_IMAGE_RE = re.compile(
    r"""<meta\b[^>]*\bproperty=['"]og:image['"][^>]*\bcontent=['"]([^'"]+)['"]""",
    re.I,
)
OG_IMAGE_RE_SWAP = re.compile(
    r"""<meta\b[^>]*\bcontent=['"]([^'"]+)['"][^>]*\bproperty=['"]og:image['"]""",
    re.I,
)
TWITTER_IMAGE_RE = re.compile(
    r"""<meta\b[^>]*\bname=['"]twitter:image['"][^>]*\bcontent=['"]([^'"]+)['"]""",
    re.I,
)
POSTER_RE = re.compile(
    r"""<video\b[^>]*\bposter=['"](https?://[^'"]+\.jpe?g[^'"]*)['"]""",
    re.I,
)
POSTER_ANY_RE = re.compile(
    r"""<video\b[^>]*\bposter=['"]((?:https?:)?//[^'"]+)['"]""",
    re.I,
)

# class="model" + /models/{slug}/ + 标签内 title（与 jable_user.MODEL_ON_VIDEO_RE 一致）
MODEL_ON_VIDEO_RE = re.compile(
    r'<a[^>]*class="[^"]*\bmodel\b[^"]*"[^>]*href="https://jable\.tv/models/([^"/]+)/"[^>]*>'
    r'[\s\S]{0,500}?title="([^"]+)"',
    re.I,
)
# title 写在 <a> 上：<a class="model" href=".../models/{slug}/" title="{name}">
MODEL_TITLE_ON_A_RE = re.compile(
    r"<a\b(?=[^>]*\bclass=['\"][^'\"]*\bmodel\b)(?=[^>]*href=['\"](?:https?://(?:www\.)?jable\.tv)?"
    r"/models/([^\"'/?#]+)/?['\"])(?=[^>]*\btitle=['\"]([^'\"]+)['\"])[^>]*>",
    re.I,
)
ANCHOR_RE = re.compile(r"<a\b([^>]*)>([\s\S]{0,1200}?)</a>", re.I)
HREF_MODEL_RE = re.compile(
    r"""href=['"](?:https?://(?:www\.)?jable\.tv)?/models/([^\"'/?#]+)""",
    re.I,
)
HREF_TAG_RE = re.compile(
    r"""href=['"](?:https?://(?:www\.)?jable\.tv)?/tags/([^\"'/?#]+)""",
    re.I,
)
HREF_CAT_RE = re.compile(
    r"""href=['"](?:https?://(?:www\.)?jable\.tv)?/categories/([^\"'/?#]+)""",
    re.I,
)
CATALOG_TAG_CLASS_RE = re.compile(r"""\bclass=['"][^'\"]*\btag\b""", re.I)
VIDEO_INFO_OPEN_RE = re.compile(
    r"""<div\b[^>]*\bclass=['"][^'\"]*\bvideo-info\b""",
    re.I,
)
TITLE_ATTR_RE = re.compile(r"""\btitle=['"]([^'"]+)['"]""", re.I)
IMG_TITLE_RE = re.compile(
    r"""<img\b[^>]*\b(?:title|alt)=['"]([^'"]+)['"]""",
    re.I,
)

DATE_LABEL_RE = re.compile(
    r"(?:上市於|上市于|上市日期|上市)\s*[:：]?\s*"
    r"(\d{4})[./\-年](\d{1,2})[./\-月](\d{1,2})",
    re.I,
)
DATE_NEAR_RE = re.compile(r"上市[於于]?")
DATE_YMD_RE = re.compile(r"(\d{4})[./\-年](\d{1,2})[./\-月](\d{1,2})日?")
INACTIVE_DATE_RE = re.compile(
    r"""class=['"][^'\"]*inactive-color[^'\"]*['\"][^>]*>\D{0,48}(\d{4}-\d{1,2}-\d{1,2})""",
    re.I,
)
DATETIME_ATTR_RE = re.compile(
    r"""\bdatetime=['"](\d{4}-\d{2}-\d{2})""",
    re.I,
)
META_DATE_RE = re.compile(
    r"""<meta\b[^>]*(?:itemprop|property|name)=['"](?:uploadDate|datePublished|releaseDate|video:release_date)['"]"""
    r"""[^>]*content=['"]([^'\"]+)['"]""",
    re.I,
)

DURATION_LABEL_RE = re.compile(
    r"(?:時長|时长|片長|片长|Duration)\s*[:：]?\s*(\d{1,3}:\d{2}(?::\d{2})?)",
    re.I,
)
DURATION_JS_RE = re.compile(
    r"""(?:videoDuration|video_duration|\bduration)\s*[:=]\s*['"](\d{1,3}:\d{2}(?::\d{2})?)['"]""",
    re.I,
)
LABEL_TIME_RE = re.compile(
    r"""<span\b[^>]*class=['"][^'\"]*\blabel\b[^'\"]*['\"][^>]*>\s*(\d{1,3}:\d{2}(?::\d{2})?)\s*</span>""",
    re.I,
)
ISO_DURATION_RE = re.compile(
    r"\bP(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?\b",
    re.I,
)
META_SECONDS_RE = re.compile(
    r"""<meta\b[^>]*(?:property|itemprop|name)=['"](?:video:duration|duration)['"][^>]*content=['"](\d+)['"]""",
    re.I,
)
JSONLD_RE = re.compile(
    r"""<script[^>]+type=['"]application/ld\+json['"][^>]*>([\s\S]*?)</script>""",
    re.I,
)
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>[\s\S]*?</\1>", re.I)

_GENERIC_SLUGS = frozenset(
    {
        "jable",
        "www",
        "http",
        "https",
        "index",
        "search",
        "video",
        "videos",
        "model",
        "models",
        "tag",
        "tags",
        "hot",
        "latest",
        "page",
        "null",
        "undefined",
        "javascript",
        "actresses",
        "categories",
    }
)
_SKIP_ACTOR_NAMES = frozenset(
    {
        "女優",
        "女优",
        "全部女優",
        "全部女优",
        "models",
        "model",
        "女優列表",
        "more",
        "首頁",
        "首页",
        "最後",
        "上一頁",
        "下一頁",
        "上一页",
        "下一页",
        "home",
        "last",
        "next",
        "prev",
        "previous",
    }
)
_SKIP_TAG_NAMES = frozenset(
    {
        "標籤",
        "标签",
        "tags",
        "tag",
        "更多",
        "更多標籤",
        "更多标签",
    }
)

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()
_HTML_CACHE: dict[str, tuple[float, str]] = {}
_HTML_LOCK = threading.Lock()
_HTML_EVENTS: dict[str, threading.Event] = {}
_HTML_TTL = 90.0


def _clean(text: str) -> str:
    text = unescape(text or "")
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def _visible_text(inner: str) -> str:
    return _clean(re.sub(r"<[^>]+>", " ", inner or ""))


def _abs_url(url: str) -> str:
    url = unescape((url or "").strip())
    if url.startswith("//"):
        return "https:" + url
    return url


def _first_jpg(*candidates: str | None) -> str:
    fallback = ""
    for item in candidates:
        if not item:
            continue
        url = _abs_url(item)
        if not url.startswith("http"):
            continue
        if re.search(r"\.jpe?g(\?|$)", url, re.I):
            return url
        if not fallback:
            fallback = url
    return fallback


def _strip_site_suffix(title: str) -> str:
    title = _clean(title)
    title = re.sub(r"\s*[-|–—]\s*Jable\.TV\b.*$", "", title, flags=re.I)
    title = re.sub(r"\s*\|\s*Jable\b.*$", "", title, flags=re.I)
    return title.strip(" -|")


def _normalize_code(code: str) -> str:
    return (code or "").strip().lower()


def _looks_like_video_page(html: str) -> bool:
    if not html:
        return False
    try:
        from jable_http import is_cloudflare
    except ImportError:
        is_cloudflare = None  # type: ignore[assignment]
    if is_cloudflare is not None and is_cloudflare(html):
        return False
    low = html.lower()
    return "/videos/" in low or "og:title" in low or "models/" in low


def _ok_slug(slug: str) -> bool:
    slug = (slug or "").strip()
    return bool(slug) and slug not in _GENERIC_SLUGS and slug not in {".", ".."}


def _norm_slug(raw: str) -> str:
    return unquote(raw or "").strip().strip("/").lower()


def _ymd(year: str | int, month: str | int, day: str | int) -> str:
    try:
        yi, mi, di = int(year), int(month), int(day)
    except (TypeError, ValueError):
        return ""
    if not (1990 <= yi <= 2100 and 1 <= mi <= 12 and 1 <= di <= 31):
        return ""
    return f"{yi:04d}-{mi:02d}-{di:02d}"


def _date_from_text(text: str) -> str:
    match = DATE_YMD_RE.search(text or "")
    if not match:
        return ""
    return _ymd(match.group(1), match.group(2), match.group(3))


def _normalize_clock(text: str) -> str:
    match = re.fullmatch(r"(\d{1,3}):(\d{2})(?::(\d{2}))?", (text or "").strip())
    if not match:
        return ""
    if match.group(3) is not None:
        hours, minutes, seconds = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if minutes > 59 or seconds > 59:
            return ""
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    minutes, seconds = int(match.group(1)), int(match.group(2))
    if minutes > 59 or seconds > 59:
        return ""
    return f"{minutes:02d}:{seconds:02d}"


def _iso_duration(text: str) -> str:
    match = ISO_DURATION_RE.search(text or "")
    if not match:
        return ""
    days = int(match.group(1) or 0)
    hours = int(match.group(2) or 0) + days * 24
    minutes = int(match.group(3) or 0)
    seconds = int(float(match.group(4) or 0))
    if not any(match.groups()):
        return ""
    if minutes > 59 or seconds > 59:
        minutes, extra = minutes % 60, minutes // 60
        hours += extra
        seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _seconds_clock(raw: str) -> str:
    try:
        total = int(raw)
    except (TypeError, ValueError):
        return ""
    if total <= 0 or total > 24 * 3600:
        return ""
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _jsonld_video(html: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for raw in JSONLD_RE.findall(html or ""):
        text = _clean(raw)
        if not text:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        nodes: list[Any] = data if isinstance(data, list) else [data]
        graph = data.get("@graph") if isinstance(data, dict) else None
        if isinstance(graph, list):
            nodes = graph
        for node in nodes:
            if not isinstance(node, dict):
                continue
            ntype = node.get("@type") or node.get("type") or ""
            if isinstance(ntype, list):
                ntype = " ".join(str(x) for x in ntype)
            if ntype and "video" not in str(ntype).lower() and not out:
                continue
            if not out.get("name") and node.get("name"):
                out["name"] = str(node.get("name") or "")
            thumb = node.get("thumbnailUrl") or node.get("thumbnail")
            if isinstance(thumb, list) and thumb:
                thumb = thumb[0]
            if not out.get("cover") and isinstance(thumb, str):
                out["cover"] = thumb
            if not out.get("date") and node.get("uploadDate"):
                out["date"] = str(node.get("uploadDate") or "")
            if not out.get("duration") and node.get("duration"):
                out["duration"] = str(node.get("duration") or "")
            if out.get("name") and out.get("cover") and out.get("date"):
                return out
    return out


def _parse_title(html: str, jsonld: dict[str, Any]) -> str:
    match = TITLE_RE.search(html or "")
    if match:
        title = _strip_site_suffix(match.group(1))
        if title:
            return title
    for regex in (OG_TITLE_RE, OG_TITLE_RE_SWAP, TWITTER_TITLE_RE):
        og = regex.search(html or "")
        if og:
            title = _strip_site_suffix(og.group(1))
            if title:
                return title
    if jsonld.get("name"):
        title = _strip_site_suffix(str(jsonld["name"]))
        if title:
            return title
    for _level, inner in HEADING_RE.findall(html or ""):
        title = _strip_site_suffix(_visible_text(inner))
        if title and title.casefold() not in {"jable", "jable.tv", "熱門", "热门"}:
            return title
    return ""


def _parse_cover(html: str, jsonld: dict[str, Any]) -> str:
    og = None
    og_match = OG_IMAGE_RE.search(html or "") or OG_IMAGE_RE_SWAP.search(html or "")
    if og_match:
        og = og_match.group(1)
    twitter = None
    tw = TWITTER_IMAGE_RE.search(html or "")
    if tw:
        twitter = tw.group(1)
    poster = None
    poster_match = POSTER_RE.search(html or "") or POSTER_ANY_RE.search(html or "")
    if poster_match:
        poster = poster_match.group(1)
    return _first_jpg(og, poster, twitter, jsonld.get("cover") if jsonld else None)


def _parse_date(html: str, jsonld: dict[str, Any]) -> str:
    labeled = DATE_LABEL_RE.search(html or "")
    if labeled:
        got = _ymd(labeled.group(1), labeled.group(2), labeled.group(3))
        if got:
            return got
    for found in DATE_NEAR_RE.finditer(html or ""):
        got = _date_from_text(html[found.start() : found.start() + 240])
        if got:
            return got
    inactive = INACTIVE_DATE_RE.search(html or "")
    if inactive:
        got = _date_from_text(inactive.group(1))
        if got:
            return got
    dt = DATETIME_ATTR_RE.search(html or "")
    if dt:
        got = _date_from_text(dt.group(1))
        if got:
            return got
    meta = META_DATE_RE.search(html or "")
    if meta:
        got = _date_from_text(meta.group(1))
        if got:
            return got
    if jsonld.get("date"):
        got = _date_from_text(str(jsonld["date"]))
        if got:
            return got
    return ""


def _parse_duration(html: str, jsonld: dict[str, Any]) -> str:
    labeled = DURATION_LABEL_RE.search(html or "")
    if labeled:
        clock = _normalize_clock(labeled.group(1))
        if clock:
            return clock
    if jsonld.get("duration"):
        raw = str(jsonld["duration"])
        clock = _iso_duration(raw) or _normalize_clock(raw)
        if clock:
            return clock
    iso = ISO_DURATION_RE.search(html or "")
    if iso:
        clock = _iso_duration(iso.group(0))
        if clock:
            return clock
    js = DURATION_JS_RE.search(html or "")
    if js:
        clock = _normalize_clock(js.group(1))
        if clock:
            return clock
    sec = META_SECONDS_RE.search(html or "")
    if sec:
        clock = _seconds_clock(sec.group(1))
        if clock:
            return clock
    label = LABEL_TIME_RE.search(html or "")
    if label:
        clock = _normalize_clock(label.group(1))
        if clock:
            return clock
    return ""


def _ok_actor_name(name: str) -> bool:
    text = _clean(name)
    if not text or text.casefold() in _SKIP_ACTOR_NAMES:
        return False
    if text.startswith(("«", "»", "‹", "›")) or "首頁" in text or "首页" in text:
        return False
    if re.fullmatch(r"[a-f0-9]{32}", text, re.I):
        return False
    return True


def _add_person(out: list[dict[str, str]], seen: set[str], slug: str, name: str) -> None:
    slug = _norm_slug(slug)
    name = _clean(name)
    if not _ok_slug(slug) or slug in seen:
        return
    if name and not _ok_actor_name(name):
        return
    if not name:
        name = slug
    if not _ok_actor_name(name):
        return
    seen.add(slug)
    out.append({"name": name, "slug": slug})


def _add_tag(
    out: list[dict[str, str]], seen: set[str], slug: str, name: str, kind: str = "tag"
) -> None:
    slug = _norm_slug(slug)
    name = _clean(name)
    key = f"{kind}:{slug}"
    if not _ok_slug(slug) or key in seen:
        return
    if name.casefold() in _SKIP_TAG_NAMES:
        name = ""
    if not name:
        name = slug
    seen.add(key)
    row = {"name": name, "slug": slug}
    if kind and kind != "tag":
        row["kind"] = kind
    out.append(row)


def _video_scope(html: str) -> str:
    """作品信息区；页脚那一整页目录标签不在这里。"""
    raw = html or ""
    m = VIDEO_INFO_OPEN_RE.search(raw)
    if not m:
        return raw
    return raw[m.start() : m.start() + 16000]


def _tag_blocks(scope: str) -> list[str]:
    blocks: list[str] = []
    for inner in re.findall(r"<h5\b[^>]*>([\s\S]*?)</h5>", scope or "", re.I):
        if "/tags/" in inner or "/categories/" in inner:
            blocks.append(inner)
    return blocks


def _collect_typed_links(html: str, out: list[dict[str, str]], seen: set[str]) -> None:
    for attrs, inner in ANCHOR_RE.findall(html or ""):
        cat = HREF_CAT_RE.search(attrs)
        tag = HREF_TAG_RE.search(attrs)
        if not cat and not tag:
            continue
        if tag and CATALOG_TAG_CLASS_RE.search(attrs):
            continue
        visible = _visible_text(inner)
        title = ""
        t = TITLE_ATTR_RE.search(attrs)
        if t:
            title = t.group(1)
        name = visible or title
        if cat:
            _add_tag(out, seen, cat.group(1), name, "cat")
        else:
            _add_tag(out, seen, tag.group(1), name, "tag")


def _parse_actors(html: str) -> list[dict[str, str]]:
    actors: list[dict[str, str]] = []
    seen: set[str] = set()
    for slug, name in MODEL_TITLE_ON_A_RE.findall(html or ""):
        _add_person(actors, seen, slug, name)
    for slug, name in MODEL_ON_VIDEO_RE.findall(html or ""):
        _add_person(actors, seen, slug, name)
    for attrs, inner in ANCHOR_RE.findall(html or ""):
        if not re.search(r"\bclass=['\"][^'\"]*\bmodel\b", attrs or "", re.I):
            continue
        href = HREF_MODEL_RE.search(attrs)
        if not href:
            continue
        slug = href.group(1)
        title = ""
        t = TITLE_ATTR_RE.search(attrs)
        if t:
            title = t.group(1)
        if not title:
            img = IMG_TITLE_RE.search(inner)
            if img:
                title = img.group(1)
        visible = _visible_text(inner)
        name = title or visible
        if not name:
            continue
        _add_person(actors, seen, slug, name)
    return actors


def _parse_tags(html: str) -> list[dict[str, str]]:
    """只收本片类型：video-info 里的分类 + 标签，排除页脚目录。"""
    tags: list[dict[str, str]] = []
    seen: set[str] = set()
    scope = _video_scope(html)
    blocks = _tag_blocks(scope)
    if blocks:
        for block in blocks:
            _collect_typed_links(block, tags, seen)
        if tags:
            return tags
    _collect_typed_links(scope, tags, seen)
    if tags:
        return tags
    _collect_typed_links(html or "", tags, seen)
    return tags


def _strip_noise(html: str) -> str:
    return SCRIPT_STYLE_RE.sub(" ", html or "")


def _copy_info(info: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": info.get("id") or "",
        "title": info.get("title") or "",
        "url": info.get("url") or "",
        "cover": info.get("cover") or "",
        "date": info.get("date") or "",
        "duration": info.get("duration") or "",
        "actors": [dict(row) for row in (info.get("actors") or [])],
        "tags": [dict(row) for row in (info.get("tags") or [])],
    }


def parse_inspect_html(html: str, code: str) -> dict[str, Any]:
    """从作品页 HTML 提取标题、演员、标签、日期（纯解析，无网络）。"""
    raw = html or ""
    cid = _normalize_code(code)
    jsonld = _jsonld_video(raw)
    title = _parse_title(raw, jsonld)
    cover = _parse_cover(raw, jsonld)
    body = _strip_noise(raw)
    date = _parse_date(body, jsonld) or _parse_date(raw, jsonld)
    duration = _parse_duration(body, jsonld) or _parse_duration(raw, jsonld)
    actors = _parse_actors(body)
    tags = _parse_tags(body)
    return {
        "id": cid,
        "title": title,
        "url": f"https://jable.tv/videos/{cid}/" if cid else "",
        "cover": cover,
        "date": date,
        "duration": duration,
        "actors": actors,
        "tags": tags,
    }


def _html_has_hls(html: str) -> bool:
    return "hlsurl" in (html or "").lower()


def _ingest_inspect_work(info: dict[str, Any], key: str) -> None:
    try:
        from .jable_index import ingest_works

        ingest_works(
            [
                {
                    "id": info.get("id") or key,
                    "title": info.get("title") or "",
                    "cover": info.get("cover") or "",
                    "duration": info.get("duration") or "",
                    "date": info.get("date") or "",
                    "actors": info.get("actors") or [],
                }
            ]
        )
    except Exception:
        pass


def _try_seed_play(key: str, url: str, html: str) -> None:
    try:
        from .jable_lists import remember_play_html

        remember_play_html(key, url, html)
    except Exception:
        pass


def fetch_video_html(code: str, *, need_hls: bool = False) -> str:
    """抓取作品页 HTML，inspect / play 共用，避免同一番号打两次。

    用户点击走 priority 请求，并短暂压住后台标签缓存，免得卡在 429 队列里。
    """
    key = (code or "").strip().lower()
    if not key:
        raise RuntimeError("缺少番号")
    now = time.time()
    wait_ev: threading.Event | None = None
    owner = False
    with _HTML_LOCK:
        hit = _HTML_CACHE.get(key)
        if hit and now - hit[0] < _HTML_TTL:
            html = hit[1]
            if html and ((not need_hls) or _html_has_hls(html)):
                return html
        wait_ev = _HTML_EVENTS.get(key)
        if wait_ev is None:
            wait_ev = threading.Event()
            _HTML_EVENTS[key] = wait_ev
            owner = True
    if not owner:
        if not wait_ev.wait(timeout=12):
            raise RuntimeError("无法获取作品页（站点拦截或网络失败）")
        with _HTML_LOCK:
            hit = _HTML_CACHE.get(key)
        if hit and hit[1] and ((not need_hls) or _html_has_hls(hit[1])):
            return hit[1]
        raise RuntimeError("无法获取作品页（站点拦截或网络失败）")
    url = f"https://jable.tv/videos/{key}/"
    try:
        from jable_http import fetch_html, hold_crawlers

        hold_crawlers(60.0)

        def _ok(text: str) -> bool:
            if not _looks_like_video_page(text):
                return False
            if need_hls:
                return _html_has_hls(text)
            return True

        html, _detail = fetch_html(
            url,
            timeout=8,
            retries=1,
            validate=_ok,
            priority=True,
        )
        if not html or not str(html).strip():
            raise RuntimeError("无法获取作品页（站点拦截或网络失败）")
        info = parse_inspect_html(html, key)
        with _CACHE_LOCK:
            _CACHE[key] = (time.time(), info)
        with _HTML_LOCK:
            _HTML_CACHE[key] = (time.time(), html)
        _ingest_inspect_work(info, key)
        _try_seed_play(key, url, html)
        return html
    except (SystemExit, RuntimeError, OSError) as exc:
        text = str(exc) or ""
        if "1015" in text or "rate limited" in text.lower():
            raise RuntimeError("站点限流（Cloudflare 1015），已暂停后台抓取，请几分钟后再试") from exc
        raise RuntimeError("无法获取作品页（站点拦截或网络失败）") from exc
    finally:
        with _HTML_LOCK:
            _HTML_EVENTS.pop(key, None)
        if wait_ev is not None:
            wait_ev.set()


def inspect_info(code: str) -> dict[str, Any]:
    """抓取 https://jable.tv/videos/{code}/ 并解析作品详情，进程内缓存约 4 分钟。

    与 play 共用同一页 HTML；若页内有 var hlsUrl，会一并写入播放缓存。
    """
    raw = (code or "").strip()
    if not raw:
        raise RuntimeError("缺少番号")
    if not CODE_OK_RE.fullmatch(raw):
        raise RuntimeError("番号无效")
    key = raw.lower()
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < CACHE_TTL:
            return _copy_info(hit[1])
    html = fetch_video_html(key, need_hls=False)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit:
            return _copy_info(hit[1])
    return _copy_info(parse_inspect_html(html, key))
