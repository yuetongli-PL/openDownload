# -*- coding: utf-8 -*-
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1] / "library"
ROOT.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8765"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(BASE + "/#/jable/type", wait_until="domcontentloaded")
        page.locator("#jable-list").wait_for(state="visible", timeout=15000)
        page.wait_for_function("document.querySelector('#jb-filter-left [data-dd=\"tag\"]')")
        assert page.locator('#jb-filter-left [data-dd="level1"]').count() == 0
        assert page.locator('#jb-filter-left [data-dd="level2"]').count() == 0
        page.locator('#jb-filter-left [data-dd="tag"] .av-dd-btn').click()
        page.locator(".av-cascade").wait_for(state="visible")
        box = page.locator(".av-cascade").bounding_box()
        c1 = page.locator('[data-cascade="1"]').bounding_box()
        c2 = page.locator('[data-cascade="2"]').bounding_box()
        assert box and c1 and c2
        assert abs(c1["y"] - c2["y"]) < 8, "columns should be on one row"
        assert c2["x"] > c1["x"] + 80, "level2 should sit to the right of level1"
        page.locator('[data-cascade="1"] [data-group="衣著"]').click()
        page.locator('[data-cascade="2"] [data-tag="black-pantyhose"]').wait_for(state="visible")
        page.screenshot(path=str(ROOT / "_ui_jable_dd_cascade.png"), full_page=False)
        page.locator('[data-cascade="2"] [data-tag="black-pantyhose"]').click()
        page.wait_for_function("location.hash.includes('/jable/tag/')")
        page.wait_for_function("document.getElementById('jb-list-title')?.textContent === '黑絲'")
        page.locator("#jb-list-grid .av-card").first.wait_for(timeout=60000)
        browser.close()
    print("cascade two-column ok")


if __name__ == "__main__":
    main()
