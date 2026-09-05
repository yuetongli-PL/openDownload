# -*- coding: utf-8 -*-
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1] / "library"
ROOT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto("http://127.0.0.1:8765/#/jable", wait_until="domcontentloaded")
        page.locator(".av-hero-card, .av-card").first.wait_for(timeout=15000)
        page.wait_for_timeout(2500)
        page.screenshot(path=str(ROOT / "_ui_jable_feed.png"), full_page=True)
        assert page.locator("#jb-av-nav").is_visible()
        assert page.locator(".av-hero-card.main").count() == 1
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
        page.screenshot(path=str(ROOT / "_ui_jable_inspect.png"), full_page=True)
        browser.close()
    print("jable inspect split ok")


if __name__ == "__main__":
    main()
