# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PY = ROOT / "python"
if str(PY) not in sys.path:
    sys.path.insert(0, str(PY))

DENIED = """
<title>Access denied | jable.tv used Cloudflare to restrict access | jable.tv | Cloudflare</title>
<h1><span data-translate="error">Error</span><span>1015</span></h1>
<h2>You are being rate limited</h2>
<p>The owner of this website (jable.tv) has banned you temporarily from accessing this website.</p>
"""

CHALLENGE = """
<title>Just a moment...</title>
<div id="cf-wrapper" class="cf-browser-verification">
  <div id="challenge-platform"></div>
</div>
"""

OK_PAGE = """
<html><head>
  <title>FNS-247 - Jable.TV</title>
  <meta property="og:title" content="FNS-247">
  <meta property="og:url" content="https://jable.tv/videos/fns-247/">
</head>
<body>
  <video id="player" poster="https://example.com/a.jpg"></video>
  <script>var hlsUrl = 'https://cdn.example/hls/fns-247/1735689600/index.m3u8';</script>
</body></html>
"""


def test_cloudflare_kind_denied():
    from jable_http import cloudflare_kind, is_cloudflare

    assert cloudflare_kind(DENIED) == "denied"
    assert is_cloudflare(DENIED)
    assert cloudflare_kind(DENIED.encode("utf-8")) == "denied"


def test_cloudflare_kind_challenge():
    from jable_http import cloudflare_kind, is_cloudflare

    assert cloudflare_kind(CHALLENGE) == "challenge"
    assert is_cloudflare(CHALLENGE)


def test_cloudflare_kind_ok_page():
    from jable_http import cloudflare_kind, is_cloudflare

    assert cloudflare_kind(OK_PAGE) == ""
    assert not is_cloudflare(OK_PAGE)


def test_looks_like_list_rejects_denied():
    from jable_hot import looks_like_list

    assert not looks_like_list(DENIED)
    assert not looks_like_list(CHALLENGE)


def test_looks_like_video_page_rejects_denied():
    from server.jable_inspect import _looks_like_video_page

    assert not _looks_like_video_page(DENIED)
    assert not _looks_like_video_page(CHALLENGE)
    assert _looks_like_video_page(OK_PAGE)


def test_note_denied_pauses_crawlers():
    from jable_http import _note_cloudflare, blocked_remaining, is_blocked, note_rate_limit

    kind = _note_cloudflare(DENIED, "exit=0 http=429 bytes=100")
    assert kind == "denied"
    assert is_blocked()
    assert blocked_remaining() > 60
    note_rate_limit(0)


if __name__ == "__main__":
    test_cloudflare_kind_denied()
    test_cloudflare_kind_challenge()
    test_cloudflare_kind_ok_page()
    test_looks_like_list_rejects_denied()
    test_looks_like_video_page_rejects_denied()
    test_note_denied_pauses_crawlers()
    print("ok test_cloudflare")
