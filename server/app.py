# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .engine import detect, health
from .jable_lists import catalog as jable_catalog
from .jobs import RUNNER
from .paths import WEB_ROOT, cookie_path, library_dir, load_settings, save_settings

app = FastAPI(title="openDownload", docs_url=None, redoc_url=None)


class JableBrowseIn(BaseModel):
    mode: str = ""
    term: str = ""
    category: str = ""
    group: str = ""
    tag: str = ""
    model: str = ""
    pages: int = 2


class ParseIn(BaseModel):
    query: str = ""
    site: str = "auto"
    limit: int = 40
    tab: str = ""
    jable: JableBrowseIn | None = None


class DownloadIn(BaseModel):
    parse_id: str
    ids: list[str] = Field(default_factory=list)
    quality: str = "1080p"
    subs: bool = False
    workers: int | None = None


class SettingsIn(BaseModel):
    library: str | None = None
    limit: int | None = None
    workers: int | None = None


class CookieIn(BaseModel):
    text: str


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    return health()


@app.get("/api/settings")
def api_settings() -> dict[str, Any]:
    return load_settings()


@app.post("/api/settings")
def api_settings_save(body: SettingsIn) -> dict[str, Any]:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "library" in patch:
        path = Path(str(patch["library"])).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        patch["library"] = str(path)
    return save_settings(patch)


@app.post("/api/cookie")
def api_cookie(body: CookieIn) -> dict[str, Any]:
    text = (body.text or "").strip()
    if len(text) < 20:
        raise HTTPException(400, "cookie 太短")
    dest = cookie_path()
    dest.write_text(text + "\n", encoding="utf-8")
    return {"ok": True, "path": str(dest)}


@app.get("/api/jable/catalog")
def api_jable_catalog() -> dict[str, Any]:
    return jable_catalog()


@app.post("/api/detect")
def api_detect(body: ParseIn) -> dict[str, Any]:
    if body.jable and body.jable.mode in {"hot", "pick"}:
        return {"site": "jable", "kind": body.jable.mode, "query": body.query or body.jable.mode, "url": ""}
    return detect(body.query, body.site)


@app.post("/api/parse")
def api_parse(body: ParseIn) -> dict[str, Any]:
    jable = body.jable.model_dump() if body.jable and body.jable.mode in {"hot", "pick"} else None
    query = (body.query or "").strip()
    if not query and not jable:
        raise HTTPException(400, "请输入链接或选择热门 / 選片")
    task = RUNNER.submit_parse(query, body.site, max(0, body.limit), body.tab, jable=jable)
    return task.snapshot()


@app.post("/api/download")
def api_download(body: DownloadIn) -> dict[str, Any]:
    try:
        task = RUNNER.submit_download(
            body.parse_id,
            body.ids,
            quality=body.quality,
            subs=body.subs,
            workers=body.workers,
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return task.snapshot()


@app.get("/api/tasks/{task_id}")
def api_task(task_id: str) -> dict[str, Any]:
    task = RUNNER.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task.snapshot()


@app.post("/api/tasks/{task_id}/cancel")
def api_cancel(task_id: str) -> dict[str, Any]:
    task = RUNNER.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    task.cancel()
    return task.snapshot()


@app.get("/api/tasks/{task_id}/stream")
def api_stream(task_id: str) -> StreamingResponse:
    task = RUNNER.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")

    def gen():
        for rec in task.iter_events():
            yield f"data: {json.dumps(rec, ensure_ascii=False)}\n\n"
        yield "data: {\"event\":\"close\"}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/proxy")
def api_proxy(url: str) -> Response:
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "bad url")
    host = parsed.netloc.lower()
    referer = "https://jable.tv/" if "jable.tv" in host else f"{parsed.scheme}://{parsed.netloc}/"
    if "douyin" in host or "byteimg" in host or "tiktokcdn" in host:
        referer = "https://www.douyin.com/"
    if "ytimg" in host or "youtube" in host or "ggpht" in host:
        referer = "https://www.youtube.com/"
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36"
    data = b""
    ctype = "image/jpeg"
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if curl:
        result = subprocess.run(
            [
                curl,
                "-sL",
                "--max-time",
                "20",
                "-A",
                ua,
                "-H",
                f"Referer: {referer}",
                "-H",
                "Accept: image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                raw,
            ],
            check=False,
            capture_output=True,
        )
        data = result.stdout or b""
    if len(data) < 80:
        req = Request(
            raw,
            headers={
                "User-Agent": ua,
                "Referer": referer,
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
        try:
            with urlopen(req, timeout=20) as resp:
                data = resp.read()
                ctype = resp.headers.get("Content-Type") or ctype
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, str(exc)) from exc
    if data[:3] == b"\xff\xd8\xff":
        ctype = "image/jpeg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        ctype = "image/png"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ctype = "image/webp"
    if len(data) < 80:
        raise HTTPException(502, "cover download too small")
    return Response(content=data, media_type=ctype, headers={"Cache-Control": "public, max-age=3600"})


MEDIA_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3"}


def _library_scan(root: Path, *, limit: int = 24) -> dict[str, Any]:
    sites: list[dict[str, Any]] = []
    scanned = 0
    for name in ("jable", "youtube", "douyin"):
        folder = root / name
        files: list[dict[str, Any]] = []
        total = 0
        if folder.is_dir():
            found: list[Path] = []
            for path in folder.rglob("*"):
                scanned += 1
                if scanned > 800:
                    break
                if not path.is_file() or path.suffix.lower() not in MEDIA_EXT:
                    continue
                total += 1
                found.append(path)
            found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for path in found[:limit]:
                stat = path.stat()
                files.append(
                    {
                        "name": path.name,
                        "rel": str(path.relative_to(root)),
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    }
                )
        sites.append({"site": name, "count": total, "recent": files})
    return {"path": str(root), "sites": sites}


@app.get("/api/library")
def api_library() -> dict[str, Any]:
    root = library_dir()
    root.mkdir(parents=True, exist_ok=True)
    return _library_scan(root)


@app.post("/api/open-library")
def api_open_library() -> dict[str, Any]:
    path = library_dir()
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        os.system(f'xdg-open "{path}"')
    return {"ok": True, "path": str(path)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


if WEB_ROOT.is_dir():
    app.mount("/static", StaticFiles(directory=str(WEB_ROOT)), name="static")
