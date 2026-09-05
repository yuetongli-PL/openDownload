# -*- coding: utf-8 -*-
"""Jable 列表翻页：只读本地索引 / 磁盘，不阻塞站点 HTTP。"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .jable_index import (
    _load_works,
    display_len,
    items_for_ui_page,
    order_len,
    order_total_hint,
)

PAGE_SIZE = 12
_SITE_PAGE_SIZE = 24
_PREFETCH_WORKERS = 10
_CARD_KEYS = ("id", "title", "url", "cover", "preview", "duration", "views", "likes", "date", "actors")


def _lists():
    # Avoid import-time cycles with jable_lists; never call _ui_page_items (it may HTTP).
    from . import jable_lists as lists

    return lists


def _page_size(lists: Any | None = None) -> int:
    mod = lists or _lists()
    try:
        n = int(getattr(mod, "PAGE_SIZE", PAGE_SIZE) or PAGE_SIZE)
    except (TypeError, ValueError):
        n = PAGE_SIZE
    return n if n > 0 else PAGE_SIZE


def _site_size(lists: Any | None = None) -> int:
    mod = lists or _lists()
    try:
        n = int(getattr(mod, "SITE_PAGE_SIZE", _SITE_PAGE_SIZE) or _SITE_PAGE_SIZE)
    except (TypeError, ValueError):
        n = _SITE_PAGE_SIZE
    return n if n > 0 else _SITE_PAGE_SIZE


def _as_int(value: Any, default: int = 1) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_card(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    code = str(row.get("id") or row.get("code") or "").strip().lower()
    if not code:
        return None
    title = row.get("title") or code
    actors = row.get("actors") or []
    if not actors:
        try:
            from jable_hot import actors_from_title

            actors = actors_from_title(str(title or ""))
        except Exception:
            actors = []
    return {
        "id": code,
        "title": title,
        "url": row.get("url") or f"https://jable.tv/videos/{code}/",
        "cover": row.get("cover") or "",
        "preview": row.get("preview") or row.get("preview_jpg") or "",
        "duration": row.get("duration") or "",
        "views": row.get("views") or 0,
        "likes": row.get("likes") or 0,
        "date": row.get("date") or "",
        "actors": actors,
    }


def _pack_cards(rows: list[Any], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        card = _as_card(row)
        if not card:
            continue
        out.append({key: card[key] for key in _CARD_KEYS})
        if len(out) >= limit:
            break
    return out


def _site_page_of(ui_page: int, page_size: int, site_size: int) -> int:
    return (max(1, ui_page) - 1) * page_size // site_size + 1


def _disk_ui_items(spec: dict[str, str], page: int, page_size: int, site_size: int) -> list[dict[str, Any]]:
    lists = _lists()
    offset = (max(1, page) - 1) * page_size
    site_page = offset // site_size + 1
    start = offset % site_size
    path = lists._pages_dir(spec) / f"{int(site_page)}.json"
    if not path.is_file():
        return []
    rows = lists._read_one_site_page(spec, site_page)
    if not isinstance(rows, list) or not rows:
        return []
    return _pack_cards(rows[start : start + page_size], page_size)


def page_feed(
    *,
    kind: str = "latest",
    slug: str = "",
    term: str = "",
    year: str = "",
    month: str = "",
    page: int = 1,
) -> dict:
    """Return one UI page from local data only. Never block on HTTP."""
    lists = _lists()
    spec = lists._resolve_list(kind, slug, term, year, month)
    try:
        lists._ensure_model_title(spec)
    except Exception:
        pass
    page_size = _page_size(lists)
    site_size = _site_size(lists)
    page = max(1, _as_int(page, 1))

    try:
        _load_works()
    except Exception:
        pass

    order_n = 0
    known = 0
    try:
        if (spec.get("kind") or "") == "model":
            from .jable_index import seed_order

            seed_order(spec)
        order_total_hint(spec)
        order_n = int(order_len(spec) or 0)
        known = int(display_len(spec) or 0)
    except Exception:
        order_n = 0
        known = 0

    meta = lists._LIST_META.get(lists._mem_key(spec)) or {}
    total = int(lists._declared_total(spec, meta, known) or 0)
    page_count = max(1, (max(total, 0) + page_size - 1) // page_size)
    if page > page_count:
        page = page_count
    start = (page - 1) * page_size

    raw: list[Any] = []
    try:
        raw = items_for_ui_page(spec, page, page_size)
    except Exception:
        raw = []
    items = _pack_cards(raw, page_size)

    kind_name = spec.get("kind") or ""
    if kind_name == "model":
        try:
            items = lists._stamp_model_items(spec, items)
        except Exception:
            pass
    paged = kind_name in getattr(lists, "_PAGED_KINDS", {"tag", "cat", "model"})
    if paged and (start >= order_n or len(items) < page_size):
        disk = _disk_ui_items(spec, page, page_size, site_size)
        if disk:
            items = disk

    if kind_name in {"tag", "cat"}:
        try:
            from .jable_tag_cache import prioritize_spec

            prioritize_spec(spec)
        except Exception:
            pass
    if kind_name == "model":
        try:
            lists._ensure_model_pages(spec)
        except Exception:
            pass

    pending = (not items) and (start < total or (kind_name == "model" and total == 0))
    out = {
        "title": lists._spec_title(spec) if hasattr(lists, "_spec_title") else (spec.get("title") or ""),
        "kind": kind_name,
        "slug": spec.get("slug") or "",
        "term": spec.get("term") or "",
        "year": spec.get("year") or "",
        "month": spec.get("month") or "",
        "items": items[:page_size],
        "page": page,
        "page_size": page_size,
        "total": total,
        "page_count": page_count,
        "has_more": page < page_count,
        "cached": bool(items) or not pending,
        "pending": pending,
    }

    short_order = order_n < total
    if kind_name != "model" and (pending or (paged and short_order)):
        threading.Thread(target=prefetch_around, args=(spec, page), daemon=True).start()
    return out


def prefetch_around(spec: dict, page: int, radius: int = 5) -> None:
    """Fire-and-forget: up to 10 worker threads fetch nearby SITE pages (24 items each) onto disk."""
    try:
        lists = _lists()
        page_size = _page_size(lists)
        site_size = _site_size(lists)
        ui_page = max(1, _as_int(page, 1))
        site_page = _site_page_of(ui_page, page_size, site_size)
        span = max(0, _as_int(radius, 5))
        pages = [n for n in range(site_page - span, site_page + span + 1) if n >= 1]
        if not pages:
            return

        def one(n: int) -> None:
            try:
                lists._site_page_items(spec, n)
            except Exception:
                pass

        workers = min(_PREFETCH_WORKERS, len(pages))
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            for fut in (pool.submit(one, n) for n in pages):
                try:
                    fut.result()
                except Exception:
                    pass
    except Exception:
        return
