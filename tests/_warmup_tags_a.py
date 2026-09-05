# -*- coding: utf-8 -*-
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from jable_pick import GROUPS
from server.jable_lists import _crawl_named_list, _resolve_list

SLUGS = [slug for group in ("衣著", "身材") for _, slug in GROUPS[group]]


def _warmup(slug: str) -> tuple[str, int, str]:
    try:
        data = _crawl_named_list(
            _resolve_list("tag", slug, "post_date_and_popularity"),
            pages=1,
            force=False,
        )
        return slug, len(data.get("items") or []), ""
    except Exception as exc:
        return slug, 0, str(exc)


def main() -> None:
    print(len(SLUGS))
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [pool.submit(_warmup, slug) for slug in SLUGS]
        for fut in as_completed(futs):
            slug, n, err = fut.result()
            if err:
                print(f"{slug}\tERROR\t{err}")
            else:
                print(f"{slug}\t{n}")


if __name__ == "__main__":
    main()
