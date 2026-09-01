# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import html as html_lib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "out"
BASE = "https://jable.tv"
TAG_RE = re.compile(r"<[^>]+>")
SAFE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def die(msg: str, code: int = 1) -> None:
    print(f"错误：{msg}", file=sys.stderr)
    raise SystemExit(code)


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def launched_bare(argv: list[str] | None) -> bool:
    raw = sys.argv[1:] if argv is None else argv
    return not raw


def print_intro(title: str, *lines: str) -> None:
    text = " ".join(s.strip() for s in lines if s and s.strip())
    print(flush=True)
    if text:
        print(f"{title}：{text}", flush=True)
    else:
        print(title, flush=True)
    print(flush=True)


def prompt_line(msg: str) -> str:
    try:
        return input(msg).strip()
    except EOFError:
        return ""


def unescape_text(raw: str) -> str:
    text = TAG_RE.sub("", raw or "")
    text = html_lib.unescape(text)
    text = text.replace("\xa0", " ").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", text).strip()


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_filename(name: str, limit: int = 80) -> str:
    name = SAFE_NAME_RE.sub("_", name).strip(" ._")
    return (name or "file")[:limit]


def write_json(path: Path, payload: Any, indent: int | None = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(payload, ensure_ascii=False, indent=indent)
    if not text.endswith("\n"):
        text += "\n"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def rewrite_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    n = 0
    with tmp.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    tmp.replace(path)
    return n


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
