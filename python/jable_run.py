# -*- coding: utf-8 -*-
"""由 jable.bat 调用：输入页面/番号/m3u8，解析、下载并封装 mp4 到当前工作目录。"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


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


def remux_mp4(ffmpeg: Path, ts_path: Path, mp4_path: Path) -> None:
    common = [
        str(ffmpeg),
        "-hide_banner",
        "-y",
        "-i",
        str(ts_path),
        "-map",
        "0",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
    ]
    print("+", " ".join(common + [str(mp4_path)]), flush=True)
    result = subprocess.run(common + [str(mp4_path)], check=False)
    if result.returncode == 0 and mp4_path.is_file() and mp4_path.stat().st_size > 0:
        return
    cmd = common[:-2] + ["-bsf:a", "aac_adtstoasc", "-movflags", "+faststart", str(mp4_path)]
    print("+", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0 or not mp4_path.is_file() or mp4_path.stat().st_size == 0:
        die("ffmpeg remux to mp4 failed")


def guess_code(raw: str) -> str:
    text = raw.strip()
    match = re.search(r"/videos/([A-Za-z0-9._-]+)", text, re.I)
    if match:
        return match.group(1).lower()
    name = text.split("?", 1)[0].rstrip("/").split("/")[-1]
    name = re.sub(r"\.m3u8$", "", name, flags=re.I)
    return name.lower() or "video"


def run_script(script: str, args: list[str], cwd: Path, capture: bool = False) -> str:
    cmd = [find_python(), str(HERE / script), *args]
    print("+", " ".join(cmd), flush=True)
    if capture:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            die(err or f"{script} failed ({result.returncode})")
        return result.stdout
    result = subprocess.run(cmd, cwd=str(cwd), check=False)
    if result.returncode != 0:
        die(f"{script} failed ({result.returncode})")
    return ""


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    extra: list[str] = []
    if args:
        url = args[0].strip()
        extra = args[1:]
    else:
        try:
            url = input("URL: ").strip()
        except EOFError:
            url = ""
        extra = []
    if not url:
        die("need a jable.tv url or video code")
    want_mp4 = True
    want_subs = False
    embed_subs = True
    code_flag = ""
    cleaned: list[str] = []
    idx = 0
    while idx < len(extra):
        item = extra[idx]
        if item == "--code" and idx + 1 < len(extra):
            code_flag = extra[idx + 1].strip()
            idx += 2
            continue
        if item.startswith("--code="):
            code_flag = item.split("=", 1)[1].strip()
            idx += 1
            continue
        if item == "--no-mp4":
            want_mp4 = False
            idx += 1
            continue
        if item == "--subs":
            want_subs = True
            idx += 1
            continue
        if item == "--no-embed":
            embed_subs = False
            idx += 1
            continue
        cleaned.append(item)
        idx += 1
    extra = cleaned

    out_root = Path.cwd()
    code = (code_flag or guess_code(url)).strip().lower() or "video"
    work = out_root / code
    work.mkdir(parents=True, exist_ok=True)
    print(f"save dir: {work}", flush=True)

    if re.search(r"\.m3u8($|[?#])", url, re.I):
        print("[1/4] m3u8 url, skip page parse", flush=True)
        hls = url
        (work / "hls.url").write_text(hls + "\n", encoding="utf-8")
    else:
        print("[1/4] parse page for HLS and cover", flush=True)
        stdout = run_script(
            "jable_hls.py",
            [url, "--json", "--save", str(work)],
            cwd=work,
            capture=True,
        )
        try:
            meta = json.loads(stdout)
        except json.JSONDecodeError:
            die("jable_hls.py did not return JSON")
        if isinstance(meta, list):
            meta = meta[0]
        hls = meta.get("hls") or ""
        if meta.get("code"):
            code = str(meta["code"])
            new_work = out_root / code
            if new_work != work:
                new_work.mkdir(parents=True, exist_ok=True)
                for item in work.iterdir():
                    dest = new_work / item.name
                    if dest.exists():
                        continue
                    item.replace(dest)
                work = new_work
        if not hls:
            die("hls/m3u8 not found")
        (work / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (work / "hls.url").write_text(hls + "\n", encoding="utf-8")

    print(f"HLS: {hls}", flush=True)
    print("[2/4] extract AES key and ts list", flush=True)
    run_script("jable_m3u8.py", [hls, "--summary", "--save", str(work)], cwd=work)

    video = work / f"{code}.ts"
    print("[3/4] download, decrypt, concat", flush=True)
    run_script("jable_decrypt.py", [str(work), "-o", str(video), *extra], cwd=work)
    if not video.is_file():
        die(f"ts not found: {video}")

    mp4 = work / f"{code}.mp4"
    if want_mp4:
        print("[4/4] remux mp4 (copy, no re-encode)", flush=True)
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            die("ffmpeg not found; install with: winget install Gyan.FFmpeg.Essentials")
        remux_mp4(ffmpeg, video, mp4)
    else:
        print("[4/4] skip mp4 (--no-mp4)", flush=True)

    if want_subs:
        if not mp4.is_file():
            print("warning: --subs skipped (no mp4)", file=sys.stderr, flush=True)
        else:
            print("[5/5] bilingual subtitles (Grok STT, zh-ja)", flush=True)
            from jable_subs import build_for_dir

            ffmpeg = find_ffmpeg()
            if not ffmpeg:
                die("ffmpeg not found; install with: winget install Gyan.FFmpeg.Essentials")
            built = build_for_dir(work, ffmpeg=ffmpeg, embed=embed_subs)
            print(f"subs: {built.get('cues')} cues", flush=True)

    print(flush=True)
    print("========== done ==========")
    print(f"dir:   {work}")
    print(f"ts:    {video}")
    if mp4.is_file():
        print(f"mp4:   {mp4}")
    cover = work / f"{code}.jpg"
    if cover.is_file():
        print(f"cover: {cover}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
