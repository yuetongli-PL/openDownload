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
        page.goto(BASE + "/#/jable/hot", wait_until="domcontentloaded")
        page.locator("#jable-list").wait_for(state="visible", timeout=15000)
        page.locator("#jb-list-grid .av-card").first.wait_for(timeout=60000)
        page.locator("#jb-inspect").wait_for(state="attached", timeout=15000)
        before = page.locator("#jb-list-grid .av-card").count()
        if before >= 12:
            assert before == 12
        page.locator("#jb-list-grid .av-card").first.click()
        page.wait_for_function("document.body.classList.contains('jb-inspect-open')")
        page.locator("#jb-inspect:not([hidden])").wait_for(state="visible")
        assert page.locator("#jb-list-grid .av-card").count() == 12
        title = page.locator("#jb-inspect-title").inner_text().strip()
        assert title
        page.screenshot(path=str(ROOT / "_ui_jable_inspect_list.png"), full_page=True)
        page.keyboard.press("Escape")
        page.wait_for_function("!document.body.classList.contains('jb-inspect-open')")
        after = page.locator("#jb-list-grid .av-card").count()
        assert after == 12 or after >= 10
        browser.close()
    print("jable inspect list ok")


if __name__ == "__main__":
    main()
