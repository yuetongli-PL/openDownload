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


def test_build_commands_uses_hls_and_code():
    from server.engine import build_commands

    preview = {
        "site": "jable",
        "kind": "video",
        "store": {
            "lulu-445": {
                "url": "https://jable.tv/videos/lulu-445/",
                "code": "lulu-445",
                "raw": {
                    "hls": "https://cdn.example/hls/lulu-445/2000000000/index.m3u8",
                    "code": "lulu-445",
                },
            }
        },
        "downloadable": True,
    }
    cmds = build_commands(preview, ["lulu-445"], quality="1080p", subs=False, workers=8)
    assert len(cmds) == 1
    argv = [str(x) for x in cmds[0]["argv"]]
    joined = " ".join(argv)
    assert "jable_run.py" in joined
    assert "index.m3u8" in joined
    assert "jable.tv/videos/lulu-445" not in joined
    assert "--code" in argv
    assert argv[argv.index("--code") + 1] == "lulu-445"
    assert "--workers" in argv
    assert cmds[0]["id"] == "lulu-445"


def test_jable_run_strips_code_flag():
    from jable_run import guess_code

    assert guess_code("https://jable.tv/videos/lulu-445/") == "lulu-445"
    src = Path(ROOT / "python" / "jable_run.py").read_text(encoding="utf-8")
    assert "--code" in src
    assert "code_flag" in src


def test_progress_parser_jable_download_rises():
    from server.progress import ProgressParser

    parser = ProgressParser(total_items=1)
    parser.start_item(0, "Jable snos-276")
    p1 = parser.feed("[1/4] m3u8 url, skip page parse")
    p2 = parser.feed("[2/4] extract AES key and ts list")
    p3 = parser.feed("[3/4] download, decrypt, concat")
    p4 = parser.feed("download: 12/1800")
    p5 = parser.feed("download: 900/1800")
    p6 = parser.feed("decrypt: 200/1800")
    assert p1 and p1["percent"] >= 5
    assert p2["percent"] > p1["percent"]
    assert p4["percent"] >= p3["percent"]
    assert p5["percent"] > p4["percent"]
    assert p5["percent"] >= 40
    assert p6["percent"] >= p3["percent"]
    assert p5["percent"] < 100


def test_save_preview_prefers_play_cache():
    from server.jable_lists import play_cached, remember_play_html

    html = """
    <html><head><title>LULU-445 - Jable.TV</title></head>
    <body>
      <video poster="https://example.com/lulu-445.jpg"></video>
      <script>var hlsUrl = 'https://cdn.example/hls/lulu-445/2000000000/index.m3u8';</script>
    </body></html>
    """
    remember_play_html("lulu-445-save", "https://jable.tv/videos/lulu-445-save/", html)
    hit = play_cached("lulu-445-save")
    assert hit and hit.get("hls", "").endswith("index.m3u8")


if __name__ == "__main__":
    test_build_commands_uses_hls_and_code()
    test_jable_run_strips_code_flag()
    test_progress_parser_jable_download_rises()
    test_save_preview_prefers_play_cache()
    print("ok test_jable_download")
