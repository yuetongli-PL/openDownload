# -*- coding: utf-8 -*-
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1] / "library"
ROOT.mkdir(parents=True, exist_ok=True)


def shot(page, name):
    page.screenshot(path=str(ROOT / name), full_page=True)
    print("shot", name, page.url, page.evaluate("document.body.dataset.site"))


def main() -> None:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto("http://127.0.0.1:8765/", wait_until="networkidle")
        page.wait_for_timeout(400)
        assert page.locator("#hero-eyebrow").count() == 0
        assert page.locator("#hero-lede").count() == 0
        assert page.locator(".board").count() == 0
        assert page.locator("#hero-title").inner_text() == "你想探索什么？"
        assert page.locator("#view-home").is_visible()
        assert page.locator("#sources").is_visible()
        shot(page, "_ui_home.png")

        page.locator('a.exhibit[href="#/jable"]').click()
        page.wait_for_function("location.hash.includes('jable')")
        page.wait_for_timeout(400)
        assert page.locator("#view-jable").is_visible()
        assert page.locator("#view-home").is_hidden()
        assert page.locator(".mark-jable").is_visible()
        assert page.locator("#query").is_visible()
        shot(page, "_ui_jable.png")

        page.locator('a[data-jmode="hot"]').click()
        page.wait_for_function("location.hash.includes('jable/hot')")
        page.wait_for_timeout(400)
        assert page.locator("#jable-hot").is_visible()
        shot(page, "_ui_jable_hot.png")

        page.locator("#btn-menu").click()
        page.get_by_role("tab", name="YouTube").click()
        page.wait_for_function("location.hash.includes('youtube')")
        page.wait_for_timeout(400)
        assert page.locator("#view-youtube").is_visible()
        assert page.locator("#yt-guide").is_visible()
        assert page.locator(".mark-youtube").is_visible()
        shot(page, "_ui_youtube.png")

        page.locator("#btn-menu").click()
        page.get_by_role("tab", name="抖音").click()
        page.wait_for_function("location.hash.includes('douyin')")
        page.wait_for_timeout(400)
        assert page.locator("#view-douyin").is_visible()
        assert page.locator("#douyin-nav").is_visible()
        assert page.locator(".mark-douyin").is_visible()
        shot(page, "_ui_douyin.png")

        page.locator('a[data-dmode="feed"]').click()
        page.wait_for_function("location.hash.includes('douyin/feed')")
        page.wait_for_timeout(400)
        shot(page, "_ui_douyin_feed.png")

        page.locator("a.app-home").first.click()
        page.wait_for_function("location.hash.includes('auto')")
        page.wait_for_timeout(300)
        assert page.locator("#view-home").is_visible()

        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        shot(page, "_ui_home_mobile.png")
        page.locator('a.exhibit[href="#/youtube"]').click()
        page.wait_for_function("location.hash.includes('youtube')")
        page.wait_for_timeout(300)
        shot(page, "_ui_youtube_mobile.png")
        browser.close()

    print("errors", errors)
    assert not errors, errors
    print("ui pages ok")


if __name__ == "__main__":
    main()
