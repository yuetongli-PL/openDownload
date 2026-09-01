# -*- coding: utf-8 -*-
from __future__ import annotations

import webbrowser

import uvicorn

from .paths import load_settings


def main() -> None:
    port = int(load_settings().get("port") or 8765)
    url = f"http://127.0.0.1:{port}/"
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run("server.app:app", host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
