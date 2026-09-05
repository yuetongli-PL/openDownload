# -*- coding: utf-8 -*-
import json
import urllib.request

from playwright.sync_api import sync_playwright

from ui_support import BASE, shot


def health():
    with urllib.request.urlopen(BASE + "/api/health", timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    origin = health()
    old_workers = int((origin.get("settings") or {}).get("workers") or 64)
    target = 63 if old_workers == 64 else 64
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(BASE + "/#/settings", wait_until="domcontentloaded")
        page.locator(".view-settings").wait_for(state="visible", timeout=10000)

        pref = page.evaluate("() => localStorage.getItem('od-theme') || 'system'")
        before = page.evaluate("() => document.documentElement.dataset.theme")
        page.locator("#btn-theme").click()
        page.wait_for_function(
            f"() => document.documentElement.dataset.theme && document.documentElement.dataset.theme !== {before!r}",
            timeout=2000,
        )
        after = page.evaluate("() => document.documentElement.dataset.theme")
        assert after in {"light", "dark"} and after != before, (before, after)
        page.reload(wait_until="domcontentloaded")
        page.locator(".view-settings").wait_for(state="visible", timeout=10000)
        kept = page.evaluate("() => document.documentElement.dataset.theme")
        assert kept == after, (kept, after)
        page.locator("#btn-theme").click()
        page.wait_for_function(
            f"() => document.documentElement.dataset.theme === {before!r}",
            timeout=2000,
        )
        shot(page, "_ui_settings_theme.png")

        page.locator("#set-workers").fill(str(target))
        page.locator("[data-save-set]").click()
        page.locator("#toast-root .toast").wait_for(timeout=8000)
        toast = page.locator("#toast-root .toast").inner_text()
        assert "保存" in toast, toast
        page.wait_for_timeout(200)
        now = health()
        got = int((now.get("settings") or {}).get("workers") or 0)
        assert got == target, (got, target, now.get("settings"))
        shot(page, "_ui_settings_save.png")

        page.locator("#set-workers").fill(str(old_workers))
        page.locator("[data-save-set]").click()
        page.locator("#toast-root .toast").wait_for(timeout=8000)
        restored = int((health().get("settings") or {}).get("workers") or 0)
        assert restored == old_workers, restored
        page.evaluate(
            """(pref) => {
              localStorage.setItem('od-theme', pref);
            }""",
            pref,
        )
        browser.close()
    print("ui settings ok", "theme", before, "→", after, "workers", old_workers, "→", target, "→", old_workers)


if __name__ == "__main__":
    main()
