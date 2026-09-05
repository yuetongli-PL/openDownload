# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from server.jable_inspect import parse_inspect_html
except ImportError:
    parse_inspect_html = None

HTML = """
<html>
<head>
  <title>SSIS-001 Test Title - Jable.TV</title>
  <meta property="og:image" content="https://example.com/ssis-001.jpg">
  <meta property="og:url" content="https://jable.tv/videos/ssis-001/">
</head>
<body>
  <a class="model" href="https://jable.tv/models/yua-mikami/" title="三上悠亜">
    <img title="三上悠亜" alt="三上悠亜">三上悠亜
  </a>
  <div class="video-info pb-3">
    <h5>
      <a href="https://jable.tv/categories/roleplay/" class="cat">角色劇情</a>
      <a href="https://jable.tv/tags/pantyhose/">黑絲</a>
    </h5>
  </div>
  <a class="tag text-light" href="https://jable.tv/tags/cosplay/">Cosplay</a>
  <p>上市於 2024-08-01</p>
  <footer>
    <a href="https://jable.tv/models/kaede-karen/">楓可憐</a>
    <a href="https://jable.tv/models/yua-mikami/">« 首頁</a>
  </footer>
</body>
</html>
"""


def _need():
    if parse_inspect_html is None:
        try:
            import pytest
        except ImportError:
            raise ImportError("server.jable_inspect") from None
        pytest.skip("server.jable_inspect not available")


def _names(items):
    out = []
    for item in items or []:
        if isinstance(item, dict):
            out.append(item.get("name") or item.get("title") or item.get("slug") or "")
        else:
            out.append(str(item))
    return out


def _slugs(items):
    out = []
    for item in items or []:
        if isinstance(item, dict):
            out.append(item.get("slug") or item.get("id") or "")
        else:
            out.append(str(item))
    return out


def test_parse_inspect_html():
    _need()
    info = parse_inspect_html(HTML, "ssis-001")
    assert str(info.get("id") or "").lower() == "ssis-001"
    title = (info.get("title") or "").strip()
    assert "Test Title" in title
    actors = info.get("actors") or []
    assert "三上悠亜" in _names(actors) or "yua-mikami" in _slugs(actors)
    assert "楓可憐" not in _names(actors)
    assert "kaede-karen" not in _slugs(actors)
    assert not any("首頁" in n or "«" in n for n in _names(actors))
    tags = info.get("tags") or []
    assert "黑絲" in _names(tags) or "pantyhose" in _slugs(tags)
    assert "角色劇情" in _names(tags) or "roleplay" in _slugs(tags)
    assert "Cosplay" not in _names(tags) and "cosplay" not in _slugs(tags)
    assert len(tags) <= 4
    assert "2024-08-01" in str(info.get("date") or "")


if __name__ == "__main__":
    test_parse_inspect_html()
    print("ok test_parse_inspect_html")
