# -*- coding: utf-8 -*-
from playwright.sync_api import sync_playwright

from ui_support import BASE, shot

PAGE_SIZE = 12
BUDGET_MS = 300

JUMP_JS = """(n) => {
  const input = document.querySelector('#jb-pager .av-pager-input');
  if (!input) throw new Error('no pager input');
  input.scrollIntoView({block:'center'});
  input.value = String(n);
  input.dispatchEvent(new Event('input', {bubbles:true}));
  input.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
}"""

READY_JS = """({n, want}) => {
  const on = document.querySelector('#jb-pager button.on, #jb-pager button[aria-current="page"]');
  const cards = document.querySelectorAll('#jb-list-grid .av-card');
  return on && on.textContent.trim() === String(n) && cards.length === want;
}"""

LOADING_JS = """() => {
  const grid = document.querySelector('#jb-list-grid');
  if (!grid) return false;
  return !!grid.querySelector('.av-skel') && !grid.querySelector('.av-card');
}"""


def pager_pages(page):
    return int(page.locator("#jb-pager").get_attribute("data-pages") or "0")


def list_total(page):
    text = (page.locator("#jb-list-count").inner_text() or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def expected_count(n, last, total):
    if last > 0 and n >= last:
        rem = total % PAGE_SIZE
        return rem if rem else PAGE_SIZE
    return PAGE_SIZE


def jump_info(page, n, want, ms, loading=False):
    cards = page.locator("#jb-list-grid .av-card")
    count = cards.count()
    first = cards.first.get_attribute("data-code") if count else None
    pages = page.locator("#jb-pager").get_attribute("data-pages")
    return {
        "n": n,
        "count": count,
        "first": first,
        "pages": pages,
        "ms": ms,
        "want": want,
        "loading": loading,
    }


def jump(page, n, *, want, timeout=15000):
    t0 = page.evaluate("() => performance.now()")
    page.evaluate(JUMP_JS, n)
    page.wait_for_function(READY_JS, arg={"n": n, "want": want}, timeout=timeout)
    ms = page.evaluate("(t0) => Math.round(performance.now() - t0)", t0)
    return jump_info(page, n, want, ms)


def jump_tag(page, n, *, want):
    t0 = page.evaluate("() => performance.now()")
    page.evaluate(JUMP_JS, n)
    loading = bool(page.evaluate(LOADING_JS))
    timeout = 8000 if loading else 15000
    page.wait_for_function(READY_JS, arg={"n": n, "want": want}, timeout=timeout)
    ms = page.evaluate("(t0) => Math.round(performance.now() - t0)", t0)
    return jump_info(page, n, want, ms, loading=loading)


def log_jump(hash_path, info):
    print(
        hash_path,
        "n",
        info["n"],
        "cards",
        info["count"],
        "first",
        info["first"],
        "pages",
        info["pages"],
        "ms",
        info.get("ms"),
        "loading",
        info.get("loading"),
    )


def open_snap_list(page, hash_path):
    page.goto(BASE + "/" + hash_path, wait_until="domcontentloaded")
    page.locator("#jable-list").wait_for(state="visible", timeout=15000)
    page.locator("#jb-list-grid .av-card").first.wait_for(timeout=15000)
    page.wait_for_function(
        "Number(document.querySelector('#jb-pager')?.dataset.pages||0) > 3000",
        timeout=20000,
    )
    page.wait_for_function("document.body.dataset.listSnap === '1'", timeout=30000)
    last = pager_pages(page)
    total = list_total(page)
    assert last > 3000, last
    assert total > 0, total
    return last, total


def check_snap(page, hash_path, targets, shot_name):
    last, total = open_snap_list(page, hash_path)
    results = []
    for raw in targets:
        n = last if raw == "last" else int(raw)
        want = expected_count(n, last, total)
        info = jump(page, n, want=want)
        log_jump(hash_path, info)
        assert info["count"] == want, info
        assert info["first"], info
        assert (info.get("ms") or 0) < BUDGET_MS, info
        results.append(info)
    firsts = [r["first"] for r in results]
    assert len(set(firsts)) == len(firsts), firsts
    shot(page, shot_name)
    return results


def check_tag(page, hash_path, shot_name):
    page.goto(BASE + "/" + hash_path, wait_until="domcontentloaded")
    page.locator("#jable-list").wait_for(state="visible", timeout=15000)
    page.wait_for_function(
        """() => {
          const title = (document.querySelector('#jb-list-title')?.textContent || '').trim();
          const count = (document.querySelector('#jb-list-count')?.textContent || '').trim();
          const cards = document.querySelectorAll('#jb-list-grid .av-card').length;
          return !!title && /\\d/.test(count) && /部影片/.test(count) && cards > 0;
        }""",
        timeout=30000,
    )
    title = (page.locator("#jb-list-title").inner_text() or "").strip()
    count_text = (page.locator("#jb-list-count").inner_text() or "").strip()
    print(hash_path, "title", title, "count", count_text, "pages", pager_pages(page))
    info = jump_tag(page, 2, want=PAGE_SIZE)
    log_jump(hash_path, info)
    assert info["count"] == PAGE_SIZE, info
    assert info["first"], info
    if info.get("loading"):
        print(hash_path, "page 2 used network", info.get("ms"), "ms")
    assert (info.get("ms") or 0) < BUDGET_MS, info
    assert not info.get("loading"), info
    shot(page, shot_name)
    return info


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        check_snap(page, "#/jable/hot", (2, 50, 1000, "last"), "_ui_jump_hot.png")
        check_snap(page, "#/jable/type", (1, 50, "last"), "_ui_jump_type.png")
        check_tag(page, "#/jable/tag/black-pantyhose", "_ui_jump_tag.png")
        browser.close()
    print("UI jump-any ok")


if __name__ == "__main__":
    main()
