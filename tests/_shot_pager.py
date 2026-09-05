# -*- coding: utf-8 -*-
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1] / "library"
BASE = "http://127.0.0.1:8765"
JUMP = """(n) => {
  const input = document.querySelector('#jb-pager .av-pager-input');
  input.value = String(n);
  input.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
}"""


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.goto(BASE + "#/jable/hot", wait_until="domcontentloaded")
        page.wait_for_function("document.body.dataset.listSnap === '1'", timeout=30000)
        page.locator("#jb-pager").scroll_into_view_if_needed()
        page.locator("#jb-pager").screenshot(path=str(ROOT / "_ui_pager_bar_p1.png"))
        page.evaluate(JUMP, 50)
        page.wait_for_function(
            "document.querySelector('#jb-pager .av-pager-pages button.on')?.textContent.trim() === '50'"
        )
        page.locator("#jb-pager").screenshot(path=str(ROOT / "_ui_pager_bar_p50.png"))
        page.evaluate(JUMP, 3244)
        page.wait_for_function(
            "document.querySelector('#jb-pager .av-pager-pages button.on')?.textContent.trim() === '3244'"
        )
        page.locator("#jb-pager").screenshot(path=str(ROOT / "_ui_pager_bar_last.png"))
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(BASE + "#/jable/hot", wait_until="domcontentloaded")
        page.wait_for_function("document.body.dataset.listSnap === '1'", timeout=30000)
        page.locator("#jb-pager").scroll_into_view_if_needed()
        page.locator("#jb-pager").screenshot(path=str(ROOT / "_ui_pager_bar_mobile.png"))
        browser.close()
    print("pager bars saved")


if __name__ == "__main__":
    main()
