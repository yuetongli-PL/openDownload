# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.goto(BASE + "/#/jable/hot", wait_until="domcontentloaded")
        page.locator("#jb-list-grid .av-card").first.wait_for(timeout=30000)
        page.locator("#jb-list-grid .av-card").first.click()
        page.wait_for_function("document.body.classList.contains('jb-inspect-open')", timeout=15000)
        page.wait_for_timeout(8000)
        print("title", page.locator("#jb-inspect-title").inner_text())
        print("actors", page.locator("#jb-inspect-actors").inner_html()[:800])
        print("status", page.locator("#jb-inspect-status").inner_text())
        browser.close()


if __name__ == "__main__":
    main()
