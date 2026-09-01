# -*- coding: utf-8 -*-
"""从 HLS / m3u8 提取 AES 密钥和全部 .ts 地址。

用法:
  python jable_m3u8.py https://.../61304.m3u8
  python jable_m3u8.py playlist.m3u8 --base https://.../61304.m3u8
  python jable_m3u8.py https://.../61304.m3u8 --save
  python jable_m3u8.py https://.../61304.m3u8 --json
  python jable_m3u8.py https://.../61304.m3u8 --summary
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from base64 import b64decode
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_REFERER = "https://jable.tv/"
ATTR_RE = re.compile(r'([A-Z0-9-]+)=("([^"]*)"|[^,]*)')


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _curl_bin() -> str | None:
    for name in ("curl.exe", "curl"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _http_headers(referer: str, accept: str) -> list[str]:
    return [
        "-A",
        USER_AGENT,
        "-H",
        f"Accept: {accept}",
        "-H",
        "Accept-Language: zh-TW,zh;q=0.9,en;q=0.8",
        "-H",
        f"Referer: {referer}",
    ]


def _fetch_with_curl(url: str, timeout: int, referer: str) -> bytes:
    curl = _curl_bin()
    if not curl:
        return b""
    cookie = Path(tempfile.gettempdir()) / "jable-hls.cookies"
    cmd = [
        curl,
        "-sL",
        "--compressed",
        "--max-time",
        str(timeout),
        "-b",
        str(cookie),
        "-c",
        str(cookie),
        *_http_headers(referer, "*/*"),
        url,
    ]
    try:
        result = subprocess.run(cmd, check=False, capture_output=True)
    except OSError:
        return b""
    return result.stdout or b""


def _fetch_with_urllib(url: str, timeout: int, referer: str) -> bytes:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Referer": referer,
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read() or b""
    except (urllib.error.URLError, TimeoutError, OSError):
        return b""


def fetch_bytes(url: str, timeout: int = 30, referer: str = DEFAULT_REFERER) -> bytes:
    data = _fetch_with_curl(url, timeout, referer)
    if data:
        return data
    return _fetch_with_urllib(url, timeout, referer)


def parse_attr_list(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for match in ATTR_RE.finditer(text):
        key = match.group(1)
        quoted = match.group(3)
        raw = match.group(2) if quoted is None else quoted
        if quoted is None:
            raw = raw.strip()
        out[key] = raw
    return out


def resolve_uri(base: str, uri: str) -> str:
    uri = uri.strip()
    if uri.lower().startswith("data:"):
        return uri
    if not base:
        return uri
    return urljoin(base, uri)


def is_master_playlist(text: str) -> bool:
    return "#EXT-X-STREAM-INF" in text and "#EXTINF:" not in text


def pick_variant(text: str, base: str) -> str:
    best_uri = None
    best_bw = -1
    pending: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-STREAM-INF:"):
            pending = parse_attr_list(line.split(":", 1)[1])
            continue
        if line.startswith("#"):
            continue
        if pending is None:
            continue
        try:
            bw = int(pending.get("BANDWIDTH") or pending.get("AVERAGE-BANDWIDTH") or 0)
        except ValueError:
            bw = 0
        if bw >= best_bw:
            best_bw = bw
            best_uri = resolve_uri(base, line)
        pending = None
    if not best_uri:
        die("master playlist has no variant m3u8")
    return best_uri


def parse_media_playlist(text: str, base: str) -> dict[str, Any]:
    keys: list[dict[str, str]] = []
    key_index: dict[tuple[str, str, str], int] = {}
    current: dict[str, str] | None = None
    segments: list[dict[str, Any]] = []
    media_sequence = 0
    seq = 0
    duration: float | None = None

    def remember_key(attrs: dict[str, str]) -> dict[str, str] | None:
        method = (attrs.get("METHOD") or "NONE").upper()
        if method == "NONE":
            return None
        uri = attrs.get("URI") or ""
        if uri and not uri.lower().startswith("data:"):
            uri = resolve_uri(base, uri)
        rec = {
            "method": method,
            "uri": uri,
            "iv": attrs.get("IV") or "",
        }
        ident = (rec["method"], rec["uri"], rec["iv"])
        if ident not in key_index:
            key_index[ident] = len(keys)
            keys.append(rec)
        return rec

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                media_sequence = int(line.split(":", 1)[1].strip())
                seq = media_sequence
            except ValueError:
                pass
            continue
        if line.startswith("#EXT-X-KEY:"):
            current = remember_key(parse_attr_list(line.split(":", 1)[1]))
            continue
        if line.startswith("#EXTINF:"):
            payload = line.split(":", 1)[1]
            first = payload.split(",", 1)[0].strip()
            try:
                duration = float(first)
            except ValueError:
                duration = None
            continue
        if line.startswith("#"):
            continue
        segments.append(
            {
                "url": resolve_uri(base, line),
                "duration": duration,
                "sequence": seq,
                "key_uri": (current or {}).get("uri") or "",
                "iv": (current or {}).get("iv") or "",
                "method": (current or {}).get("method") or "",
            }
        )
        seq += 1
        duration = None

    if not segments:
        die("no .ts segments in m3u8")
    return {
        "keys": keys,
        "segments": segments,
        "media_sequence": media_sequence,
    }


def decode_data_uri(uri: str) -> bytes:
    # data:application/octet-stream;base64,XXXX
    try:
        _, data = uri.split(",", 1)
    except ValueError:
        return b""
    header = uri.split(",", 1)[0].lower()
    if ";base64" in header:
        return b64decode(data)
    return data.encode("utf-8")


def load_key_bytes(uri: str, referer: str) -> bytes:
    if not uri:
        return b""
    if uri.lower().startswith("data:"):
        return decode_data_uri(uri)
    return fetch_bytes(uri, referer=referer)


def load_playlist(source: str, base: str | None, referer: str) -> tuple[str, str]:
    path = Path(source)
    if path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
        playlist_url = base or path.resolve().as_uri()
        return text, playlist_url
    if source.lower().startswith("http://") or source.lower().startswith("https://"):
        raw = b""
        for attempt in range(3):
            raw = fetch_bytes(source, referer=referer)
            text = raw.decode("utf-8", errors="replace").lstrip("\ufeff")
            if text.lstrip().startswith("#EXTM3U"):
                return text, source
            time.sleep(1.2 * (attempt + 1))
        die("failed to fetch m3u8 (not a playlist)")
    die(f"not an m3u8 url or file: {source}")
    return "", ""


def stem_from_url(url: str) -> str:
    name = Path(urlparse(url).path).stem
    return name or "playlist"


def save_outputs(out_dir: Path, parsed: dict[str, Any], playlist_text: str) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "playlist": str(out_dir / "playlist.m3u8"),
        "ts": str(out_dir / "ts.txt"),
        "key_info": str(out_dir / "key.txt"),
    }
    Path(files["playlist"]).write_text(playlist_text, encoding="utf-8")
    Path(files["ts"]).write_text(
        "\n".join(seg["url"] for seg in parsed["segments"]) + "\n",
        encoding="utf-8",
    )
    key_lines: list[str] = []
    for i, key in enumerate(parsed["keys"], start=1):
        key_lines.append(f"[{i}] method={key['method']}")
        key_lines.append(f"uri={key['uri']}")
        if key.get("iv"):
            key_lines.append(f"iv={key['iv']}")
        if key.get("hex"):
            key_lines.append(f"hex={key['hex']}")
        key_lines.append(f"length={key.get('length', 0)}")
        raw_hex = key.get("bytes")
        if isinstance(raw_hex, (bytes, bytearray)) and raw_hex:
            bin_path = out_dir / ("key.bin" if i == 1 else f"key{i}.bin")
            bin_path.write_bytes(bytes(raw_hex))
            files[f"key_bin_{i}"] = str(bin_path)
            key_lines.append(f"saved={bin_path}")
        key_lines.append("")
    Path(files["key_info"]).write_text("\n".join(key_lines).rstrip() + "\n", encoding="utf-8")
    return files


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract AES key and all .ts URLs from an HLS m3u8 playlist."
    )
    parser.add_argument("m3u8", nargs="?", help="m3u8 URL or local .m3u8 file")
    parser.add_argument("--base", help="base URL used to resolve relative URIs")
    parser.add_argument("--referer", default=DEFAULT_REFERER, help="Referer header")
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--summary", action="store_true", help="print key + count only")
    parser.add_argument("--ts-only", action="store_true", help="print only .ts URLs")
    parser.add_argument("--limit", type=int, default=0, help="only first N segments")
    parser.add_argument(
        "--save",
        nargs="?",
        const=".",
        metavar="DIR",
        help="save key.bin / ts.txt / playlist.m3u8 (default: current directory)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    source = args.m3u8
    if not source:
        try:
            source = input("m3u8: ").strip()
        except EOFError:
            source = ""
        if not source:
            die("need an m3u8 url or file")

    text, playlist_url = load_playlist(source, args.base, args.referer)
    media_url = playlist_url
    hops = 0
    while is_master_playlist(text):
        hops += 1
        if hops > 5:
            die("too many master playlist redirects")
        media_url = pick_variant(text, playlist_url)
        raw = fetch_bytes(media_url, referer=args.referer)
        text = raw.decode("utf-8", errors="replace").lstrip("\ufeff")
        if not text.lstrip().startswith("#EXTM3U"):
            die("variant playlist fetch failed")
        playlist_url = media_url

    parsed = parse_media_playlist(text, playlist_url)
    if args.limit and args.limit > 0:
        parsed["segments"] = parsed["segments"][: args.limit]

    for key in parsed["keys"]:
        blob = load_key_bytes(key["uri"], args.referer)
        key["bytes"] = blob
        key["length"] = len(blob)
        key["hex"] = blob.hex() if blob else ""
        if not blob:
            print(f"warning: failed to download key: {key['uri']}", file=sys.stderr)

    saved = None
    if args.save is not None:
        out_dir = Path(args.save).expanduser()
        if args.save in {".", ""}:
            out_dir = Path.cwd()
            stem = stem_from_url(media_url)
            if stem:
                out_dir = out_dir / stem
        saved = save_outputs(out_dir, parsed, text)

    payload = {
        "playlist": media_url,
        "ts_count": len(parsed["segments"]),
        "media_sequence": parsed["media_sequence"],
        "keys": [
            {
                "method": k["method"],
                "uri": k["uri"],
                "iv": k["iv"],
                "hex": k.get("hex") or "",
                "length": k.get("length") or 0,
            }
            for k in parsed["keys"]
        ],
        "ts": [seg["url"] for seg in parsed["segments"]],
        "saved": saved,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.ts_only:
        for url in payload["ts"]:
            print(url)
        return 0

    if not parsed["keys"]:
        print("method: NONE")
    for i, key in enumerate(parsed["keys"], start=1):
        prefix = "key" if len(parsed["keys"]) == 1 else f"key{i}"
        print(f"{prefix}_method: {key['method']}")
        print(f"{prefix}_uri: {key['uri']}")
        if key.get("iv"):
            print(f"{prefix}_iv: {key['iv']}")
        if key.get("hex"):
            print(f"{prefix}_hex: {key['hex']}")
        print(f"{prefix}_length: {key.get('length') or 0}")
    print(f"ts_count: {payload['ts_count']}")
    if saved:
        print(f"saved_ts: {saved['ts']}")
        print(f"saved_key: {saved['key_info']}")
        if "key_bin_1" in saved:
            print(f"saved_key_bin: {saved['key_bin_1']}")

    if not args.summary:
        print()
        for url in payload["ts"]:
            print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
