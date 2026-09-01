# -*- coding: utf-8 -*-
"""从 jable.tv 视频页提取 HLS/m3u8 与封面 jpg。

用法:
  python jable_hls.py https://jable.tv/videos/fpre-239/
  python jable_hls.py fpre-239
  python jable_hls.py URL1 URL2 --json
  python jable_hls.py URL --save
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
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

HLS_RE = re.compile(
    r"""var\s+hlsUrl\s*=\s*['"](https?://[^'"]+\.m3u8[^'"]*)['"]""",
    re.I,
)
POSTER_RE = re.compile(
    r"""<video\b[^>]*\bposter=['"](https?://[^'"]+\.jpe?g[^'"]*)['"]""",
    re.I,
)
OG_IMAGE_RE = re.compile(
    r"""<meta\b[^>]*\bproperty=['"]og:image['"][^>]*\bcontent=['"](https?://[^'"]+)['"]""",
    re.I,
)
OG_IMAGE_RE_SWAP = re.compile(
    r"""<meta\b[^>]*\bcontent=['"](https?://[^'"]+)['"][^>]*\bproperty=['"]og:image['"]""",
    re.I,
)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
VIDEO_ID_RE = re.compile(r"""videoId:\s*['"](\d+)['"]""")
CODE_RE = re.compile(r"/videos/([A-Za-z0-9._-]+)/?", re.I)
TOKEN_TS_RE = re.compile(r"/hls/[^/]+/(\d{10})/")


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


def normalize_url(raw: str) -> str:
    text = raw.strip()
    if not text:
        die("empty url")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,40}", text):
        return f"https://jable.tv/videos/{text.lower()}/"
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        die(f"invalid url: {raw}")
    host = parsed.netloc.lower()
    if "jable.tv" not in host:
        die(f"not a jable.tv url: {raw}")
    match = CODE_RE.search(parsed.path)
    if not match:
        die(f"not a video page: {raw}")
    return f"https://jable.tv/videos/{match.group(1)}/"


def video_code(url: str) -> str:
    match = CODE_RE.search(urlparse(url).path)
    return match.group(1) if match else "video"


def _curl_bin() -> str | None:
    for name in ("curl.exe", "curl"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _looks_like_page(html: str) -> bool:
    if not html or len(html) < 1000:
        return False
    lowered = html.lower()
    if "just a moment" in lowered or "cf-browser-verification" in lowered:
        return False
    return "hlsurl" in lowered or 'id="player"' in lowered or "og:image" in lowered


def _http_headers(accept: str) -> list[str]:
    return [
        "-A",
        USER_AGENT,
        "-H",
        f"Accept: {accept}",
        "-H",
        "Accept-Language: zh-TW,zh;q=0.9,en;q=0.8",
        "-H",
        "Referer: https://jable.tv/",
    ]


def _fetch_with_curl(url: str, timeout: int) -> bytes:
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
        *_http_headers("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        url,
    ]
    try:
        result = subprocess.run(cmd, check=False, capture_output=True)
    except OSError:
        return b""
    return result.stdout or b""


def _fetch_with_urllib(url: str, timeout: int) -> bytes:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        "Referer": "https://jable.tv/",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read() or b""
    except (urllib.error.URLError, TimeoutError, OSError):
        return b""


def fetch_html(url: str, timeout: int = 30) -> str:
    last = ""
    for attempt in range(3):
        raw = _fetch_with_curl(url, timeout) or _fetch_with_urllib(url, timeout)
        html = raw.decode("utf-8", errors="replace")
        last = html
        if _looks_like_page(html):
            return html
        time.sleep(1.2 * (attempt + 1))
    snippet = re.sub(r"\s+", " ", last)[:180]
    die(f"failed to fetch page (cloudflare or network): {snippet or 'empty response'}")
    return ""


def _first_jpg(*candidates: str | None) -> str | None:
    for item in candidates:
        if not item:
            continue
        url = unescape(item.strip())
        if re.search(r"\.jpe?g(\?|$)", url, re.I):
            return url
        if url.startswith("http"):
            return url
    return None


def parse_page(url: str, html: str) -> dict[str, Any]:
    hls_match = HLS_RE.search(html)
    if not hls_match:
        die("hls/m3u8 not found in page")
    hls = unescape(hls_match.group(1))

    poster = None
    poster_match = POSTER_RE.search(html)
    if poster_match:
        poster = unescape(poster_match.group(1))
    og = None
    og_match = OG_IMAGE_RE.search(html) or OG_IMAGE_RE_SWAP.search(html)
    if og_match:
        og = unescape(og_match.group(1))
    cover = _first_jpg(poster, og)
    if not cover:
        die("cover jpg not found in page")

    title = None
    title_match = TITLE_RE.search(html)
    if title_match:
        title = unescape(re.sub(r"\s+", " ", title_match.group(1))).strip()
        title = re.sub(r"\s*-\s*Jable\.TV.*$", "", title, flags=re.I)

    video_id = None
    id_match = VIDEO_ID_RE.search(html)
    if id_match:
        video_id = id_match.group(1)

    expires_at = None
    ts_match = TOKEN_TS_RE.search(hls)
    if ts_match:
        ts = int(ts_match.group(1))
        expires_at = datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

    return {
        "url": url,
        "code": video_code(url),
        "video_id": video_id,
        "title": title,
        "hls": hls,
        "cover": cover,
        "expires_at": expires_at,
    }


def _download_bytes(url: str, timeout: int = 30) -> bytes:
    data = _fetch_with_curl(url, timeout)
    if len(data) >= 100:
        return data
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://jable.tv/",
        "Accept": "image/jpeg,image/*;q=0.8,*/*;q=0.5",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read() or b""


def save_cover(item: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{item['code']}.jpg"
    data = _download_bytes(item["cover"])
    if len(data) < 100 or data[:3] != b"\xff\xd8\xff":
        die("cover download is not a jpg")
    dest.write_bytes(data)
    (out_dir / f"{item['code']}.m3u8.url").write_text(item["hls"] + "\n", encoding="utf-8")
    return dest


def print_text(item: dict[str, Any], saved: Path | None = None) -> None:
    if item.get("title"):
        print(f"title: {item['title']}")
    print(f"hls: {item['hls']}")
    print(f"cover: {item['cover']}")
    if item.get("expires_at"):
        print(f"expires: {item['expires_at']}")
    if saved:
        print(f"saved: {saved}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract HLS/m3u8 and cover jpg from a jable.tv video page."
    )
    parser.add_argument("urls", nargs="*", help="jable.tv video URL or video code")
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument(
        "--save",
        nargs="?",
        const=".",
        metavar="DIR",
        help="download cover jpg (default: current directory)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    urls = list(args.urls)
    if not urls:
        try:
            raw = input("url: ").strip()
        except EOFError:
            die("need a jable.tv url")
        if not raw:
            die("need a jable.tv url")
        urls = [raw]

    results = []
    saved_paths: list[Path | None] = []
    out_dir = Path(args.save).expanduser() if args.save else None
    for raw in urls:
        page_url = normalize_url(raw)
        html = fetch_html(page_url)
        item = parse_page(page_url, html)
        saved = save_cover(item, out_dir) if out_dir is not None else None
        if saved:
            item["saved"] = str(saved)
        results.append(item)
        saved_paths.append(saved)

    if args.json:
        payload: Any = results[0] if len(results) == 1 else results
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for i, item in enumerate(results):
            if i:
                print()
            print_text(item, saved_paths[i])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
