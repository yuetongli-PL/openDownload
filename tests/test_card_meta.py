# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT))

from jable_hot import actors_from_title, parse_items  # noqa: E402
from server.jable_index import _normalize_work  # noqa: E402

HTML = """
<div class="video-img-box">
  <a href="https://jable.tv/videos/ssis-001/">
    <img data-src="https://example.com/a.jpg">
  </a>
  <span class="label">1:23:45</span>
  <h6 class="title"><a href="https://jable.tv/videos/ssis-001/">SSIS-001 Test</a></h6>
  <svg><use xlink:href="#icon-eye"></use></svg> 12 345
  <div>2024-08-01</div>
  <a href="https://jable.tv/models/yua-mikami/">三上悠亜</a>
</div>
<div class="video-img-box">
  <a href="https://jable.tv/videos/ssis-002/">
    <img data-src="https://example.com/b.jpg">
  </a>
  <h6 class="title"><a href="https://jable.tv/videos/ssis-002/">SSIS-002 Other</a></h6>
  <ul class="pagination">
    <li><a href="https://jable.tv/models/yua-mikami/">« 首頁</a></li>
  </ul>
</div>
"""


def test_parse_items_date_actors() -> None:
    items = parse_items(HTML)
    assert items
    row = items[0]
    assert row["code"] == "ssis-001"
    assert row["date"] == "2024-08-01"
    names = [a.get("name") for a in row.get("actors") or []]
    slugs = [a.get("slug") for a in row.get("actors") or []]
    assert "三上悠亜" in names
    assert "yua-mikami" in slugs
    work = _normalize_work(row)
    assert work["date"] == "2024-08-01"
    assert work["actors"][0]["slug"] == "yua-mikami"
    last = items[-1]
    last_names = [a.get("name") for a in last.get("actors") or []]
    assert "首頁" not in "".join(last_names)
    assert not any("«" in (n or "") for n in last_names)


def test_actors_from_title() -> None:
    one = actors_from_title("DLDSS-544 今晩、商談が決まるから…。 逢見梨花")
    assert [a["name"] for a in one] == ["逢見梨花"]
    two = actors_from_title("BONY-144 預定強● 入侵性交委託俱樂部 由香里 藤咲紫")
    assert [a["name"] for a in two] == ["由香里", "藤咲紫"]
    latin = actors_from_title("START-602 顔面特化 4コスプレシチュエーション MINAMO")
    assert [a["name"] for a in latin] == ["MINAMO"]


def test_normalize_work_fills_actors_from_title() -> None:
    work = _normalize_work(
        {
            "id": "lulu-445",
            "title": "LULU-445 被住在附近的美腿痴女空姐挑逗 天馬由衣",
            "date": "",
            "actors": [],
        }
    )
    assert work["actors"]
    assert work["actors"][0]["name"] == "天馬由衣"


def test_page_feed_keeps_date_actors() -> None:
    from server.jable_page import _as_card

    card = _as_card(
        {
            "id": "ssis-001",
            "title": "SSIS-001 Test 三上悠亜",
            "date": "2024-08-01",
            "actors": [{"name": "三上悠亜", "slug": "yua-mikami"}],
        }
    )
    assert card["date"] == "2024-08-01"
    assert card["actors"][0]["slug"] == "yua-mikami"


if __name__ == "__main__":
    test_parse_items_date_actors()
    test_actors_from_title()
    test_normalize_work_fills_actors_from_title()
    test_page_feed_keeps_date_actors()
    print("ok test_card_meta")
