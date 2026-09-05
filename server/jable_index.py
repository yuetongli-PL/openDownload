# -*- coding: utf-8 -*-
"""Jable 元数据 / 索引 / 封面：启动时补一轮，之后每 24 小时追加新片。"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from jable_hot import actors_from_title

from .paths import library_dir

DAILY_SEC = 24 * 3600
LATEST_PAGES = 4
HOT_PAGES = 2
COVER_WORKERS = 8
BACKFILL_WORKERS = 2
BACKFILL_BATCH = 2
BACKFILL_KINDS = ("hot", "latest", "all", "week", "month")

_WORKS: dict[str, dict[str, Any]] = {}
_WORKS_LOCK = threading.Lock()
_WORKS_LOADED = False
_WORKS_GEN = 0
_WORKS_COMPACT: list[list[Any]] | None = None
_WORKS_COMPACT_N: Any = -1
_ORDERS: dict[str, list[str]] = {}
_ORDER_HINTS: dict[str, int] = {}
_ORDER_LOCK = threading.Lock()
_OVERFLOW: dict[str, tuple[int, int, list[str]]] = {}
_RUN_LOCK = threading.Lock()
_BACKFILL_LOCK = threading.Lock()
_STATE: dict[str, Any] = {}
_STARTED = False
_COVER_POOL: ThreadPoolExecutor | None = None
_CATALOG_KINDS = {"hot", "latest", "week", "month", "all", "type"}


def _index_dir() -> Path:
    path = library_dir() / "jable" / "_index"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cover_dir() -> Path:
    path = library_dir() / "jable" / "_covers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cover_cache_path(url: str) -> Path:
    digest = hashlib.sha1((url or "").encode("utf-8", errors="replace")).hexdigest()
    return cover_dir() / f"{digest}.jpg"


def _works_path() -> Path:
    return _index_dir() / "works.json"


def _state_path() -> Path:
    return _index_dir() / "state.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _save_state() -> None:
    try:
        _state_path().write_text(json.dumps(_STATE, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _load_state() -> None:
    global _STATE
    path = _state_path()
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _STATE.update(data)
    except (OSError, json.JSONDecodeError):
        pass


def _touch_works() -> None:
    global _WORKS_GEN, _WORKS_COMPACT, _WORKS_COMPACT_N
    _WORKS_GEN += 1
    _WORKS_COMPACT = None
    _WORKS_COMPACT_N = -1


def _date_rank(raw: str) -> int:
    text = str(raw or "").strip()
    if len(text) >= 10:
        return 3
    if len(text) >= 7:
        return 2
    if len(text) >= 4:
        return 1
    return 0


def _date_from_search_label(label: str) -> str:
    text = unquote(str(label or "")).strip()
    month = re.match(r"^(20\d{2})-(\d{1,2})$", text)
    if month:
        return f"{month.group(1)}-{int(month.group(2)):02d}"
    year = re.match(r"^(20\d{2})$", text)
    if year:
        return year.group(1)
    return ""


def _norm_actors(raw: Any) -> list[dict[str, str]]:
    rows: list[Any]
    if isinstance(raw, str):
        rows = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            if "|" in part:
                name, slug = part.split("|", 1)
                rows.append({"name": name.strip(), "slug": slug.strip()})
            else:
                rows.append({"name": part, "slug": ""})
    elif isinstance(raw, list):
        rows = raw
    else:
        rows = []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if isinstance(row, str):
            name, slug = row.strip(), ""
        elif isinstance(row, dict):
            name = str(row.get("name") or row.get("title") or "").strip()
            slug = str(row.get("slug") or "").strip()
        else:
            continue
        key = (slug or name).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"name": name or slug, "slug": slug})
    return out


def _normalize_work(row: dict[str, Any]) -> dict[str, Any] | None:
    code = str(row.get("id") or row.get("code") or "").strip().lower()
    if not code:
        return None
    date = str(row.get("date") or "").strip()
    if len(date) >= 10 and date[4] in "-/.":
        date = date[:10].replace(".", "-").replace("/", "-")
    else:
        date = date if date else ""
    title = row.get("title") or code
    actors = _norm_actors(row.get("actors"))
    if not actors:
        actors = actors_from_title(str(title or ""))
    return {
        "id": code,
        "title": title,
        "url": row.get("url") or f"https://jable.tv/videos/{code}/",
        "cover": row.get("cover") or "",
        "preview": row.get("preview") or row.get("preview_jpg") or "",
        "duration": row.get("duration") or "",
        "views": row.get("views") or 0,
        "likes": row.get("likes") or 0,
        "date": date,
        "actors": actors,
    }


def _cover_pool() -> ThreadPoolExecutor:
    global _COVER_POOL
    if _COVER_POOL is None:
        _COVER_POOL = ThreadPoolExecutor(max_workers=COVER_WORKERS, thread_name_prefix="jable-cover")
    return _COVER_POOL


def enqueue_covers(rows: list[dict[str, Any]]) -> None:
    pool = _cover_pool()
    for row in rows or []:
        url = str((row or {}).get("cover") or "").strip()
        if url:
            pool.submit(ensure_cover, url)


def works_meta(codes: list[str], fetch_missing: bool = False) -> list[dict[str, Any]]:
    _load_works()
    wanted = [str(c or "").strip().lower() for c in codes if str(c or "").strip()][:12]
    found: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    with _WORKS_LOCK:
        for code in wanted:
            row = _WORKS.get(code)
            if row:
                found[code] = dict(row)
            if not row or not row.get("date"):
                missing.append(code)
    if fetch_missing and missing:
        from .jable_inspect import inspect_info

        def one(code: str) -> dict[str, Any] | None:
            try:
                return inspect_info(code)
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=min(4, len(missing))) as pool:
            futs = [pool.submit(one, code) for code in missing[:8]]
            done, _pending = wait(futs, timeout=8)
            for fut in done:
                try:
                    info = fut.result()
                except Exception:
                    info = None
                if not info:
                    continue
                code = str(info.get("id") or "").strip().lower()
                if not code:
                    continue
                with _WORKS_LOCK:
                    row = _WORKS.get(code)
                    if row:
                        found[code] = dict(row)
    return [found[c] for c in wanted if c in found]


def works_for_codes(codes: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with _WORKS_LOCK:
        for code in codes:
            item = _WORKS.get(code)
            if item:
                out.append(dict(item))
            elif code:
                out.append(
                    {
                        "id": code,
                        "title": code,
                        "url": f"https://jable.tv/videos/{code}/",
                        "cover": "",
                        "preview": "",
                        "duration": "",
                        "views": 0,
                        "likes": 0,
                        "date": "",
                        "actors": [],
                    }
                )
    return out


def _order_path(spec: dict[str, str]) -> Path:
    from .jable_lists import _list_dir

    return _list_dir(spec["path"], spec["term"]) / "order.json"


def _order_key(spec: dict[str, str]) -> str:
    return f"{spec.get('path')}|{spec.get('term')}"


def load_order(spec: dict[str, str]) -> list[str]:
    key = _order_key(spec)
    with _ORDER_LOCK:
        hit = _ORDERS.get(key)
        if hit:
            return list(hit)
    path = _order_path(spec)
    codes: list[str] = []
    hint = 0
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            raw = data.get("codes") if isinstance(data, dict) else None
            if isinstance(raw, list):
                codes = [str(c).strip().lower() for c in raw if str(c).strip()]
            if isinstance(data, dict):
                hint = int(data.get("total_hint") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            codes = []
            hint = 0
    with _ORDER_LOCK:
        _ORDERS[key] = codes
        _ORDER_HINTS[key] = max(int(_ORDER_HINTS.get(key) or 0), hint, len(codes))
    return list(codes)


def save_order(spec: dict[str, str], codes: list[str], total_hint: int = 0) -> None:
    key = _order_key(spec)
    uniq: list[str] = []
    seen: set[str] = set()
    for code in codes:
        c = str(code or "").strip().lower()
        if not c or c in seen:
            continue
        seen.add(c)
        uniq.append(c)
    prev_hint = 0
    path = _order_path(spec)
    if path.is_file():
        try:
            prev = json.loads(path.read_text(encoding="utf-8"))
            prev_hint = int((prev or {}).get("total_hint") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            prev_hint = 0
    hint = max(int(total_hint or 0), prev_hint, len(uniq))
    with _ORDER_LOCK:
        _ORDERS[key] = uniq
        _ORDER_HINTS[key] = max(int(_ORDER_HINTS.get(key) or 0), hint)
    _OVERFLOW.pop(key, None)
    payload = {
        "codes": uniq,
        "count": len(uniq),
        "total_hint": hint,
        "updated_at": _now(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    from .jable_lists import _LIST_META, _mem_key

    meta = _LIST_META.setdefault(_mem_key(spec), {})
    meta["total"] = max(int(meta.get("total") or 0), int(payload["total_hint"]), len(uniq))


def order_len(spec: dict[str, str]) -> int:
    return len(load_order(spec))


def order_total_hint(spec: dict[str, str]) -> int:
    key = _order_key(spec)
    with _ORDER_LOCK:
        hit = _ORDER_HINTS.get(key)
        if hit is not None:
            return int(hit)
    load_order(spec)
    with _ORDER_LOCK:
        return int(_ORDER_HINTS.get(key) or 0)


def works_count() -> int:
    _load_works()
    with _WORKS_LOCK:
        return len(_WORKS)


def all_work_ids() -> list[str]:
    _load_works()
    with _WORKS_LOCK:
        return list(_WORKS.keys())


def overflow_codes(spec: dict[str, str]) -> list[str]:
    codes = load_order(spec)
    n_order = len(codes)
    n_works = works_count()
    key = _order_key(spec)
    hit = _OVERFLOW.get(key)
    if hit and hit[0] == n_order and hit[1] == n_works:
        return hit[2]
    seen = set(codes)
    extra = [c for c in all_work_ids() if c not in seen]
    _OVERFLOW[key] = (n_order, n_works, extra)
    return extra


def display_len(spec: dict[str, str]) -> int:
    n = order_len(spec)
    if (spec.get("kind") or "") in _CATALOG_KINDS:
        return max(n, works_count())
    return n


def display_codes(spec: dict[str, str]) -> list[str]:
    codes = load_order(spec)
    if (spec.get("kind") or "") not in _CATALOG_KINDS:
        return list(codes)
    extra = overflow_codes(spec)
    if not extra:
        return list(codes)
    return codes + extra


_COVER_BASES = (
    "https://assets-cdn.jable.tv",
    "https://static-assets-cdn.jable.tv",
)


def pack_cover(url: str) -> str:
    text = str(url or "")
    for i, base in enumerate(_COVER_BASES):
        if text.startswith(base):
            return f"{i}{text[len(base):]}"
    return text


def compact_cards(codes: list[str]) -> list[list[Any]]:
    _load_works()
    out: list[list[Any]] = []
    with _WORKS_LOCK:
        for code in codes:
            row = _WORKS.get(code)
            if row:
                actors = row.get("actors") or []
                actor_s = ",".join(
                    f"{a.get('name') or ''}|{a.get('slug') or ''}"
                    for a in actors
                    if isinstance(a, dict)
                )
                out.append(
                    [
                        code,
                        row.get("title") or code,
                        pack_cover(str(row.get("cover") or "")),
                        row.get("duration") or "",
                        row.get("views") or 0,
                        row.get("date") or "",
                        actor_s,
                    ]
                )
            elif code:
                out.append([code, code, "", "", 0, "", ""])
    return out


def _cached_order_len(spec: dict[str, str]) -> int | None:
    key = _order_key(spec)
    with _ORDER_LOCK:
        hit = _ORDERS.get(key)
        if hit is not None:
            return len(hit)
    return None


def _slice_order(spec: dict[str, str], start: int, n: int) -> tuple[list[str], int]:
    """Return (order[start:start+n], order_len) without copying the whole order."""
    key = _order_key(spec)
    with _ORDER_LOCK:
        hit = _ORDERS.get(key)
        if hit is not None:
            return hit[start : start + n], len(hit)
    codes = load_order(spec)
    return codes[start : start + n], len(codes)


def _slice_overflow(spec: dict[str, str], start: int, n: int) -> list[str]:
    key = _order_key(spec)
    n_order = _cached_order_len(spec)
    n_works = works_count()
    hit = _OVERFLOW.get(key)
    if hit and n_order is not None and hit[0] == n_order and hit[1] == n_works:
        extra = hit[2]
        return extra[start : start + n]
    extra = overflow_codes(spec)
    return extra[start : start + n]


def codes_for_ui_page(spec: dict[str, str], page: int, page_size: int = 12) -> list[str]:
    """Return exactly the codes for that UI page (0..page_size). Local only."""
    page = max(1, int(page or 1))
    start = (page - 1) * page_size
    chunk, n_order = _slice_order(spec, start, page_size)
    catalog = (spec.get("kind") or "") in _CATALOG_KINDS
    if start < n_order:
        if len(chunk) >= page_size or not catalog:
            return chunk
        return chunk + _slice_overflow(spec, 0, page_size - len(chunk))
    if catalog:
        return _slice_overflow(spec, start - n_order, page_size)
    return []


def page_is_local(spec: dict[str, str], page: int, page_size: int = 12) -> bool:
    """True if this UI page can be filled from order + overflow without network."""
    page = max(1, int(page or 1))
    start = (page - 1) * page_size
    if (spec.get("kind") or "") in _CATALOG_KINDS:
        return start < display_len(spec)
    return start < order_len(spec)


def items_for_ui_page(spec: dict[str, str], page: int, page_size: int = 12) -> list[dict[str, Any]]:
    return works_for_codes(codes_for_ui_page(spec, page, page_size))


def prepend_order(spec: dict[str, str], head: list[dict[str, Any]], total_hint: int = 0) -> int:
    ingest_works(head)
    old = load_order(spec)
    seen: set[str] = set()
    new_codes: list[str] = []
    added = 0
    old_set = set(old)
    for row in head:
        code = str(row.get("id") or row.get("code") or "").strip().lower()
        if not code or code in seen:
            continue
        seen.add(code)
        new_codes.append(code)
        if code not in old_set:
            added += 1
    tail = [c for c in old if c not in seen]
    hint = max(int(total_hint or 0), len(new_codes) + len(tail))
    save_order(spec, new_codes + tail, total_hint=hint)
    return added


def extend_order_from_disk(spec: dict[str, str]) -> int:
    """Grow order.json from contiguous pages/*.json. Never shrinks."""
    from .jable_lists import SITE_PAGE_SIZE, _LIST_META, _mem_key, _pages_dir, _read_list_json

    existing = load_order(spec)
    folder = _pages_dir(spec)
    contiguous = 0
    while folder.is_dir() and (folder / f"{contiguous + 1}.json").is_file():
        contiguous += 1
        if contiguous > 4000:
            break
    hint = int(order_total_hint(spec) or 0)
    try:
        hint = max(hint, int((_LIST_META.get(_mem_key(spec)) or {}).get("total") or 0))
    except Exception:
        pass
    cached: dict[str, Any] | None = None

    def bump_hint(codes: list[str]) -> None:
        if codes and hint > int(order_total_hint(spec) or 0):
            save_order(spec, codes, total_hint=hint)

    if existing and not contiguous:
        bump_hint(existing)
        return len(existing)
    if existing and contiguous:
        lower = (contiguous - 1) * SITE_PAGE_SIZE
        upper = contiguous * SITE_PAGE_SIZE
        if len(existing) > upper or (lower < len(existing) <= upper):
            bump_hint(existing)
            return len(existing)

    codes: list[str] = []
    seen: set[str] = set()
    n = 1
    while folder.is_dir():
        path = folder / f"{n}.json"
        if not path.is_file():
            break
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            break
        if not isinstance(rows, list) or not rows:
            break
        ingest_works(rows)
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("id") or row.get("code") or "").strip().lower()
            if not code or code in seen:
                continue
            seen.add(code)
            codes.append(code)
        n += 1
    if len(codes) < SITE_PAGE_SIZE:
        cached = _read_list_json(spec["path"], spec["term"]) or {}
        ingest_works(list(cached.get("items") or []))
        for row in list(cached.get("items") or []):
            if not isinstance(row, dict):
                continue
            code = str(row.get("id") or row.get("code") or "").strip().lower()
            if not code or code in seen:
                continue
            seen.add(code)
            codes.append(code)
        hint = max(hint, int(cached.get("total_hint") or cached.get("total") or 0))
    elif not hint:
        cached = _read_list_json(spec["path"], spec["term"]) or {}
        hint = int(cached.get("total_hint") or cached.get("total") or 0)
    if existing and len(existing) >= len(codes):
        bump_hint(existing)
        return len(existing)
    if codes:
        save_order(spec, codes, total_hint=max(hint, len(codes), len(existing)))
        return len(codes)
    return len(existing)


def seed_order(spec: dict[str, str]) -> int:
    existing = load_order(spec)
    kind = spec.get("kind") or ""
    if existing and len(existing) >= 256 and kind != "model":
        return len(existing)
    return extend_order_from_disk(spec)


def ingest_works(rows: list[dict[str, Any]]) -> int:
    added = 0
    changed = False
    with _WORKS_LOCK:
        for row in rows or []:
            item = _normalize_work(row if isinstance(row, dict) else {})
            if not item:
                continue
            code = item["id"]
            old = _WORKS.get(code)
            if old is None:
                item["seen_at"] = _now()
                _WORKS[code] = item
                added += 1
                changed = True
            else:
                for key in ("title", "cover", "preview", "duration", "views", "likes", "url", "date"):
                    if item.get(key) and old.get(key) != item[key]:
                        old[key] = item[key]
                        if key in ("title", "date"):
                            changed = True
                if item.get("actors") and old.get("actors") != item["actors"]:
                    old["actors"] = item["actors"]
                    changed = True
        if changed:
            _touch_works()
    return added


def _flush_works() -> None:
    with _WORKS_LOCK:
        payload = {
            "count": len(_WORKS),
            "updated_at": _now(),
            "items": list(_WORKS.values()),
        }
    try:
        _works_path().write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _load_works() -> None:
    global _WORKS_LOADED
    if _WORKS_LOADED:
        return
    path = _works_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        items = data.get("items") if isinstance(data, dict) else None
        if isinstance(items, list):
            ingest_works(items)
    harvest_search_dates()
    _WORKS_LOADED = True


def harvest_search_dates() -> int:
    root = library_dir() / "jable" / "_lists" / "search"
    if not root.is_dir():
        return 0
    filled = 0
    with _WORKS_LOCK:
        for folder in root.iterdir():
            if not folder.is_dir():
                continue
            stamp = _date_from_search_label(folder.name)
            if not stamp:
                continue
            order_path = folder / "post_date" / "order.json"
            if not order_path.is_file():
                found = next(folder.rglob("order.json"), None)
                if found is None:
                    continue
                order_path = found
            try:
                data = json.loads(order_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            codes = data.get("codes") if isinstance(data, dict) else data
            if not isinstance(codes, list):
                continue
            rank = _date_rank(stamp)
            for code in codes:
                key = str(code or "").strip().lower()
                row = _WORKS.get(key)
                if not row:
                    continue
                if _date_rank(str(row.get("date") or "")) >= rank:
                    continue
                row["date"] = stamp
                filled += 1
    if filled:
        _touch_works()
    return filled


def harvest_list_files() -> int:
    root = library_dir() / "jable" / "_lists"
    if not root.is_dir():
        return 0
    added = 0
    for path in root.rglob("items.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows = data.get("items") if isinstance(data, dict) else None
        if isinstance(rows, list):
            added += ingest_works(rows)
    for folder in root.rglob("pages"):
        if not folder.is_dir():
            continue
        for path in folder.glob("*.json"):
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(rows, list):
                added += ingest_works(rows)
    return added


def ensure_cover(url: str) -> bool:
    raw = (url or "").strip()
    if not raw:
        return False
    dest = cover_cache_path(raw)
    if dest.is_file() and dest.stat().st_size >= 80:
        return True
    curl = shutil.which("curl.exe") or shutil.which("curl")
    data = b""
    if curl:
        try:
            result = subprocess.run(
                [
                    curl,
                    "-sL",
                    "--max-time",
                    "12",
                    "-A",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36",
                    "-H",
                    "Referer: https://jable.tv/",
                    "-H",
                    "Accept: image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    raw,
                ],
                check=False,
                capture_output=True,
            )
            data = result.stdout or b""
        except OSError:
            data = b""
    if len(data) < 80:
        return False
    try:
        dest.write_bytes(data)
    except OSError:
        return False
    return True


def prefetch_covers(rows: list[dict[str, Any]], limit: int = 120) -> int:
    urls: list[str] = []
    seen: set[str] = set()
    for row in rows or []:
        url = str((row or {}).get("cover") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
        if len(urls) >= limit:
            break
    if not urls:
        return 0
    ok = 0
    workers = min(COVER_WORKERS, len(urls))
    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futs = [pool.submit(ensure_cover, url) for url in urls]
            for fut in as_completed(futs):
                try:
                    if fut.result():
                        ok += 1
                except Exception:
                    pass
    except RuntimeError:
        return ok
    return ok


def _pull_front(spec: dict[str, str], pages: int) -> tuple[list[dict[str, Any]], int]:
    from jable_hot import RateGate, fetch_list_page, list_url, parse_items, parse_total

    from .jable_lists import _public_items

    pages = max(1, min(int(pages or 1), 8))
    gate = RateGate(0.05)
    rows: list[dict[str, Any]] = []
    total = 0
    for page in range(1, pages + 1):
        url = list_url(spec["path"], spec["term"], page, block_id=spec["block_id"])
        html = fetch_list_page(url, gate, timeout=15, retries=2)
        chunk = parse_items(html) or []
        total = parse_total(html) or total
        rows.extend(chunk)
    return _public_items({"items": rows}, 10000), total


def _merge_list_head(spec: dict[str, str], head: list[dict[str, Any]], total_hint: int) -> int:
    from .jable_lists import (
        SITE_PAGE_SIZE,
        _mem_key,
        _pack_list,
        _read_list_json,
        _save_list_json,
        _save_site_page,
        _LIST_SITE,
    )

    existing = _read_list_json(spec["path"], spec["term"]) or {}
    old = list(existing.get("items") or [])
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    new_n = 0
    old_codes = {
        str(x.get("id") or x.get("code") or "").strip().lower()
        for x in old
        if str(x.get("id") or x.get("code") or "").strip()
    }
    for row in head:
        code = str(row.get("id") or row.get("code") or "").strip().lower()
        if not code or code in seen:
            continue
        seen.add(code)
        if code not in old_codes:
            new_n += 1
        merged.append(row)
    for row in old:
        code = str(row.get("id") or row.get("code") or "").strip().lower()
        if not code or code in seen:
            continue
        seen.add(code)
        merged.append(row)
    hint = max(int(total_hint or 0), int(existing.get("total_hint") or existing.get("total") or 0), len(merged))
    payload = dict(existing) if isinstance(existing, dict) else {}
    payload.update(
        {
            "path": spec["path"],
            "term": spec["term"],
            "label": spec.get("title") or "",
            "total_hint": hint,
            "total": hint,
            "count": len(merged),
            "fetched_at": _now(),
            "items": merged,
        }
    )
    payload["items"] = merged[:240]
    _save_list_json(spec, payload)
    for i in range(0, min(len(head), SITE_PAGE_SIZE * 8), SITE_PAGE_SIZE):
        _save_site_page(spec, i // SITE_PAGE_SIZE + 1, head[i : i + SITE_PAGE_SIZE])
    prepend_order(spec, head, hint)
    _pack_list(spec, head[:240] or merged[:240], cached=True, total_hint=hint, total=hint, index_pages=False)
    key = _mem_key(spec)
    bucket = _LIST_SITE.setdefault(key, {})
    for i in range(0, len(head), SITE_PAGE_SIZE):
        bucket[i // SITE_PAGE_SIZE + 1] = head[i : i + SITE_PAGE_SIZE]
    return new_n


def works_compact() -> list[list[Any]]:
    global _WORKS_COMPACT, _WORKS_COMPACT_N
    _load_works()
    n = works_count()
    if _WORKS_COMPACT is not None and _WORKS_COMPACT_N == (n, _WORKS_GEN):
        return _WORKS_COMPACT
    cards = compact_cards(all_work_ids())
    _WORKS_COMPACT = cards
    _WORKS_COMPACT_N = (n, _WORKS_GEN)
    return cards


def _fetch_site_batch(
    spec: dict[str, str],
    pages: list[int],
    workers: int | None = None,
) -> dict[int, list[dict[str, Any]]]:
    from jable_hot import list_url, looks_like_list, parse_items
    from jable_http import fetch_many, wait_rate_limit

    from .jable_lists import SITE_PAGE_SIZE, _public_items

    if not pages:
        return {}
    wait_rate_limit()
    model = (spec.get("kind") or "") == "model"
    urls = [
        list_url(spec["path"], spec["term"], page, async_mode=not model, block_id=spec["block_id"])
        for page in pages
    ]
    conc = max(1, int(workers or BACKFILL_WORKERS or 2))
    rows = fetch_many(urls, timeout=20, parallel_max=min(conc, len(urls)))
    out: dict[int, list[dict[str, Any]]] = {}
    for page, (_url, body, _detail) in zip(pages, rows):
        html = (body or b"").decode("utf-8", errors="replace")
        if not looks_like_list(html):
            continue
        if model:
            try:
                from jable_user import looks_like_model_page

                if not looks_like_model_page(html):
                    continue
            except Exception:
                if "title-with-avatar" not in html:
                    continue
        chunk = parse_items(html) or []
        if chunk:
            out[int(page)] = _public_items({"items": chunk}, SITE_PAGE_SIZE)
    return out


def backfill_one(spec: dict[str, str], max_pages: int | None = None) -> dict[str, Any]:
    from .jable_lists import SITE_PAGE_SIZE, _LIST_META, _mem_key, _save_site_page

    seed_order(spec)
    total = int((_LIST_META.get(_mem_key(spec)) or {}).get("total") or 0)
    if total < SITE_PAGE_SIZE * 2:
        try:
            head, total = _pull_front(spec, 1)
        except Exception:
            head, total = [], total
        if head:
            ingest_works(head)
            prepend_order(spec, head, total)
    total = max(total, order_len(spec))
    total_pages = max(1, (max(total, 1) + SITE_PAGE_SIZE - 1) // SITE_PAGE_SIZE)
    if max_pages:
        total_pages = min(total_pages, int(max_pages))
    start = len(load_order(spec)) // SITE_PAGE_SIZE + 1
    label = f"{spec.get('kind')}|{spec.get('term')}"
    info = {"done": max(0, start - 1), "total": total_pages, "items": order_len(spec)}
    _STATE.setdefault("backfill", {})[label] = info
    _save_state()
    todo = list(range(start, total_pages + 1))
    i = 0
    while i < len(todo):
        batch = todo[i : i + BACKFILL_BATCH]
        i += len(batch)
        try:
            got = _fetch_site_batch(spec, batch)
        except Exception:
            got = {}
            time.sleep(4)
        extra: list[str] = []
        time.sleep(0.8)
        for page in batch:
            chunk = got.get(page) or []
            if not chunk:
                continue
            ingest_works(chunk)
            _save_site_page(spec, page, chunk)
            enqueue_covers(chunk)
            extra.extend(str(row.get("id") or "") for row in chunk)
        if extra:
            save_order(spec, load_order(spec) + extra, total_hint=total)
        missing = [p for p in batch if p not in got]
        if missing:
            time.sleep(3)
            try:
                retry = _fetch_site_batch(spec, missing)
            except Exception:
                retry = {}
            extra2: list[str] = []
            for page in missing:
                chunk = retry.get(page) or []
                if not chunk:
                    continue
                ingest_works(chunk)
                _save_site_page(spec, page, chunk)
                enqueue_covers(chunk)
                extra2.extend(str(row.get("id") or "") for row in chunk)
            if extra2:
                save_order(spec, load_order(spec) + extra2, total_hint=total)
        info = {
            "done": min(batch[-1], total_pages),
            "total": total_pages,
            "items": order_len(spec),
        }
        _STATE.setdefault("backfill", {})[label] = info
        if batch[-1] % 20 == 0 or batch[-1] >= total_pages:
            _flush_works()
            _save_state()
    _flush_works()
    _save_state()
    return info


def start_full_backfill() -> None:
    if not _BACKFILL_LOCK.acquire(blocking=False):
        return

    def work() -> None:
        try:
            from .jable_lists import _resolve_list

            try:
                from jable_http import wait_rate_limit

                time.sleep(60.0)
                wait_rate_limit()
            except Exception:
                time.sleep(60.0)
            _load_works()
            specs = [_resolve_list(kind, "", "") for kind in BACKFILL_KINDS]
            for spec in specs:
                try:
                    backfill_one(spec, max_pages=30)
                except Exception as exc:
                    _STATE.setdefault("backfill", {})[str(spec.get("kind"))] = {"error": str(exc)[:200]}
                    _save_state()
            for spec in specs:
                try:
                    backfill_one(spec)
                except Exception as exc:
                    _STATE.setdefault("backfill", {})[str(spec.get("kind"))] = {"error": str(exc)[:200]}
                    _save_state()
            _STATE["backfill_done"] = _now()
            _STATE["works"] = len(_WORKS)
            _flush_works()
            _save_state()
        finally:
            try:
                _BACKFILL_LOCK.release()
            except Exception:
                pass

    threading.Thread(target=work, daemon=True, name="jable-full-backfill").start()


def run_daily_index(*, force: bool = False) -> dict[str, Any]:
    if not _RUN_LOCK.acquire(blocking=False):
        return dict(_STATE) | {"busy": True}
    t0 = time.time()
    try:
        _load_state()
        _load_works()
        harvested = harvest_list_files()
        from .jable_lists import _pack_home, _resolve_list, _save_home, _HOME_CACHE

        jobs = [
            (_resolve_list("latest", "", ""), LATEST_PAGES),
            (_resolve_list("hot", "", ""), HOT_PAGES),
        ]
        added = 0
        covers = 0
        fronts: dict[str, list[dict[str, Any]]] = {}
        for spec, pages in jobs:
            try:
                head, total = _pull_front(spec, pages)
            except Exception:
                head, total = [], 0
            if not head:
                continue
            added += ingest_works(head)
            _merge_list_head(spec, head, total)
            covers += prefetch_covers(head)
            fronts[spec["kind"]] = head
        pending: list[dict[str, Any]] = []
        with _WORKS_LOCK:
            for row in _WORKS.values():
                url = str(row.get("cover") or "").strip()
                if url and not cover_cache_path(url).is_file():
                    pending.append(row)
                if len(pending) >= 80:
                    break
        if pending:
            covers += prefetch_covers(pending, 80)
        _flush_works()
        if fronts.get("latest") or fronts.get("hot"):
            home = _pack_home(
                {"items": [{"code": x["id"], **x} for x in fronts.get("latest") or []]},
                {"items": [{"code": x["id"], **x} for x in fronts.get("hot") or []]},
            )
            _HOME_CACHE["ts"] = time.time()
            _HOME_CACHE["data"] = home
            _save_home(home)
        _STATE.update(
            {
                "last_run": _now(),
                "last_ms": int((time.time() - t0) * 1000),
                "last_added": added,
                "last_harvested": harvested,
                "last_covers": covers,
                "works": len(_WORKS),
                "ok": True,
                "forced": bool(force),
            }
        )
        _save_state()
        return dict(_STATE)
    except Exception as exc:
        _STATE.update({"last_run": _now(), "ok": False, "error": str(exc)[:240]})
        _save_state()
        raise
    finally:
        _RUN_LOCK.release()


def index_status() -> dict[str, Any]:
    _load_state()
    _load_works()
    with _WORKS_LOCK:
        n = len(_WORKS)
    covers = 0
    folder = cover_dir()
    if folder.is_dir():
        covers = sum(1 for p in folder.glob("*.jpg") if p.is_file())
    return {
        "works": n or int(_STATE.get("works") or 0),
        "covers": covers,
        "last_run": _STATE.get("last_run") or "",
        "last_added": _STATE.get("last_added") or 0,
        "last_covers": _STATE.get("last_covers") or 0,
        "ok": _STATE.get("ok"),
        "interval_sec": DAILY_SEC,
        "backfill": _STATE.get("backfill") or {},
        "backfill_done": _STATE.get("backfill_done") or "",
    }


def start_daily_index() -> None:
    global _STARTED
    if _STARTED:
        return
    _STARTED = True

    def loop() -> None:
        time.sleep(1.0)
        try:
            from jable_http import wait_rate_limit

            wait_rate_limit()
        except Exception:
            pass
        try:
            run_daily_index()
        except Exception:
            pass
        try:
            start_full_backfill()
        except Exception:
            pass
        while True:
            time.sleep(DAILY_SEC)
            try:
                run_daily_index()
            except Exception:
                pass

    threading.Thread(target=loop, daemon=True, name="jable-daily-index").start()
