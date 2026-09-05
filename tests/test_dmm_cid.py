# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from server.dmm_preview import (
        allowed_preview_url,
        digital_cids,
        normalize_code,
        guess_preview_urls,
        preview_candidates,
        preview_urls_for_code,
        remember_preview_url,
    )
except ImportError:
    allowed_preview_url = digital_cids = normalize_code = preview_candidates = None
    guess_preview_urls = preview_urls_for_code = remember_preview_url = None

HHB = "https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00001/ssis00001hhb.mp4"


def _need():
    if digital_cids is None:
        try:
            import pytest
        except ImportError:
            raise ImportError("server.dmm_preview") from None
        pytest.skip("server.dmm_preview not available")


def test_digital_cids():
    _need()
    assert "ssis00001" in digital_cids("ssis-001")
    assert "abf00341" in digital_cids("ABF-341")
    assert any(str(c).lower().startswith("300mium") for c in digital_cids("300MIUM-001"))


def test_preview_url_and_allowlist():
    _need()
    assert normalize_code("SSIS-001") == "ssis-001"
    urls = preview_candidates("ssis00001", "hhb")
    assert HHB in urls
    assert allowed_preview_url(HHB) is True
    assert allowed_preview_url("https://evil.com/x.mp4") is False
    assert allowed_preview_url("https://www.dmm.co.jp/digital/videoa/-/detail/=/cid=ssis00001/") is False
    assert allowed_preview_url("https://cc3001.dmm.co.jp/digital/video/ssis00001.mp4") is False
    guessed = guess_preview_urls("ssis-001")
    assert HHB in guessed
    assert guessed[0] == HHB
    alt = "https://cc3001.dmm.co.jp/litevideo/freepv/s/ssi/ssis00001/ssis00001dm.mp4"
    remember_preview_url("ssis-001", alt)
    assert preview_urls_for_code("ssis-001")[0] == alt


if __name__ == "__main__":
    test_digital_cids()
    test_preview_url_and_allowlist()
    print("ok test_dmm_cid")
