# -*- coding: utf-8 -*-
from pathlib import Path
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1] / "library"
ROOT.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8765"


def wait_cards(page, min_n=4, timeout=15000):
    page.wait_for_function(
        f"document.querySelectorAll('#jb-list-grid .av-card').length >= {min_n}",
        timeout=timeout,
    )


def time_cards(page, t0, *, hash_part, min_n=4, timeout_ms=1000):
    page.wait_for_function(
        f"location.hash.includes({hash_part!r}) && "
        f"document.querySelectorAll('#jb-list-grid .av-card').length >= {min_n}",
        timeout=timeout_ms,
    )
    return (time.perf_counter() - t0) * 1000


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        try:
            page.goto(BASE + "/#/jable/hot", wait_until="domcontentloaded", timeout=8000)
        except Exception as exc:
            if "ERR_CONNECTION_REFUSED" in str(exc) or "net::ERR_" in str(exc):
                print(f"server not up at {BASE} — start it and retry after warmup")
                browser.close()
                sys.exit(2)
            raise

        page.locator("#jable-list").wait_for(state="visible", timeout=15000)
        page.wait_for_function("document.querySelector('#jb-filter-right .av-dd')")
        wait_cards(page)
        page.locator("#jb-filter-right .av-dd-btn").click()
        t0 = time.perf_counter()
        page.locator('#jb-filter-right [data-sort="week"]').click()
        week_ms = time_cards(page, t0, hash_part="/jable/week", timeout_ms=1000)
        print("week", f"{week_ms:.0f}ms")
        assert week_ms < 1000, f"week cards {week_ms:.0f}ms >= 1000ms"

        page.goto(BASE + "/#/jable/latest", wait_until="domcontentloaded")
        page.locator("#jable-list").wait_for(state="visible")
        page.wait_for_function("document.querySelector('#jb-filter-left [data-dd=\"year\"]')")
        wait_cards(page)
        page.locator('#jb-filter-left [data-dd="year"] .av-dd-btn').click()
        t0 = time.perf_counter()
        page.locator('#jb-filter-left [data-year="2025"]').click()
        year_ms = time_cards(page, t0, hash_part="/jable/latest/2025", timeout_ms=1000)
        print("year 2025", f"{year_ms:.0f}ms")
        assert year_ms < 1000, f"year 2025 cards {year_ms:.0f}ms >= 1000ms"

        page.goto(BASE + "/#/jable/type", wait_until="domcontentloaded")
        page.locator("#jable-list").wait_for(state="visible")
        page.wait_for_function("document.querySelector('#jb-filter-left [data-dd=\"tag\"]')")
        wait_cards(page)
        page.locator('#jb-filter-left [data-dd="tag"] .av-dd-btn').click()
        page.locator(".av-cascade").wait_for(state="visible")
        page.locator('[data-cascade="1"] [data-group="衣著"]').click()
        page.locator('[data-cascade="2"] [data-tag="black-pantyhose"]').wait_for(state="visible")
        t0 = time.perf_counter()
        page.locator('[data-cascade="2"] [data-tag="black-pantyhose"]').click()
        tag_ms = time_cards(page, t0, hash_part="/jable/tag/", timeout_ms=1500)
        print("tag 黑絲", f"{tag_ms:.0f}ms")
        assert tag_ms < 1500, f"tag cards {tag_ms:.0f}ms >= 1500ms"
        page.screenshot(path=str(ROOT / "_ui_jable_fast.png"), full_page=True)
        browser.close()

    print("jable ui latency ok")


if __name__ == "__main__":
    main()
