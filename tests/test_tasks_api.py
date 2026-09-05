# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from server.app import app
from server.jobs import RUNNER, Task, read_history


def _reset_runner() -> None:
    with RUNNER._lock:
        RUNNER.tasks.clear()
        RUNNER._parse_queue.clear()
        RUNNER._download_queue.clear()


def _wait_status(task: Task, wanted: set[str], timeout: float = 3.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if task.status in wanted:
            return task.status
        time.sleep(0.02)
    return task.status


def test_snapshot_new_fields():
    parse = Task("parse", {"query": "hello world", "site": "youtube"})
    snap = parse.snapshot()
    assert snap["title"] == "hello world"
    assert snap["site"] == "youtube"
    assert snap["count"] == 0
    assert snap["finished"] is None
    assert snap["live"] is True

    parse.preview = {"title": "Full Title", "items": [{}, {}]}
    snap = parse.snapshot()
    assert snap["title"] == "Full Title"
    assert snap["count"] == 2

    long_q = "x" * 100
    assert Task("parse", {"query": long_q, "site": "auto"}).snapshot()["title"] == "x" * 80

    download = Task(
        "download",
        {"ids": ["a", "b"], "preview": {"title": "Album", "site": "youtube"}},
    )
    snap = download.snapshot()
    assert snap["title"] == "Album"
    assert snap["site"] == "youtube"
    assert snap["count"] == 2

    jable = Task("download", {"ids": ["abp-123"], "jable_code": "abp-123", "preview": None})
    snap = jable.snapshot()
    assert snap["title"] == "ABP-123"
    assert snap["site"] == "jable"
    assert snap["count"] == 1


def test_download_terminal_writes_history_and_tasks_api(tmp_path, monkeypatch):
    monkeypatch.setattr("server.paths.library_dir", lambda: tmp_path)
    _reset_runner()
    client = TestClient(app)

    older = Task(
        "download",
        {
            "ids": ["one"],
            "preview": {"title": "Older Title", "site": "youtube"},
        },
    )
    older.created = time.time() - 20
    older.status = "done"
    older.percent = 100
    older.phase = "done"
    older.result = {"ok": True, "count": 1, "cwd": str(tmp_path / "youtube")}
    older.emit("done", status="done", percent=100, phase="done")

    newer = Task(
        "download",
        {"ids": ["abp-001"], "jable_code": "abp-001", "preview": None},
    )
    newer.created = time.time()
    newer.status = "done"
    newer.percent = 88
    newer.phase = "done"
    RUNNER.tasks[newer.id] = newer
    newer.emit("done", status="done", percent=88, phase="done")

    hist_path = tmp_path / "_tasks.json"
    assert hist_path.is_file()
    blob = json.loads(hist_path.read_text(encoding="utf-8"))
    assert isinstance(blob, list)
    ids = {row["id"] for row in blob}
    assert older.id in ids
    assert newer.id in ids
    older_row = next(row for row in blob if row["id"] == older.id)
    assert older_row["title"] == "Older Title"
    assert older_row["site"] == "youtube"
    assert older_row["count"] == 1
    assert older_row["finished"]
    assert older_row["result"]["cwd"]

    data = client.get("/api/tasks", params={"limit": 50}).json()
    items = data["items"]
    assert [row["id"] for row in items[:2]] == [newer.id, older.id]
    live_row = next(row for row in items if row["id"] == newer.id)
    hist_row = next(row for row in items if row["id"] == older.id)
    assert live_row["live"] is True
    assert hist_row["live"] is False
    assert live_row["percent"] == 88
    assert hist_row["percent"] == 100
    assert sum(1 for row in items if row["id"] == newer.id) == 1

    running = Task("download", {"ids": ["x"], "jable_code": "x-1"})
    running.status = "running"
    RUNNER.tasks[running.id] = running
    assert client.delete(f"/api/tasks/{running.id}").status_code == 409

    assert client.delete("/api/tasks/no-such-id").status_code == 404

    gone = client.delete(f"/api/tasks/{newer.id}")
    assert gone.status_code == 200
    assert gone.json() == {"ok": True}
    assert newer.id not in {row["id"] for row in client.get("/api/tasks").json()["items"]}
    assert newer.id not in {row["id"] for row in read_history()}

    leftover = client.delete(f"/api/tasks/{older.id}")
    assert leftover.status_code == 200


def test_dual_channel_parse_not_blocked_by_download(tmp_path, monkeypatch):
    monkeypatch.setattr("server.paths.library_dir", lambda: tmp_path)
    _reset_runner()

    def slow_download(task: Task) -> None:
        time.sleep(1.0)
        task.result = {"ok": True, "count": 1, "cwd": str(tmp_path)}

    def instant_parse(task: Task) -> None:
        task.preview = {"site": "youtube", "title": "instant", "items": []}

    monkeypatch.setattr(RUNNER, "_run_download", slow_download)
    monkeypatch.setattr(RUNNER, "_run_parse", instant_parse)

    download = None
    try:
        t0 = time.time()
        download = RUNNER.submit_jable_save("lulu-445")
        assert _wait_status(download, {"running"}, timeout=1.0) == "running"
        parse = RUNNER.submit_parse("anything", "youtube", 5, "")
        assert _wait_status(parse, {"done", "error"}, timeout=0.8) == "done"
        assert parse.preview and parse.preview["title"] == "instant"
        assert download.status == "running"
        assert time.time() - t0 < 0.95
    finally:
        if download is not None:
            _wait_status(download, {"done", "error", "cancelled"}, timeout=3.0)
        _reset_runner()
