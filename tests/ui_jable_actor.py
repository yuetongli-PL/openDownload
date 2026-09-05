# -*- coding: utf-8 -*-
import re

from playwright.sync_api import sync_playwright

from ui_support import BASE, shot

SLUG = "e82b22cd3275fd0e569147d82fa1999d"
NAME = "彩月七緒"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.add_init_script(
            f"localStorage.setItem('od-jable-models', JSON.stringify({{'{SLUG}':'{NAME}'}}))"
        )
        page.goto(BASE + f"/#/jable/model/{SLUG}", wait_until="domcontentloaded")
        page.locator("#jable-list").wait_for(state="visible", timeout=15000)
        page.wait_for_function(
            f"document.querySelector('#jb-list-title')?.textContent.trim() === '{NAME}'",
            timeout=20000,
        )
        title = page.locator("#jb-list-title").inner_text().strip()
        assert title == NAME
        assert not re.fullmatch(r"[a-f0-9]{32}", title)
        page.locator("#jb-filter-right .av-dd-btn").first.wait_for(timeout=8000)
        sort_label = page.locator("#jb-filter-right .av-dd-btn").first.inner_text()
        assert "发布时间" in sort_label or "最多观看" in sort_label
        page.locator("#jb-filter-right .av-dd-btn").first.click()
        page.locator('#jb-filter-right [data-sort="video_viewed"]').click()
        page.wait_for_function("location.hash.includes('/viewed')", timeout=10000)
        page.wait_for_function(
            "document.querySelector('#jb-filter-right .av-dd-btn')?.textContent.includes('最多观看')",
            timeout=10000,
        )
        viewed_label = page.locator("#jb-filter-right .av-dd-btn").first.inner_text()
        assert "最多观看" in viewed_label
        cards = page.locator("#jb-list-grid .av-card").count()
        shot(page, "_ui_jable_actor.png")
        print("title", title, "cards", cards, "hash", page.evaluate("location.hash"), "sort", viewed_label)
        browser.close()
    print("jable actor jump ok")


if __name__ == "__main__":
    main()
