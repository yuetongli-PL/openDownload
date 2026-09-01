# -*- coding: utf-8 -*-
"""按 ts.txt 下载 HLS 分片，AES-128 解密后按顺序拼接成可播放的 .ts。

默认用 curl --parallel（约 128 连接）一次拉完全部分片。
加密分片写到系统临时目录，避免 Desktop/OneDrive 拖慢小文件。

用法:
  python jable_decrypt.py C:\\Users\\lyt-p\\Desktop\\Jable\\fpre-239
  python jable_decrypt.py fpre-239 --workers 128
  python jable_decrypt.py fpre-239 --limit 10 -o sample.ts
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_REFERER = "https://jable.tv/"
DEFAULT_WORKERS = 128
IV_RE = re.compile(r"^(?:key_iv|iv)\s*[:=]\s*(.+)$", re.I)
HEX_RE = re.compile(r"^(?:key_hex|hex)\s*[:=]\s*([0-9a-fA-F]+)$", re.I)
PLAYLIST_IV_RE = re.compile(r"IV=(0x[0-9a-fA-F]+)", re.I)
_CURL_HELP = ""


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def parse_hex_bytes(text: str, expect: int | None = None, name: str = "hex") -> bytes:
    raw = text.strip().replace(" ", "").replace(":", "")
    if raw.lower().startswith("0x"):
        raw = raw[2:]
    if len(raw) % 2:
        die(f"invalid {name}: odd length")
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        die(f"invalid {name}: {text}")
    if expect is not None and len(data) != expect:
        die(f"{name} must be {expect} bytes, got {len(data)}")
    return data


def _curl_bin() -> str | None:
    for name in ("curl.exe", "curl"):
        found = shutil.which(name)
        if found:
            return found
    return None


def curl_help_text(curl: str) -> str:
    global _CURL_HELP
    if _CURL_HELP:
        return _CURL_HELP
    chunks: list[str] = []
    for args in ([curl, "-h"], [curl, "-h", "global"], [curl, "-h", "connection"], [curl, "-h", "tls"]):
        try:
            result = subprocess.run(
                args,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue
        chunks.append(result.stdout or "")
        chunks.append(result.stderr or "")
    _CURL_HELP = "\n".join(chunks)
    return _CURL_HELP


def curl_supports_parallel(curl: str) -> bool:
    text = curl_help_text(curl)
    return "--parallel" in text or " -Z, " in text


def curl_has_flag(curl: str, flag: str) -> bool:
    return flag in curl_help_text(curl)


def _fetch_curl(url: str, timeout: int, referer: str) -> bytes:
    curl = _curl_bin()
    if not curl:
        return b""
    cookie = Path(tempfile.gettempdir()) / "jable-hls.cookies"
    cmd = [
        curl,
        "-sL",
        "--max-time",
        str(timeout),
        "-A",
        USER_AGENT,
        "-H",
        "Accept: */*",
        "-H",
        f"Referer: {referer}",
        "-b",
        str(cookie),
        "-c",
        str(cookie),
        url,
    ]
    try:
        result = subprocess.run(cmd, check=False, capture_output=True)
    except OSError:
        return b""
    return result.stdout or b""


def _fetch_urllib(url: str, timeout: int, referer: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*",
            "Referer": referer,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read() or b""
    except (urllib.error.URLError, TimeoutError, OSError):
        return b""


def fetch_bytes(url: str, timeout: int, referer: str, retries: int = 3) -> bytes:
    last = b""
    for attempt in range(retries):
        data = _fetch_curl(url, timeout, referer) or _fetch_urllib(url, timeout, referer)
        last = data
        if data and len(data) >= 16:
            return data
        time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"download failed: {url} (got {len(last)} bytes)")


def enc_ok(path: Path) -> bool:
    try:
        size = path.stat().st_size
    except OSError:
        return False
    return size >= 16 and size % 16 == 0


def write_curl_config(jobs: list[tuple[str, Path]], cfg: Path) -> None:
    lines: list[str] = []
    for url, dest in jobs:
        out = dest.as_posix().replace('"', '\\"')
        safe_url = url.replace('"', "%22")
        lines.append(f'url = "{safe_url}"')
        lines.append(f'output = "{out}"')
    cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_curl_parallel_cmd(
    curl: str,
    cfg: Path,
    parallel_max: int,
    timeout: int,
    referer: str,
) -> list[str]:
    pmax = str(max(1, parallel_max))
    cmd = [
        curl,
        "-sS",
        "-L",
        "-Z",
        "--parallel-max",
        pmax,
        "--retry",
        "2",
        "--retry-delay",
        "0",
        "--connect-timeout",
        "10",
        "--max-time",
        str(max(timeout, 60)),
        "-A",
        USER_AGENT,
        "-H",
        "Accept: */*",
        "-H",
        f"Referer: {referer}",
        "-K",
        str(cfg),
    ]
    if curl_has_flag(curl, "--parallel-immediate"):
        cmd.append("--parallel-immediate")
    if curl_has_flag(curl, "--parallel-max-host"):
        cmd.extend(["--parallel-max-host", pmax])
    if curl_has_flag(curl, "--tcp-nodelay"):
        cmd.append("--tcp-nodelay")
    if curl_has_flag(curl, "--ssl-no-revoke"):
        cmd.append("--ssl-no-revoke")
    if curl_has_flag(curl, "--retry-all-errors"):
        cmd.append("--retry-all-errors")
    return cmd


def download_curl_parallel(
    urls: list[str],
    dests: list[Path],
    parts: Path,
    parallel_max: int,
    timeout: int,
    referer: str,
    retries: int,
) -> None:
    curl = _curl_bin()
    if not curl:
        die("curl not found")
    parts.mkdir(parents=True, exist_ok=True)

    def pending() -> list[tuple[str, Path]]:
        return [(u, p) for u, p in zip(urls, dests) if not enc_ok(p)]

    jobs = pending()
    if not jobs:
        print("download: all segments already cached", file=sys.stderr)
        return

    cfg = parts / "curl.cfg"
    pmax = max(1, min(parallel_max, len(jobs)))
    for attempt in range(max(1, retries)):
        jobs = pending()
        if not jobs:
            break
        pmax = max(1, min(parallel_max, len(jobs)))
        write_curl_config(jobs, cfg)
        print(
            f"download: curl --parallel {len(jobs)} files, connections={pmax}"
            + (f" (retry {attempt})" if attempt else ""),
            file=sys.stderr,
        )
        cmd = build_curl_parallel_cmd(curl, cfg, pmax, timeout, referer)
        result = subprocess.run(cmd, check=False)
        if result.returncode not in (0, 18, 26, 28, 56):
            print(f"warning: curl exit {result.returncode}", file=sys.stderr)

    missing = pending()
    if missing:
        print(f"download: retry {len(missing)} leftover files, workers=32", file=sys.stderr)

        def one(job: tuple[str, Path]) -> None:
            url, dest = job
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = fetch_bytes(url, timeout, referer, retries)
            dest.write_bytes(data)

        with ThreadPoolExecutor(max_workers=min(32, len(missing))) as pool:
            futs = [pool.submit(one, job) for job in missing]
            for fut in futs:
                fut.result()

    missing = pending()
    if missing:
        die(f"download incomplete: {len(missing)} segments failed, e.g. {missing[0][0]}")


def download_thread_pool(
    urls: list[str],
    dests: list[Path],
    workers: int,
    timeout: int,
    referer: str,
    retries: int,
) -> None:
    workers = max(1, workers)
    t0 = time.time()
    n = len(urls)

    def one(i: int) -> int:
        dest = dests[i]
        if enc_ok(dest):
            return dest.stat().st_size
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = fetch_bytes(urls[i], timeout, referer, retries)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)
        return len(data)

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(one, i) for i in range(n)]
        for i, fut in enumerate(futs, start=1):
            fut.result()
            done = i
            if done == 1 or done % 20 == 0 or done == n:
                elapsed = max(time.time() - t0, 0.001)
                print(
                    f"\rdownload: {done}/{n}  {done / elapsed:.1f} seg/s",
                    end="",
                    file=sys.stderr,
                    flush=True,
                )
    print(file=sys.stderr)


def read_ts_list(path: Path) -> list[str]:
    if not path.is_file():
        die(f"ts list not found: {path}")
    urls = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        urls.append(text.split()[0])
    if not urls:
        die(f"no .ts urls in {path}")
    return urls


def load_key_iv(
    key_path: Path | None,
    key_txt: Path | None,
    playlist: Path | None,
    iv_arg: str | None,
) -> tuple[bytes, bytes | None]:
    key = b""
    iv: bytes | None = None
    hex_from_txt = ""
    iv_from_txt = ""

    if key_txt and key_txt.is_file():
        for line in key_txt.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            m_iv = IV_RE.match(line)
            if m_iv:
                iv_from_txt = m_iv.group(1).strip()
            m_hex = HEX_RE.match(line)
            if m_hex:
                hex_from_txt = m_hex.group(1).strip()

    if key_path and key_path.is_file():
        key = key_path.read_bytes()
    elif hex_from_txt:
        key = parse_hex_bytes(hex_from_txt, name="key hex")

    if len(key) != 16:
        die(f"AES-128 key must be 16 bytes, got {len(key)}")

    if iv_arg:
        iv = parse_hex_bytes(iv_arg, 16, "iv")
    elif iv_from_txt:
        iv = parse_hex_bytes(iv_from_txt, 16, "iv")
    elif playlist and playlist.is_file():
        text = playlist.read_text(encoding="utf-8", errors="replace")
        match = PLAYLIST_IV_RE.search(text)
        if match:
            iv = parse_hex_bytes(match.group(1), 16, "iv")
    return key, iv


def is_mpegts(data: bytes, packets: int = 8) -> bool:
    if len(data) < 188 or data[0] != 0x47:
        return False
    checks = min(packets, len(data) // 188)
    ok = sum(1 for i in range(checks) if data[i * 188] == 0x47)
    return ok == checks


def decrypt_segment(enc: bytes, key: bytes, iv: bytes, check: bool = True) -> bytes:
    if len(enc) < 16:
        raise ValueError("encrypted segment too small")
    if len(enc) % 16:
        raise ValueError(f"encrypted segment not AES block aligned: {len(enc)} bytes")
    plain = AES.new(key, AES.MODE_CBC, iv).decrypt(enc)
    try:
        data = unpad(plain, 16, style="pkcs7")
    except ValueError:
        data = plain.rstrip(b"\x00")
        if not is_mpegts(data):
            data = plain
    if check and not is_mpegts(data):
        raise ValueError("not MPEG-TS after AES-128 decrypt")
    return data


def sequence_iv(seq: int) -> bytes:
    return seq.to_bytes(16, "big")


def resolve_inputs(
    args: argparse.Namespace,
) -> tuple[Path, Path | None, Path | None, Path | None, Path]:
    target = Path(args.dir or args.ts or args.path or "").expanduser()
    if not str(target):
        die("need a work directory or ts.txt")

    if target.is_dir():
        work = target
        ts_path = work / "ts.txt"
        key_path = Path(args.key).expanduser() if args.key else work / "key.bin"
        key_txt = work / "key.txt"
        playlist = work / "playlist.m3u8"
        default_out = work / f"{work.name}.ts"
    else:
        ts_path = Path(args.ts).expanduser() if args.ts else target
        work = ts_path.parent
        key_path = Path(args.key).expanduser() if args.key else work / "key.bin"
        key_txt = work / "key.txt"
        playlist = work / "playlist.m3u8"
        default_out = work / f"{work.name or 'video'}.ts"

    out = Path(args.output).expanduser() if args.output else default_out
    if not key_path.is_file():
        key_path = None
    if not key_txt.is_file():
        key_txt = None
    if not playlist.is_file():
        playlist = None
    return ts_path, key_path, key_txt, playlist, out


def pick_iv(first_enc: bytes, key: bytes, iv: bytes | None, start_seq: int) -> bytes:
    candidates: list[tuple[str, bytes]] = []
    if iv is not None:
        candidates.append(("playlist IV", iv))
    candidates.append(("media-sequence IV", sequence_iv(start_seq)))
    last_err = "decrypt failed"
    for name, cand in candidates:
        try:
            decrypt_segment(first_enc, key, cand)
            print(f"iv_mode: {name}", file=sys.stderr)
            return cand
        except ValueError as exc:
            last_err = str(exc)
    die(f"cannot decrypt first segment ({last_err})")
    return b""


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download .ts segments, AES-128 decrypt, concat into one playable MPEG-TS."
    )
    parser.add_argument("path", nargs="?", help="work directory or ts.txt")
    parser.add_argument("--dir", help="work directory containing ts.txt / key.bin / key.txt")
    parser.add_argument("--ts", help="path to ts.txt")
    parser.add_argument("--key", help="path to 16-byte key.bin")
    parser.add_argument("--iv", help="AES IV, e.g. 0x9b45ae00...")
    parser.add_argument("-o", "--output", help="output .ts path")
    parser.add_argument("--referer", default=DEFAULT_REFERER)
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="parallel connections (default 128; this is the setting that reached ~13 MB/s)",
    )
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--start", type=int, default=0, help="start index, 0-based")
    parser.add_argument("--limit", type=int, default=0, help="only process N segments")
    parser.add_argument("--seq-iv", action="store_true", help="force media-sequence IV per segment")
    parser.add_argument(
        "--parts",
        help="directory for encrypted parts (default: %%TEMP%%\\jable-decrypt\\<name>)",
    )
    parser.add_argument(
        "--keep-parts",
        action="store_true",
        help="keep encrypted .enc parts after concat",
    )
    parser.add_argument(
        "--no-parallel-curl",
        action="store_true",
        help="fallback: one curl process per segment via thread pool",
    )
    return parser.parse_args(argv)


def publish_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        src.replace(dest)
        return
    except OSError:
        pass
    shutil.copyfile(src, dest)
    try:
        src.unlink(missing_ok=True)
    except OSError:
        pass


def concat_decrypt(
    dests: list[Path],
    key: bytes,
    ivs: list[bytes],
    out: Path,
    start_seq: int,
    tmp: Path,
) -> int:
    tmp.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    t0 = time.time()
    n = len(dests)
    with tmp.open("wb", buffering=8 * 1024 * 1024) as fh:
        for i, dest in enumerate(dests):
            enc = dest.read_bytes()
            try:
                plain = decrypt_segment(enc, key, ivs[i], check=(i == 0))
            except ValueError as exc:
                die(f"{exc}: part {start_seq + i} {dest}")
            fh.write(plain)
            total += len(plain)
            if i == 0 or (i + 1) % 100 == 0 or i + 1 == n:
                elapsed = max(time.time() - t0, 0.001)
                print(
                    f"\rdecrypt: {i + 1}/{n}  {total / 1024 / 1024:.1f} MB  { (i + 1) / elapsed:.0f} seg/s",
                    end="",
                    file=sys.stderr,
                    flush=True,
                )
    print(file=sys.stderr)
    publish_file(tmp, out)
    return total


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    ts_path, key_path, key_txt, playlist, out = resolve_inputs(args)
    urls = read_ts_list(ts_path)
    start = max(0, args.start)
    if start >= len(urls):
        die(f"--start {start} out of range ({len(urls)} segments)")
    urls = urls[start:]
    if args.limit and args.limit > 0:
        urls = urls[: args.limit]

    key, playlist_iv = load_key_iv(key_path, key_txt, playlist, args.iv)
    work = ts_path.parent
    if args.parts:
        parts = Path(args.parts).expanduser()
    else:
        parts = Path(tempfile.gettempdir()) / "jable-decrypt" / work.name
    dests = [parts / f"{start + i:06d}.enc" for i in range(len(urls))]
    tmp_out = parts / (out.name + ".part")

    print(f"segments: {len(urls)}", file=sys.stderr)
    print(f"key: {key.hex()}", file=sys.stderr)
    print(f"parts: {parts}", file=sys.stderr)
    print(f"output: {out}", file=sys.stderr)

    curl = _curl_bin()
    use_parallel = (
        curl
        and not args.no_parallel_curl
        and curl_supports_parallel(curl)
    )
    t_dl = time.time()
    if use_parallel:
        download_curl_parallel(
            urls,
            dests,
            parts,
            parallel_max=max(1, args.workers),
            timeout=args.timeout,
            referer=args.referer,
            retries=args.retries,
        )
    else:
        print("download: thread pool fallback (one curl per segment)", file=sys.stderr)
        download_thread_pool(
            urls,
            dests,
            workers=max(1, args.workers),
            timeout=args.timeout,
            referer=args.referer,
            retries=args.retries,
        )
    dl_s = max(time.time() - t_dl, 0.001)
    enc_bytes = sum(p.stat().st_size for p in dests)
    print(
        f"download done: {enc_bytes / 1024 / 1024:.1f} MB in {dl_s:.1f}s  ({enc_bytes / dl_s / 1024 / 1024:.2f} MB/s)",
        file=sys.stderr,
    )

    first_enc = dests[0].read_bytes()
    if args.seq_iv:
        print("iv_mode: media-sequence IV", file=sys.stderr)
        ivs = [sequence_iv(start + i) for i in range(len(urls))]
    else:
        base_iv = pick_iv(first_enc, key, playlist_iv, start)
        print(f"iv: 0x{base_iv.hex()}", file=sys.stderr)
        ivs = [base_iv] * len(urls)

    t_dec = time.time()
    total_bytes = concat_decrypt(dests, key, ivs, out, start, tmp_out)
    dec_s = max(time.time() - t_dec, 0.001)
    print(
        f"decrypt done: {total_bytes / 1024 / 1024:.1f} MB in {dec_s:.1f}s",
        file=sys.stderr,
    )

    if not args.keep_parts:
        for dest in dests:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
        cfg = parts / "curl.cfg"
        try:
            cfg.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            parts.rmdir()
        except OSError:
            pass

    print(f"saved: {out}  ({total_bytes} bytes, {len(urls)} segments)", file=sys.stderr)
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
