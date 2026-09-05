# -*- coding: utf-8 -*-
"""标签顺序在内存里切片，任意页都应在 3ms 内取出 12 条。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "python", ROOT):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from server.jable_index import compact_cards, load_order, works_compact, works_count  # noqa: E402
from server.jable_lists import _resolve_list  # noqa: E402
from server.jable_page import page_feed  # noqa: E402
from server.jable_tag_cache import cache_status, orders_payload, spec_page_codes  # noqa: E402


def test_disk_pages_are_in_snapshot() -> None:
    spec = _resolve_list("tag", "big-tits", "")
    pages = spec_page_codes(spec)
    if len(pages) < 10:
        pytest.skip("big-tits pages missing")
    from server.jable_lists import list_snapshot

    data = list_snapshot(kind="tag", slug="big-tits")
    assert data.get("pages")
    assert len(data["pages"]) >= 10
    far = max(int(k) for k in data["pages"])
    assert far > 10


def test_orders_payload_shape() -> None:
    data = orders_payload()
    assert "tags" in data and "cats" in data
    assert data["lists"] >= 100
    assert isinstance(data["tags"], dict)
    assert isinstance(data["cats"], dict)
    status = cache_status()
    assert "works" in status


def test_works_compact_matches_library() -> None:
    if works_count() < 1000:
        pytest.skip("works index missing")
    cards = works_compact()
    assert len(cards) == works_count()
    assert cards[0][0]


def test_cached_tag_slice_under_3ms() -> None:
    spec = _resolve_list("tag", "black-pantyhose", "")
    codes = load_order(spec)
    if len(codes) < 1200:
        pytest.skip("tag order not fully cached yet")
    page = 100
    start = (page - 1) * 12
    t0 = time.perf_counter()
    chunk = codes[start : start + 12]
    cards = compact_cards(chunk)
    ms = (time.perf_counter() - t0) * 1000
    assert len(chunk) == 12
    assert len(cards) == 12
    assert ms < 3, ms


def test_page_feed_uses_order_when_cached() -> None:
    spec = _resolve_list("tag", "black-pantyhose", "")
    codes = load_order(spec)
    if len(codes) < 1200:
        pytest.skip("tag order not fully cached yet")
    t0 = time.perf_counter()
    data = page_feed(kind="tag", slug="black-pantyhose", page=100)
    ms = (time.perf_counter() - t0) * 1000
    items = data.get("items") or []
    assert len(items) == 12
    assert items[0]["id"] == codes[1188]
    assert not data.get("pending")
    assert ms < 80, ms
