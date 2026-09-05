# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "python"):
    s = str(p)
    if s not in sys.path:
        sys.path.insert(0, s)

from server.jable_lists import _crawl_named_list, _resolve_list  # noqa: E402

TERM = "post_date_and_popularity"
GROUPS = {
    "交合": [
        "facial",
        "footjob",
        "anal-sex",
        "spasms",
        "squirting",
        "deep-throat",
        "kiss",
        "cum-in-mouth",
        "blowjob",
        "tit-wank",
        "creampie",
    ],
    "玩法": [
        "outdoor",
        "gang-intrusion",
        "intrusion",
        "tune",
        "bondage",
        "quickie",
        "chikan",
        "chizyo",
        "masochism-guy",
        "crapulence",
        "soapland",
        "breast-milk",
        "piss",
        "massage",
        "groupsex",
        "grip",
        "insult",
        "10-times-a-day",
        "3p",
    ],
    "劇情": [
        "black",
        "ugly-man",
        "temptation",
        "kinship",
        "virginity",
        "time-stop",
        "avenge",
        "age-difference",
        "giant",
        "love-potion",
        "sex-beside-husband",
        "affair",
        "hypnosis",
        "private-cam",
        "rainy-day",
        "ntr",
    ],
}


def warmup_one(group: str, slug: str) -> tuple[str, str, int, str]:
    try:
        spec = _resolve_list("tag", slug, TERM)
        data = _crawl_named_list(spec, pages=1, force=False)
        n = len(data.get("items") or [])
        status = "ok" if n else "empty"
        return group, slug, n, status
    except Exception as exc:
        return group, slug, 0, f"error: {exc}"


def main() -> int:
    jobs = [(group, slug) for group, slugs in GROUPS.items() for slug in slugs]
    print(
        f"warmup tags_b groups={list(GROUPS)} tags={len(jobs)} "
        f"workers=4 pages=1 force=False term={TERM}",
        flush=True,
    )
    ok = fail = empty = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(warmup_one, group, slug): (group, slug) for group, slug in jobs}
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
    print(f"done ok={ok} empty={empty} fail={fail} total={len(jobs)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
