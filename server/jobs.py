# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Callable, Iterator

from . import paths
from .cleanup import tidy_command
from .engine import build_commands, preview as run_preview, public_preview
from .paths import PY_ROOT, find_ffmpeg
from .progress import ProgressParser

LogFn = Callable[[str], None]

_HISTORY_LOCK = threading.Lock()
_HISTORY_MAX = 200
_MEM_MAX = 300
_TERMINAL = {"done", "error", "cancelled"}


def _kill_tree(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
        return
    try:
        os.kill(pid, 15)
    except OSError:
        pass


def _history_path() -> Path:
    return paths.library_dir() / "_tasks.json"


def _read_history_unlocked() -> list[dict[str, Any]]:
    path = _history_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return []


def _write_history_unlocked(items: list[dict[str, Any]]) -> None:
    root = paths.library_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "_tasks.json"
    payload = json.dumps(items, ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(prefix="_tasks.", suffix=".tmp", dir=str(root))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
            fh.flush()
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_history() -> list[dict[str, Any]]:
    with _HISTORY_LOCK:
        return _read_history_unlocked()


def persist_download_task(task: Task) -> None:
    if task.kind != "download" or getattr(task, "_persisted", False):
        return
    if task.status not in _TERMINAL:
        return
    task._persisted = True
    rec = history_record(task)
    with _HISTORY_LOCK:
        items = [row for row in _read_history_unlocked() if str(row.get("id") or "") != rec["id"]]
        items.append(rec)
        if len(items) > _HISTORY_MAX:
            items = items[-_HISTORY_MAX:]
        _write_history_unlocked(items)


def remove_history(task_id: str) -> bool:
    with _HISTORY_LOCK:
        items = _read_history_unlocked()
        kept = [row for row in items if str(row.get("id") or "") != task_id]
        if len(kept) == len(items):
            return False
        _write_history_unlocked(kept)
        return True


def history_record(task: Task) -> dict[str, Any]:
    snap = task.snapshot()
    result = snap.get("result")
    if isinstance(result, dict) and "cwd" in result:
        result = {"cwd": result.get("cwd") or ""}
    return {
        "id": snap["id"],
        "kind": snap["kind"],
        "title": snap.get("title") or "",
        "site": snap.get("site") or "",
        "status": snap["status"],
        "count": snap.get("count") or 0,
        "created": snap["created"],
        "finished": snap.get("finished"),
        "error": snap.get("error") or "",
        "result": result,
        "percent": snap.get("percent"),
        "phase": snap.get("phase") or "",
    }


def history_item(rec: dict[str, Any]) -> dict[str, Any]:
    percent = rec.get("percent")
    if percent is None:
        percent = 100
    return {
        "id": rec.get("id") or "",
        "kind": rec.get("kind") or "download",
        "title": rec.get("title") or "",
        "site": rec.get("site") or "",
        "status": rec.get("status") or "",
        "count": rec.get("count") or 0,
        "created": rec.get("created"),
        "finished": rec.get("finished"),
        "error": rec.get("error") or "",
        "result": rec.get("result"),
        "percent": percent,
        "phase": rec.get("phase") or "",
        "live": False,
    }


class Task:
    def __init__(self, kind: str, payload: dict[str, Any]) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.payload = payload
        self.status = "queued"
        self.percent = 0
        self.phase = "queued"
        self.label = "排队"
        self.error = ""
        self.created = time.time()
        self.updated = self.created
        self.finished: float | None = None
        self.events: deque[dict[str, Any]] = deque(maxlen=800)
        self.preview: dict[str, Any] | None = None
        self.result: dict[str, Any] | None = None
        self.proc: subprocess.Popen[str] | None = None
        self._cv = threading.Condition()
        self._seq = 0
        self._persisted = False

    def _preview_blob(self) -> dict[str, Any] | None:
        if isinstance(self.preview, dict):
            return self.preview
        raw = (self.payload or {}).get("preview")
        return raw if isinstance(raw, dict) else None

    def _title(self) -> str:
        p = self.payload or {}
        if self.kind == "parse":
            preview = self.preview if isinstance(self.preview, dict) else None
            if preview and preview.get("title"):
                return str(preview.get("title") or "")
            return str(p.get("query") or "")[:80]
        code = str(p.get("jable_code") or "").strip()
        if code:
            return code.upper()
        preview = self._preview_blob()
        if preview and preview.get("title"):
            return str(preview.get("title") or "")
        return ""

    def _site(self) -> str:
        p = self.payload or {}
        if self.kind == "parse":
            return str(p.get("site") or "")
        preview = self._preview_blob()
        if preview and preview.get("site"):
            return str(preview.get("site") or "")
        return "jable"

    def _count(self) -> int:
        p = self.payload or {}
        if self.kind == "download":
            ids = p.get("ids") or []
            return len(ids) if isinstance(ids, list) else 0
        preview = self.preview if isinstance(self.preview, dict) else None
        items = (preview or {}).get("items") if preview else None
        return len(items) if isinstance(items, list) else 0

    def _mark_finished(self) -> None:
        if self.finished is None:
            self.finished = time.time()

    def emit(self, event: str, **fields: Any) -> None:
        self._seq += 1
        rec = {"event": event, "seq": self._seq, "ts": time.time(), **fields}
        if "percent" in fields:
            self.percent = int(fields["percent"])
        if "phase" in fields:
            self.phase = str(fields["phase"])
        if "label" in fields:
            self.label = str(fields["label"])
        self.updated = rec["ts"]
        if event == "done":
            status = str(fields.get("status") or self.status)
            if status in _TERMINAL and self.status not in _TERMINAL:
                self.status = status
            if self.status in _TERMINAL:
                self._mark_finished()
                persist_download_task(self)
        elif event == "error" and self.status in {"error", "cancelled"}:
            self._mark_finished()
            persist_download_task(self)
        with self._cv:
            self.events.append(rec)
            self._cv.notify_all()

    def snapshot(self) -> dict[str, Any]:
        out = {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "percent": self.percent,
            "phase": self.phase,
            "label": self.label,
            "error": self.error,
            "created": self.created,
            "updated": self.updated,
            "title": self._title(),
            "site": self._site(),
            "count": self._count(),
            "finished": self.finished,
            "live": True,
        }
        if self.preview is not None:
            out["preview"] = public_preview(self.preview)
        if self.result is not None:
            out["result"] = self.result
        return out

    def iter_events(self) -> Iterator[dict[str, Any]]:
        last = 0
        while True:
            with self._cv:
                while True:
                    batch = [e for e in self.events if int(e.get("seq") or 0) > last]
                    alive = self.status in {"queued", "running"}
                    if batch or not alive:
                        break
                    self._cv.wait(timeout=1.0)
            if not batch and not alive:
                return
            for rec in batch:
                last = int(rec.get("seq") or last)
                yield rec

    def cancel(self) -> None:
        if self.status not in {"queued", "running"}:
            return
        self.status = "cancelled"
        self.error = "已取消"
        self._mark_finished()
        persist_download_task(self)
        if self.proc and self.proc.poll() is None:
            _kill_tree(self.proc.pid)
        self.emit("error", message="已取消", percent=self.percent, phase="cancelled")
        self.emit("done", status="cancelled")


class JobRunner:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        self._parse_queue: deque[Task] = deque()
        self._download_queue: deque[Task] = deque()
        self._parse_worker = threading.Thread(target=self._loop, args=("parse",), name="od-parse", daemon=True)
        self._download_worker = threading.Thread(
            target=self._loop, args=("download",), name="od-download", daemon=True
        )
        self._parse_worker.start()
        self._download_worker.start()
        read_history()

    def submit_parse(
        self,
        query: str,
        site: str,
        limit: int,
        tab: str,
        jable: dict[str, Any] | None = None,
    ) -> Task:
        task = Task(
            "parse",
            {"query": query, "site": site, "limit": limit, "tab": tab, "jable": jable},
        )
        return self._enqueue(task)

    def submit_download(
        self,
        parse_id: str,
        ids: list[str],
        *,
        quality: str,
        subs: bool,
        workers: int | None,
    ) -> Task:
        with self._lock:
            parent = self.tasks.get(parse_id)
        if not parent or not parent.preview:
            raise RuntimeError("找不到解析结果，请重新解析")
        task = Task(
            "download",
            {
                "parse_id": parse_id,
                "ids": ids,
                "quality": quality,
                "subs": subs,
                "workers": workers,
                "preview": parent.preview,
            },
        )
        return self._enqueue(task)

    def submit_jable_save(
        self,
        code: str,
        *,
        subs: bool = False,
        workers: int | None = None,
    ) -> Task:
        raw = (code or "").strip().lower()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,40}", raw):
            raise RuntimeError("番号无效")
        task = Task(
            "download",
            {
                "parse_id": "",
                "ids": [raw],
                "quality": "1080p",
                "subs": bool(subs),
                "workers": workers,
                "preview": None,
                "jable_code": raw,
            },
        )
        return self._enqueue(task)

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self.tasks.get(task_id)

    def list_items(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or 50), 200))
        with self._lock:
            live = [task.snapshot() for task in self.tasks.values()]
        seen = {str(item.get("id") or "") for item in live}
        items = list(live)
        for rec in read_history():
            rid = str(rec.get("id") or "")
            if not rid or rid in seen:
                continue
            items.append(history_item(rec))
            seen.add(rid)
        items.sort(key=lambda item: float(item.get("created") or 0), reverse=True)
        return items[:limit]

    def delete_task(self, task_id: str) -> str:
        with self._lock:
            task = self.tasks.get(task_id)
            if task is not None and task.status in {"queued", "running"}:
                return "busy"
            existed_live = task is not None
            if existed_live:
                self.tasks.pop(task_id, None)
                for queue in (self._parse_queue, self._download_queue):
                    try:
                        queue.remove(task)  # type: ignore[arg-type]
                    except ValueError:
                        pass
        existed_hist = remove_history(task_id)
        if not existed_live and not existed_hist:
            return "missing"
        return "ok"

    def _enqueue(self, task: Task) -> Task:
        with self._lock:
            self.tasks[task.id] = task
            if task.kind == "parse":
                self._parse_queue.append(task)
            else:
                self._download_queue.append(task)
            self._prune_locked()
        return task

    def _prune_locked(self) -> None:
        extra = len(self.tasks) - _MEM_MAX
        if extra <= 0:
            return
        inactive = [task for task in self.tasks.values() if task.status not in {"queued", "running"}]
        inactive.sort(key=lambda task: task.created)
        for task in inactive[:extra]:
            self.tasks.pop(task.id, None)

    def _loop(self, kind: str) -> None:
        while True:
            with self._lock:
                queue = self._parse_queue if kind == "parse" else self._download_queue
                task = queue.popleft() if queue else None
            if task is None:
                time.sleep(0.05)
                continue
            if task.status == "cancelled":
                continue
            task.status = "running"
            task.emit("log", text="开始", phase="running", percent=1, label="开始")
            try:
                if task.kind == "parse":
                    self._run_parse(task)
                else:
                    self._run_download(task)
                if task.status == "cancelled":
                    continue
                task.status = "done"
                task.emit("done", status="done", percent=100, phase="done", label="完成")
            except Exception as exc:  # noqa: BLE001
                if task.status == "cancelled":
                    continue
                task.status = "error"
                task.error = str(exc)
                task.emit("error", message=str(exc), phase="error", label=str(exc))
                task.emit("done", status="error")

    def _run_parse(self, task: Task) -> None:
        p = task.payload

        def log(line: str) -> None:
            text = (line or "").rstrip()
            if text:
                task.emit("log", text=text, label=text[:140], phase="parse", percent=max(task.percent, 8))

        task.emit("progress", percent=5, phase="parse", label="识别并解析")
        result = run_preview(
            p["query"],
            p["site"],
            limit=int(p.get("limit") or 40),
            tab=str(p.get("tab") or ""),
            jable=p.get("jable") if isinstance(p.get("jable"), dict) else None,
            log=log,
        )
        task.preview = result
        task.percent = 100
        task.phase = "confirm"
        task.label = result.get("hint") or "请确认下载内容"
        task.emit("preview", preview=public_preview(result), percent=100, phase="confirm", label=task.label)

    def _run_download(self, task: Task) -> None:
        p = task.payload
        preview = p.get("preview")
        code = str(p.get("jable_code") or "").strip().lower()
        if not preview and code:
            task.emit("progress", percent=4, phase="parse", label="获取播放地址")
            from .jable_lists import play_cached, play_info

            data = play_cached(code) or play_info(code)
            hls = str((data or {}).get("hls") or "").strip()
            if not hls:
                raise RuntimeError("没有播放地址，无法下载")
            cid = str((data or {}).get("id") or code).strip().lower() or code
            preview = {
                "site": "jable",
                "kind": "video",
                "title": (data or {}).get("title") or cid,
                "url": (data or {}).get("url") or f"https://jable.tv/videos/{cid}/",
                "cover": (data or {}).get("cover") or "",
                "items": [{"id": cid, "title": (data or {}).get("title") or cid}],
                "store": {
                    cid: {
                        "url": (data or {}).get("url") or "",
                        "code": cid,
                        "raw": data,
                    }
                },
                "downloadable": True,
            }
            p["preview"] = preview
            p["ids"] = [cid]
            task.emit("progress", percent=8, phase="download", label=f"开始下载 {cid.upper()}")
        if not preview:
            raise RuntimeError("找不到解析结果，请重新解析")
        cmds = build_commands(
            preview,
            list(p.get("ids") or []),
            quality=str(p.get("quality") or "1080p"),
            subs=bool(p.get("subs")),
            workers=p.get("workers"),
        )
        parser = ProgressParser(total_items=len(cmds))
        ffmpeg = find_ffmpeg()
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONPATH"] = str(PY_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        if ffmpeg:
            env["PATH"] = str(ffmpeg.parent) + os.pathsep + env.get("PATH", "")

        failures: list[str] = []
        for i, cmd in enumerate(cmds):
            if task.status == "cancelled":
                return
            snap = parser.start_item(i, cmd["label"])
            task.emit("progress", **snap)
            task.emit("log", text="+ " + " ".join(str(x) for x in cmd["argv"]))
            popen_kw: dict[str, Any] = {
                "args": cmd["argv"],
                "cwd": cmd["cwd"],
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "stdin": subprocess.DEVNULL,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "env": env,
                "bufsize": 1,
            }
            if os.name == "nt":
                popen_kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(**popen_kw)
            task.proc = proc
            assert proc.stdout is not None
            for line in _iter_proc_lines(proc.stdout):
                if task.status == "cancelled":
                    _kill_tree(proc.pid)
                    return
                task.emit("log", text=line)
                update = parser.feed(line)
                if update:
                    task.emit("progress", **update)
            code = proc.wait()
            task.proc = None
            if code != 0:
                failures.append(f"{cmd['label']} (exit {code})")
                task.emit("log", text=f"failed: {cmd['label']} exit {code}")
            else:
                parser.finish_item()
                task.emit("log", text=f"ok: {cmd['label']}")
                tidy_command(
                    cmd["cwd"],
                    str(cmd.get("id") or ""),
                    ffmpeg,
                    log=lambda line: task.emit("log", text=line),
                )
        if failures:
            raise RuntimeError("部分失败: " + "; ".join(failures))
        task.result = {"ok": True, "count": len(cmds), "cwd": cmds[0]["cwd"] if cmds else ""}
        task.emit("progress", percent=100, phase="done", label="下载完成")


def _iter_proc_lines(stream) -> Iterator[str]:
    buf = ""
    while True:
        chunk = stream.read(256)
        if not chunk:
            if buf.strip():
                yield buf.strip("\r\n")
            return
        buf += chunk
        while True:
            match = re.search(r"[\r\n]", buf)
            if not match:
                break
            line, buf = buf[: match.start()], buf[match.end() :]
            text = line.strip()
            if text:
                yield text


RUNNER = JobRunner()
