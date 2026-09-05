# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright

from ui_support import BASE, shot


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE + "/#/library", wait_until="domcontentloaded")
        page.locator(".view-library").wait_for(state="visible", timeout=10000)
        page.locator(".view-library .media-card, .view-library .lib-row, .view-library .empty").first.wait_for(
            timeout=15000
        )

        page.locator('.chip[data-value="jable"]').click()
        page.wait_for_function("location.hash.includes('site=jable')", timeout=8000)
        page.locator(".view-library .media-card, .view-library .empty").first.wait_for(timeout=10000)
        jable_n = page.locator(".view-library .media-card").count()
        print("jable cards", jable_n)
        shot(page, "_ui_library_jable.png")

        page.locator("#lib-q").click()
        page.locator("#lib-q").fill("")
        page.locator("#lib-q").type("lulu", delay=40)
        page.wait_for_function("location.hash.includes('q=lulu')", timeout=8000)
        page.wait_for_function(
            """() => document.querySelectorAll('.view-library .media-card, .view-library .lib-row').length === 1""",
            timeout=10000,
        )
        assert page.locator(".view-library .media-card, .view-library .lib-row").count() == 1
        shot(page, "_ui_library_search.png")

        page.locator("#lib-sort .dropdown-btn, [data-dropdown='lib-sort'] .dropdown-btn").first.click()
        page.locator('.dropdown-item[data-value="name"]').click()
        page.wait_for_function("location.hash.includes('sort=name')", timeout=8000)

        page.locator("#lib-sort .dropdown-btn, [data-dropdown='lib-sort'] .dropdown-btn").first.click()
        page.locator('.dropdown-item[data-value="size"]').click()
        page.wait_for_function("location.hash.includes('sort=size')", timeout=8000)
        shot(page, "_ui_library_sort.png")

        page.locator(".view-library .media-card, .view-library .lib-row").first.click()
        page.locator("dialog[open] video.lib-player, dialog[open] video").wait_for(timeout=10000)
        page.wait_for_function(
            """() => {
              const v = document.querySelector('dialog[open] video');
              if (!v) return false;
              const src = v.currentSrc || v.src || '';
              const ready = v.readyState >= 1;
              return src.includes('/api/library/file?rel=') && (ready || v.preload !== undefined);
            }""",
            timeout=15000,
        )
        info = page.evaluate(
            """() => {
              const v = document.querySelector('dialog[open] video');
              return {
                src: (v && (v.currentSrc || v.src)) || '',
                ready: v ? v.readyState : 0,
              };
            }"""
        )
        assert "/api/library/file?rel=" in info["src"], info
        if info["ready"] < 1:
            page.locator("dialog[open] video").evaluate(
                """(v) => new Promise((resolve, reject) => {
                  if (v.readyState >= 1) return resolve(true);
                  const t = setTimeout(() => reject(new Error('no metadata')), 12000);
                  v.addEventListener('loadedmetadata', () => { clearTimeout(t); resolve(true); }, { once: true });
                })"""
            )
        assert page.get_by_role("button", name="在资源管理器中显示").count() >= 1
        shot(page, "_ui_library_play.png")
        browser.close()
    print("ui library ok")


if __name__ == "__main__":
    main()
