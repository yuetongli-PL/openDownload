# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT))

from server.jable_index import extend_order_from_disk, order_len, order_total_hint, seed_order  # noqa: E402
from server.jable_lists import (  # noqa: E402
    PAGE_SIZE,
    SITE_PAGE_SIZE,
    _allowed_site_pages,
    _declared_total,
    _learn_model_title,
    _resolve_list,
    _spec_title,
    list_snapshot,
)
from server.jable_page import page_feed  # noqa: E402


def test_resolve_model_list() -> None:
    spec = _resolve_list("model", "yua-mikami", "")
    assert spec["kind"] == "model"
    assert spec["path"] == "/models/yua-mikami/"
    assert spec["slug"] == "yua-mikami"
    assert spec["term"] == "post_date"
    actor = _resolve_list("actor", "yua-mikami", "video_viewed")
    assert actor["kind"] == "model"
    assert actor["path"] == spec["path"]
    assert actor["term"] == "video_viewed"
    hashed = _resolve_list("model", "e82b22cd3275fd0e569147d82fa1999d", "")
    assert hashed["title"] in {"演员", "彩月七緒"}
    name = _learn_model_title(
        "e82b22cd3275fd0e569147d82fa1999d",
        '<h2 class="h3-md mb-1">彩月七緒</h2>',
    )
    assert name == "彩月七緒"
    hashed2 = _resolve_list("model", "e82b22cd3275fd0e569147d82fa1999d", "")
    assert hashed2["title"] == "彩月七緒"
    assert _spec_title(hashed2) == "彩月七緒"


def test_model_one_page_cache_keeps_site_total() -> None:
    spec = _resolve_list("model", "0536d6211777fdfff62483acd7815921", "")
    seed_order(spec)
    hint = order_total_hint(spec)
    known = order_len(spec)
    if hint < 40:
        return
    assert hint >= 129
    assert known <= hint
    assert _declared_total(spec, {"total": 24}, 24) == hint
    assert _allowed_site_pages(spec) >= 6
    data = page_feed(kind="model", slug=spec["slug"], page=1)
    assert int(data.get("total") or 0) >= 129
    assert int(data.get("page_count") or 0) >= 11
    assert len(data.get("items") or []) == PAGE_SIZE
    far = page_feed(kind="model", slug=spec["slug"], page=8)
    assert int(far.get("total") or 0) >= 129
    assert int(far.get("page") or 0) == 8
    if not (far.get("items") or []):
        assert far.get("pending") is True


def test_model_page_stamps_current_actor() -> None:
    data = page_feed(kind="model", slug="kaede-karen", page=1)
    items = data.get("items") or []
    if not items:
        return
    slug = "kaede-karen"
    for item in items:
        actors = item.get("actors") or []
        slugs = [str(a.get("slug") or "") for a in actors if isinstance(a, dict)]
        names = [str(a.get("name") or "") for a in actors if isinstance(a, dict)]
        assert slug in slugs or any("楓" in n or "可憐" in n or "カレン" in n for n in names)
        assert not any("首頁" in n or "«" in n for n in names)


def test_model_cached_pages_are_jumpable() -> None:
    spec = _resolve_list("model", "kaede-karen", "")
    n = extend_order_from_disk(spec)
    if n < 48:
        return
    hint = order_total_hint(spec)
    assert hint >= n
    pages = max(1, (hint + PAGE_SIZE - 1) // PAGE_SIZE)
    data = page_feed(kind="model", slug="kaede-karen", page=min(5, pages))
    items = data.get("items") or []
    assert items, (data.get("total"), data.get("pending"), n)
    assert int(data.get("total") or 0) >= 65
    snap = list_snapshot(kind="model", slug="kaede-karen")
    assert int(snap.get("total") or 0) >= 65
    assert snap.get("pages")
    last_site = max(int(k) for k in snap["pages"])
    assert last_site >= 2
    assert _allowed_site_pages(spec) >= (hint + SITE_PAGE_SIZE - 1) // SITE_PAGE_SIZE


if __name__ == "__main__":
    test_resolve_model_list()
    test_model_one_page_cache_keeps_site_total()
    test_model_cached_pages_are_jumpable()
    print("ok test_model_list")
