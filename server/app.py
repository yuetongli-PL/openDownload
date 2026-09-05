# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse
from urllib.request import Request as UrlRequest, urlopen

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from starlette.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .dmm_preview import (
    allowed_preview_url,
    guess_preview_urls,
    normalize_code as dmm_normalize_code,
    stream_preview,
    stream_preview_for_code,
    warm_preview_many,
)
from .engine import detect, health
from .jable_inspect import inspect_info
from .jable_lists import catalog as jable_catalog
from .jable_lists import home_feed as jable_home_feed
from .jable_lists import list_feed as jable_list_feed
from .jable_lists import list_snapshot_bytes as jable_list_snapshot_bytes
from .jable_lists import forget_play as jable_forget_play
from .jable_lists import play_cached as jable_play_cached
from .jable_lists import play_info as jable_play_info
from .jable_page import page_feed
from .jobs import RUNNER
from .paths import WEB_ROOT, cookie_path, library_dir, load_settings, save_settings


def _kick_warmup() -> None:
    try:
        from jable_http import hold_crawlers

        hold_crawlers(180.0)
    except Exception:
        pass
    try:
        from .jable_lists import warmup_lists
    except ImportError:
        return
    threading.Thread(target=warmup_lists, kwargs={"limit_workers": 4}, daemon=True).start()
    try:
        from .jable_index import start_daily_index

        start_daily_index()
    except Exception:
        pass
    try:
        from .jable_tag_cache import start_full_cache

        start_full_cache()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    _kick_warmup()
    yield


app = FastAPI(title="openDownload", docs_url=None, redoc_url=None, lifespan=lifespan)


class SkipMediaGZipMiddleware(GZipMiddleware):
    """JSON/HTML can be gzipped; HLS/SSE must not or playback and progress stall."""

    _SKIP = (
        "/api/jable/seg",
        "/api/jable/hls",
        "/api/dmm/preview",
        "/api/tasks/",
    )

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            path = scope.get("path") or ""
            if path.startswith(self._SKIP):
                await self.app(scope, receive, send)
                return
        await super().__call__(scope, receive, send)


app.add_middleware(SkipMediaGZipMiddleware, minimum_size=1000)


class JableBrowseIn(BaseModel):
    mode: str = ""
    term: str = ""
    category: str = ""
    group: str = ""
    tag: str = ""
    model: str = ""
    pages: int = 2


class ParseIn(BaseModel):
    query: str = ""
    site: str = "auto"
    limit: int = 40
    tab: str = ""
    jable: JableBrowseIn | None = None


class DownloadIn(BaseModel):
    parse_id: str
    ids: list[str] = Field(default_factory=list)
    quality: str = "1080p"
    subs: bool = False
    workers: int | None = None


class JableSaveIn(BaseModel):
    code: str
    subs: bool = False
    workers: int | None = None


class SettingsIn(BaseModel):
    library: str | None = None
    limit: int | None = None
    workers: int | None = None


class CookieIn(BaseModel):
    text: str


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    return health()


@app.get("/api/settings")
def api_settings() -> dict[str, Any]:
    return load_settings()


@app.post("/api/settings")
def api_settings_save(body: SettingsIn) -> dict[str, Any]:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "library" in patch:
        path = Path(str(patch["library"])).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        patch["library"] = str(path)
    return save_settings(patch)


@app.post("/api/cookie")
def api_cookie(body: CookieIn) -> dict[str, Any]:
    text = (body.text or "").strip()
    if len(text) < 20:
        raise HTTPException(400, "cookie 太短")
    dest = cookie_path()
    dest.write_text(text + "\n", encoding="utf-8")
    return {"ok": True, "path": str(dest)}


@app.get("/api/jable/catalog")
def api_jable_catalog() -> dict[str, Any]:
    return jable_catalog()


@app.get("/api/jable/index")
def api_jable_index() -> dict[str, Any]:
    from .jable_index import index_status

    return index_status()


@app.get("/api/jable/home")
def api_jable_home(pages: int = 2, refresh: bool = False) -> dict[str, Any]:
    pages = max(1, min(int(pages or 2), 8))
    try:
        return jable_home_feed(pages=pages, force=refresh)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc) or "Jable 列表抓取失败") from exc


@app.get("/api/jable/snapshot")
def api_jable_snapshot(
    kind: str = "latest",
    slug: str = "",
    term: str = "",
    year: str = "",
    month: str = "",
) -> Response:
    year = (year or "").strip()
    month = (month or "").strip()
    if year and not re.fullmatch(r"(?:19|20)\d{2}", year):
        year = ""
    if month and not re.fullmatch(r"(?:0?[1-9]|1[0-2])", month):
        month = ""
    try:
        raw = jable_list_snapshot_bytes(kind=kind, slug=slug, term=term, year=year, month=month)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc) or "Jable 索引读取失败") from exc
    return Response(
        content=raw,
        media_type="application/json; charset=utf-8",
        headers={"Cache-Control": "public, max-age=120"},
    )


@app.get("/api/jable/works")
def api_jable_works() -> dict[str, Any]:
    from .jable_index import works_compact, works_count

    cards = works_compact()
    return {
        "total": works_count(),
        "cards": cards,
        "cover_bases": [
            "https://assets-cdn.jable.tv",
            "https://static-assets-cdn.jable.tv",
        ],
    }


@app.get("/api/jable/orders")
def api_jable_orders() -> dict[str, Any]:
    from .jable_tag_cache import orders_payload

    return orders_payload()


@app.get("/api/jable/cache")
def api_jable_cache() -> dict[str, Any]:
    from .jable_tag_cache import cache_status

    return cache_status()


@app.get("/api/jable/meta")
def api_jable_meta(codes: str = "", wait: bool = False) -> dict[str, Any]:
    raw = [c.strip().lower() for c in (codes or "").split(",") if c.strip()]
    from .jable_index import works_meta

    items = works_meta(raw, fetch_missing=wait)
    out = []
    for row in items:
        out.append(
            {
                "id": row.get("id") or "",
                "title": row.get("title") or "",
                "date": row.get("date") or "",
                "actors": row.get("actors") or [],
                "duration": row.get("duration") or "",
                "views": row.get("views") or 0,
            }
        )
    return {"items": out}


@app.get("/api/jable/list")
def api_jable_list(
    kind: str = "latest",
    slug: str = "",
    term: str = "",
    year: str = "",
    month: str = "",
    pages: int = 1,
    page: int = 1,
    refresh: bool = False,
) -> dict[str, Any]:
    pages = max(1, min(int(pages or 1), 8))
    page = max(1, min(int(page or 1), 20000))
    year = (year or "").strip()
    month = (month or "").strip()
    if year and not re.fullmatch(r"(?:19|20)\d{2}", year):
        year = ""
    if month and not re.fullmatch(r"(?:0?[1-9]|1[0-2])", month):
        month = ""
    try:
        return jable_list_feed(
            kind=kind,
            slug=slug,
            term=term,
            year=year,
            month=month,
            pages=pages,
            page=page,
            force=refresh,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc) or "Jable 列表抓取失败") from exc


@app.get("/api/jable/page")
def api_jable_page(
    kind: str = "latest",
    slug: str = "",
    term: str = "",
    year: str = "",
    month: str = "",
    page: int = 1,
) -> dict[str, Any]:
    page = max(1, min(int(page or 1), 20000))
    year = (year or "").strip()
    month = (month or "").strip()
    if year and not re.fullmatch(r"(?:19|20)\d{2}", year):
        year = ""
    if month and not re.fullmatch(r"(?:0?[1-9]|1[0-2])", month):
        month = ""
    try:
        return page_feed(
            kind=kind,
            slug=slug,
            term=term,
            year=year,
            month=month,
            page=page,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, str(exc) or "Jable 列表抓取失败") from exc


@app.get("/api/jable/play")
def api_jable_play(code: str) -> dict[str, Any]:
    raw = (code or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,40}", raw):
        raise HTTPException(400, "番号无效")
    cached = None
    try:
        cached = jable_play_cached(raw)
    except Exception:
        cached = None
    if not cached:
        try:
            from jable_http import hold_crawlers

            hold_crawlers(60.0)
        except Exception:
            pass
    try:
        data = cached or jable_play_info(raw)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    if not data.get("hls"):
        raise HTTPException(502, "没有播放地址")
    hls = str(data["hls"])
    data["stream"] = "/api/jable/hls?url=" + quote(hls, safe="")
    data["cached"] = bool(cached or data.get("cached"))
    _remember_play_origin(raw, hls)
    try:
        _prepare_playlist(hls)
    except Exception:
        threading.Thread(target=_warm_playlist, args=(hls,), daemon=True).start()
    return data


@app.get("/api/jable/play/warm")
def api_jable_play_warm(codes: str = "") -> dict[str, Any]:
    raw = [c.strip() for c in (codes or "").split(",") if c.strip()]
    items = [c for c in raw if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,40}", c)][:3]
    if not items:
        raise HTTPException(400, "番号无效")
    threading.Thread(target=_warm_play_many, args=(items,), daemon=True).start()
    return {"queued": len(items)}


@app.get("/api/jable/inspect")
def api_jable_inspect(code: str) -> dict[str, Any]:
    raw = (code or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,40}", raw):
        raise HTTPException(400, "番号无效")
    try:
        return inspect_info(raw)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


def _dmm_stream_path(url: str) -> str:
    return "/api/dmm/preview/file?url=" + quote(url, safe="")


@app.get("/api/dmm/preview")
def api_dmm_preview(code: str) -> dict[str, Any]:
    raw = (code or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,40}", raw):
        raise HTTPException(400, "番号无效")
    urls = guess_preview_urls(raw)
    if not urls:
        raise HTTPException(502, "没有公开预览")
    return {
        "id": dmm_normalize_code(raw),
        "url": urls[0],
        "urls": urls[:16],
        "stream": _dmm_stream_path(urls[0]),
        "streams": [_dmm_stream_path(u) for u in urls[:16]],
    }


def _dmm_file_response(
    status: int, headers: dict[str, str], chunks: Any
) -> StreamingResponse:
    out = {"Cache-Control": "no-store"}
    lowered = {k.lower(): v for k, v in headers.items()}
    for key in ("Content-Range", "Accept-Ranges", "Content-Length"):
        if key.lower() in lowered:
            out[key] = lowered[key.lower()]
    if "accept-ranges" not in {k.lower() for k in out}:
        out["Accept-Ranges"] = "bytes"
    return StreamingResponse(chunks, status_code=status, media_type="video/mp4", headers=out)


@app.get("/api/dmm/preview/warm")
def api_dmm_preview_warm(codes: str = "") -> dict[str, Any]:
    raw = [c.strip() for c in (codes or "").split(",") if c.strip()]
    items = [c for c in raw if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,40}", c)][:24]
    if not items:
        raise HTTPException(400, "番号无效")
    threading.Thread(target=warm_preview_many, args=(items,), kwargs={"workers": 6}, daemon=True).start()
    return {"queued": len(items)}


@app.get("/api/dmm/preview/play")
def api_dmm_preview_play(code: str, request: Request) -> StreamingResponse:
    raw = (code or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,40}", raw):
        raise HTTPException(400, "番号无效")
    range_header = request.headers.get("Range")
    try:
        status, headers, chunks = stream_preview_for_code(raw, range_header)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return _dmm_file_response(status, headers, chunks)


@app.get("/api/dmm/preview/file")
def api_dmm_preview_file(url: str, request: Request) -> StreamingResponse:
    raw = unquote((url or "").strip())
    if not allowed_preview_url(raw):
        raise HTTPException(400, "bad url")
    range_header = request.headers.get("Range")
    try:
        status, headers, chunks = stream_preview(raw, range_header)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return _dmm_file_response(status, headers, chunks)


def _jable_fetch(url: str, timeout: int = 30) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "bad url")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36"
    referer = "https://jable.tv/"
    curl = shutil.which("curl.exe") or shutil.which("curl")
    data = b""
    if curl:
        result = subprocess.run(
            [
                curl,
                "-sL",
                "--max-time",
                str(timeout),
                "-A",
                ua,
                "-H",
                f"Referer: {referer}",
                "-H",
                "Accept: */*",
                url,
            ],
            check=False,
            capture_output=True,
        )
        data = result.stdout or b""
    if len(data) < 16:
        req = UrlRequest(url, headers={"User-Agent": ua, "Referer": referer, "Accept": "*/*"})
        try:
            with urlopen(req, timeout=timeout) as resp:
                data = resp.read() or b""
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, str(exc)) from exc
    if len(data) < 16:
        raise HTTPException(502, "empty stream")
    return data


def _cdn_get(url: str, timeout: int = 8, accept: str = "*/*", tries: int = 2) -> bytes:
    from jable_http import pooled_get

    last: bytes = b""
    denied = False
    for _attempt in range(max(1, int(tries))):
        try:
            data = pooled_get(url, timeout=timeout, referer="https://jable.tv/", accept=accept)
            if data and len(data) >= 16:
                return data
            last = data or last
        except Exception as exc:
            err = str(exc).lower()
            if "http 403" in err or "http 404" in err or "http 401" in err:
                denied = True
            continue
    if last and len(last) >= 16 and not denied:
        return last
    if denied:
        raise RuntimeError("cdn denied")
    return _jable_fetch(url, timeout=max(8, min(30, int(timeout))))


_HLS_CACHE: dict[str, tuple[float, bytes]] = {}
_HLS_LOCK = threading.Lock()
_HLS_WAIT: dict[str, threading.Event] = {}
_HLS_TTL = 300.0
_SEG_CACHE: dict[str, tuple[float, bytes, str]] = {}
_SEG_LOCK = threading.Lock()
_SEG_WAIT: dict[str, threading.Event] = {}
_SEG_TTL = 600.0
_SEG_MAX = 180
_SEG_MAX_BYTES = 180 * 1024 * 1024
_START_SEGS = 2
_WARM_SEGS = 8
_AHEAD_SEGS = 8
_VARIANT_MAX_HEIGHT = 720
_VARIANT_MAX_BW = 5_000_000
_IO_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="jb-hls")
_CDN_GATE = threading.Semaphore(4)
_PREFETCH_SLOTS = threading.Semaphore(3)
_CURL_BATCH_LOCK = threading.Lock()
_PLAY_WARMING: set[str] = set()
_PLAY_WARM_LOCK = threading.Lock()
_PLAYLIST_SEGS: dict[str, list[str]] = {}
_SEG_POS: dict[str, tuple[str, int]] = {}
_HLS_PREFIX_RE = re.compile(r"(https?://[^/]+/hls/[^/]+/\d{10}/)", re.I)
_ORIGIN_LOCK = threading.Lock()
_CODE_PREFIX: dict[str, str] = {}
_PREFIX_CODE: dict[str, str] = {}
_PREFIX_REFRESHING: set[str] = set()
_PREFIX_WAIT: dict[str, threading.Event] = {}


def _parse_variants(text: str, base: str) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    pending = False
    pending_bw = 0
    pending_h = 0
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXT-X-STREAM-INF:"):
            pending = True
            match = re.search(r"BANDWIDTH=(\d+)", line)
            pending_bw = int(match.group(1)) if match else 0
            match = re.search(r"RESOLUTION=\d+x(\d+)", line)
            pending_h = int(match.group(1)) if match else 0
            continue
        if pending and line and not line.startswith("#"):
            out.append((pending_h, pending_bw, urljoin(base, line)))
            pending = False
    return out


def _hls_prefix(url: str) -> str:
    match = _HLS_PREFIX_RE.search(url or "")
    return match.group(1) if match else ""


def _remember_play_origin(code: str, hls: str) -> None:
    prefix = _hls_prefix(hls)
    key = (code or "").strip().lower()
    if not prefix:
        return
    with _ORIGIN_LOCK:
        if key:
            _CODE_PREFIX[key] = prefix
            _PREFIX_CODE[prefix] = key


def _current_prefix_for(url: str) -> str:
    prefix = _hls_prefix(url)
    if not prefix:
        return ""
    with _ORIGIN_LOCK:
        code = _PREFIX_CODE.get(prefix) or ""
        return _CODE_PREFIX.get(code) or prefix


def _retarget_hls_url(url: str) -> str:
    prefix = _hls_prefix(url)
    current = _current_prefix_for(url)
    if prefix and current and current != prefix and url.startswith(prefix):
        return current + url[len(prefix) :]
    return url


def _refresh_prefix_for_code(code: str) -> str:
    key = (code or "").strip().lower()
    if not key:
        return ""
    wait: threading.Event | None = None
    owner = False
    with _ORIGIN_LOCK:
        if key in _PREFIX_REFRESHING:
            wait = _PREFIX_WAIT.get(key)
        else:
            _PREFIX_REFRESHING.add(key)
            wait = threading.Event()
            _PREFIX_WAIT[key] = wait
            owner = True
    if not owner:
        if wait:
            wait.wait(timeout=20)
        with _ORIGIN_LOCK:
            return _CODE_PREFIX.get(key) or ""
    try:
        jable_forget_play(key)
        data = jable_play_info(key)
        hls = str((data or {}).get("hls") or "")
        if hls:
            _remember_play_origin(key, hls)
        with _ORIGIN_LOCK:
            return _CODE_PREFIX.get(key) or ""
    except Exception:
        with _ORIGIN_LOCK:
            return _CODE_PREFIX.get(key) or ""
    finally:
        with _ORIGIN_LOCK:
            _PREFIX_REFRESHING.discard(key)
            ev = _PREFIX_WAIT.pop(key, None)
        if ev:
            ev.set()


def _maybe_refresh_token(url: str) -> None:
    prefix = _hls_prefix(url)
    match = re.search(r"/(\d{10})/", prefix or url or "")
    if not match:
        return
    remain = int(match.group(1)) - time.time()
    if remain > 180:
        return
    with _ORIGIN_LOCK:
        code = _PREFIX_CODE.get(prefix) or ""
        busy = code in _PREFIX_REFRESHING
    if code and not busy:
        _IO_POOL.submit(_refresh_prefix_for_code, code)


def _pick_variant(text: str, base: str) -> str | None:
    """Prefer 720p / ~5 Mbps so a long VOD can keep a buffer through the local proxy."""
    variants = _parse_variants(text, base)
    if not variants:
        return None
    capped = [
        item
        for item in variants
        if (item[0] and item[0] <= _VARIANT_MAX_HEIGHT)
        or (not item[0] and item[1] <= _VARIANT_MAX_BW)
    ]
    if capped:
        return max(capped, key=lambda item: (item[0], item[1]))[2]
    return min(variants, key=lambda item: (item[1] or 10**12, item[0] or 10**6))[2]


def _inline_key_uris(text: str, base: str) -> str:
    def repl(match: re.Match[str]) -> str:
        uri = match.group(1)
        if uri.startswith("data:"):
            return match.group(0)
        abs_url = urljoin(base, uri)
        path = urlparse(abs_url).path.lower()
        if path.endswith(".m3u8"):
            return 'URI="' + _hls_proxy_uri(abs_url) + '"'
        try:
            raw, _ctype = _seg_bytes(abs_url)
        except Exception:
            return 'URI="' + _hls_proxy_uri(abs_url) + '"'
        if 8 <= len(raw) <= 128:
            b64 = base64.b64encode(raw).decode("ascii")
            return f'URI="data:application/octet-stream;base64,{b64}"'
        return 'URI="' + _hls_proxy_uri(abs_url) + '"'

    return re.sub(r'URI="([^"]+)"', repl, text)


def _seg_ctype(url: str) -> str:
    path = urlparse(url).path.lower()
    if path.endswith(".ts") or path.endswith(".m4s"):
        return "video/MP2T"
    if path.endswith(".mp4"):
        return "video/mp4"
    if path.endswith(".key"):
        return "application/octet-stream"
    return "application/octet-stream"


def _seg_cache_trim_locked() -> None:
    while len(_SEG_CACHE) > _SEG_MAX:
        oldest = min(_SEG_CACHE.items(), key=lambda kv: kv[1][0])[0]
        _SEG_CACHE.pop(oldest, None)
    total = sum(len(item[1]) for item in _SEG_CACHE.values())
    while total > _SEG_MAX_BYTES and _SEG_CACHE:
        oldest = min(_SEG_CACHE.items(), key=lambda kv: kv[1][0])[0]
        dropped = _SEG_CACHE.pop(oldest, None)
        if dropped:
            total -= len(dropped[1])


def _fetch_seg_body(url: str, *, urgent: bool) -> bytes:
    data = b""
    if urgent:
        gate = _CDN_GATE
        acquired = gate.acquire(timeout=12)
    else:
        if not _PREFETCH_SLOTS.acquire(timeout=8):
            return b""
        acquired = _CDN_GATE.acquire(timeout=8)
        if not acquired:
            _PREFETCH_SLOTS.release()
            return b""
        gate = _CDN_GATE
    if not acquired:
        if not urgent:
            _PREFETCH_SLOTS.release()
        return b""
    try:
        try:
            data = _cdn_get(url, timeout=8, tries=1)
        except Exception:
            data = b""
        return data
    finally:
        gate.release()
        if not urgent:
            _PREFETCH_SLOTS.release()


def _seg_bytes(url: str, urgent: bool = True) -> tuple[bytes, str]:
    now = time.time()
    owner = False
    wait: threading.Event | None = None
    with _SEG_LOCK:
        hit = _SEG_CACHE.get(url)
        if hit and now - hit[0] < _SEG_TTL:
            return hit[1], hit[2]
        wait = _SEG_WAIT.get(url)
        if wait is None:
            wait = threading.Event()
            _SEG_WAIT[url] = wait
            owner = True
    if not owner:
        wait.wait(timeout=20)
        with _SEG_LOCK:
            hit = _SEG_CACHE.get(url)
        if hit:
            return hit[1], hit[2]
        raise HTTPException(502, "empty stream")
    try:
        target = _retarget_hls_url(url)
        data = _fetch_seg_body(target, urgent=urgent)
        if len(data) < 16:
            prefix = _hls_prefix(url)
            with _ORIGIN_LOCK:
                code = _PREFIX_CODE.get(prefix) or ""
            if code:
                _refresh_prefix_for_code(code)
                target = _retarget_hls_url(url)
                data = _fetch_seg_body(target, urgent=urgent)
        if len(data) < 16:
            raise HTTPException(502, "empty stream")
        ctype = _seg_ctype(url)
        with _SEG_LOCK:
            _SEG_CACHE[url] = (time.time(), data, ctype)
            if target != url:
                _SEG_CACHE[target] = (time.time(), data, ctype)
            _seg_cache_trim_locked()
        return data, ctype
    finally:
        with _SEG_LOCK:
            _SEG_WAIT.pop(url, None)
        wait.set()


def _media_uris(text: str, base: str) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(urljoin(base, line))
    return out


def _key_urls(text: str, base: str) -> list[str]:
    urls: list[str] = []
    for match in re.finditer(r'URI="([^"]+)"', text):
        uri = match.group(1)
        if uri.startswith("data:"):
            continue
        abs_url = urljoin(base, uri)
        if not urlparse(abs_url).path.lower().endswith(".m3u8"):
            urls.append(abs_url)
    return urls


def _prefetch_one(url: str) -> None:
    try:
        _seg_bytes(url, urgent=False)
    except Exception:
        pass


def _prefetch_urls(urls: list[str], wait: bool = True, urgent: bool = True) -> None:
    if not urls:
        return
    if wait:
        futs = [_IO_POOL.submit(_seg_bytes, item) for item in urls]
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception:
                pass
        return
    worker = _seg_bytes if urgent else _prefetch_one
    for item in urls:
        _IO_POOL.submit(worker, item)


def _curl_batch_get(urls: list[str], timeout: int = 24) -> dict[str, bytes]:
    from jable_http import USER_AGENT, _popen_kw, cookie_path, curl_bin, curl_has_flag

    curl = curl_bin()
    if not curl or not urls:
        return {}
    tmp = Path(tempfile.gettempdir()) / f"jb-hls-batch-{os.getpid()}-{time.time_ns()}"
    try:
        tmp.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {}
    cfg = tmp / "curl.txt"
    mapping: list[tuple[str, Path]] = []
    lines: list[str] = []
    for i, url in enumerate(urls):
        dest = tmp / f"{i}.bin"
        mapping.append((url, dest))
        lines.append('url = "' + url.replace('"', "%22") + '"')
        lines.append('output = "' + dest.as_posix().replace('"', '\\"') + '"')
    try:
        cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
        return {}
    cmd = [
        curl,
        "-sS",
        "-L",
        "-Z",
        "--parallel-max",
        "4",
        "--fail",
        "--connect-timeout",
        "8",
        "--max-time",
        str(max(12, int(timeout))),
        "-A",
        USER_AGENT,
        "-H",
        "Referer: https://jable.tv/",
        "-b",
        str(cookie_path()),
        "-c",
        str(cookie_path()),
        "-K",
        str(cfg),
    ]
    if curl_has_flag(curl, "--ssl-no-revoke"):
        cmd.append("--ssl-no-revoke")
    if curl_has_flag(curl, "--parallel-immediate"):
        cmd.append("--parallel-immediate")
    try:
        subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            timeout=max(16, int(timeout) + 4),
            **_popen_kw(),
        )
    except Exception:
        pass
    out: dict[str, bytes] = {}
    for url, dest in mapping:
        try:
            if dest.is_file():
                data = dest.read_bytes()
                if len(data) >= 16:
                    out[url] = data
        except OSError:
            pass
    shutil.rmtree(tmp, ignore_errors=True)
    return out


def _claim_missing(urls: list[str]) -> list[tuple[str, threading.Event]]:
    claimed: list[tuple[str, threading.Event]] = []
    now = time.time()
    with _SEG_LOCK:
        for item in urls:
            hit = _SEG_CACHE.get(item)
            if hit and now - hit[0] < _SEG_TTL:
                continue
            if item in _SEG_WAIT:
                continue
            ev = threading.Event()
            _SEG_WAIT[item] = ev
            claimed.append((item, ev))
    return claimed


def _fill_claimed(claimed: list[tuple[str, threading.Event]]) -> None:
    if not claimed:
        return
    urls = [item for item, _ev in claimed]
    got: dict[str, bytes] = {}
    try:
        if urls and "cdn.example" not in urls[0] and _CURL_BATCH_LOCK.acquire(blocking=False):
            try:
                got = _curl_batch_get(urls)
            finally:
                _CURL_BATCH_LOCK.release()
        if got:
            with _SEG_LOCK:
                for item, data in got.items():
                    _SEG_CACHE[item] = (time.time(), data, _seg_ctype(item))
                _seg_cache_trim_locked()
    finally:
        with _SEG_LOCK:
            for item, _ev in claimed:
                _SEG_WAIT.pop(item, None)
        for _item, ev in claimed:
            ev.set()
    leftover = [item for item, _ev in claimed if item not in got]
    for item in leftover:
        _IO_POOL.submit(_prefetch_one, item)


def _index_playlist(primary: str, alias: str, segs: list[str]) -> None:
    _PLAYLIST_SEGS[primary] = segs
    if alias and alias != primary:
        _PLAYLIST_SEGS[alias] = segs
    for i, item in enumerate(segs):
        _SEG_POS[item] = (primary, i)


def _kick_ahead(url: str) -> None:
    pos = _SEG_POS.get(url)
    if not pos:
        return
    key, idx = pos
    segs = _PLAYLIST_SEGS.get(key) or []
    nxt = segs[idx + 1 : idx + 1 + _AHEAD_SEGS]
    if not nxt:
        return
    claimed = _claim_missing(nxt)
    if claimed:
        _IO_POOL.submit(_fill_claimed, claimed)


def _prepare_playlist(url: str) -> bytes:
    now = time.time()
    owner = False
    wait: threading.Event | None = None
    with _HLS_LOCK:
        hit = _HLS_CACHE.get(url)
        if hit and now - hit[0] < _HLS_TTL:
            return hit[1]
        wait = _HLS_WAIT.get(url)
        if wait is None:
            wait = threading.Event()
            _HLS_WAIT[url] = wait
            owner = True
    if not owner:
        if not wait.wait(timeout=20):
            raise HTTPException(502, "playlist timeout")
        with _HLS_LOCK:
            hit = _HLS_CACHE.get(url)
        if hit:
            return hit[1]
        raise HTTPException(502, "not a playlist")
    try:
        data = _cdn_get(url, timeout=8, accept="application/vnd.apple.mpegurl,*/*")
        text = data.decode("utf-8", errors="ignore")
        if "#EXTM3U" not in text:
            raise HTTPException(502, "not a playlist")
        base = url
        if "#EXT-X-STREAM-INF" in text:
            variant = _pick_variant(text, url)
            if variant:
                data = _cdn_get(variant, timeout=8, accept="application/vnd.apple.mpegurl,*/*")
                text = data.decode("utf-8", errors="ignore")
                base = variant
        keys = _key_urls(text, base)
        all_segs = _media_uris(text, base)
        _index_playlist(base, url, all_segs)
        must = all_segs[:_START_SEGS]
        warm = all_segs[_START_SEGS:_WARM_SEGS]
        _prefetch_urls(keys + must, wait=True)
        rewritten = _inline_key_uris(text, base)
        rewritten = _rewrite_m3u8(rewritten, base)
        payload = rewritten.encode("utf-8")
        with _HLS_LOCK:
            _HLS_CACHE[url] = (now, payload)
            if base != url:
                _HLS_CACHE[base] = (now, payload)
        if warm:
            claimed = _claim_missing(warm)
            if claimed:
                _IO_POOL.submit(_fill_claimed, claimed)
        return payload
    finally:
        with _HLS_LOCK:
            _HLS_WAIT.pop(url, None)
        wait.set()


def _warm_playlist(url: str) -> None:
    try:
        _prepare_playlist(url)
    except Exception:
        pass


def _warm_play_one(code: str) -> bool:
    key = (code or "").strip().lower()
    if not key:
        return False
    try:
        from jable_http import is_blocked, play_cooling

        if is_blocked() or play_cooling():
            return False
    except Exception:
        pass
    with _PLAY_WARM_LOCK:
        if key in _PLAY_WARMING:
            return False
        _PLAY_WARMING.add(key)
    try:
        data = jable_play_cached(key) or jable_play_info(key)
        hls = str((data or {}).get("hls") or "")
        if not hls:
            return False
        _remember_play_origin(key, hls)
        _prepare_playlist(hls)
        return True
    except Exception:
        return False
    finally:
        with _PLAY_WARM_LOCK:
            _PLAY_WARMING.discard(key)


def _warm_play_many(codes: list[str]) -> int:
    ok = 0
    for code in codes[:3]:
        if _warm_play_one(code):
            ok += 1
    return ok


def _hls_proxy_uri(target: str) -> str:
    path = urlparse(target).path.lower()
    if path.endswith(".m3u8"):
        return "/api/jable/hls?url=" + quote(target, safe="")
    return "/api/jable/seg?url=" + quote(target, safe="")


def _rewrite_m3u8(body: str, base: str) -> str:
    out: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("#") and "URI=" in line:
            def repl(match: re.Match[str]) -> str:
                uri = match.group(1)
                if uri.startswith("data:"):
                    return match.group(0)
                abs_url = urljoin(base, uri)
                return 'URI="' + _hls_proxy_uri(abs_url) + '"'

            out.append(re.sub(r'URI="([^"]+)"', repl, raw))
        elif line and not line.startswith("#"):
            abs_url = urljoin(base, line)
            out.append(_hls_proxy_uri(abs_url))
        else:
            out.append(raw)
    return "\n".join(out) + "\n"


@app.get("/api/jable/hls")
def api_jable_hls(url: str) -> Response:
    raw = unquote((url or "").strip())
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(400, "bad url")
    payload = _prepare_playlist(raw)
    return Response(
        content=payload,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "private, max-age=60"},
    )


@app.get("/api/jable/seg")
def api_jable_seg(url: str) -> Response:
    raw = unquote((url or "").strip())
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(400, "bad url")
    _kick_ahead(raw)
    _maybe_refresh_token(raw)
    data, ctype = _seg_bytes(raw)
    return Response(
        content=data,
        media_type=ctype,
        headers={"Cache-Control": "public, max-age=300", "X-Content-Type-Options": "nosniff"},
    )


@app.post("/api/detect")
def api_detect(body: ParseIn) -> dict[str, Any]:
    if body.jable and body.jable.mode in {"hot", "pick"}:
        return {"site": "jable", "kind": body.jable.mode, "query": body.query or body.jable.mode, "url": ""}
    return detect(body.query, body.site)


@app.post("/api/parse")
def api_parse(body: ParseIn) -> dict[str, Any]:
    jable = body.jable.model_dump() if body.jable and body.jable.mode in {"hot", "pick"} else None
    query = (body.query or "").strip()
    if not query and not jable:
        raise HTTPException(400, "请输入链接或选择热门 / 選片")
    task = RUNNER.submit_parse(query, body.site, max(0, body.limit), body.tab, jable=jable)
    return task.snapshot()


@app.post("/api/download")
def api_download(body: DownloadIn) -> dict[str, Any]:
    try:
        task = RUNNER.submit_download(
            body.parse_id,
            body.ids,
            quality=body.quality,
            subs=body.subs,
            workers=body.workers,
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return task.snapshot()


@app.post("/api/jable/save")
def api_jable_save(body: JableSaveIn) -> dict[str, Any]:
    raw = (body.code or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,40}", raw):
        raise HTTPException(400, "番号无效")
    try:
        from jable_http import hold_crawlers

        hold_crawlers(90.0)
    except Exception:
        pass
    try:
        task = RUNNER.submit_jable_save(raw, subs=body.subs, workers=body.workers)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return task.snapshot()


@app.get("/api/tasks/{task_id}")
def api_task(task_id: str) -> dict[str, Any]:
    task = RUNNER.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task.snapshot()


@app.post("/api/tasks/{task_id}/cancel")
def api_cancel(task_id: str) -> dict[str, Any]:
    task = RUNNER.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    task.cancel()
    return task.snapshot()


@app.get("/api/tasks/{task_id}/stream")
def api_stream(task_id: str) -> StreamingResponse:
    task = RUNNER.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")

    def gen():
        for rec in task.iter_events():
            yield f"data: {json.dumps(rec, ensure_ascii=False)}\n\n"
        yield "data: {\"event\":\"close\"}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _cover_cache_path(url: str) -> Path:
    from .jable_index import cover_cache_path

    return cover_cache_path(url)


@app.get("/api/proxy")
def api_proxy(url: str) -> Response:
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "bad url")
    host = parsed.netloc.lower()
    referer = "https://jable.tv/" if "jable.tv" in host else f"{parsed.scheme}://{parsed.netloc}/"
    if "douyin" in host or "byteimg" in host or "tiktokcdn" in host:
        referer = "https://www.douyin.com/"
    if "ytimg" in host or "youtube" in host or "ggpht" in host:
        referer = "https://www.youtube.com/"
    cache_path = None
    if "jable" in host or "assets-cdn" in host:
        cache_path = _cover_cache_path(raw)
        if cache_path.is_file() and cache_path.stat().st_size >= 80:
            data = cache_path.read_bytes()
            ctype = "image/jpeg"
            if data[:8] == b"\x89PNG\r\n\x1a\n":
                ctype = "image/png"
            return Response(content=data, media_type=ctype, headers={"Cache-Control": "public, max-age=86400"})
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36"
    data = b""
    ctype = "image/jpeg"
    cf_host = "jable.tv" in host or "assets-cdn" in host
    if not cf_host:
        try:
            from jable_http import pooled_get

            data = pooled_get(
                raw,
                timeout=8,
                referer=referer,
                accept="image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                extra_headers={"User-Agent": ua},
            )
        except Exception:
            data = b""
    if len(data) < 80:
        curl = shutil.which("curl.exe") or shutil.which("curl")
        if curl:
            result = subprocess.run(
                [
                    curl,
                    "-sL",
                    "--max-time",
                    "12",
                    "-A",
                    ua,
                    "-H",
                    f"Referer: {referer}",
                    "-H",
                    "Accept: image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    raw,
                ],
                check=False,
                capture_output=True,
            )
            data = result.stdout or b""
    if len(data) < 80:
        req = UrlRequest(
            raw,
            headers={
                "User-Agent": ua,
                "Referer": referer,
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
        try:
            with urlopen(req, timeout=12) as resp:
                data = resp.read()
                ctype = resp.headers.get("Content-Type") or ctype
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, str(exc)) from exc
    if data[:3] == b"\xff\xd8\xff":
        ctype = "image/jpeg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        ctype = "image/png"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ctype = "image/webp"
    if len(data) < 80:
        raise HTTPException(502, "cover download too small")
    if cache_path is not None:
        try:
            cache_path.write_bytes(data)
        except OSError:
            pass
    return Response(content=data, media_type=ctype, headers={"Cache-Control": "public, max-age=86400"})


MEDIA_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3"}


def _library_scan(root: Path, *, limit: int = 24) -> dict[str, Any]:
    sites: list[dict[str, Any]] = []
    scanned = 0
    for name in ("jable", "youtube", "douyin"):
        folder = root / name
        files: list[dict[str, Any]] = []
        total = 0
        if folder.is_dir():
            found: list[Path] = []
            for path in folder.rglob("*"):
                scanned += 1
                if scanned > 800:
                    break
                if not path.is_file() or path.suffix.lower() not in MEDIA_EXT:
                    continue
                total += 1
                found.append(path)
            found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for path in found[:limit]:
                stat = path.stat()
                files.append(
                    {
                        "name": path.name,
                        "rel": str(path.relative_to(root)),
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    }
                )
        sites.append({"site": name, "count": total, "recent": files})
    return {"path": str(root), "sites": sites}


@app.get("/api/library")
def api_library() -> dict[str, Any]:
    root = library_dir()
    root.mkdir(parents=True, exist_ok=True)
    return _library_scan(root)


@app.post("/api/open-library")
def api_open_library() -> dict[str, Any]:
    path = library_dir()
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        os.system(f'xdg-open "{path}"')
    return {"ok": True, "path": str(path)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(
        WEB_ROOT / "index.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


if WEB_ROOT.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_ROOT)), name="static")
