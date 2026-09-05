# -*- coding: utf-8 -*-
"""List grid: 12 cards; desktop auto-fill (~4 cols); inspect split uses 2 cols."""
from playwright.sync_api import sync_playwright

from ui_support import BASE, shot


def grid_info(page, sel="#jb-list-grid"):
    return page.evaluate(
        """(sel) => {
          const host = document.querySelector(sel);
          const cards = [...host.querySelectorAll(':scope > .av-card')].filter(
            (c) => getComputedStyle(c).display !== "none"
          );
          const cols = getComputedStyle(host).gridTemplateColumns.split(' ').filter(Boolean).length;
          const tops = cards.map((c) => c.getBoundingClientRect().top).sort((a, b) => a - b);
          const rows = [];
          tops.forEach((t) => {
            if (!rows.length || Math.abs(t - rows[rows.length - 1]) > 4) rows.push(t);
          });
          return { n: cards.length, cols, rows: rows.length };
        }""",
        sel,
    )


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1100})
        for hash_path in ("#/jable/hot", "#/jable/latest", "#/jable/type"):
            page.goto(BASE + "/" + hash_path, wait_until="domcontentloaded")
            page.locator("#jable-list").wait_for(state="visible", timeout=15000)
            page.locator("#jb-list-grid .av-card").first.wait_for(timeout=30000)
            page.wait_for_function(
                "document.querySelectorAll('#jb-list-grid > .av-card').length >= 12",
                timeout=15000,
            )
            page.wait_for_timeout(800)
            info = grid_info(page)
            print(hash_path, info)
            assert info["n"] == 12, info
            assert info["cols"] >= 3, info
            assert info["rows"] >= 2, info
        page.locator("#jb-list-grid .av-card").first.click()
        page.wait_for_function("document.body.classList.contains('jb-inspect-open')", timeout=15000)
        page.wait_for_function(
            "document.querySelectorAll('#jb-list-grid > .av-card').length >= 12",
            timeout=15000,
        )
        page.wait_for_timeout(400)
        info = grid_info(page)
        print("inspect", info)
        assert info["n"] == 12, info
        assert info["cols"] == 2, info
        shot(page, "_ui_grid_34.png")
        browser.close()
    print("grid 12 / inspect 2-col ok")


if __name__ == "__main__":
    main()
