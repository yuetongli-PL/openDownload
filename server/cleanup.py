# -*- coding: utf-8 -*-
"""After a download, keep only the mp4 and a jpg cover in the work folder."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

LogFn = Callable[[str], None]

COVER_SRC = {".webp", ".png", ".jpeg", ".jpg"}
SKIP_DIR_NAMES = {".om-undo", "_queue"}


def _log(log: LogFn | None, msg: str) -> None:
    if log:
        log(msg)


def _to_jpg(src: Path, dest: Path, ffmpeg: Path | None) -> bool:
    if dest.is_file() and dest.stat().st_size > 0:
        return True
    if not ffmpeg or not src.is_file():
        if src.suffix.lower() in {".jpg", ".jpeg"}:
            try:
                if src.resolve() != dest.resolve():
                    shutil.copyfile(src, dest)
                return dest.is_file() and dest.stat().st_size > 0
            except OSError:
                return False
        return False
    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        str(dest),
    ]
    result = subprocess.run(cmd, check=False, capture_output=True)
    return result.returncode == 0 and dest.is_file() and dest.stat().st_size > 0


def tidy_folder(folder: Path, ffmpeg: Path | None = None, log: LogFn | None = None) -> None:
    if not folder.is_dir():
        return
    files = [p for p in folder.iterdir() if p.is_file()]
    dirs = [p for p in folder.iterdir() if p.is_dir()]
    mp4s = [p for p in files if p.suffix.lower() == ".mp4" and p.stat().st_size > 0]
    if not mp4s:
        return
    stem = mp4s[0].stem
    cover_dest = folder / f"{stem}.jpg"
    covers = [p for p in files if p.suffix.lower() in COVER_SRC]
    covers.sort(key=lambda p: (0 if p.suffix.lower() in {".jpg", ".jpeg"} else 1, -p.stat().st_size))
    have_jpg = False
    if cover_dest.is_file() and cover_dest.stat().st_size > 0:
        have_jpg = True
    else:
        for src in covers:
            if _to_jpg(src, cover_dest, ffmpeg):
                have_jpg = True
                break
    keep = {p.resolve() for p in mp4s}
    if have_jpg:
        keep.add(cover_dest.resolve())

    removed = 0
    for item in dirs:
        try:
            shutil.rmtree(item)
            removed += 1
        except OSError:
            pass
    for item in files:
        if item.resolve() in keep:
            continue
        try:
            item.unlink()
            removed += 1
        except OSError:
            pass
    _log(log, f"tidy {folder.name}: keep {len(keep)}  removed {removed}")


def work_folders(cwd: Path, item_id: str) -> list[Path]:
    folders: list[Path] = []
    if item_id and item_id != "batch":
        direct = cwd / item_id
        if direct.is_dir():
            folders.append(direct)
    if item_id == "batch" or not folders:
        for child in cwd.iterdir() if cwd.is_dir() else []:
            if not child.is_dir() or child.name in SKIP_DIR_NAMES:
                continue
            if any(p.suffix.lower() == ".mp4" for p in child.iterdir() if p.is_file()):
                folders.append(child)
    # unique
    seen: set[Path] = set()
    out: list[Path] = []
    for folder in folders:
        key = folder.resolve()
        if key in seen:
            continue
        seen.add(key)
        out.append(folder)
    return out


def tidy_command(cwd: str | Path, item_id: str, ffmpeg: Path | None, log: LogFn | None = None) -> None:
    root = Path(cwd)
    for folder in work_folders(root, item_id):
        tidy_folder(folder, ffmpeg=ffmpeg, log=log)
    queue = root / "_queue"
    if queue.is_dir():
        shutil.rmtree(queue, ignore_errors=True)
