# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY_ROOT = ROOT / "python"
WEB_ROOT = ROOT / "web"
DEFAULT_LIBRARY = ROOT / "library"
SETTINGS_PATH = ROOT / "settings.json"

if str(PY_ROOT) not in sys.path:
    sys.path.insert(0, str(PY_ROOT))


def load_settings() -> dict:
    data = {
        "library": str(DEFAULT_LIBRARY),
        "limit": 40,
        "workers": 64,
        "port": 8765,
    }
    if SETTINGS_PATH.is_file():
        try:
            blob = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(blob, dict):
                data.update({k: v for k, v in blob.items() if v is not None})
        except (OSError, json.JSONDecodeError):
            pass
    return data


def save_settings(patch: dict) -> dict:
    data = load_settings()
    data.update(patch)
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def library_dir() -> Path:
    path = Path(str(load_settings().get("library") or DEFAULT_LIBRARY)).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_python() -> str:
    return sys.executable


def find_ffmpeg() -> Path | None:
    for name in ("ffmpeg", "ffmpeg.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    roots: list[Path] = []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        winget = Path(local) / "Microsoft" / "WinGet"
        roots.append(winget / "Links" / "ffmpeg.exe")
        pkgs = winget / "Packages"
        if pkgs.is_dir():
            roots.extend(sorted(pkgs.glob("*FFmpeg*")))
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    roots.append(Path(pf) / "ffmpeg" / "bin" / "ffmpeg.exe")
    roots.append(Path(r"C:\ffmpeg\bin\ffmpeg.exe"))
    hits: list[Path] = []
    for root in roots:
        if root.is_file() and root.name.lower() == "ffmpeg.exe":
            hits.append(root)
            continue
        if root.is_dir():
            hits.extend(root.rglob("ffmpeg.exe"))
    if not hits:
        return None
    hits.sort(key=lambda p: (0 if "full" in str(p).lower() else 1, len(str(p))))
    return hits[0]


def cookie_path() -> Path:
    return PY_ROOT / "cookie.txt"
