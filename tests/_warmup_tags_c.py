# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "python"):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from server.jable_lists import _crawl_named_list, _resolve_list  # noqa: E402

TAG_TERM = "post_date_and_popularity"
YEAR_TERM = "post_date"
GROUPS = {
    "角色": [
        "club-hostess-and-sex-worker",
        "doctor",
        "fugitive",
        "nurse",
        "teacher",
        "flight-attendant",
        "team-manager",
        "widow",
        "detective",
        "couple",
        "housewife",
        "private-teacher",
        "idol",
        "wife",
        "female-anchor",
        "ol",
    ],
    "地點": [
        "magic-mirror",
        "tram",
        "first-night",
        "prison",
        "hot-spring",
        "bathing-place",
        "swimming-pool",
        "car",
        "toilet",
        "school",
        "library",
        "gym-room",
        "store",
    ],
    "雜項": [
        "video-recording",
        "debut-retires",
        "variety-show",
        "festival",
        "thanksgiving",
        "more-than-4-hours",
    ],
}
YEARS = ("2026", "2025", "2024", "2023", "2022", "2021", "2020")


def warmup_tag(group: str, slug: str) -> tuple[str, str, int, str]:
    try:
        spec = _resolve_list("tag", slug, TAG_TERM)
        data = _crawl_named_list(spec, pages=1, force=False)
        n = len(data.get("items") or [])
        status = "ok" if n else "empty"
        return group, slug, n, status
    except Exception as exc:
        return group, slug, 0, f"error: {exc}"


def warmup_year(year: str) -> tuple[str, str, int, str]:
    try:
        spec = _resolve_list("latest", "", YEAR_TERM, year=year)
        data = _crawl_named_list(spec, pages=1, force=False)
        n = len(data.get("items") or [])
        status = "ok" if n else "empty"
        return "year", year, n, status
    except Exception as exc:
        return "year", year, 0, f"error: {exc}"


def main() -> int:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    tag_jobs = [(group, slug) for group, slugs in GROUPS.items() for slug in slugs]
    print(
        f"warmup tags_c groups={list(GROUPS)} tags={len(tag_jobs)} "
        f"years={list(YEARS)} workers=4 pages=1 force=False",
        flush=True,
    )
    ok = fail = empty = 0
    total = len(tag_jobs) + len(YEARS)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {}
        for group, slug in tag_jobs:
            futs[pool.submit(warmup_tag, group, slug)] = (group, slug)
        for year in YEARS:
            futs[pool.submit(warmup_year, year)] = ("year", year)
        for fut in as_completed(futs):
            group, slug = futs[fut]
            try:
                group, slug, n, status = fut.result()
            except Exception as exc:
                n, status = 0, f"error: {exc}"
            if status == "ok":
                ok += 1
            elif status == "empty":
                empty += 1
            else:
                fail += 1
            print(f"{group}\t{slug}\t{n}\t{status}", flush=True)
    print(f"done ok={ok} empty={empty} fail={fail} total={total}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
