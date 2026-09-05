# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import paths

MEDIA_EXT = {".mp4", ".mkv", ".webm", ".mov", ".m4a", ".mp3"}
COVER_EXT = (".jpg", ".jpeg", ".png", ".webp")
SITE_NAMES = ("jable", "youtube", "douyin")
CHUNK_SIZE = 1024 * 1024
SCAN_TTL = 10.0
MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

router = APIRouter()

_SCAN_LOCK = threading.Lock()
_SCAN_CACHE: dict[str, dict[str, Any]] = {}


class RevealIn(BaseModel):
    rel: str = ""


def _posix_rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _dir_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _cover_rel(media: Path, root: Path) -> str:
    stem = media.stem
    parent = media.parent
    for ext in COVER_EXT:
        cand = parent / f"{stem}{ext}"
        if cand.is_file():
            return _posix_rel(cand, root)
    return ""


def _iter_media(root: Path, site: str) -> list[Path]:
    folder = root / site
    if not folder.is_dir():
        return []
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [name for name in dirnames if not name.startswith("_")]
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix.lower() in MEDIA_EXT:
                found.append(path)
    return found


def _scan_root(root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for site in SITE_NAMES:
        for path in _iter_media(root, site):
            try:
                stat = path.stat()
            except OSError:
                continue
            items.append(
                {
                    "site": site,
                    "name": path.name,
                    "rel": _posix_rel(path, root),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "ext": path.suffix.lower().lstrip("."),
                    "cover": _cover_rel(path, root),
                }
            )
    return items


def _collect_media(root: Path) -> list[dict[str, Any]]:
    try:
        key = str(root.resolve())
    except OSError:
        key = str(root)
    mtimes = tuple(_dir_mtime(root / site) for site in SITE_NAMES)
    now = time.time()
    with _SCAN_LOCK:
        hit = _SCAN_CACHE.get(key)
        if hit and now - float(hit.get("ts") or 0) < SCAN_TTL and hit.get("mtimes") == mtimes:
            return list(hit["items"])
    items = _scan_root(root)
    with _SCAN_LOCK:
        _SCAN_CACHE[key] = {"ts": now, "mtimes": mtimes, "items": items}
    return list(items)


def _sites_payload(items: list[dict[str, Any]], *, recent_limit: int = 24) -> list[dict[str, Any]]:
    sites: list[dict[str, Any]] = []
    for name in SITE_NAMES:
        rows = [it for it in items if it["site"] == name]
        rows.sort(key=lambda it: float(it.get("mtime") or 0), reverse=True)
        recent = [
            {
                "name": it["name"],
                "rel": it["rel"],
                "size": it["size"],
                "mtime": it["mtime"],
            }
            for it in rows[: max(0, int(recent_limit))]
        ]
        sites.append({"site": name, "count": len(rows), "recent": recent})
    return sites


def library_scan(root: Path, *, limit: int = 24) -> dict[str, Any]:
    items = _collect_media(root)
    return {"path": str(root), "sites": _sites_payload(items, recent_limit=limit)}


def list_library(
    *,
    site: str = "",
    q: str = "",
    sort: str = "mtime",
    order: str = "desc",
    offset: int = 0,
    limit: int = 60,
) -> dict[str, Any]:
    root = paths.library_dir()
    root.mkdir(parents=True, exist_ok=True)
    items = _collect_media(root)
    site_f = (site or "").strip().lower()
    qn = (q or "").strip().lower()
    filtered = items
    if site_f:
        filtered = [it for it in filtered if it["site"] == site_f]
    if qn:
        filtered = [it for it in filtered if qn in str(it.get("name") or "").lower()]
    sort_key = sort if sort in {"mtime", "name", "size"} else "mtime"
    reverse = (order or "desc").strip().lower() != "asc"

    def keyfn(it: dict[str, Any]) -> Any:
        if sort_key == "name":
            return str(it.get("name") or "").lower()
        if sort_key == "size":
            return int(it.get("size") or 0)
        return float(it.get("mtime") or 0)

    filtered.sort(key=keyfn, reverse=reverse)
    offset = max(0, int(offset or 0))
    limit = max(1, min(int(limit or 60), 200))
    return {
        "path": str(root),
        "total": len(filtered),
        "sites": _sites_payload(items),
        "items": filtered[offset : offset + limit],
    }


def resolve_library_path(rel: str) -> Path:
    raw = (rel or "").strip()
    if not raw:
        raise HTTPException(400, "bad path")
    root = paths.library_dir().resolve()
    try:
        abs_path = Path(root, raw).resolve()
    except (OSError, ValueError) as exc:
        raise HTTPException(400, "bad path") from exc
    if not abs_path.is_relative_to(root):
        raise HTTPException(400, "bad path")
    return abs_path


def _parse_byte_range(header: str, size: int) -> tuple[int, int] | None:
    text = (header or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if not lowered.startswith("bytes="):
        return None
    spec = text.split("=", 1)[1].strip()
    if not spec or "," in spec:
        raise HTTPException(400, "bad range")
    if "-" not in spec:
        raise HTTPException(400, "bad range")
    start_s, end_s = spec.split("-", 1)
    try:
        if start_s == "" and end_s:
            length = int(end_s)
            if length <= 0 or size <= 0:
                raise HTTPException(416, "range not satisfiable")
            start = max(0, size - length)
            end = size - 1
        elif start_s and end_s == "":
            start = int(start_s)
            end = size - 1
        else:
            start = int(start_s)
            end = int(end_s)
    except ValueError as exc:
        raise HTTPException(400, "bad range") from exc
    if size <= 0 or start < 0 or end < start or start >= size:
        raise HTTPException(416, "range not satisfiable")
    return start, min(end, size - 1)


def _iter_file_range(path: Path, start: int, end: int) -> Iterator[bytes]:
    remaining = end - start + 1
    with path.open("rb") as fh:
        fh.seek(start)
        while remaining > 0:
            chunk = fh.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def open_library_dir() -> dict[str, Any]:
    path = paths.library_dir()
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        os.system(f'xdg-open "{path}"')
    return {"ok": True, "path": str(path)}


def reveal_library_path(rel: str) -> dict[str, Any]:
    abs_path = resolve_library_path(rel)
    if not abs_path.exists():
        raise HTTPException(404, "not found")
    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", str(abs_path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(abs_path.parent)])
    else:
        subprocess.Popen(["xdg-open", str(abs_path.parent)])
    return {"ok": True, "path": str(abs_path)}


@router.get("/api/library")
def api_library(
    site: str = "",
    q: str = "",
    sort: str = "mtime",
    order: str = "desc",
    offset: int = 0,
    limit: int = 60,
) -> dict[str, Any]:
    return list_library(site=site, q=q, sort=sort, order=order, offset=offset, limit=limit)


@router.get("/api/library/file")
def api_library_file(rel: str, request: Request) -> StreamingResponse:
    path = resolve_library_path(rel)
    if not path.is_file():
        raise HTTPException(404, "not found")
    size = path.stat().st_size
    ctype = MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
    headers = {
        "Cache-Control": "private, max-age=3600",
        "Accept-Ranges": "bytes",
    }
    parsed = _parse_byte_range(request.headers.get("Range") or "", size)
    if parsed is not None:
        start, end = parsed
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        headers["Content-Length"] = str(end - start + 1)
        return StreamingResponse(
            _iter_file_range(path, start, end),
            status_code=206,
            media_type=ctype,
            headers=headers,
        )
    headers["Content-Length"] = str(size)
    if size <= 0:
        return StreamingResponse(iter(()), status_code=200, media_type=ctype, headers=headers)
    return StreamingResponse(
        _iter_file_range(path, 0, size - 1),
        status_code=200,
        media_type=ctype,
        headers=headers,
    )


@router.post("/api/library/reveal")
def api_library_reveal(body: RevealIn) -> dict[str, Any]:
    return reveal_library_path(body.rel)


@router.post("/api/open-library")
def api_open_library() -> dict[str, Any]:
    return open_library_dir()
