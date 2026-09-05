# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_ROOT = ROOT / "python"
for path in (str(ROOT), str(PY_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from server.jable_lists import DEFAULT_CATEGORIES, _crawl_named_list, _resolve_list  # noqa: E402

SLUGS = [slug for slug, _ in DEFAULT_CATEGORIES]


def warmup_one(slug: str) -> tuple[str, int]:
    spec = _resolve_list("cat", slug, "post_date_and_popularity")
    data = _crawl_named_list(spec, 1, False)
    return slug, len(data.get("items") or [])


def main() -> None:
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(warmup_one, slug): slug for slug in SLUGS}
        for fut in as_completed(futs):
            slug = futs[fut]
            try:
                name, count = fut.result()
                print(f"{name} {count}", flush=True)
            except Exception as exc:
                print(f"{slug} ERROR {exc}", flush=True)


if __name__ == "__main__":
    main()
