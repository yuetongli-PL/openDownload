# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright

from ui_support import BASE, pick_jable_code, shot


def open_global(page, text: str):
    box = page.locator("#global-query")
    box.wait_for(state="visible", timeout=8000)
    box.click()
    box.fill(text)
    box.press("Enter")


def wait_drawer(page, timeout=15000):
    page.wait_for_function(
        """() => {
          const el = document.querySelector('#collect-drawer');
          if (!el || el.hidden) return false;
          return el.classList.contains('is-open') || el.getAttribute('aria-label') === '收藏单';
        }""",
        timeout=timeout,
    )
    page.wait_for_timeout(220)


def main() -> None:
    code = pick_jable_code()
    print("success code", code)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE + "/#/jable", wait_until="domcontentloaded")
        page.locator("#view-jable").wait_for(state="visible", timeout=15000)

        open_global(page, "zzz-not-a-link")
        wait_drawer(page)
        page.locator("#collect-drawer .empty h3").wait_for(timeout=20000)
        heading = page.locator("#collect-drawer .empty h3").inner_text().strip()
        assert "失败" in heading or "无法" in heading, heading
        assert page.locator("[data-collect-retry]").count() >= 1
        shot(page, "_ui_collect_error.png")

        page.keyboard.press("Escape")
        page.wait_for_function(
            """() => {
              const el = document.querySelector('#collect-drawer');
              return !el || el.hidden;
            }""",
            timeout=5000,
        )
        page.wait_for_timeout(350)
        focused = page.evaluate("() => document.activeElement && document.activeElement.id")
        assert focused == "global-query", focused

        open_global(page, code)
        wait_drawer(page)
        page.locator("#collect-drawer .collect-item, #collect-drawer .collect-cards .media-card").first.wait_for(
            timeout=90000
        )
        items = page.locator("#collect-drawer .collect-item").count()
        cards = page.locator("#collect-drawer .collect-cards .media-card").count()
        assert items >= 1 or cards >= 1, (items, cards)
        assert page.locator("[data-collect-save]").count() >= 1
        shot(page, "_ui_collect_preview.png")

        page.locator("[data-drawer-close]").click()
        page.wait_for_function(
            """() => {
              const el = document.querySelector('#collect-drawer');
              return !el || el.hidden || !el.classList.contains('is-open');
            }""",
            timeout=5000,
        )
        browser.close()
    print("ui collect ok")


if __name__ == "__main__":
    main()
