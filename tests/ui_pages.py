# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright

from ui_support import BASE, attach_errors, shot


def main() -> None:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        errors = attach_errors(page)
        page.goto(BASE + "/#/", wait_until="domcontentloaded")
        page.locator(".view-home").wait_for(state="visible", timeout=10000)
        assert page.title() == "openDownload"
        assert "把喜欢的内容" in page.locator(".view-home h1").inner_text()
        assert page.locator("#home-query").is_visible()
        assert page.locator(".source-card").count() == 3
        shot(page, "_ui_home.png", full_page=True)

        page.locator('a.nav-link[data-nav="jable"]').click()
        page.wait_for_function("location.hash.includes('jable')")
        page.locator("#view-jable").wait_for(state="visible", timeout=15000)
        assert page.locator("#jb-av-nav").is_visible()
        shot(page, "_ui_jable.png", full_page=True)

        page.locator('#jb-av-nav [data-jmode="hot"]').click()
        page.wait_for_function("location.hash.includes('jable/hot')")
        page.locator("#jable-list").wait_for(state="visible", timeout=15000)
        shot(page, "_ui_jable_hot.png", full_page=True)

        page.locator('a.nav-link[data-nav="youtube"]').click()
        page.wait_for_function("location.hash.includes('youtube')")
        page.wait_for_function(
            "document.querySelector('.view-source h1')?.textContent.includes('YouTube')",
            timeout=10000,
        )
        assert page.locator("#source-query").is_visible()
        shot(page, "_ui_youtube.png", full_page=True)

        page.locator('a.nav-link[data-nav="douyin"]').click()
        page.wait_for_function("location.hash.includes('douyin')")
        page.wait_for_function(
            "document.querySelector('.view-source h1')?.textContent.includes('抖音')",
            timeout=10000,
        )
        shot(page, "_ui_douyin.png", full_page=True)

        page.locator('#tab-dy-feed').click()
        page.wait_for_function("location.hash.includes('douyin/feed')")
        page.wait_for_timeout(200)
        shot(page, "_ui_douyin_feed.png", full_page=True)

        page.locator('a.nav-link[data-nav="home"]').click()
        page.wait_for_function("location.hash === '#/' || location.hash === '#/auto'")
        page.locator(".view-home").wait_for(state="visible")

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        shot(page, "_ui_home_mobile.png", full_page=True)
        page.locator("#btn-menu").click()
        page.locator('a.nav-link[data-nav="youtube"]').click()
        page.wait_for_function("location.hash.includes('youtube')")
        page.locator(".view-source").wait_for(state="visible")
        shot(page, "_ui_youtube_mobile.png", full_page=True)
        browser.close()

    print("errors", errors)
    assert not errors, errors
    print("ui pages ok")


if __name__ == "__main__":
    main()
