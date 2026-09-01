# -*- coding: utf-8 -*-
"""抓取 jable.tv 熱門影片四个时间档，以及全部主题分类下的全部作品。

对应页面：https://jable.tv/hot/
时间档：所有時間 / 本月熱門 / 本週熱門 / 今日熱門
主题分类：https://jable.tv/categories/ 共 12 个
"""
from __future__ import annotations

import argparse
import math
import re
import sys
import threading
import time
from collections import deque
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from jable_http import DEFAULT_REFERER, fetch_html, fetch_many, is_cloudflare, note_rate_limit, warmup
from jable_util import (
    BASE,
    DEFAULT_OUT,
    append_jsonl,
    configure_stdio,
    die,
    iter_jsonl,
    launched_bare,
    now_iso,
    print_intro,
    prompt_line,
    unescape_text,
    write_csv,
    write_json,
)

# jable_http has no BASE; keep local BASE from util.

TERMS: dict[str, str] = {
    "video_viewed": "所有時間",
    "video_viewed_month": "本月熱門",
    "video_viewed_week": "本週熱門",
    "video_viewed_today": "今日熱門",
}
TERM_ORDER = (
    "video_viewed",
    "video_viewed_month",
    "video_viewed_week",
    "video_viewed_today",
)
TERM_ALIASES = {
    "all": "all",
    "全部": "all",
    "全": "all",
    "video_viewed": "video_viewed",
    "alltime": "video_viewed",
    "all-time": "video_viewed",
    "所有時間": "video_viewed",
    "所有时间": "video_viewed",
    "总": "video_viewed",
    "總": "video_viewed",
    "video_viewed_month": "video_viewed_month",
    "month": "video_viewed_month",
    "monthly": "video_viewed_month",
    "本月": "video_viewed_month",
    "本月熱門": "video_viewed_month",
    "本月热门": "video_viewed_month",
    "月": "video_viewed_month",
    "video_viewed_week": "video_viewed_week",
    "week": "video_viewed_week",
    "weekly": "video_viewed_week",
    "本週": "video_viewed_week",
    "本周": "video_viewed_week",
    "本週熱門": "video_viewed_week",
    "本周热门": "video_viewed_week",
    "周": "video_viewed_week",
    "週": "video_viewed_week",
    "video_viewed_today": "video_viewed_today",
    "today": "video_viewed_today",
    "daily": "video_viewed_today",
    "今日": "video_viewed_today",
    "今日熱門": "video_viewed_today",
    "今日热门": "video_viewed_today",
    "日": "video_viewed_today",
}

BOX_SPLIT_RE = re.compile(r'<div class="video-img-box\b', re.I)
VIDEO_HREF_RE = re.compile(r'href="(https://jable\.tv/videos/([^"/]+)/)"', re.I)
COVER_RE = re.compile(r'data-src="([^"]+)"', re.I)
PREVIEW_RE = re.compile(r'data-preview="([^"]+)"', re.I)
FAV_RE = re.compile(r'data-fav-video-id="(\d+)"', re.I)
DURATION_RE = re.compile(r'<span class="label">([^<]+)</span>', re.I)
TITLE_RE = re.compile(r'<h6 class="title">\s*<a href="[^"]+">([^<]+)</a>', re.I | re.S)
VIEWS_RE = re.compile(r'#icon-eye"></use></svg>\s*([0-9][0-9 \u00a0]*)', re.I)
LIKES_RE = re.compile(r'#icon-heart-inline"></use></svg>\s*([0-9][0-9 \u00a0]*)', re.I)
SHOT_ID_RE = re.compile(r"/videos_screenshots/\d+/(\d+)/")
TOTAL_RE = re.compile(r"([0-9][0-9,]*)\s*部影片")
PAGINATION_RE = re.compile(r'<ul class="pagination">(.*?)</ul>', re.I | re.S)
FROM_RE = re.compile(r"\bfrom:(\d+)")
LAST_RE = re.compile(r"from:(\d+)[^\"']*\"[^>]*>\s*(?:最後|&raquo;|Last)", re.I)
CAT_RE = re.compile(
    r'<a href="(https://jable\.tv/categories/([^"/]+)/)"[^>]*>\s*'
    r'(?:<div class="overlay"></div>\s*)?'
    r"<img[^>]*>\s*<div class=\"absolute-center\">\s*"
    r"<h4>([^<]+)</h4>\s*<span class=\"label\">(\d+)\s*部影片</span>",
    re.I | re.S,
)
CSV_FIELDS = [
    "rank",
    "code",
    "video_id",
    "title",
    "url",
    "cover",
    "preview_jpg",
    "preview",
    "duration",
    "views",
    "likes",
    "term",
    "label",
    "category",
]


def looks_like_list(html: str) -> bool:
    if is_cloudflare(html):
        return False
    return "video-img-box" in html and "/videos/" in html


def looks_like_catalog(html: str) -> bool:
    if is_cloudflare(html):
        return False
    return "/categories/" in html and "<h4>" in html and "部影片" in html


def parse_int_digits(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None
    return int(digits)


def preview_jpg_from_cover(cover: str) -> str:
    match = re.search(r"(https://[^/]+/contents/videos_screenshots/\d+/\d+)/", cover)
    if match:
        return match.group(1) + "/preview.jpg"
    return ""


def parse_items(html: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in BOX_SPLIT_RE.split(html)[1:]:
        href_m = VIDEO_HREF_RE.search(chunk)
        if not href_m:
            continue
        url = href_m.group(1)
        code = href_m.group(2).strip().lower()
        if not code or code in seen:
            continue
        seen.add(code)
        cover_m = COVER_RE.search(chunk)
        preview_m = PREVIEW_RE.search(chunk)
        fav_m = FAV_RE.search(chunk)
        dur_m = DURATION_RE.search(chunk)
        title_m = TITLE_RE.search(chunk)
        views_m = VIEWS_RE.search(chunk)
        likes_m = LIKES_RE.search(chunk)
        cover = cover_m.group(1) if cover_m else ""
        video_id = fav_m.group(1) if fav_m else ""
        if not video_id and cover:
            shot = SHOT_ID_RE.search(cover)
            if shot:
                video_id = shot.group(1)
        items.append(
            {
                "code": code,
                "video_id": video_id,
                "title": unescape_text(title_m.group(1)) if title_m else "",
                "url": url if url.endswith("/") else url + "/",
                "cover": cover,
                "preview_jpg": preview_jpg_from_cover(cover),
                "preview": preview_m.group(1) if preview_m else "",
                "duration": unescape_text(dur_m.group(1)) if dur_m else "",
                "views": parse_int_digits(views_m.group(1) if views_m else ""),
                "likes": parse_int_digits(likes_m.group(1) if likes_m else ""),
            }
        )
    return items


def parse_total(html: str) -> int:
    match = TOTAL_RE.search(html)
    if not match:
        return 0
    return parse_int_digits(match.group(1)) or 0


def parse_last_page(html: str, per_page: int, total: int) -> int:
    pages = 1
    block = ""
    pag = PAGINATION_RE.search(html)
    if pag:
        block = pag.group(1)
        last = LAST_RE.search(block)
        if last:
            pages = max(pages, int(last.group(1)))
        for hit in FROM_RE.findall(block):
            pages = max(pages, int(hit))
    if per_page > 0 and total > 0:
        pages = max(pages, math.ceil(total / per_page))
    return max(1, pages)


def parse_catalog(html: str) -> list[dict[str, Any]]:
    cats: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url, slug, name, count in CAT_RE.findall(html):
        slug = slug.strip().lower()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        cats.append(
            {
                "slug": slug,
                "name": unescape_text(name),
                "count": int(count),
                "url": url if url.endswith("/") else url + "/",
            }
        )
    return cats


def list_path(scope: str, slug: str | None = None) -> str:
    if scope == "hot":
        return "/hot/"
    if not slug:
        die("分类缺少 slug")
    return f"/categories/{slug}/"


def list_url(
    path: str,
    term: str,
    page: int,
    async_mode: bool = True,
    block_id: str = "list_videos_common_videos_list",
) -> str:
    path = "/" + path.strip("/") + "/"
    if async_mode:
        query = {
            "mode": "async",
            "function": "get_block",
            "block_id": block_id,
            "sort_by": term,
            "from": str(page),
            "_": str(int(time.time() * 1000)),
        }
        return f"{BASE}{path}?{urlencode(query)}"
    if page <= 1:
        return f"{BASE}{path}?sort_by={term}"
    return f"{BASE}{path}{page}/?sort_by={term}"


class RateGate:
    def __init__(self, interval: float) -> None:
        self.interval = max(0.0, interval)
        self.lock = threading.Lock()
        self.next_t = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        with self.lock:
            now = time.monotonic()
            delay = self.next_t - now
            self.next_t = max(now, self.next_t) + self.interval
        if delay > 0:
            time.sleep(delay)


def fetch_list_page(url: str, gate: RateGate, timeout: int, retries: int = 5) -> str:
    gate.wait()
    html, _detail = fetch_html(
        url,
        timeout=timeout,
        referer=DEFAULT_REFERER,
        retries=retries,
        validate=looks_like_list,
    )
    return html


def progress_path(out_dir: Path) -> Path:
    return out_dir / "progress.json"


def load_progress(out_dir: Path) -> dict[str, Any]:
    path = progress_path(out_dir)
    if not path.is_file():
        return {"pages_done": 0, "item_count": 0, "total_pages": 0, "per_page": 0}
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"pages_done": 0, "item_count": 0, "total_pages": 0, "per_page": 0}
    if not isinstance(data, dict):
        return {"pages_done": 0, "item_count": 0, "total_pages": 0, "per_page": 0}
    return data


def save_progress(out_dir: Path, payload: dict[str, Any]) -> None:
    write_json(progress_path(out_dir), payload)


def existing_codes(jsonl: Path) -> tuple[list[dict[str, Any]], set[str]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in iter_jsonl(jsonl) or []:
        code = str(row.get("code") or "").lower()
        if not code or code in seen:
            continue
        seen.add(code)
        items.append(row)
    return items, seen


def crawl_list(
    *,
    path: str,
    term: str,
    label: str,
    out_dir: Path,
    sleep: float,
    workers: int,
    timeout: int,
    max_pages: int,
    force: bool,
    formats: set[str],
    extra_meta: dict[str, Any] | None = None,
    block_id: str = "list_videos_common_videos_list",
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "items.jsonl"
    json_path = out_dir / "items.json"
    csv_path = out_dir / "items.csv"
    gate = RateGate(sleep)
    start_page = 1
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    per_page = 0
    total_hint = 0
    total_pages = 0

    if force:
        for leftover in (jsonl_path, json_path, csv_path, progress_path(out_dir)):
            leftover.unlink(missing_ok=True)
    else:
        items, seen = existing_codes(jsonl_path)
        prog = load_progress(out_dir)
        start_page = int(prog.get("pages_done") or 0) + 1
        per_page = int(prog.get("per_page") or 0)
        total_hint = int(prog.get("total_hint") or 0)
        total_pages = int(prog.get("total_pages") or 0)
        if items and start_page == 1:
            start_page = (len(items) // (per_page or 24)) + 1
        if start_page > 1 and not items:
            start_page = 1

    first_code = ""
    first_items: list[dict[str, Any]] = []
    resume = start_page > 1 and per_page > 0 and total_pages > 1
    if resume:
        print(
            f"{label}  续跑 从第 {start_page} 页  已有 {len(items)} 部  共 {total_pages} 页",
            flush=True,
        )
        if items:
            first_code = str(items[0].get("code") or "")
    else:
        page1_url = list_url(path, term, 1, block_id=block_id)
        html1 = fetch_list_page(page1_url, gate, timeout)
        first_items = parse_items(html1)
        if not first_items:
            die(f"列表为空：{page1_url}")
        per_page = per_page or len(first_items)
        total_hint = parse_total(html1) or total_hint
        total_pages = parse_last_page(html1, per_page, total_hint)
        first_code = first_items[0]["code"]
    if max_pages > 0:
        total_pages = min(total_pages, max_pages)

    if start_page <= 1:
        start_page = 1
        if jsonl_path.exists():
            jsonl_path.unlink()
        items = []
        seen = set()
        tagged = []
        for i, rec in enumerate(first_items, start=1):
            if rec["code"] in seen:
                continue
            seen.add(rec["code"])
            row = {"rank": i, **rec}
            items.append(row)
            tagged.append(row)
        append_jsonl(jsonl_path, tagged)
        save_progress(
            out_dir,
            {
                "path": path,
                "term": term,
                "pages_done": 1,
                "item_count": len(items),
                "total_pages": total_pages,
                "total_hint": total_hint,
                "per_page": per_page,
                "fetched_at": now_iso(),
            },
        )
        print(
            f"{label}  第 1/{total_pages} 页  本页 {len(first_items)}  累计 {len(items)}"
            f"  站点声明 {total_hint}",
            flush=True,
        )
        start_page = 2

    if start_page > total_pages:
        payload = finish_list(
            path,
            term,
            label,
            items,
            total_hint,
            total_pages,
            out_dir,
            formats,
            extra_meta,
        )
        return payload

    workers = max(1, workers)
    done_pages: set[int] = set(range(1, start_page))
    contiguous = start_page - 1
    last_print = time.monotonic()
    t_crawl = time.monotonic()
    session_pages = 0

    def dump_progress(force_write: bool = False) -> None:
        if not force_write and session_pages and session_pages % 10 != 0:
            return
        save_progress(
            out_dir,
            {
                "path": path,
                "term": term,
                "pages_done": contiguous,
                "item_count": len(items),
                "total_pages": total_pages,
                "total_hint": total_hint,
                "per_page": per_page,
                "fetched_at": now_iso(),
            },
        )

    def ingest(page: int, chunk: list[dict[str, Any]]) -> None:
        nonlocal contiguous
        if not chunk:
            die(f"{label} 第 {page} 页为空")
        if page > 1 and first_code and chunk[0]["code"] == first_code:
            die(f"{label} 第 {page} 页翻回第 1 页")
        new_rows: list[dict[str, Any]] = []
        for i, rec in enumerate(chunk):
            if rec["code"] in seen:
                continue
            seen.add(rec["code"])
            row = {"rank": (page - 1) * per_page + i + 1, **rec}
            items.append(row)
            new_rows.append(row)
        if new_rows:
            append_jsonl(jsonl_path, new_rows)
        done_pages.add(page)
        while contiguous + 1 in done_pages:
            contiguous += 1

    def report() -> None:
        nonlocal last_print
        now = time.monotonic()
        elapsed = max(now - t_crawl, 0.001)
        pps = session_pages / elapsed
        ips = (session_pages * (per_page or 24)) / elapsed
        remain = (total_pages - contiguous) / pps if pps > 0 else 0
        print(
            f"{label}  {contiguous}/{total_pages} 页  {len(items)} 部  "
            f"{pps:.1f} 页/s  {ips:.0f} 部/s  并发 {conc}  剩余约 {remain/60:.1f} 分",
            flush=True,
        )
        last_print = now

    todo: deque[int] = deque(range(start_page, total_pages + 1))
    retry_q: deque[int] = deque()
    tries_of: dict[int, int] = {}
    conc = max(1, min(workers, 8))
    max_conc = workers
    streak = 0
    while todo or retry_q:
        if retry_q and (not todo or streak == 0):
            batch_n = min(max(1, conc // 2), len(retry_q))
            batch = [retry_q.popleft() for _ in range(batch_n)]
            use_async = False
        else:
            batch_n = min(conc, len(todo))
            batch = [todo.popleft() for _ in range(batch_n)]
            use_async = True
        urls = [list_url(path, term, page, async_mode=use_async, block_id=block_id) for page in batch]
        if sleep:
            gate.wait()
        rows = fetch_many(
            urls,
            timeout=timeout,
            referer=DEFAULT_REFERER,
            parallel_max=len(batch),
        )
        failed: list[int] = []
        limited = 0
        ok_n = 0
        for page, (_url, body, _detail) in zip(batch, rows):
            html = body.decode("utf-8", errors="replace") if body else ""
            if looks_like_list(html):
                chunk = parse_items(html)
                if chunk:
                    ingest(page, chunk)
                    ok_n += 1
                    session_pages += 1
                    continue
            if body and 800 <= len(body) <= 20000 and not looks_like_list(html):
                limited += 1
            failed.append(page)
        now = time.monotonic()
        if contiguous == total_pages or now - last_print >= 2:
            dump_progress(True)
            report()
        if not failed:
            streak += 1
            if streak >= 2 and conc < max_conc:
                conc = min(max_conc, conc + 2)
                streak = 0
            continue
        if limited >= max(1, len(batch) // 2) or ok_n == 0:
            nxt = max(2, conc // 2)
            wait = 8.0 if limited else 3.0
            print(
                f"{label}  限流/失败 {len(failed)}/{len(batch)}  并发 {conc}->{nxt}  暂停 {wait:.0f}s",
                file=sys.stderr,
                flush=True,
            )
            note_rate_limit(wait)
            time.sleep(wait)
            conc = nxt
            streak = 0
        for page in failed:
            tries_of[page] = tries_of.get(page, 0) + 1
            if tries_of[page] >= 6:
                die(f"{label} 第 {page} 页多次失败")
            retry_q.append(page)

    dump_progress(True)
    items.sort(key=lambda rec: int(rec.get("rank") or 0))

    return finish_list(
        path,
        term,
        label,
        items,
        total_hint,
        total_pages,
        out_dir,
        formats,
        extra_meta,
    )


def finish_list(
    path: str,
    term: str,
    label: str,
    items: list[dict[str, Any]],
    total_hint: int,
    pages: int,
    out_dir: Path,
    formats: set[str],
    extra_meta: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": path,
        "term": term,
        "label": label,
        "source": list_url(path, term, 1, async_mode=False),
        "total_hint": total_hint,
        "pages": pages,
        "count": len(items),
        "fetched_at": now_iso(),
        "items": items,
    }
    items.sort(key=lambda rec: int(rec.get("rank") or 0))
    payload["count"] = len(items)
    payload["items"] = items
    if extra_meta:
        payload.update(extra_meta)
    if "json" in formats:
        write_json(out_dir / "items.json", payload)
    if "csv" in formats:
        rows = []
        for rec in items:
            row = dict(rec)
            row["term"] = term
            row["label"] = label
            row["category"] = (extra_meta or {}).get("category") or (extra_meta or {}).get("slug") or ""
            rows.append(row)
        write_csv(out_dir / "items.csv", rows, CSV_FIELDS)
    print(f"{label}  完成  {len(items)} 部  {out_dir}", flush=True)
    return payload


def fetch_catalog(out_dir: Path, force: bool) -> list[dict[str, Any]]:
    path = out_dir / "categories" / "catalog.json"
    if path.exists() and not force:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        cats = data.get("categories") if isinstance(data, dict) else data
        if isinstance(cats, list) and cats:
            print(f"分类目录  {len(cats)} 个  {path}", flush=True)
            return cats
    html, _ = fetch_html(
        f"{BASE}/categories/",
        timeout=40,
        retries=5,
        validate=looks_like_catalog,
    )
    cats = parse_catalog(html)
    if not cats:
        die("未能解析主题分类目录")
    write_json(
        path,
        {
            "source": f"{BASE}/categories/",
            "count": len(cats),
            "categories": cats,
            "fetched_at": now_iso(),
        },
    )
    print(f"分类目录  {len(cats)} 个  {path}", flush=True)
    for cat in cats:
        print(f"  {cat['slug']:22}  {cat['count']:6}  {cat['name']}", flush=True)
    return cats


def resolve_terms(spec: str) -> list[str]:
    spec = (spec or "all").strip().lower()
    spec = TERM_ALIASES.get(spec, spec)
    if spec == "all":
        return list(TERM_ORDER)
    if spec in TERMS:
        return [spec]
    die("时间档必须是 日/周/月/总/全部（或 today/week/month/video_viewed/all）")
    return []


def parse_formats(raw: str) -> set[str]:
    wanted = {p.strip().lower() for p in (raw or "json,jsonl").split(",") if p.strip()}
    allowed = {"json", "jsonl", "csv"}
    bad = wanted - allowed
    if bad:
        die(f"未知输出格式：{', '.join(sorted(bad))}")
    if not wanted:
        wanted = {"json", "jsonl"}
    wanted.add("jsonl")
    return wanted


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="抓取 jable.tv 熱門影片四个时间档，以及全部主题分类作品。"
    )
    p.add_argument("--scope", default="", help="hot 热门 / categories 分类 / all 全部")
    p.add_argument("--term", default="", help="today/week/month/video_viewed/all")
    p.add_argument("--category", default="", help="只抓这些 slug，逗号分隔")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="输出目录")
    p.add_argument("--sleep", type=float, default=0.05, help="批次间隔秒")
    p.add_argument("--workers", type=int, default=8, help="并行页数（curl --parallel）")
    p.add_argument("--timeout", type=int, default=40)
    p.add_argument(
        "-p",
        "--pages",
        "--max-pages",
        dest="max_pages",
        type=int,
        default=0,
        help="每个列表抓前 N 页；默认 0=全部分页",
    )
    p.add_argument("--force", action="store_true", help="忽略进度，重抓")
    p.add_argument("--dry-run", action="store_true", help="只打印将请求的网址")
    p.add_argument("--catalog", action="store_true", help="只刷新主题分类目录")
    p.add_argument("--format", default="json,jsonl", help="json,jsonl,csv")
    p.add_argument("--parse-file", default="", help="解析本地 HTML，不发请求")
    return p.parse_args(argv)


def jobs_from_args(
    scope: str,
    terms: list[str],
    cats: list[dict[str, Any]],
    only_slugs: set[str],
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    if scope in {"hot", "all"}:
        for term in terms:
            jobs.append(
                {
                    "scope": "hot",
                    "path": "/hot/",
                    "term": term,
                    "label": f"熱門/{TERMS[term]}",
                    "subdir": Path("hot") / term,
                    "extra": {"scope": "hot"},
                }
            )
    if scope in {"categories", "all"}:
        picked = [c for c in cats if not only_slugs or c["slug"] in only_slugs]
        if only_slugs and not picked:
            die("没有匹配的分类 slug")
        for cat in picked:
            for term in terms:
                jobs.append(
                    {
                        "scope": "categories",
                        "path": list_path("categories", cat["slug"]),
                        "term": term,
                        "label": f"{cat['name']}/{TERMS[term]}",
                        "subdir": Path("categories") / cat["slug"] / term,
                        "extra": {
                            "scope": "categories",
                            "slug": cat["slug"],
                            "category": cat["name"],
                            "category_count_hint": cat["count"],
                        },
                    }
                )
    return jobs


def main(argv: list[str] | None = None) -> int:
    bare = launched_bare(argv)
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.parse_file:
        html = Path(args.parse_file).read_text(encoding="utf-8", errors="replace")
        items = parse_items(html)
        cats = parse_catalog(html)
        payload = {
            "total_hint": parse_total(html),
            "last_page": parse_last_page(html, len(items) or 24, parse_total(html)),
            "item_count": len(items),
            "items": items[:24],
            "categories": cats,
        }
        import json as json_lib

        print(json_lib.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if bare:
        print_intro(
            "熱門影片",
            "抓取 所有時間 / 本月熱門 / 本週熱門 / 今日熱門，以及 12 个主题分类。"
            "默认翻完全部分页；指定页数则只抓每个列表的前 N 页。"
            "只保存公开列表元数据，不下正片。",
        )
    scope = args.scope.strip().lower()
    if not scope:
        if bare:
            line = prompt_line("请选择范围 [热门/分类/全部]（回车=全部）：")
            scope = (line or "all").strip().lower()
        else:
            scope = "all"
    scope = {
        "热门": "hot",
        "熱門": "hot",
        "hot": "hot",
        "分类": "categories",
        "分類": "categories",
        "categories": "categories",
        "category": "categories",
        "全部": "all",
        "all": "all",
    }.get(scope, scope)
    if scope not in {"hot", "categories", "all"}:
        die("范围必须是 热门 / 分类 / 全部")

    term_spec = args.term.strip()
    if not term_spec:
        if bare:
            line = prompt_line("请选择时间档 [日/周/月/总/全部]（回车=全部）：")
            term_spec = line or "all"
        else:
            term_spec = "all"
    terms = resolve_terms(term_spec)
    if bare:
        line = prompt_line("每个列表抓几页？回车=全部，输入数字=只抓前 N 页：")
        if not line:
            args.max_pages = 0
        else:
            try:
                args.max_pages = int(line)
            except ValueError:
                die("页数必须是整数")
            if args.max_pages < 0:
                die("页数不能为负数")
    formats = parse_formats(args.format)
    out_root = Path(args.out)
    only_slugs = {s.strip().lower() for s in args.category.split(",") if s.strip()}

    warmup()
    cats: list[dict[str, Any]] = []
    if args.catalog:
        fetch_catalog(out_root, True)
        return 0
    if scope in {"categories", "all"}:
        cats = fetch_catalog(out_root, args.force)

    jobs = jobs_from_args(scope, terms, cats, only_slugs)
    if not jobs:
        die("没有可执行的任务")
    if args.max_pages > 0:
        print(f"每个列表前 {args.max_pages} 页  共 {len(jobs)} 个列表", flush=True)
    else:
        print(f"每个列表全部分页  共 {len(jobs)} 个列表", flush=True)
    if args.dry_run:
        for job in jobs:
            for page in (1, 2, 3):
                print(list_url(job["path"], job["term"], page))
        print(f"jobs {len(jobs)}", flush=True)
        return 0

    stamp = date.today().isoformat()
    index: dict[str, Any] = {
        "fetched_at": now_iso(),
        "date": stamp,
        "scope": scope,
        "terms": [{"term": t, "label": TERMS[t]} for t in terms],
        "jobs": [],
    }
    t0 = time.time()
    for i, job in enumerate(jobs, start=1):
        print(flush=True)
        print(f"[{i}/{len(jobs)}] {job['label']}  {job['path']}  {job['term']}", flush=True)
        dest = out_root / job["subdir"]
        payload = crawl_list(
            path=job["path"],
            term=job["term"],
            label=job["label"],
            out_dir=dest,
            sleep=args.sleep,
            workers=args.workers,
            timeout=args.timeout,
            max_pages=args.max_pages,
            force=args.force,
            formats=formats,
            extra_meta=job.get("extra"),
        )
        index["jobs"].append(
            {
                "label": job["label"],
                "path": job["path"],
                "term": job["term"],
                "count": payload.get("count"),
                "pages": payload.get("pages"),
                "total_hint": payload.get("total_hint"),
                "out": str(dest / "items.json"),
            }
        )
        write_json(out_root / "index.json", index)

    index["elapsed_sec"] = round(time.time() - t0, 1)
    write_json(out_root / "index.json", index)
    print(flush=True)
    print(f"完成  {len(index['jobs'])} 个列表  {out_root}", flush=True)
    return 0


if __name__ == "__main__":
    configure_stdio()
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:
        print(f"错误：{type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
