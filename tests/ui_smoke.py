# -*- coding: utf-8 -*-
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOT = ROOT / "library" / "_ui_home.png"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.goto("http://127.0.0.1:8765/", wait_until="networkidle")
        assert page.title() == "openDownload"
        assert page.locator("#query").is_visible()
        assert page.locator(".board li").count() == 4
        page.get_by_role("tab", name="YouTube").click()
        page.wait_for_function("location.hash.includes('youtube')")
        assert "频道" in (page.locator("#query").get_attribute("placeholder") or "")
        page.get_by_role("tab", name="抖音").click()
        page.wait_for_function("location.hash.includes('douyin')")
        page.get_by_role("tab", name="Jable").click()
        page.wait_for_function("location.hash.includes('jable')")
        page.fill("#query", "mfyd-180")
        page.click("#btn-parse")
        page.locator("#panel-confirm").wait_for(state="visible", timeout=60000)
        title = page.locator("#head-title").inner_text()
        assert "MFYD-180" in title or "mfyd-180" in title.lower()
        assert page.locator(".card").count() >= 1
        assert page.locator("#btn-download").is_visible()
        SHOT.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOT), full_page=True)
        browser.close()
    print("ui ok", title)


if __name__ == "__main__":
    main()
