# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright

from ui_support import BASE, shot

JUMP_JS = """(n) => {
  const input = document.querySelector('#jb-pager .av-pager-input');
  if (!input) throw new Error('no pager input');
  input.scrollIntoView({block:'center'});
  input.value = String(n);
  input.dispatchEvent(new Event('input', {bubbles:true}));
  input.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
}"""

WAIT_JS = """(n) => {
  const pager = document.querySelector('#jb-pager');
  const on = pager && pager.querySelector('button.on, button[aria-current="page"]');
  const cards = document.querySelectorAll('#jb-list-grid .av-card');
  const last = Number((pager && pager.dataset.pages) || 0);
  const enough = cards.length >= 12 || (last > 0 && Number(n) === last);
  return !!(on && on.textContent.trim() === String(n) && enough);
}"""


def jump(page, n):
    t0 = page.evaluate("() => performance.now()")
    page.evaluate(JUMP_JS, n)
    page.wait_for_function(WAIT_JS, arg=n, timeout=15000)
    ms = page.evaluate("(t0) => Math.round(performance.now() - t0)", t0)
    cards = page.locator("#jb-list-grid .av-card")
    count = cards.count()
    codes = [cards.nth(i).get_attribute("data-code") for i in range(count)]
    first = codes[0] if codes else None
    pages = page.locator("#jb-pager").get_attribute("data-pages")
    return {"n": n, "count": count, "first": first, "codes": codes, "pages": pages, "ms": ms}


def check(page, hash_path, shot_name, sizes):
    page.set_viewport_size(sizes)
    page.goto(BASE + "/" + hash_path, wait_until="domcontentloaded")
    page.locator("#jable-list").wait_for(state="visible", timeout=15000)
    page.locator("#jb-list-grid .av-card").first.wait_for(timeout=15000)
    page.wait_for_function(
        "Number(document.querySelector('#jb-pager')?.dataset.pages||0) > 3000",
        timeout=20000,
    )
    page.wait_for_function("document.body.dataset.listSnap === '1'", timeout=30000)
    last_page = int(page.locator("#jb-pager").get_attribute("data-pages") or "0")
    jumps = []
    for n in (1, 40, 50, 3232, last_page):
        if n not in jumps:
            jumps.append(n)
    results = []
    for n in jumps:
        info = jump(page, n)
        results.append(info)
        print(
            hash_path,
            sizes["width"],
            info["n"],
            "cards",
            info["count"],
            "first",
            info["first"],
            "pages",
            info["pages"],
            "ms",
            info.get("ms"),
        )
        if n != last_page:
            assert info["count"] == 12, info
        else:
            assert info["count"] >= 1, info
        assert info["codes"] and all(info["codes"]), info
        if n != 1:
            assert (info.get("ms") or 0) < 300, info
    firsts = [r["first"] for r in results]
    assert len(set(firsts)) == len(firsts), firsts
    shot(page, shot_name)
    return results


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        check(page, "#/jable/hot", "_ui_far_hot.png", {"width": 1400, "height": 1000})
        check(page, "#/jable/latest", "_ui_far_latest.png", {"width": 1400, "height": 1000})
        check(page, "#/jable/type", "_ui_far_type.png", {"width": 1400, "height": 1000})
        check(page, "#/jable/hot", "_ui_far_hot_mobile.png", {"width": 390, "height": 844})
        check(page, "#/jable/type", "_ui_far_type_mobile.png", {"width": 390, "height": 844})
        browser.close()
    print("UI far-page ok")


if __name__ == "__main__":
    main()
