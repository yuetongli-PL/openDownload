# -*- coding: utf-8 -*-
import json
import time
import urllib.request

def hit(path):
    t = time.perf_counter()
    with urllib.request.urlopen("http://127.0.0.1:8765" + path, timeout=8) as r:
        data = json.loads(r.read().decode())
    ms = (time.perf_counter() - t) * 1000
    items = data.get("items") or []
    print(
        f"{ms:7.1f}ms n={len(items):2d} page={data.get('page')} total={data.get('total')} "
        f"pages={data.get('page_count')} first={[i.get('id') for i in items[:2]]} {path}"
    )
    return data

hot = hit("/api/jable/list?kind=hot&page=1")
hit("/api/jable/list?kind=latest&page=1")
hit("/api/jable/list?kind=tag&slug=black-pantyhose&page=1")
assert len(hot.get("items") or []) == 12
assert (hot.get("page_count") or 0) > 10
assert (hot.get("total") or 0) > 100
print("ok")
