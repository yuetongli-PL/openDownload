# -*- coding: utf-8 -*-
"""Shared HTTP fetch for jable.tv (Cloudflare). Prefer Windows curl over urllib.

Python urllib is JA3-fingerprinted and typically gets HTTP 403. curl.exe
(Schannel) usually works. Try several curl strategies before giving up.
"""
from __future__ import annotations

import http.client
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

_RATE_LOCK = threading.Lock()
_RATE_BLOCK_UNTIL = 0.0
_PLAY_COOLDOWN_UNTIL = 0.0
DENIED_PAUSE = 1800.0
PLAY_COOLDOWN = 180.0
CHALLENGE_PAUSE = 25.0
_RATE_PATH = Path(tempfile.gettempdir()) / "jable-http.ratelimit"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_REFERER = "https://jable.tv/"
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
COOKIE_NAME = "jable-hls.cookies"
_CURL_HELP = ""
_CURL_BIN: str | None | bool = False


def cookie_path() -> Path:
    return Path(tempfile.gettempdir()) / COOKIE_NAME


def curl_bin() -> str | None:
    global _CURL_BIN
    if _CURL_BIN is not False:
        return _CURL_BIN if isinstance(_CURL_BIN, str) else None
    found = None
    for name in ("curl.exe", "curl"):
        hit = shutil.which(name)
        if hit:
            found = hit
            break
    if not found and sys.platform == "win32":
        system = os.environ.get("SystemRoot", r"C:\Windows")
        candidate = Path(system) / "System32" / "curl.exe"
        if candidate.is_file():
            found = str(candidate)
    _CURL_BIN = found
    return found


def curl_help_text(curl: str) -> str:
    global _CURL_HELP
    if _CURL_HELP:
        return _CURL_HELP
    chunks: list[str] = []
    for args in ([curl, "-h"], [curl, "-h", "global"], [curl, "-h", "tls"]):
        try:
            result = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                **_popen_kw(),
            )
        except OSError:
            continue
        chunks.append(result.stdout or "")
        chunks.append(result.stderr or "")
    _CURL_HELP = "\n".join(chunks)
    return _CURL_HELP


def curl_has_flag(curl: str, flag: str) -> bool:
    return flag in curl_help_text(curl)


def curl_supports_parallel(curl: str) -> bool:
    text = curl_help_text(curl)
    return "--parallel" in text or " -Z, " in text


def _popen_kw() -> dict[str, Any]:
    kw: dict[str, Any] = {}
    if sys.platform == "win32":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return kw


def browser_headers(referer: str, accept: str) -> list[str]:
    headers = [
        "-A",
        USER_AGENT,
        "-H",
        f"Accept: {accept}",
        "-H",
        "Accept-Language: zh-TW,zh;q=0.9,en;q=0.8",
        "-H",
        f"Referer: {referer}",
        "-H",
        'sec-ch-ua: "Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "-H",
        "sec-ch-ua-mobile: ?0",
        "-H",
        'sec-ch-ua-platform: "Windows"',
    ]
    if "text/html" in accept:
        headers.extend(
            [
                "-H",
                "Upgrade-Insecure-Requests: 1",
                "-H",
                "sec-fetch-dest: document",
                "-H",
                "sec-fetch-mode: navigate",
                "-H",
                "sec-fetch-site: none",
                "-H",
                "sec-fetch-user: ?1",
            ]
        )
    return headers


def _curl_get_once(
    url: str,
    *,
    timeout: int,
    referer: str,
    accept: str,
    ipv4: bool,
    compressed: bool,
    fresh_cookies: bool,
    extra: list[str] | None = None,
    priority: bool = False,
    connect_timeout: int = 15,
) -> tuple[bytes, str]:
    curl = curl_bin()
    if not curl:
        return b"", "curl not found"
    cookie = cookie_path()
    if fresh_cookies:
        try:
            cookie.unlink(missing_ok=True)
        except OSError:
            pass
    out_path = Path(tempfile.gettempdir()) / f"jable-http-{os.getpid()}-{time.time_ns()}.bin"
    cmd = [
        curl,
        "-sS",
        "-L",
        "--max-time",
        str(max(5, int(timeout))),
        "--connect-timeout",
        str(max(2, int(connect_timeout))),
        "-o",
        str(out_path),
        "-w",
        "%{http_code} %{errormsg}",
        "-b",
        str(cookie),
        "-c",
        str(cookie),
        *browser_headers(referer, accept),
    ]
    if compressed:
        cmd.append("--compressed")
    if ipv4:
        cmd.append("-4")
    if curl_has_flag(curl, "--ssl-no-revoke"):
        cmd.append("--ssl-no-revoke")
    if (not priority) and curl_has_flag(curl, "--retry"):
        cmd.extend(["--retry", "1", "--retry-delay", "0"])
    if extra:
        cmd.extend(extra)
    cmd.append(url)
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            timeout=max(6, int(timeout) + 2),
            **_popen_kw(),
        )
    except subprocess.TimeoutExpired:
        return b"", "curl timeout"
    except OSError as exc:
        return b"", f"curl spawn failed: {exc}"
    body = b""
    try:
        if out_path.is_file():
            body = out_path.read_bytes()
    except OSError:
        body = b""
    finally:
        try:
            out_path.unlink(missing_ok=True)
        except OSError:
            pass
    status_line = (result.stdout or b"").decode("utf-8", errors="replace").strip()
    err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
    parts = status_line.split(" ", 1)
    http_code = parts[0] if parts else ""
    curl_err = parts[1].strip() if len(parts) > 1 else ""
    detail_bits = [
        f"exit={result.returncode}",
        f"http={http_code or '?'}",
        f"bytes={len(body)}",
    ]
    if ipv4:
        detail_bits.append("ipv4")
    if not compressed:
        detail_bits.append("identity")
    if fresh_cookies:
        detail_bits.append("fresh-cookies")
    if curl_err:
        detail_bits.append(curl_err)
    if err:
        detail_bits.append(err.replace("\n", " ")[:180])
    return body, " ".join(detail_bits)


CURL_PLANS: tuple[dict[str, Any], ...] = (
    {"ipv4": True, "compressed": True, "fresh_cookies": False},
    {"ipv4": False, "compressed": True, "fresh_cookies": False},
    {"ipv4": True, "compressed": True, "fresh_cookies": True},
    {"ipv4": True, "compressed": False, "fresh_cookies": True},
)


def _persist_rate_limit() -> None:
    with _RATE_LOCK:
        remain = max(0.0, _RATE_BLOCK_UNTIL - time.monotonic())
    try:
        if remain > 1:
            _RATE_PATH.write_text(str(time.time() + remain), encoding="utf-8")
        elif _RATE_PATH.exists():
            _RATE_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def _restore_rate_limit() -> None:
    try:
        until = float(_RATE_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return
    remain = until - time.time()
    if remain > 1:
        note_rate_limit(remain)


def note_rate_limit(seconds: float = 20.0) -> None:
    global _RATE_BLOCK_UNTIL
    with _RATE_LOCK:
        _RATE_BLOCK_UNTIL = max(_RATE_BLOCK_UNTIL, time.monotonic() + max(0.0, float(seconds)))
    _persist_rate_limit()


def note_play_cooldown(seconds: float = PLAY_COOLDOWN) -> None:
    global _PLAY_COOLDOWN_UNTIL
    with _RATE_LOCK:
        _PLAY_COOLDOWN_UNTIL = max(_PLAY_COOLDOWN_UNTIL, time.monotonic() + max(0.0, float(seconds)))


def play_cooldown_remaining() -> float:
    with _RATE_LOCK:
        return max(0.0, _PLAY_COOLDOWN_UNTIL - time.monotonic())


def play_cooling() -> bool:
    return play_cooldown_remaining() > 0


def hold_crawlers(seconds: float = 90.0) -> None:
    """Pause background list crawlers so a user play/inspect click can get through."""
    note_rate_limit(seconds)


def is_blocked() -> bool:
    with _RATE_LOCK:
        return _RATE_BLOCK_UNTIL > time.monotonic()


def blocked_remaining() -> float:
    with _RATE_LOCK:
        return max(0.0, _RATE_BLOCK_UNTIL - time.monotonic())


def wait_rate_limit() -> None:
    while True:
        with _RATE_LOCK:
            delay = _RATE_BLOCK_UNTIL - time.monotonic()
        if delay <= 0:
            return
        time.sleep(min(delay, 1.0))


def warmup(timeout: int = 15) -> None:
    cookie = cookie_path()
    try:
        if cookie.is_file() and time.time() - cookie.stat().st_mtime < 1800:
            return
    except OSError:
        pass
    _curl_get_once(
        DEFAULT_REFERER,
        timeout=timeout,
        referer=DEFAULT_REFERER,
        accept=HTML_ACCEPT,
        ipv4=True,
        compressed=True,
        fresh_cookies=False,
    )


_SSL_CTX = ssl.create_default_context()
_POOL_LOCK = threading.Lock()
_POOL: dict[tuple[str, str, int], deque[http.client.HTTPConnection]] = {}
_POOL_MAX = 16


def _conn_key(parsed: Any) -> tuple[str, str, int]:
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return (parsed.scheme, host, int(port))


def _borrow_conn(parsed: Any, timeout: int) -> http.client.HTTPConnection:
    key = _conn_key(parsed)
    conn = None
    with _POOL_LOCK:
        bucket = _POOL.get(key)
        if bucket:
            conn = bucket.popleft()
    if conn is not None:
        try:
            conn.timeout = timeout
            return conn
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
    if parsed.scheme == "https":
        return http.client.HTTPSConnection(
            parsed.hostname or "",
            parsed.port or 443,
            timeout=timeout,
            context=_SSL_CTX,
        )
    return http.client.HTTPConnection(parsed.hostname or "", parsed.port or 80, timeout=timeout)


def _return_conn(parsed: Any, conn: http.client.HTTPConnection | None) -> None:
    if conn is None:
        return
    key = _conn_key(parsed)
    stale = None
    with _POOL_LOCK:
        bucket = _POOL.get(key)
        if bucket is None:
            bucket = deque()
            _POOL[key] = bucket
        if len(bucket) >= _POOL_MAX:
            stale = bucket.popleft()
        bucket.append(conn)
    if stale is not None and stale is not conn:
        try:
            stale.close()
        except Exception:
            pass


def pooled_get(
    url: str,
    *,
    timeout: int = 20,
    referer: str = DEFAULT_REFERER,
    accept: str = "*/*",
    extra_headers: dict[str, str] | None = None,
    max_redirects: int = 5,
) -> bytes:
    """Keep-alive GET for CDN objects (covers, m3u8, keys, ts). Not for Cloudflare HTML."""
    current = url
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Referer": referer,
        "Connection": "keep-alive",
    }
    if extra_headers:
        headers.update(extra_headers)
    last_err = "empty"
    for _hop in range(max_redirects + 1):
        parsed = urlparse(current)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise RuntimeError(f"bad url: {current}")
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        for attempt in range(2):
            conn = None
            try:
                conn = _borrow_conn(parsed, timeout)
                conn.request("GET", path, headers=headers)
                resp = conn.getresponse()
                status = resp.status
                loc = resp.getheader("Location") or ""
                if status in {301, 302, 303, 307, 308} and loc:
                    resp.read()
                    _return_conn(parsed, conn)
                    current = urljoin(current, loc)
                    break
                data = resp.read() or b""
                expected = resp.getheader("Content-Length") or ""
                close = (resp.getheader("Connection") or "").lower() == "close" or status >= 400
                short = False
                if expected.isdigit():
                    need = int(expected)
                    if need > 0 and len(data) < need:
                        short = True
                        last_err = f"short read {len(data)}/{need}"
                        close = True
                if close:
                    try:
                        conn.close()
                    except Exception:
                        pass
                else:
                    _return_conn(parsed, conn)
                if status >= 400:
                    last_err = f"http {status}"
                    if attempt == 0:
                        continue
                    raise RuntimeError(last_err)
                if short:
                    if attempt == 0:
                        continue
                    raise RuntimeError(last_err)
                return data
            except Exception as exc:
                last_err = str(exc)
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                if attempt == 0:
                    continue
                raise RuntimeError(last_err) from exc
        else:
            continue
    raise RuntimeError(last_err)


def cloudflare_kind(raw: bytes | str | None) -> str:
    """Return 'denied' (1015/ban), 'challenge' (JS wall), or ''."""
    if not raw:
        return ""
    if isinstance(raw, (bytes, bytearray)):
        text = raw[:8000].decode("utf-8", errors="replace")
    else:
        text = raw[:8000]
    low = text.lower()
    if (
        "you are being rate limited" in low
        or "used cloudflare to restrict access" in low
        or ("access denied" in low and "cloudflare" in low)
        or "error 1015" in low
        or ">1015<" in low
        or "cf-error-details" in low and "1015" in low
    ):
        return "denied"
    if (
        "just a moment" in low
        or "cf-browser-verification" in low
        or "challenge-platform" in low
        or "cf-chl-" in low
    ):
        return "challenge"
    return ""


def is_cloudflare(raw: bytes | str | None) -> bool:
    return bool(cloudflare_kind(raw))


def _note_cloudflare(raw: bytes | str | None, detail: str = "") -> str:
    kind = cloudflare_kind(raw)
    info = detail or ""
    if kind == "denied" or "http=429" in info:
        note_rate_limit(DENIED_PAUSE)
        note_play_cooldown(PLAY_COOLDOWN)
        return "denied"
    if kind == "challenge":
        note_rate_limit(CHALLENGE_PAUSE)
        return "challenge"
    if "http=503" in info or "http=403" in info:
        note_rate_limit(min(90.0, CHALLENGE_PAUSE * 3))
        return "challenge"
    return kind


def fetch_bytes(
    url: str,
    *,
    timeout: int = 30,
    referer: str = DEFAULT_REFERER,
    accept: str = "*/*",
    retries: int = 4,
    min_bytes: int = 1,
    validate: Callable[[bytes], bool] | None = None,
    extra: list[str] | None = None,
    priority: bool = False,
) -> tuple[bytes, str]:
    last_detail = ""
    last_body = b""
    n = 1 if priority else max(1, retries)
    for attempt in range(n):
        if not priority:
            wait_rate_limit()
        elif attempt and is_blocked() and blocked_remaining() > 8:
            break
        plan = CURL_PLANS[attempt % len(CURL_PLANS)]
        body, detail = _curl_get_once(
            url,
            timeout=timeout,
            referer=referer,
            accept=accept,
            extra=extra,
            priority=priority,
            connect_timeout=3 if priority else 15,
            **plan,
        )
        last_detail = detail
        blocked = _note_cloudflare(body, detail)
        if blocked == "denied":
            last_body = body or last_body
            last_detail = f"{detail} (cloudflare 1015)"
            if priority:
                break
            wait_rate_limit()
            continue
        if body and len(body) >= min_bytes and not cloudflare_kind(body) and (
            validate is None or validate(body)
        ):
            return body, detail
        if body:
            last_body = body
            if cloudflare_kind(body) or (validate is not None and len(body) >= min_bytes):
                last_detail = f"{detail} (not a valid page)"
        if blocked or "http=429" in detail or "http=503" in detail or "http=403" in detail:
            if priority:
                break
            time.sleep(min(20.0, 6.0 * (attempt + 1)))
            continue
        if priority:
            break
        time.sleep(0.8 * (attempt + 1))
    if (
        last_body
        and len(last_body) >= min_bytes
        and not cloudflare_kind(last_body)
        and (validate is None or validate(last_body))
    ):
        return last_body, last_detail
    skip_urllib = priority and (
        cloudflare_kind(last_body)
        or any(
            tag in (last_detail or "")
            for tag in ("http=403", "http=429", "http=503", "http=1015", "cloudflare")
        )
    )
    if skip_urllib:
        return last_body, last_detail or "priority skip urllib"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Referer": referer,
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read() or b""
        if (
            data
            and len(data) >= min_bytes
            and not cloudflare_kind(data)
            and (validate is None or validate(data))
        ):
            return data, "urllib"
        last_detail = last_detail or f"urllib empty ({len(data)} bytes)"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        last_detail = last_detail or f"urllib: {exc}"
    return last_body, last_detail or "empty response"


def fetch_html(
    url: str,
    *,
    timeout: int = 30,
    referer: str = DEFAULT_REFERER,
    retries: int = 5,
    validate: Callable[[str], bool] | None = None,
    extra: list[str] | None = None,
    priority: bool = False,
) -> tuple[str, str]:
    """Fetch HTML. Returns (text, diagnostic). Raises RuntimeError on failure.

    priority=True skips the global crawler backoff so a user click (play/inspect)
    is not queued behind tag-cache 429 sleeps.
    """

    extra_headers = list(extra or [])
    if "mode=async" in url and not any("X-Requested-With" in x for x in extra_headers):
        extra_headers.extend(["-H", "X-Requested-With: XMLHttpRequest"])

    def _ok(raw: bytes) -> bool:
        if not raw or len(raw) < 400:
            return False
        if is_cloudflare(raw):
            return False
        text = raw.decode("utf-8", errors="replace")
        if validate is not None:
            return validate(text)
        return True

    last_detail = ""
    rounds = 1 if priority else max(1, retries)
    for attempt in range(rounds):
        body, detail = fetch_bytes(
            url,
            timeout=timeout,
            referer=referer,
            accept=HTML_ACCEPT,
            retries=1 if priority else 3,
            min_bytes=400,
            validate=_ok,
            extra=extra_headers or None,
            priority=priority,
        )
        last_detail = detail
        if body and _ok(body):
            return body.decode("utf-8", errors="replace"), detail
        blocked = _note_cloudflare(body, detail)
        if blocked == "denied":
            if priority:
                raise RuntimeError(f"fetch failed: {url} (cloudflare 1015 rate limited)")
            print(f"warning: cloudflare 1015, pause crawlers  {detail}", file=sys.stderr, flush=True)
            wait_rate_limit()
            continue
        if "http=429" in detail or "http=503" in detail or blocked:
            if priority:
                raise RuntimeError(f"fetch failed: {url} (rate limited)")
            wait = min(60.0, 5.0 * (2 ** attempt))
            print(f"warning: rate-limited, sleep {wait:.0f}s  {detail}", file=sys.stderr, flush=True)
            time.sleep(wait)
            warmup(timeout=min(20, timeout))
            continue
        if attempt + 1 < rounds:
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url} ({last_detail})")


def _write_curl_config(jobs: list[tuple[str, Path]], cfg: Path) -> None:
    lines: list[str] = []
    for url, dest in jobs:
        out = dest.as_posix().replace('"', '\\"')
        safe_url = url.replace('"', "%22")
        lines.append(f'url = "{safe_url}"')
        lines.append(f'output = "{out}"')
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fetch_many(
    urls: list[str],
    *,
    timeout: int = 40,
    referer: str = DEFAULT_REFERER,
    parallel_max: int = 8,
    extra: list[str] | None = None,
) -> list[tuple[str, bytes, str]]:
    """Fetch many URLs in one curl --parallel process. Same order as urls."""
    if not urls:
        return []
    curl = curl_bin()
    if not curl or not curl_supports_parallel(curl) or len(urls) == 1:
        out: list[tuple[str, bytes, str]] = []
        for url in urls:
            body, detail = fetch_bytes(
                url,
                timeout=timeout,
                referer=referer,
                accept=HTML_ACCEPT,
                retries=2,
                min_bytes=400,
                extra=extra,
            )
            out.append((url, body, detail))
        return out

    wait_rate_limit()
    work = Path(tempfile.gettempdir()) / f"jable-hot-par-{os.getpid()}-{time.time_ns()}"
    work.mkdir(parents=True, exist_ok=True)
    jobs: list[tuple[str, Path]] = []
    for i, url in enumerate(urls):
        jobs.append((url, work / f"{i:04d}.html"))
    cfg = work / "curl.cfg"
    _write_curl_config(jobs, cfg)
    pmax = str(max(1, min(parallel_max, len(jobs))))
    extra_headers = list(extra or [])
    if any("mode=async" in u for u in urls) and not any("X-Requested-With" in x for x in extra_headers):
        extra_headers.extend(["-H", "X-Requested-With: XMLHttpRequest"])
    cookie = cookie_path()
    cmd = [
        curl,
        "-sS",
        "-L",
        "-Z",
        "--parallel-max",
        pmax,
        "--connect-timeout",
        "10",
        "--max-time",
        str(max(8, int(timeout))),
        "-b",
        str(cookie),
        *browser_headers(referer, HTML_ACCEPT),
        "--compressed",
        "-4",
        "-K",
        str(cfg),
    ]
    if curl_has_flag(curl, "--parallel-immediate"):
        cmd.append("--parallel-immediate")
    if curl_has_flag(curl, "--parallel-max-host"):
        cmd.extend(["--parallel-max-host", pmax])
    if curl_has_flag(curl, "--tcp-nodelay"):
        cmd.append("--tcp-nodelay")
    if curl_has_flag(curl, "--ssl-no-revoke"):
        cmd.append("--ssl-no-revoke")
    if curl_has_flag(curl, "--http2"):
        cmd.append("--http2")
    if extra_headers:
        cmd.extend(extra_headers)
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, **_popen_kw())
        err = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        exit_s = f"exit={result.returncode}"
        if err:
            exit_s += " " + err.replace("\n", " ")[:180]
    except OSError as exc:
        exit_s = f"curl spawn failed: {exc}"
        result = None

    out_rows: list[tuple[str, bytes, str]] = []
    denied = 0
    for url, dest in jobs:
        body = b""
        try:
            if dest.is_file():
                body = dest.read_bytes()
        except OSError:
            body = b""
        detail = f"{exit_s} bytes={len(body)} parallel={pmax}"
        if _note_cloudflare(body, detail) == "denied":
            denied += 1
            body = b""
            detail += " (cloudflare 1015)"
        elif cloudflare_kind(body):
            body = b""
        out_rows.append((url, body, detail))
    if denied:
        note_rate_limit(DENIED_PAUSE)
    try:
        for item in work.iterdir():
            item.unlink(missing_ok=True)
        work.rmdir()
    except OSError:
        pass
    return out_rows


_restore_rate_limit()
