# -*- coding: utf-8 -*-
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path("python").resolve()))
sys.path.insert(0, str(Path(".").resolve()))

from server import jable_lists as jl

_resolve_list = getattr(jl, "_resolve_list", None)
_crawl_named_list = getattr(jl, "_crawl_named_list", None)
crawl_one = getattr(jl, "crawl_one", None)

TARGETS = [
    ("latest", "post_date"),
    ("hot", "video_viewed_today"),
    ("week", "video_viewed_week"),
    ("month", "video_viewed_month"),
    ("all", "video_viewed"),
]


def _count(payload) -> int:
    if not isinstance(payload, dict):
        return 0
    items = payload.get("items")
    return len(items) if isinstance(items, list) else 0


def warm_one(kind: str, term: str) -> str:
    label = f"{kind}/{term}"
    try:
        if callable(_resolve_list) and callable(_crawl_named_list):
            spec = _resolve_list(kind, "", term)
            label = spec.get("title") or label
            data = _crawl_named_list(spec, 1, False)
            return f"{label}  {kind} {term}  items={_count(data)}"
        if not callable(crawl_one):
            raise RuntimeError("no crawl helper available")
        spec = _resolve_list(kind, "", term) if callable(_resolve_list) else {
            "path": "/hot/" if kind != "latest" else "/latest-updates/",
            "term": term,
            "title": kind,
            "kind": kind,
            "slug": "",
            "block_id": (
                "list_videos_latest_videos_list"
                if kind == "latest"
                else "list_videos_common_videos_list"
            ),
        }
        label = spec.get("title") or label
        data = crawl_one(
            path=spec["path"],
            term=spec.get("term") or term,
            label=label,
            pages=1,
            extra={
                "scope": spec.get("kind") or kind,
                "slug": spec.get("slug") or "",
                "year": spec.get("year") or "",
                "month": spec.get("month") or "",
            },
            force=False,
            block_id=spec.get("block_id") or "list_videos_common_videos_list",
        )
        return f"{label}  {kind} {term}  items={_count(data)}"
    except Exception as exc:
        traceback.print_exc()
        return f"{label}  {kind} {term}  error={exc}"


def main() -> int:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    print("warmup start", flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(warm_one, kind, term): (kind, term) for kind, term in TARGETS}
        try:
            for fut in as_completed(futs, timeout=110):
                kind, term = futs[fut]
                try:
                    print(fut.result(), flush=True)
                except Exception as exc:
                    print(f"{kind}/{term}  error={exc}", flush=True)
        except TimeoutError:
            print("warmup timeout", flush=True)
            for fut, (kind, term) in futs.items():
                if not fut.done():
                    print(f"{kind}/{term}  error=timeout", flush=True)
                    fut.cancel()
    print("warmup done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
