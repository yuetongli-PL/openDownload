# -*- coding: utf-8 -*-
"""Cache-hit path: inspect 完整视频 pipeline attaches in < 500ms."""
from __future__ import annotations

import sys
import time

from playwright.sync_api import sync_playwright

from ui_support import BASE, shot

PLAYLIST = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:2
#EXT-X-MEDIA-SEQUENCE:0
#EXTINF:2.0,
/api/jable/seg?url=https://cdn.example/seg0.ts
#EXT-X-ENDLIST
"""

PLAY_JSON = (
    '{"id":"hit-247","title":"hit","hls":"https://cdn.example/index.m3u8",'
    '"stream":"/api/jable/hls?url=https://cdn.example/index.m3u8","cached":true}'
)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.route(
            "**/api/jable/play?**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=PLAY_JSON,
            ),
        )
        page.route(
            "**/api/jable/hls**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/vnd.apple.mpegurl",
                body=PLAYLIST,
            ),
        )
        page.route("**/api/jable/seg**", lambda route: route.fulfill(status=200, body=b"x" * 32))
        try:
            page.goto(BASE + "/#/jable/hot", wait_until="domcontentloaded", timeout=8000)
        except Exception as exc:
            if "ERR_CONNECTION_REFUSED" in str(exc) or "net::ERR_" in str(exc):
                print("server not up at", BASE)
                browser.close()
                sys.exit(2)
            raise
        page.locator("#jable-list").wait_for(state="visible", timeout=15000)
        page.locator("#jb-list-grid .av-card").first.wait_for(timeout=20000)
        t0 = time.perf_counter()
        page.locator("#jb-list-grid .av-card").first.click()
        page.wait_for_function("document.body.classList.contains('jb-inspect-open')", timeout=3000)
        page.wait_for_function(
            """() => {
              const st = document.querySelector("#jb-inspect-status");
              const text = ((st && st.textContent) || "").trim();
              return text !== "正在解析 m3u8…" && text !== "正在准备播放…";
            }""",
            timeout=2000,
        )
        ms = (time.perf_counter() - t0) * 1000
        print("inspect full attach", f"{ms:.0f}ms")
        assert ms < 500, f"inspect full attach {ms:.0f}ms >= 500ms"
        shot(page, "_ui_jable_play_hit.png")
        browser.close()
    print("jable play hit ok")


if __name__ == "__main__":
    main()
