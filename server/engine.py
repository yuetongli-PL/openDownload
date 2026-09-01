# -*- coding: utf-8 -*-
"""Detect site, parse a preview (no download), then build download commands.

Engines live in ../python (copied from the original folders). Nothing here
imports or shells out to Desktop\\Jable / Youtube / 抖音.
"""
from __future__ import annotations

import json
import re
import sys
from contextlib import contextmanager
from typing import Any, Callable, Iterator
from urllib.parse import parse_qs, urlparse

from .paths import PY_ROOT, cookie_path, find_ffmpeg, find_python, library_dir, load_settings

LogFn = Callable[[str], None]


def _log(log: LogFn | None, msg: str) -> None:
    if log:
        log(msg)


def _host(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def first_url(text: str) -> str:
    found = re.search(r"https?://[^\s]+", text or "")
    return found.group(0) if found else (text or "").strip()


YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
UC_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
JABLE_CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{1,40}$")
JABLE_VIDEO_CODE_RE = re.compile(r"^[A-Za-z]{2,15}[-_]\d{2,8}[A-Za-z0-9._-]*$")
JABLE_HYPHEN_RE = JABLE_VIDEO_CODE_RE
DIGIT_ID_RE = re.compile(r"^\d{5,}$")
HANDLE_RE = re.compile(r"^@[^/\s?]+$")

YOUTUBE_HOSTS = {
    "youtu.be",
    "youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "youtubekids.com",
}
DOUYIN_HOSTS = {"douyin.com", "iesdouyin.com", "v.douyin.com"}
JABLE_HOSTS = {"jable.tv"}
SITES = ("auto", "jable", "youtube", "douyin")


def detect(query: str, site: str = "auto") -> dict[str, Any]:
    raw = (query or "").strip()
    site = (site or "auto").strip().lower()
    if site not in SITES:
        site = "auto"
    if not raw:
        return {"site": site if site != "auto" else "unknown", "kind": "empty", "query": raw, "url": ""}

    url = first_url(raw)
    host = _host(url) if re.match(r"https?://", url, re.I) else ""

    guessed = "unknown"
    kind = "unknown"
    if host:
        if host in JABLE_HOSTS or host.endswith(".jable.tv"):
            guessed, kind = "jable", _jable_url_kind(url)
        elif host in YOUTUBE_HOSTS or host.endswith(".youtube.com"):
            guessed, kind = "youtube", "url"
        elif host in DOUYIN_HOSTS or host.endswith(".douyin.com") or host.endswith(".iesdouyin.com"):
            guessed, kind = "douyin", "url"
    elif HANDLE_RE.fullmatch(raw) or UC_RE.fullmatch(raw):
        guessed, kind = "youtube", "channel"
    elif YT_ID_RE.fullmatch(raw):
        guessed, kind = "youtube", "video"
    elif raw.startswith("#") and len(raw) > 1:
        guessed, kind = "douyin", "hashtag"
    elif JABLE_HYPHEN_RE.fullmatch(raw):
        guessed, kind = "jable", "video"
    elif DIGIT_ID_RE.fullmatch(raw) and len(raw) >= 16:
        guessed, kind = "douyin", "video"

    locked = site if site != "auto" else guessed
    if site == "auto" and guessed == "unknown":
        return {
            "site": "unknown",
            "kind": "need-site",
            "query": raw,
            "url": url if host else "",
            "message": "无法从内容判断站点，请先点上方 Jable / YouTube / 抖音",
        }
    if site != "auto" and guessed not in {"unknown", site}:
        # honor the router even if the string looks like another site
        locked = site

    if locked == "youtube" and kind in {"unknown", "url"}:
        path = (urlparse(url).path or "").lower() if host else ""
        if "/playlist" in path:
            kind = "playlist"
        elif "/shorts/" in path or "/watch" in path or host == "youtu.be":
            kind = "video"
        elif (
            HANDLE_RE.fullmatch(raw)
            or UC_RE.fullmatch(raw)
            or "/@" in path
            or "/channel/" in path
            or "/c/" in path
            or "/user/" in path
        ):
            kind = "channel"
        elif not host and not YT_ID_RE.fullmatch(raw):
            kind = "channel"
        elif YT_ID_RE.fullmatch(raw):
            kind = "video"
    if locked == "jable" and kind in {"unknown", "url"}:
        kind = _jable_url_kind(url if host else raw)
    if locked == "douyin" and kind in {"unknown", "url"}:
        if raw.startswith("#"):
            kind = "hashtag"
        elif not host:
            kind = "user" if not DIGIT_ID_RE.fullmatch(raw) else "video"

    return {"site": locked, "kind": kind, "query": raw, "url": url if host else ""}


def _jable_url_kind(raw: str) -> str:
    text = (raw or "").strip()
    if re.search(r"\.m3u8($|[?#])", text, re.I):
        return "video"
    if re.search(r"/videos/[A-Za-z0-9._-]+", text, re.I):
        return "video"
    model = re.search(r"/models/([^/?#]+)", text, re.I)
    if model and model.group(1):
        return "user"
    if re.search(r"/search/([^/?#]+)", text, re.I):
        return "user"
    if JABLE_VIDEO_CODE_RE.fullmatch(text):
        return "video"
    if JABLE_CODE_RE.fullmatch(text) and re.search(r"\d", text) and "://" not in text:
        return "video"
    if re.search(r"/(hot|categories|tags|amateur|actresses|latest-updates|new-release)/", text, re.I):
        return "list"
    if re.search(r"/models/?$", text, re.I):
        return "list"
    if re.search(r"jable\.tv/?$", text, re.I):
        return "list"
    if "://" not in text:
        return "user"
    return "video"


@contextmanager
def _stdio_to_log(log: LogFn | None) -> Iterator[None]:
    if not log:
        yield
        return

    class Tee:
        def __init__(self, orig):
            self.orig = orig
            self.buf = ""

        def write(self, s: str) -> int:
            try:
                self.orig.write(s)
            except Exception:
                pass
            self.buf += s
            while "\n" in self.buf or "\r" in self.buf:
                cut = min([i for i in (self.buf.find("\n"), self.buf.find("\r")) if i >= 0])
                line, self.buf = self.buf[:cut], self.buf[cut + 1 :]
                if line.strip():
                    log(line.strip())
            return len(s)

        def flush(self) -> None:
            try:
                self.orig.flush()
            except Exception:
                pass

    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = Tee(old_out), Tee(old_err)
    try:
        yield
    finally:
        sys.stdout, sys.stderr = old_out, old_err


def _catch(fn, log: LogFn | None):
    try:
        with _stdio_to_log(log):
            return fn()
    except SystemExit as exc:
        msg = exc.code if isinstance(exc.code, str) and exc.code else "解析失败"
        raise RuntimeError(msg) from exc
    except Exception as exc:  # noqa: BLE001
        _log(log, f"error: {exc}")
        raise


def _card(
    *,
    item_id: str,
    title: str,
    url: str = "",
    cover: str = "",
    duration: Any = "",
    author: str = "",
    subtitle: str = "",
    size: int | None = None,
) -> dict[str, Any]:
    return {
        "id": str(item_id),
        "title": title or str(item_id),
        "url": url,
        "cover": cover or "",
        "duration": duration if duration not in (None, "") else "",
        "author": author or "",
        "subtitle": subtitle or "",
        "size": size,
    }


def _thumb(item: dict[str, Any]) -> str:
    if item.get("cover"):
        return str(item["cover"])
    if item.get("thumbnail"):
        return str(item["thumbnail"])
    thumbs = item.get("thumbnails") or []
    if isinstance(thumbs, list) and thumbs:
        last = thumbs[-1]
        if isinstance(last, dict) and last.get("url"):
            return str(last["url"])
        if isinstance(last, str):
            return last
    return ""


def preview(
    query: str,
    site: str = "auto",
    *,
    limit: int = 40,
    tab: str = "",
    jable: dict[str, Any] | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    if isinstance(jable, dict) and jable.get("mode") in {"hot", "pick"}:
        return _preview_jable_browse(jable, log=log)
    found = detect(query, site)
    if found["kind"] in {"empty", "need-site"}:
        raise RuntimeError(found.get("message") or "请输入链接或用户名")
    _log(log, f"站点: {found['site']}  类型: {found['kind']}")
    site_name = found["site"]
    if site_name == "jable":
        return _preview_jable(found, limit=limit, log=log)
    if site_name == "youtube":
        return _preview_youtube(found, limit=limit, tab=tab, log=log)
    if site_name == "douyin":
        return _preview_douyin(found, limit=limit, log=log)
    raise RuntimeError("未知站点")


def _jable_list_preview(
    items: list[dict[str, Any]],
    *,
    title: str,
    url: str,
    hint: str,
    kind: str = "list",
) -> dict[str, Any]:
    cards = [
        _card(
            item_id=row["code"],
            title=row.get("title") or row["code"],
            url=row.get("url") or "",
            cover=row.get("cover") or "",
            duration=row.get("duration") or "",
            subtitle=f"播放 {row.get('views') or '-'}  收藏 {row.get('likes') or '-'}",
        )
        for row in items
        if row.get("code")
    ]
    store = {
        row["code"]: {"url": row.get("url"), "code": row["code"], "raw": row}
        for row in items
        if row.get("code")
    }
    return {
        "site": "jable",
        "kind": kind,
        "title": title,
        "author": "jable.tv",
        "cover": cards[0]["cover"] if cards else "",
        "url": url,
        "items": cards,
        "store": store,
        "options": {"subs": False, "quality": False},
        "hint": hint,
    }


def _preview_jable_browse(opts: dict[str, Any], log: LogFn | None) -> dict[str, Any]:
    from .jable_lists import run_hot, run_pick

    mode = str(opts.get("mode") or "hot")
    _log(log, f"Jable {'热门' if mode == 'hot' else '選片'}")

    def run():
        return run_hot(opts, log=log) if mode == "hot" else run_pick(opts, log=log)

    payload = _catch(run, log)
    items = payload.get("items") or []
    title = str(payload.get("browse_title") or payload.get("label") or "Jable 列表")
    url = str(payload.get("browse_url") or payload.get("source") or "")
    return _jable_list_preview(
        items,
        title=title,
        url=url,
        kind="hot" if mode == "hot" else "pick",
        hint=f"{title} · {len(items)} 部，勾选后下载正片",
    )


def _preview_jable(found: dict[str, Any], *, limit: int, log: LogFn | None) -> dict[str, Any]:
    from jable_hls import fetch_html as fetch_video_html
    from jable_hls import normalize_url, parse_page
    from jable_hot import list_url, looks_like_list, parse_items
    from jable_http import fetch_html as fetch_list_html

    kind = found["kind"]
    raw = found["query"]
    if kind == "user":
        return _preview_jable_user(raw, limit=limit, log=log)
    if kind == "list":
        _log(log, "解析 Jable 列表页（不下正片）")
        url = found.get("url") or raw
        if not re.match(r"https?://", url, re.I):
            url = "https://jable.tv/hot/"
        parsed = urlparse(url)
        path = parsed.path or "/hot/"
        term = (parse_qs(parsed.query).get("sort_by") or ["video_viewed"])[0]
        items: list[dict[str, Any]] = []
        page = 1
        while len(items) < max(1, limit):
            page_url = url if page == 1 else list_url(path, term, page)
            _log(log, f"抓取第 {page} 页  {page_url}")
            html, _diag = fetch_list_html(page_url, validate=looks_like_list)
            chunk = parse_items(html)
            if not chunk:
                break
            seen = {it["code"] for it in items}
            for row in chunk:
                if row["code"] not in seen:
                    items.append(row)
                    seen.add(row["code"])
            if len(chunk) < 10:
                break
            page += 1
            if page > 8:
                break
        items = items[: max(1, limit)]
        cards = [
            _card(
                item_id=row["code"],
                title=row.get("title") or row["code"],
                url=row.get("url") or "",
                cover=row.get("cover") or "",
                duration=row.get("duration") or "",
                subtitle=f"播放 {row.get('views') or '-'}  收藏 {row.get('likes') or '-'}",
            )
            for row in items
        ]
        store = {row["code"]: {"url": row.get("url"), "code": row["code"], "raw": row} for row in items}
        return {
            "site": "jable",
            "kind": "list",
            "title": path.strip("/") or "hot",
            "author": "jable.tv",
            "cover": cards[0]["cover"] if cards else "",
            "url": url,
            "items": cards,
            "store": store,
            "options": {"subs": False, "quality": False},
            "hint": f"列表 {len(cards)} 部，勾选后下载正片",
        }

    _log(log, "解析 Jable 作品页：HLS / 封面")
    page_url = raw
    try:
        page_url = normalize_url(raw)
    except SystemExit:
        if re.search(r"\.m3u8($|[?#])", raw, re.I):
            code = raw.split("?")[0].rstrip("/").split("/")[-1].replace(".m3u8", "")
            card = _card(item_id=code, title=code, url=raw, subtitle="直接 m3u8")
            return {
                "site": "jable",
                "kind": "video",
                "title": code,
                "author": "jable.tv",
                "cover": "",
                "url": raw,
                "items": [card],
                "store": {code: {"url": raw, "code": code, "raw": {"url": raw, "code": code, "hls": raw}}},
                "options": {"subs": True, "quality": False},
                "hint": "确认后下载、解密并封装 mp4",
            }
        raise
    html = _catch(lambda: fetch_video_html(page_url), log)
    meta = _catch(lambda: parse_page(page_url, html), log)
    code = str(meta.get("code") or "video")
    card = _card(
        item_id=code,
        title=meta.get("title") or code,
        url=meta.get("url") or page_url,
        cover=meta.get("cover") or "",
        subtitle=f"HLS  {meta.get('expires_at') or ''}".strip(),
    )
    _log(log, f"番号 {code}  {meta.get('title') or ''}")
    return {
        "site": "jable",
        "kind": "video",
        "title": meta.get("title") or code,
        "author": "jable.tv",
        "cover": meta.get("cover") or "",
        "url": meta.get("url") or page_url,
        "items": [card],
        "store": {code: {"url": meta.get("url") or page_url, "code": code, "raw": meta}},
        "options": {"subs": True, "quality": False},
        "hint": "确认后下载、解密并封装 mp4",
    }


def _preview_jable_user(raw: str, *, limit: int, log: LogFn | None) -> dict[str, Any]:
    from jable_user import list_user_videos

    _log(log, "识别 Jable 用户 / 女優，拉取全部作品")
    bundle = list_user_videos(raw, limit=0, log=log)
    items = bundle.get("items") or []
    cards = [
        _card(
            item_id=row["code"],
            title=row.get("title") or row["code"],
            url=row.get("url") or "",
            cover=row.get("cover") or "",
            duration=row.get("duration") or "",
            author=bundle.get("name") or "",
            subtitle=f"播放 {row.get('views') or '-'}  收藏 {row.get('likes') or '-'}",
        )
        for row in items
        if row.get("code")
    ]
    store = {row["code"]: {"url": row.get("url"), "code": row["code"], "raw": row} for row in items if row.get("code")}
    name = bundle.get("name") or raw
    total = bundle.get("count") or len(cards)
    url = bundle.get("url") or ""
    _log(log, f"列出 {len(cards)} / {total} 部")
    return {
        "site": "jable",
        "kind": "user",
        "title": name,
        "author": name,
        "cover": bundle.get("cover") or (cards[0]["cover"] if cards else ""),
        "url": url,
        "items": cards,
        "store": store,
        "options": {"subs": False, "quality": False},
        "hint": f"女優 {name} · {len(cards)} 部已列出，勾选后下载正片",
        "meta": {"slug": bundle.get("slug"), "declared": total},
    }


def _preview_youtube(found: dict[str, Any], *, limit: int, tab: str, log: LogFn | None) -> dict[str, Any]:
    from youtube_parse import LIST_KINDS, VIDEO_KINDS, extract_info, parse_target

    raw = found["query"]
    as_channel = found["kind"] == "channel" or (
        found["kind"] != "video" and not re.search(r"https?://", raw) and not YT_ID_RE.fullmatch(raw)
    )
    _log(log, "解析 YouTube 元数据（不下载体）")
    ffmpeg = find_ffmpeg()
    ffmpeg_loc = str(ffmpeg.parent) if ffmpeg else None
    want_tab = tab if tab and tab != "all" else None

    def run():
        target = parse_target(raw, as_channel=as_channel)
        _log(log, f"识别: {target.kind}  {target.url}")
        return extract_info(
            raw,
            ffmpeg_loc,
            limit=limit if limit > 0 else None,
            tab=want_tab,
            as_channel=as_channel,
        )

    item = _catch(run, log)
    kind = item.get("kind") or found["kind"]
    if kind in LIST_KINDS:
        entries = item.get("entries") or []
        cards = []
        store = {}
        for entry in entries:
            vid = str(entry.get("id") or "")
            if not vid:
                continue
            url = entry.get("url") or f"https://www.youtube.com/watch?v={vid}"
            cards.append(
                _card(
                    item_id=vid,
                    title=entry.get("title") or vid,
                    url=url,
                    cover=_thumb(entry),
                    duration=entry.get("duration_string") or entry.get("duration") or "",
                    author=entry.get("uploader") or item.get("uploader") or "",
                    subtitle=entry.get("tab") or entry.get("media_type") or "",
                )
            )
            store[vid] = {"url": url, "code": vid, "raw": entry}
        title = item.get("title") or item.get("channel") or raw
        _log(log, f"{kind}  {title}  {len(cards)} 条")
        return {
            "site": "youtube",
            "kind": kind,
            "title": title,
            "author": item.get("uploader") or item.get("channel") or "",
            "cover": _thumb(item),
            "url": item.get("url") or "",
            "items": cards,
            "store": store,
            "options": {"subs": True, "quality": True},
            "hint": f"{kind} 共 {len(cards)} 条，勾选后按所选分辨率下载",
            "meta": {
                "channel_id": item.get("channel_id"),
                "subscribers": item.get("channel_follower_count"),
                "tab_counts": item.get("tab_counts"),
            },
        }
    if kind not in VIDEO_KINDS:
        raise RuntimeError(f"暂不支持的 YouTube 类型: {kind}")
    vid = str(item.get("id") or "")
    dash = item.get("dash") or {}
    url = item.get("url") or f"https://www.youtube.com/watch?v={vid}"
    card = _card(
        item_id=vid,
        title=item.get("title") or vid,
        url=url,
        cover=_thumb(item),
        duration=item.get("duration_string") or item.get("duration") or "",
        author=item.get("uploader") or "",
        subtitle=str(dash.get("resolution") or item.get("resolution") or ""),
    )
    _log(log, f"视频 {vid}  {item.get('title') or ''}")
    return {
        "site": "youtube",
        "kind": "video",
        "title": item.get("title") or vid,
        "author": item.get("uploader") or "",
        "cover": _thumb(item),
        "url": url,
        "items": [card],
        "store": {vid: {"url": url, "code": vid, "raw": item}},
        "options": {"subs": True, "quality": True},
        "hint": "确认后按所选分辨率下载并合并 mp4",
        "meta": {"resolution": dash.get("resolution") or item.get("resolution")},
    }


def _preview_douyin(found: dict[str, Any], *, limit: int, log: LogFn | None) -> dict[str, Any]:
    from douyin_filter import classify_items
    from douyin_parse import classify, fetch_feed, fetch_video, set_cookie_file
    from douyin_user import normalize_unique_id, resolve_input
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

    raw = found["query"]
    cookies = default_cookie_path() or (cookie_path() if cookie_path().is_file() else None)
    if cookies:
        set_cookie_file(cookies)
        _log(log, f"cookies: {cookies}")

    kind = found["kind"]
    info: dict[str, str] | None = None
    if re.search(r"https?://", raw, re.I) or "douyin.com/" in raw.lower():
        info = classify(raw)
        kind = info["kind"]
        _log(log, f"链接类型: {kind}")
    elif raw.startswith("#"):
        kind = "hashtag"
        info = {"kind": "hashtag", "id": raw.lstrip("#"), "url": f"https://www.douyin.com/hashtag/{raw.lstrip('#')}"}
    elif DIGIT_ID_RE.fullmatch(raw):
        kind = "video"
        info = {"kind": "video", "id": raw, "url": f"https://www.douyin.com/video/{raw}"}
    else:
        kind = "user"

    want = max(0, int(limit or 0))

    def need_cookie() -> Path:
        if not cookies:
            raise RuntimeError(cookie_help())
        return cookies

    data: dict[str, Any]
    if kind == "video":
        vid = (info or {}).get("id") or raw
        _log(log, f"解析作品 {vid}")
        if cookies:
            bundle = fetch_video_page(cookies, vid, related=False, headed=False)
            item = bundle.get("detail") or (bundle.get("items") or [{}])[0]
        else:
            item = fetch_video(vid)
        return _douyin_video_preview(item)

    if kind == "feed":
        _log(log, "解析推荐流")
        if cookies:
            data = fetch_logged_in_feed(need_cookie(), want or 40, headed=False)
        else:
            data = fetch_feed(want or 40)
            data["logged_in"] = False
        return _douyin_feed_preview(data, title="推荐", url="https://www.douyin.com/?recommend=1")

    if kind == "follow_feed":
        _log(log, "解析关注作品流")
        data = fetch_follow_feed(need_cookie(), want or 40, headed=False)
        return _douyin_feed_preview(data, title="关注流", url="https://www.douyin.com/follow")

    if kind == "hashtag":
        tag = (info or {}).get("id") or raw.lstrip("#")
        _log(log, f"解析话题 #{tag}")
        data = fetch_hashtag(need_cookie(), tag, want or 40, headed=False)
        return _douyin_feed_preview(data, title=f"#{tag}", url=f"https://www.douyin.com/hashtag/{tag}")

    if kind in {"like", "following", "followers"}:
        uid = (info or {}).get("id") or "self"
        _log(log, f"解析 {kind}  {uid}")
        cookie = need_cookie()
        if kind == "like":
            data = fetch_likes(cookie, uid, want, headed=False)
            return _douyin_feed_preview(data, title="喜欢", url=(info or {}).get("url") or "")
        if kind == "following":
            data = fetch_following(cookie, uid, want, headed=False)
            return _douyin_users_preview(data, title="关注")
        data = fetch_followers(cookie, uid, want, headed=False)
        return _douyin_users_preview(data, title="粉丝")

    # user / 抖音号
    _log(log, f"解析抖音号 / 主页: {raw}")
    cookie = need_cookie()
    if info and info.get("id") and str(info["id"]).startswith("MS4wLjAB"):
        sec_uid = info["id"]
        unique = sec_uid
        author: dict[str, Any] = {}
    else:
        ident = normalize_unique_id(raw) if not (info and info.get("id")) else info["id"]
        author = resolve_input(ident if not (info and str(info.get("id", "")).startswith("MS4w")) else ident)
        sec_uid = str(author.get("sec_uid") or ident)
        unique = str(author.get("unique_id") or ident)
        _log(log, f"抖音号 {unique}  作品 {author.get('aweme_count')}")
    posts = fetch_user_posts(cookie, sec_uid, want, headed=False)
    data = posts
    if author:
        data = dict(posts)
        data["author"] = {**(posts.get("author") or {}), **author}
    title = (data.get("author") or {}).get("nickname") or unique
    return _douyin_feed_preview(
        data,
        title=title,
        url=f"https://www.douyin.com/user/{sec_uid}",
        kind="user",
    )


def _douyin_item_card(item: dict[str, Any]) -> dict[str, Any]:
    best = item.get("best") or {}
    size = int(best.get("size") or 0) or None
    stats = item.get("statistics") or {}
    dur = item.get("duration")
    if isinstance(dur, (int, float)) and dur > 0:
        duration: Any = f"{int(dur // 60)}:{int(dur % 60):02d}" if dur >= 60 else f"{int(dur)}s"
    else:
        duration = dur or ""
    gear = " ".join(
        str(x)
        for x in (best.get("width") and f"{best.get('width')}x{best.get('height')}", best.get("gear"))
        if x
    )
    likes = stats.get("digg_count")
    return _card(
        item_id=str(item.get("id") or ""),
        title=item.get("title") or str(item.get("id") or ""),
        url=item.get("url") or "",
        cover=item.get("cover") or "",
        duration=duration,
        author=item.get("author") or item.get("nickname") or "",
        subtitle="  ".join(x for x in (gear, f"赞 {likes}" if likes is not None else "") if x),
        size=size,
    )


def _douyin_feed_preview(data: dict[str, Any], *, title: str, url: str, kind: str = "feed") -> dict[str, Any]:
    from douyin_filter import classify_items

    items = classify_items(data.get("items") or [])
    cards = []
    store: dict[str, Any] = {}
    for item in items:
        iid = str(item.get("id") or "")
        if not iid:
            continue
        cards.append(_douyin_item_card(item))
        store[iid] = {"url": item.get("url") or "", "code": iid, "raw": item}
    author = data.get("author") or {}
    return {
        "site": "douyin",
        "kind": kind,
        "title": title,
        "author": author.get("nickname") or author.get("unique_id") or "",
        "cover": author.get("avatar") or (cards[0]["cover"] if cards else ""),
        "url": url,
        "items": cards,
        "store": store,
        "options": {"subs": False, "quality": False},
        "hint": f"{len(cards)} 条作品，勾选后并行下载最高清 mp4",
        "downloadable": True,
    }


def _douyin_video_preview(item: dict[str, Any]) -> dict[str, Any]:
    iid = str(item.get("id") or "")
    card = _douyin_item_card(item)
    return {
        "site": "douyin",
        "kind": "video",
        "title": item.get("title") or iid,
        "author": item.get("author") or "",
        "cover": item.get("cover") or "",
        "url": item.get("url") or "",
        "items": [card],
        "store": {iid: {"url": item.get("url") or "", "code": iid, "raw": item}},
        "options": {"subs": False, "quality": False},
        "hint": "确认后下载最高清 mp4",
        "downloadable": True,
    }


def _douyin_users_preview(data: dict[str, Any], *, title: str) -> dict[str, Any]:
    items = data.get("items") or []
    cards = []
    store: dict[str, Any] = {}
    for item in items:
        iid = str(item.get("sec_uid") or item.get("uid") or item.get("unique_id") or "")
        if not iid:
            continue
        cards.append(
            _card(
                item_id=iid,
                title=item.get("nickname") or item.get("unique_id") or iid,
                url=item.get("url") or "",
                cover=item.get("avatar") or "",
                author=item.get("unique_id") or "",
                subtitle=f"粉丝 {item.get('follower_count') or '-'}",
            )
        )
        store[iid] = {"url": item.get("url") or "", "code": iid, "raw": item}
    return {
        "site": "douyin",
        "kind": "users",
        "title": title,
        "author": "",
        "cover": cards[0]["cover"] if cards else "",
        "url": "",
        "items": cards,
        "store": store,
        "options": {"subs": False, "quality": False},
        "hint": "这是用户列表，不能当视频下载。回到输入框打开某个主页再解析作品。",
        "downloadable": False,
    }


def public_preview(preview: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in preview.items() if k != "store"}
    return out


def build_commands(
    preview: dict[str, Any],
    ids: list[str],
    *,
    quality: str = "1080p",
    subs: bool = False,
    workers: int | None = None,
) -> list[dict[str, Any]]:
    site = preview.get("site")
    store: dict[str, Any] = preview.get("store") or {}
    wanted = [i for i in ids if i in store] if ids else list(store.keys())
    if not wanted:
        raise RuntimeError("没有可下载的条目，请先勾选")
    if preview.get("downloadable") is False:
        raise RuntimeError(preview.get("hint") or "该结果不能下载")
    py = find_python()
    settings = load_settings()
    n_workers = int(workers if workers is not None else settings.get("workers") or 64)
    lib = library_dir() / str(site)
    lib.mkdir(parents=True, exist_ok=True)

    if site == "douyin":
        items = []
        for iid in wanted:
            raw = (store[iid] or {}).get("raw") or {}
            if raw.get("id") and ((raw.get("best") or {}).get("url") or (raw.get("best") or {}).get("urls")):
                items.append(raw)
        if not items:
            raise RuntimeError("选中的抖音条目没有播放地址")
        feed_dir = lib / "_queue"
        feed_dir.mkdir(parents=True, exist_ok=True)
        feed_path = feed_dir / "selected.json"
        payload = {"kind": "feed-selected", "count": len(items), "items": items}
        feed_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        argv = [
            py,
            "-u",
            str(PY_ROOT / "douyin_run.py"),
            "--from-feed",
            str(feed_path),
            "--yes",
            "--workers",
            str(max(1, n_workers)),
        ]
        cookies = cookie_path()
        if cookies.is_file():
            argv.extend(["--cookies", str(cookies)])
        return [
            {
                "argv": argv,
                "cwd": str(lib),
                "label": f"抖音 {len(items)} 条",
                "id": "batch",
            }
        ]

    cmds: list[dict[str, Any]] = []
    if site == "jable":
        for iid in wanted:
            rec = store[iid]
            target = rec.get("url") or rec.get("code") or iid
            argv = [py, "-u", str(PY_ROOT / "jable_run.py"), str(target), "--workers", str(max(1, n_workers))]
            if subs:
                argv.append("--subs")
            cmds.append({"argv": argv, "cwd": str(lib), "label": f"Jable {iid}", "id": iid})
        return cmds

    if site == "youtube":
        q = quality if quality in {"1080p", "2k", "4k", "1440p", "2160p"} else "1080p"
        for iid in wanted:
            rec = store[iid]
            target = rec.get("url") or iid
            argv = [
                py,
                "-u",
                str(PY_ROOT / "youtube_run.py"),
                str(target),
                "--quality",
                q,
                "--no-grok-voice",
                "--no-grok-zh",
            ]
            if not subs:
                argv.append("--no-subs")
            cmds.append({"argv": argv, "cwd": str(lib), "label": f"YouTube {iid}", "id": iid})
        return cmds

    raise RuntimeError(f"未知站点: {site}")


def health() -> dict[str, Any]:
    ffmpeg = find_ffmpeg()
    cookies = cookie_path()
    yt_dlp_ver = ""
    try:
        from yt_dlp.version import __version__ as yt_ver

        yt_dlp_ver = str(yt_ver)
    except Exception:
        yt_dlp_ver = ""
    try:
        import playwright  # noqa: F401

        playwright_ok = True
    except Exception:
        playwright_ok = False
    return {
        "python": sys.executable,
        "ffmpeg": str(ffmpeg) if ffmpeg else "",
        "yt_dlp": yt_dlp_ver,
        "playwright": playwright_ok,
        "cookie": cookies.is_file() and cookies.stat().st_size > 20,
        "library": str(library_dir()),
        "settings": load_settings(),
    }
