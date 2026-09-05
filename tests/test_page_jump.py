# -*- coding: utf-8 -*-
"""任意目录页都能立刻返回 12 条本地作品。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.jable_index import works_count  # noqa: E402
from server.jable_lists import list_feed  # noqa: E402
from server.jable_page import page_feed  # noqa: E402

KINDS = ("hot", "latest", "type")
PAGES = (1, 50, 2000, 3232)


def _skip_if_no_catalog() -> None:
    if works_count() < 30000:
        pytest.skip("local catalog missing")


def test_catalog_pages_return_12_items_fast() -> None:
    _skip_if_no_catalog()
    for kind in KINDS:
        first_ids: list[str] = []
        for page in PAGES:
            t0 = time.perf_counter()
            data = page_feed(kind=kind, page=page)
            ms = (time.perf_counter() - t0) * 1000
            items = data.get("items") or []
            assert len(items) == 12, (kind, page, len(items), ms)
            for item in items:
                assert item.get("id"), (kind, page, item)
            assert ms < 80, (kind, page, ms)
            first_ids.append(str(items[0]["id"]))
        assert len(set(first_ids)) == len(PAGES), (kind, first_ids)


def test_tag_black_pantyhose_local_only() -> None:
    data = page_feed(kind="tag", slug="black-pantyhose", page=1)
    items = data.get("items") or []
    if items:
        assert len(items) <= 12
        assert int(data.get("total") or 0) >= 6000

    t0 = time.perf_counter()
    far = page_feed(kind="tag", slug="black-pantyhose", page=100)
    ms = (time.perf_counter() - t0) * 1000
    assert ms < 80, ms
    far_items = far.get("items") or []
    if not far_items:
        assert far.get("pending") is True


def test_list_feed_type_page_50() -> None:
    _skip_if_no_catalog()
    t0 = time.perf_counter()
    data = list_feed(kind="type", page=50)
    ms = (time.perf_counter() - t0) * 1000
    items = data.get("items") or []
    assert len(items) == 12, (len(items), ms)
    assert ms < 150, ms


if __name__ == "__main__":
    test_catalog_pages_return_12_items_fast()
    test_tag_black_pantyhose_local_only()
    test_list_feed_type_page_50()
    print("page jump ok")
