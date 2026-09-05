# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright

from ui_support import BASE, shot


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.goto(BASE + "/#/jable/hot", wait_until="domcontentloaded")
        page.locator("#jable-list").wait_for(state="visible", timeout=15000)
        page.locator("#jb-list-grid .av-card").first.wait_for(timeout=30000)
        page.locator("#jb-list-grid .av-card-meta").first.wait_for(timeout=10000)
        try:
            page.wait_for_function(
                "!!(document.querySelector('#jb-list-grid .av-card-date') || document.querySelector('#jb-list-grid .av-card-actors'))",
                timeout=20000,
            )
        except Exception:
            pass
        dates = page.locator("#jb-list-grid .av-card-date").count()
        actors = page.locator("#jb-list-grid .av-card-actors").count()
        views = page.locator("#jb-list-grid .av-card-views").count()
        page.locator("#jb-list-grid .av-card").first.scroll_into_view_if_needed()
        shot(page, "_ui_card_meta.png")
        print("views", views, "dates", dates, "actors", actors)
        assert views >= 1
        browser.close()
    print("card meta ok")


if __name__ == "__main__":
    main()
