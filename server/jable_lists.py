# -*- coding: utf-8 -*-
"""Jable 热门 / 選片：把公开列表解析进确认看板（正片仍走确认后下载）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

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
) -> dict[str, Any]:
    from jable_hot import crawl_list
    from jable_http import warmup

    pages = int(pages or 0)
    if pages < 0:
        pages = 0
    if pages > 80:
        pages = 80
    _log(log, f"列表 {label}  path={path}  term={term}  pages={pages or '全部'}")
    warmup(timeout=15)
    out = _out_dir(*[p for p in path.strip("/").split("/") if p], term or "default")
    payload = crawl_list(
        path=path,
        term=term or "post_date",
        label=label,
        out_dir=out,
        sleep=0.05,
        workers=8,
        timeout=40,
        max_pages=pages,
        force=True,
        formats={"json"},
        extra_meta=extra,
        block_id=block_id,
    )
    items = payload.get("items") or []
    _log(log, f"抓到 {len(items)} 部  {label}")
    return payload


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
