# -*- coding: utf-8 -*-
"""Parse engine stdout/stderr into a single percent + phase for the UI bar."""
from __future__ import annotations

import re

STEP_RE = re.compile(r"^\[(\d+)\s*/\s*(\d+)\]\s*(.*)$")
YT_PCT_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")
YT_SPEED_RE = re.compile(r"at\s+(\S+/s)")
YT_ETA_RE = re.compile(r"ETA\s+(\S+)")
FRAC_RE = re.compile(
    r"(?:download|decrypt|videos|covers|comments)\s*:?\s*(\d+)\s*/\s*(\d+)",
    re.I,
)
ITEM_RE = re.compile(r"(?:-----|download)\s+(\d+)\s*/\s*(\d+)\s")
DONE_RE = re.compile(r"^={5,} done ={5,}|^\[3/3\] done|^saved:", re.I)

PHASE_HINTS = (
    ("parse", ("parse", "解析", "[1/", "extract_info", "hls", "page")),
    ("m3u8", ("m3u8", "[2/4] extract", "aes", "ts list")),
    ("download", ("download", "[2/3]", "[3/4]", "curl", "yt-dlp", "dash")),
    ("decrypt", ("decrypt",)),
    ("remux", ("remux", "merge", "merger", "[4/4]", "[3/3]")),
)


class ProgressParser:
    def __init__(self, total_items: int = 1) -> None:
        self.total_items = max(1, int(total_items or 1))
        self.item_index = 0
        self.item_pct = 0.0
        self.phase = "download"
        self.label = "准备下载"
        self.speed = ""
        self.eta = ""
        self.detail = ""

    def start_item(self, index: int, label: str) -> dict:
        self.item_index = max(0, index)
        self.item_pct = max(self.item_pct, 8.0)
        self.phase = "download"
        self.label = label
        self.speed = ""
        self.eta = ""
        return self.snapshot()

    def feed(self, line: str) -> dict | None:
        text = (line or "").strip()
        if not text:
            return None
        changed = False

        step = STEP_RE.match(text)
        if step:
            cur, total, rest = int(step.group(1)), max(1, int(step.group(2))), step.group(3).strip()
            if total == 4 and cur == 3:
                self.item_pct = max(self.item_pct, 15.0)
            elif total == 4 and cur == 4:
                self.item_pct = max(self.item_pct, 90.0)
            else:
                self.item_pct = min(95.0, (cur - 1) / total * 90 + 8)
            self.label = rest or self.label
            self._hint_phase(text)
            changed = True

        yt = YT_PCT_RE.search(text)
        if yt:
            self.item_pct = min(95.0, float(yt.group(1)))
            self.phase = "download"
            spd = YT_SPEED_RE.search(text)
            eta = YT_ETA_RE.search(text)
            self.speed = spd.group(1) if spd else self.speed
            self.eta = eta.group(1) if eta else self.eta
            self.detail = text
            changed = True

        frac = FRAC_RE.search(text)
        if frac and not yt:
            done, total = int(frac.group(1)), max(1, int(frac.group(2)))
            # Jable spends most of the bar inside [3/4] download/decrypt.
            mapped = min(95.0, 15.0 + done / total * 75.0)
            self.item_pct = max(self.item_pct, mapped)
            self.detail = f"{done}/{total}"
            self._hint_phase(text)
            changed = True

        item = ITEM_RE.search(text)
        if item:
            cur, total = int(item.group(1)), max(1, int(item.group(2)))
            self.item_index = max(0, cur - 1)
            self.total_items = max(self.total_items, total)
            self.label = text[:120]
            changed = True

        if "Merger" in text or "remux" in text.lower():
            self.phase = "remux"
            self.item_pct = max(self.item_pct, 92.0)
            changed = True

        if DONE_RE.search(text):
            self.item_pct = 100.0
            self.phase = "done"
            changed = True

        if text and not text.startswith("+ "):
            self.label = text[:140]
        if not changed:
            self._hint_phase(text)
            if len(text) > 8 and not text.startswith("+ "):
                return self.snapshot()
            return None
        return self.snapshot()

    def finish_item(self) -> dict:
        self.item_pct = 100.0
        return self.snapshot()

    def snapshot(self) -> dict:
        if self.total_items <= 1:
            percent = int(max(0, min(100, self.item_pct)))
        else:
            base = self.item_index / self.total_items
            inner = min(self.item_pct, 100.0) / 100.0 / self.total_items
            percent = int(max(0, min(99, (base + inner) * 100)))
        return {
            "percent": percent,
            "phase": self.phase,
            "label": self.label,
            "speed": self.speed,
            "eta": self.eta,
            "detail": self.detail,
            "item": self.item_index + 1,
            "items": self.total_items,
        }

    def _hint_phase(self, text: str) -> None:
        lower = text.lower()
        for phase, keys in PHASE_HINTS:
            if any(key in lower for key in keys):
                self.phase = phase
                return
