# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright

from ui_support import BASE, shot


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(BASE + "/#/jable", wait_until="domcontentloaded")
        page.locator("#jb-hot-grid .av-card, #jb-latest .av-card").first.wait_for(timeout=15000)
        page.wait_for_timeout(2500)
        shot(page, "_ui_jable_feed.png", full_page=True)
        assert page.locator("#jb-av-nav").is_visible()
        assert page.locator("#jb-hot-grid .av-card").count() >= 4
        assert page.locator("#jb-latest .av-card").count() >= 4
        page.locator("#jb-inspect").wait_for(state="attached", timeout=15000)
        page.locator("#jb-hot-grid .av-card").first.click()
        page.wait_for_function("document.body.classList.contains('jb-inspect-open')")
        page.locator("#jb-inspect:not([hidden])").wait_for(state="visible")
        n = page.locator("#jb-hot-grid .av-card").count()
        assert n == 12
        assert page.locator("#jb-inspect-video").count() >= 1
        h = page.evaluate("location.hash")
        opened = page.evaluate("document.body.classList.contains('jb-inspect-open')")
        assert opened
        assert "p=" in h or opened
        assert "/jable/v/" not in h
        page.wait_for_timeout(800)
        shot(page, "_ui_jable_inspect.png", full_page=True)
        browser.close()
    print("jable inspect split ok")


if __name__ == "__main__":
    main()
