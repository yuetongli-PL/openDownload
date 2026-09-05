# -*- coding: utf-8 -*-
"""Jable 热门 / 選片：把公开列表解析进确认看板（正片仍走确认后下载）。"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, unquote

from .paths import library_dir

LogFn = Callable[[str], None]

DEFAULT_CATEGORIES = [
    ("bdsm", "主奴調教"),
    ("sex-only", "直接開啪"),
    ("chinese-subtitle", "中文字幕"),
    ("insult", "凌辱快感"),
    ("uniform", "制服誘惑"),
    ("roleplay", "角色劇情"),
    ("private-cam", "盜攝偷拍"),
    ("uncensored", "無碼解放"),
    ("pov", "男友視角"),
    ("groupsex", "多P群交"),
    ("pantyhose", "絲襪美腿"),
    ("lesbian", "女同歡愉"),
]


def _log(log: LogFn | None, msg: str) -> None:
    if log:
        log(msg)


def catalog() -> dict[str, Any]:
    from jable_hot import TERM_ORDER, TERMS
    from jable_pick import GROUPS, PICK_TERMS

    year_now = date.today().year
    if year_now < 2026:
        year_now = 2026
    return {
        "hot_terms": [{"id": key, "name": TERMS[key]} for key in TERM_ORDER],
        "pick_terms": [{"id": key, "name": name} for key, name in PICK_TERMS.items()],
        "categories": [{"slug": slug, "name": name} for slug, name in DEFAULT_CATEGORIES],
        "groups": [
            {
                "name": group,
                "tags": [{"name": name, "slug": slug} for name, slug in tags],
            }
            for group, tags in GROUPS.items()
        ],
        "extra_groups": ["按主題", "按女優", "新片優先", "熱度優先"],
        "years": list(range(year_now, 1999, -1)),
        "months": [{"id": str(i), "name": f"{i}月"} for i in range(1, 13)],
        "hot_sorts": [
            {"id": "hot", "name": "今日观看", "term": "video_viewed_today"},
            {"id": "week", "name": "每周观看", "term": "video_viewed_week"},
            {"id": "month", "name": "每月观看", "term": "video_viewed_month"},
            {"id": "all", "name": "最多观看", "term": "video_viewed"},
        ],
    }


def _out_dir(*parts: str) -> Path:
    path = library_dir() / "jable" / "_lists"
    for part in parts:
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in part)[:80]
        path = path / (safe or "_")
    path.mkdir(parents=True, exist_ok=True)
    return path


def crawl_one(
    *,
    path: str,
    term: str,
    label: str,
    pages: int,
    log: LogFn | None = None,
    block_id: str = "list_videos_common_videos_list",
    extra: dict[str, Any] | None = None,
    force: bool = True,
    cache_ttl: float = 180.0,
) -> dict[str, Any]:
    from jable_hot import crawl_list
    from jable_http import warmup

    pages = int(pages or 0)
    if pages < 0:
        pages = 0
    if pages > 80:
        pages = 80
    out = _out_dir(*[p for p in path.strip("/").split("/") if p], term or "default")
    cached = out / "items.json"
    if not force and cached.is_file() and time.time() - cached.stat().st_mtime < cache_ttl:
        try:
            payload = json.loads(cached.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("items"):
                _log(log, f"缓存 {label}  {len(payload['items'])} 部")
                return payload
        except (OSError, json.JSONDecodeError):
            pass
    _log(log, f"列表 {label}  path={path}  term={term}  pages={pages or '全部'}")
    warmup(timeout=15)
    payload = crawl_list(
        path=path,
        term=term or "post_date",
        label=label,
        out_dir=out,
        sleep=0.05,
        workers=10,
        timeout=20,
        max_pages=pages,
        force=force,
        formats={"json"},
        extra_meta=extra,
        block_id=block_id,
    )
    items = payload.get("items") or []
    _log(log, f"抓到 {len(items)} 部  {label}")
    return payload


def _public_items(payload: dict[str, Any], limit: int = 240) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for row in (payload.get("items") or [])[:limit]:
        code = str(row.get("code") or "").strip().lower()
        if not code:
            continue
        cards.append(
            {
                "id": code,
                "title": row.get("title") or code,
                "url": row.get("url") or f"https://jable.tv/videos/{code}/",
                "cover": row.get("cover") or "",
                "preview": row.get("preview") or "",
                "duration": row.get("duration") or "",
                "views": row.get("views") or 0,
                "likes": row.get("likes") or 0,
                "date": row.get("date") or "",
                "actors": row.get("actors") or [],
            }
        )
        if not cards[-1]["actors"]:
            try:
                from jable_hot import actors_from_title

                cards[-1]["actors"] = actors_from_title(str(cards[-1]["title"] or ""))
            except Exception:
                pass
        if not cards[-1]["date"] or not cards[-1]["actors"]:
            try:
                from .jable_index import _WORKS, _WORKS_LOCK, _load_works

                _load_works()
                with _WORKS_LOCK:
                    hit = _WORKS.get(cards[-1]["id"])
                if hit:
                    if not cards[-1]["date"] and hit.get("date"):
                        cards[-1]["date"] = hit.get("date") or ""
                    if not cards[-1]["actors"] and hit.get("actors"):
                        cards[-1]["actors"] = hit.get("actors") or []
            except Exception:
                pass
    return cards


def _hydrate_home(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"latest": {"title": "最新影片", "items": []}, "hot": {"title": "今日热门", "items": []}}
    out = dict(data)
    for key in ("latest", "hot"):
        block = dict(out.get(key) or {})
        rows = []
        for row in block.get("items") or []:
            if not isinstance(row, dict):
                continue
            item = dict(row)
            title = item.get("title") or item.get("id") or ""
            if not item.get("actors"):
                try:
                    from jable_hot import actors_from_title

                    item["actors"] = actors_from_title(str(title or ""))
                except Exception:
                    item["actors"] = []
            rows.append(item)
        block["items"] = rows
        out[key] = block
    return out


_HOME_TTL = 180.0
_HOME_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}
_REFRESH_LOCK = threading.Lock()


def _home_json_path() -> Path:
    path = library_dir() / "jable" / "_lists" / "home.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _list_dir(path: str, term: str) -> Path:
    return _out_dir(*[p for p in path.strip("/").split("/") if p], term or "default")


def _save_list_json(spec: dict[str, str], payload: dict[str, Any]) -> None:
    out = _list_dir(spec["path"], spec["term"])
    try:
        (out / "items.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _pages_dir(spec: dict[str, str]) -> Path:
    return _list_dir(spec["path"], spec["term"]) / "pages"


def _save_site_page(spec: dict[str, str], site_page: int, items: list[dict[str, Any]]) -> None:
    if not items:
        return
    folder = _pages_dir(spec)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{int(site_page)}.json").write_text(
            json.dumps(items, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def _load_site_pages(spec: dict[str, str]) -> None:
    folder = _pages_dir(spec)
    if not folder.is_dir():
        return
    key = _mem_key(spec)
    bucket = _LIST_SITE.setdefault(key, {})
    for path in folder.glob("*.json"):
        try:
            num = int(path.stem)
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(rows, list) and rows:
            bucket[num] = rows


def _read_list_json(path: str, term: str) -> dict[str, Any] | None:
    out = _list_dir(path, term)
    cached = out / "items.json"
    if cached.is_file():
        try:
            payload = json.loads(cached.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and payload.get("items"):
            return payload
    jsonl = out / "items.jsonl"
    if not jsonl.is_file():
        return None
    items: list[dict[str, Any]] = []
    try:
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if isinstance(row, dict) and row.get("code"):
                items.append(row)
    except (OSError, json.JSONDecodeError):
        return None
    if not items:
        return None
    return {"items": items}


def _pack_home(latest_p: dict[str, Any] | None, hot_p: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "latest": {"title": "最新影片", "items": _public_items(latest_p or {})},
        "hot": {"title": "今日热门", "items": _public_items(hot_p or {})},
    }


def _save_home(data: dict[str, Any]) -> None:
    try:
        _home_json_path().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _read_home_disk() -> dict[str, Any] | None:
    path = _home_json_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and (
                (data.get("latest") or {}).get("items") or (data.get("hot") or {}).get("items")
            ):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    latest_p = _read_list_json("/latest-updates/", "post_date")
    hot_p = _read_list_json("/hot/", "video_viewed_today")
    if not latest_p and not hot_p:
        return None
    data = _pack_home(latest_p, hot_p)
    _save_home(data)
    return data


def _crawl_home(pages: int, force: bool) -> dict[str, Any]:
    def latest() -> dict[str, Any]:
        return crawl_one(
            path="/latest-updates/",
            term="post_date",
            label="最新影片",
            pages=pages,
            extra={"scope": "latest"},
            force=force,
            block_id="list_videos_latest_videos_list",
        )

    def hot() -> dict[str, Any]:
        return crawl_one(
            path="/hot/",
            term="video_viewed_today",
            label="今日热门",
            pages=pages,
            extra={"scope": "hot"},
            force=force,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_latest = pool.submit(latest)
        f_hot = pool.submit(hot)
        try:
            latest_p = f_latest.result()
        except Exception:
            latest_p = {"items": []}
        try:
            hot_p = f_hot.result()
        except Exception:
            hot_p = {"items": []}
    return _pack_home(latest_p, hot_p)


def _refresh_home_bg(pages: int) -> None:
    if not _REFRESH_LOCK.acquire(blocking=False):
        return
    try:
        data = _crawl_home(pages, force=True)
        if (data["latest"]["items"] or data["hot"]["items"]):
            _HOME_CACHE["ts"] = time.time()
            _HOME_CACHE["data"] = data
            _save_home(data)
    except Exception:
        pass
    finally:
        _REFRESH_LOCK.release()


def home_feed(*, pages: int = 2, force: bool = False) -> dict[str, Any]:
    now = time.time()
    if force:
        data = _crawl_home(pages, force=True)
        _HOME_CACHE["ts"] = now
        _HOME_CACHE["data"] = data
        _save_home(data)
        return _hydrate_home(data)

    mem = _HOME_CACHE.get("data")
    if mem and ((mem.get("latest") or {}).get("items") or (mem.get("hot") or {}).get("items")):
        age = now - float(_HOME_CACHE.get("ts") or 0)
        if age > _HOME_TTL:
            threading.Thread(target=_refresh_home_bg, args=(pages,), daemon=True).start()
        _prefetch_hot_ranges()
        return _hydrate_home(mem)

    disk = _read_home_disk()
    if disk:
        _HOME_CACHE["ts"] = now
        _HOME_CACHE["data"] = disk
        threading.Thread(target=_refresh_home_bg, args=(pages,), daemon=True).start()
        _prefetch_hot_ranges()
        return _hydrate_home(disk)

    data = _crawl_home(pages, force=False)
    _HOME_CACHE["ts"] = now
    _HOME_CACHE["data"] = data
    _save_home(data)
    return _hydrate_home(data)


_LIST_KINDS = {
    "latest": {
        "path": "/latest-updates/",
        "term": "post_date",
        "block_id": "list_videos_latest_videos_list",
        "title": "最新影片",
    },
    "hot": {
        "path": "/hot/",
        "term": "video_viewed_today",
        "block_id": "list_videos_common_videos_list",
        "title": "热门",
    },
    "week": {
        "path": "/hot/",
        "term": "video_viewed_week",
        "block_id": "list_videos_common_videos_list",
        "title": "本周热门",
    },
    "month": {
        "path": "/hot/",
        "term": "video_viewed_month",
        "block_id": "list_videos_common_videos_list",
        "title": "本月热门",
    },
    "all": {
        "path": "/hot/",
        "term": "video_viewed",
        "block_id": "list_videos_common_videos_list",
        "title": "所有时间",
    },
    "type": {
        "path": "/hot/",
        "term": "video_viewed",
        "block_id": "list_videos_common_videos_list",
        "title": "类型",
    },
}

_LIST_MEM: dict[str, dict] = {}
_LIST_SITE: dict[str, dict[int, list[dict[str, Any]]]] = {}
_LIST_META: dict[str, dict[str, Any]] = {}
_LIST_LOCKS: dict[str, threading.Lock] = {}
_LIST_LOCKS_MU = threading.Lock()
_LIST_SEM = threading.Semaphore(10)
SITE_PAGE_SIZE = 24


def _mem_key(spec: dict[str, str]) -> str:
    return f"{spec['path']}|{spec['term']}"


def _lock_for(spec: dict[str, str]) -> threading.Lock:
    key = _mem_key(spec)
    with _LIST_LOCKS_MU:
        lock = _LIST_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LIST_LOCKS[key] = lock
        return lock


_CATALOG_KINDS = {"hot", "latest", "week", "month", "all", "type"}
_PAGED_KINDS = {"tag", "cat", "model"}
_MODEL_FILLING: set[str] = set()
_MODEL_FILL_MU = threading.Lock()
_TERM_ALIAS = {
    "all": "video_viewed",
    "alltime": "video_viewed",
    "all-time": "video_viewed",
    "week": "video_viewed_week",
    "weekly": "video_viewed_week",
    "month": "video_viewed_month",
    "monthly": "video_viewed_month",
    "hot": "video_viewed_today",
    "today": "video_viewed_today",
    "daily": "video_viewed_today",
    "latest": "post_date",
    "new": "post_date",
}
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")


def _norm_term(term: str) -> str:
    text = (term or "").strip()
    return _TERM_ALIAS.get(text, text)


def _clean_year(year: str) -> str:
    text = (year or "").strip()
    return text if _YEAR_RE.fullmatch(text) else ""


def _clean_month(month: str) -> str:
    text = (month or "").strip()
    if text.isdigit() and 1 <= int(text) <= 12:
        return str(int(text))
    return ""


_HEX_SLUG_RE = re.compile(r"^[a-f0-9]{32}$", re.I)
_MODEL_H2_RE = re.compile(r'<h2 class="h3-md mb-1">([^<]+)</h2>', re.I)
_MODEL_TITLES: dict[str, str] = {}


def _looks_like_person_name(text: str) -> bool:
    name = unescape((text or "").strip())
    if not name or _HEX_SLUG_RE.fullmatch(name):
        return False
    compact = re.sub(r"[\s\-_.]", "", name)
    if len(compact) >= 24 and compact.isalnum():
        return False
    try:
        from jable_hot import good_actor_name

        if not good_actor_name(name):
            return False
    except Exception:
        pass
    return True


def _model_profile_path(slug: str) -> Path:
    return _out_dir("models", slug) / "profile.json"


def _save_model_title(slug: str, name: str) -> None:
    if not slug or not _looks_like_person_name(name):
        return
    _MODEL_TITLES[slug] = name
    path = _model_profile_path(slug)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"slug": slug, "name": name}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def _model_title(slug: str) -> str:
    key = (slug or "").strip()
    if not key:
        return ""
    hit = _MODEL_TITLES.get(key)
    if hit:
        return hit
    path = _model_profile_path(key)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        name = str((data or {}).get("name") or "").strip()
        if _looks_like_person_name(name):
            _MODEL_TITLES[key] = name
            return name
    return ""


def _learn_model_title(slug: str, html: str) -> str:
    key = (slug or "").strip()
    if not key:
        return ""
    match = _MODEL_H2_RE.search(html or "")
    name = unescape(match.group(1)).strip() if match else ""
    if _looks_like_person_name(name):
        _save_model_title(key, name)
        return name
    return _model_title(key)


def _spec_title(spec: dict[str, str]) -> str:
    if spec.get("kind") == "model":
        name = _model_title(spec.get("slug") or "")
        if name:
            return name
        return "演员"
    return spec.get("title") or ""


def _ensure_model_title(spec: dict[str, str]) -> None:
    if spec.get("kind") != "model":
        return
    slug = spec.get("slug") or ""
    if not slug or _model_title(slug):
        return

    def work() -> None:
        try:
            from jable_hot import RateGate, fetch_list_page, list_url

            url = list_url(spec["path"], spec["term"], 1, async_mode=False, block_id=spec["block_id"])
            html = fetch_list_page(url, RateGate(0.0), timeout=12, retries=2)
            _learn_model_title(slug, html)
        except Exception:
            pass

    threading.Thread(target=work, daemon=True).start()


def _tag_title(slug: str) -> str:
    from jable_pick import GROUPS

    for tags in GROUPS.values():
        for name, tag_slug in tags:
            if tag_slug.lower() == slug:
                return name
    return slug


def _resolve_list(kind: str, slug: str, term: str, year: str = "", month: str = "") -> dict[str, str]:
    kind = (kind or "latest").strip().lower()
    slug = (slug or "").strip()
    term = _norm_term(term)
    year = _clean_year(year)
    month = _clean_month(month)
    if kind == "cat" and slug:
        key = slug.lower()
        names = {s: n for s, n in DEFAULT_CATEGORIES}
        return {
            "path": f"/categories/{key}/",
            "term": term or "post_date_and_popularity",
            "block_id": "list_videos_common_videos_list",
            "title": names.get(key, slug),
            "kind": "cat",
            "slug": key,
            "year": "",
            "month": "",
        }
    if kind in {"model", "actor", "models"} and slug:
        path_slug = unquote(slug).strip().strip("/")
        if path_slug:
            return {
                "path": f"/models/{path_slug}/",
                "term": term or "post_date",
                "block_id": "list_videos_common_videos_list",
                "title": _model_title(path_slug) or "演员",
                "kind": "model",
                "slug": path_slug,
                "year": "",
                "month": "",
            }
    if kind == "tag" and slug:
        path_slug = slug
        title = _tag_title(slug)
        needle = slug.lower()
        from jable_pick import GROUPS

        for tags in GROUPS.values():
            for name, tag_slug in tags:
                if tag_slug.lower() == needle:
                    path_slug = tag_slug
                    title = name
                    break
        return {
            "path": f"/tags/{path_slug}/",
            "term": term or "post_date_and_popularity",
            "block_id": "list_videos_common_videos_list",
            "title": title,
            "kind": "tag",
            "slug": path_slug,
            "year": "",
            "month": "",
        }
    spec = _LIST_KINDS.get(kind) or _LIST_KINDS["latest"]
    resolved = kind if kind in _LIST_KINDS else "latest"
    if resolved == "latest" and (year or month):
        if year and month:
            query = f"{year}-{int(month):02d}"
            title = f"最近添加 · {year}年{int(month)}月"
        elif year:
            query = year
            title = f"最近添加 · {year}"
        else:
            query = f"{int(month)}月"
            title = f"最近添加 · {int(month)}月"
        return {
            "path": f"/search/{quote(query, safe='')}/",
            "term": term or "post_date",
            "block_id": "list_videos_videos_list_search_result",
            "title": title,
            "kind": "latest",
            "slug": "",
            "year": year,
            "month": month,
        }
    return {
        "path": spec["path"],
        "term": term or spec["term"],
        "block_id": spec["block_id"],
        "title": spec["title"] if resolved != "latest" else "最近添加",
        "kind": resolved,
        "slug": "",
        "year": "",
        "month": "",
    }


def _fallback_home_items(kind: str) -> list[dict[str, Any]]:
    home = _HOME_CACHE.get("data") or _read_home_disk() or {}
    if kind in {"hot", "week", "month", "all", "type"}:
        return list((home.get("hot") or {}).get("items") or [])
    return list((home.get("latest") or {}).get("items") or [])


PAGE_SIZE = 12


def _pack_list(spec: dict[str, str], items: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    index_pages = extra.pop("index_pages", True)
    hint = int(extra.get("total_hint") or extra.get("total") or 0)
    total = max(hint, len(items))
    data = {
        "title": spec["title"],
        "kind": spec["kind"],
        "slug": spec.get("slug") or "",
        "term": spec["term"],
        "year": spec.get("year") or "",
        "month": spec.get("month") or "",
        "items": items,
        "total": total,
        "total_hint": hint or total,
        "page_count": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
    }
    data.update(extra)
    data["total"] = max(int(data.get("total") or 0), len(items))
    data["page_count"] = max(1, (int(data["total"]) + PAGE_SIZE - 1) // PAGE_SIZE)
    key = _mem_key(spec)
    if items:
        _LIST_MEM[key] = data
        if index_pages:
            _index_site_pages(key, items)
    if data["total"]:
        meta = _LIST_META.setdefault(key, {})
        meta["total"] = max(int(meta.get("total") or 0), data["total"])
        meta["title"] = spec["title"]
    return data


def _index_site_pages(key: str, items: list[dict[str, Any]]) -> None:
    bucket = _LIST_SITE.setdefault(key, {})
    for i in range(0, len(items), SITE_PAGE_SIZE):
        bucket[i // SITE_PAGE_SIZE + 1] = items[i : i + SITE_PAGE_SIZE]


def _hydrate_from_disk(spec: dict[str, str]) -> dict[str, Any] | None:
    try:
        from .jable_index import seed_order

        seed_order(spec)
    except Exception:
        pass
    cached = _read_list_json(spec["path"], spec["term"])
    if cached:
        hint = int(cached.get("total_hint") or cached.get("total") or 0)
        items = _public_items(cached, 240)
        return _pack_list(
            spec,
            items,
            cached=True,
            total_hint=hint,
            total=max(hint, len(items)),
            index_pages=False,
        )
    return _LIST_MEM.get(_mem_key(spec))


def _fetch_site_page(spec: dict[str, str], site_page: int) -> list[dict[str, Any]]:
    from jable_hot import RateGate, fetch_list_page, list_url, parse_items, parse_total

    site_page = max(1, int(site_page or 1))
    model = spec.get("kind") == "model"
    url = list_url(
        spec["path"],
        spec["term"],
        site_page,
        async_mode=not model,
        block_id=spec["block_id"],
    )
    if model and site_page == 1:
        # A user-opened actor must not wait behind the background crawler backoff.
        from jable_http import fetch_html
        from jable_user import looks_like_model_page

        html, _ = fetch_html(url, timeout=12, retries=1, validate=looks_like_model_page, priority=True)
    else:
        html = fetch_list_page(url, RateGate(0.0), timeout=12, retries=2)
    if model:
        try:
            from jable_user import looks_like_model_page

            if not looks_like_model_page(html):
                return []
        except Exception:
            if "/models/" not in (html or "") or "title-with-avatar" not in (html or ""):
                return []
        _learn_model_title(spec.get("slug") or "", html)
    rows = parse_items(html) or []
    total = parse_total(html) or 0
    if total:
        meta = _LIST_META.setdefault(_mem_key(spec), {})
        meta["total"] = max(int(meta.get("total") or 0), total)
    chunk = _public_items({"items": rows}, SITE_PAGE_SIZE)
    if chunk and _is_wrap_chunk(spec, site_page, chunk):
        return []
    if spec.get("kind") == "model":
        chunk = _stamp_model_items(spec, chunk)
    if chunk:
        _save_site_page(spec, site_page, chunk)
        try:
            from .jable_index import extend_order_from_disk, ingest_works, prefetch_covers

            ingest_works(chunk)
            extend_order_from_disk(spec)
            threading.Thread(target=prefetch_covers, args=(chunk, 24), daemon=True).start()
        except Exception:
            pass
    return chunk


def _prefetch_neighbor(spec: dict[str, str], page: int) -> None:
    if spec.get("kind") == "model":
        _ensure_model_pages(spec)
    try:
        from .jable_index import display_len

        if display_len(spec) >= (max(1, int(page or 1)) + 1) * PAGE_SIZE:
            return
    except Exception:
        pass
    offset = (max(1, int(page or 1)) - 1) * PAGE_SIZE
    site_page = offset // SITE_PAGE_SIZE + 1
    try:
        _site_page_items(spec, site_page + 1)
    except Exception:
        pass


def _load_site_page_file(spec: dict[str, str], site_page: int) -> list[dict[str, Any]]:
    path = _pages_dir(spec) / f"{int(site_page)}.json"
    if not path.is_file():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return rows if isinstance(rows, list) else []


def _read_one_site_page(spec: dict[str, str], site_page: int) -> list[dict[str, Any]]:
    rows = _load_site_page_file(spec, site_page)
    if spec.get("kind") == "model":
        return _stamp_model_items(spec, rows)
    return rows


def _model_pages_are_sane(spec: dict[str, str]) -> bool:
    if spec.get("kind") != "model":
        return True
    raw = _load_site_page_file(spec, 1)
    if not raw:
        return True
    name = _model_title(spec.get("slug") or "")
    if not name or name in {"演员", "女優", "女优"}:
        return True
    return _chunk_belongs_to_model(spec, raw)


def _ids_of(rows: list[dict[str, Any]]) -> list[str]:
    return [str(x.get("id") or x.get("code") or "").strip().lower() for x in rows or []]


def _stamp_model_items(spec: dict[str, str], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if spec.get("kind") != "model" or not items:
        return items
    slug = (spec.get("slug") or "").strip()
    if not slug:
        return items
    title = _spec_title(spec)
    try:
        from jable_hot import good_actor_name
    except Exception:
        good_actor_name = lambda text: bool(str(text or "").strip())  # noqa: E731
    label = title if title and title not in {"演员", "女優", "女优"} and good_actor_name(title) else ""
    if not label or _HEX_SLUG_RE.fullmatch(label):
        return items
    me = {"name": label, "slug": slug}
    out: list[dict[str, Any]] = []
    for row in items:
        item = dict(row)
        actors: list[dict[str, str]] = []
        for raw in item.get("actors") or []:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name or not good_actor_name(name):
                continue
            actors.append({"name": name, "slug": str(raw.get("slug") or "").strip()})
        prefix = label[:2] if re.search(r"[\u4e00-\u9fff\u3040-\u30ff]", label) else ""

        def same_person(actor: dict[str, str]) -> bool:
            if actor.get("slug") == slug or actor.get("name") == label:
                return True
            other = actor.get("name") or ""
            return bool(prefix and other.startswith(prefix))

        rest = [a for a in actors if not same_person(a)]
        item["actors"] = [me] + rest[:3]
        out.append(item)
    return out


def _model_aliases(spec: dict[str, str]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        name = unescape((text or "").strip())
        if not name or name in seen or _HEX_SLUG_RE.fullmatch(name):
            return
        if name in {"演员", "女優", "女优"}:
            return
        compact = re.sub(r"\s", "", name)
        if not (2 <= len(compact) <= 16):
            return
        seen.add(name)
        names.append(name)

    add(_model_title(spec.get("slug") or ""))
    add(spec.get("title") or "")
    slug = (spec.get("slug") or "").strip().lower()
    first = _load_site_page_file(spec, 1)
    blob = " ".join(str(row.get("title") or "") for row in first)
    for row in first:
        for actor in row.get("actors") or []:
            if not isinstance(actor, dict):
                continue
            name = str(actor.get("name") or "").strip()
            actor_slug = str(actor.get("slug") or "").strip().lower()
            if slug and actor_slug == slug:
                add(name)
            elif name and blob.count(name) >= 3:
                add(name)
    return names


def _chunk_belongs_to_model(spec: dict[str, str], chunk: list[dict[str, Any]]) -> bool:
    if spec.get("kind") != "model" or not chunk:
        return True
    slug = (spec.get("slug") or "").strip().lower()
    aliases = _model_aliases(spec)
    if not slug and not aliases:
        return True
    hits = 0
    for row in chunk:
        blob_parts = [str(row.get("title") or "")]
        has_slug = False
        for actor in row.get("actors") or []:
            if not isinstance(actor, dict):
                continue
            if slug and str(actor.get("slug") or "").strip().lower() == slug:
                has_slug = True
            blob_parts.append(str(actor.get("name") or ""))
        blob = " ".join(blob_parts)
        if has_slug:
            hits += 1
            continue
        for alias in aliases:
            if not alias:
                continue
            if alias in blob:
                hits += 1
                break
            compact = re.sub(r"\s", "", alias)
            if len(compact) >= 2 and re.search(r"[\u4e00-\u9fff\u3040-\u30ff]", compact) and compact[:2] in blob:
                hits += 1
                break
    return hits >= max(1, (len(chunk) + 3) // 4)


def _ids_match_catalog(ids: list[str]) -> bool:
    if len(ids) < 8:
        return False
    for kind in ("hot", "latest"):
        try:
            head = _ids_of(_read_one_site_page(_resolve_list(kind, "", ""), 1))
        except Exception:
            head = []
        if len(head) >= 8 and ids[:8] == head[:8]:
            return True
    return False


def _is_wrap_chunk(spec: dict[str, str], site_page: int, chunk: list[dict[str, Any]]) -> bool:
    if not chunk:
        return True
    ids = _ids_of(chunk)
    if not ids:
        return True
    if spec.get("kind") == "model" and site_page > 1 and _ids_match_catalog(ids):
        return True
    if site_page <= 1:
        return False
    first = _load_site_page_file(spec, 1)
    if first:
        head = _ids_of(first)
        if head and ids[0] == head[0] and ids[-1] == head[-1]:
            return True
    prev = _load_site_page_file(spec, site_page - 1)
    if prev and _ids_of(prev) == ids:
        return True
    last_n = _max_site_page(spec)
    if last_n and last_n != site_page:
        last = _load_site_page_file(spec, last_n)
        if last and _ids_of(last) == ids:
            return True
    if spec.get("kind") == "model" and not _chunk_belongs_to_model(spec, chunk):
        return True
    return False


def _max_site_page(spec: dict[str, str]) -> int:
    folder = _pages_dir(spec)
    max_p = 0
    if folder.is_dir():
        for path in folder.glob("*.json"):
            try:
                max_p = max(max_p, int(path.stem))
            except ValueError:
                continue
    return max_p


def _cached_item_count(spec: dict[str, str]) -> int:
    n = 0
    try:
        from .jable_index import order_len

        n = max(n, int(order_len(spec) or 0))
    except Exception:
        pass
    return max(n, _max_site_page(spec) * SITE_PAGE_SIZE)


def resolve_list_total(meta_total: int, order_hint: int, known: int) -> int:
    """站点声明的部数优先；本地已抓条数只作下限，不能拿一页缓存盖掉总数。"""
    return max(int(meta_total or 0), int(order_hint or 0), int(known or 0))


def _declared_total(spec: dict[str, str], meta: dict[str, Any], known: int) -> int:
    hint = 0
    try:
        from .jable_index import order_total_hint

        hint = int(order_total_hint(spec) or 0)
    except Exception:
        hint = 0
    return resolve_list_total(int((meta or {}).get("total") or 0), hint, known)


def _allowed_site_pages(spec: dict[str, str]) -> int:
    """How many site pages the list is allowed to have. 0 = unknown."""
    total = _declared_total(spec, _LIST_META.get(_mem_key(spec)) or {}, 0)
    if total > 0:
        return max(1, (total + SITE_PAGE_SIZE - 1) // SITE_PAGE_SIZE)
    return 0


def _site_page_items(spec: dict[str, str], site_page: int) -> list[dict[str, Any]]:
    key = _mem_key(spec)
    bucket = _LIST_SITE.setdefault(key, {})
    disk = _read_one_site_page(spec, site_page)
    if disk:
        bucket[site_page] = disk
        return disk
    allowed = _allowed_site_pages(spec)
    if allowed and site_page > allowed:
        return []
    max_p = _max_site_page(spec)
    if not allowed and max_p and site_page > max_p + 1:
        return []
    if site_page in bucket and bucket[site_page]:
        if _is_wrap_chunk(spec, site_page, bucket[site_page]):
            bucket.pop(site_page, None)
        else:
            return bucket[site_page]
    try:
        chunk = _fetch_site_page(spec, site_page)
    except (SystemExit, Exception):
        chunk = []
    if chunk and _is_wrap_chunk(spec, site_page, chunk):
        return []
    if chunk:
        bucket[site_page] = chunk
    return chunk


def _ui_page_items(spec: dict[str, str], page: int) -> list[dict[str, Any]]:
    page = max(1, int(page or 1))
    offset = (page - 1) * PAGE_SIZE
    kind = spec.get("kind") or ""
    catalog = kind in _CATALOG_KINDS
    rows: list[dict[str, Any]] = []
    try:
        from .jable_index import display_len, items_for_ui_page, order_len

        rows = items_for_ui_page(spec, page, PAGE_SIZE) or []
        n = int(display_len(spec) or 0)
        try:
            order_n = int(order_len(spec) or 0)
        except Exception:
            order_n = 0
        got = len(rows)
        if got == PAGE_SIZE:
            return rows
        if rows and (offset + got >= n or (order_n and offset + got >= order_n)):
            return rows
        if catalog:
            return rows
    except Exception:
        if catalog:
            return rows

    site_page = offset // SITE_PAGE_SIZE + 1
    start = offset % SITE_PAGE_SIZE
    if kind in _PAGED_KINDS:
        disk = _read_one_site_page(spec, site_page)
        if disk:
            return disk[start : start + PAGE_SIZE]
    elif catalog:
        return rows
    fetched = _site_page_items(spec, site_page)
    return fetched[start : start + PAGE_SIZE]


def _paged(data: dict[str, Any], page: int, page_size: int = PAGE_SIZE) -> dict[str, Any]:
    items = list(data.get("items") or [])
    page = max(1, int(page or 1))
    total = max(int(data.get("total") or data.get("total_hint") or 0), len(items))
    page_count = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    start = (page - 1) * PAGE_SIZE
    out = dict(data)
    out["items"] = items[start : start + PAGE_SIZE]
    out["page"] = page
    out["page_size"] = PAGE_SIZE
    out["total"] = total
    out["page_count"] = page_count
    out["has_more"] = page < page_count
    return out


def _crawl_named_list(spec: dict[str, str], pages: int, force: bool) -> dict[str, Any]:
    try:
        payload = crawl_one(
            path=spec["path"],
            term=spec["term"],
            label=spec["title"],
            pages=pages,
            extra={
                "scope": spec["kind"],
                "slug": spec.get("slug") or "",
                "year": spec.get("year") or "",
                "month": spec.get("month") or "",
            },
            force=force,
            block_id=spec["block_id"],
            cache_ttl=10**9,
        )
    except (SystemExit, Exception):
        payload = {"items": []}
    hint = int((payload or {}).get("total_hint") or 0)
    return _pack_list(spec, _public_items(payload, 10000), total_hint=hint, total=hint)


def _refresh_list_bg(spec: dict[str, str], pages: int) -> None:
    lock = _lock_for(spec)
    if not lock.acquire(blocking=False):
        return
    try:
        _LIST_SEM.acquire()
        try:
            _crawl_named_list(spec, pages, force=False)
        finally:
            _LIST_SEM.release()
    except Exception:
        pass
    finally:
        lock.release()


def _disk_page_codes(spec: dict[str, str]) -> dict[str, list[str]]:
    pages: dict[str, list[str]] = {}
    folder = _pages_dir(spec)
    if not folder.is_dir():
        return pages
    for path in folder.glob("*.json"):
        try:
            num = int(path.stem)
        except ValueError:
            continue
        ids: list[str] = []
        for row in _read_one_site_page(spec, num) or []:
            code = str(row.get("id") or row.get("code") or "").strip().lower()
            if code:
                ids.append(code)
        if ids:
            pages[str(num)] = ids
    return pages


def _ensure_model_pages(spec: dict[str, str]) -> None:
    if spec.get("kind") != "model":
        return
    key = _mem_key(spec)
    with _MODEL_FILL_MU:
        if key in _MODEL_FILLING:
            return
        _MODEL_FILLING.add(key)

    def work() -> None:
        try:
            _fill_model_pages(spec)
        except Exception:
            pass
        finally:
            with _MODEL_FILL_MU:
                _MODEL_FILLING.discard(key)

    threading.Thread(target=work, daemon=True, name=f"model-fill-{spec.get('slug') or ''}").start()


def _fill_model_pages(spec: dict[str, str]) -> None:
    extend_order_from_disk = None
    ingest_works = None
    try:
        from .jable_index import extend_order_from_disk as _extend
        from .jable_index import ingest_works as _ingest
        from .jable_index import seed_order

        extend_order_from_disk = _extend
        ingest_works = _ingest
        seed_order(spec)
    except Exception:
        pass
    have: set[int] = set()
    folder = _pages_dir(spec)
    if folder.is_dir():
        for path in folder.glob("*.json"):
            try:
                have.add(int(path.stem))
            except ValueError:
                continue
    total = _declared_total(spec, _LIST_META.get(_mem_key(spec)) or {}, 0)
    if not total or 1 not in have:
        try:
            chunk = _site_page_items(spec, 1)
        except Exception:
            chunk = []
        if chunk:
            have.add(1)
        total = _declared_total(spec, _LIST_META.get(_mem_key(spec)) or {}, 0)
    if total <= 0:
        return
    n_pages = max(1, (total + SITE_PAGE_SIZE - 1) // SITE_PAGE_SIZE)
    missing = [p for p in range(1, n_pages + 1) if p not in have]
    if not missing:
        if extend_order_from_disk:
            try:
                extend_order_from_disk(spec)
            except Exception:
                pass
        return
    try:
        from .jable_index import _fetch_site_batch
    except Exception:
        _fetch_site_batch = None  # type: ignore[assignment]
    i = 0
    while i < len(missing):
        batch = missing[i : i + 2]
        i += len(batch)
        try:
            from jable_http import wait_rate_limit

            wait_rate_limit()
        except Exception:
            pass
        got: dict[int, list[dict[str, Any]]] = {}
        if _fetch_site_batch:
            try:
                got = _fetch_site_batch(spec, batch, workers=2) or {}
            except Exception:
                got = {}
        for page in batch:
            chunk = got.get(page) or []
            if not chunk:
                try:
                    chunk = _fetch_site_page(spec, page)
                except Exception:
                    chunk = []
            if not chunk or _is_wrap_chunk(spec, page, chunk):
                continue
            _save_site_page(spec, page, chunk)
            _LIST_SITE.setdefault(_mem_key(spec), {})[page] = chunk
            if ingest_works:
                try:
                    ingest_works(chunk)
                except Exception:
                    pass
        if extend_order_from_disk:
            try:
                extend_order_from_disk(spec)
            except Exception:
                pass
        time.sleep(0.25)


_PREFETCH_STARTED = False


def _prefetch_hot_ranges() -> None:
    global _PREFETCH_STARTED
    if _PREFETCH_STARTED:
        return
    _PREFETCH_STARTED = True

    def work() -> None:
        for kind in ("week", "month"):
            spec = _resolve_list(kind, "", "")
            if _read_list_json(spec["path"], spec["term"]):
                continue
            try:
                _crawl_named_list(spec, 2, force=False)
            except Exception:
                pass

    threading.Thread(target=work, daemon=True).start()


_WARMUP_STARTED = False


def warmup_lists(limit_workers: int = 10) -> None:
    global _WARMUP_STARTED
    if _WARMUP_STARTED:
        return
    _WARMUP_STARTED = True

    def work() -> None:
        try:
            from jable_pick import GROUPS

            specs: list[dict[str, str]] = []
            seen: set[str] = set()

            def add(spec: dict[str, str]) -> None:
                key = _mem_key(spec)
                if key in seen:
                    return
                seen.add(key)
                specs.append(spec)

            for kind in ("latest", "hot", "week", "month", "all", "type"):
                add(_resolve_list(kind, "", ""))
            for slug, _name in DEFAULT_CATEGORIES:
                add(_resolve_list("cat", slug, ""))
            for tags in GROUPS.values():
                for _name, slug in tags:
                    add(_resolve_list("tag", slug, ""))
            for year in range(2026, 2019, -1):
                add(_resolve_list("latest", "", "", year=str(year)))

            need: list[dict[str, str]] = []
            for spec in specs:
                mem = _LIST_MEM.get(_mem_key(spec))
                meta = _LIST_META.get(_mem_key(spec)) or {}
                if mem and mem.get("items") and int(meta.get("total") or 0) > SITE_PAGE_SIZE * 2:
                    continue
                disk = _read_list_json(spec["path"], spec["term"])
                if disk:
                    hint = int(disk.get("total_hint") or disk.get("total") or 0)
                    items = _public_items(disk, 10000)
                    _pack_list(
                        spec,
                        items,
                        cached=True,
                        total_hint=hint,
                        total=max(hint, len(items)),
                    )
                    continue
                need.append(spec)
            if not need:
                return

            def one(spec: dict[str, str]) -> None:
                try:
                    _crawl_named_list(spec, 1, force=False)
                except Exception:
                    pass

            workers = max(1, int(limit_workers or 10))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [pool.submit(one, spec) for spec in need]
                for fut in futs:
                    try:
                        fut.result()
                    except Exception:
                        pass
        except Exception:
            pass

    threading.Thread(target=work, daemon=True).start()


_SNAP_CACHE: dict[str, tuple[int, dict[str, Any], bytes]] = {}


def list_snapshot(
    *,
    kind: str = "latest",
    slug: str = "",
    term: str = "",
    year: str = "",
    month: str = "",
) -> dict[str, Any]:
    spec = _resolve_list(kind, slug, term, year, month)
    _ensure_model_title(spec)
    from .jable_index import compact_cards, display_codes, display_len, order_len, seed_order

    if order_len(spec) < 256 or spec.get("kind") == "model":
        seed_order(spec)
        if spec.get("kind") == "model" and not _model_pages_are_sane(spec):
            _ensure_model_pages(spec)
    codes = display_codes(spec)
    key = _mem_key(spec)
    known = max(len(codes), int(display_len(spec) or 0))
    total = _declared_total(spec, _LIST_META.get(key) or {}, known)
    kind_name = spec.get("kind") or ""
    pages: dict[str, list[str]] = {}
    if kind_name in {"tag", "cat"}:
        try:
            from .jable_tag_cache import prioritize_spec, spec_page_codes

            prioritize_spec(spec)
            pages = spec_page_codes(spec)
        except Exception:
            pages = {}
    elif kind_name == "model":
        pages = _disk_page_codes(spec)
        _ensure_model_pages(spec)
    stamp = (len(codes), total, len(pages))
    hit = _SNAP_CACHE.get(key)
    if hit and hit[0] == stamp and hit[1].get("codes") is not None:
        return hit[1]
    if kind_name in {"tag", "cat"} and len(codes) > 480:
        cards = compact_cards(codes[:240])
    else:
        cards = compact_cards(codes)
    total = max(total, len(codes), len(cards))
    data = {
        "title": _spec_title(spec),
        "kind": spec["kind"],
        "slug": spec.get("slug") or "",
        "term": spec["term"],
        "year": spec.get("year") or "",
        "month": spec.get("month") or "",
        "page_size": PAGE_SIZE,
        "total": total,
        "page_count": max(1, (max(total, 1) + PAGE_SIZE - 1) // PAGE_SIZE),
        "codes": codes,
        "cards": cards,
        "cover_bases": [
            "https://assets-cdn.jable.tv",
            "https://static-assets-cdn.jable.tv",
        ],
    }
    if pages:
        data["pages"] = pages
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    _SNAP_CACHE[key] = (stamp, data, raw)
    return data


def list_snapshot_bytes(
    *,
    kind: str = "latest",
    slug: str = "",
    term: str = "",
    year: str = "",
    month: str = "",
) -> bytes:
    data = list_snapshot(kind=kind, slug=slug, term=term, year=year, month=month)
    spec = _resolve_list(kind, slug, term, year, month)
    key = _mem_key(spec)
    hit = _SNAP_CACHE.get(key)
    if hit and hit[2]:
        return hit[2]
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def list_feed(
    *,
    kind: str = "latest",
    slug: str = "",
    term: str = "",
    year: str = "",
    month: str = "",
    pages: int = 1,
    page: int = 1,
    page_size: int = PAGE_SIZE,
    force: bool = False,
) -> dict[str, Any]:
    spec = _resolve_list(kind, slug, term, year, month)
    _ensure_model_title(spec)
    if spec.get("kind") == "model":
        _ensure_model_pages(spec)
        if not force:
            from .jable_page import page_feed

            return page_feed(kind=kind, slug=slug, term=term, year=year, month=month, page=page)
    page = max(1, int(page or 1))
    key = _mem_key(spec)
    if force:
        data = _crawl_named_list(spec, max(1, (page + 1) // 2), force=True)
        chunk = _ui_page_items(spec, page)
        out = _paged(data, page)
        if chunk:
            out["items"] = chunk
        return out

    mem = _LIST_MEM.get(key)
    meta = _LIST_META.get(key) or {}
    have_mem = bool((mem and mem.get("items")) or (_LIST_SITE.get(key) or {}))
    have_hint = int(meta.get("total") or 0) > SITE_PAGE_SIZE * 2
    if not have_mem or not have_hint:
        _hydrate_from_disk(spec)
        meta = _LIST_META.get(key) or {}
    total = int(meta.get("total") or 0)
    known = 0
    try:
        from .jable_index import display_len, seed_order

        seed_order(spec)
        if spec.get("kind") == "model" and not _model_pages_are_sane(spec):
            try:
                _fetch_site_page(spec, 1)
                seed_order(spec)
            except Exception:
                pass
        known = int(display_len(spec) or 0)
    except Exception:
        try:
            from .jable_index import order_len

            known = int(order_len(spec) or 0)
        except Exception:
            known = 0
    if known < PAGE_SIZE:
        known = max(known, _cached_item_count(spec))
    meta = _LIST_META.get(key) or {}
    total = _declared_total(spec, meta, known)
    page_count = max(1, (max(total, 1) + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > page_count:
        page = page_count

    chunk: list[dict[str, Any]] = []
    try:
        chunk = _ui_page_items(spec, page)
    except (SystemExit, Exception):
        chunk = []
    if spec.get("kind") == "model":
        chunk = _stamp_model_items(spec, chunk)

    page_count = max(1, (max(total, 1) + PAGE_SIZE - 1) // PAGE_SIZE)
    if spec["kind"] in _CATALOG_KINDS:
        if spec["kind"] in {"hot", "type"}:
            _prefetch_hot_ranges()
        threading.Thread(target=_prefetch_neighbor, args=(spec, page), daemon=True).start()
        return {
            "title": _spec_title(spec),
            "kind": spec["kind"],
            "slug": spec.get("slug") or "",
            "term": spec["term"],
            "year": spec.get("year") or "",
            "month": spec.get("month") or "",
            "items": chunk,
            "page": page,
            "page_size": PAGE_SIZE,
            "total": total,
            "page_count": page_count,
            "has_more": page < page_count,
            "cached": True,
        }

    if not total:
        if spec["kind"] != "model":
            threading.Thread(target=_refresh_list_bg, args=(spec, 1), daemon=True).start()
        if spec["kind"] in {"hot", "type"}:
            _prefetch_hot_ranges()
        fallback = chunk or (
            []
            if spec["kind"] in {"cat", "tag", "model", "week", "month", "all"} or spec.get("year") or spec.get("month")
            else _fallback_home_items(spec["kind"])
        )
        total = int((_LIST_META.get(key) or {}).get("total") or len(fallback))
        page_count = max(1, (max(total, 1) + PAGE_SIZE - 1) // PAGE_SIZE)
        return {
            "title": _spec_title(spec),
            "kind": spec["kind"],
            "slug": spec.get("slug") or "",
            "term": spec["term"],
            "year": spec.get("year") or "",
            "month": spec.get("month") or "",
            "items": fallback[:PAGE_SIZE] if page == 1 else chunk,
            "page": page,
            "page_size": PAGE_SIZE,
            "total": total,
            "page_count": page_count,
            "has_more": page < page_count,
            "pending": not total or (spec["kind"] == "model" and not fallback and not chunk),
            "cached": False,
        }

    if spec["kind"] in {"hot", "type"}:
        _prefetch_hot_ranges()
    threading.Thread(target=_prefetch_neighbor, args=(spec, page), daemon=True).start()
    start = (page - 1) * PAGE_SIZE
    pending = (not chunk) and start < total
    return {
        "title": _spec_title(spec),
        "kind": spec["kind"],
        "slug": spec.get("slug") or "",
        "term": spec["term"],
        "year": spec.get("year") or "",
        "month": spec.get("month") or "",
        "items": chunk,
        "page": page,
        "page_size": PAGE_SIZE,
        "total": total,
        "page_count": page_count,
        "has_more": page < page_count,
        "pending": pending,
        "cached": bool(chunk) or not pending,
    }


_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,40}$")
_PLAY_MEM: dict[str, dict[str, Any]] = {}
_PLAY_LOCK = threading.Lock()
_PLAY_TTL = 240.0


def play_cached(code: str) -> dict[str, Any] | None:
    """Return in-memory play info if HLS is still fresh. No network."""
    raw = (code or "").strip().lower()
    if not raw:
        return None
    now = time.time()
    with _PLAY_LOCK:
        hit = _PLAY_MEM.get(raw)
        if not hit or now - float(hit.get("ts") or 0) >= _PLAY_TTL:
            return None
        data = hit.get("data") or {}
        hls = str(data.get("hls") or "")
        if not hls:
            return None
        out = dict(data)
        out["cached"] = True
        return out


def forget_play(code: str) -> None:
    raw = (code or "").strip().lower()
    if not raw:
        return
    with _PLAY_LOCK:
        _PLAY_MEM.pop(raw, None)


def remember_play_html(key: str, url: str, html: str) -> None:
    """从已抓到的作品页 HTML 解析 var hlsUrl，写入播放缓存。"""
    from jable_hls import parse_page

    raw = (key or "").strip().lower()
    if not raw or not html:
        return
    page_url = url or f"https://jable.tv/videos/{raw}/"
    try:
        meta = parse_page(page_url, html, require_cover=False)
    except SystemExit:
        return
    hls = meta.get("hls") or ""
    if not hls:
        return
    data = {
        "id": meta.get("code") or raw,
        "title": meta.get("title") or meta.get("code") or raw,
        "url": meta.get("url") or page_url,
        "cover": meta.get("cover") or "",
        "hls": hls,
        "expires_at": meta.get("expires_at") or "",
        "related": [],
    }
    with _PLAY_LOCK:
        _PLAY_MEM[raw] = {"ts": time.time(), "data": data}


def _play_related(current: str) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    cached = _HOME_CACHE.get("data") or {}
    seen: set[str] = set()
    cur = str(current or "").lower()
    for bucket in (cached.get("hot") or {}, cached.get("latest") or {}):
        for item in bucket.get("items") or []:
            iid = str(item.get("id") or "").lower()
            if not iid or iid == cur or iid in seen:
                continue
            seen.add(iid)
            related.append(item)
            if len(related) >= 12:
                return related
    return related


def play_info(code: str) -> dict[str, Any]:
    from jable_hls import normalize_url, parse_page

    raw = (code or "").strip()
    if not raw:
        raise RuntimeError("缺少番号")
    key = raw.lower()
    cached = play_cached(key)
    if cached:
        out = dict(cached)
        if not out.get("related"):
            out["related"] = _play_related(out.get("id") or key)
        out["cached"] = True
        return out
    try:
        from .jable_inspect import fetch_video_html

        url = normalize_url(raw)
        html = fetch_video_html(key, need_hls=True)
        meta = parse_page(url, html, require_cover=False)
    except SystemExit as exc:
        raise RuntimeError("无法解析该作品（站点拦截或网络失败）") from exc
    except RuntimeError as exc:
        text = str(exc) or ""
        if "1015" in text or "rate limited" in text.lower():
            raise RuntimeError("站点限流（Cloudflare 1015），已暂停后台抓取，请几分钟后再播完整视频") from exc
        raise RuntimeError("无法解析该作品（站点拦截或网络失败）") from exc
    data = {
        "id": meta.get("code") or raw,
        "title": meta.get("title") or meta.get("code") or raw,
        "url": meta.get("url") or "",
        "cover": meta.get("cover") or "",
        "hls": meta.get("hls") or "",
        "expires_at": meta.get("expires_at") or "",
        "related": _play_related(meta.get("code") or raw),
        "cached": False,
    }
    with _PLAY_LOCK:
        _PLAY_MEM[key] = {"ts": time.time(), "data": dict(data)}
    return dict(data)


def run_hot(opts: dict[str, Any], log: LogFn | None = None) -> dict[str, Any]:
    from jable_hot import TERMS, list_path

    term = str(opts.get("term") or "video_viewed_today")
    if term not in TERMS:
        term = "video_viewed_today"
    category = str(opts.get("category") or "").strip().lower()
    pages = int(opts.get("pages") or 2)
    if category:
        cats = {slug: name for slug, name in DEFAULT_CATEGORIES}
        name = cats.get(category, category)
        path = list_path("categories", category)
        label = f"{name}/{TERMS[term]}"
        extra = {"scope": "categories", "slug": category, "category": name}
        url = f"https://jable.tv{path}?sort_by={term}"
    else:
        path = "/hot/"
        label = f"熱門/{TERMS[term]}"
        extra = {"scope": "hot"}
        url = f"https://jable.tv/hot/?sort_by={term}"
    payload = crawl_one(
        path=path,
        term=term,
        label=label,
        pages=pages,
        log=log,
        extra=extra,
    )
    payload["browse_title"] = label
    payload["browse_url"] = url
    return payload


def run_pick(opts: dict[str, Any], log: LogFn | None = None) -> dict[str, Any]:
    from jable_hot import TERMS
    from jable_pick import GROUPS, PICK_TERMS, build_jobs, pick_tags, resolve_group

    group = str(opts.get("group") or "衣著").strip()
    if group not in GROUPS and group not in {
        "按主題",
        "按女優",
        "新片優先",
        "熱度優先",
    }:
        try:
            group = resolve_group(group) or "衣著"
        except SystemExit:
            group = "衣著"
    tag = str(opts.get("tag") or "").strip()
    model = str(opts.get("model") or "").strip()
    pages = int(opts.get("pages") or 2)
    term = str(opts.get("term") or "")
    hot = group == "熱度優先"
    if hot:
        if term not in TERMS:
            term = "video_viewed_today"
        terms = [term]
    else:
        if term not in PICK_TERMS:
            term = "post_date_and_popularity" if group != "新片優先" else "post_date"
        if group == "新片優先":
            term = "post_date"
        terms = [term]
    tags: list[dict[str, str]] = []
    theme_cats = [{"slug": slug, "name": name} for slug, name in DEFAULT_CATEGORIES]
    if group in GROUPS:
        if not tag:
            raise RuntimeError("请选择選片子类")
        tags = pick_tags(group, tag)
    elif group == "按主題":
        if not tag:
            raise RuntimeError("请选择主题分类")
        theme_cats = [c for c in theme_cats if c["slug"] == tag or c["name"] == tag] or theme_cats
    elif group == "按女優":
        if not model:
            raise RuntimeError("按女優请输入用户名或 slug，例如 yua-mikami")
    jobs = build_jobs(
        group=group,
        tags=tags,
        terms=terms,
        model=model,
        theme_cats=theme_cats,
    )
    if not jobs:
        raise RuntimeError("没有可解析的選片列表，请选择大类/子类")
    job = jobs[0]
    payload = crawl_one(
        path=job["path"],
        term=job["term"],
        label=job["label"],
        pages=pages,
        log=log,
        block_id=job.get("block_id") or "list_videos_common_videos_list",
        extra=job.get("extra"),
    )
    payload["browse_title"] = job["label"]
    payload["browse_url"] = f"https://jable.tv{job['path']}"
    return payload
