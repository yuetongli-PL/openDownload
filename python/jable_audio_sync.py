# -*- coding: utf-8 -*-
"""Demux mp4 audio and let Grok STT produce the subtitle clock.

Ported from the Youtube subtitle pipeline (read-only). Japanese tokens are
kept; the Latin-only word filter that dropped CJK is not used here.
"""
from __future__ import annotations

import array
import json
import math
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

STT_URL = "https://api.x.ai/v1/stt"
CHAT_URL = "https://api.x.ai/v1/chat/completions"
_ZH_MODEL_CACHE: str | None = None
_AUDIO_ONLY = {".m4a", ".aac", ".mp3", ".wav", ".ogg", ".opus", ".flac"}
_MIME = {
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".flac": "audio/flac",
}
_KEEP_RE = re.compile(r"[A-Za-z0-9'\u3040-\u30ff\u3400-\u9fff\u3005ー]")
_NOISE_RE = re.compile(
    r"^[\[\(\（]?(music|applause|laughter|cheers|singing|音楽|拍手|笑い)[\]\)\）]?$",
    re.I,
)
_PUNCT_ONLY_RE = re.compile(r"^[。、！？!?…〜~・,.\s]+$")


def grok_api_token() -> str:
    for name in ("XAI_API_KEY", "GROK_API_KEY"):
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    path = Path.home() / ".grok" / "auth.json"
    if not path.is_file():
        raise RuntimeError("no grok login (~/.grok/auth.json) and no XAI_API_KEY")
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        for entry in data.values():
            if isinstance(entry, dict):
                tok = entry.get("key") or entry.get("access_token")
                if tok:
                    return str(tok)
            elif isinstance(entry, str) and len(entry) > 20:
                return entry
    raise RuntimeError("grok auth.json has no access token")


def _zh_model_candidates() -> list[str]:
    env = (os.environ.get("GROK_ZH_MODEL") or os.environ.get("JABLE_GROK_ZH_MODEL") or "").strip()
    models: list[str] = []
    if env:
        models.append(env)
    models.extend(
        (
            "grok-4.6",
            "grok-4-fast-non-reasoning",
            "grok-4.20-0309-non-reasoning",
            "grok-4-1-fast-non-reasoning",
        )
    )
    seen: set[str] = set()
    out: list[str] = []
    for name in models:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _chat_uses_low_effort(model: str) -> bool:
    name = model.lower()
    if "non-reasoning" in name:
        return False
    return "grok-4.6" in name or "grok-4.5" in name


def grok_chat_json(
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    *,
    timeout: int = 90,
) -> dict[str, Any]:
    global _ZH_MODEL_CACHE
    models = [_ZH_MODEL_CACHE] if _ZH_MODEL_CACHE else _zh_model_candidates()
    last_err: Exception | None = None
    for model in models:
        if not model:
            continue
        payload: dict[str, Any] = {
            "model": model,
            "temperature": 0.2,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "zh_cues",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        if _chat_uses_low_effort(model):
            payload["reasoning_effort"] = "low"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        for attempt in range(4):
            req = urllib.request.Request(CHAT_URL, data=body, method="POST")
            req.add_header("Authorization", "Bearer " + grok_api_token())
            req.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise RuntimeError("chat completions returned non-object JSON")
                _ZH_MODEL_CACHE = model
                return data
            except urllib.error.HTTPError as exc:
                err = exc.read().decode("utf-8", errors="replace")[:800]
                if exc.code == 429 and attempt < 3:
                    time.sleep(1.5 * (2**attempt))
                    continue
                if exc.code in {404, 400} and (
                    "model" in err.lower()
                    or "not found" in err.lower()
                    or "does not exist" in err.lower()
                ):
                    last_err = RuntimeError(f"grok chat HTTP {exc.code} model={model}: {err}")
                    _ZH_MODEL_CACHE = None
                    break
                raise RuntimeError(f"grok chat HTTP {exc.code}: {err}") from exc
            except urllib.error.URLError as exc:
                last_err = RuntimeError(f"grok chat request failed: {exc}")
                if attempt < 3:
                    time.sleep(1.0 * (2**attempt))
                    continue
                raise last_err from exc
    if last_err:
        raise last_err
    raise RuntimeError("grok chat: no model available")


def extract_audio_track(media: Path, dest: Path, ffmpeg: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    media = Path(media)
    if media.suffix.lower() in _AUDIO_ONLY and media.is_file() and media.stat().st_size > 1000:
        return media
    out = dest / f"{media.stem}.audio.m4a"
    if out.is_file() and out.stat().st_size > 1000:
        print(f"grok-voice: reuse {out.name}", flush=True)
        return out
    copy_cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-y",
        "-i",
        str(media),
        "-vn",
        "-c:a",
        "copy",
        str(out),
    ]
    result = subprocess.run(copy_cmd, capture_output=True, check=False)
    if result.returncode == 0 and out.is_file() and out.stat().st_size > 1000:
        return out
    if out.is_file():
        out.unlink(missing_ok=True)
    aac_cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-y",
        "-i",
        str(media),
        "-vn",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(out),
    ]
    result = subprocess.run(aac_cmd, capture_output=True, check=False)
    if result.returncode != 0 or not out.is_file() or out.stat().st_size < 1000:
        err = (result.stderr or b"").decode("utf-8", errors="replace")[-500:]
        raise RuntimeError(f"ffmpeg demux audio failed: {err}")
    return out


def keep_spoken_token(raw: str) -> bool:
    text = (raw or "").strip()
    if not text:
        return False
    if _NOISE_RE.fullmatch(text):
        return False
    if _PUNCT_ONLY_RE.fullmatch(text):
        return True
    return bool(_KEEP_RE.search(text))


def glyph_count(text: str) -> int:
    n = 0
    for ch in text or "":
        if ch.isalnum() or "\u3040" <= ch <= "\u30ff" or "\u3400" <= ch <= "\u9fff" or ch in "ー々":
            n += 1
    return n


def parse_stt_words(payload: dict[str, Any], *, offset: float = 0.0) -> list[tuple[str, float, float]]:
    words: list[tuple[str, float, float]] = []
    for item in payload.get("words") or []:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("text") or "").strip()
        if not keep_spoken_token(raw):
            continue
        try:
            start = float(item.get("start") or 0.0) + offset
            end = float(item.get("end") or start) + offset
        except (TypeError, ValueError):
            continue
        if end <= start:
            end = start + 0.08
        words.append((raw, start, end))
    return clamp_word_times(words)


def clamp_word_times(
    words: list[tuple[str, float, float]],
    *,
    max_dur: float = 1.8,
    glue: float = 0.16,
) -> list[tuple[str, float, float]]:
    """Cap tokens stretched across silence/moans. Long CJK phrases keep more time."""
    if not words:
        return []
    out: list[tuple[str, float, float]] = []
    n = len(words)
    for i, (text, start, end) in enumerate(words):
        prev_end = words[i - 1][2] if i else None
        next_start = words[i + 1][1] if i + 1 < n else None
        if next_start is not None:
            end = min(end, next_start)
        if prev_end is not None:
            start = max(start, prev_end)
        if end <= start:
            end = start + 0.08
        glyphs = glyph_count(text)
        if glyphs <= 3:
            cap = min(1.05, max(0.32, 0.14 + 0.08 * max(glyphs, 1)))
        else:
            cap = min(4.5, max(0.5, 0.12 * glyphs + 0.3), max_dur if glyphs < 8 else 4.5)
        # First mora of a Japanese word is often stretched across earlier silence.
        if (
            glyphs <= 2
            and next_start is not None
            and (next_start - start) > 2.0
            and (next_start - start) < 20.0
        ):
            start = max(start, next_start - cap)
            if prev_end is not None:
                start = max(start, prev_end)
            if end < start + 0.08:
                end = start + 0.08
        if end - start > cap:
            glued_prev = prev_end is not None and (start - prev_end) <= glue
            glued_next = next_start is not None and (next_start - end) <= glue
            if glued_next and not glued_prev:
                start = end - cap
            else:
                end = start + cap
            if next_start is not None:
                end = min(end, next_start)
            if prev_end is not None:
                start = max(start, prev_end)
            if end <= start:
                end = start + 0.08
        out.append((text, start, end))
    return out


def _multipart(
    fields: list[tuple[str, str]],
    filename: str,
    data: bytes,
    mime: str,
) -> tuple[bytes, str]:
    boundary = "----GrokSttFormBoundary7"
    chunks: list[bytes] = []
    for key, value in fields:
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                f"{value}\r\n"
            ).encode()
        )
    chunks.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode()
    )
    chunks.append(data)
    chunks.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def grok_stt_file(
    audio: Path,
    *,
    language: str = "ja",
    vad_threshold: str | None = "0",
    keyterms: list[str] | None = None,
    filler_words: bool = True,
) -> dict[str, Any]:
    audio = Path(audio)
    if not audio.is_file() or audio.stat().st_size < 100:
        raise RuntimeError(f"audio missing: {audio}")
    mime = _MIME.get(audio.suffix.lower(), "application/octet-stream")
    data = audio.read_bytes()
    # Whole-file listen (YouTube style). 2h m4a needs more than the old 600s cap.
    timeout = min(1800, max(180, int(audio.stat().st_size / 20_000) + 180))

    def post(fields: list[tuple[str, str]]) -> dict[str, Any]:
        body, content_type = _multipart(fields, audio.name, data, mime)
        last_err: Exception | None = None
        for attempt in range(5):
            req = urllib.request.Request(STT_URL, data=body, method="POST")
            req.add_header("Authorization", "Bearer " + grok_api_token())
            req.add_header("Content-Type", content_type)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = json.loads(resp.read())
                if not isinstance(payload, dict):
                    raise RuntimeError("grok STT returned non-object JSON")
                return payload
            except urllib.error.HTTPError as exc:
                err = exc.read().decode("utf-8", errors="replace")[:800]
                if exc.code in {429, 503} and attempt < 4:
                    wait = 2.0 * (2**attempt)
                    print(f"warning: STT HTTP {exc.code}, retry in {wait:.0f}s", flush=True)
                    time.sleep(wait)
                    last_err = RuntimeError(f"grok STT HTTP {exc.code}: {err}")
                    continue
                raise RuntimeError(f"grok STT HTTP {exc.code}: {err}") from exc
            except urllib.error.URLError as exc:
                last_err = RuntimeError(f"grok STT request failed: {exc}")
                if attempt < 4:
                    time.sleep(1.5 * (2**attempt))
                    continue
                raise last_err from exc
        if last_err:
            raise last_err
        raise RuntimeError("grok STT failed")

    def build_fields(vad: str | None) -> list[tuple[str, str]]:
        fields: list[tuple[str, str]] = [("language", language), ("format", "true")]
        if filler_words:
            fields.append(("filler_words", "true"))
        if vad is not None:
            fields.append(("vad_threshold", str(vad)))
        for term in keyterms or []:
            t = str(term).strip()
            if t and len(t) <= 50:
                fields.append(("keyterm", t))
        return fields

    try:
        return post(build_fields(vad_threshold))
    except RuntimeError as exc:
        msg = str(exc)
        if vad_threshold is not None and ("HTTP 400" in msg or "HTTP 422" in msg):
            print("warning: STT vad_threshold rejected; retry without it", flush=True)
            return post(build_fields(None))
        raise


def _ffprobe_duration(media: Path, ffmpeg: Path) -> float | None:
    probe = Path(ffmpeg).with_name("ffprobe.exe" if ffmpeg.name.lower().endswith(".exe") else "ffprobe")
    if not probe.is_file():
        return None
    result = subprocess.run(
        [
            str(probe),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    try:
        return float((result.stdout or "").strip())
    except ValueError:
        return None


def _slice_audio(audio: Path, dest: Path, ffmpeg: Path, start: float, duration: float) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"{audio.stem}.chunk-{int(start):04d}.m4a"
    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(audio),
        "-t",
        f"{duration:.3f}",
        "-vn",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode != 0 or not out.is_file() or out.stat().st_size < 500:
        err = (result.stderr or b"").decode("utf-8", errors="replace")[-400:]
        raise RuntimeError(f"ffmpeg audio chunk failed: {err}")
    return out


def _cache_stem(audio: Path) -> str:
    stem = audio.stem
    if stem.endswith(".audio"):
        return stem[: -len(".audio")]
    return stem


def _stt_workers() -> int:
    raw = os.environ.get("JABLE_STT_WORKERS") or "6"
    try:
        n = int(raw)
    except ValueError:
        n = 6
    return max(1, min(n, 8))


def payload_has_speech(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    if _is_keyterm_dump(payload):
        return False
    if len(payload.get("words") or []) >= 1:
        return True
    return bool(str(payload.get("text") or "").strip())


def _is_keyterm_dump(payload: dict[str, Any]) -> bool:
    """STT sometimes echoes keyterm= names as if spoken."""
    text = str(payload.get("text") or "").strip()
    if text.count(",") < 2:
        return False
    parts = [p.strip() for p in re.split(r"[,，、]", text) if p.strip()]
    named = [p for p in parts if 2 <= len(p) <= 12]
    return len(named) >= 3


def _already_retried(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    if _is_keyterm_dump(payload):
        return False
    vad = str(payload.get("vad_threshold") or "")
    if vad in {"0", "0.0"}:
        return True
    return payload.get("_slice_start") is not None and not payload_has_speech(payload)


def _load_payload(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def should_reuse_stt_cache(payload: dict[str, Any] | None, words: list) -> bool:
    """Only reuse a previous whole-file listen, not sliced chunks."""
    if not payload or payload.get("chunked"):
        return False
    return len(words) >= 8


def grok_stt_words(
    audio: Path,
    dest: Path,
    ffmpeg: Path | None = None,
    *,
    cache: bool = True,
    chunk_sec: float = 240.0,
    language: str = "ja",
    keyterms: list[str] | None = None,
    force: bool = False,
    retry_empty: bool = True,
    vad_threshold: str | None = "0",
    overlap_sec: float = 4.0,
) -> list[tuple[str, float, float]]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    audio = Path(audio)
    stem = _cache_stem(audio)
    cache_path = dest / f"{stem}.grok-stt.json"
    if cache and not force and cache_path.is_file() and cache_path.stat().st_size > 50:
        payload = _load_payload(cache_path)
        if payload:
            words = parse_stt_words(payload)
            if should_reuse_stt_cache(payload, words):
                print(f"grok-voice: reuse {cache_path.name} ({len(words)} words)", flush=True)
                return words
            if payload.get("chunked"):
                print("grok-voice: ignore sliced cache, listen whole audio", flush=True)

    duration = 0.0
    if ffmpeg is not None:
        duration = _ffprobe_duration(audio, Path(ffmpeg)) or 0.0
    print(
        f"grok-voice: listen {audio.name} ({audio.stat().st_size} bytes)"
        + (f", {duration:.0f}s" if duration else "")
        + "  [whole file]",
        flush=True,
    )

    payload: dict[str, Any] | None = None
    words: list[tuple[str, float, float]] = []
    try:
        payload = grok_stt_file(
            audio,
            language=language,
            keyterms=keyterms,
            vad_threshold=vad_threshold,
            filler_words=True,
        )
        words = parse_stt_words(payload)
    except Exception as exc:
        msg = str(exc)
        if "HTTP 401" in msg or "HTTP 403" in msg:
            raise
        print(f"warning: grok STT full-file failed ({exc}); try chunks", flush=True)
        words = []
        payload = None
        if ffmpeg is None:
            raise

    if len(words) < 8:
        if ffmpeg is None:
            raise RuntimeError("grok STT failed and ffmpeg missing for chunks")
        if duration < 8:
            duration = _ffprobe_duration(audio, Path(ffmpeg)) or 0.0
        if duration < 8:
            raise RuntimeError("audio too short for chunked STT")
        words, payload = _stt_chunks(
            audio,
            dest,
            Path(ffmpeg),
            duration,
            chunk_sec=chunk_sec,
            language=language,
            keyterms=keyterms,
            cache=cache,
            force=force,
            retry_empty=retry_empty,
            vad_threshold=vad_threshold,
            overlap_sec=overlap_sec,
        )

    if len(words) < 8:
        raise RuntimeError(f"grok STT returned too few words ({len(words)})")
    if cache and payload is not None:
        try:
            cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    print(f"grok-voice: {len(words)} spoken words", flush=True)
    return words


def _stt_chunks(
    audio: Path,
    dest: Path,
    ffmpeg: Path,
    duration: float,
    *,
    chunk_sec: float,
    language: str,
    keyterms: list[str] | None,
    cache: bool,
    force: bool,
    retry_empty: bool = True,
    vad_threshold: str | None = "0",
    overlap_sec: float = 4.0,
) -> tuple[list[tuple[str, float, float]], dict[str, Any]]:
    stem = _cache_stem(audio)
    chunks_dir = dest / f"{stem}.stt-chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    jobs: list[tuple[float, float, float, float]] = []
    start = 0.0
    overlap = max(0.0, overlap_sec)
    while start < duration - 0.2:
        take = min(chunk_sec, duration - start)
        slice_start = max(0.0, start - overlap) if start > 0 else 0.0
        slice_end = min(duration, start + take + overlap)
        jobs.append((start, take, slice_start, slice_end - slice_start))
        start += take
    workers = _stt_workers()
    print(
        f"grok-voice: {len(jobs)} chunks x {chunk_sec:.0f}s, overlap {overlap:.0f}s, {workers} workers",
        flush=True,
    )

    def one(off: float, take: float, slice_start: float, slice_dur: float) -> tuple[float, dict[str, Any]]:
        part_path = chunks_dir / f"{int(round(off)):04d}.json"
        if cache and not force and part_path.is_file() and part_path.stat().st_size > 20:
            cached = _load_payload(part_path)
            if cached is not None:
                if payload_has_speech(cached) or not retry_empty or _already_retried(cached):
                    return off, cached
        chunk = _slice_audio(audio, chunks_dir, ffmpeg, slice_start, slice_dur)
        try:
            part = grok_stt_file(
                chunk,
                language=language,
                keyterms=keyterms,
                vad_threshold=vad_threshold,
                filler_words=True,
            )
            if retry_empty and not payload_has_speech(part) and vad_threshold not in {None, "0"}:
                part = grok_stt_file(
                    chunk,
                    language=language,
                    keyterms=keyterms,
                    vad_threshold="0",
                    filler_words=True,
                )
        finally:
            try:
                chunk.unlink(missing_ok=True)
            except OSError:
                pass
        part["_slice_start"] = slice_start
        part["_nominal_start"] = off
        part["_nominal_take"] = take
        part["vad_threshold"] = vad_threshold
        part["filler_words"] = True
        try:
            part_path.write_text(json.dumps(part, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return off, part

    results: dict[float, dict[str, Any]] = {}
    done = 0

    def record(off: float, take: float, part: dict[str, Any]) -> None:
        nonlocal done
        results[off] = part
        done += 1
        nwords = len(part.get("words") or [])
        print(
            f"grok-voice: chunk {done}/{len(jobs)}  {_fmt_hms(off)}-{_fmt_hms(off + take)}"
            f"  {nwords} words",
            flush=True,
        )

    if workers <= 1:
        for off, take, slice_start, slice_dur in jobs:
            o, part = one(off, take, slice_start, slice_dur)
            record(o, take, part)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {
                pool.submit(one, off, take, ss, sd): (off, take)
                for off, take, ss, sd in jobs
            }
            for fut in as_completed(futs):
                off, take = futs[fut]
                try:
                    o, part = fut.result()
                except Exception as exc:
                    raise RuntimeError(f"STT chunk {_fmt_hms(off)} failed: {exc}") from exc
                record(o, take, part)

    merged: list[tuple[str, float, float]] = []
    texts: list[str] = []
    for i, (off, take, slice_start, _slice_dur) in enumerate(jobs):
        part = results[off]
        raw = parse_stt_words(part, offset=float(part.get("_slice_start", slice_start)))
        last = i == len(jobs) - 1
        lo, hi = off, off + take
        if last:
            hi = duration + 1.0
        kept = []
        for text, t0, t1 in raw:
            mid = (t0 + t1) / 2.0
            if lo - 0.05 <= mid < hi:
                kept.append((text, t0, t1))
        merged.extend(kept)
        texts.append(str(part.get("text") or ""))
    payload = {
        "text": "".join(t for t in texts if t).strip(),
        "language": language,
        "duration": round(duration, 3),
        "words": [{"text": w, "start": round(t0, 3), "end": round(t1, 3)} for w, t0, t1 in merged],
        "chunked": True,
        "chunk_sec": chunk_sec,
        "overlap_sec": overlap,
        "vad_threshold": vad_threshold,
    }
    if jobs and merged:
        sample = join_ja([w[0] for w in merged[:12]])
        print(f"grok-voice: first words: {sample[:80]}", flush=True)
    return merged, payload


def _fmt_hms(t: float) -> str:
    total = max(0, int(t))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


_CJK_EDGE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\u3005ー]")
_PUNCT_RIGHT = set("。、！？!?,.…)）」』】〜~")
_PUNCT_LEFT = set("（「『【")


def join_ja(parts: list[str]) -> str:
    tokens = [p.strip() for p in parts if p and str(p).strip()]
    if not tokens:
        return ""
    out = tokens[0]
    for piece in tokens[1:]:
        a, b = out[-1], piece[0]
        if b in _PUNCT_RIGHT or a in _PUNCT_LEFT or a in _PUNCT_RIGHT:
            out += piece
        elif _CJK_EDGE.match(a) and _CJK_EDGE.match(b):
            out += piece
        elif a.isspace() or b.isspace():
            out += piece
        else:
            out += " " + piece
    return out


def _percentile(vals: list[float], p: float) -> float:
    if not vals:
        return -60.0
    ordered = sorted(vals)
    idx = int(round((len(ordered) - 1) * (p / 100.0)))
    return ordered[max(0, min(idx, len(ordered) - 1))]


def audio_rms_envelope(
    audio: Path,
    ffmpeg: Path,
    *,
    hop: float = 0.25,
    sr: int = 8000,
    cache: Path | None = None,
) -> list[tuple[float, float]]:
    """Mono RMS envelope in dBFS. Cached as JSON when cache path is set."""
    audio = Path(audio)
    if cache and Path(cache).is_file() and Path(cache).stat().st_mtime >= audio.stat().st_mtime:
        try:
            raw = json.loads(Path(cache).read_text(encoding="utf-8"))
            frames = raw.get("frames") if isinstance(raw, dict) else raw
            out = [(float(a), float(b)) for a, b in frames]
            if len(out) >= 8:
                return out
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    hop_n = max(160, int(sr * hop))
    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-nostdin",
        "-i",
        str(audio),
        "-ac",
        "1",
        "-ar",
        str(sr),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    env: list[tuple[float, float]] = []
    t = 0.0
    stdout = proc.stdout
    if stdout is None:
        raise RuntimeError("ffmpeg envelope: no stdout")
    while True:
        buf = stdout.read(hop_n * 2)
        if not buf or len(buf) < 8:
            break
        n = len(buf) // 2
        samples = array.array("h")
        samples.frombytes(buf[: n * 2])
        acc = 0.0
        for s in samples:
            acc += s * s
        rms = math.sqrt(acc / max(n, 1))
        db = 20.0 * math.log10(max(rms, 1e-9) / 32768.0)
        env.append((t, db))
        t += hop
    proc.wait()
    if cache and env:
        try:
            Path(cache).write_text(
                json.dumps({"hop": hop, "sr": sr, "frames": env}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
    return env


def vocal_threshold(env: list[tuple[float, float]]) -> float:
    dbs = [db for _, db in env]
    floor = _percentile(dbs, 20)
    return max(-46.0, min(-28.0, floor + 11.0))


def vocal_runs(
    env: list[tuple[float, float]],
    *,
    thresh: float | None = None,
    hop: float = 0.25,
    min_dur: float = 0.45,
    max_gap: float = 0.5,
) -> list[tuple[float, float, float]]:
    """Return (start, end, peak_db) for voiced runs."""
    if not env:
        return []
    if thresh is None:
        thresh = vocal_threshold(env)
    hop = env[1][0] - env[0][0] if len(env) > 1 else hop
    runs: list[tuple[float, float, float]] = []
    start: float | None = None
    last_on = 0.0
    peak = -120.0
    for t, db in env:
        if db >= thresh:
            if start is None:
                start = t
                peak = db
            else:
                peak = max(peak, db)
            last_on = t + hop
        elif start is not None and (t - last_on) > max_gap:
            if last_on - start >= min_dur:
                runs.append((start, last_on, peak))
            start = None
            peak = -120.0
    if start is not None and last_on - start >= min_dur:
        runs.append((start, last_on, peak))
    return runs


def subtract_intervals(
    runs: list[tuple[float, float, float]],
    covered: list[tuple[float, float]],
    *,
    pad: float = 0.35,
) -> list[tuple[float, float, float]]:
    blocks = [(a - pad, b + pad) for a, b in covered if b > a]
    blocks.sort()
    out: list[tuple[float, float, float]] = []
    for start, end, peak in runs:
        pieces = [(start, end)]
        for lo, hi in blocks:
            nxt: list[tuple[float, float]] = []
            for a, b in pieces:
                if hi <= a or lo >= b:
                    nxt.append((a, b))
                    continue
                if a < lo:
                    nxt.append((a, min(lo, b)))
                if b > hi:
                    nxt.append((max(hi, a), b))
            pieces = [(a, b) for a, b in nxt if b - a >= 0.4]
        for a, b in pieces:
            out.append((a, b, peak))
    return out


def moan_label(peak_db: float, run_len: float) -> tuple[str, str]:
    if peak_db >= -22.0:
        return "啊", "あっ"
    if run_len >= 3.8 and peak_db >= -33.0:
        return "哈", "はぁ"
    if peak_db >= -30.0:
        return "啊", "あっ"
    return "嗯", "んっ"


def moan_cues_from_runs(
    runs: list[tuple[float, float, float]],
    env: list[tuple[float, float]],
    *,
    spacing: float = 2.7,
    cue_dur: float = 0.95,
) -> list[dict[str, Any]]:
    """Sparse 嗯/啊 cues on uncovered vocal energy (not a ん wall)."""
    hop = env[1][0] - env[0][0] if len(env) > 1 else 0.25
    by_t = env
    cues: list[dict[str, Any]] = []

    def env_peak(lo: float, hi: float) -> tuple[float, float]:
        best_t, best_db = lo, -120.0
        for t, db in by_t:
            if t < lo:
                continue
            if t >= hi:
                break
            if db > best_db:
                best_t, best_db = t, db
        return best_t, best_db

    for start, end, run_peak in runs:
        span = end - start
        if span < 0.45:
            continue
        if span <= 2.4:
            zh, ja = moan_label(run_peak, span)
            cues.append(
                {
                    "start": round(start, 3),
                    "end": round(min(end, start + 2.2), 3),
                    "zh": zh,
                    "ja": ja,
                    "kind": "vocal",
                }
            )
            continue
        picked: list[float] = []
        # greedy loudest-first, then time-sort
        windows: list[tuple[float, float]] = []
        t = start
        while t < end:
            w1 = min(end, t + max(hop * 4, 0.8))
            pt, pdb = env_peak(t, w1)
            windows.append((pt, pdb))
            t += 0.4
        windows.sort(key=lambda item: -item[1])
        chosen: list[tuple[float, float]] = []
        for pt, pdb in windows:
            if pdb < run_peak - 8 and pdb < -34:
                continue
            if any(abs(pt - q) < spacing for q, _ in chosen):
                continue
            chosen.append((pt, pdb))
        chosen.sort()
        if not chosen:
            pt, pdb = env_peak(start, end)
            chosen = [(pt, pdb)]
        for pt, pdb in chosen:
            a = max(start, pt - cue_dur * 0.25)
            b = min(end, a + cue_dur)
            if b - a < 0.45:
                continue
            zh, ja = moan_label(pdb, span)
            cues.append(
                {
                    "start": round(a, 3),
                    "end": round(b, 3),
                    "zh": zh,
                    "ja": ja,
                    "kind": "vocal",
                }
            )
            picked.append(pt)
        _ = picked
    cues.sort(key=lambda c: (c["start"], c["end"]))
    return cues


def vocal_cues_for_audio(
    audio: Path,
    ffmpeg: Path,
    covered: list[tuple[float, float]],
    *,
    dest: Path | None = None,
) -> list[dict[str, Any]]:
    audio = Path(audio)
    cache = None
    if dest is not None:
        stem = audio.stem[:-6] if audio.stem.endswith(".audio") else audio.stem
        cache = Path(dest) / f"{stem}.vocal-env.json"
    print("vocals: RMS envelope (non-lexical 嗯/啊)", flush=True)
    env = audio_rms_envelope(audio, ffmpeg, cache=cache)
    if len(env) < 8:
        print("warning: vocal envelope too short", flush=True)
        return []
    thresh = vocal_threshold(env)
    runs = vocal_runs(env, thresh=thresh)
    holes = subtract_intervals(runs, covered)
    cues = moan_cues_from_runs(holes, env)
    print(
        f"vocals: thresh={thresh:.1f} dB  runs={len(runs)}  uncovered={len(holes)}  cues={len(cues)}",
        flush=True,
    )
    return cues

