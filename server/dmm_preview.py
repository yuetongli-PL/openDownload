# -*- coding: utf-8 -*-
"""按 Jable 品番解析 FANZA/DMM 公开样品 MP4（litevideo/freepv），不含付费流。"""
from __future__ import annotations

import http.cookiejar
import random
import re
import ssl
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterator
from urllib.parse import quote, urlparse

from .dmm_head_cache import HEAD, HEAD_BYTES, file_total, parse_range

# 画质从高到低
QUALITIES = ("hhb", "hmb", "mhb", "mmb", "dm", "sm")
MIN_VIDEO = 200_000

BASE = "https://www.dmm.co.jp"
AGE_CHECK = "https://www.dmm.co.jp/age_check/=/declared=yes/?rurl="
REFERER = "https://www.dmm.co.jp/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
REGION_MARKERS = ("お住まいの地域からご利用になれません", "not available in your region")
AGE_MARKERS = ("年齢認証", "年齢確認", "あなたは18歳以上ですか")
PREVIEW_HOSTS = frozenset({"cc3001.dmm.co.jp", "cc3001.dmm.com"})
CACHE_TTL = 600.0

_CODE_RE = re.compile(r"^(\d*[a-z]+)[-_](\d+)([a-z0-9]*)$")
_CID_RE = re.compile(r"(?:/|=)cid=([^/\"'?&]+)", re.I)
_VIDEO_ID_RE = re.compile(r"video\.dmm\.co\.jp/av/content/\?id=([^\"'&]+)", re.I)
_PICS_RE = re.compile(
    r"pics\.dmm\.co\.jp/(?:digital/video|mono/movie/adult)/([0-9a-z_]+)/",
    re.I,
)
_CJK_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
_CR_TOTAL_RE = re.compile(r"/(\d+)\s*$")

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()
_HIT_URLS: dict[str, str] = {}
_HIT_LOCK = threading.Lock()
_CLIENT: _Client | None = None
_CLIENT_LOCK = threading.Lock()


def normalize_code(code: str) -> str:
    """小写、去空白，下划线收成连字符。"""
    return re.sub(r"_+", "-", (code or "").strip().lower())


def digital_cids(code: str) -> list[str]:
    """Jable/AV 品番 → DMM 数字 cid 候选。

    ssis-001 → ssis00001；abf-341 → abf00341；300mium-001 → 300mium00001。
    另含 3 位补零与不补零，去重。
    """
    raw = normalize_code(code)
    out: list[str] = []
    seen: set[str] = set()

    def add(cid: str) -> None:
        cid = cid.strip()
        if cid and cid not in seen:
            seen.add(cid)
            out.append(cid)

    if not raw:
        return out
    m = _CODE_RE.fullmatch(raw)
    if not m:
        add(raw.replace("-", ""))
        return out
    prefix, digits, tail = m.group(1), m.group(2), m.group(3)
    n = int(digits)
    add(f"{prefix}{n:05d}{tail}")
    add(f"{prefix}{n:03d}{tail}")
    add(f"{prefix}{n}{tail}")
    add(f"{prefix}{digits}{tail}")
    return out


def preview_candidates(cid: str, quality: str) -> list[str]:
    """按 Desktop DMM 规则拼 litevideo/freepv 候选。"""
    cid = (cid or "").strip()
    if len(cid) < 3:
        return []
    c0, c3 = cid[0], cid[:3]
    urls: list[str] = []
    for suf in (quality, f"_{quality}_w"):
        urls.append(
            f"https://cc3001.dmm.co.jp/litevideo/freepv/{c0}/{c3}/{cid}/{cid}{suf}.mp4"
        )
    return urls


def guess_preview_urls(code: str) -> list[str]:
    """只按品番拼公开样品地址，不发网络请求。"""
    urls: list[str] = []
    seen: set[str] = set()
    for cid in digital_cids(code):
        for quality in QUALITIES:
            for url in preview_candidates(cid, quality):
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
    return urls


def fast_preview_urls(code: str) -> list[str]:
    """优先少量高命中候选，供并行探测。"""
    key = normalize_code(code)
    cached = remembered_preview_url(key)
    if cached:
        return [cached]
    cids = digital_cids(key)
    if not cids:
        return []
    urls: list[str] = []
    seen: set[str] = set()

    def add(cid: str, *qualities: str) -> None:
        for quality in qualities:
            for url in preview_candidates(cid, quality):
                if url not in seen:
                    seen.add(url)
                    urls.append(url)

    add(cids[0], "hhb", "hmb", "mhb")
    if len(cids) > 1:
        add(cids[1], "hhb", "hmb")
    return urls[:10]


def allowed_preview_url(url: str) -> bool:
    """仅允许 cc3001 上 /litevideo/freepv/ 的 https MP4。"""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if host not in PREVIEW_HOSTS:
        return False
    path = parsed.path or ""
    if "/litevideo/freepv/" not in path:
        return False
    return path.lower().endswith(".mp4")


def resolve_preview(code: str) -> dict[str, Any]:
    """探测公开样品，成功则缓存约 10 分钟；没有则 RuntimeError('没有公开预览')。"""
    key = normalize_code(code)
    if not key:
        raise RuntimeError("没有公开预览")
    now = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < CACHE_TTL:
            return dict(cached[1])

    client = _client()
    client.ensure_age()
    tried: set[str] = set()
    hit = _probe_cids(client, digital_cids(key), tried)
    if hit is None:
        hit = _probe_cids(client, client.search_cids(key), tried)
    if hit is None:
        raise RuntimeError("没有公开预览")

    result = {
        "id": key,
        "cid": hit["cid"],
        "quality": hit["quality"],
        "url": hit["url"],
        "bytes": int(hit.get("bytes") or 0),
    }
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), dict(result))
    return result


def stream_preview(
    url: str, range_header: str | None = None
) -> tuple[int, dict[str, str], Iterator[bytes]]:
    """代理公开预览：校验 URL，转发 Range，返回状态 / 响应头 / 分块。"""
    return _client().stream(url, range_header)


def remembered_preview_url(code: str) -> str | None:
    key = normalize_code(code)
    if not key:
        return None
    with _HIT_LOCK:
        return _HIT_URLS.get(key)


def remember_preview_url(code: str, url: str) -> None:
    key = normalize_code(code)
    raw = (url or "").strip()
    if not key or not allowed_preview_url(raw):
        return
    with _HIT_LOCK:
        _HIT_URLS[key] = raw


def preview_urls_for_code(code: str) -> list[str]:
    """命中过的地址排最前，其余按品番猜测。"""
    key = normalize_code(code)
    fast = fast_preview_urls(key)
    if fast and (len(fast) == 1 or remembered_preview_url(key)):
        return fast
    urls = guess_preview_urls(key)
    cached = remembered_preview_url(key)
    if cached:
        return [cached] + [u for u in urls if u != cached]
    return fast + [u for u in urls if u not in fast]


def _probe_url(client: _Client, url: str) -> str | None:
    kind, _ = client.probe(url)
    return url if kind == "ok" else None


def resolve_preview_url(code: str) -> str:
    """并行探测最可能的地址，避免串行 404 等待。"""
    key = normalize_code(code)
    if not key:
        raise RuntimeError("没有公开预览")
    cached = remembered_preview_url(key)
    if cached:
        return cached
    client = _client()
    fast = fast_preview_urls(key)
    rest = [u for u in guess_preview_urls(key) if u not in fast][:12]
    for batch in (fast, rest):
        if not batch:
            continue
        workers = min(8, len(batch))
        hit: str | None = None
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_probe_url, client, url) for url in batch]
            for fut in as_completed(futs):
                try:
                    url = fut.result()
                except Exception:
                    continue
                if url:
                    hit = url
                    break
        if hit:
            remember_preview_url(key, hit)
            return hit
    raise RuntimeError("没有公开预览")


def warm_preview(code: str) -> bool:
    """后台拉取首包并写入内存缓存。"""
    key = normalize_code(code)
    if not key:
        return False
    if HEAD.get(key):
        return True
    try:
        status, headers, chunks = stream_preview_for_code(key, f"bytes=0-{HEAD_BYTES - 1}")
        if status not in (200, 206):
            return False
        data = b"".join(chunks)
        if len(data) < 64 or b"ftyp" not in data[:64]:
            return False
        return True
    except Exception:
        return False


def warm_preview_many(codes: list[str], *, workers: int = 10) -> int:
    items = []
    seen: set[str] = set()
    for raw in codes:
        key = normalize_code(raw)
        if key and key not in seen:
            seen.add(key)
            items.append(key)
    if not items:
        return 0
    ok = 1 if warm_preview(items[0]) else 0
    rest = items[1:]
    if not rest:
        return ok
    workers = min(workers, 6, len(rest))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for hit in ex.map(warm_preview, rest):
            if hit:
                ok += 1
    return ok


def stream_preview_for_code(
    code: str, range_header: str | None = None
) -> tuple[int, dict[str, str], Iterator[bytes]]:
    """按品番开流：完整 Range 在缓存内则秒回，否则接上远端剩余字节。"""
    key = normalize_code(code)
    if not key:
        raise RuntimeError("没有公开预览")
    if HEAD.can_serve(key, range_header):
        served = HEAD.serve(key, range_header)
        if served is not None:
            return served
    stitched = _stitch_head_and_tail(key, range_header)
    if stitched is not None:
        return stitched
    hit = HEAD.get(key)
    url_hint = (hit[0] if hit else None) or remembered_preview_url(key)
    urls = [url_hint] if url_hint else []
    for url in preview_urls_for_code(key):
        if url not in urls:
            urls.append(url)
    if not urls:
        raise RuntimeError("没有公开预览")
    last: Exception | None = None
    for url in urls[:6]:
        try:
            status, headers, chunks = stream_preview(url, range_header)
            remember_preview_url(key, url)
            if _should_tee_head(range_header):
                return _tee_head_cache(key, url, status, headers, chunks)
            return status, headers, chunks
        except RuntimeError as exc:
            last = exc
            if "地域" in str(exc):
                raise
    raise last or RuntimeError("没有公开预览")


def _stitch_head_and_tail(
    code: str, range_header: str | None
) -> tuple[int, dict[str, str], Iterator[bytes]] | None:
    """请求越过首包时：先吐缓存，再从 DMM 接着拉，保证能播完。"""
    hit = HEAD.get(code)
    if not hit:
        return None
    url, data, total = hit
    start, end = parse_range(range_header, total)
    if start >= len(data) or end < len(data) or start > end or end >= total:
        return None
    rest = f"bytes={len(data)}-{end}"
    try:
        _status, _headers, chunks = stream_preview(url, rest)
    except RuntimeError:
        return None

    def gen() -> Iterator[bytes]:
        yield data[start:]
        yield from chunks

    headers = {
        "Content-Type": "video/mp4",
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{total}",
        "Content-Length": str(end - start + 1),
    }
    return 206, headers, gen()


def _should_tee_head(range_header: str | None) -> bool:
    if not range_header:
        return True
    return _range_starts_at_zero(range_header)


def _range_starts_at_zero(range_header: str) -> bool:
    m = re.match(r"^bytes=(\d+)-", (range_header or "").strip(), re.I)
    return bool(m and int(m.group(1)) == 0)


def _tee_head_cache(
    code: str,
    url: str,
    status: int,
    headers: dict[str, str],
    chunks: Iterator[bytes],
) -> tuple[int, dict[str, str], Iterator[bytes]]:
    buf = bytearray()

    def wrapped() -> Iterator[bytes]:
        nonlocal buf
        try:
            for block in chunks:
                if len(buf) < HEAD_BYTES:
                    need = HEAD_BYTES - len(buf)
                    buf.extend(block[:need])
                yield block
        finally:
            if len(buf) >= 64 and b"ftyp" in bytes(buf[:64]):
                total = file_total(headers)
                if total:
                    HEAD.put(code, url, bytes(buf), total)

    return status, headers, wrapped()


def iter_preview(
    url: str, range_header: str | None = None
) -> tuple[int, dict[str, str], Iterator[bytes]]:
    """同 stream_preview，便于按块转发。"""
    return stream_preview(url, range_header)


def _client() -> _Client:
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = _Client()
        return _CLIENT


def _try_quality(client: _Client, cid: str, quality: str) -> tuple[dict[str, Any] | None, bool]:
    urls = preview_candidates(cid, quality)
    if not urls:
        return None, True
    absent = 0
    for url in urls:
        kind, nbytes = client.probe(url)
        if kind == "ok":
            return {
                "cid": cid,
                "quality": quality,
                "url": url,
                "bytes": nbytes,
            }, False
        if kind == "miss":
            absent += 1
    return None, absent == len(urls)


def _probe_one_cid(client: _Client, cid: str) -> dict[str, Any] | None:
    """先探最高档；两边都 404 再用 sm 试探，避免不存在的 cid 扫完全部画质。"""
    first, last = QUALITIES[0], QUALITIES[-1]
    hit, first_absent = _try_quality(client, cid, first)
    if hit:
        return hit
    if first_absent:
        sm_hit, sm_absent = _try_quality(client, cid, last)
        if sm_absent:
            return None
        if sm_hit:
            for quality in QUALITIES[1:-1]:
                mid, _ = _try_quality(client, cid, quality)
                if mid:
                    return mid
            return sm_hit
    for quality in QUALITIES[1:]:
        hit, _ = _try_quality(client, cid, quality)
        if hit:
            return hit
    return None


def _probe_cids(client: _Client, cids: list[str], tried: set[str]) -> dict[str, Any] | None:
    for cid in cids:
        if not cid or cid in tried:
            continue
        tried.add(cid)
        hit = _probe_one_cid(client, cid)
        if hit:
            return hit
    return None


def _decode_html(raw: bytes) -> str:
    head = raw[:4096].decode("ascii", errors="ignore")
    m = re.search(r"charset\s*=\s*['\"]?([a-zA-Z0-9_\-]+)", head, re.I)
    declared = (m.group(1) if m else "").lower()
    aliases = {
        "euc-jp": "euc_jp",
        "x-euc-jp": "euc_jp",
        "shift_jis": "cp932",
        "shift-jis": "cp932",
        "utf8": "utf-8",
    }
    order: list[str] = []
    if declared:
        order.append(aliases.get(declared, declared))
    for enc in ("utf-8", "euc_jp", "cp932"):
        if enc not in order:
            order.append(enc)
    best, best_score = "", -1
    for enc in order:
        try:
            text = raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
        score = len(_CJK_RE.findall(text[:80000]))
        if score > best_score:
            best, best_score = text, score
    return best or raw.decode("utf-8", errors="replace")


def _raise_if_region(raw: bytes | str) -> None:
    if isinstance(raw, bytes):
        texts = (
            raw[:8000].decode("utf-8", errors="ignore"),
            raw[:8000].decode("euc_jp", errors="ignore"),
        )
    else:
        texts = (raw,)
    for text in texts:
        if any(mark in text for mark in REGION_MARKERS):
            raise RuntimeError("当前 IP 被地域限制")


def _content_bytes(headers: dict[str, str]) -> int:
    cr = headers.get("content-range") or ""
    m = _CR_TOTAL_RE.search(cr)
    if m:
        return int(m.group(1))
    cl = headers.get("content-length") or ""
    if cl.isdigit():
        n = int(cl)
        return 0 if n <= 2048 else n
    return 0


def _looks_like_video(body: bytes, headers: dict[str, str]) -> bool:
    if not body:
        return False
    ctype = (headers.get("content-type") or "").lower()
    if "image/" in ctype or "text/html" in ctype or "application/json" in ctype:
        return False
    sample = body[:256].lstrip()
    if sample.startswith(b"<") or b"<html" in body[:256].lower():
        return False
    if b"ftyp" in body[:64]:
        return True
    return ctype.startswith("video/")


def _cids_from_html(html: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    skip = {"search", "detail", "list", "videoa", "dvd"}

    def add(cid: str) -> None:
        cid = (cid or "").strip()
        if not cid or cid in seen or cid.lower() in skip or len(cid) < 4:
            return
        seen.add(cid)
        out.append(cid)

    for cid in _CID_RE.findall(html):
        add(cid)
    for cid in _VIDEO_ID_RE.findall(html):
        add(cid)
    for cid in _PICS_RE.findall(html):
        add(cid)
    return out


def _cookie(name: str, value: str, domain: str = ".dmm.co.jp") -> http.cookiejar.Cookie:
    return http.cookiejar.Cookie(
        0,
        name,
        value,
        None,
        False,
        domain,
        True,
        True,
        "/",
        True,
        False,
        None,
        True,
        None,
        None,
        {},
    )


class _Client:
    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout
        self._lock = threading.RLock()
        self.cj = http.cookiejar.CookieJar()
        ctx = ssl.create_default_context()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj),
            urllib.request.HTTPSHandler(context=ctx),
        )
        self._aged = False

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Accept-Encoding": "identity",
            "Referer": REFERER,
        }
        if extra:
            h.update(extra)
        return h

    def _has_age_cookie(self) -> bool:
        names = {c.name for c in self.cj}
        return "ckcy" in names or "age_check_done" in names

    def _inject_age_cookies(self) -> None:
        with self._lock:
            for name in ("ckcy", "age_check_done"):
                self.cj.set_cookie(_cookie(name, "1"))

    def _open(
        self,
        url: str,
        extra: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Any:
        last: Exception | None = None
        wait = timeout if timeout is not None else self.timeout
        for attempt in range(1, 3):
            req = urllib.request.Request(url, headers=self._headers(extra))
            try:
                return self.opener.open(req, timeout=wait)
            except urllib.error.HTTPError as e:
                if e.code == 206 and e.fp is not None:
                    return e
                if e.code in (404, 405, 410, 416):
                    raise
                last = e
                if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(0.4 * attempt + random.random() * 0.2)
                    continue
                raise
            except urllib.error.URLError as e:
                last = e
                if attempt < 2:
                    time.sleep(0.4 * attempt + random.random() * 0.2)
                    continue
                raise
        raise last or RuntimeError("请求失败")

    def age_check(self) -> None:
        url = AGE_CHECK + quote(f"{BASE}/mono/dvd/", safe="")
        resp = self._open(url)
        try:
            raw = resp.read(200_000)
        finally:
            resp.close()
        text = _decode_html(raw)
        _raise_if_region(text)
        if any(m in text for m in AGE_MARKERS) and not self._has_age_cookie():
            raise RuntimeError("年龄确认失败")
        if not self._has_age_cookie():
            self._inject_age_cookies()
        self._aged = True

    def ensure_age(self) -> None:
        with self._lock:
            if not self._aged:
                self.age_check()

    def fetch_html(self, url: str) -> str:
        self.ensure_age()
        resp = self._open(url, extra={"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"})
        try:
            raw = resp.read(2_000_000)
        finally:
            resp.close()
        text = _decode_html(raw)
        _raise_if_region(text)
        if any(m in text for m in AGE_MARKERS) and "cid=" not in text:
            self._aged = False
            self.age_check()
            resp = self._open(url)
            try:
                raw = resp.read(2_000_000)
            finally:
                resp.close()
            text = _decode_html(raw)
            _raise_if_region(text)
        return text

    def search_cids(self, code: str) -> list[str]:
        raw = normalize_code(code)
        queries: list[str] = []
        for q in (raw, raw.upper()):
            if q and q not in queries:
                queries.append(q)
        templates = (
            "https://www.dmm.co.jp/search/=/searchstr={}/",
            "https://www.dmm.co.jp/mono/dvd/-/search/=/searchstr={}/",
        )
        for q in queries:
            quoted = quote(q, safe="-")
            for tmpl in templates:
                try:
                    html = self.fetch_html(tmpl.format(quoted))
                except (urllib.error.HTTPError, urllib.error.URLError):
                    continue
                found = _cids_from_html(html)
                if found:
                    return found
        return []

    def probe(self, url: str) -> tuple[str, int]:
        extra = {"Range": "bytes=0-2047", "Accept": "*/*"}
        try:
            resp = self._open(url, extra=extra, timeout=4.0)
        except urllib.error.HTTPError as e:
            raw = b""
            try:
                raw = e.read(2048) if e.fp is not None else b""
            except Exception:
                raw = b""
            _raise_if_region(raw)
            return "miss", 0
        except urllib.error.URLError:
            return "miss", 0
        try:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            status = int(getattr(resp, "status", None) or getattr(resp, "code", None) or 200)
            body = resp.read(2048)
        finally:
            try:
                resp.close()
            except Exception:
                pass
        _raise_if_region(body)
        if status not in (200, 206):
            return "miss", 0
        total = _content_bytes(headers)
        if 0 < total < MIN_VIDEO:
            return "reject", 0
        if not _looks_like_video(body, headers):
            return "reject", 0
        return "ok", total

    def stream(
        self, url: str, range_header: str | None = None
    ) -> tuple[int, dict[str, str], Iterator[bytes]]:
        if not allowed_preview_url(url):
            raise RuntimeError("非法预览地址")
        self._inject_age_cookies()
        extra = {"Accept": "*/*"}
        if range_header:
            extra["Range"] = range_header
        req = urllib.request.Request(url, headers=self._headers(extra))
        try:
            resp = self.opener.open(req, timeout=60.0)
        except urllib.error.HTTPError as e:
            if e.code in (206, 416) and e.fp is not None:
                resp = e
            else:
                raw = b""
                try:
                    raw = e.read(800) if e.fp is not None else b""
                except Exception:
                    raw = b""
                _raise_if_region(raw)
                raise RuntimeError(f"预览请求失败 HTTP {e.code}") from e
        status = int(getattr(resp, "status", None) or getattr(resp, "code", None) or 200)
        rh = {k.lower(): v for k, v in resp.headers.items()}
        headers = {
            "Content-Type": "video/mp4",
            "Accept-Ranges": rh.get("accept-ranges") or "bytes",
        }
        if rh.get("content-range"):
            headers["Content-Range"] = rh["content-range"]
        if rh.get("content-length"):
            headers["Content-Length"] = rh["content-length"]

        def chunks() -> Iterator[bytes]:
            try:
                while True:
                    buf = resp.read(64 * 1024)
                    if not buf:
                        break
                    yield buf
            finally:
                try:
                    resp.close()
                except Exception:
                    pass

        return status, headers, chunks()
