# -*- coding: utf-8 -*-
"""把全部分类 / 标签的站点页抓进本地，供任意页 3ms 切片。"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from typing import Any

from .paths import library_dir

SITE_PAGE = 24
PAGE_WORKERS = 2
_LOCK = threading.Lock()
_STARTED = False
_ORDERS_PACK: dict[str, Any] | None = None
_ORDERS_PACK_AT = 0.0
_PAGE_MAPS: dict[str, dict[int, list[str]]] = {}
_PRIORITY: list[str] = []
_STATE: dict[str, Any] = {
    "running": False,
    "done": False,
    "pages_ok": 0,
    "pages_miss": 0,
    "specs": {},
    "updated_at": "",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state_path():
    path = library_dir() / "jable" / "_index" / "tag_cache.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _save_state() -> None:
    _STATE["updated_at"] = _now()
    try:
        _state_path().write_text(json.dumps(_STATE, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def cache_status() -> dict[str, Any]:
    out = dict(_STATE)
    try:
        from .jable_index import works_count

        out["works"] = works_count()
    except Exception:
        out["works"] = 0
    return out


def _all_specs() -> list[dict[str, str]]:
    from jable_pick import GROUPS

    from .jable_lists import DEFAULT_CATEGORIES, _resolve_list

    specs: list[dict[str, str]] = []
    for slug, _name in DEFAULT_CATEGORIES:
        specs.append(_resolve_list("cat", slug, ""))
    for tags in GROUPS.values():
        for _name, slug in tags:
            specs.append(_resolve_list("tag", slug, ""))
    return specs


def _spec_key(spec: dict[str, str]) -> str:
    return f"{spec.get('kind')}|{spec.get('slug') or spec.get('path')}"


def _row_codes(rows: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for row in rows or []:
        code = str(row.get("id") or row.get("code") or "").strip().lower()
        if code:
            out.append(code)
    return out


def _page_files(spec: dict[str, str]) -> dict[int, Any]:
    from .jable_lists import _pages_dir

    folder = _pages_dir(spec)
    found: dict[int, Any] = {}
    if not folder.is_dir():
        return found
    for path in folder.glob("*.json"):
        try:
            num = int(path.stem)
        except ValueError:
            continue
        try:
            if path.stat().st_size < 20:
                continue
        except OSError:
            continue
        found[num] = path
    return found


def _spec_complete(spec: dict[str, str]) -> bool:
    from .jable_index import order_len, order_total_hint

    hint = int(order_total_hint(spec) or 0)
    n = order_len(spec)
    if 0 < hint < SITE_PAGE and n >= hint:
        return True
    if hint <= SITE_PAGE:
        return False
    return n >= hint or (hint - n) <= SITE_PAGE


def refresh_spec_pages(spec: dict[str, str]) -> dict[int, list[str]]:
    from .jable_index import ingest_works
    from .jable_lists import _read_one_site_page

    pages: dict[int, list[str]] = {}
    for num in _page_files(spec):
        rows = _read_one_site_page(spec, num) or []
        codes = _row_codes(rows)
        if not codes:
            continue
        pages[num] = codes
        try:
            ingest_works(rows)
        except Exception:
            pass
    _PAGE_MAPS[_spec_key(spec)] = pages
    return pages


def spec_page_codes(spec: dict[str, str]) -> dict[str, list[str]]:
    key = _spec_key(spec)
    hit = _PAGE_MAPS.get(key)
    if hit is None:
        hit = refresh_spec_pages(spec)
    return {str(num): list(codes) for num, codes in hit.items()}


def prioritize_spec(spec: dict[str, str]) -> None:
    key = _spec_key(spec)
    with _LOCK:
        if key in _PRIORITY:
            _PRIORITY.remove(key)
        _PRIORITY.insert(0, key)


def _rebuild_order(spec: dict[str, str], hint: int) -> int:
    from .jable_index import ingest_works, save_order
    from .jable_lists import _read_one_site_page

    have = _page_files(spec)
    if not have:
        return 0
    codes: list[str] = []
    page = 1
    while page in have:
        rows = _read_one_site_page(spec, page) or []
        if not rows:
            break
        ingest_works(rows)
        codes.extend(_row_codes(rows))
        page += 1
    if codes:
        save_order(spec, codes, total_hint=max(hint, len(codes)))
    return len(codes)


def _ensure_hint(spec: dict[str, str]) -> int:
    from .jable_index import _pull_front, order_len, order_total_hint, prepend_order

    hint = int(order_total_hint(spec) or 0)
    n = order_len(spec)
    if hint > SITE_PAGE:
        return hint
    try:
        head, total = _pull_front(spec, 1)
    except Exception:
        return hint
    if head:
        prepend_order(spec, head, total or hint)
        from .jable_lists import _save_site_page

        _save_site_page(spec, 1, head[:SITE_PAGE])
        refresh_spec_pages(spec)
    return max(hint, n, int(total or 0), len(head or []))


def _fetch_pages(spec: dict[str, str], pages: list[int]) -> dict[int, list[dict[str, Any]]]:
    from jable_http import is_blocked, wait_rate_limit

    from .jable_index import _fetch_site_batch

    if not pages:
        return {}
    wait_rate_limit()
    if is_blocked():
        return {}
    try:
        return _fetch_site_batch(spec, pages, workers=PAGE_WORKERS) or {}
    except Exception:
        return {}


def index_all_disk() -> None:
    global _ORDERS_PACK
    from .jable_index import load_order, order_total_hint

    for spec in _all_specs():
        try:
            load_order(spec)
        except Exception:
            pass
        try:
            refresh_spec_pages(spec)
            _rebuild_order(spec, int(order_total_hint(spec) or 0))
        except Exception:
            pass
    with _LOCK:
        _ORDERS_PACK = None


def _cache_one(spec: dict[str, str]) -> dict[str, Any]:
    global _ORDERS_PACK
    from .jable_index import ingest_works, order_len
    from .jable_lists import _save_site_page

    hint = _ensure_hint(spec)
    total_pages = max(1, (max(hint, 1) + SITE_PAGE - 1) // SITE_PAGE)
    have = set(_page_files(spec))
    missing = [p for p in range(1, total_pages + 1) if p not in have]
    info = {
        "kind": spec.get("kind") or "",
        "slug": spec.get("slug") or "",
        "title": spec.get("title") or "",
        "hint": hint,
        "pages": total_pages,
        "have": len(have),
        "missing": len(missing),
        "items": order_len(spec),
    }
    key = _spec_key(spec)
    with _LOCK:
        _STATE["focus"] = key
        _STATE["specs"][key] = info
    if _spec_complete(spec) and not missing:
        info["missing"] = 0
        info["have"] = len(have) or total_pages
        return info
    if not missing:
        info["items"] = _rebuild_order(spec, hint)
        info["have"] = total_pages
        info["missing"] = 0
        refresh_spec_pages(spec)
        return info

    empty_rounds = 0
    while missing:
        batch = missing[:PAGE_WORKERS]
        got = _fetch_pages(spec, batch)
        saved = 0
        for page in batch:
            chunk = got.get(page) or []
            if not chunk:
                with _LOCK:
                    _STATE["pages_miss"] = int(_STATE.get("pages_miss") or 0) + 1
                continue
            ingest_works(chunk)
            _save_site_page(spec, page, chunk)
            saved += 1
            with _LOCK:
                _STATE["pages_ok"] = int(_STATE.get("pages_ok") or 0) + 1
        if saved:
            empty_rounds = 0
            refresh_spec_pages(spec)
            info["items"] = _rebuild_order(spec, hint)
            with _LOCK:
                _ORDERS_PACK = None
        else:
            empty_rounds += 1
            try:
                from jable_http import is_blocked, wait_rate_limit

                if is_blocked():
                    wait_rate_limit()
                    empty_rounds = min(empty_rounds, 2)
                    continue
            except Exception:
                pass
            time.sleep(min(45.0, 6.0 * empty_rounds))
            if empty_rounds >= 5:
                break
            continue
        have = set(_page_files(spec))
        missing = [p for p in range(1, total_pages + 1) if p not in have]
        info["have"] = len(have)
        info["missing"] = len(missing)
        with _LOCK:
            _STATE["specs"][key] = dict(info)
            _save_state()
        time.sleep(0.35)
    info["items"] = _rebuild_order(spec, hint)
    info["have"] = len(_page_files(spec))
    info["missing"] = max(0, total_pages - int(info["have"]))
    refresh_spec_pages(spec)
    with _LOCK:
        _STATE["specs"][key] = dict(info)
        _save_state()
    return info


def _next_spec(specs: list[dict[str, str]]) -> dict[str, str] | None:
    from .jable_index import order_total_hint

    by_key = {_spec_key(spec): spec for spec in specs}
    with _LOCK:
        pending = list(_PRIORITY)
    for key in pending:
        spec = by_key.get(key)
        if spec and not _spec_complete(spec):
            return spec
    leftover = [spec for spec in specs if not _spec_complete(spec)]
    leftover.sort(key=lambda spec: int(order_total_hint(spec) or 0) or 5000)
    return leftover[0] if leftover else None


def run_full_cache() -> dict[str, Any]:
    global _ORDERS_PACK
    with _LOCK:
        if _STATE.get("running"):
            return dict(_STATE)
        _STATE["running"] = True
        _STATE["done"] = False
        _STATE["started_at"] = _now()
        _save_state()
    try:
        index_all_disk()
        specs = _all_specs()
        while True:
            try:
                from jable_http import wait_rate_limit

                wait_rate_limit()
            except Exception:
                pass
            nxt = _next_spec(specs)
            if not nxt:
                with _LOCK:
                    _ORDERS_PACK = None
                    _STATE["done"] = True
                    _STATE["running"] = False
                    _STATE["complete"] = len(specs)
                    _STATE["lists"] = len(specs)
                    _STATE["focus"] = ""
                    _save_state()
                return dict(_STATE)
            _cache_one(nxt)
            with _LOCK:
                _ORDERS_PACK = None
                _STATE["complete"] = sum(1 for spec in specs if _spec_complete(spec))
                _STATE["lists"] = len(specs)
                _save_state()
    except Exception as exc:
        with _LOCK:
            _STATE["running"] = False
            _STATE["error"] = str(exc)[:240]
            _save_state()
    return dict(_STATE)


def start_full_cache() -> None:
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    path = _state_path()
    if path.is_file():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(prev, dict):
                _STATE.update(prev)
                _STATE["running"] = False
                _STATE["done"] = False
        except (OSError, json.JSONDecodeError):
            pass
    def boot() -> None:
        time.sleep(45.0)
        run_full_cache()

    threading.Thread(target=boot, daemon=True, name="jable-tag-cache").start()


def orders_payload() -> dict[str, Any]:
    global _ORDERS_PACK, _ORDERS_PACK_AT
    now = time.monotonic()
    with _LOCK:
        running = bool(_STATE.get("running"))
        pack = _ORDERS_PACK
        packed_at = _ORDERS_PACK_AT
    if pack is not None and (not running) and now - packed_at < 8:
        return pack
    if pack is not None and running and now - packed_at < 4:
        return pack

    from .jable_index import load_order, order_total_hint

    tags: dict[str, Any] = {}
    cats: dict[str, Any] = {}
    for spec in _all_specs():
        codes = [c for c in load_order(spec) if c]
        hint = int(order_total_hint(spec) or 0)
        pages = spec_page_codes(spec)
        filled = sum(len(v) for v in pages.values())
        row = {
            "codes": codes,
            "total": max(hint, len(codes), filled),
            "count": max(len(codes), filled),
        }
        slug = spec.get("slug") or ""
        if spec.get("kind") == "cat":
            cats[slug] = row
        else:
            tags[slug] = row
    complete = 0
    for row in list(tags.values()) + list(cats.values()):
        total = int(row.get("total") or 0)
        count = int(row.get("count") or 0)
        if total and (count >= total or (total - count) <= SITE_PAGE):
            complete += 1
    payload = {
        "tags": tags,
        "cats": cats,
        "complete": complete,
        "lists": len(tags) + len(cats),
        "cache": cache_status(),
    }
    with _LOCK:
        _ORDERS_PACK = payload
        _ORDERS_PACK_AT = time.monotonic()
    return payload
