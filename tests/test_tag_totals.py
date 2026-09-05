# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.jable_lists import resolve_list_total  # noqa: E402


def test_resolve_list_total_keeps_site_hint() -> None:
    assert resolve_list_total(0, 6655, 24) == 6655
    assert resolve_list_total(6655, 0, 24) == 6655
    assert resolve_list_total(24, 24, 24) == 24
    assert resolve_list_total(0, 0, 12) == 12
    assert resolve_list_total(100, 90, 240) == 240


def test_tag_order_hint_survives_one_page_cache() -> None:
    from server.jable_index import order_len, order_total_hint
    from server.jable_lists import _declared_total, _resolve_list

    spec = _resolve_list("tag", "black-pantyhose", "")
    known = order_len(spec)
    hint = order_total_hint(spec)
    if hint < 100:
        return
    assert _declared_total(spec, {"total": 24}, 24) == hint
    assert _declared_total(spec, {}, 24) >= 6000
    assert known <= hint + 24
