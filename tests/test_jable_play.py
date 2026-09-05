# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PY = ROOT / "python"
if str(PY) not in sys.path:
    sys.path.insert(0, str(PY))

HTML = """
<html>
<head>
  <title>FNS-247 Sample Title - Jable.TV</title>
  <meta property="og:image" content="https://example.com/fns-247.jpg">
</head>
<body>
  <video poster="https://example.com/fns-247.jpg"></video>
  <script>
    var hlsUrl = 'https://cdn.example/hls/fns-247/2000000000/index.m3u8';
  </script>
</body>
</html>
"""


def test_parse_page_hls_url():
    from jable_hls import parse_page

    item = parse_page("https://jable.tv/videos/fns-247/", HTML, require_cover=False)
    assert item["hls"].endswith("index.m3u8")
    assert "fns-247" in item["hls"]
    assert (item.get("code") or "").lower() == "fns-247"
    assert "Sample Title" in (item.get("title") or "")


def test_play_info_uses_cached_hls():
    from server.jable_lists import play_cached, play_info, remember_play_html

    remember_play_html("fns-247-cache-test", "https://jable.tv/videos/fns-247-cache-test/", HTML)
    data = play_info("fns-247-cache-test")
    assert data.get("hls", "").endswith("index.m3u8")
    assert "fns-247" in data["hls"]
    hit = play_cached("fns-247-cache-test")
    assert hit and hit.get("cached") is True
    assert hit["hls"] == data["hls"]


def test_play_info_cache_hit_under_50ms():
    from server.jable_lists import play_info, remember_play_html

    remember_play_html("fns-247-hit", "https://jable.tv/videos/fns-247-hit/", HTML)
    play_info("fns-247-hit")
    t0 = time.perf_counter()
    data = play_info("fns-247-hit")
    ms = (time.perf_counter() - t0) * 1000
    assert ms < 50, f"play_info cache {ms:.1f}ms >= 50ms"
    assert data.get("cached") is True
    assert data.get("hls", "").endswith("index.m3u8")


def test_play_cached_unknown_is_none():
    from server.jable_lists import play_cached

    assert play_cached("no-such-code-xyz") is None


def test_hls_second_hit_under_50ms():
    from server import app as s

    url = "https://cdn.example/hls/fns-247/2000000000/index.m3u8"
    body = (
        b"#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXTINF:2,\nseg0.ts\n"
        b"#EXTINF:2,\nseg1.ts\n#EXT-X-ENDLIST\n"
    )
    s._HLS_CACHE.clear()
    s._SEG_CACHE.clear()
    s._PLAYLIST_SEGS.clear()
    s._SEG_POS.clear()
    orig = s._cdn_get
    s._cdn_get = lambda *a, **k: body
    try:
        first = s._prepare_playlist(url)
        assert b"#EXTM3U" in first
        t0 = time.perf_counter()
        payload = s._prepare_playlist(url)
        ms = (time.perf_counter() - t0) * 1000
        assert ms < 50, f"hls cache {ms:.1f}ms >= 50ms"
        assert b"#EXTM3U" in payload
        assert b"/api/jable/seg?url=" in payload
    finally:
        s._cdn_get = orig


def test_pick_variant_prefers_720():
    from server import app as s

    text = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360\nlow.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720\nmid.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=8000000,RESOLUTION=1920x1080\nhigh.m3u8\n"
    )
    picked = s._pick_variant(text, "https://cdn.example/master.m3u8")
    assert picked.endswith("/mid.m3u8")


def test_retarget_hls_url_rewrites_prefix():
    from server import app as s

    old = "https://cdn.example/hls/aaa/1788609510/1/2/20.ts"
    new_hls = "https://cdn.example/hls/bbb/1788609999/1/2/index.m3u8"
    s._CODE_PREFIX.clear()
    s._PREFIX_CODE.clear()
    s._remember_play_origin("fns-247", "https://cdn.example/hls/aaa/1788609510/1/2/index.m3u8")
    assert s._retarget_hls_url(old) == old
    s._remember_play_origin("fns-247", new_hls)
    rewritten = s._retarget_hls_url(old)
    assert rewritten.startswith("https://cdn.example/hls/bbb/1788609999/")
    assert rewritten.endswith("/1/2/20.ts")


def test_seg_request_prefetches_ahead():
    from server import app as s

    master = "https://cdn.example/index.m3u8"
    lines = ["#EXTM3U", "#EXT-X-TARGETDURATION:2"]
    for i in range(20):
        lines.append("#EXTINF:2,")
        lines.append(f"seg{i}.ts")
    lines.append("#EXT-X-ENDLIST")
    playlist = ("\n".join(lines) + "\n").encode("utf-8")

    fetched: list[str] = []
    lock = __import__("threading").Lock()

    def fake_cdn(url: str, timeout: int = 8, accept: str = "*/*", **_kw) -> bytes:
        with lock:
            fetched.append(url)
        if url.endswith(".m3u8"):
            return playlist
        return b"T" * 32

    s._HLS_CACHE.clear()
    s._SEG_CACHE.clear()
    s._PLAYLIST_SEGS.clear()
    s._SEG_POS.clear()
    orig = s._cdn_get
    s._cdn_get = fake_cdn
    try:
        s._prepare_playlist(master)
        deadline = time.perf_counter() + 2.0
        segs = set()
        while time.perf_counter() < deadline:
            with lock:
                segs = {u for u in fetched if u.endswith(".ts")}
            if len(segs) >= 8:
                break
            time.sleep(0.05)
        assert len(segs) >= 8, f"warm prefetch only got {len(segs)} segs"
        s._kick_ahead("https://cdn.example/seg7.ts")
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline:
            with lock:
                segs = {u for u in fetched if u.endswith(".ts")}
            if "https://cdn.example/seg15.ts" in segs:
                break
            time.sleep(0.05)
        assert "https://cdn.example/seg15.ts" in segs
    finally:
        deadline = time.perf_counter() + 2.0
        while time.perf_counter() < deadline:
            with s._SEG_LOCK:
                waiting = bool(s._SEG_WAIT)
            if not waiting:
                break
            time.sleep(0.05)
        s._cdn_get = orig


if __name__ == "__main__":
    test_parse_page_hls_url()
    test_play_info_uses_cached_hls()
    test_play_info_cache_hit_under_50ms()
    test_play_cached_unknown_is_none()
    test_hls_second_hit_under_50ms()
    test_pick_variant_prefers_720()
    test_retarget_hls_url_rewrites_prefix()
    test_seg_request_prefetches_ahead()
    print("ok test_jable_play")
