# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.engine import detect
from server.progress import ProgressParser

sys.path.insert(0, str(ROOT / "python"))
from jable_user import name_variants, names_match  # noqa: E402


def test_jable_url_and_code():
    a = detect("https://jable.tv/videos/mfyd-180/")
    assert a["site"] == "jable" and a["kind"] == "video"
    b = detect("mfyd-180")
    assert b["site"] == "jable" and b["kind"] == "video"
    c = detect("https://jable.tv/hot/")
    assert c["site"] == "jable" and c["kind"] == "list"


def test_jable_name_fold():
    assert names_match("波多野结衣", "波多野結衣")
    variants = name_variants("波多野结衣")
    assert "波多野结衣" in variants
    assert "波多野結衣" in variants


def test_jable_catalog_shape():
    from server.jable_lists import catalog

    data = catalog()
    assert data["hot_terms"][0]["id"]
    assert any(g["name"] == "衣著" for g in data["groups"])
    assert data["categories"]


def test_jable_username():
    a = detect("https://jable.tv/models/yua-mikami/")
    assert a["site"] == "jable" and a["kind"] == "user"
    b = detect("yua-mikami", "jable")
    assert b["site"] == "jable" and b["kind"] == "user"
    c = detect("三上悠亜", "jable")
    assert c["site"] == "jable" and c["kind"] == "user"
    d = detect("mfyd-180", "jable")
    assert d["kind"] == "video"


def test_youtube_bot_check_opts_and_cookies():
    import tempfile

    from youtube_parse import (
        explain_youtube_error,
        is_youtube_bot_check,
        set_youtube_auth,
        ytdlp_base_opts,
    )

    try:
        opts = ytdlp_base_opts()
        clients = opts["extractor_args"]["youtube"]["player_client"]
        assert clients[0] == "tv"
        assert "web" in clients
        assert "cookiefile" not in opts
        msg = "ERROR: [youtube] -xP1WpahG5I: Sign in to confirm you’re not a bot"
        assert is_youtube_bot_check(msg)
        hint = explain_youtube_error(msg)
        assert "cookies.txt" in hint or "Chrome" in hint
        with tempfile.TemporaryDirectory() as raw:
            cookie = Path(raw) / "youtube_cookie.txt"
            cookie.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tx\n", encoding="utf-8")
            set_youtube_auth(cookiefile=cookie)
            attached = ytdlp_base_opts()
            assert attached.get("cookiefile") == str(cookie)
        set_youtube_auth(browser="chrome")
        browsed = ytdlp_base_opts()
        assert browsed.get("cookiesfrombrowser") == ("chrome",)
        assert "cookiefile" not in browsed
    finally:
        set_youtube_auth()


def test_youtube_url_and_handle():
    a = detect("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert a["site"] == "youtube" and a["kind"] == "video"
    b = detect("@OutdoorBoys")
    assert b["site"] == "youtube" and b["kind"] == "channel"
    c = detect("dQw4w9WgXcQ")
    assert c["site"] == "youtube" and c["kind"] == "video"
    d = detect("https://www.youtube.com/@OutdoorBoys")
    assert d["site"] == "youtube" and d["kind"] == "channel"


def test_douyin_url():
    a = detect("https://www.douyin.com/video/7123456789012345678")
    assert a["site"] == "douyin"
    b = detect("bbj0817_", "douyin")
    assert b["site"] == "douyin" and b["kind"] == "user"


def test_auto_needs_site_for_bare_name():
    a = detect("somebody")
    assert a["kind"] == "need-site"


def test_router_lock():
    a = detect("PewDiePie", "youtube")
    assert a["site"] == "youtube" and a["kind"] == "channel"
    b = detect("mfyd-180", "jable")
    assert b["site"] == "jable" and b["kind"] == "video"


def test_tidy_keeps_mp4_and_jpg(tmp_path=None):
    import tempfile

    from server.cleanup import tidy_folder

    with tempfile.TemporaryDirectory() as raw:
        folder = Path(raw)
        (folder / "clip.mp4").write_bytes(b"mp4-data-xxxx")
        (folder / "clip.webp").write_bytes(b"webp")
        (folder / "clip.jpg").write_bytes(b"jpeg-bytes")
        (folder / "meta.json").write_text("{}", encoding="utf-8")
        (folder / "dash.txt").write_text("x", encoding="utf-8")
        (folder / "clip.ts").write_bytes(b"ts")
        extra = folder / "stt-chunks"
        extra.mkdir()
        (extra / "a.json").write_text("{}", encoding="utf-8")
        tidy_folder(folder, ffmpeg=None)
        names = sorted(p.name for p in folder.iterdir())
        assert names == ["clip.jpg", "clip.mp4"]


def test_task_emit_progress_snapshot():
    from server.jobs import Task
    from server.progress import ProgressParser

    task = Task("download", {})
    parser = ProgressParser(1)
    snap = parser.start_item(0, "YouTube abc")
    task.emit("progress", **snap)
    assert task.label == "YouTube abc"
    assert task.percent >= 0


def test_library_scan_lists_media(tmp_path=None):
    import tempfile

    from server.app import _library_scan

    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        folder = root / "youtube"
        folder.mkdir()
        (folder / "clip.mp4").write_bytes(b"mp4-data-xxxx")
        (folder / "notes.txt").write_text("x", encoding="utf-8")
        data = _library_scan(root)
        youtube = next(site for site in data["sites"] if site["site"] == "youtube")
        assert youtube["count"] == 1
        assert youtube["recent"][0]["name"] == "clip.mp4"


def test_progress_yt_and_decrypt():
    p = ProgressParser(1)
    p.feed("[download]  40.5% of 12.0MiB at  2.00MiB/s ETA 00:04")
    snap = p.snapshot()
    assert 39 <= snap["percent"] <= 42
    p.feed("decrypt: 50/100  20.0 MB  80 seg/s")
    assert p.snapshot()["percent"] >= 40


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("ok", name)
    print("all passed")
