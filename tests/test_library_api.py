# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from server.app import app
from server.app import _library_scan


def _seed_library(root: Path) -> None:
    jable = root / "jable"
    youtube = root / "youtube"
    hidden = jable / "_lists"
    jable.mkdir(parents=True)
    youtube.mkdir(parents=True)
    hidden.mkdir(parents=True)
    (jable / "a.mp4").write_bytes(b"aaaa")
    (jable / "a.jpg").write_bytes(b"jpg-bytes")
    (youtube / "b.mp4").write_bytes(b"bbbbbbbb")
    (hidden / "x.mp4").write_bytes(b"xxxx")
    now = 1_700_000_000.0
    os.utime(jable / "a.mp4", (now, now + 20))
    os.utime(youtube / "b.mp4", (now, now + 10))


def test_library_scan_compat(tmp_path):
    _seed_library(tmp_path)
    data = _library_scan(tmp_path)
    jable = next(site for site in data["sites"] if site["site"] == "jable")
    youtube = next(site for site in data["sites"] if site["site"] == "youtube")
    assert jable["count"] == 1
    assert youtube["count"] == 1
    assert jable["recent"][0]["name"] == "a.mp4"


def test_library_list_filter_sort_cover(tmp_path, monkeypatch):
    monkeypatch.setattr("server.paths.library_dir", lambda: tmp_path)
    _seed_library(tmp_path)
    client = TestClient(app)

    all_rows = client.get("/api/library").json()
    assert all_rows["path"] == str(tmp_path)
    assert all_rows["total"] == 2
    names = {row["name"] for row in all_rows["items"]}
    assert names == {"a.mp4", "b.mp4"}
    assert "x.mp4" not in names
    jable = next(site for site in all_rows["sites"] if site["site"] == "jable")
    assert jable["count"] == 1
    assert jable["recent"][0]["name"] == "a.mp4"
    a_row = next(row for row in all_rows["items"] if row["name"] == "a.mp4")
    b_row = next(row for row in all_rows["items"] if row["name"] == "b.mp4")
    assert a_row["cover"] == "jable/a.jpg"
    assert a_row["rel"] == "jable/a.mp4"
    assert a_row["ext"] == "mp4"
    assert b_row["cover"] == ""

    only_jable = client.get("/api/library", params={"site": "jable"}).json()
    assert only_jable["total"] == 1
    assert only_jable["items"][0]["name"] == "a.mp4"

    searched = client.get("/api/library", params={"q": "A"}).json()
    assert searched["total"] == 1
    assert searched["items"][0]["name"] == "a.mp4"

    by_name = client.get("/api/library", params={"sort": "name", "order": "asc"}).json()
    assert [row["name"] for row in by_name["items"]] == ["a.mp4", "b.mp4"]

    by_size = client.get("/api/library", params={"sort": "size", "order": "desc"}).json()
    assert [row["name"] for row in by_size["items"]] == ["b.mp4", "a.mp4"]

    page = client.get("/api/library", params={"sort": "name", "order": "asc", "offset": 1, "limit": 1}).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1
    assert page["items"][0]["name"] == "b.mp4"


def test_library_file_range_and_reveal(tmp_path, monkeypatch):
    monkeypatch.setattr("server.paths.library_dir", lambda: tmp_path)
    _seed_library(tmp_path)
    client = TestClient(app)
    payload = (tmp_path / "jable" / "a.mp4").read_bytes()

    full = client.get("/api/library/file", params={"rel": "jable/a.mp4"})
    assert full.status_code == 200
    assert full.content == payload
    assert full.headers["content-length"] == str(len(payload))
    assert full.headers["content-type"].startswith("video/mp4")
    assert "private, max-age=3600" in full.headers["cache-control"]

    partial = client.get(
        "/api/library/file",
        params={"rel": "jable/a.mp4"},
        headers={"Range": "bytes=0-2"},
    )
    assert partial.status_code == 206
    assert partial.content == payload[:3]
    assert partial.headers["content-range"] == f"bytes 0-2/{len(payload)}"
    assert partial.headers["content-length"] == "3"
    assert partial.headers["accept-ranges"] == "bytes"

    assert client.get("/api/library/file", params={"rel": "../x"}).status_code == 400
    assert client.get("/api/library/file", params={"rel": "jable/missing.mp4"}).status_code == 404

    called: dict[str, list[str]] = {}

    def fake_popen(args, **kwargs):
        called["args"] = list(args)

        class _Proc:
            pass

        return _Proc()

    monkeypatch.setattr("server.library.subprocess.Popen", fake_popen)
    revealed = client.post("/api/library/reveal", json={"rel": "jable/a.mp4"})
    assert revealed.status_code == 200
    body = revealed.json()
    assert body["ok"] is True
    assert body["path"].endswith("a.mp4")
    assert called["args"][0] in {"explorer", "xdg-open", "open"}

    assert client.post("/api/library/reveal", json={"rel": "../x"}).status_code == 400
