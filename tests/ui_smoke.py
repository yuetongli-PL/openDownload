# -*- coding: utf-8 -*-
"""Traverse routes × viewports: overflow, main content, console, screenshots."""
from __future__ import annotations

import time

from playwright.sync_api import sync_playwright

from ui_support import BASE, attach_errors, legacy_hashes, no_hscroll, shot, wait_main_content

VIEWPORTS = [
    ("1440x900", 1440, 900),
    ("1280x720", 1280, 720),
    ("390x844", 390, 844),
]

ROUTES = [
    "#/",
    "#/jable",
    "#/jable/hot",
    "#/jable/week",
    "#/jable/month",
    "#/jable/all",
    "#/jable/latest",
    "#/jable/latest/2025",
    "#/jable/type",
    "#/jable/cat/chinese-subtitle",
    "#/jable/tag/black-pantyhose",
    "#/jable/model/e82b22cd3275fd0e569147d82fa1999d",
    "#/jable/v/vdd-208",
    "#/youtube",
    "#/youtube/videos",
    "#/youtube/shorts",
    "#/douyin",
    "#/douyin/feed",
    "#/douyin/follow",
    "#/library",
    "#/tasks",
    "#/settings",
]


def view_name(hash_path: str) -> str:
    body = hash_path[1:].split("?")[0].strip("/")
    head = (body.split("/") or [""])[0]
    if head in {"", "auto"}:
        return "home"
    if head in {"setup", "settings"}:
        return "settings"
    if head in {"youtube", "douyin"}:
        return "source"
    return head or "home"


def slug(hash_path: str) -> str:
    return hash_path.replace("#/", "").replace("/", "_").replace("?", "_") or "home"


def goto_hash(page, hash_path: str):
    page.evaluate("(h) => { location.hash = h; }", hash_path)


def check_route(page, hash_path: str, vp_name: str, seen_views: set[str]) -> list[str]:
    fails: list[str] = []
    goto_hash(page, hash_path)
    name = view_name(hash_path)
    budget = 2000 if name not in seen_views else 150
    try:
        elapsed = wait_main_content(page, timeout_ms=3000)
    except Exception as exc:
        fails.append(f"{hash_path} @{vp_name} main 无内容: {exc}")
        elapsed = -1
    else:
        if name in seen_views and elapsed > 150:
            fails.append(f"{hash_path} @{vp_name} main {elapsed}ms > 150ms")
        elif name not in seen_views and elapsed > 2000:
            fails.append(f"{hash_path} @{vp_name} 首次装载 {elapsed}ms > 2000ms")
        print(f"  {hash_path:40} {vp_name:10} main {elapsed}ms view={name}")
        seen_views.add(name)
    page.wait_for_timeout(80)
    if not no_hscroll(page):
        sw, iw = page.evaluate(
            "() => [document.documentElement.scrollWidth, window.innerWidth]"
        )
        fails.append(f"{hash_path} @{vp_name} 水平溢出 scrollWidth={sw} innerWidth={iw}")
    shot(page, f"smoke_{vp_name}_{slug(hash_path)}.png")
    return fails


def main() -> None:
    routes = list(ROUTES)
    for hash_path, _kind in legacy_hashes():
        if hash_path not in routes:
            routes.append(hash_path)
    print("legacy hashes", [h for h, _ in legacy_hashes()])
    fails: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = attach_errors(page)
        page.goto(BASE + "/#/?od_smoke=" + str(int(time.time())), wait_until="domcontentloaded")
        wait_main_content(page, timeout_ms=5000)

        for vp_name, w, h in VIEWPORTS:
            page.set_viewport_size({"width": w, "height": h})
            seen: set[str] = set()
            for hash_path in routes:
                fails.extend(check_route(page, hash_path, vp_name, seen))

        page.set_viewport_size({"width": 1440, "height": 900})
        goto_hash(page, "#/jable")
        wait_main_content(page)
        goto_hash(page, "#/library")
        wait_main_content(page)
        page.go_back()
        page.wait_for_function("location.hash.includes('jable')", timeout=3000)
        page.go_forward()
        page.wait_for_function("location.hash.includes('library')", timeout=3000)
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("location.hash.includes('library')", timeout=5000)
        wait_main_content(page)
        print("history back/forward/reload ok")
        browser.close()

    if errors:
        fails.extend(errors)
    if fails:
        print("SMOKE FAILS")
        for row in fails:
            print(" -", row)
        raise SystemExit(1)
    print("ui smoke ok", len(routes), "routes ×", len(VIEWPORTS), "viewports")


if __name__ == "__main__":
    main()
