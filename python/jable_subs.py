# -*- coding: utf-8 -*-
"""日语对白：抽音 -> Grok STT 对轴 -> 简日双语 ASS/SRT。

沿用 Youtube 字幕组做法：词级时间当钟，中文较大在上、日文较小在下。
不读、不改 Desktop\\Youtube。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jable_audio_sync import (
    extract_audio_track,
    glyph_count,
    grok_api_token,
    grok_chat_json,
    grok_stt_words,
    join_ja,
    vocal_cues_for_audio,
)

HERE = Path(__file__).resolve().parent


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(code)


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


def find_grok() -> Path | None:
    for name in ("grok", "grok.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    home = Path.home() / ".grok" / "bin" / "grok.exe"
    if home.is_file():
        return home
    return None


@dataclass
class Cue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class BilingualCue:
    start: float
    end: float
    zh: str
    ja: str


_JA_PARTICLE = re.compile(r"^(は|が|を|に|で|と|も|の|か|よ|ね|わ|さ|な|って|んだ)$")
_SMALL_KANA = set("ぁぃぅぇぉゃゅょっァィゥェォャュョッ")
_JA_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"オハヨー"), "おはよう"),
    (re.compile(r"こうけんに"), "貢献に"),
    (re.compile(r"レズロマンサギ"), "レズロマンス詐欺"),
    (re.compile(r"ロマンスサギ"), "ロマンス詐欺"),
    (re.compile(r"勇敢マダム"), "有閑マダム"),
    (re.compile(r"撮り込めば"), "取り込みば"),
    (re.compile(r"未だらな"), "淫らな"),
    (re.compile(r"変えとった"), "奪い取った"),
    (re.compile(r"うちに跳ねま"), "うちにハマりま"),
    (re.compile(r"一通足"), "いっちょ足"),
    (re.compile(r"ですい"), "です結衣"),
    (re.compile(r"いいさん"), "結衣さん"),
    (re.compile(r"ゆいさん"), "結衣さん"),
    (re.compile(r"はたのさん"), "波多野さん"),
    (re.compile(r"はやさん"), "波多野さん"),
    (re.compile(r"篠野さん"), "波多野さん"),
    (re.compile(r"篠野"), "波多野"),
    (re.compile(r"嫌さん"), "波多野さん"),
    (re.compile(r"やさんね"), "彩さんね"),
    (re.compile(r"さあや"), "さあ彩"),
    (re.compile(r"はたの"), "波多野"),
    (re.compile(r"アヤさん"), "彩さん"),
    (re.compile(r"サイヤ"), "さあ彩"),
    (re.compile(r"アヤ"), "彩"),
]


def cleanup_ja(text: str) -> str:
    out = (text or "").strip()
    if not out:
        return ""
    for pat, repl in _JA_FIXES:
        out = pat.sub(repl, out)
    out = re.sub(r"^([ょゃゅっ]+)", "", out)
    return out.strip()


def _norm_ja(text: str) -> str:
    return re.sub(r"[\s　、。！？!?]", "", text or "")


def split_ja_utterances(text: str) -> list[str]:
    chunks: list[str] = []
    for block in (text or "").split():
        block = block.strip()
        if not block:
            continue
        parts = [
            p.strip()
            for p in re.split(
                r"(?<=でしょ)|(?<=わよ)|(?<=のよ)|(?<=かしら)|(?<=わね)|(?<=さんね)|(?<=[。！？!?])",
                block,
            )
            if p and p.strip()
        ]
        chunks.extend(parts or [block])
    return chunks


def align_phrase_window(
    phrase: str,
    words: list[tuple[str, float, float]],
    cursor: int,
) -> tuple[int, int]:
    """Map one STT phrase onto mora words. Returns [start_i, end_i)."""
    target = _norm_ja(phrase)
    n = len(words)
    if not target or cursor >= n:
        return cursor, min(cursor + 1, n)
    best_i, best_j, best_score = cursor, min(cursor + 1, n), -1.0
    max_j = min(n, cursor + max(12, len(target) * 3 + 6))
    for i in range(cursor, min(n, cursor + 6)):
        acc = ""
        for j in range(i + 1, max_j + 1):
            acc = _norm_ja(join_ja([w[0] for w in words[i:j]]))
            if not acc:
                continue
            if target == acc:
                return i, j
            if target.startswith(acc) or acc.startswith(target) or target in acc or acc in target:
                score = min(len(acc), len(target)) / max(len(acc), len(target))
                if score > best_score:
                    best_i, best_j, best_score = i, j, score
            if len(acc) > len(target) + 4:
                break
    if best_score >= 0.45:
        return best_i, best_j
    return cursor, min(cursor + max(1, len(target)), n)


def cues_from_stt_text(
    text: str,
    words: list[tuple[str, float, float]],
) -> list[Cue]:
    cues: list[Cue] = []
    cursor = 0
    for phrase in split_ja_utterances(text):
        i, j = align_phrase_window(phrase, words, cursor)
        if j <= i:
            continue
        cursor = j
        start, end = words[i][1], words[j - 1][2]
        if end <= start:
            end = start + 0.4
        ja = cleanup_ja(phrase)
        if ja:
            cues.append(Cue(start, end, ja))
    return cues


def cues_from_chunk_texts(dest: Path, words: list[tuple[str, float, float]]) -> list[Cue]:
    dest = Path(dest)
    chunks_dir = dest / f"{dest.name}.stt-chunks"
    if not chunks_dir.is_dir():
        return []
    files = sorted(chunks_dir.glob("*.json"))
    if not files:
        return []
    cursor = 0
    cues: list[Cue] = []
    for path in files:
        try:
            off = int(path.stem)
        except ValueError:
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw = str(payload.get("text") or "").strip()
        if not raw:
            continue
        take = float(payload.get("_nominal_take") or 240.0)
        window = [(w, a, b) for w, a, b in words if off - 1.0 <= a < off + take + 1.0]
        if not window:
            continue
        local = window
        loc_cur = 0
        for phrase in split_ja_utterances(raw):
            i, j = align_phrase_window(phrase, local, loc_cur)
            if j <= i:
                continue
            loc_cur = j
            start, end = local[i][1], local[j - 1][2]
            if end <= start:
                end = start + 0.4
            text = cleanup_ja(phrase)
            if text:
                cues.append(Cue(start, end, text))
        if window:
            # advance global cursor past this chunk
            last_t = window[-1][2]
            while cursor < len(words) and words[cursor][1] <= last_t + 0.05:
                cursor += 1
    return cues
_FILLER_JA = {
    "うん",
    "ええ",
    "ああ",
    "あー",
    "ん",
    "はぁ",
    "あっ",
    "えっ",
    "おっ",
    "ふぅ",
    "んっ",
    "あっ…",
    "嗯",
}


def visual_len(text: str) -> float:
    n = 0.0
    for ch in text or "":
        n += 1.0 if ord(ch) > 0x2FF else 0.5
    return n


def phrases_from_words(
    words: list[tuple[str, float, float]],
    *,
    max_span: float = 8.0,
    pause: float = 1.05,
) -> list[Cue]:
    if not words:
        return []
    out: list[Cue] = []
    buf: list[tuple[str, float, float]] = []

    def flush() -> None:
        if not buf:
            return
        text = join_ja([w[0] for w in buf])
        if text:
            out.append(Cue(buf[0][1], buf[-1][2], text))
        buf.clear()

    for item in words:
        if buf and (item[1] - buf[-1][2] > pause or item[2] - buf[0][1] > max_span):
            flush()
        buf.append(item)
        joined = join_ja([w[0] for w in buf])
        span = buf[-1][2] - buf[0][1]
        if re.search(r'[。！？!?]["\']?$', joined.strip()):
            flush()
        elif visual_len(joined) >= 22 and span >= 1.6 and re.search(
            r"[はがをにでとねよわ、。！？]$", joined
        ):
            flush()
    flush()
    return [cue for cue in out if cue.text.strip()]


def split_on_sentence_punct(cues: list[Cue]) -> list[Cue]:
    out: list[Cue] = []
    for cue in cues:
        parts = [p.strip() for p in re.split(r"(?<=[。！？!?])\s*", cue.text) if p.strip()]
        if len(parts) <= 1:
            out.append(cue)
            continue
        total = sum(max(len(part), 1) for part in parts)
        t = cue.start
        span = max(cue.end - cue.start, 0.4 * len(parts))
        for i, part in enumerate(parts):
            dur = span * (len(part) / total)
            end = cue.end if i == len(parts) - 1 else t + max(dur, 0.45)
            if end > cue.end:
                end = cue.end
            out.append(Cue(t, max(end, t + 0.35), part))
            t = end
    return out


_CONT_START = re.compile(r"^(て|で|に|を|は|が|の|と|も|っ|ょ|ゃ|ゅ|ん|げ|だ|す|ス|キ|、|。)")
_CONT_END = re.compile(r"(でし|し|て|っ|ちゃ|じゃ|けん|ます|でしょ|あ|ちょう|キ|一|ま|な|い)$")


def coalesce_cues(
    cues: list[Cue],
    *,
    max_span: float = 10.0,
    max_pause: float = 1.5,
) -> list[Cue]:
    if not cues:
        return []
    out: list[Cue] = [cues[0]]
    for cue in cues[1:]:
        prev = out[-1]
        pause = cue.start - prev.end
        span = cue.end - prev.start
        nxt = (cue.text or "").strip()
        prev_text = (prev.text or "").strip()
        prev_done = bool(re.search(r'[。！？!?]["\']?$', prev_text))
        frag = glyph_count(cue.text) <= 4 or len(nxt) <= 8
        particle = bool(_JA_PARTICLE.fullmatch(nxt))
        glue = pause <= max_pause and span <= max_span and (
            particle or (frag and (not prev_done or pause <= 0.45))
        )
        if not glue and not prev_done and pause <= 3.2 and span <= 12.0:
            cut = bool(_CONT_END.search(prev_text)) or prev_text.endswith("、")
            small = bool(nxt) and nxt[0] in _SMALL_KANA
            if cut or small or _CONT_START.match(nxt) or glyph_count(nxt) <= 2:
                glue = True
        if glue:
            text = join_ja([prev.text, cue.text])
            out[-1] = Cue(prev.start, max(prev.end, cue.end), text)
            continue
        out.append(cue)
    return out


def rows_from_spoken_words(
    words: list[tuple[str, float, float]],
    dest: Path | None = None,
) -> list[BilingualCue]:
    cues: list[Cue] = []
    if dest is not None:
        try:
            dest = Path(dest)
            cache = dest / f"{dest.name}.grok-stt.json"
            payload = None
            if cache.is_file():
                payload = json.loads(cache.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and not payload.get("chunked") and (payload.get("text") or "").strip():
                cues = cues_from_stt_text(str(payload.get("text") or ""), words)
                print("subs: sentence axis from whole-file STT text", flush=True)
            else:
                cues = cues_from_chunk_texts(dest, words)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            print(f"warning: STT-text cues skipped: {exc}", file=sys.stderr, flush=True)
            cues = []
    if len(cues) < 8:
        cues = split_on_sentence_punct(coalesce_cues(phrases_from_words(words)))
    else:
        cues = coalesce_cues(cues, max_span=6.0, max_pause=0.55)
        print(f"subs: {len(cues)} cues from STT sentence text", flush=True)
    return [
        BilingualCue(cue.start, cue.end, "", cleanup_ja(cue.text))
        for cue in cues
        if cleanup_ja(cue.text)
    ]


def merge_vocal_cues(rows: list[BilingualCue], vocals: list[dict[str, Any]]) -> list[BilingualCue]:
    if not vocals:
        return rows
    covered = [(r.start, r.end) for r in rows]
    extra: list[BilingualCue] = []
    for item in vocals:
        start = float(item["start"])
        end = float(item["end"])
        if end - start < 0.35:
            continue
        if any(min(end, b) - max(start, a) > 0.12 for a, b in covered):
            continue
        extra.append(BilingualCue(start, end, str(item.get("zh") or ""), str(item.get("ja") or "")))
        covered.append((start, end))
    out = list(rows) + extra
    out.sort(key=lambda r: (r.start, r.end))
    print(f"vocals: merged {len(extra)} 嗯/啊 cues -> {len(out)} total", flush=True)
    return out


def keyterms_from_meta(meta: dict[str, Any] | None) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        t = (text or "").strip()
        if not t or t in seen or len(t) > 50:
            return
        seen.add(t)
        terms.append(t)

    if not meta:
        return terms
    title = str(meta.get("title") or "")
    for part in re.split(r"[\s　/|]+", title):
        if re.fullmatch(r"[\u3040-\u9fff]{2,8}", part):
            add(part)
    for actor in meta.get("actors") or []:
        if isinstance(actor, dict):
            add(str(actor.get("name") or ""))
        else:
            add(str(actor))
    for extra in ("波多野結衣", "波多野结衣", "笹倉彩", "ノンケ", "レズビアン"):
        if extra in title:
            add(extra)
    return terms[:20]


_GROK_ZH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "cues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "i": {"type": "integer"},
                    "zh": {"type": "string"},
                },
                "required": ["i", "zh"],
            },
        }
    },
    "required": ["cues"],
}

_GROK_ZH_SYSTEM = (
    "你是字幕组。这是双人日语对白，只有两个女人：\n"
    "结衣＝波多野结衣（ゆい／波多野さん／はたのさん／ゆいさん）。"
    "彩＝笹仓彩（あや／彩さん／アヤさん）。\n"
    "术语：はたのさん/はやさん/篠野さん→波多野；嫌さん/ゆいさん/いいさん→结衣；"
    "アヤ/彩さん→彩；貢献に→出把力；でしょ→吧；キス→吻；点と面→点和面；"
    "髄まで/ミソまで→骨子里；取り込み→拉拢；ロマンス詐欺→恋爱诈骗；"
    "レズロマンス詐欺→女同恋爱诈骗；有閑マダム→有闲贵妇。\n"
    "先在脑子里把破碎假名拼成完整日语句，再译成本条中文。"
    "prev_ja/next_ja 只是邻句，不要把它们写进本条 zh。\n"
    "i 从 0 起连续编号，每条都必须输出中文。口播简体，两行以内，不要注音和括号。"
    "うん/ああ/ん/はぁ/あっ 短译嗯/啊或省略。不要把日文原样抄进 zh。"
)


def _zh_schema_for_batch(n: int) -> dict[str, Any]:
    schema = json.loads(json.dumps(_GROK_ZH_SCHEMA))
    cues = schema["properties"]["cues"]
    cues["minItems"] = n
    cues["maxItems"] = n
    return schema


def _parse_grok_cues(stdout: str) -> dict[int, str]:
    text = stdout.strip()
    if not text:
        return {}
    try:
        outer = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return {}
        outer = json.loads(match.group(0))
    if isinstance(outer, dict) and isinstance(outer.get("choices"), list) and outer["choices"]:
        msg = outer["choices"][0]
        if isinstance(msg, dict):
            content = (
                (msg.get("message") or {}).get("content")
                if isinstance(msg.get("message"), dict)
                else msg.get("content")
            )
            if isinstance(content, str) and content.strip():
                try:
                    outer = json.loads(content)
                except json.JSONDecodeError:
                    match = re.search(r"\{[\s\S]*\}", content)
                    outer = json.loads(match.group(0)) if match else outer
    inner = outer.get("text") if isinstance(outer, dict) else None
    payload = outer
    if isinstance(inner, str):
        try:
            payload = json.loads(inner)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", inner)
            payload = json.loads(match.group(0)) if match else {}
    cues = payload.get("cues") if isinstance(payload, dict) else None
    out: dict[int, str] = {}
    for item in cues or []:
        try:
            idx = int(item.get("i"))
            zh = str(item.get("zh") or "").strip()
        except (TypeError, ValueError, AttributeError):
            continue
        if zh:
            out[idx] = zh
    return out


def _zh_workers() -> int:
    raw = os.environ.get("GROK_ZH_WORKERS") or os.environ.get("JABLE_GROK_ZH_WORKERS") or "6"
    try:
        n = int(raw)
    except ValueError:
        n = 6
    return max(1, min(n, 8))


def _zh_batch_size(default: int) -> int:
    raw = os.environ.get("GROK_ZH_BATCH") or ""
    if not raw.strip():
        return default
    try:
        n = int(raw)
    except ValueError:
        return default
    return max(8, min(n, 80))


def _cjk_len(text: str) -> int:
    return sum(1 for ch in text or "" if "\u4e00" <= ch <= "\u9fff")


def _normalize_mapped(mapped: dict[int, str], n: int) -> dict[int, str]:
    if not mapped or n <= 0:
        return {}
    keys = set(mapped)
    if 0 not in keys and keys <= set(range(1, n + 1)) and (n in keys or n - 1 in keys):
        mapped = {idx - 1: zh for idx, zh in mapped.items()}
    return {idx: zh for idx, zh in mapped.items() if 0 <= idx < n and zh}


def _apply_zh_map(
    updated: list[BilingualCue],
    offset: int,
    batch: list[BilingualCue],
    mapped: dict[int, str],
) -> None:
    mapped = _normalize_mapped(mapped, len(batch))
    for i, zh in mapped.items():
        src = batch[i]
        updated[offset + i] = BilingualCue(src.start, src.end, zh, src.ja)


def _zh_payload_indexed(all_rows: list[BilingualCue], indices: list[int]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for i, abs_i in enumerate(indices):
        prev_ja = [all_rows[j].ja for j in range(max(0, abs_i - 2), abs_i)]
        next_ja = all_rows[abs_i + 1].ja if abs_i + 1 < len(all_rows) else ""
        items.append(
            {
                "i": i,
                "ja": all_rows[abs_i].ja,
                "prev_ja": prev_ja,
                "next_ja": next_ja,
            }
        )
    return items


def _run_zh_batch_http(
    offset: int,
    batch: list[BilingualCue],
    title: str,
    total: int,
    all_rows: list[BilingualCue],
) -> tuple[int, list[BilingualCue], dict[int, str]]:
    payload = _zh_payload_indexed(all_rows, list(range(offset, offset + len(batch))))
    user = f"视频标题：{title or '(unknown)'}\n输入：\n" + json.dumps(payload, ensure_ascii=False)
    print(f"grok: 中文翻译 {offset + 1}-{offset + len(batch)}/{total} (http)", flush=True)
    data = grok_chat_json(
        [
            {"role": "system", "content": _GROK_ZH_SYSTEM},
            {"role": "user", "content": user},
        ],
        _zh_schema_for_batch(len(batch)),
    )
    mapped = _parse_grok_cues(json.dumps(data, ensure_ascii=False))
    if not mapped:
        content = ""
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = json.dumps(data, ensure_ascii=False)[:2000]
        mapped = _parse_grok_cues(content if isinstance(content, str) else "")
    return offset, batch, mapped


def _run_zh_batch_cli(
    offset: int,
    batch: list[BilingualCue],
    title: str,
    total: int,
    grok: Path,
    all_rows: list[BilingualCue],
) -> tuple[int, list[BilingualCue], dict[int, str]]:
    payload = _zh_payload_indexed(all_rows, list(range(offset, offset + len(batch))))
    prompt = _GROK_ZH_SYSTEM + f"\n视频标题：{title or '(unknown)'}\n输入：\n" + json.dumps(
        payload, ensure_ascii=False
    )
    prompt_file = Path(os.environ.get("TEMP") or ".") / f"jable-grok-zh-{os.getpid()}-{offset}.txt"
    schema = json.dumps(_zh_schema_for_batch(len(batch)), ensure_ascii=False, separators=(",", ":"))
    try:
        prompt_file.write_text(prompt, encoding="utf-8")
        cmd = [
            str(grok),
            "--prompt-file",
            str(prompt_file),
            "--output-format",
            "json",
            "--json-schema",
            schema,
            "--model",
            "grok-4.6",
            "--reasoning-effort",
            "low",
            "--max-turns",
            "1",
            "--no-subagents",
            "--disable-web-search",
            "--verbatim",
            "--always-approve",
        ]
        print(f"grok: 中文翻译 {offset + 1}-{offset + len(batch)}/{total} (cli)", flush=True)
        result = subprocess.run(cmd, capture_output=True, timeout=180, check=False)
        stdout = (result.stdout or b"").decode("utf-8", errors="replace")
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace")
            print(
                f"warning: grok batch {offset} exit {result.returncode}: {stderr[-400:]}",
                file=sys.stderr,
                flush=True,
            )
            return offset, batch, {}
        return offset, batch, _parse_grok_cues(stdout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"warning: grok failed: {exc}", file=sys.stderr, flush=True)
        return offset, batch, {}
    finally:
        try:
            prompt_file.unlink(missing_ok=True)
        except OSError:
            pass


def _flag_bad_zh(rows: list[BilingualCue]) -> list[int]:
    flagged: list[int] = []
    for i, row in enumerate(rows):
        ja = (row.ja or "").strip()
        zh = (row.zh or "").strip()
        ja_n = glyph_count(ja)
        cjk = _cjk_len(zh)
        filler = re.sub(r"[…。、！？!?~\s]", "", ja) in _FILLER_JA
        bad = False
        if not zh:
            bad = True
        elif filler and cjk >= 6:
            bad = True
        elif ja_n <= 2 and cjk >= 10:
            bad = True
        elif ja_n >= 16 and cjk <= 2:
            bad = True
        elif zh == ja or (re.search(r"[\u3040-\u30ff]", zh) and cjk < 2):
            bad = True
        if bad:
            flagged.append(i)
    return flagged


def grok_optimize_zh(
    rows: list[BilingualCue],
    *,
    title: str = "",
    batch_size: int = 24,
) -> list[BilingualCue]:
    if not rows:
        return rows
    batch_size = _zh_batch_size(batch_size)
    workers = _zh_workers()
    updated = list(rows)
    jobs = [
        (offset, rows[offset : offset + batch_size])
        for offset in range(0, len(rows), batch_size)
    ]
    print(f"grok: {len(rows)} cues, {len(jobs)} batches, {workers} workers", flush=True)
    use_http = True
    try:
        grok_api_token()
    except Exception as exc:  # noqa: BLE001
        print(f"warning: grok HTTP auth missing ({exc}); try CLI", file=sys.stderr, flush=True)
        use_http = False

    def run_job(offset: int, batch: list[BilingualCue]) -> tuple[int, list[BilingualCue], dict[int, str]]:
        if use_http:
            return _run_zh_batch_http(offset, batch, title, len(rows), updated)
        grok = find_grok()
        if grok is None:
            return offset, batch, {}
        return _run_zh_batch_cli(offset, batch, title, len(rows), grok, updated)

    try:
        probe_off, probe_batch = jobs[0]
        try:
            offset, batch, mapped = run_job(probe_off, probe_batch)
        except Exception as exc:
            if use_http and find_grok() is not None:
                print(f"warning: grok HTTP failed ({exc}); fall back to CLI", file=sys.stderr, flush=True)
                use_http = False
                offset, batch, mapped = run_job(probe_off, probe_batch)
            else:
                raise
        if use_http and not mapped and find_grok() is not None:
            print("warning: grok HTTP empty; fall back to CLI", file=sys.stderr, flush=True)
            use_http = False
            offset, batch, mapped = run_job(probe_off, probe_batch)
        _apply_zh_map(updated, offset, batch, mapped)
        if not mapped:
            print(f"warning: grok batch {offset} empty parse", file=sys.stderr, flush=True)
        rest = jobs[1:]
        if rest:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [pool.submit(run_job, off, bat) for off, bat in rest]
                for fut in as_completed(futs):
                    try:
                        off, bat, mapped = fut.result()
                    except Exception as exc:  # noqa: BLE001
                        print(f"warning: grok worker failed: {exc}", file=sys.stderr, flush=True)
                        continue
                    if not mapped:
                        print(f"warning: grok batch {off} empty parse", file=sys.stderr, flush=True)
                        continue
                    _apply_zh_map(updated, off, bat, mapped)
        if use_http:
            bad = _flag_bad_zh(updated)
            if bad:
                print(f"grok: zh repair {len(bad)} cues", flush=True)
                repair_size = 12
                chunks = [bad[i : i + repair_size] for i in range(0, len(bad), repair_size)]

                def repair_job(indices: list[int]) -> tuple[list[int], dict[int, str]]:
                    payload = _zh_payload_indexed(updated, indices)
                    user = (
                        f"视频标题：{title or '(unknown)'}\n"
                        "只重译下列可疑条，仍只译本条 ja。\n输入：\n"
                        + json.dumps(payload, ensure_ascii=False)
                    )
                    data = grok_chat_json(
                        [
                            {"role": "system", "content": _GROK_ZH_SYSTEM},
                            {"role": "user", "content": user},
                        ],
                        _zh_schema_for_batch(len(indices)),
                    )
                    mapped = _parse_grok_cues(json.dumps(data, ensure_ascii=False))
                    if not mapped:
                        try:
                            mapped = _parse_grok_cues(data["choices"][0]["message"]["content"])
                        except (KeyError, IndexError, TypeError):
                            mapped = {}
                    return indices, _normalize_mapped(mapped, len(indices))

                with ThreadPoolExecutor(max_workers=min(workers, len(chunks))) as pool:
                    futs = [pool.submit(repair_job, chunk) for chunk in chunks]
                    for fut in as_completed(futs):
                        try:
                            indices, mapped = fut.result()
                        except Exception as exc:  # noqa: BLE001
                            print(f"warning: grok repair failed: {exc}", file=sys.stderr, flush=True)
                            continue
                        for i, zh in mapped.items():
                            abs_i = indices[i]
                            src = updated[abs_i]
                            updated[abs_i] = BilingualCue(src.start, src.end, zh, src.ja)
    except Exception as exc:  # noqa: BLE001
        print(f"warning: grok 中文翻译 skipped: {exc}", file=sys.stderr, flush=True)
    filled = sum(1 for row in updated if row.zh)
    print(f"grok: zh filled {filled}/{len(updated)}", flush=True)
    return updated


def _ass_time(t: float) -> str:
    total_cs = max(0, int(round(t * 100)))
    hours, rem = divmod(total_cs, 360000)
    minutes, rem = divmod(rem, 6000)
    seconds, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"


def _srt_time(t: float) -> str:
    total_ms = max(0, int(round(t * 1000)))
    hours, rem = divmod(total_ms, 3600000)
    minutes, rem = divmod(rem, 60000)
    seconds, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def _ass_text(text: str) -> str:
    text = text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")
    return text.replace("\n", r"\N")


def write_bilingual_ass(path: Path, rows: list[BilingualCue]) -> None:
    header = """[Script Info]
Title: zh-ja bilingual
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CN,Microsoft YaHei,52,&H00FFFFFF,&H000000FF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,2,48,48,78,1
Style: JA,Yu Gothic,32,&H00DDDDDD,&H000000FF,&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,48,48,22,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for row in rows:
        start, end = _ass_time(row.start), _ass_time(row.end)
        if row.zh:
            lines.append(f"Dialogue: 0,{start},{end},CN,,0,0,0,,{_ass_text(row.zh)}\n")
        if row.ja:
            lines.append(f"Dialogue: 0,{start},{end},JA,,0,0,0,,{_ass_text(row.ja)}\n")
    path.write_text("".join(lines), encoding="utf-8")


def write_bilingual_srt(path: Path, rows: list[BilingualCue]) -> None:
    chunks: list[str] = []
    n = 0
    for row in rows:
        body = "\n".join(p for p in (row.zh, row.ja) if p)
        if not body:
            continue
        n += 1
        chunks.append(f"{n}\n{_srt_time(row.start)} --> {_srt_time(row.end)}\n{body}\n")
    path.write_text("\n".join(chunks) + ("\n" if chunks else ""), encoding="utf-8")


def _ts_to_sec(h: str | None, m: str, s: str, frac: str) -> float:
    ms = int(frac.ljust(3, "0")[:3])
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + ms / 1000.0


def parse_bilingual_srt(path: Path) -> list[BilingualCue]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    rows: list[BilingualCue] = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip() != ""]
        if len(lines) < 2:
            continue
        match = re.search(
            r"(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})\s+-->\s+(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})",
            lines[1] if re.match(r"^\d+$", lines[0]) else lines[0],
        )
        body_lines = lines[2:] if match and re.match(r"^\d+$", lines[0]) else lines[1:]
        if not match:
            continue
        start = _ts_to_sec(match.group(1), match.group(2), match.group(3), match.group(4))
        end = _ts_to_sec(match.group(5), match.group(6), match.group(7), match.group(8))
        zh, ja = "", ""
        if len(body_lines) >= 2:
            zh, ja = body_lines[0].strip(), " ".join(body_lines[1:]).strip()
        elif body_lines:
            text = body_lines[0].strip()
            if re.search(r"[\u3040-\u30ff]", text):
                ja = text
            else:
                zh = text
        if zh or ja:
            rows.append(BilingualCue(start, end, zh, ja))
    return rows


def write_rows_json(path: Path, rows: list[BilingualCue]) -> None:
    payload = [
        {"start": round(r.start, 3), "end": round(r.end, 3), "zh": r.zh, "ja": r.ja} for r in rows
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _ffmpeg_subtitles_arg(ass: Path) -> str:
    text = ass.resolve().as_posix().replace("\\", "/")
    text = text.replace(":", r"\:").replace("'", r"\'")
    return f"subtitles='{text}'"


def embed_subtitles_mp4(
    media: Path,
    dest: Path,
    code: str,
    ffmpeg: Path,
    built: dict[str, Any],
    *,
    hardsub: bool = False,
) -> bool:
    if media.suffix.lower() != ".mp4":
        print(f"warning: embed skip (not mp4): {media.name}", file=sys.stderr, flush=True)
        return False
    if not ffmpeg.is_file():
        print("warning: embed skip (ffmpeg missing)", file=sys.stderr, flush=True)
        return False
    tmp = media.with_name(media.stem + ".embed.tmp.mp4")
    if hardsub:
        vf = _ffmpeg_subtitles_arg(built["ass"])
        cmd = [
            str(ffmpeg),
            "-hide_banner",
            "-y",
            "-i",
            str(media),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "fast",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(tmp),
        ]
        print(f"embed: hardsub ASS 中上日下 -> {media.name}", flush=True)
        timeout = max(300, int(media.stat().st_size / 400_000) + 120)
    else:
        cmd = [
            str(ffmpeg),
            "-hide_banner",
            "-y",
            "-i",
            str(media),
            "-i",
            str(built["srt"]),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-map",
            "1:0",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-c:s",
            "mov_text",
            "-metadata:s:s:0",
            "language=zho",
            "-metadata:s:s:0",
            "title=简日双语",
            "-disposition:s:0",
            "default",
            "-movflags",
            "+faststart",
            str(tmp),
        ]
        print(f"embed: mux 简日双语 ({built['cues']} cues) -> {media.name}", flush=True)
        timeout = max(120, int(media.stat().st_size / 2_000_000) + 60)
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"warning: embed failed: {exc}", file=sys.stderr, flush=True)
        if tmp.is_file():
            tmp.unlink(missing_ok=True)
        return False
    if result.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < 1024:
        err = (result.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()
        tail = "\n".join(err[-12:])
        print(f"warning: embed ffmpeg failed\n{tail}", file=sys.stderr, flush=True)
        if tmp.is_file():
            tmp.unlink(missing_ok=True)
        return False
    replaced = False
    last_err: Exception | None = None
    for _attempt in range(6):
        try:
            os.replace(tmp, media)
            replaced = True
            break
        except PermissionError as exc:
            last_err = exc
            time.sleep(1.2)
    if not replaced:
        if tmp.is_file():
            tmp.unlink(missing_ok=True)
        print(
            f"warning: embed wrote {built['ass'].name} / {built['srt'].name} "
            f"but could not replace mp4 (file in use): {last_err}",
            file=sys.stderr,
            flush=True,
        )
        return False
    print(f"embed: ok  {built['ass'].name}  {built['srt'].name}", flush=True)
    return True


def resolve_work(arg: str, cwd: Path) -> Path:
    raw = (arg or "").strip().strip('"')
    if not raw:
        die("need a work directory or video code")
    p = Path(raw)
    cands = []
    if p.is_absolute():
        cands.append(p)
    else:
        cands.extend(
            [
                cwd / p,
                cwd / "out" / p,
                HERE / "out" / p,
                HERE / p,
            ]
        )
    for cand in cands:
        if cand.is_dir():
            return cand.resolve()
    die(f"not a directory: {arg}")
    raise SystemExit(1)


def find_media(work: Path, code: str) -> Path:
    mp4 = work / f"{code}.mp4"
    if mp4.is_file() and mp4.stat().st_size > 1024:
        return mp4
    hits = [p for p in work.glob("*.mp4") if p.is_file() and ".embed." not in p.name]
    if not hits:
        die(f"mp4 not found in {work}")
    return max(hits, key=lambda p: p.stat().st_size)


def load_meta(work: Path) -> dict[str, Any]:
    path = work / "meta.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def build_bilingual_subtitles(
    dest: Path,
    code: str,
    media: Path,
    ffmpeg: Path,
    *,
    title: str = "",
    use_grok: bool = True,
    keyterms: list[str] | None = None,
    chunk_sec: float = 240.0,
    force_stt: bool = False,
    retry_empty: bool = True,
    vocals: bool = True,
) -> dict[str, Any]:
    audio = extract_audio_track(media, dest, ffmpeg)
    print(f"grok-voice: demux {audio.name} (audio only, not the video)", flush=True)
    words = grok_stt_words(
        audio,
        dest,
        ffmpeg,
        chunk_sec=chunk_sec,
        language="ja",
        keyterms=None,
        force=force_stt,
        retry_empty=retry_empty,
        vad_threshold="0",
    )
    rows = rows_from_spoken_words(words, dest=dest)
    print(f"subs: grok-voice {len(rows)} cues from {len(words)} spoken words", flush=True)
    if len(rows) < 3:
        raise RuntimeError("grok STT produced too few subtitle cues")
    if use_grok:
        rows = grok_optimize_zh(rows, title=title)
    if vocals:
        covered = [(r.start, r.end) for r in rows]
        try:
            vrows = vocal_cues_for_audio(audio, ffmpeg, covered, dest=dest)
        except Exception as exc:  # noqa: BLE001
            print(f"warning: vocal layer skipped: {exc}", file=sys.stderr, flush=True)
            vrows = []
        rows = merge_vocal_cues(rows, vrows)
    ass_path = dest / f"{code}.zh-ja.ass"
    srt_path = dest / f"{code}.zh-ja.srt"
    json_path = dest / f"{code}.zh-ja.json"
    write_bilingual_ass(ass_path, rows)
    write_bilingual_srt(srt_path, rows)
    write_rows_json(json_path, rows)
    index = dest / "subtitles.json"
    index.write_text(
        json.dumps(
            {
                "source": "speech+vocal",
                "language": "ja",
                "cues": len(rows),
                "files": [ass_path.name, srt_path.name, json_path.name],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"subs: bilingual {len(rows)} cues (speech) -> {ass_path.name}", flush=True)
    return {
        "ass": ass_path,
        "srt": srt_path,
        "json": json_path,
        "cues": len(rows),
        "rows": rows,
    }


def build_for_dir(
    work: Path,
    *,
    ffmpeg: Path | None = None,
    embed: bool = True,
    hardsub: bool = False,
    use_grok: bool = True,
    chunk_sec: float = 240.0,
    force_stt: bool = False,
    retry_empty: bool = True,
    vocals: bool = True,
) -> dict[str, Any]:
    work = Path(work).resolve()
    if not work.is_dir():
        die(f"not a directory: {work}")
    code = work.name
    meta = load_meta(work)
    if meta.get("code"):
        code = str(meta["code"])
    media = find_media(work, code)
    ff = ffmpeg or find_ffmpeg()
    if not ff:
        die("ffmpeg not found; install with: winget install Gyan.FFmpeg.Essentials")
    title = str(meta.get("title") or "")
    print(f"subs: {code}", flush=True)
    print(f"media: {media}", flush=True)
    built = build_bilingual_subtitles(
        work,
        code,
        media,
        ff,
        title=title,
        use_grok=use_grok,
        keyterms=keyterms_from_meta(meta),
        chunk_sec=chunk_sec,
        force_stt=force_stt,
        retry_empty=retry_empty,
        vocals=vocals,
    )
    embedded = False
    if embed:
        embedded = embed_subtitles_mp4(media, work, code, ff, built, hardsub=hardsub)
    return {
        "ok": True,
        "code": code,
        "media": str(media),
        "cues": built["cues"],
        "ass": str(built["ass"]),
        "srt": str(built["srt"]),
        "embedded": embedded,
    }


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="抽音 + Grok STT 对轴，写出简日双语 ASS/SRT（中上日下）。"
    )
    parser.add_argument("path", nargs="?", help="作品目录或番号，例如 out\\mfyd-180")
    parser.add_argument("--no-embed", action="store_true", help="只写字幕文件，不嵌进 mp4")
    parser.add_argument("--no-translate", action="store_true", help="只出日文轴，不译中文")
    parser.add_argument("--force-stt", action="store_true", help="丢掉 grok-stt 缓存重听")
    parser.add_argument(
        "--no-retry-empty",
        action="store_true",
        help="空 STT 分片也复用缓存（默认会关 VAD 重听空片）",
    )
    parser.add_argument("--hardsub", action="store_true", help="把 ASS 烧进画面（会重编码）")
    parser.add_argument("--chunk-sec", type=float, default=240.0, help="STT 分片秒数，默认 240")
    parser.add_argument("--no-vocals", action="store_true", help="不要给喘息/无词发声补 嗯/啊")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    path = args.path
    if not path:
        try:
            path = input("作品目录或番号: ").strip()
        except EOFError:
            path = ""
    if not path:
        die("need a work directory or video code")
    work = resolve_work(path, Path.cwd())
    result = build_for_dir(
        work,
        embed=not args.no_embed,
        hardsub=args.hardsub,
        use_grok=not args.no_translate,
        chunk_sec=args.chunk_sec,
        force_stt=args.force_stt,
        retry_empty=not args.no_retry_empty,
        vocals=not args.no_vocals,
    )
    print(flush=True)
    print("========== done ==========")
    print(f"dir:  {work}")
    print(f"ass:  {result['ass']}")
    print(f"srt:  {result['srt']}")
    print(f"cues: {result['cues']}")
    if result.get("embedded"):
        print(f"mp4:  {result['media']} (soft sub default)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
