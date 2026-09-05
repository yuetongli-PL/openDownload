# -*- coding: utf-8 -*-
"""DMM 预览首包内存缓存：只加速开头，绝不能把半截文件当成整片。"""
from __future__ import annotations

import re
import threading
import time
from typing import Iterator

HEAD_BYTES = 512 * 1024
TTL = 1800.0
MIN_TOTAL = 200_000
_RANGE_RE = re.compile(r"^bytes=(\d+)-(\d*)$", re.I)
_CR_TOTAL_RE = re.compile(r"/(\d+)\s*$")


class HeadCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[str, tuple[float, str, bytes, int]] = {}

    def put(self, code: str, url: str, data: bytes, total: int) -> None:
        key = (code or "").strip().lower()
        if not key or not data or total < MIN_TOTAL:
            return
        with self._lock:
            prev = self._store.get(key)
            if prev and prev[3] >= total and len(prev[2]) >= len(data[:HEAD_BYTES]):
                return
            self._store[key] = (time.time(), url, data[:HEAD_BYTES], total)

    def drop(self, code: str) -> None:
        key = (code or "").strip().lower()
        with self._lock:
            self._store.pop(key, None)

    def get(self, code: str) -> tuple[str, bytes, int] | None:
        key = (code or "").strip().lower()
        with self._lock:
            hit = self._store.get(key)
            if not hit:
                return None
            at, url, data, total = hit
            if time.time() - at > TTL or total < MIN_TOTAL:
                del self._store[key]
                return None
            return url, data, total

    def can_serve(self, code: str, range_header: str | None) -> bool:
        hit = self.get(code)
        if not hit:
            return False
        _, data, total = hit
        start, end = parse_range(range_header, total)
        return 0 <= start <= end < len(data)

    def serve(
        self, code: str, range_header: str | None
    ) -> tuple[int, dict[str, str], Iterator[bytes]] | None:
        hit = self.get(code)
        if not hit:
            return None
        _url, data, total = hit
        start, end = parse_range(range_header, total)
        if start < 0 or end >= len(data):
            return None
        chunk = data[start : end + 1]
        return 206, _range_headers(start, start + len(chunk) - 1, total), iter([chunk])


def parse_range(range_header: str | None, total: int) -> tuple[int, int]:
    last = max(0, total - 1)
    raw = (range_header or "").strip()
    if not raw:
        return 0, last
    m = _RANGE_RE.match(raw)
    if not m:
        return 0, last
    start = int(m.group(1))
    if m.group(2):
        end = min(int(m.group(2)), last)
    else:
        end = last
    return start, end


def file_total(headers: dict[str, str]) -> int:
    """只信 Content-Range 的 /总数，不用 Range 响应的 Content-Length。"""
    lowered = {k.lower(): v for k, v in headers.items()}
    cr = lowered.get("content-range") or ""
    m = _CR_TOTAL_RE.search(cr)
    if not m:
        return 0
    n = int(m.group(1))
    return n if n >= MIN_TOTAL else 0


def _range_headers(start: int, end: int, total: int) -> dict[str, str]:
    return {
        "Content-Type": "video/mp4",
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{total}",
        "Content-Length": str(end - start + 1),
    }


HEAD = HeadCache()
