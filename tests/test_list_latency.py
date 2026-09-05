# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8765"
TIMEOUT_S = 3
LIMIT_MS = 1000

CASES = [
    {"kind": "hot"},
    {"kind": "week"},
    {"kind": "month"},
    {"kind": "all"},
    {"kind": "latest"},
    {"kind": "type"},
    {"kind": "cat", "slug": "chinese-subtitle"},
    {"kind": "cat", "slug": "uncensored"},
    {"kind": "tag", "slug": "black-pantyhose"},
    {"kind": "tag", "slug": "creampie"},
    {"kind": "tag", "slug": "wife"},
    {"kind": "latest", "year": "2025"},
    {"kind": "latest", "year": "2026"},
]


def _label(params: dict[str, str]) -> str:
    parts = [params["kind"]]
    if params.get("slug"):
        parts.append(params["slug"])
    if params.get("year"):
        parts.append(f"year={params['year']}")
    return " ".join(parts)


def _server_down(msg: str) -> None:
    print(msg)
    if "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
        import pytest

        pytest.skip(msg)
    sys.exit(2)


def _is_unavailable(exc: BaseException) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return False
    if isinstance(exc, TimeoutError):
        return False
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            return False
        text = str(reason).lower()
        if "timed out" in text or "timeout" in text:
            return False
        return True
    return isinstance(exc, ConnectionError)


def _probe() -> None:
    url = BASE + "/api/health"
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as resp:
            resp.read()
    except Exception as exc:  # noqa: BLE001
        if _is_unavailable(exc):
            _server_down(f"server not up at {BASE} — start it and retry after warmup")
        raise


def _get_list(params: dict[str, str]) -> tuple[float, dict]:
    query = dict(params)
    query["pages"] = "1"
    url = BASE + "/api/jable/list?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        ms = (time.perf_counter() - t0) * 1000
        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            data = {"items": [], "error": str(exc)}
        return ms, data
    except Exception as exc:  # noqa: BLE001
        if _is_unavailable(exc):
            _server_down(f"server not up at {BASE} — start it and retry after warmup")
        raise
    ms = (time.perf_counter() - t0) * 1000
    data = json.loads(raw.decode("utf-8"))
    return ms, data


def test_list_latency() -> None:
    _probe()
    slow: list[str] = []
    for params in CASES:
        label = _label(params)
        ms, data = _get_list(params)
        items = data.get("items") or []
        ids = [str(row.get("id") or "") for row in items[:2]]
        pending = data.get("pending", False)
        print(label, f"{ms:.0f}ms", f"n={len(items)}", ids, f"pending={pending}")
        if ms >= LIMIT_MS:
            slow.append(f"{label} {ms:.0f}ms")
    assert not slow, "list calls exceeded 1000ms: " + "; ".join(slow)


if __name__ == "__main__":
    try:
        test_list_latency()
    except SystemExit:
        raise
    except Exception as exc:
        if type(exc).__name__ in {"Skipped", "SkipTest"}:
            sys.exit(2)
        raise
    print("list latency ok")
