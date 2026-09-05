# -*- coding: utf-8 -*-
import json
import time
import urllib.request

def hit(path):
    t = time.perf_counter()
    with urllib.request.urlopen("http://127.0.0.1:8765" + path, timeout=3) as r:
        data = json.loads(r.read().decode())
    ms = (time.perf_counter() - t) * 1000
    items = data.get("items") or []
    ids = [i.get("id") for i in items[:2]]
    print(
        f"{ms:7.1f}ms n={len(items):2d} page={data.get('page')} total={data.get('total')} "
        f"more={data.get('has_more')} pending={data.get('pending')} first={ids} {path}"
    )
    return ms

times = []
for p in [
    "/api/jable/list?kind=hot&page=1",
    "/api/jable/list?kind=hot&page=2",
    "/api/jable/list?kind=latest&page=1",
    "/api/jable/list?kind=latest&page=2",
    "/api/jable/list?kind=week&page=1",
    "/api/jable/list?kind=type&page=1",
    "/api/jable/list?kind=tag&slug=black-pantyhose&page=1",
    "/api/jable/list?kind=cat&slug=chinese-subtitle&page=1",
    "/api/jable/list?kind=latest&year=2025&page=1",
]:
    times.append(hit(p))
print("max", round(max(times), 1), "all<1000", all(t < 1000 for t in times))
