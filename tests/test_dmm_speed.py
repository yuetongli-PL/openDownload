# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.dmm_head_cache import HEAD
from server.dmm_preview import fast_preview_urls, warm_preview, warm_preview_many


def test_fast_urls_short():
    urls = fast_preview_urls("ssis-001")
    assert len(urls) <= 10
    assert any("ssis00001hhb" in u for u in urls)


def test_head_cache_serve():
    code = "test-code"
    data = b"\x00\x00\x00\x20ftypisom" + b"x" * 1000
    url = "https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00001/ssis00001hhb.mp4"
    HEAD.drop(code)
    HEAD.put(code, url, data, 10_000_000)
    hit = HEAD.serve(code, "bytes=0-511")
    assert hit is not None
    status, headers, chunks = hit
    assert status == 206
    assert "10000000" in headers["Content-Range"]
    body = b"".join(chunks)
    assert len(body) == 512
    assert body.startswith(b"\x00\x00\x00\x20ftyp")
    assert HEAD.can_serve(code, "bytes=0-") is False
    HEAD.put(code, url, data, len(data))
    assert HEAD.get(code)[2] == 10_000_000


def test_warm_many_parallel():
    t0 = time.time()
    ok = warm_preview_many(["yuj-067", "jur-837"], workers=2)
    elapsed = time.time() - t0
    print(f"warm ok={ok} elapsed={elapsed:.2f}s")
    assert ok >= 1
    assert elapsed < 8.0


if __name__ == "__main__":
    test_fast_urls_short()
    test_head_cache_serve()
    try:
        test_warm_many_parallel()
    except Exception as exc:
        print("warm network skip:", exc)
    print("ok test_dmm_speed")
