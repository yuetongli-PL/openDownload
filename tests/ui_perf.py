# -*- coding: utf-8 -*-
import json
import time
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

from ui_support import BASE, ensure_out, shot


def _kb(n: int) -> float:
    return round(n / 1024, 2)


def fetch_bytes(url: str) -> int:
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return len(resp.read())


def main() -> None:
    stamp = str(int(time.time() * 1000))
    home = f"{BASE}/?od={stamp}#/"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        cdp = context.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})

        reqs: list[str] = []
        page.on("request", lambda r: reqs.append(r.url))

        page.goto(home, wait_until="domcontentloaded")
        page.locator(".view-home, main#app").first.wait_for(timeout=8000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            page.wait_for_timeout(800)

        metrics = page.evaluate(
            """() => {
              const nav = performance.getEntriesByType('navigation')[0];
              const fcp = performance.getEntriesByName('first-contentful-paint')[0];
              const resources = performance.getEntriesByType('resource');
              const here = location.host;
              const external = resources.filter((r) => {
                try { return new URL(r.name).host && new URL(r.name).host !== here; }
                catch { return false; }
              }).map((r) => r.name);
              const js = resources.filter((r) => /\\.m?js(\\?|$)/i.test(r.name) && !/hls\\.min\\.js/i.test(r.name));
              const css = resources.filter((r) => /\\.css(\\?|$)/i.test(r.name));
              const firstJs = [...document.querySelectorAll('link[rel="modulepreload"], script[type="module"]')]
                .map((el) => el.href || el.src)
                .filter(Boolean);
              return {
                dcl_ms: nav ? Math.round(nav.domContentLoadedEventEnd) : null,
                fcp_ms: fcp ? Math.round(fcp.startTime) : null,
                resource_count: resources.length,
                first_js_urls: firstJs,
                js_urls: js.map((r) => r.name),
                css_urls: css.map((r) => r.name),
                external,
                transfer_js: js.reduce((s, r) => s + (r.decodedBodySize || r.encodedBodySize || 0), 0),
                transfer_css: css.reduce((s, r) => s + (r.decodedBodySize || r.encodedBodySize || 0), 0),
              };
            }"""
        )

        js_urls = []
        for url in list(metrics["first_js_urls"]) + list(metrics["js_urls"]):
            if url and url not in js_urls and "hls.min.js" not in url:
                js_urls.append(url)
        css_urls = []
        for url in metrics["css_urls"]:
            if url and url not in css_urls:
                css_urls.append(url)

        js_bytes = 0
        css_bytes = 0
        for url in js_urls:
            try:
                js_bytes += fetch_bytes(url)
            except Exception as exc:
                print("js fetch fail", url, exc)
        for url in css_urls:
            try:
                css_bytes += fetch_bytes(url)
            except Exception as exc:
                print("css fetch fail", url, exc)

        page.wait_for_timeout(1500)
        idle_from = len(reqs)
        page.wait_for_timeout(30000)
        idle_new = [u for u in reqs[idle_from:] if "devtools" not in u]
        idle_new_n = len(idle_new)

        page.evaluate("() => { location.hash = '#/jable/hot'; }")
        page.locator("#jb-list-grid .av-card").first.wait_for(timeout=30000)
        page.wait_for_function(
            "document.querySelectorAll('#jb-list-grid .av-card').length >= 12",
            timeout=30000,
        )
        page.wait_for_timeout(400)
        page.evaluate("() => { location.hash = '#/'; }")
        page.locator(".view-home").wait_for(state="visible", timeout=8000)
        t0 = time.perf_counter()
        page.evaluate("() => { location.hash = '#/jable/hot'; }")
        page.wait_for_function(
            "location.hash.includes('/jable/hot') && document.querySelectorAll('#jb-list-grid .av-card').length >= 12",
            timeout=8000,
        )
        hot_ms = round((time.perf_counter() - t0) * 1000)

        out = {
            "dcl_ms": metrics["dcl_ms"],
            "fcp_ms": metrics["fcp_ms"],
            "resource_count": metrics["resource_count"],
            "first_js_count": len(set(urllib.parse.urldefrag(u)[0] for u in metrics["first_js_urls"])),
            "js_decoded_kb": _kb(js_bytes),
            "css_decoded_kb": _kb(css_bytes),
            "external_requests": len(metrics["external"]),
            "external_urls": metrics["external"],
            "idle_30s_new_requests": idle_new_n,
            "idle_30s_urls": idle_new,
            "jable_hot_cached_12cards_ms": hot_ms,
            "first_js_urls": metrics["first_js_urls"],
        }
        text = json.dumps(out, ensure_ascii=False, indent=2)
        ensure_out()
        (ensure_out() / "ui_perf.json").write_text(text, encoding="utf-8")
        print(text)
        shot(page, "_ui_perf_home.png")
        browser.close()

    assert out["dcl_ms"] is not None and out["dcl_ms"] < 300, out
    assert out["fcp_ms"] is not None and out["fcp_ms"] < 600, out
    assert out["external_requests"] == 0, out
    assert out["idle_30s_new_requests"] == 0, out
    assert out["js_decoded_kb"] <= 160, out
    print("ui perf ok")


if __name__ == "__main__":
    main()
