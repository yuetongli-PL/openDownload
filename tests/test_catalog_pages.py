# -*- coding: utf-8 -*-
"""热门 / 最近 / 类型：目录页都能立刻取出本地作品。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT))

from server.jable_index import display_len, items_for_ui_page, works_count  # noqa: E402
from server.jable_lists import PAGE_SIZE, _resolve_list  # noqa: E402


def _pages(total: int) -> int:
    return max(1, (max(total, 1) + PAGE_SIZE - 1) // PAGE_SIZE)


def test_catalog_pages_instant() -> None:
    catalog = works_count()
    assert catalog > 30000, catalog
    want_pages = _pages(catalog)
    assert want_pages >= 3000, want_pages

    seen_first: dict[str, set[str]] = {}
    for kind in ("hot", "latest", "type"):
        spec = _resolve_list(kind, "", "")
        total = display_len(spec)
        pages = _pages(total)
        assert total >= catalog, (kind, total, catalog)
        assert pages == want_pages, (kind, pages, want_pages)
        probes = [1, 2, 40, 50, 1000, 2000, 2800, 3000, 3232, pages - 1, pages]
        firsts: list[str] = []
        for page in probes:
            if page < 1:
                continue
            rows = items_for_ui_page(spec, page, PAGE_SIZE)
            assert rows, f"{kind} page {page} empty (pages={pages} total={total})"
            expect = PAGE_SIZE if page < pages else ((total - 1) % PAGE_SIZE) + 1
            assert len(rows) == expect, (kind, page, len(rows), expect)
            code = str(rows[0].get("id") or "")
            assert code
            firsts.append(f"{page}:{code}")
        seen_first[kind] = set(firsts)
        # 相邻探测页不应整页相同
        uniq = {item.split(":", 1)[1] for item in firsts}
        assert len(uniq) >= 8, (kind, firsts)


if __name__ == "__main__":
    test_catalog_pages_instant()
    print("catalog pages ok", works_count(), "works")
