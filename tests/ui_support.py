# -*- coding: utf-8 -*-
"""Shared helpers for Playwright UI scripts."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

BASE = os.environ.get("OD_BASE", "http://127.0.0.1:8765").rstrip("/")
ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "_out"
ROUTER_JS = ROOT / "web" / "js" / "core" / "router.js"
ROUTE_JS = ROOT / "web" / "js" / "jable" / "route.js"
WORKS_JSON = ROOT / "library" / "jable" / "_index" / "works.json"


def ensure_out() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    return OUT


def shot(page, name: str, *, full_page: bool = False):
    ensure_out()
    dest = OUT / name
    page.screenshot(path=str(dest), full_page=full_page)
    return dest


def attach_errors(page) -> list[str]:
    bag: list[str] = []

    def on_pageerror(err):
        bag.append(f"pageerror: {err}")

    def on_console(msg):
        if msg.type == "error":
            bag.append(f"console.error: {msg.text}")

    page.on("pageerror", on_pageerror)
    page.on("console", on_console)
    return bag


def pick_jable_code() -> str:
    data = json.loads(WORKS_JSON.read_text(encoding="utf-8"))
    items = data.get("items") or []
    for row in items:
        if not isinstance(row, dict):
            continue
        code = str(row.get("id") or "").strip()
        if code and "-" in code and len(code) < 24:
            return code
    raise RuntimeError("works.json 没有可用番号")


def legacy_hashes() -> list[tuple[str, str]]:
    """Old hash aliases declared in router.js / jable/route.js."""
    cases: list[tuple[str, str]] = []
    router = ROUTER_JS.read_text(encoding="utf-8")
    if re.search(r'segments\[0\] === "auto"', router):
        cases.append(("#/auto", "home"))
    if re.search(r'segments\[0\] === "setup"', router):
        cases.append(("#/setup", "settings"))
    jable = ROUTE_JS.read_text(encoding="utf-8")
    if re.search(r'mode === "pick"', jable):
        cases.append(("#/jable/pick", "jable"))
    if re.search(r'mode === "actor"', jable):
        cases.append(("#/jable/actor/e82b22cd3275fd0e569147d82fa1999d", "jable"))
    return cases


def wait_main_content(page, timeout_ms: int = 3000) -> float:
    t0 = page.evaluate("() => performance.now()")
    page.wait_for_function(
        """() => {
          const main = document.querySelector('main#app');
          if (!main) return false;
          const text = (main.textContent || '').trim();
          return main.childElementCount > 0 && text.length > 0;
        }""",
        timeout=timeout_ms,
    )
    return page.evaluate("(t0) => Math.round(performance.now() - t0)", t0)


def no_hscroll(page) -> bool:
    return bool(
        page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
    )
