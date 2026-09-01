# -*- coding: utf-8 -*-
"""Demux the mp4 audio track and let Grok listen (word times).

WAV/M4A is audio, not the video. Grok CLI (grok.exe) is a text agent and
cannot hear a file attached as a prompt; TUI /voice is microphone dictation.
File listening is xAI Speech-to-Text: POST https://api.x.ai/v1/stt with the
separated audio, using grok login (api:access) or XAI_API_KEY.

Word timestamps are the subtitle clock. Source-language wording comes from the transcript.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from youtube_parse import BilingualCue, Cue

_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_CHAR_SCRIPTS = re.compile(
    r"[\u0E00-\u0E7F\u3040-\u30FF\u3400-\u9FFF\uAC00-\uD7AF]"
)
_TOKEN_RE = re.compile(
    r"[A-Za-z0-9']+"
    r"|[\u0400-\u04FF]+"
    r"|[\u0600-\u06FF]+"
    r"|[\u0900-\u097F]+"
    r"|[\u0E00-\u0E7F\u3040-\u30FF\u3400-\u9FFF\uAC00-\uD7AF]+"
)
STT_LANGS = {
    "ar",
    "cs",
    "da",
    "nl",
    "en",
    "fil",
    "fr",
    "de",
    "hi",
    "id",
    "it",
    "ja",
    "ko",
    "mk",
    "ms",
    "fa",
    "pl",
    "pt",
    "ro",
    "ru",
    "es",
    "sv",
    "th",
    "tr",
    "vi",
}
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


def _lang_code(text: str | None) -> str:
    raw = str(text or "").strip().lower().replace("_", "-")
    if raw.endswith("-orig"):
        raw = raw[:-5]
    if not raw or raw in {"auto", "und", "unknown"}:
        return ""
    base = raw.split("-", 1)[0]
    return {
        "jp": "ja",
        "jpn": "ja",
        "kr": "ko",
        "kor": "ko",
        "spa": "es",
        "ger": "de",
        "deu": "de",
        "fre": "fr",
        "fra": "fr",
        "chi": "zh",
        "zho": "zh",
        "cmn": "zh",
        "cn": "zh",
        "tl": "fil",
        "tgl": "fil",
        "in": "id",
        "iw": "he",
        "nb": "no",
    }.get(base, base)


def stt_language(language: str | None) -> str | None:
    code = _lang_code(language)
    if code in STT_LANGS:
        return code
    return None


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for match in _TOKEN_RE.finditer(text or ""):
        piece = match.group(0)
        if _CHAR_SCRIPTS.search(piece):
            out.extend(list(piece))
        else:
            out.append(piece.lower() if piece.isascii() else piece)
    return out


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
    env = (os.environ.get("GROK_ZH_MODEL") or os.environ.get("YT_GROK_ZH_MODEL") or "").strip()
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
    """One-shot JSON-schema chat. Avoids grok.exe agent/xhigh overhead."""
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
                    "model" in err.lower() or "not found" in err.lower() or "does not exist" in err.lower()
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
    """Strip the video; keep only the audio stream as .audio.m4a."""
    dest.mkdir(parents=True, exist_ok=True)
    media = Path(media)
    if media.suffix.lower() in _AUDIO_ONLY and media.is_file() and media.stat().st_size > 1000:
        return media
    out = dest / f"{media.stem}.audio.m4a"
    if out.is_file() and out.stat().st_size > 1000:
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


def extract_align_wav(media: Path, dest: Path, ffmpeg: Path) -> Path:
    wav = dest / f"{media.stem}.align.wav"
    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-y",
        "-i",
        str(media),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(wav),
    ]
    result = subprocess.run(cmd, capture_output=True, check=False)
    if result.returncode != 0 or not wav.is_file() or wav.stat().st_size < 1000:
        err = (result.stderr or b"").decode("utf-8", errors="replace")[-500:]
        raise RuntimeError(f"ffmpeg extract wav failed: {err}")
    return wav


def _whisper_device() -> tuple[str, str]:
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def whisper_words(
    wav: Path,
    model_size: str | None = None,
    language: str = "en",
) -> list[tuple[str, float, float]]:
    from faster_whisper import WhisperModel

    lang = stt_language(language) or _lang_code(language) or "en"
    if model_size is None:
        model_size = "small.en" if lang == "en" else "small"
    device, compute = _whisper_device()
    print(f"audio-align: whisper {model_size} lang={lang} on {device}/{compute}", flush=True)
    model = WhisperModel(model_size, device=device, compute_type=compute)
    segments, _info = model.transcribe(
        str(wav),
        language=lang,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )
    words: list[tuple[str, float, float]] = []
    for seg in segments:
        for word in seg.words or []:
            raw = str(word.word or "").strip()
            if not raw or not _tokens(raw):
                continue
            start = float(word.start)
            end = float(word.end)
            if end <= start:
                end = start + 0.08
            words.append((raw, start, end))
    print(f"audio-align: {len(words)} words from audio", flush=True)
    return words


def parse_stt_words(payload: dict[str, Any], *, offset: float = 0.0) -> list[tuple[str, float, float]]:
    words: list[tuple[str, float, float]] = []
    for item in payload.get("words") or []:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("text") or "").strip()
        if not raw or not _tokens(raw):
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
    max_dur: float = 1.05,
    glue: float = 0.16,
) -> list[tuple[str, float, float]]:
    """STT often holds a token across music/silence. Cap duration; if the
    word is glued to the next token and far from the previous, snap start
    forward so 'Thank' sits on the real thank-you, not the plane 24s earlier.
    """
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
        letters = sum(ch.isalnum() for ch in text)
        cap = min(max_dur, max(0.32, 0.14 + 0.07 * letters))
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
    language: str | None = "en",
    vad_threshold: str | None = "0.2",
) -> dict[str, Any]:
    audio = Path(audio)
    if not audio.is_file() or audio.stat().st_size < 100:
        raise RuntimeError(f"audio missing: {audio}")
    mime = _MIME.get(audio.suffix.lower(), "application/octet-stream")
    data = audio.read_bytes()
    timeout = min(600, max(180, int(audio.stat().st_size / 20_000) + 120))

    def post(fields: list[tuple[str, str]]) -> dict[str, Any]:
        body, content_type = _multipart(fields, audio.name, data, mime)
        req = urllib.request.Request(STT_URL, data=body, method="POST")
        req.add_header("Authorization", "Bearer " + grok_api_token())
        req.add_header("Content-Type", content_type)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read())
        if not isinstance(payload, dict):
            raise RuntimeError("grok STT returned non-object JSON")
        return payload

    fields: list[tuple[str, str]] = []
    stt_lang = stt_language(language)
    if stt_lang:
        fields.append(("language", stt_lang))
        fields.append(("format", "true"))
    if vad_threshold is not None:
        fields.append(("vad_threshold", str(vad_threshold)))
    try:
        return post(fields)
    except urllib.error.HTTPError as exc:
        err = exc.read().decode("utf-8", errors="replace")[:800]
        if vad_threshold is not None and exc.code in {400, 422}:
            print(
                f"warning: STT vad_threshold rejected ({exc.code}); retry without it",
                flush=True,
            )
            retry_fields: list[tuple[str, str]] = []
            if stt_lang:
                retry_fields.extend([("language", stt_lang), ("format", "true")])
            try:
                return post(retry_fields)
            except urllib.error.HTTPError as exc2:
                err2 = exc2.read().decode("utf-8", errors="replace")[:800]
                raise RuntimeError(f"grok STT HTTP {exc2.code}: {err2}") from exc2
        raise RuntimeError(f"grok STT HTTP {exc.code}: {err}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"grok STT request failed: {exc}") from exc


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
    out = dest / f"{audio.stem}.chunk-{int(start):04d}.m4a"
    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(audio),
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


def grok_stt_words(
    audio: Path,
    dest: Path,
    ffmpeg: Path | None = None,
    *,
    cache: bool = True,
    chunk_sec: float = 240.0,
    language: str = "en",
) -> list[tuple[str, float, float]]:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    audio = Path(audio)
    want_lang = stt_language(language) or _lang_code(language)
    cache_path = dest / f"{audio.stem.replace('.audio', '')}.grok-stt.json"
    if cache and cache_path.is_file() and cache_path.stat().st_size > 50:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            got_lang = _lang_code(payload.get("language") if isinstance(payload, dict) else "")
            words = parse_stt_words(payload)
            lang_ok = not want_lang or not got_lang or want_lang == got_lang
            if lang_ok and len(words) >= 8:
                print(f"grok-voice: reuse {cache_path.name} ({len(words)} words)", flush=True)
                return words
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    print(
        f"grok-voice: listen {audio.name} ({audio.stat().st_size} bytes) lang={want_lang or 'auto'}",
        flush=True,
    )
    try:
        payload = grok_stt_file(audio, language=want_lang)
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
        duration = _ffprobe_duration(audio, Path(ffmpeg)) or 0.0
        if duration < 8:
            raise
        merged: list[tuple[str, float, float]] = []
        texts: list[str] = []
        start = 0.0
        while start < duration - 0.2:
            take = min(chunk_sec, duration - start)
            chunk = _slice_audio(audio, dest, Path(ffmpeg), start, take)
            try:
                part = grok_stt_file(chunk, language=want_lang)
            finally:
                try:
                    chunk.unlink(missing_ok=True)
                except OSError:
                    pass
            merged.extend(parse_stt_words(part, offset=start))
            texts.append(str(part.get("text") or ""))
            start += take
        words = merged
        payload = {
            "text": " ".join(t for t in texts if t).strip(),
            "language": want_lang or "en",
            "duration": round(duration, 3),
            "words": [
                {"text": w, "start": round(t0, 3), "end": round(t1, 3)}
                for w, t0, t1 in words
            ],
            "chunked": True,
        }
    if len(words) < 8:
        raise RuntimeError("grok STT returned too few words")
    if cache and payload is not None:
        try:
            cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    print(f"grok-voice: {len(words)} spoken words", flush=True)
    return words


def sync_rows_to_grok_voice(
    rows: list,
    media: Path,
    dest: Path,
    ffmpeg: Path,
    *,
    language: str = "en",
) -> list:
    audio = extract_audio_track(media, dest, ffmpeg)
    print(f"grok-voice: demux {audio.name} (audio only, not the video)", flush=True)
    words = grok_stt_words(audio, dest, ffmpeg, language=language)
    return apply_word_times(rows, words)


def _ratio(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, " ".join(a), " ".join(b)).ratio()


def match_sentence_window(
    tokens: list[str],
    words: list[tuple[str, float, float]],
    cursor: int,
) -> tuple[int, int, float] | None:
    if not tokens or cursor >= len(words):
        return None
    n = len(words)
    best: tuple[float, int, int] | None = None
    search_limit = min(n, cursor + 24)
    max_len = min(n, max(len(tokens) * 4, len(tokens) + 8) + cursor)
    for start in range(cursor, search_limit):
        buf: list[str] = []
        end_limit = min(n, start + max(len(tokens) * 4, 18))
        if end_limit > max_len:
            end_limit = max_len
        for end in range(start + 1, end_limit + 1):
            tok = _tokens(words[end - 1][0])
            if tok:
                buf.extend(tok)
            else:
                buf.append(words[end - 1][0].lower())
            if len(buf) < max(1, int(len(tokens) * 0.45)):
                continue
            score = _ratio(tokens, buf)
            pen = abs(len(buf) - len(tokens)) * 0.015
            val = score - pen
            if best is None or val > best[0]:
                best = (val, start, end)
            if score >= 0.9 and len(buf) >= len(tokens):
                break
    if best is None or best[0] < 0.48:
        return None
    return best[1], best[2], best[0]


def apply_word_times(
    rows: list,
    words: list[tuple[str, float, float]],
) -> list:
    from youtube_parse import BilingualCue

    cursor = 0
    out = []
    hits = 0
    for row in rows:
        tokens = _tokens(row.en)
        if not tokens:
            out.append(row)
            continue
        matched = match_sentence_window(tokens, words, cursor)
        if matched is None and cursor > 0:
            matched = match_sentence_window(tokens, words, max(0, cursor - 8))
        if matched is None:
            out.append(row)
            continue
        start_i, end_i, score = matched
        start = words[start_i][1]
        end = words[end_i - 1][2]
        if end - start < 0.35:
            end = start + 0.35
        out.append(BilingualCue(start, end, row.zh, row.en))
        cursor = end_i
        hits += 1
        _ = score
    # keep monotonic
    for i in range(1, len(out)):
        prev, cur = out[i - 1], out[i]
        if cur.start < prev.end:
            mid = (prev.end + cur.start) / 2
            if mid > prev.start + 0.2:
                out[i - 1] = BilingualCue(prev.start, mid, prev.zh, prev.en)
            if cur.end > mid + 0.2:
                out[i] = BilingualCue(mid, cur.end, cur.zh, cur.en)
    print(f"audio-align: retimed {hits}/{len(rows)} cues from speech", flush=True)
    return out


def sync_rows_to_media(
    rows: list,
    media: Path,
    dest: Path,
    ffmpeg: Path,
    *,
    keep_wav: bool = False,
    language: str = "en",
) -> list:
    wav = extract_align_wav(media, dest, ffmpeg)
    try:
        words = whisper_words(wav, language=language)
        if len(words) < 8:
            print("warning: audio-align got too few words, keep YouTube times", flush=True)
            return rows
        return apply_word_times(rows, words)
    finally:
        if not keep_wav:
            try:
                wav.unlink(missing_ok=True)
            except OSError:
                pass
