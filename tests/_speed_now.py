# -*- coding: utf-8 -*-
import json
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8765"


def hit(path: str, timeout: float = 20.0) -> tuple[float, int, dict | None]:
    url = BASE + path
    req = urllib.request.Request(url, headers={"Accept": "*/*"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        status = resp.status
        ctype = resp.headers.get("Content-Type") or ""
    ms = (time.perf_counter() - t0) * 1000
    data = None
    if "json" in ctype or path.startswith("/api/jable/list") or path.startswith("/api/jable/play"):
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            data = None
    return ms, status, data


def main() -> None:
    lists = [
        "/api/jable/list?kind=hot&page=1",
        "/api/jable/list?kind=hot&page=2",
        "/api/jable/list?kind=latest&page=1",
        "/api/jable/list?kind=type&page=1",
        "/api/jable/list?kind=tag&slug=black-pantyhose&page=1",
    ]
    for path in lists:
        ms, status, data = hit(path, 8)
        n = len((data or {}).get("items") or [])
        pages = (data or {}).get("page_count")
        print(f"LIST {path:62} {ms:7.1f}ms  items={n} pages={pages} status={status}")

    code = "yuj-067"
    first, _, pdata = hit("/api/jable/play?code=" + code, 30)
    print(f"PLAY first {code:54} {first:7.1f}ms  hls={bool((pdata or {}).get('hls'))}")
    second, _, _ = hit("/api/jable/play?code=" + code, 8)
    print(f"PLAY cache {code:54} {second:7.1f}ms")

    stream = (pdata or {}).get("stream") or ""
    if stream:
        h1, _, _ = hit(stream, 20)
        print(f"HLS  first {stream[:52]:54} {h1:7.1f}ms")
        h2, _, _ = hit(stream, 8)
        print(f"HLS  cache {stream[:52]:54} {h2:7.1f}ms")

    cover = ((pdata or {}).get("cover") or "").strip()
    if cover:
        prox = "/api/proxy?url=" + urllib.parse.quote(cover, safe="")
        c1, _, _ = hit(prox, 15)
        print(f"COVER first {'':54} {c1:7.1f}ms")
        c2, _, _ = hit(prox, 8)
        print(f"COVER cache {'':54} {c2:7.1f}ms")


if __name__ == "__main__":
    main()
