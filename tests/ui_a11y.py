# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright

from ui_support import BASE, shot


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE + "/#/library", wait_until="domcontentloaded")
        page.locator(".view-library").wait_for(state="visible", timeout=10000)

        page.keyboard.press("Tab")
        focused = page.evaluate(
            """() => {
              const el = document.activeElement;
              return {
                tag: el && el.tagName,
                cls: el && el.className,
                text: (el && el.textContent || '').trim(),
                href: el && el.getAttribute('href'),
              };
            }"""
        )
        print("first tab", focused)
        assert focused["cls"] and "skip" in focused["cls"], focused
        assert focused["text"] == "跳到主要内容", focused
        assert focused["href"] == "#app", focused

        current = page.locator('a.nav-link[data-nav="library"]')
        assert current.get_attribute("aria-current") == "page"

        page.locator("#global-query").click()
        page.locator("#global-query").fill("zzz-not-a-link")
        page.locator("#global-query").press("Enter")
        page.locator("#collect-drawer:not([hidden])").wait_for(state="visible", timeout=15000)
        page.wait_for_function(
            "document.querySelector('#collect-drawer')?.classList.contains('is-open')",
            timeout=8000,
        )
        page.wait_for_timeout(200)

        trap = page.evaluate(
            """() => {
              const root = document.querySelector('#collect-drawer');
              const selector = 'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';
              const items = [...root.querySelectorAll(selector)].filter((el) => !el.hasAttribute('disabled') && !el.closest('[hidden]'));
              return { n: items.length, first: items[0] && items[0].getAttribute('aria-label'), last: items.at(-1) && (items.at(-1).textContent || '').trim() };
            }"""
        )
        assert trap["n"] >= 2, trap

        page.evaluate(
            """() => {
              const root = document.querySelector('#collect-drawer');
              const selector = 'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';
              const items = [...root.querySelectorAll(selector)].filter((el) => !el.hasAttribute('disabled') && !el.closest('[hidden]'));
              items[items.length - 1].focus();
            }"""
        )
        page.keyboard.press("Tab")
        wrap = page.evaluate(
            """() => {
              const root = document.querySelector('#collect-drawer');
              const active = document.activeElement;
              return !!(root && active && root.contains(active));
            }"""
        )
        assert wrap, "Tab 离开了收藏单抽屉"
        shot(page, "_ui_a11y_drawer.png")

        page.keyboard.press("Escape")
        page.wait_for_function(
            """() => {
              const el = document.querySelector('#collect-drawer');
              return !el || el.hidden || !el.classList.contains('is-open');
            }""",
            timeout=5000,
        )
        browser.close()
    print("ui a11y ok")


if __name__ == "__main__":
    main()
