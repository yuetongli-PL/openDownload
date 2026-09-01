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
SETTINGS_PATH = ROOT / "settings.json"
DESKTOP_ALIASES = {"", "desktop", "~/desktop", "~/桌面", "~"}

if str(PY_ROOT) not in sys.path:
    sys.path.insert(0, str(PY_ROOT))


def _windows_desktop() -> Path | None:
    try:
        import winreg
    except ImportError:
        return None
    keys = (
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
    )
    for hive in keys:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, hive) as key:
                raw, _ = winreg.QueryValueEx(key, "Desktop")
        except OSError:
            continue
        path = Path(os.path.expandvars(str(raw))).expanduser()
        if str(path).strip():
            return path
    return None


def _xdg_desktop() -> Path | None:
    env = os.environ.get("XDG_DESKTOP_DIR")
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    cfg = Path.home() / ".config" / "user-dirs.dirs"
    if not cfg.is_file():
        return None
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("XDG_DESKTOP_DIR="):
            continue
        raw = line.split("=", 1)[1].strip().strip('"')
        if raw:
            return Path(os.path.expandvars(raw)).expanduser()
    return None


def desktop_dir() -> Path:
    """本机桌面：Windows 注册表 / OneDrive / XDG / Desktop / 桌面。"""
    if os.name == "nt":
        win = _windows_desktop()
        if win:
            return win
    xdg = _xdg_desktop()
    if xdg:
        return xdg
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())
    for candidate in (
        home / "Desktop",
        home / "OneDrive" / "Desktop",
        home / "OneDrive" / "桌面",
        home / "桌面",
    ):
        if candidate.is_dir():
            return candidate
    return home / "Desktop"


def resolve_library(value: object) -> Path:
    raw = str(value or "").strip()
    folded = raw.lower()
    if folded in DESKTOP_ALIASES or raw == "桌面":
        return desktop_dir()
    return Path(raw).expanduser()


def persist_library(value: object) -> str:
    raw = str(value or "").strip()
    if raw.lower() in DESKTOP_ALIASES or raw == "桌面":
        return "desktop"
    path = Path(raw).expanduser()
    try:
        if path.resolve() == desktop_dir().resolve():
            return "desktop"
    except OSError:
        pass
    return str(path)


def load_settings() -> dict:
    data = {
        "library": "desktop",
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


def settings_public() -> dict:
    data = dict(load_settings())
    data["library"] = str(resolve_library(data.get("library")))
    data["desktop"] = str(desktop_dir())
    return data


def save_settings(patch: dict) -> dict:
    data = load_settings()
    data.update(patch)
    if "library" in data:
        data["library"] = persist_library(data.get("library"))
    SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return settings_public()


def library_dir() -> Path:
    path = resolve_library(load_settings().get("library"))
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
