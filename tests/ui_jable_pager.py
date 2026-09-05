# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright

from ui_support import BASE, shot

JUMP_JS = """(n) => {
  const input = document.querySelector('#jb-pager .av-pager-input');
  if (!input) throw new Error('no pager input');
  input.value = String(n);
  input.dispatchEvent(new Event('input', {bubbles:true}));
  input.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
}"""

ON_BTN = '#jb-pager .av-pager-pages button.on, #jb-pager .av-pager-pages button[aria-current="page"]'


def pager_state(page):
    return page.evaluate(
        """() => {
          const host = document.querySelector('#jb-pager');
          const nums = [...host.querySelectorAll('.av-pager-pages button')].map((b) => b.textContent.trim());
          const on = host.querySelector('.av-pager-pages button.on, .av-pager-pages button[aria-current="page"]')?.textContent.trim();
          const first = host.querySelector('.av-pager-first');
          const prev = host.querySelector('.av-pager-prev');
          const next = host.querySelector('.av-pager-next');
          const last = host.querySelector('.av-pager-last');
          return {
            nums,
            on,
            pages: host.dataset.pages,
            first: first?.textContent.trim(),
            prev: prev?.textContent.trim(),
            next: next?.textContent.trim(),
            last: last?.textContent.trim(),
            firstOff: !!first?.disabled,
            prevOff: !!prev?.disabled,
            nextOff: !!next?.disabled,
            lastOff: !!last?.disabled,
            onIndex: nums.indexOf(on),
          };
        }"""
    )


def check(page, hash_path, shot_name):
    page.goto(BASE + "/" + hash_path, wait_until="domcontentloaded")
    page.locator("#jable-list").wait_for(state="visible", timeout=15000)
    page.wait_for_function(
        "Number(document.querySelector('#jb-pager')?.dataset.pages||0) > 10",
        timeout=20000,
    )
    page.wait_for_function("document.body.dataset.listSnap === '1'", timeout=30000)
    page.locator("#jb-list-grid .av-card").first.wait_for(timeout=20000)
    cards = page.locator("#jb-list-grid .av-card").count()
    pager = page.locator("#jb-pager")
    maxp = int(pager.get_attribute("data-pages") or "0")
    tops = page.locator("#jb-pager-top").count()
    stickies = page.locator("#jable-list .av-pager-sticky").count()
    pagers = page.locator("#jable-list .av-pager").count()
    ratio = page.evaluate(
        """() => {
          const el = document.querySelector('#jb-list-grid .av-thumb');
          if (!el) return 0;
          const r = el.getBoundingClientRect();
          return r.height ? r.width / r.height : 0;
        }"""
    )

    home = pager_state(page)
    print(hash_path, "home", home)
    assert home["first"] == "首"
    assert home["prev"] == "上"
    assert home["next"] == "下"
    assert home["last"] == "末"
    assert home["nums"] == ["1", "2", "3", "4", "5"]
    assert home["on"] == "1"
    assert home["onIndex"] == 0
    assert home["firstOff"] and home["prevOff"]
    assert not home["nextOff"] and not home["lastOff"]
    shot(page, shot_name, full_page=False)

    page.evaluate(JUMP_JS, 50)
    page.wait_for_function(
        f"""() => document.querySelector({ON_BTN!r})?.textContent.trim() === '50'""",
        timeout=10000,
    )
    mid = pager_state(page)
    print(hash_path, "mid", mid)
    assert mid["nums"] == ["48", "49", "50", "51", "52"]
    assert mid["on"] == "50"
    assert mid["onIndex"] == 2

    page.evaluate(JUMP_JS, maxp)
    page.wait_for_function(
        f"""() => document.querySelector({ON_BTN!r})?.textContent.trim() === '{maxp}'""",
        timeout=10000,
    )
    end = pager_state(page)
    print(hash_path, "end", end)
    assert end["on"] == str(maxp)
    assert end["nums"] == [str(i) for i in range(maxp - 4, maxp + 1)]
    assert end["onIndex"] == 4
    assert end["nextOff"] and end["lastOff"]
    assert not end["firstOff"] and not end["prevOff"]

    print(
        hash_path,
        "cards",
        cards,
        "pages",
        maxp,
        "pagers",
        pagers,
        "top",
        tops,
        "sticky",
        stickies,
        "ratio",
        round(ratio, 3),
        "text",
        pager.inner_text().replace("\n", " "),
    )
    assert cards <= 12
    assert maxp > 10
    assert tops == 0
    assert stickies == 0
    assert pagers == 1
    assert 1.5 <= ratio <= 1.7
    return cards


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        check(page, "#/jable/hot", "_ui_jable_pager_hot.png")
        check(page, "#/jable/latest", "_ui_jable_pager_latest.png")
        check(page, "#/jable/type", "_ui_jable_pager_type.png")
        page.set_viewport_size({"width": 390, "height": 844})
        check(page, "#/jable/hot", "_ui_jable_pager_hot_mobile.png")
        browser.close()
    print("pager ok on hot/latest/type")


if __name__ == "__main__":
    main()
