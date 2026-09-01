# -*- coding: utf-8 -*-
"""Shared HTTP fetch for jable.tv (Cloudflare). Prefer Windows curl over urllib.

Python urllib is JA3-fingerprinted and typically gets HTTP 403. curl.exe
(Schannel) usually works. Try several curl strategies before giving up.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

_RATE_LOCK = threading.Lock()
_RATE_BLOCK_UNTIL = 0.0

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
        "15",
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
    if curl_has_flag(curl, "--retry"):
        cmd.extend(["--retry", "1", "--retry-delay", "0"])
    if extra:
        cmd.extend(extra)
    cmd.append(url)
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, **_popen_kw())
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


def note_rate_limit(seconds: float = 20.0) -> None:
    global _RATE_BLOCK_UNTIL
    with _RATE_LOCK:
        _RATE_BLOCK_UNTIL = max(_RATE_BLOCK_UNTIL, time.monotonic() + seconds)


def wait_rate_limit() -> None:
    while True:
        with _RATE_LOCK:
            delay = _RATE_BLOCK_UNTIL - time.monotonic()
        if delay <= 0:
            return
        time.sleep(min(delay, 1.0))


def warmup(timeout: int = 15) -> None:
    _curl_get_once(
        DEFAULT_REFERER,
        timeout=timeout,
        referer=DEFAULT_REFERER,
        accept=HTML_ACCEPT,
        ipv4=True,
        compressed=True,
        fresh_cookies=False,
    )


def is_cloudflare(raw: bytes | str) -> bool:
    text = raw[:4000].decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else raw[:4000]
    low = text.lower()
    return (
        "just a moment" in low
        or "cf-browser-verification" in low
        or "challenge-platform" in low
        or "cf-chl-" in low
    )


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
) -> tuple[bytes, str]:
    last_detail = ""
    last_body = b""
    n = max(1, retries)
    for attempt in range(n):
        wait_rate_limit()
        plan = CURL_PLANS[attempt % len(CURL_PLANS)]
        body, detail = _curl_get_once(
            url,
            timeout=timeout,
            referer=referer,
            accept=accept,
            extra=extra,
            **plan,
        )
        last_detail = detail
        if body and len(body) >= min_bytes and (validate is None or validate(body)):
            return body, detail
        if body:
            last_body = body
            if validate is not None and len(body) >= min_bytes:
                last_detail = f"{detail} (not a valid page)"
        if "http=429" in detail or "http=503" in detail or "http=403" in detail:
            wait = min(45.0, 8.0 * (2 ** attempt))
            note_rate_limit(wait)
            time.sleep(wait)
            continue
        time.sleep(0.8 * (attempt + 1))
    if last_body and len(last_body) >= min_bytes and (validate is None or validate(last_body)):
        return last_body, last_detail
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
        if data and len(data) >= min_bytes and (validate is None or validate(data)):
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
) -> tuple[str, str]:
    """Fetch HTML. Returns (text, diagnostic). Raises RuntimeError on failure."""

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
    rounds = max(1, retries)
    for attempt in range(rounds):
        body, detail = fetch_bytes(
            url,
            timeout=timeout,
            referer=referer,
            accept=HTML_ACCEPT,
            retries=3,
            min_bytes=400,
            validate=_ok,
            extra=extra_headers or None,
        )
        last_detail = detail
        if body and _ok(body):
            return body.decode("utf-8", errors="replace"), detail
        if "http=429" in detail or "http=503" in detail:
            wait = min(60.0, 5.0 * (2 ** attempt))
            print(f"warning: rate-limited, sleep {wait:.0f}s  {detail}", file=sys.stderr, flush=True)
            time.sleep(wait)
            warmup(timeout=min(20, timeout))
            continue
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
    for url, dest in jobs:
        body = b""
        try:
            if dest.is_file():
                body = dest.read_bytes()
        except OSError:
            body = b""
        detail = f"{exit_s} bytes={len(body)} parallel={pmax}"
        out_rows.append((url, body, detail))
    try:
        for item in work.iterdir():
            item.unlink(missing_ok=True)
        work.rmdir()
    except OSError:
        pass
    return out_rows
