# -*- coding: utf-8 -*-
"""Run every tests/ui_*.py sequentially and print a result table."""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
TIMEOUT = 180


def discover(only: str | None) -> list[Path]:
    rows = sorted(
        p
        for p in TESTS.glob("ui_*.py")
        if p.name != "ui_support.py" and p.name != "run_ui.py"
    )
    if only:
        rows = [p for p in rows if only.lower() in p.name.lower()]
    return rows


def run_one(script: Path) -> tuple[str, float, str]:
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(ROOT),
            timeout=TIMEOUT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        ms = time.perf_counter() - t0
        if proc.returncode == 0:
            return "pass", ms, (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else ""
        tail = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        return "fail", ms, tail[-1200:]
    except subprocess.TimeoutExpired as exc:
        ms = time.perf_counter() - t0
        extra = ""
        if exc.stdout:
            extra = exc.stdout if isinstance(exc.stdout, str) else exc.stdout.decode("utf-8", "replace")
        return "timeout", ms, extra[-800:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="substring filter on script name")
    args = parser.parse_args()
    scripts = discover(args.only or None)
    if not scripts:
        print("no ui_*.py matched")
        return 1

    print(f"{'脚本':<28} {'结果':<10} {'耗时'}")
    print("-" * 56)
    failed = 0
    for script in scripts:
        status, seconds, detail = run_one(script)
        if status != "pass":
            status2, seconds2, detail2 = run_one(script)
            if status2 == "pass":
                status, seconds, detail = "pass(retry)", seconds + seconds2, detail2
            else:
                status, seconds, detail = status2, seconds + seconds2, detail2
        mark = "通过" if status.startswith("pass") else ("超时" if status == "timeout" else "失败")
        print(f"{script.name:<28} {mark:<10} {seconds:6.1f}s")
        if not status.startswith("pass"):
            failed += 1
            if detail:
                print(detail)
                print("-" * 56)
    print("-" * 56)
    print(f"合计 {len(scripts)}  失败 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
