# -*- coding: utf-8 -*-
"""Resolve a Jable actress / username and list every public video.

Does not download media. Used by the openDownload web board.
"""
from __future__ import annotations

import re
import time
import unicodedata
from html import unescape
from typing import Any, Callable
from urllib.parse import quote, unquote, urlparse

from jable_hot import (
    list_url,
    looks_like_list,
    parse_items,
    parse_last_page,
    parse_total,
)
from jable_http import DEFAULT_REFERER, HTML_ACCEPT, fetch_bytes, fetch_html, is_cloudflare, warmup

LogFn = Callable[[str], None]

BASE = "https://jable.tv"
MODEL_HREF_RE = re.compile(r"/models/([^/?#]+)/?", re.I)
SEARCH_HREF_RE = re.compile(r"/search/([^/?#]+)/?", re.I)
VIDEO_CODE_RE = re.compile(r"^[A-Za-z]{2,15}[-_]\d{2,8}[A-Za-z0-9._-]*$")
ASCII_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HEX_SLUG_RE = re.compile(r"^[a-f0-9]{32}$")
H2_RE = re.compile(r'<h2 class="h3-md mb-1">([^<]+)</h2>', re.I)
TOTAL_SPAN_RE = re.compile(r"([0-9][0-9,]*)\s*部影片")
KW_RE = re.compile(r'<meta\s+name=["\']keywords["\']\s+content=["\']([^"\']+)["\']', re.I)
AVATAR_RE = re.compile(
    r'<img class="avatar[^"]*"[^>]*src="(https://[^"]+)"',
    re.I,
)
MODEL_ON_VIDEO_RE = re.compile(
    r'<a[^>]*class="[^"]*\bmodel\b[^"]*"[^>]*href="https://jable\.tv/models/([^"/]+)/"[^>]*>'
    r'[\s\S]{0,500}?title="([^"]+)"',
    re.I,
)
NAME_FOLD = str.maketrans(
    {
        "结": "結",
        "亞": "亜",
        "亚": "亜",
        "丽": "麗",
        "实": "実",
        "實": "実",
        "樱": "桜",
        "櫻": "桜",
        "优": "優",
        "黑": "黒",
        "步": "歩",
        "宫": "宮",
        "泽": "沢",
        "濑": "瀬",
        "桥": "橋",
        "岛": "島",
        "崎": "崎",
        "儿": "児",
        "艳": "艶",
        "辉": "輝",
        "凉": "涼",
        "内": "内",
        "户": "戸",
        "广": "広",
        "滨": "浜",
        "濑": "瀬",
        "纮": "紘",
        "绘": "絵",
        "祯": "禎",
        "纯": "純",
        "纱": "紗",
        "里": "里",
        "香": "香",
        "奈": "奈",
    }
)
NAME_UNFOLD = str.maketrans({jp: cn for cn, jp in NAME_FOLD.items() if cn != jp})


def _log(log: LogFn | None, msg: str) -> None:
    if log:
        log(msg)


def fold_name(text: str) -> str:
    raw = unicodedata.normalize("NFKC", text or "")
    raw = raw.translate(NAME_FOLD)
    raw = re.sub(r"[\s・·．.\-_'’]+", "", raw)
    return raw.casefold()


def names_match(query: str, name: str) -> bool:
    a, b = fold_name(query), fold_name(name)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def name_variants(text: str) -> list[str]:
    raw = (text or "").strip()
    out: list[str] = []
    for item in (raw, raw.translate(NAME_FOLD), raw.translate(NAME_UNFOLD)):
        item = item.strip()
        if item and item not in out:
            out.append(item)
    return out


def keyword_slugs(html: str) -> list[str]:
    match = KW_RE.search(html or "")
    if not match:
        return []
    slugs: list[str] = []
    seen: set[str] = set()
    for part in unescape(match.group(1)).split(","):
        slug = slugify(part)
        if not slug or slug in seen or not ASCII_SLUG_RE.fullmatch(slug):
            continue
        if len(slug) < 4 or slug in {"av", "jav", "tv", "hd", "www", "jable", "http", "https"}:
            continue
        if HEX_SLUG_RE.fullmatch(slug) or is_video_code(slug):
            continue
        seen.add(slug)
        slugs.append(slug)
        bits = slug.split("-")
        if len(bits) == 2:
            rev = f"{bits[1]}-{bits[0]}"
            if rev not in seen and ASCII_SLUG_RE.fullmatch(rev):
                seen.add(rev)
                slugs.append(rev)
    return slugs


def slugify(text: str) -> str:
    raw = unicodedata.normalize("NFKC", (text or "").strip()).lower()
    raw = raw.replace("_", "-").replace(" ", "-")
    raw = re.sub(r"[^a-z0-9-]+", "", raw)
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    return raw


def is_video_code(text: str) -> bool:
    return bool(VIDEO_CODE_RE.fullmatch((text or "").strip()))


def looks_like_model_page(html: str) -> bool:
    if not html or is_cloudflare(html):
        return False
    return "title-with-avatar" in html and "部影片" in html and "/videos/" in html


def _decode(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")


def _get_html(url: str, *, retries: int = 2) -> tuple[str | None, str]:
    extra = []
    if "mode=async" in url:
        extra = ["-H", "X-Requested-With: XMLHttpRequest"]
    body, detail = fetch_bytes(
        url,
        timeout=30,
        referer=DEFAULT_REFERER,
        accept=HTML_ACCEPT,
        retries=retries,
        min_bytes=200,
        extra=extra or None,
    )
    if "http=404" in detail:
        return None, detail
    if not body:
        return None, detail
    html = _decode(body)
    if is_cloudflare(html):
        return None, detail + " cloudflare"
    return html, detail


def parse_model_header(html: str, slug: str, url: str) -> dict[str, Any]:
    h2 = H2_RE.search(html)
    name = unescape(h2.group(1)).strip() if h2 else slug
    total = 0
    tot = TOTAL_SPAN_RE.search(html)
    if tot:
        total = int(re.sub(r"[^\d]", "", tot.group(1)) or "0")
    cover = ""
    av = AVATAR_RE.search(html)
    if av:
        cover = av.group(1)
    return {
        "slug": slug,
        "name": name,
        "url": url,
        "count": total,
        "cover": cover,
        "html": html,
    }


def fetch_model(slug: str, log: LogFn | None = None) -> dict[str, Any] | None:
    slug = (slug or "").strip().strip("/")
    if not slug:
        return None
    url = f"{BASE}/models/{slug}/"
    _log(log, f"打开女優页 {url}")
    html, detail = _get_html(url, retries=2)
    if not html:
        _log(log, f"不是女優页 ({detail})")
        return None
    if not looks_like_model_page(html):
        return None
    info = parse_model_header(html, slug, url)
    _log(log, f"识别 {info['name']}  {info['count']} 部  /models/{slug}/")
    return info


def models_on_video_page(html: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for slug, name in MODEL_ON_VIDEO_RE.findall(html or ""):
        slug = slug.strip()
        name = unescape(name).strip()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        out.append({"slug": slug, "name": name})
    return out


def crawl_videos(
    path: str,
    *,
    term: str = "post_date",
    block_id: str = "list_videos_common_videos_list",
    html1: str | None = None,
    limit: int = 0,
    log: LogFn | None = None,
) -> list[dict[str, Any]]:
    path = "/" + path.strip("/") + "/"
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    page = 1
    total_pages = 1
    while True:
        if page == 1 and html1:
            html = html1
        else:
            page_url = list_url(path, term, page, block_id=block_id)
            _log(log, f"作品第 {page} 页")
            html, _diag = fetch_html(page_url, validate=looks_like_list)
        if page == 1:
            per_page = max(len(parse_items(html)), 24)
            total_hint = parse_total(html)
            total_pages = parse_last_page(html, per_page, total_hint)
            if total_hint:
                _log(log, f"共 {total_hint} 部 / {total_pages} 页")
        chunk = parse_items(html)
        if not chunk:
            break
        for row in chunk:
            code = str(row.get("code") or "").lower()
            if not code or code in seen:
                continue
            seen.add(code)
            items.append(row)
            if limit > 0 and len(items) >= limit:
                return items
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.12)
    return items


def _count_of(info: dict[str, Any] | None) -> int:
    if not info:
        return -1
    return int(info.get("count") or 0)


def _rank(info: dict[str, Any]) -> tuple[int, int]:
    slug = str(info.get("slug") or "")
    weak = 1 if info.get("search") or HEX_SLUG_RE.fullmatch(slug) else 0
    return (weak, -_count_of(info))


def _prefer(current: dict[str, Any] | None, other: dict[str, Any] | None) -> dict[str, Any] | None:
    if other is None:
        return current
    if current is None:
        return other
    return other if _rank(other) < _rank(current) else current


def _pick_model(query: str, candidates: list[dict[str, str]], log: LogFn | None) -> dict[str, Any] | None:
    hits = [
        c
        for c in candidates
        if names_match(query, c.get("name") or "") or slugify(query) == (c.get("slug") or "")
    ]
    if not hits:
        hits = list(candidates)
    best: dict[str, Any] | None = None
    for cand in hits:
        info = fetch_model(cand["slug"], log=log)
        best = _prefer(best, info)
    return best


def _models_from_first_video(videos: list[dict[str, Any]], log: LogFn | None) -> list[dict[str, str]]:
    if not videos:
        return []
    try:
        from jable_hls import fetch_html as fetch_video_html
        from jable_hls import normalize_url

        page_url = normalize_url(videos[0].get("url") or videos[0]["code"])
        _log(log, f"从作品页读取出演 {videos[0]['code']}")
        vhtml = fetch_video_html(page_url)
        linked = models_on_video_page(vhtml)
        if linked:
            _log(log, "出演: " + ", ".join(f"{x['name']}({x['slug']})" for x in linked[:6]))
        return linked
    except Exception as exc:  # noqa: BLE001
        _log(log, f"作品页出演解析失败: {exc}")
        return []


def _search_name(name: str, log: LogFn | None) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    qpath = f"/search/{quote(name, safe='')}/"
    search_url = BASE + qpath
    _log(log, f"按名字搜索 {name}")
    html, diag = _get_html(search_url, retries=3)
    if not html:
        _log(log, f"搜索失败：{name} ({diag})")
        return None, []
    videos = parse_items(html)
    total = parse_total(html) or len(videos)
    _log(log, f"搜索到 {total or len(videos)} 部（「{name}」）")
    search_info = {
        "slug": "",
        "name": name,
        "url": search_url,
        "count": total,
        "cover": (videos[0].get("cover") if videos else "") or "",
        "html": html,
        "search": True,
        "path": qpath,
        "block_id": "list_videos_videos_list_search_result",
        "term": "",
    }
    linked = _models_from_first_video(videos, log)
    return search_info, linked


def _upgrade_by_keywords(info: dict[str, Any], log: LogFn | None) -> dict[str, Any]:
    html = str(info.get("html") or "")
    best = info
    for slug in keyword_slugs(html):
        other = fetch_model(slug, log=log)
        best = _prefer(best, other) or best
    return best


def resolve_user(query: str, log: LogFn | None = None) -> dict[str, Any]:
    raw = (query or "").strip()
    if not raw:
        raise RuntimeError("请输入 Jable 用户名 / 女優名")
    warmup(timeout=15)

    parsed = urlparse(raw if re.match(r"https?://", raw, re.I) else "")
    path = parsed.path if parsed.path else raw

    m = MODEL_HREF_RE.search(path)
    if m and m.group(1):
        info = fetch_model(unquote(m.group(1)), log=log)
        if info:
            return _upgrade_by_keywords(info, log)
        raise RuntimeError(f"打不开女優页：{raw}")

    s = SEARCH_HREF_RE.search(path)
    search_q = unquote(s.group(1)) if s and s.group(1) else ""
    name = search_q or raw
    if re.match(r"https?://", name, re.I):
        name = unquote(urlparse(name).path.strip("/").split("/")[-1] or name)

    best: dict[str, Any] | None = None
    slug = slugify(name)
    if slug and ASCII_SLUG_RE.fullmatch(slug) and not is_video_code(slug):
        best = _prefer(best, fetch_model(slug, log=log))

    seen_slugs: set[str] = set()
    for variant in name_variants(name):
        search_info, linked = _search_name(variant, log)
        best = _prefer(best, search_info)
        hits = [
            c
            for c in linked
            if names_match(name, c.get("name") or "") or names_match(variant, c.get("name") or "")
        ] or linked
        for cand in hits:
            key = cand.get("slug") or ""
            if not key or key in seen_slugs:
                continue
            seen_slugs.add(key)
            info = fetch_model(key, log=log)
            if info:
                info = _upgrade_by_keywords(info, log)
                best = _prefer(best, info)

    if best:
        if best.get("slug"):
            _log(log, f"采用 {best.get('name')}  /models/{best.get('slug')}/  {best.get('count')} 部")
        else:
            _log(log, f"采用搜索结果 {best.get('name')}  {best.get('count')} 部")
        return best
    raise RuntimeError(f"找不到用户 / 女優：{name}")


def list_user_videos(query: str, *, limit: int = 0, log: LogFn | None = None) -> dict[str, Any]:
    info = resolve_user(query, log=log)
    if info.get("search"):
        path = str(info.get("path") or "/search/")
        block = str(info.get("block_id") or "list_videos_videos_list_search_result")
        term = str(info.get("term") or "")
        items = crawl_videos(
            path,
            term=term,
            block_id=block,
            html1=info.get("html"),
            limit=limit,
            log=log,
        )
        info["items"] = items
        return info
    items = crawl_videos(
        f"/models/{info['slug']}/",
        term="post_date",
        block_id="list_videos_common_videos_list",
        html1=info.get("html"),
        limit=limit,
        log=log,
    )
    info["items"] = items
    return info
