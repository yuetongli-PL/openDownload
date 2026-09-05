# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright

from ui_support import BASE, shot


def wait_cards(page, min_n=4, timeout=45000):
    page.locator("#jb-list-grid .av-card").first.wait_for(timeout=timeout)
    page.wait_for_function(
        f"document.querySelectorAll('#jb-list-grid .av-card').length >= {min_n}",
        timeout=timeout,
    )


def first_codes(page, n=6):
    return page.locator("#jb-list-grid .av-card").evaluate_all(
        f"(els) => els.slice(0, {n}).map((el) => el.getAttribute('data-code') || '')"
    )


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        page.goto(BASE + "/#/jable/hot", wait_until="domcontentloaded")
        page.locator("#jable-list").wait_for(state="visible", timeout=15000)
        page.wait_for_function("document.querySelector('#jb-filter-right .av-dd')")
        assert page.locator("#jb-filter-right .av-dd-label").inner_text().startswith("排序")
        wait_cards(page)
        page.wait_for_timeout(600)
        hot_codes = first_codes(page)
        page.locator("#jb-filter-right .av-dd-btn").click()
        page.wait_for_timeout(200)
        shot(page, "_ui_jable_dd_hot.png")

        page.locator('#jb-filter-right [data-sort="week"]').click()
        page.wait_for_function("location.hash.includes('/jable/week')")
        page.wait_for_function("document.getElementById('jb-list-title')?.textContent === '本周热门'")
        wait_cards(page, timeout=60000)
        page.wait_for_timeout(500)
        week_codes = first_codes(page)

        page.goto(BASE + "/#/jable/latest", wait_until="domcontentloaded")
        page.locator("#jable-list").wait_for(state="visible")
        page.wait_for_function("document.querySelectorAll('#jb-filter-left .av-dd').length >= 2")
        labels = page.locator("#jb-filter-left .av-dd-label").all_inner_texts()
        assert any("年份" in t for t in labels)
        assert any("月份" in t for t in labels)
        wait_cards(page)
        latest_codes = first_codes(page)
        page.locator('#jb-filter-left [data-dd="year"] .av-dd-btn').click()
        page.wait_for_timeout(200)
        shot(page, "_ui_jable_dd_year.png")

        page.locator('#jb-filter-left [data-year="2025"]').click()
        page.wait_for_function("location.hash.includes('/jable/latest/2025')")
        wait_cards(page, min_n=1, timeout=60000)
        page.wait_for_timeout(400)
        year_codes = first_codes(page)

        page.goto(BASE + "/#/jable/type", wait_until="domcontentloaded")
        page.locator("#jable-list").wait_for(state="visible")
        page.wait_for_function("document.querySelectorAll('#jb-filter-left .av-dd').length >= 2")
        type_labels = page.locator("#jb-filter-left .av-dd-label").all_inner_texts()
        assert any("分类" in t for t in type_labels)
        assert any("标签" in t for t in type_labels)
        wait_cards(page)
        type_codes = first_codes(page)
        page.locator('#jb-filter-left [data-dd="tag"] .av-dd-btn').click()
        page.locator(".av-cascade").wait_for(state="visible")
        page.wait_for_timeout(200)
        shot(page, "_ui_jable_dd_tag.png")

        page.locator('[data-cascade="1"] [data-group="衣著"]').click()
        page.locator('[data-cascade="2"] [data-tag="black-pantyhose"]').wait_for(state="visible")
        page.locator('[data-cascade="2"] [data-tag="black-pantyhose"]').click()
        page.wait_for_function("location.hash.includes('/jable/tag/')")
        page.wait_for_function("document.getElementById('jb-list-title')?.textContent === '黑絲'")
        wait_cards(page, timeout=60000)
        page.wait_for_timeout(400)
        tag_codes = first_codes(page)
        shot(page, "_ui_jable_list_tag.png", full_page=True)

        browser.close()

    print("hot", hot_codes)
    print("week", week_codes)
    print("latest", latest_codes)
    print("year", year_codes)
    print("type", type_codes)
    print("tag", tag_codes)
    assert hot_codes and week_codes and hot_codes != week_codes
    assert latest_codes and year_codes and latest_codes != year_codes
    assert tag_codes and type_codes and tag_codes != type_codes
    print("jable dropdown filters ok")


if __name__ == "__main__":
    main()
