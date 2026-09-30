#!/usr/bin/env python3
"""
Sonora — Notebook to Podcast.

Text -> HD voice generator with:
- Solo narration (documentary / audiobook / trailer styles)
- Two-host podcast (auto dialogue, smart LLM, or your own script)
- Dramatic pauses, narration speed, procedural studio beds (warm / drone / crackle / pad)
- Save as MP3 / WAV (plus M4A / OGG via /api/convert)
- Voices: the same HD neural voices used by Microsoft Edge "Read Aloud".
"""
import asyncio
import json
import os
import re
import struct
import subprocess
import shutil
import sys
import tempfile
import queue as _queue
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import imageio_ffmpeg

import enhance as E  # Clean & Clear mastering engine (shared with AI_Agent)
import hdclean as HDC  # HD Cleanup — Adaptive Khmer Voice Enhancement (RVC clone only)
import narration as NAR  # Narration Style & Voice Performance engine
import numpy as np

# TTS engines load SOFTLY — the studio must boot even if a package is missing.
# Production chains whichever engines are available:
#   1) edge-tts  2) our own Microsoft client (tts_fallback)  3) Google gTTS.
try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except Exception:
    edge_tts = None
    EDGE_TTS_AVAILABLE = False

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except Exception:
    gTTS = None
    GTTS_AVAILABLE = False

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    from sonora_paths import resolve_model_field, resolve_index_field
except Exception:                      # never break the studio over a helper
    resolve_model_field = resolve_index_field = None
# When Sonora ships inside the combined package, both apps share ONE copy of
# the neural weights (~420 MB) instead of downloading them twice. The combined
# START.bat sets CLEAN_CHECKPOINTS_DIR; on a standalone install it stays local.
CLEAN_CKPT = os.environ.get("CLEAN_CHECKPOINTS_DIR") or ROOT
PUBLIC = os.path.join(ROOT, "public")
CACHE_DIR = os.path.join(ROOT, ".cache_audio")
BEDI_DIR = os.path.join(ROOT, ".beds")          # user-uploaded music beds (persist)
BEDI_INDEX = os.path.join(BEDI_DIR, "index.json")
BEDI_MAX_BYTES = 3 * 1024 * 1024 * 1024        # up to ~2h of lossless
BEDI_EXTS = {"mp3", "m4a", "wav", "ogg", "flac", "aac", "opus", "webm", "mp4"}
VOICES_CACHE = os.path.join(ROOT, ".voices_cache.json")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()

# ---------------------------------------------------------------- media layer
# Every ffmpeg call goes through here. Two hard lessons:
#   * a double PIPE (stdin AND stdout) can hang forever on Windows — a console
#     in "select" mode blocks stderr, and ffmpeg then never finishes. A test
#     conversion died on exactly that ("timed out after 300 seconds").
#     So: bytes are written to a temp FILE, output is a temp FILE, no pipes.
#   * a broken/odd ffmpeg build must not be fatal: RVC ships its own
#     ffmpeg.exe, the PATH may have another one. Self-test once, fall back.
_FF_CACHE = {"bin": "", "tested": False}


def _ff_candidates():
    out = []
    env = os.environ.get("FFMPEG")
    if env and os.path.exists(env):
        out.append(env)
    try:
        out.append(FFMPEG)
    except Exception:
        pass
    try:
        rvc = (RVC_STATE.get("cfg") or {}).get("rvcDir") or ""
        if rvc:
            for rel in ("ffmpeg.exe", "ffmpeg", "runtime/ffmpeg.exe",
                        "runtime/ffmpeg", "bin/ffmpeg.exe"):
                cand = os.path.join(rvc, *rel.split("/"))
                if os.path.exists(cand):
                    out.append(cand)
    except Exception:
        pass
    try:
        w = shutil.which("ffmpeg")
        if w:
            out.append(w)
    except Exception:
        pass
    seen, uniq = set(), []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)
    return uniq


def _ff_selftest(binary, timeout=8):
    """Can this binary decode 50 ms of silence without hanging?"""
    try:
        r = subprocess.run(
            [binary, "-nostdin", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "0.05",
             "-f", "f32le", "-"],
            capture_output=True, timeout=timeout)
        return r.returncode == 0 and len(r.stdout) > 100
    except Exception:
        return False


def ffmpeg_bin():
    """The first working ffmpeg (tested once, then cached)."""
    if _FF_CACHE["bin"]:
        return _FF_CACHE["bin"]
    if not _FF_CACHE["tested"]:
        _FF_CACHE["tested"] = True
        for c in _ff_candidates():
            if _ff_selftest(c):
                _FF_CACHE["bin"] = c
                print("[media] ffmpeg: " + c, flush=True)
                return c
        print("[media] WARNING: no ffmpeg passed the self-test — using the "
              "first candidate anyway", flush=True)
    cands = _ff_candidates()
    _FF_CACHE["bin"] = cands[0] if cands else FFMPEG
    return _FF_CACHE["bin"]


def ffmpeg_run(in_bytes=None, in_path=None, in_name="in.bin", in_raw=None,
               args=(), out_name="out.bin", timeout=600, step=""):
    """Run ffmpeg with FILE input and FILE output. Returns the output bytes.

    in_raw = (sample_rate, channels) when the input is headerless PCM.
    Raises RuntimeError naming the step and every binary that was tried, so a
    hang never hides behind "timed out".
    """
    tries = _ff_candidates() or [FFMPEG]
    first = ffmpeg_bin()
    if first in tries:
        tries = [first] + [t for t in tries if t != first]
    last = ""
    for binary in tries:
        with tempfile.TemporaryDirectory() as td:
            src = None
            if in_path:
                src = in_path
            elif in_bytes is not None:
                src = os.path.join(td, in_name)
                with open(src, "wb") as f:
                    f.write(in_bytes)
            dst = os.path.join(td, out_name)
            cmd = [binary, "-nostdin", "-y", "-hide_banner",
                   "-loglevel", "error"]
            if in_raw:
                cmd += ["-f", "f32le", "-ar", str(in_raw[0]),
                        "-ac", str(in_raw[1])]
            if src:
                cmd += ["-i", src]
            cmd += list(args) + [dst]
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=timeout)
            except subprocess.TimeoutExpired:
                last = "%s did not finish within %ds" % (binary, timeout)
                print("[media] TIMEOUT: %s on %s — trying the next ffmpeg"
                      % (binary, step or "decode"), flush=True)
                continue
            except Exception as e:
                last = "%s: %s" % (binary, e)
                continue
            if r.returncode != 0:
                last = "%s: %s" % (binary,
                                   r.stderr.decode("utf-8", "replace")[:300])
                continue
            try:
                with open(dst, "rb") as f:
                    return f.read()
            except Exception as e:
                last = "output missing: %s" % e
                continue
    raise RuntimeError("the audio step (%s) failed — %s" % (step or "media",
                       last or "no ffmpeg available")
                       + "  |  ffmpeg tried: "
                       + ", ".join(os.path.basename(t) for t in tries))


RQ_LOG = []                       # last requests, newest last
RQ_LOG_PATH = os.path.join(ROOT, ".studio.log")


def _rq_log(line):
    """Append one line to the request log (memory + .studio.log on disk).

    WHY: when a click fails we need to know whether the request ever reached
    the studio. "HTTP 501" from somewhere in between looks exactly like a
    studio problem until you can see that no request arrived at all.
    """
    txt = "%s %s" % (time.strftime("%H:%M:%S"), line)
    RQ_LOG.append(txt)
    if len(RQ_LOG) > 400:
        del RQ_LOG[:len(RQ_LOG) - 400]
    try:
        with open(RQ_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(txt + "\n")
        if os.path.getsize(RQ_LOG_PATH) > 400_000:
            with open(RQ_LOG_PATH, "w", encoding="utf-8") as f:
                f.write("\n".join(RQ_LOG[-200:]) + "\n")
    except Exception:
        pass


def ffmpeg_quiet(args, timeout=3600, step=""):
    """Run ffmpeg with file arguments only (no pipes at all).
    Tries every candidate binary, so one bad build cannot fail a job."""
    tries = _ff_candidates() or [FFMPEG]
    last = ""
    for binary in tries:
        cmd = [binary, "-nostdin"] + list(args)
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            last = "%s timed out after %ds" % (os.path.basename(binary), timeout)
            continue
        except Exception as e:
            last = str(e)
            continue
        if r.returncode == 0:
            return ""
        last = r.stderr.decode("utf-8", "replace")[:300]
    raise RuntimeError("ffmpeg %s failed: %s" % (step or "run", last))



PORT = int(os.environ.get("PORT", "8000"))
# Build tag: shown in the header AND appended to every job failure, so a
# screenshot/report always says which studio build produced it.
STUDIO_BUILD = "2026-09-30q"
STUDIO_FEATURES = ("go-straight queue (a long episode waits and continues by "
                   "itself, never ends FAILED on a bad minute; runner supervisor, "
                   "plan saved on disk and resumed after a studio restart, Stop and "
                   "Continue, no duplicate runs, honest 'queued (#n in line)' that "
                   "never vanishes), "
                   "speed pass (clone model loads while the first lines are spoken, "
                   "16-line/45 s clone passes, no per-unit crawl during a provider "
                   "outage), "
                   "PURE VOICE, OWN STYLE (every style performs its own pace, its "
                   "own softness and its own pauses — meditation 0.84x at -1.2 dB "
                   "with long gaps, news 1.07x and brisk, trailer 0.90x and +0.7 dB, "
                   "pitch stays 0.0 st in "
                   "all 14 styles and all 56 feelings, so it is always the same "
                   "speaker, and Narration Speed is the user's alone and applies on "
                   "top), "
                   "manuscript marks are never spoken (English AND Khmer: #, ##, **, "
                   "bullets, list numbers, quotes, links, dashes -> words and pauses; "
                   "a range still reads as a range), "
                   "khmer-language-engine (normalizer + pronunciation dictionary "
                   "+ numbers by meaning + pause levels + learning lexicon), "
                   "khmer-performance-engine (52 emotions, 14 style profiles, "
                   "intra-sentence emotion, arcs, restraint guards), "
                   "feeling layer (13 styles x four emotional deliveries = 52, "
                   "style protection: a feeling never turns one style into another; "
                   "delivery moves pauses, emphasis, breath and rhythm only), "
                   "13 Narration Style cards in three rows, above PERFORMANCE "
                   "behind one line (each card names its "
                   "own pace/softness/pauses and its ▶ plays that style PERFORMED by "
                   "the studio engine — same plan as a real episode, Jenny US · "
                   "female voice, 48 kHz/192 kbps master), "
                   "the two styles from build k stay as the user re-set them in l: "
                   "Emotional Cinematic Storytelling reads like a storyteller "
                   "(unhurried, phrase by phrase, gentle landings) with the ORIGINAL "
                   "voice — no tone shaping, pitch 0.0 st — and the whisper stage "
                   "is REMOVED (build 2026-09-30n): nothing is whispered. (Was: a "
                   "brief moment inside another "
                   "style, never a whole narration, "
                   "plain voice (DRAMATIC PAUSES + NARRATION SPEED are always the "
                   "user's; a style adds its own pace, softness and phrase rhythm "
                   "on top — nothing ever re-tunes the speaker), "
                   "manuscript marks never spoken")
SR = 24000
# Generous ceilings — long documents (1h, 2h, 4h+) are fine. The pipeline
# streams to disk in 1-minute chunks, so memory stays flat at any length.
# The caps below only guard against accidental multi-day pastes.
MAX_CHARS = 8_000_000
MAX_UNITS = 40_000     # a 4-hour book of short Khmer lines ≈ 4 000–7 000 units
BATCH = SR * 60  # 1 minute of audio per in-memory chunk
SYNTH_WORKERS = 6  # units synthesized simultaneously (parallel TTS sessions)

# --- long-job protection ------------------------------------------------------
# A 1–2 hour episode is tens of thousands of units. The failure mode that used
# to kill it: the provider starts throttling a burst, every unit in the group
# fails, the whole job is retried from the start, and the same thing happens
# again at the same place — an hour of work lost per attempt.
#
# What protects it now:
#   * a burst breaker: when N units in a row fail, stop launching new work and
#     WAIT for the provider instead of hammering it (a small pause usually
#     clears a rate limit; hammering makes it worse and kills the job).
#   * an adaptive width: a group that fails as a whole makes the next groups
#     narrower (6 → 4 → 2 → 1 sequential), so the burst that caused the throttle
#     is never repeated. A clean group widens it back.
#   * fewer, shorter provider retries per unit (the local/offline engine and the
#     whole-job retry still exist) — the job makes progress instead of waiting.
SYNTH_WORKERS_MIN = 1

# A polite pacer: when the provider shows pressure, requests are spaced out
# instead of being fired six at a time. It is the difference between a provider
# that throttles you (and a job that has to wait it out) and a job that simply
# keeps going. Interval 0 = full speed (the normal case).
_EDGE_PACE = {"interval": 0.0, "next": 0.0}
_EDGE_PACE_LOCK = threading.Lock()


def _edge_pace_set(interval: float):
    with _EDGE_PACE_LOCK:
        _EDGE_PACE["interval"] = max(0.0, min(1.5, float(interval)))


async def _edge_pace():
    with _EDGE_PACE_LOCK:
        if _EDGE_PACE["interval"] <= 0:
            return
        now = time.time()
        wait = _EDGE_PACE["next"] - now
        _EDGE_PACE["next"] = max(now, _EDGE_PACE["next"]) + _EDGE_PACE["interval"]
    if wait > 0:
        await asyncio.sleep(min(wait, 2.0))
BURST_FAIL_LIMIT = 8          # consecutive failed units before the pause
BURST_PAUSE_S = 25            # how long to let a throttled provider recover

# Clone work is done in BATCHES: one pass through the RVC model per group of
# lines instead of one pass per line. Per-pass overhead (temp files, f0
# model, index, resampling) was being paid for every sentence — a chapter now
# pays it a handful of times.
RVC_BATCH_UNITS = 16       # at most this many lines per pass
RVC_BATCH_SECS = 45.0      # and at most this much audio per pass
RVC_BATCH_GAP = 0.15       # silence welded between lines (splits back off)
CACHE_TTL = 6 * 3600
CACHE_MAX = 30

os.makedirs(CACHE_DIR, exist_ok=True)

# ---------------------------------------------------------------- voices ----
_voice_cache = None


async def _load_voices():
    global _voice_cache
    if os.path.exists(VOICES_CACHE):
        try:
            with open(VOICES_CACHE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data:
                _voice_cache = data
                return data
        except Exception:
            pass
    vs = await edge_tts.list_voices() if EDGE_TTS_AVAILABLE else []
    if not vs:
        _voice_cache = _voice_cache or []
        return _voice_cache
    data = [
        {
            "id": v["ShortName"],
            "locale": v["Locale"],
            "gender": v.get("Gender", ""),
            "name": v.get("FriendlyName", v["ShortName"]),
        }
        for v in vs
    ]
    try:
        with open(VOICES_CACHE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass
    _voice_cache = data
    return data


def get_voices(refresh=False):
    global _voice_cache
    if _voice_cache is not None and not refresh:
        return _voice_cache
    try:
        return asyncio.run(_load_voices())
    except Exception:
        if _voice_cache is not None:
            return _voice_cache
        raise

# ------------------------------------------------------------- text utils ---

def clean_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, limit: int = 2200):
    text = (text or "").strip()
    if not text:
        return []
    chunks, cur = [], ""
    for para in [p.strip() for p in text.split("\n") if p.strip()]:
        pieces = [p.strip() for p in re.findall(r"[^.!?…\u0E40]*[.!?…\u0E40]*", para) if p.strip()]
        if not pieces:
            pieces = [para]
        for piece in pieces:
            while len(piece) > limit:
                if cur:
                    chunks.append(cur.strip())
                    cur = ""
                chunks.append(piece[:limit].strip())
                piece = piece[limit:].strip()
            if len(cur) + len(piece) + 1 > limit and cur:
                chunks.append(cur.strip())
                cur = ""
            cur = (cur + " " + piece).strip()
    if cur.strip():
        chunks.append(cur.strip())
    return [c for c in chunks if c]


def sentence_units(text: str, max_len: int = 450):
    """Split one narration line into sentence-sized TTS units.
    Returns [(unit_text, boundary)] where boundary is '.', '!', '?', '…',
    ។ (Khmer full stop) or 'para' (line end without punctuation) — used for
    natural, punctuation-aware dramatic pauses."""
    text = (text or "").strip()
    if not text:
        return []
    units = []
    for para in [p.strip() for p in text.split("\n") if p.strip()]:
        if is_khmer(para):
            para = _khmer_segment(para)  # word spaces before splitting
        # \u17D4 = Khmer full stop (KHMER SIGN KHAN, ។)
        pieces = [p.strip() for p in re.findall(r"[^.!?…\u0E40\u17D4]*[.!?…\u0E40\u17D4]*", para) if p.strip()]
        for piece in (pieces or [para]):
            m = re.search(r"([.!?…\u0E40\u17D4])\s*$", piece)
            boundary = m.group(1) if m else "para"
            while len(piece) > max_len:
                cut = piece.rfind(" ", 60, max_len)
                if cut < 60:
                    cut = max_len
                units.append((piece[:cut].strip(), "."))  # mid-sentence split
                piece = piece[cut:].strip()
            if piece.strip():
                units.append((piece.strip(), boundary))
    # A unit that has no letters or digits is punctuation only ("...", "…", "។").
    # Sending that to a TTS engine fails on every provider and used to kill the
    # whole episode ("No audio was received"). Glue it onto the sentence it
    # belongs to instead.
    clean = []
    for u, b in units:
        if not re.search(r"[^\W_]", u, re.UNICODE):
            if clean:
                prev, prevb = clean[-1]
                clean[-1] = ((prev.rstrip() + " " + u.strip()).strip(),
                             b if b != "para" else prevb)
            continue
        clean.append((u, b))
    return [u for u in clean if u[0]]


def is_thai(text: str) -> bool:
    compact = re.sub(r"\s", "", text or "")
    if not compact:
        return False
    thai = sum(1 for c in compact if "\u0e00" <= c <= "\u0e7f")
    return thai / len(compact) > 0.3

def is_khmer(text: str) -> bool:
    compact = re.sub(r"\s", "", text or "")
    if not compact:
        return False
    kh = sum(1 for c in compact if "\u1780" <= c <= "\u17ff")
    return kh / len(compact) > 0.3

# -------------------------------------------------- Khmer preparation -------
# Khmer script is written WITHOUT word spaces, and digits/percent/currency are
# the most common mispronunciation sources. Before any TTS engine sees Khmer
# text we: 1) segment it into word-space tokens (khmercut), 2) expand numbers,
# percentages and currency into natural spoken Khmer words, 3) NFC-normalize
# (already done in _tts_safe_text).
try:
    import khmercut as _khmercut
except Exception:  # pragma: no cover — segmentation is a quality boost, not a requirement
    _khmercut = None

_KHMER_DIGITS = {"០": "0", "១": "1", "២": "2", "៣": "3", "៤": "4",
                 "៥": "5", "៦": "6", "៧": "7", "៨": "8", "៩": "9"}
_KHMER_DIGIT_WORDS = {"0": "សូន្យ", "1": "មួយ", "2": "ពីរ", "3": "បី", "4": "បួន",
                      "5": "ប្រាំ", "6": "ប្រាំមួយ", "7": "ប្រាំពីរ", "8": "ប្រាំបី", "9": "ប្រាំបួន"}
_KHMER_TENS = {"1": "ដប់", "2": "ម្ភៃ", "3": "សាមសិប", "4": "សែសិប", "5": "ហាសិប",
               "6": "ហុកសិប", "7": "ចិត្តសិប", "8": "ប៉ែតសិប", "9": "កៅសិប"}
# up to 10^5 — 10^6 and above are built with លាន (see _khmer_number_words)
_KHMER_UNITS = ["", "ដប់", "រយ", "ពាន់", "ម៉ឺន", "សែន"]

# a number, comma groups included:  1,200 | 2,500,000 | 3.5 | 85
_KH_NUM = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
# 9+ ungrouped digits (and any leading-zero number) are identifiers/phonenumbers,
# spoken digit by digit
_KH_SPELL_LIMIT = 8


def _khmer_six(num_str: str) -> str:
    """0–999999 as spoken Khmer (no លាន)."""
    num_str = num_str.lstrip("0")
    if not num_str:
        return _KHMER_DIGIT_WORDS["0"]
    words = []
    length = len(num_str)
    for i, digit in enumerate(num_str):
        if digit == "0":
            continue
        pos = length - i - 1
        if pos == 1:
            words.append(_KHMER_TENS[digit])
        else:
            words.append(_KHMER_DIGIT_WORDS[digit])
            if pos > 0:
                words.append(_KHMER_UNITS[pos])
    return "".join(words) or _KHMER_DIGIT_WORDS["0"]


def _khmer_number_words(num_str: str) -> str:
    """Spell a number out in natural spoken Khmer.

    85 -> ប៉ែតសិបប្រាំ   1,200 -> មួយពាន់ពីររយ
    2,500,000 -> ពីរលានប្រាំសែន   12,345,678 -> ដប់ពីរលាន សាមសិបបួនម៉ឺន...
    Long ungrouped digits (phone numbers / IDs) are read digit by digit.
    """
    grouped = "," in num_str
    num_str = num_str.replace(",", "")
    if not num_str.isdigit():
        return num_str
    if num_str == "0":
        return _KHMER_DIGIT_WORDS["0"]
    if not grouped and len(num_str) > _KH_SPELL_LIMIT:
        return " ".join(_KHMER_DIGIT_WORDS[d] for d in num_str)
    if not grouped and num_str.startswith("0") and len(num_str) >= 8:
        return " ".join(_KHMER_DIGIT_WORDS[d] for d in num_str)
    if len(num_str) > 15:
        return " ".join(_KHMER_DIGIT_WORDS[d] for d in num_str)
    if len(num_str) > 6:
        head, rest = num_str[:-6], num_str[-6:]
        out = _khmer_number_words(head) + "លាន"
        rest = rest.lstrip("0")
        if rest:
            out += _khmer_number_words(rest)
        return out
    return _khmer_six(num_str)


def _khmer_decimal(s: str) -> str:
    """3.5 -> បីចំណុចប្រាំ   1,200.50 -> មួយពាន់ពីររយចំណុចប្រាំសូន្យ"""
    s = s.replace(",", "")
    if "." in s:
        head, tail = s.split(".", 1)
        tail_words = "".join(_KHMER_DIGIT_WORDS[d] for d in tail
                             if d in _KHMER_DIGIT_WORDS)
        return _khmer_number_words(head) + "ចំណុច" + tail_words
    return _khmer_number_words(s)


def _khmer_phonetics(text: str) -> str:
    """Expand digits, times, ranges, ordinals, percentages and currency into
    the words a Khmer narrator would actually say."""
    for k, a in _KHMER_DIGITS.items():
        text = text.replace(k, a)

    # times: 3:30 -> ម៉ោងបី សាមសិបនាទី  (only valid clock values)
    # if the writer already wrote ម៉ោង before it, or នាទី after it, we do not
    # repeat the word — "ម៉ោង 3:30 នាទី" must read "ម៉ោងបី សាមសិប នាទី"
    def _time(m):
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 24 or mi > 59:
            return m.group(0)
        before = m.string[max(0, m.start() - 14):m.start()]
        after = m.string[m.end():m.end() + 14]
        head = "" if before.rstrip().endswith("ម៉ោង") else "ម៉ោង"
        out = head + _khmer_number_words(str(h))
        if mi:
            tail = "" if after.lstrip().startswith("នាទី") else "នាទី"
            out += " " + _khmer_number_words(str(mi)) + tail
        return out
    text = re.sub(r"\b(\d{1,2})[:៖](\d{2})\b", _time, text)

    # ranges: 1990-1995 -> ពី... ដល់ ...
    text = re.sub(r"(%s)\s*[-–—~]\s*(%s)" % (_KH_NUM, _KH_NUM),
                  lambda m: "ពី" + _khmer_decimal(m.group(1)) + " ដល់ " +
                            _khmer_decimal(m.group(2)), text)

    # ordinals: ទី 5 / ទី5 -> ទីប្រាំ
    text = re.sub(r"ទី\s*(%s)" % _KH_NUM,
                  lambda m: "ទី" + _khmer_decimal(m.group(1)), text)

    # percentages and currency (comma groups included) — the unit word is not
    # repeated if the writer already wrote it next to the number
    def _add_word(m, word):
        after = m.string[m.end():m.end() + len(word) + 2]
        return " " + _khmer_decimal(m.group(1)) + ("" if after.lstrip().startswith(word) else " " + word)

    text = re.sub(r"(%s)\s*%%" % _KH_NUM, lambda m: _add_word(m, "ភាគរយ"), text)
    text = re.sub(r"\$\s*(%s)" % _KH_NUM, lambda m: _add_word(m, "ដុល្លារ"), text)
    text = re.sub(r"\u17DB\s*(%s)" % _KH_NUM, lambda m: _add_word(m, "រៀល"), text)
    text = re.sub(r"(?<![A-Za-z])(?:riel|រៀល)\s*(%s)" % _KH_NUM,
                  lambda m: " " + _khmer_decimal(m.group(1)) + " រៀល", text,
                  flags=re.IGNORECASE)

    # spaced phone groups: 012 345 678 -> every digit spoken
    def _spaced_phone(m):
        return " ".join(_KHMER_DIGIT_WORDS[d] for d in m.group(0) if d.isdigit())
    text = re.sub(r"\b0\d{1,3}(?:[ ]\d{2,4}){2,}\b", _spaced_phone, text)

    # everything else that is still a number
    text = re.sub(_KH_NUM, lambda m: _khmer_decimal(m.group(0)), text)
    return re.sub(r"  +", " ", text).strip()


def _khmer_segment(text: str) -> str:
    """Insert word spaces — Khmer is written without them, and engines need the
    boundaries to get rhythm right (fixes run-on / chopped-syllable readings).

    When the language frontend is installed it has ALREADY segmented (and
    protected names and numbers from being re-split), so this only tidies the
    punctuation: a full stop never floats away from the word it closes.
    """
    if _khmer_module() is not None:
        return re.sub(r"[ \t]+([.,!?;:\u17d4\u17d5\u17d6])", r"\1", text)
    if _khmercut is None:
        return text
    try:
        toks = _khmercut.tokenize(text)
        out = " ".join(t for t in toks if t and t.strip())
        return out or text
    except Exception:
        return text

# ------------------------------------------------------------------ TTS -----

def _tempo_f32(arr: "np.ndarray", rate: float) -> "np.ndarray":
    """Time-stretch without changing pitch (ffmpeg atempo) — how a local engine
    that has no rate control still gets the style's pace."""
    rate = float(rate)
    if abs(rate - 1.0) < 0.02:
        return arr
    rate = max(0.5, min(1.6, rate))
    chain = []
    r = rate
    while r > 2.0:
        chain.append("atempo=2.0"); r /= 2.0
    while r < 0.5:
        chain.append("atempo=0.5"); r /= 0.5
    chain.append(f"atempo={r:.4f}")
    try:
        out = ffmpeg_run(in_bytes=arr.astype("<f4").tobytes(),
                         in_name="in.f32", in_raw=(SR, 1),
                         args=["-filter:a", ",".join(chain), "-f", "f32le",
                               "-ar", str(SR), "-ac", "1"],
                         out_name="out.f32", timeout=180, step="changing the pace")
    except Exception as e:
        print("[tempo] %s" % e, flush=True)
        return arr
    if not out:
        return arr
    return np.frombuffer(out, dtype=np.float32)


def _pitch_f32(arr: "np.ndarray", factor: float) -> "np.ndarray":
    """Register shift for engines with no pitch control (asetrate + atempo).

    Only used for a real change (>= 1 semitone) that a style genuinely asks
    for, e.g. a movie trailer sitting low."""
    if abs(factor - 1.0) < 0.06:
        return arr
    try:
        out = ffmpeg_run(in_bytes=arr.astype("<f4").tobytes(),
                         in_name="in.f32", in_raw=(SR, 1),
                         args=["-filter:a",
                               f"asetrate={int(SR * factor)},aresample={SR},"
                               f"atempo={1.0 / factor:.4f}",
                               "-f", "f32le", "-ar", str(SR), "-ac", "1"],
                         out_name="out.f32", timeout=180, step="shifting the pitch")
    except Exception as e:
        print("[pitch] %s" % e, flush=True)
        return arr
    if not out:
        return arr
    return np.frombuffer(out, dtype=np.float32)


def _breath_samples(n: int, level_db: float, seed: int = 0) -> "np.ndarray":
    """SILENCE — the pause breath was removed in build 2026-09-30o.

    It used to return a soft filtered-noise inhale ("shaped noise, low-passed")
    which the render loop wrote into the gaps between sentences. That sound is
    the "whisper" the user kept hearing mid-read, so it is gone: the function
    now returns exactly zero samples, which makes it impossible for any stale
    caller to put the noise back.
    """
    return np.zeros(max(0, int(n)), dtype=np.float32)
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    rng = np.random.default_rng(1000 + seed)
    noise = rng.standard_normal(n).astype(np.float32)
    # one-pole low pass -> breathy, not hissy (2 passes)
    for _ in range(2):
        a = 0.12
        out = np.empty_like(noise)
        acc = 0.0
        for i in range(n):
            acc += a * (noise[i] - acc)
            out[i] = acc
        noise = out
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    env = np.clip(np.sin(np.pi * t), 0.0, None) ** 1.3  # in and out (never NaN)
    amp = 10.0 ** (level_db / 20.0)
    peak = float(np.max(np.abs(noise))) or 1.0
    return (noise / peak * env * amp * 0.6).astype(np.float32)


def _rate_from_speed(speed: float) -> str:
    pct = (float(speed) - 1.0) * 100.0
    return f"{pct:+.0f}%"


def _evict_cache():
    try:
        now = time.time()
        files = []
        for f in os.listdir(CACHE_DIR):
            p = os.path.join(CACHE_DIR, f)
            if os.path.isfile(p):
                files.append((os.path.getmtime(p), p))
        files.sort()
        for mt, p in files:
            if now - mt > CACHE_TTL:
                os.remove(p)
        files = [p for mt, p in files if os.path.exists(p)]
        for p in files[: max(0, len(files) - CACHE_MAX)]:
            os.remove(p)
    except Exception:
        pass


class VoiceServiceDown(Exception):
    """The voice service rejected the request repeatedly (transient)."""

# Global service state — prevents a rate-limit on one provider from cascading
# into a total outage (the "failed at 20%" failure mode):
#   * edge_blocked_until: circuit breaker. After Microsoft definitively refuses
#     us (403/410) we stop sending it requests for 2 minutes instead of
#     hammering it and deepening the block.
#   * gTTS is serialized (one request at a time, ~1s apart) so a whole episode
#     falling back to Google stays at a polite pace and doesn't trip Google's
#     own rate limit.
SERVICE_STATE = {"edge_blocked_until": 0.0,
                 "burst_fail_streak": 0,     # consecutive failed units
                 "throttle_until": 0.0}      # burst-breaker quiet window
_GTTS_LOCK = threading.Lock()
_GTTS_LAST_CALL = [0.0]

# ------------------------------------------------- unit cache (resume) ------
# Every synthesized sentence is cached by content hash. If a job fails on a
# transient outage (or the user re-presses Generate), already-made sentences
# are reused instantly — long jobs RESUME instead of restarting from zero.
import hashlib

UNIT_CACHE = os.path.join(ROOT, ".unit_cache")
UNIT_CACHE_TTL = 24 * 3600
UNIT_CACHE_MAX = 200 * 1024 * 1024  # 200 MB
os.makedirs(UNIT_CACHE, exist_ok=True)


def _unit_path(voice, rate, text):
    h = hashlib.sha1(f"{voice}|{rate}|{text}".encode("utf-8")).hexdigest()[:24]
    return os.path.join(UNIT_CACHE, h + ".mp3")


def _cached_unit(voice, rate, text):
    """(mp3_bytes, engine) for a cached sentence, or None.

    WHY the engine is stored: edge-tts applies the speaking rate ITSELF, the
    local engines cannot. The cache holds the engine's own output, so whoever
    reuses it must know whether the pace is still missing — otherwise the rate
    is applied twice (edge: too fast/slow) or not at all (local). The engine
    name lives in a tiny sidecar file next to the audio.
    """
    try:
        p = _unit_path(voice, rate, text)
        if os.path.exists(p) and os.path.getsize(p) > 600:
            with open(p, "rb") as f:
                mp3 = f.read()
            engine = "edge"
            try:
                with open(p + ".engine", "r", encoding="utf-8") as fh:
                    engine = (fh.read().strip() or "edge")
            except OSError:
                pass                      # an older entry: edge was the norm
            return mp3, engine
    except Exception:
        pass
    return None


def _save_unit(voice, rate, text, mp3, engine="edge"):
    try:
        p = _unit_path(voice, rate, text)
        with open(p, "wb") as f:
            f.write(mp3)
        try:
            with open(p + ".engine", "w", encoding="utf-8") as fh:
                fh.write(engine or "edge")
        except OSError:
            pass
        _evict_unit_cache()
    except Exception:
        pass


def _evict_unit_cache():
    try:
        now = time.time()
        files = []
        for f in os.listdir(UNIT_CACHE):
            p = os.path.join(UNIT_CACHE, f)
            try:
                mt = os.path.getmtime(p)
                if now - mt > UNIT_CACHE_TTL:
                    os.remove(p)
                else:
                    files.append((mt, os.path.getsize(p), p))
            except OSError:
                pass
        total = sum(s for _, s, _ in files)
        for mt, s, p in sorted(files):
            if total <= UNIT_CACHE_MAX:
                break
            try:
                os.remove(p)
                total -= s
            except OSError:
                pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# KHMER LANGUAGE FRONTEND (pipeline/khmer_text.py)
# SOURCE -> SPEECH: normalization, abbreviations, numbers by meaning, the ស sign,
# punctuation as pause instructions, word/phrase spacing, the user's own rules.
# The TTS model must never have to guess an abbreviation or a number.
# ---------------------------------------------------------------------------
_KH_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", "pipeline"))
_KH_LEXICON_PATH = os.path.join(_KH_DIR, "khmer_lexicon.json")
_KH_MOD = {"mod": None, "tried": False}
_KH_CACHE = {}
_KH_NOTES = []


def _khmer_module():
    """pipeline/khmer_text.py, loaded once. None when it is missing."""
    if _KH_MOD["tried"]:
        return _KH_MOD["mod"]
    _KH_MOD["tried"] = True
    try:
        if _KH_DIR not in sys.path:
            sys.path.insert(0, _KH_DIR)
        import khmer_text as _kt
        _KH_MOD["mod"] = _kt
        _rq_log("khmer frontend: pipeline/khmer_text.py loaded")
    except Exception as e:
        _rq_log("khmer frontend unavailable (%s) - built-in rules stay active" % e)
    return _KH_MOD["mod"]


def khmer_lexicon_path():
    return _KH_LEXICON_PATH


def khmer_prepare(text, lexicon=None):
    """SOURCE text -> the SPEECH text a Khmer narrator would read.

    Returns the same shape whether or not the frontend module exists, so the
    API and the UI never break. Never raises.
    """
    src = text or ""
    kt = _khmer_module()
    if kt is None:
        return {"source": src, "speech": _khmer_phonetics(src), "phrased": "",
                "stats": {}, "notes": ["frontend module missing - simple rules used"],
                "pause_plan": [], "unknown_abbreviations": [],
                "repetitions": [], "low_confidence": []}
    hit = _KH_CACHE.get(src)
    if hit is None:
        try:
            lex = lexicon if lexicon is not None else kt.load_lexicon(_KH_LEXICON_PATH)
            r = kt.prepare(src, lex)
            hit = {"source": r["source"], "speech": r["speech"], "phrased": r["phrased"],
                   "stats": r["stats"], "notes": r["notes"], "pause_plan": r["pause_plan"],
                   "unknown_abbreviations": r["unknown_abbreviations"],
                   "repetitions": r["repetitions"], "low_confidence": r["low_confidence"]}
        except Exception as e:
            hit = {"source": src, "speech": _khmer_phonetics(src), "phrased": "",
                   "stats": {}, "notes": ["frontend error: %s" % e], "pause_plan": [],
                   "unknown_abbreviations": [], "repetitions": [], "low_confidence": []}
        if len(_KH_CACHE) > 4000:
            _KH_CACHE.clear()
        _KH_CACHE[src] = hit
        for n in hit["notes"]:
            _KH_NOTES.append(n)
        del _KH_NOTES[:-40]
    return hit


def _khmer_expressive():
    """pipeline/khmer_expressive.py — the prosody/emotion layer, loaded once."""
    kt = _khmer_module()
    if kt is None:
        return None
    try:
        import khmer_expressive as _xp
        return _xp
    except Exception as e:
        _rq_log("performance layer unavailable (%s)" % e)
        return None


def _khmer_frontend(text):
    """The text the engines actually receive (used by _tts_safe_text)."""
    try:
        return khmer_prepare(text)["speech"]
    except Exception:
        return _khmer_phonetics(text)


# ---- manuscript marks are NEVER spoken --------------------------------------
# Whatever the writer typed — "#", "##", "###", "**bold**", "- bullet", "1.",
# "១.", ">", backticks, "~~", a link, a dash — must reach the engine as WORDS
# and pauses only. English lines used to skip every cleaning step (only Khmer
# text was normalized), which is why a heading like "## Part 7 — Four Hours
# Away" was read out loud with its marks.
_DASHES = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212"   # - ‐ ‑ ‒ – — ― −


def _manuscript_clean(text: str, keep_dashes: bool = False) -> str:
    """Turn typed markup into what a narrator would actually say."""
    t = text or ""
    # block markers at the start of the line
    t = re.sub(r"^[ \t]*#{1,6}[ \t]*", "", t)                      # # ## ###
    t = re.sub(r"^[ \t]*>+[ \t]*", "", t)                          # > quote
    t = re.sub(r"^[ \t]*[-*+\u2022\u2023\u25aa\u25cf][ \t]+", "", t)   # bullets
    t = re.sub(r"^[ \t]*\(?\d{1,3}[.)\u17d4][ \t]+", "", t)      # 1.  1)  1។
    t = re.sub(r"^[ \t]*[០-៩]{1,3}[.)\u17d4][ \t]+", "", t)  # ១.  ១)
    t = re.sub(r"^[ \t]*[\u17e0-៩]{1,3}[ \t]+(?=[\u1780-\u17a2])", "", t)
    # inline marks, anywhere in the line
    t = t.replace("**", "").replace("__", "").replace("`", "").replace("*", "")
    t = t.replace("#", " ").replace("|", " ")          # stray marks mid-sentence
    t = t.replace("\\", "")                            # markdown escapes
    t = re.sub(r"~~(.+?)~~", r"\1", t)
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)              # [text](url)
    t = re.sub(r"<[^>]{1,60}>", " ", t)                              # stray tags
    t = re.sub(r"^\s*[\-=_~]{3,}\s*$", " ", t)                     # ---- ===== ~~~
    # dashes: a range is read as a range, anything else is a short pause
    if not keep_dashes:
        t = re.sub(r"(?<=\d)\s*[" + _DASHES + r"]\s*(?=\d)", " to ", t)
        t = re.sub(r"[" + _DASHES + r"]", ",", t)
    t = re.sub(r"[ \t]+([,.;:!?\u17d4-\u17d9])", r"\1", t)   # no space before a pause mark
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()


def _tts_safe_text(text: str) -> str:
    """Normalize TTS input: strip control characters and odd symbols that can
    make a specific sentence fail ALL engines (which used to kill whole jobs).
    Khmer text also gets phonetic normalization: digits/percent/currency are
    spelled out in Khmer words (the #1 mispronunciation source)."""
    import unicodedata
    t = unicodedata.normalize("NFC", text or "")
    if is_khmer(t):
        t = _khmer_frontend(t)      # Khmer language layer, not a digit patch
    t = "".join(c for c in t if c.isprintable() or c in "\n\t")
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\ufeff]", "", t)
    return t.strip()


_KHmerKT = {"mod": None, "tried": False}


def _local_khmer_tts():
    """The package's khmer_tts.py — ships next to this file (../pipeline) in the
    bundle, or at ../AI_Agent in a source checkout. Returns None if absent."""
    if _KHmerKT["tried"]:
        return _KHmerKT["mod"]
    _KHmerKT["tried"] = True
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", "pipeline"),
                 os.path.join(here, "..", "AI_Agent"),
                 here):
        path = os.path.join(cand, "khmer_tts.py")
        if os.path.exists(path):
            try:
                spec = importlib.util.spec_from_file_location("khmer_tts", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _KHmerKT["mod"] = mod
                return mod
            except Exception as e:
                print(f"[tts] local engine import failed: {type(e).__name__}: {e}",
                      flush=True)
    return None


def _local_tts_bytes(text: str) -> bytes:
    """OFFLINE engine: a local Khmer VITS model (MMS fine-tuned by default, or
    the voice you trained with the Colab kit — set KHMER_MMSFT_MODEL).

    Used only when every network provider has failed, so a Microsoft/Google
    outage (or no internet at all) does not stop the book. Khmer only: the
    model cannot speak other languages.
    """
    kt = _local_khmer_tts()
    if kt is None:
        raise RuntimeError("local engine unavailable (khmer_tts.py not found)")
    tmp = os.path.join(tempfile.gettempdir(), "sonora_local_%d.wav" % time.time_ns())
    try:
        r = kt.synth(text, tmp, engine="mmsft", ffmpeg=FFMPEG)
        if not r.get("ok"):
            raise RuntimeError(r.get("error") or "local engine produced no audio")
        mp3 = ffmpeg_run(in_path=tmp, args=["-f", "mp3", "-b:a", "96k"],
                         out_name="out.mp3", timeout=180,
                         step="encoding the offline engine audio")
        if len(mp3) < 1000:
            raise RuntimeError("local engine: mp3 encode failed")
        return mp3
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _definitive_block(e) -> bool:
    """HTTP 403/410 = provider is refusing us outright — retrying is pointless."""
    s = str(e)
    return ("403" in s or "410" in s or "Forbidden" in s or "Gone" in s)


async def _try_edge_tts(text: str, voice: str, rate: str, pitch: int = 0) -> bytes:
    if not EDGE_TTS_AVAILABLE:
        raise RuntimeError("edge-tts engine unavailable in this sandbox")
    kwargs = {"rate": rate}
    if pitch:
        kwargs["pitch"] = f"{int(pitch):+d}Hz"
    comm = edge_tts.Communicate(text, voice, **kwargs)
    buf = b""
    async for msg in comm.stream():
        if msg.get("type") == "audio":
            buf += msg["data"]
    if not buf:
        raise RuntimeError("empty audio")
    return buf


async def _try_fallback_tts(text: str, voice: str, rate: str) -> bytes:
    from tts_fallback import _tts_once
    return await _tts_once(text, voice, rate)


def _gtts_bytes(text: str, voice: str) -> bytes:
    """Third engine: Google gTTS — a fully independent provider (last resort).
    Retried 3x with backoff so a single network blip cannot kill an episode.
    Serialized: at most ONE Google request in flight, ~1s apart — so a long
    episode falling back to Google stays at a polite pace and does NOT trip
    Google's own rate limit (which would turn one outage into a total failure)."""
    if not GTTS_AVAILABLE:
        raise RuntimeError("gTTS engine unavailable in this sandbox")
    lang = (voice.split("-")[0] or "en").lower()
    # Use the platform temp dir (C:\Users\...\Temp on Windows, /tmp on Linux) —
    # a hardcoded "/tmp" path crashes on Windows (the "failed at 20%" bug).
    out = os.path.join(tempfile.gettempdir(), "sonora_gtts_%d.mp3" % time.time_ns())
    last = None
    for attempt in range(3):
        try:
            try:
                g = gTTS(text, lang=lang)
            except Exception:
                g = gTTS(text, lang="en")
            wav = out + ".wav"
            with _GTTS_LOCK:
                gap = 1.0 - (time.time() - _GTTS_LAST_CALL[0])
                if gap > 0:
                    time.sleep(gap)
                _GTTS_LAST_CALL[0] = time.time()
                g.save(wav)
            ffmpeg_quiet(["-y", "-loglevel", "error", "-i", wav,
                          "-c:a", "libmp3lame", "-b:a", "96k", "-ar", str(SR),
                          out], timeout=120, step="gTTS conversion")
            if not os.path.exists(out) or os.path.getsize(out) < 600:
                raise RuntimeError("gTTS conversion failed")
            with open(out, "rb") as f:
                return f.read()
        except Exception as e:
            last = e
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
        finally:
            for p in (out, out + ".wav"):
                try:
                    if os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass
    raise last


def _mp3_duration(mp3: bytes) -> float:
    """Decoded length of an mp3 clip (seconds). Returns a large number on
    probe failure — a probe hiccup must never fail a job."""
    try:
        raw = ffmpeg_run(in_bytes=mp3, in_name="in.mp3",
                         args=["-f", "f32le", "-ac", "1", "-ar", "16000"],
                         out_name="out.f32", timeout=60, step="measuring the clip")
        return len(raw) / 4.0 / 16000.0
    except Exception:
        return 1e9


_READABLE_RE = re.compile(r"[^\W_]", re.UNICODE)      # a letter or a digit
_PROBE_TEXT = "សូមស្វាគមន៍"          # a line every Khmer voice can say


def _speakable(text: str) -> bool:
    """True if a voice engine could really say something here.

    A line of punctuation, symbols or emoji is NOT a service problem: every
    provider answers "no audio was received", the job retries, and the user is
    told the voice service is down. It is not — there is simply nothing to
    read. Those lines are skipped on purpose and said so in the report.
    """
    t = _tts_safe_text(text or "")
    return bool(_READABLE_RE.search(t))


def _edge_probe(voice: str, tries: int = 1) -> bool:
    """Is the provider answering RIGHT NOW?

    Used to tell two very different failures apart when a whole batch fails:
      * provider down / rate-limited  -> it cannot even say "សូមស្វាគមន៍"
      * the text is the problem       -> the probe works, those lines do not
    One trivial request, short timeout, never raises.
    """
    if not EDGE_TTS_AVAILABLE:
        return False
    for attempt in range(max(1, tries)):
        try:
            mp3 = asyncio.run(asyncio.wait_for(
                _try_edge_tts(_PROBE_TEXT, voice, "+0%", 0), 15))
            if mp3 and _mp3_duration(mp3) > 0.3:
                return True
        except Exception:
            pass
        if attempt + 1 < max(1, tries):
            time.sleep(1.5)
    return False


# MPEG-1/2 Layer III frame header: bitrate and sample-rate tables
_MP3_BITRATES = {
    1: (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0),   # V1L3
    2: (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0),       # V2L3
}
_MP3_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000),
              1: (11025, 12000, 8000), 0: (0, 0, 0)}


def _mp3_frames_seconds(mp3: bytes):
    """Exact length by walking the MPEG frames — no ffmpeg, no guessing.

    Provider mp3s are CBR, so the old byte-count estimate (48 kbps) was only
    ever right for edge:  Google returns 32 kbps at 24 kHz mono, where it
    over-reported the length ~1.4x — enough to make the truncation guard
    accept a truncated read or reject a good one. The frame walk answers the
    question exactly, at any sample rate and bitrate.
    """
    n, i, frames, spf, sr = len(mp3), 0, 0, 0, 0
    while i + 4 <= n:
        if mp3[i] != 0xFF or (mp3[i + 1] & 0xE0) != 0xE0:
            i += 1
            continue
        b1, b2 = mp3[i + 1], mp3[i + 2]
        ver = (b1 >> 3) & 3                 # 3 = MPEG1, 2 = MPEG2, 0 = MPEG2.5
        layer = (b1 >> 1) & 3               # 1 = Layer III
        br_idx = (b2 >> 4) & 0xF
        sr_idx = (b2 >> 2) & 3
        if ver == 1 or layer != 1 or br_idx in (0, 15) or sr_idx == 3:
            i += 1
            continue
        kbps = _MP3_BITRATES[1 if ver == 3 else 2][br_idx]
        rate = _MP3_RATES[ver][sr_idx]
        if not kbps or not rate:
            i += 1
            continue
        pad = (b2 >> 1) & 1
        this_spf = 1152 if ver == 3 else 576
        length = int(this_spf / 8 * kbps * 1000 / rate) + pad
        if length <= 4:
            i += 1
            continue
        frames += 1
        spf, sr = this_spf, rate          # the stream is one format in practice
        i += length
        if frames >= 400000:
            break
    if frames < 2 or not sr:
        return None
    # the first frame of a LAME/ffmpeg file is the Xing/Info header: no audio
    return max(0.0, (frames - 1) * spf / float(sr))


def _estimate_mp3_seconds(mp3: bytes):
    """Length in seconds of a provider mp3 — frame-walk first (exact), byte
    count only as a last resort (CBR ~48 kbps). Returns None when unsure."""
    try:
        if not mp3 or len(mp3) < 2000:
            return 0.0
        d = _mp3_frames_seconds(mp3)
        if d is not None:
            return d
        return (len(mp3) * 8.0 / 48000.0)
    except Exception:
        return None


def _expected_min_seconds(text: str) -> float:
    """Conservative lower bound on how long `text` must take to speak.
    Providers under rate pressure sometimes return TRUNCATED audio instead of
    an error — a 15-word unit coming back as half a second. Anything shorter
    than this is treated as a failure so it gets retried / falls to the next
    engine instead of being spoken (and cached) as a blip."""
    words = len((text or "").split())
    return max(0.4, 0.22 * words, 0.03 * len(text or ""))



# ------------------------------------------------------------------- RVC ----
# Optional voice-clone layer: the user's trained RVC model (e.g. Sonaro-kh)
# re-voices lines through a persistent worker (rvc_worker.py) that runs in
# their RVC-WebUI Python environment. The worker loads the model ONCE and
# serves WAV-in/WAV-out on 127.0.0.1 only. Lines spoken by the special
# "rvc-clone" voice are synthesized with a base ("carrier") voice first,
# then converted through the model.
import base64 as _b64

RVC_VOICE_ID = "rvc-clone"
RVC_PORT = 18950
RVC_CFG_PATH = os.path.join(ROOT, ".rvc_config.json")
RVC_WORKER_LOG = os.path.join(ROOT, ".rvc_worker.log")

# "Clean & Clear" — denoise + 48 kHz + loudness master of the finished mix.
CLEAN_DEFAULTS = {"lufs": -16.0, "peak": -1.0, "sr": 48000, "deess": 2.5}
CLEAN_STATE = {"last": None, "install": None}

#: HD Cleanup (the “HD / CLEAN KHMER VOICE” tool). One entry per finished job, so
#: the browser can offer the Original ▶ / HD Clean ▶ pair (§17) and the one-line
#: note. The original clone audio is always kept on disk (§16).
HD_STATE = {}
HD_NOTE_FAIL = "Enhancement unavailable; original TTS preserved."
RVC_STATE = {"proc": None, "cfg": {}}
_RVC_LOCK = threading.Lock()


def _rvc_default_cfg():
    return {
        "rvcDir": "", "python": "",
        # a starting suggestion only — the fields are resolved against every
        # real layout (assets/weights, weights, bare names, folders) before use
        "model": "assets/weights/Sonaro-kh.pth",
        "index": "",            # blank = Sonora picks the best matching .index
        "pitch": 0, "indexRate": 0.75, "protect": 0.33,
        "f0Method": "rmvpe", "carrier": "km-KH-SreymomNeural", "scope": "khmer",
    }


def _rvc_load_cfg():
    cfg = _rvc_default_cfg()
    try:
        with open(RVC_CFG_PATH) as f:
            data = json.load(f)
        for k in cfg:
            if k in data:
                cfg[k] = data[k]
    except Exception:
        pass
    return cfg


def _rvc_save_cfg(cfg):
    try:
        with open(RVC_CFG_PATH, "w") as f:
            json.dump(cfg, f, indent=1)
    except Exception:
        pass


def _rvc_cfg_from_body(body):
    """Merge + clamp the rvc config from a request body.
    Accepts it nested under "rvc" (the normal shape) or flat at the top level."""
    cfg = _rvc_default_cfg()
    src = body.get("rvc")
    if not isinstance(src, dict):
        src = {k: v for k, v in (body or {}).items() if k in cfg}
    if isinstance(src, dict):
        for k in ("rvcDir", "python", "model", "index", "carrier"):
            if isinstance(src.get(k), str):
                cfg[k] = src[k].strip()[:400]
        for k, lo, hi in (("pitch", -12, 12), ("indexRate", 0.0, 1.0),
                          ("protect", 0.0, 0.7)):
            try:
                cfg[k] = round(min(hi, max(lo, float(src.get(k, cfg[k])))), 3)
            except Exception:
                pass
        if src.get("f0Method") in ("rmvpe", "harvest", "crepe", "pm"):
            cfg["f0Method"] = src["f0Method"]
        if src.get("scope") in ("khmer", "all"):
            cfg["scope"] = src["scope"]
    return cfg


def _rvc_scan():
    """Search the local drives for an RVC-WebUI installation.

    Returns (candidates, dirs_visited, roots). A candidate is any folder that
    contains an `infer/` package plus models — `assets/weights/` for the
    2.3+ layout, plain `weights/` for 2.0–2.2 — with its .pth models and
    .index files listed (relative paths). Depth and visit caps keep a big
    drive from scanning forever; Windows system/OS folders are pruned.
    """
    cands = []
    visited = [0]
    if os.name == "nt":
        roots = [f"{L}:\\" for L in "CDEFGH" if os.path.isdir(f"{L}:\\")]
    else:
        roots = [p for p in (os.path.expanduser("~"), "/opt", "/srv", "/data", "/home")
                 if os.path.isdir(p)]
        # drop roots nested inside another root (e.g. ~ under /home)
        roots = [r for r in roots if not any(
            r != o and r.startswith(o.rstrip("/") + "/") for o in roots)]
    skip = {".git", "node_modules", "__pycache__", ".venv", "venv", "env",
            "site-packages", "$recycle.bin", "system volume information",
            "windows", "appdata", ".cache", ".npm", ".vscode"}
    cap = {"dirs": 0, "limit": 6000, "done": False, "t0": time.time(),
           "seconds": 45}

    def rel(p):
        return p.replace("\\", "/")

    def candidate_info(d, layout):
        model_root = os.path.join(d, "assets", "weights") if layout == "modern" \
            else os.path.join(d, "weights")
        try:
            models = sorted(f for f in os.listdir(model_root)
                            if f.lower().endswith(".pth"))[:20]
        except Exception:
            models = []
        models = [(( "assets/weights/" if layout == "modern" else "weights/") + m)
                  for m in models]
        indices = []
        for sub in (os.path.join(d, "assets", "indices"), os.path.join(d, "logs")):
            if not os.path.isdir(sub):
                continue
            for dp, dn, fn in os.walk(sub):
                for f in fn:
                    if f.lower().endswith(".index"):
                        indices.append(
                            rel(os.path.relpath(os.path.join(dp, f), d)))
        # training checkpoints sit in logs/<name>/G_*.pth — NOT voice models;
        # report them so the UI can warn instead of the user picking one.
        checkpoints = []
        logs = os.path.join(d, "logs")
        if os.path.isdir(logs):
            for dp, dn, fn in os.walk(logs):
                for f in fn:
                    if f.lower().endswith(".pth") and \
                            f[:2].upper() in ("G_", "D_"):
                        checkpoints.append(
                            rel(os.path.relpath(os.path.join(dp, f), d)))
        return {"dir": rel(d), "layout": layout,
                "models": models, "indices": sorted(set(indices))[:40],
                "checkpoints": sorted(checkpoints)[:20]}

    def is_rvc(d):
        """A folder that can run RVC inference. Layouts vary; accept any of the
        usual markers so a real install is never missed (a missing
        assets/weights used to hide an otherwise perfect folder)."""
        has_infer = os.path.isdir(os.path.join(d, "infer"))
        has_old = os.path.exists(os.path.join(d, "RVC.py"))
        if not (has_infer or has_old):
            return None
        if os.path.isdir(os.path.join(d, "assets", "weights")):
            return "modern"
        if os.path.isdir(os.path.join(d, "weights")):
            return "classic"
        for probe in ("assets/indices", "logs", "runtime", "configs/config.json"):
            if os.path.exists(os.path.join(d, *probe.split("/"))):
                return "modern"          # right folder, weights not created yet
        return "modern" if has_infer else "classic"

    def walk(d, depth, budget=None, clock=None):
        if cap["done"] or len(cands) >= 8:
            return
        if clock is not None and time.time() - clock > cap["seconds"]:
            return
        cap["dirs"] += 1
        visited[0] = cap["dirs"]
        if budget is not None and budget["dirs"] > budget["limit"]:
            return
        if budget is not None:
            budget["dirs"] += 1
        if depth > 6:
            return
        found = is_rvc(d)
        if found:
            cands.append(candidate_info(d, found))
            return
        try:
            entries = list(os.scandir(d))
        except (PermissionError, OSError):
            return
        for e in entries:
            if cap["done"] or len(cands) >= 8:
                return
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if e.name.lower() in skip:
                continue
            if e.name.startswith("."):
                continue
            walk(e.path, depth + 1, budget, clock)

    # one budget per drive: a big C: must not eat the scan before D:/E: are
    # looked at (that is why "Find RVC folder" once reported nothing at all)
    for r in roots:
        budget = {"dirs": 0, "limit": cap["limit"]}
        walk(r, 0, budget, time.time())
    return cands, visited[0], [rel(r) for r in roots]
    return cands, visited[0], [rel(r) for r in roots]


def _discover_torch_python(rvc_dir=""):
    """Find the python that runs RVC-WebUI: the launcher .bat(s) inside the
    RVC folder, any python under it (venv / python / runtime / py311 / ...),
    then the pythons installed system-wide. First one with torch wins.

    Cached per RVC folder. Without the RVC folder this is just the old
    `py -0p` scan, so nothing is guessed when the folder is unknown."""
    global _TORCH_PY
    cache_key = "_TORCH_PY_" + (rvc_dir or "").lower()
    if cache_key in globals():
        return globals()[cache_key]
    found = None
    try:
        sys.path.insert(0, ROOT)
        import find_rvc_python as FRP
        best, _ = FRP.find(rvc_dir or "", "", include_self=(os.name != "nt"))
        found = best
    except Exception as e:
        print(f"[rvc] python discovery error: {type(e).__name__}: {e}",
              flush=True)
        found = None
    if not found and os.name == "nt":
        # fallback: ask the py launcher (no RVC folder known/possible)
        try:
            out = subprocess.run(["py", "-0p"], capture_output=True,
                                 timeout=8).stdout.decode("utf-8", "ignore")
        except Exception:
            out = ""
        paths = []
        for m in re.finditer(r'([A-Za-z]:\\[^\r\n]*?python(?:w)?\.exe)', out):
            q = m.group(1).strip().strip('"')
            if os.path.exists(q) and q.lower() not in [z.lower() for z in paths]:
                paths.append(q)
        for q in paths[:8]:
            try:
                if subprocess.run([q, "-c", "import torch"], capture_output=True,
                                  timeout=20).returncode == 0:
                    found = q
                    break
            except Exception:
                continue
    globals()[cache_key] = found
    _TORCH_PY = found
    if found:
        print(f"RVC python auto-detected (has torch): {found}", flush=True)
    return found


def _rvc_worker_cmd(cfg):
    """Resolve the RVC environment's python + build the worker command.

    Order: explicit RVC PYTHON field -> the torch-verified python found by
    find_rvc_python (launcher .bat -> any python under the RVC folder ->
    installed pythons) -> plain venv/root guesses -> system python."""
    d = cfg.get("rvcDir") or ""
    cands = []
    if cfg.get("python"):
        cands.append(cfg["python"])          # your explicit "RVC PYTHON" field
    discovered = _discover_torch_python(d)   # torch-verified, scans the RVC folder
    if discovered:
        cands.append(discovered)
    if d:                                    # plain guesses, only after the above
        for rel in ("venv/Scripts/python.exe", "venv/bin/python",
                    ".venv/Scripts/python.exe", ".venv/bin/python",
                    "python.exe", "python3.exe"):
            cands.append(os.path.join(d, rel))
    cands += ["python", "python3"]
    for py in cands:
        if os.path.isabs(py):
            if not os.path.exists(py):
                continue
        elif py not in ("python", "python3"):
            continue
        return [py, os.path.join(ROOT, "rvc_worker.py"),
                "--rvc-dir", d, "--model", cfg.get("model", ""),
                "--index", cfg.get("index", ""),
                "--port", str(RVC_PORT), "--f0-method", cfg.get("f0Method", "rmvpe")]
    return None


def _rvc_health():
    """Worker /health dict, or None if unreachable."""
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{RVC_PORT}/health")
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _rvc_log_tail(n=300):
    try:
        with open(RVC_WORKER_LOG, "rb") as f:
            return f.read()[-n:].decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _median_f0(x, sr=None):
    """Median speaking pitch (F0) of an audio array, in Hz. 0.0 = no voice found.

    Autocorrelation over loud 40 ms frames — cheap, dependency-free, and plenty
    accurate to tell three things apart:
      * a male-range voice (~85-155 Hz) from a female-range one (~165-255 Hz)
      * whether the clone kept the carrier's pitch (it should)
      * an octave slip in the chain (a bug) from a genuine timbre difference
    """
    import numpy as _np
    a = _np.asarray(x, dtype=_np.float32)
    sr = int(sr or SR)
    if a.size < sr // 2:
        return 0.0
    win = int(0.04 * sr)
    hop = int(0.02 * sr)
    lo, hi = max(2, int(sr / 400.0)), int(sr / 70.0)   # 70-400 Hz
    rms_all = float(_np.sqrt(_np.mean(a * a))) or 1.0
    vals = []
    for i in range(0, a.size - win, hop):
        seg = a[i:i + win]
        if float(_np.sqrt(_np.mean(seg * seg))) < 0.25 * rms_all:
            continue
        seg = seg - float(_np.mean(seg))
        ac = _np.correlate(seg, seg, mode="full")[win - 1:]
        if ac.size <= hi or ac[0] <= 0:
            continue
        ac = ac / ac[0]
        part = ac[lo:hi]
        if part.size == 0:
            continue
        k = int(_np.argmax(part)) + lo
        if ac[k] < 0.3:                                # not periodic enough
            continue
        vals.append(sr / float(k))
    return float(_np.median(vals)) if vals else 0.0


def _pitch_band(hz):
    if not hz:
        return "unmeasured"
    if hz < 155:
        return "male range"
    if hz < 165:
        return "low / androgynous range"
    return "female range"


def _model_identity_note(cfg, health, carrier_hz=0.0, clone_hz=0.0):
    """One line that names the model that actually loaded, and — when the clone
    comes out in the wrong pitch range — says which knob caused it."""
    h = health or {}
    ident = h.get("identity") or {}
    bits = []
    who = ident.get("file") or os.path.basename(cfg.get("model") or "")
    if who:
        extra = []
        if ident.get("size_mb"):
            extra.append("%s MB" % ident["size_mb"])
        if ident.get("version"):
            extra.append(str(ident["version"]))
        if ident.get("sr"):
            extra.append("%dk" % (int(ident["sr"]) // 1000))
        bits.append("loaded model: " + who
                    + ((" (" + " · ".join(extra) + ")") if extra else ""))
    if ident.get("index"):
        bits.append("index: " + ident["index"])
    elif cfg.get("index"):
        bits.append("index: " + os.path.basename(cfg["index"]))
    else:
        bits.append("index: none found (auto-detect) — the clone will lean "
                    "toward the base voice")
    pitch_set = int(cfg.get("pitch") or 0)
    if pitch_set:
        semis = ("%+d semitones" % pitch_set)
        if abs(pitch_set) >= 11:
            semis += " (about an octave %s)" % ("down" if pitch_set < 0 else "up")
        bits.append("PITCH is set to %d — %s" % (pitch_set, semis))
    dropped = bool(carrier_hz and clone_hz and clone_hz < carrier_hz * 0.75)
    if pitch_set <= -11 and (dropped or (clone_hz and clone_hz < 160.0)):
        bits.append("THAT IS THE CAUSE: the clone landed at %d Hz — the PITCH "
                    "slider moved the voice an octave down, which by itself is "
                    "what makes a female model sound male. Set PITCH to 0 and "
                    "test again." % int(clone_hz or 0))
    elif pitch_set == 0 and dropped:
        bits.append("with PITCH at 0 that drop is not normal — check that MODEL "
                    "is the female .pth (the line above names the file that "
                    "loaded) and that the index belongs to the same model.")
    if ident.get("info"):
        bits.append("model metadata: " + str(ident["info"])[:160])
    return " | ".join(bits)


def _pitch_report(carrier_hz, clone_hz):
    """One sentence for the UI: what the clone did to the pitch, and whether
    the difference is normal (timbre) or a chain bug (octave slip)."""
    if not clone_hz:
        return ""
    parts = []
    if carrier_hz:
        parts.append("base voice %.0f Hz (%s)" % (carrier_hz, _pitch_band(carrier_hz)))
    parts.append("clone %.0f Hz (%s)" % (clone_hz, _pitch_band(clone_hz)))
    line = "Voice pitch: " + " → ".join(parts) + "."
    if carrier_hz and clone_hz:
        ratio = clone_hz / carrier_hz
        if ratio < 0.71 or ratio > 1.41:
            line += ("  ⚠ the clone is about an octave %s than the base voice — "
                     "that is a pitch-handling problem, not your model: send me "
                     "this line." % ("lower" if ratio < 1 else "higher"))
        else:
            line += ("  The clone keeps the base voice's pitch; the TIMBRE comes "
                     "from your model — a male model always sounds male.")
    return line


def _rvc_looks_like_root(path):
    """Which RVC-WebUI markers does this folder have? [] = does not look like one.

    Layouts differ a lot between builds, so several markers are accepted:
    infer/ (2.3+), RVC.py (older), configs/config.json, runtime/ (the portable
    Windows build), and assets/weights or weights (models).
    """
    marks = []
    if not path or not os.path.isdir(path):
        return marks
    for rel, label in (("infer", "infer/"), ("RVC.py", "RVC.py"),
                       ("configs/config.json", "configs/config.json"),
                       ("runtime", "runtime/"), ("weights", "weights/"),
                       ("assets/weights", "assets/weights/")):
        if os.path.exists(os.path.join(path, *rel.split("/"))):
            marks.append(label)
    return marks


def _rvc_resolve_cfg(cfg):
    """Turn the MODEL / INDEX fields into real file paths (folder -> file).

    Returns a list of human notes ([] when both fields were already files).
    Never raises: a field that cannot be resolved is left as-is so the normal
    error path can explain it.
    """
    notes = []
    rvc_dir = cfg.get("rvcDir") or ""
    if rvc_dir and os.path.isdir(rvc_dir):
        marks = _rvc_looks_like_root(rvc_dir)
        if not marks:
            notes.append("this folder does not look like an RVC-WebUI folder "
                         "(no infer/, RVC.py, configs/config.json, runtime/ or "
                         "weights/ inside): " + rvc_dir
                         + " — press Find RVC folder, or paste the folder that "
                           "contains the RVC files")
        else:
            print("[rvc] root markers in " + rvc_dir + ": " + ", ".join(marks),
                  flush=True)
    if resolve_model_field is None:
        return notes
    if not rvc_dir or not os.path.isdir(rvc_dir):
        return notes
    model, note = resolve_model_field(
        rvc_dir, cfg.get("model", ""),
        prefer=["Sonaro-kh.pth", os.path.basename(cfg.get("model", ""))])
    if note:
        notes.append(note)
    if model:
        try:
            cfg["model"] = os.path.relpath(model, rvc_dir).replace(os.sep, "/")
        except Exception:
            cfg["model"] = model
    idx, inote = resolve_index_field(
        rvc_dir, cfg.get("index", ""),
        prefer=[os.path.basename(model or cfg.get("model", ""))])
    if inote:
        notes.append(inote)
    if idx:
        try:
            cfg["index"] = os.path.relpath(idx, rvc_dir).replace(os.sep, "/")
        except Exception:
            cfg["index"] = idx
    return notes


def _rvc_ensure_worker(cfg, wait=150):
    """Make sure the worker is up and the model is loaded. (ok, detail)."""
    with _RVC_LOCK:
        h = _rvc_health()
        if h and h.get("state") == "ready":
            return True, "ready"
        proc = RVC_STATE.get("proc")
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        cmd = _rvc_worker_cmd(cfg)
        _rq_log("[rvc] worker start: %s | rvc-dir=%s | model=%s | index=%s"
                % ((os.path.basename(cmd[0]) if cmd else "?"),
                   cfg.get("rvcDir", "?"), cfg.get("model", "?"),
                   cfg.get("index") or "(auto)"))
        if cmd is None:
            return False, ("no Python found for the RVC environment — set the "
                           "RVC folder (or Python path) in the RVC section")
        try:
            logf = open(RVC_WORKER_LOG, "ab")
            RVC_STATE["proc"] = subprocess.Popen(
                cmd, stdout=logf, stderr=subprocess.STDOUT,
                cwd=cfg.get("rvcDir") or None)
        except Exception as e:
            return False, f"could not start RVC worker: {e}"
        t0 = time.time()
        while time.time() - t0 < wait:
            time.sleep(1.5)
            h = _rvc_health()
            if h is None:
                if RVC_STATE["proc"].poll() is not None:
                    return False, ("RVC worker exited during model load — "
                                   "see the error below")
                continue
            if h.get("state") == "ready":
                return True, "ready"
            if h.get("state") == "error":
                _rq_log("[rvc] worker error: " + str(h.get("error", ""))[:200])
                return False, h.get("error", "model load failed")
        return False, ("the RVC worker did not finish loading the model within "
                       "%ds — the first load of a voice model really can take a "
                       "minute or two, so press Test clone again and watch the "
                       "log below; if it stays stuck, the log's last line names "
                       "the reason" % wait)


def wav_bytes_to_f32(wav: bytes) -> np.ndarray:
    out = ffmpeg_run(in_bytes=wav, in_name="in.wav",
                     args=["-f", "f32le", "-ar", str(SR), "-ac", "1"],
                     out_name="out.f32", timeout=180, step="decoding audio")
    return np.frombuffer(out, dtype=np.float32)


def _rvc_convert_f32(f32: np.ndarray, cfg) -> np.ndarray:
    """Send one line through the RVC worker. VoiceServiceDown if it can't."""
    wav = f32_to_wav_bytes(f32)
    payload = json.dumps({
        "wav_b64": _b64.b64encode(wav).decode(),
        "pitch": int(cfg.get("pitch", 0)),
        "index_rate": float(cfg.get("indexRate", 0.75)),
        "protect": float(cfg.get("protect", 0.33)),
        "f0_method": cfg.get("f0Method", "rmvpe"),
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{RVC_PORT}/convert", data=payload,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            j = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read()).get("error", "")
        except Exception:
            pass
        raise VoiceServiceDown(f"RVC conversion failed: {detail[:200]}")
    except Exception as e:
        raise VoiceServiceDown(
            f"RVC worker unreachable ({str(e)[:120]}) — it may have crashed; "
            "press Generate again")
    out_wav = _b64.b64decode(j.get("wav_b64", ""))
    if len(out_wav) < 1000:
        raise VoiceServiceDown("RVC worker returned no audio")
    return wav_bytes_to_f32(out_wav)


def _is_rvc_error(exc) -> bool:
    """True when the failure came from the clone layer (not the TTS provider).
    Such a failure must NEVER be answered by silently skipping the line."""
    try:
        return "rvc" in str(exc).lower()
    except Exception:
        return False


CACHE_POOL = ThreadPoolExecutor(max_workers=2)   # background mp3 cache writes


def _rvc_convert_f32_batch(arrs, cfg, on_batch=None):
    """Send MANY lines through the RVC model in ONE pass.

    The lines are welded together with a short silence, converted as a single
    piece and split back in proportion. Everything RVC does per call — temp
    files, the f0 model, the index, resampling — is paid once for the whole
    group, and the GPU works on longer audio (better occupancy) instead of a
    stream of 2-second snippets.

    If the output length does not match the input (a sign the split would
    drift), it falls back to converting line by line: correctness first.
    """
    arrs = [np.asarray(a, dtype=np.float32) for a in arrs if a is not None
            and np.asarray(a).size]
    if not arrs:
        return []
    if len(arrs) == 1:
        return [_rvc_convert_f32(arrs[0], cfg)]
    gap = np.zeros(int(RVC_BATCH_GAP * SR), dtype=np.float32)
    parts, starts, lens, pos = [], [], [], 0
    for k, a in enumerate(arrs):
        if k:
            parts.append(gap)
            pos += gap.size
        starts.append(pos)                     # where this line starts
        lens.append(a.size)
        parts.append(a)
        pos += a.size
    joined = np.concatenate(parts)
    t0 = time.time()
    out = _rvc_convert_f32(joined, cfg)        # ONE worker round trip
    ratio = (out.size / float(joined.size)) if joined.size else 1.0
    if not (0.9 <= ratio <= 1.1):
        print(f"[rvc] batch came back {ratio:.3f}x its input length — "
              f"converting {len(arrs)} line(s) one by one instead", flush=True)
        return [_rvc_convert_f32(a, cfg) for a in arrs]
    # each line gets its OWN length back (not the separator silence: the
    # pipeline inserts the plan's own pauses, and a welded-in 0.15 s would
    # have quietly stretched every pause in the episode)
    pieces = []
    for lo, ln in zip(starts, lens):
        a = int(round(lo * ratio))
        b = a + int(round(ln * ratio))
        pieces.append(out[a:max(a + 1, b)])
    if on_batch:
        try:
            on_batch(len(arrs), joined.size / float(SR), time.time() - t0)
        except Exception:
            pass
    return pieces


async def synth_unit_mp3(text: str, voice: str, rate: str, pitch: int = 0):
    """Three-engine chain with a circuit breaker. Returns (mp3_bytes, engine).

    1) edge-tts — up to 5 tries; a definitive 403/410 opens the breaker:
       for the next 2 minutes Microsoft is skipped entirely (hammering a
       refusing provider only deepens the rate-limit — the "failed at 20%" bug)
    2) our own Microsoft WebSocket client
    3) Google gTTS — serialized, polite pace (marks the episode degraded)
    """
    last = None

    def ok(mp3, engine):
        # reject truncated provider output (rate-limited providers often return
        # a few hundred ms instead of the full read) before it gets spoken/cached
        need = _expected_min_seconds(text)
        est = _estimate_mp3_seconds(mp3)
        if est is not None:
            if est >= need * 1.25:
                return mp3, engine            # obviously complete
            if est < need * 0.6:
                raise RuntimeError(
                    f"truncated audio: about {est:.2f}s returned for "
                    f"{len((text or '').split())} words")
        dur = _mp3_duration(mp3)              # borderline: measure exactly
        if dur < need:
            raise RuntimeError(
                f"truncated audio: {dur:.2f}s returned for "
                f"{len((text or '').split())} words")
        return mp3, engine

    ms_open = time.time() < SERVICE_STATE["edge_blocked_until"]
    if time.time() < SERVICE_STATE.get("throttle_until", 0.0):
        # the burst breaker asked for quiet: do not spend a retry budget on a
        # provider that is currently rate-limiting us
        ms_open = True
    if not ms_open:
        # 3 tries, short waits: a long episode must not sit 11 s on one sentence
        for attempt in range(3):
            await _edge_pace()
            try:
                return ok(await _try_edge_tts(text, voice, rate, pitch), "edge")
            except Exception as e:
                last = e
                if _definitive_block(e):
                    SERVICE_STATE["edge_blocked_until"] = time.time() + 120
                    break  # point of no return — go to engine 2
                await asyncio.sleep((0.5, 1.2, 3.0)[attempt])
    try:
        return ok(await _try_fallback_tts(text, voice, rate), "ms")
    except Exception as e2:
        last2 = e2
    try:
        loop = asyncio.get_running_loop()
        return ok(await loop.run_in_executor(None, _gtts_bytes, text, voice), "google")
    except Exception as e3:
        last3 = e3

    # OFFLINE ENGINE: every network provider failed. If a local Khmer model is
    # installed (menu 7 / install_khmer_tts.bat option 2), speak it here rather
    # than waiting out a 30 s outage. Khmer lines only — the model is Khmer-only.
    if is_khmer(text) and (voice or "").lower().startswith("km"):
        try:
            loop = asyncio.get_running_loop()
            return ok(await loop.run_in_executor(None, _local_tts_bytes, text),
                      "local")
        except Exception as e5:
            last4 = e5
            print(f"[tts] local offline engine failed too: {str(e5)[:120]}", flush=True)

    # During a burst failure the whole provider is unwell: crawling through
    # this unit for another 30 s only hides the problem and delays the job's
    # own, much more effective, recovery. Hand it to the job immediately.
    if SERVICE_STATE.get("burst_fail_streak", 0) >= 3:
        raise VoiceServiceDown(
            "the voice service is failing in bursts right now — the episode is "
            "waiting a moment and will continue by itself")

    # LAST RESORT: every provider failed — the outage is probably seconds to a
    # couple of minutes long. Pause, then walk the chain again (still honoring
    # the circuit breaker) before giving up, so short outages never surface
    # as a FAILED job.
    for wait_s in (6, 14):
        await asyncio.sleep(wait_s)
        if time.time() >= SERVICE_STATE["edge_blocked_until"]:
            try:
                return ok(await _try_edge_tts(text, voice, rate, pitch), "edge")
            except Exception as e:
                last = e
        try:
            return ok(await _try_fallback_tts(text, voice, rate), "ms")
        except Exception:
            pass
        try:
            loop = asyncio.get_running_loop()
            return ok(await loop.run_in_executor(None, _gtts_bytes, text, voice), "google")
        except Exception as e4:
            last3 = e4
    local_note = locals().get("last4")
    print(f"[tts] unit failed ALL engines — edge: {last} | ms: {last2} | "
          f"google: {last3}" + (f" | local: {local_note}" if local_note else ""),
          flush=True)
    wait_left = max(0, int(SERVICE_STATE.get("edge_blocked_until", 0) - time.time()))
    why = ("the online voice providers are refusing requests right now — usually a "
           "rate limit, and it clears by itself")
    if wait_left:
        why += f" (Microsoft is on cooldown for ~{wait_left}s more)"
    raise VoiceServiceDown(
        "the voice service is temporarily unavailable — " + why +
        ". Press Generate again in a minute and it resumes where it stopped "
        f"(edge: {last}; ms-backup: {last2}; google: {last3})"
    )


def mp3_to_f32(mp3) -> np.ndarray:
    """Decode an mp3 clip to float samples — via temp files, never a double pipe.

    Accepts EITHER the mp3 bytes or a path to an mp3 file: both shapes are
    used by the studio, and mixing them up used to die with the useless
    "a bytes-like object is required, not 'str'".
    """
    if isinstance(mp3, (str, bytes)) and not isinstance(mp3, bytes) \
            and os.path.exists(mp3):
        with open(mp3, "rb") as f:
            mp3 = f.read()
    elif hasattr(mp3, "__fspath__"):                      # pathlib.Path
        with open(os.fspath(mp3), "rb") as f:
            mp3 = f.read()
    out = ffmpeg_run(in_bytes=mp3, in_name="in.mp3",
                     args=["-f", "f32le", "-ar", str(SR), "-ac", "1"],
                     out_name="out.f32", timeout=180, step="decoding the voice clip")
    return np.frombuffer(out, dtype=np.float32)


def f32_to_i16_bytes(a: np.ndarray) -> bytes:
    # nan_to_num: a single bad sample must never turn into junk audio
    a = np.nan_to_num(a, nan=0.0, posinf=1.0, neginf=-1.0)
    return (np.clip(a, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def f32_to_wav_bytes(a: np.ndarray) -> bytes:
    data = (np.clip(a, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(data), b"WAVE", b"fmt ", 16, 1, 1, SR, SR * 2, 2, 16, b"data", len(data),
    )
    return header + data


def _wav_info(path: str):
    """(sample_rate, data_offset, data_bytes) of a WAV file, by walking its
    chunks — NOT by assuming the data chunk sits at offset 36.

    ffmpeg writes a LIST/INFO chunk between "fmt " and "data", so a fixed
    offset reads the LIST size (26) as the audio length and every cleaned file
    looked 0.0003 s long. Chunks are the only correct way.
    """
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(4096)
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            return 0, 0, 0
        sr = 0
        pos = 12
        while pos + 8 <= len(head):
            cid = head[pos:pos + 4]
            csz = struct.unpack("<I", head[pos + 4:pos + 8])[0]
            if cid == b"fmt " and pos + 8 + 16 <= len(head):
                sr = int(struct.unpack("<I", head[pos + 12:pos + 16])[0])
            elif cid == b"data":
                off = pos + 8
                n = csz
                if n <= 0 or off + n > size:
                    n = max(0, size - off)      # streamed: trust the file size
                return sr, off, n
            pos += 8 + csz + (csz % 2)
        # no data chunk found: treat the file as headerless PCM
        return sr, 44, max(0, size - 44)
    except Exception:
        return 0, 0, 0


def wav_rate(path: str) -> int:
    """Sample rate from a WAV header (0 when the file is not a plain WAV)."""
    return _wav_info(path)[0]


def wav_duration(path: str) -> float:
    """Exact duration of a WAV — correct for the 24 kHz working master, the
    48 kHz Clean & Clear master, and any file ffmpeg wrote (see _wav_info)."""
    try:
        sr, _off, nbytes = _wav_info(path)
        if not sr or nbytes <= 0:
            return 0.0
        # 16-bit mono everywhere in this studio; derive the width from the
        # file itself when the header is odd
        with open(path, "rb") as f:
            head = f.read(4096)
        ch, bits = 1, 16
        p = 12
        while p + 8 <= len(head):
            cid = head[p:p + 4]
            csz = struct.unpack("<I", head[p + 4:p + 8])[0]
            if cid == b"fmt ":
                ch = int(struct.unpack("<H", head[p + 10:p + 12])[0]) or 1
                bits = int(struct.unpack("<H", head[p + 22:p + 24])[0]) or 16
                break
            p += 8 + csz + (csz % 2)
        return nbytes / float(sr * ch * max(1, bits // 8))
    except Exception:
        return 0.0


def wav_to_mp3(wav_path: str, mp3_path: str, kbps: int = None):
    """Encode the final mp3. Bitrate follows the master: a Clean & Clear
    master is 48 kHz and gets 192 kbps (HD); a plain 24 kHz master gets
    128 kbps — 96 kbps was quietly throwing away detail."""
    if kbps is None:
        kbps = 192 if (wav_rate(wav_path) or 0) >= 48000 else 128
    ffmpeg_quiet(["-y", "-loglevel", "error", "-i", wav_path,
                  "-c:a", "libmp3lame", "-b:a", f"{int(kbps)}k", mp3_path],
                 timeout=3600, step="mp3 encode")


def wav_to_hd(wav_path: str, hd_path: str):
    """The HD deliverable: 48 kHz / 24-bit / stereo.

    A Clean & Clear master is already 48 kHz (and already carries the
    reconstructed high band); a plain master is resampled up — the sample
    rate is honest, the extra band only exists when the neural engine ran.
    """
    ffmpeg_quiet(["-y", "-loglevel", "error", "-i", wav_path,
                  "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le", hd_path],
                 timeout=7200, step="HD wav encode")


def convert(master_path: str, fmt: str):
    exts = {"wav": "wav", "m4a": "m4a", "ogg": "ogg", "mp3": "mp3"}
    if fmt not in exts:
        raise ValueError("bad format")
    base = master_path
    for ext in ("master", "wav", "mp3"):
        if os.path.exists(os.path.join(CACHE_DIR, os.path.basename(master_path) + ext)):
            base = os.path.join(CACHE_DIR, os.path.basename(master_path) + ext)
            break
    out_path = os.path.join(CACHE_DIR, os.path.basename(master_path) + "." + exts[fmt])
    if base == out_path:
        return out_path
    if not os.path.exists(out_path):
        if fmt == "wav":
            args = ["-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le"]  # HD 24-bit/48k/stereo
        elif fmt == "m4a":
            args = ["-c:a", "aac", "-b:a", "192k"]
        elif fmt == "ogg":
            args = ["-c:a", "libopus", "-b:a", "112k"]
        else:
            base_sr = wav_rate(base) or SR
            kbps = 192 if base_sr >= 48000 else 128
            args = ["-c:a", "libmp3lame", "-b:a", f"{kbps}k",
                    "-ar", str(base_sr)]
        ffmpeg_quiet(["-y", "-loglevel", "error", "-i", base] + args + [out_path],
                     timeout=3600, step="converting to " + fmt)
        if not os.path.exists(out_path):
            raise RuntimeError("conversion failed: no output file")
    return out_path

# -------------------------------------------------------- studio beds -------

def _lowpass_white(rng, n: int, f_cut: float, carry: float = 0.0):
    """Unit-RMS low-passed white noise (smooth rumble). Returns (noise, end_state)."""
    a = 1.0 - min(0.99, max(0.001, f_cut / SR))
    w = rng.normal(0, 1, n)
    b = np.empty(n, dtype=np.float64)
    b[0] = carry  # continue from the previous chunk's state (0 = start from rest)
    b[1:] = a * b[:-1] + (1 - a) * w[1:]
    std = b.std() + 1e-9
    return b / std, b[-1] / std


def gen_bed(kind: str, n: int, offset: float, seed: int, total: float, carry: float = 0.0):
    """Procedural 24 kHz mono bed, peak ~0.55, continuous across chunks.
    Returns (bed, end_state) so the next chunk can continue the noise state."""
    t = offset + np.arange(n, dtype=np.float64) / SR
    rng = np.random.default_rng(seed)
    new_carry = 0.0
    if kind == "warm":
        brown, new_carry = _lowpass_white(rng, n, 350, carry)
        s = (0.32 * np.sin(2 * np.pi * 55 * t)
             + 0.18 * np.sin(2 * np.pi * 110 * t)
             + 0.07 * np.sin(2 * np.pi * 164.81 * t)
             + 0.14 * brown)
        s *= (0.85 + 0.15 * np.sin(2 * np.pi * 0.08 * t))
    elif kind == "drone":
        brown, new_carry = _lowpass_white(rng, n, 180, carry)
        s = (0.42 * np.sin(2 * np.pi * 38 * t)
             + 0.20 * np.sin(2 * np.pi * 76.5 * t)
             + 0.10 * np.sin(2 * np.pi * 114 * t)
             + 0.16 * brown)
        s *= (0.6 + 0.4 * np.sin(2 * np.pi * 0.05 * t - 1.2))
    elif kind == "crackle":
        s = rng.normal(0, 0.045, n)
        s += 0.018 * np.sin(2 * np.pi * 50 * t)
        k = max(1, int(n / SR * 7))
        idx = rng.integers(0, max(1, n - 4), k)
        amp = rng.uniform(0.2, 0.55, k)
        decay = np.exp(-np.arange(4) / 2.0) * 0.3
        for i, a in zip(idx, amp):
            s[i:i + 4] += a * decay
    elif kind == "pad":
        s = np.zeros(n)
        for f, g in ((110.0, 0.30), (164.81, 0.22), (220.0, 0.20), (277.18, 0.12)):
            s += g * np.sin(2 * np.pi * f * t + 0.4 * np.sin(2 * np.pi * 0.11 * t))
        s *= np.clip(t / 4.0, 0, 1)
    else:
        s = np.zeros(n)
    peak = np.max(np.abs(s)) + 1e-9
    s = s / peak * 0.55
    # short fade in at the very start, fade out at the very end
    fade = min(int(0.4 * SR), n)
    if offset < 1e-6 and n > fade:
        s[:fade] *= np.linspace(0, 1, fade)
    if total - (offset + n / SR) < 1e-6 and n > fade:
        s[-fade:] *= np.linspace(1, 0, fade)
    return s.astype(np.float32), new_carry

# ------------------------------------------------------- music beds ---------
# User-uploaded audio that is looped (with a 1s crossfade at the wrap) to fit
# the whole episode, with a 1.5s fade-in and 3s fade-out. Files can be 1–2h.
BEDI_LOCK = threading.Lock()

def _beds_load():
    try:
        with open(BEDI_INDEX, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}

def _beds_save(idx):
    os.makedirs(BEDI_DIR, exist_ok=True)
    tmp = BEDI_INDEX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False)
    os.replace(tmp, BEDI_INDEX)

def _bed_duration(path):
    try:
        r = subprocess.run([FFMPEG, "-hide_banner", "-i", path],
                           capture_output=True, text=True, timeout=180)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return None

def _atempo_chain(speed):
    """ffmpeg atempo filters, each stage kept within [0.5, 2.0]."""
    s = min(2.0, max(0.5, float(speed)))
    chain = []
    while s > 2.0:
        chain.append(2.0); s /= 2.0
    while s < 0.5:
        chain.append(0.5); s /= 0.5
    chain.append(round(s, 4))
    out = []
    for c in chain:
        out += ["-filter:a", "atempo=" + str(c)]
    return out

def _bed_raw(bid: str, speed: float):
    """Decode an uploaded bed to a 24 kHz/16-bit/mono raw file at the given
    speed (cached per id+speed). Returns the raw path."""
    speed = min(2.0, max(0.5, float(speed)))
    os.makedirs(BEDI_DIR, exist_ok=True)
    tag = str(int(round(speed * 100)))
    p = os.path.join(BEDI_DIR, bid + "_s" + tag + ".raw")
    if os.path.exists(p) and os.path.getsize(p) > 1000:
        return p
    with BEDI_LOCK:
        entry = _beds_load().get(bid)
    if not entry or not os.path.exists(entry.get("path", "")):
        raise ValueError("music bed not found")
    args = [FFMPEG, "-y", "-loglevel", "error", "-i", entry["path"]]
    args += _atempo_chain(speed)
    args += ["-ar", str(SR), "-ac", "1", "-f", "s16le", p + ".tmp"]
    r = subprocess.run(args, capture_output=True, timeout=5400)
    if r.returncode != 0 or not os.path.exists(p + ".tmp") or os.path.getsize(p + ".tmp") < 1000:
        try: os.remove(p + ".tmp")
        except OSError: pass
        raise RuntimeError("music bed decode failed: " + r.stderr.decode(errors="ignore")[:300])
    os.replace(p + ".tmp", p)
    return p

class BedLoopReader:
    """Streams an uploaded music bed (24k/16/mono raw) chunk by chunk, looping
    it to the full episode length. A 1s crossfade blends the loop wrap so the
    repeat is not audible as a click; 1.5s fade-in at the start and a 3s
    fade-out over the final seconds of the episode."""
    def __init__(self, raw_path: str, total_samples: int):
        self.total = int(total_samples)
        self.f = open(raw_path, "rb")
        self.file_samples = max(1, os.path.getsize(raw_path) // 2)
        self.FADE = int(1.0 * SR) if self.file_samples > 2 * int(1.0 * SR) else 0
        self.pos = 0
        self.fade_in_n = int(1.5 * SR)
        self.fade_out_start = self.total - int(3.0 * SR)

    def _seek_read(self, sample_off: int, count: int):
        b = b""
        need = count * 2
        self.f.seek(min(sample_off, self.file_samples - 1) * 2)
        got = self.f.read(min(need, max(0, self.file_samples - sample_off) * 2))
        if len(got) < need:
            got += b"\x00" * (need - len(got))
        return got

    def read(self, n: int):
        """Return n mono f32 samples in ~[-1,1]."""
        out = np.zeros(n, dtype=np.float32)
        i = 0
        while i < n:
            p = self.pos + i
            q = p % self.file_samples
            seg = min(self.file_samples - q, n - i)
            b = self._seek_read(q, seg)
            s = np.frombuffer(b, dtype="<i2").astype(np.float32) / 32768.0
            # crossfade the loop wrap — but never at the very first pass,
            # where the start of the file should play clean (just fade-in).
            if self.FADE and q < self.FADE and p >= self.file_samples:
                k = min(seg, self.FADE - q)
                bt = self._seek_read(self.file_samples - self.FADE, k)
                tail = np.frombuffer(bt, dtype="<i2").astype(np.float32) / 32768.0
                a = np.linspace(0.0, 1.0, k, dtype=np.float32)
                s[:k] = s[:k] * a + tail * (1.0 - a)
            out[i:i + seg] = s
            i += seg
        if self.pos == 0 and self.fade_in_n:
            k = min(self.fade_in_n, n)
            out[:k] *= np.linspace(0.0, 1.0, k, dtype=np.float32)
        if self.pos >= self.fade_out_start:
            k = min(n, max(0, self.total - self.pos))
            if k:
                out[:k] *= np.linspace(1.0, 0.0, k, dtype=np.float32)
        self.pos += n
        return out

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass

# ------------------------------------------------------------- podcast ------

BRIDGES = {
    "en": {
        "B": [  # spoken by B, handing over to A
            "Interesting. So walk us through the next part.",
            "I did not see that coming. What happened next?",
            "That is the detail I care about most. Go on.",
            "Now, how did that turn out?",
            "Let's dig a little deeper into that.",
            "So, tell us more.",
        ],
        "A": [  # spoken by A, handing over to B
            "So, here is where it gets interesting. What happened next?",
            "Now, I have to hear the rest of that.",
            "This is the part most people miss. Continue, please.",
            "Okay, take it from here.",
            "And that leads us to the next part.",
            "Let's keep going. What happens next?",
        ],
        "intro": (
            "Welcome back, everyone. Today we are getting into a topic I have been wanting to talk about for a while.",
            "Me too. There is more to it than you would think at first glance.",
        ),
        "outro": (
            "Well, that is time for today. Thanks so much for listening.",
            "And thanks to all of you tuning in. See you in the next one.",
        ),
    },
    "th": {
        "B": [
            "น่าสนใจเลย แล้วต่อจากนั้นเป็นอย่างไร",
            "ไม่คาดคิดเลย แล้วเรื่องจบลงอย่างไร",
            "ตรงนี้สำคัญมากเลย เล่าต่อเลยครับ",
            "แล้วต่อจากนั้นเกิดอะไรขึ้น",
            "มาเจาะลึกตรงนี้กันเถอะ",
            "เล่าให้ฟังต่อเลย",
        ],
        "A": [
            "แล้วตรงนี้แหละที่เริ่มสนุก ต่อจากนั้นเกิดอะไรขึ้น",
            "ผมต้องรู้ต่อว่าเรื่องนี้เป็นอย่างไร",
            "นี่คือส่วนที่คนส่วนใหญ่ไม่รู้ ต่อเลย",
            "มาฟังกันต่อว่าเกิดอะไรขึ้น",
            "แล้วเรื่องก็เดินทางมาถึงตรงนี้",
            "ฟังกันต่อครับ แล้วต่อจากนั้นเป็นอย่างไร",
        ],
        "intro": (
            "ยินดีต้อนรับสู่รายการของเรา วันนี้เรามาคุยกันในหัวข้อที่หลายคนอยากรู้",
            "ใช่แล้ว เรื่องนี้มีอะไรมากกว่าที่คิดเยอะ",
        ),
        "outro": (
            "หมดเวลาสำหรับวันนี้ ขอบคุณที่รับฟังนะครับ",
            "พบกันใหม่ครั้งหน้า แล้วเจอกัน",
        ),
    },
    "km": {
        "B": [
            "ចាប់អារម្មណ៍ណាស់។ តើបន្ទាប់មកមានអ្វីកើតឡើងទៀត?",
            "ខ្ញុំមិនបានគិតទេ។ តើរឿងនេះបញ្ចប់យ៉ាងដូចម្តេច?",
            "ចំណុចនេះសំខាន់ណាស់។ សូមបន្តទត។",
            "បន្ទាប់ពីនោះ មានអ្វីកើតឡើងទៀត?",
            "យើងមកស្វែងយល់បន្តិចទៀត។",
            "សូមរៀបរាប់បន្តទត។",
        ],
        "A": [
            "ហើយនៅចំណុចនេះហើយ រឿងចាប់ផ្តើមរីកចម្រើន។ តើបន្ទាប់មកកើតឡើងអ្វី?",
            "ខ្ញុំត្រូវដឹងបន្ថែមថា រឿងនេះដំណើរការយ៉ាងដូចម្តេច។",
            "នេះជាផ្នែកដែលអ្នកភាគច្រើនមិនដឹង។ សូមបន្ត។",
            "សូមស្តាប់បន្តទត។",
            "ហើយរឿងកមកដល់ចំណុចនេះ។",
            "សូមស្តាប់បន្តទត។ តើបន្ទាប់មកមានអ្វីកើតឡើងទៀត?",
        ],
        "intro": (
            "សូមស្វាគមន៍មកកាន់កម្មវិធីរបស់យើង។ ថ្ងៃនេះយើងនិយាយគ្នាអំពីប្រធានបទមួយដែលសំខាន់ណាស់។",
            "បាទ រឿងនេះមានអ្វីៗច្រើនជាងដែលគិតទុក។",
        ),
        "outro": (
            "ពេលវេលាចប់សម្រាប់ថ្ងៃនេះ។ សូមអរគុណសម្រាប់ការស្តាប់។",
            "ជួបគ្នាម្តងទៀតនៅពេលក្រោយ។",
        ),
    },
}


def _sent_list(text):
    out = []
    for para in [p.strip() for p in re.split(r"\n+", text) if p.strip()]:
        for s in re.findall(r"[^.!?…]*[.!?…]+|[^.!?…]+$", para):
            s = s.strip()
            if len(s) > 1:
                out.append(s)
    return out


def _topic_of(text):
    lines = [l.strip() for l in (text or "").strip().splitlines() if l.strip()]
    t = lines[0] if lines else (text or "").strip()
    if not t:
        return "this topic"
    t = t.strip(" \t\"'“”—-–:")
    if len(t) > 70:
        t = t[:70]
        t = t[: t.rfind(" ")].rstrip() if " " in t else t
    return t.rstrip(" .,:;—-…")


SAL_STOP = {
    "The","A","An","Inside","However","Yet","For","So","But","When","After","Before",
    "During","Today","Now","Then","Here","There","This","That","These","Those","It",
    "Its","He","She","They","We","You","Mr","Mrs","Ms","Dr","Saint","No","Yes","Well",
    "And","Or","Not","King","Queen","God","New","Old","Great","First","Last",
}


def _salience(s):
    """Most salient element of a sentence: a number+unit, a proper noun, or nothing."""
    m = re.search(r"\b(\d+(?:[.,]\d+)*(?:st|nd|rd|th)?)\s+([A-Za-z]{3,}(?:\s+[A-Za-z]{3,})?)\b", s)
    if m:
        return ("number", m.group(0))
    names = re.findall(r"\b[A-Z][a-z]{2,}(?:'s)?\b(?:\s+[A-Z][a-z]{2,}(?:'s)?\b){0,2}", s)
    for nm in names:
        if len(nm.split()) >= 2:
            return ("name", nm)  # multi-word capitalized spans are proper nouns
        first = nm.rstrip("'s")
        if first in SAL_STOP:
            continue
        if s.startswith(nm):
            continue  # sentence-initial word — capitalized by grammar, not a name
        return ("name", nm)
    return ("idea", None)


def _auto_en(text):
    """Content-aware two-host discussion: hosts tease and reference the actual
    details (numbers, names, turning points) found in the source text."""
    sents = _sent_list(text)
    facts = [s for s in sents if len(s.split()) >= 6] or sents or [(text or "").strip()]
    if len(facts) > 8:
        idx = sorted({round(i * (len(facts) - 1) / 7) for i in range(8)})
        facts = [facts[i] for i in idx]
    topic = _topic_of(text)
    L = []
    if len(topic.split()) > 6:
        # first line is a full sentence, not a title — tease it instead of repeating it
        intro_t = " ".join(topic.split()[:5]) + " — and the story behind it."
        L.append(("A", f"Welcome back, everyone. Today's episode starts with {intro_t}"))
    else:
        L.append(("A", f"Welcome back, everyone. Today's episode: {topic}."))
    L.append(("B", "I've read through the material, and I have to say — there's a lot more going on here than you'd expect."))
    tease_num = [
        "There's a number in this next part that I honestly didn't believe at first.",
        "Hold on to this, because the next detail is a big one.",
        "This next part is where the scale of it all becomes obvious.",
    ]
    tease_name = [
        "The next part brings in {sal} — and it changes the whole picture.",
        "Coming up, we get to {sal}, which is where things start to matter.",
        "And then there's {sal}. I'll say no more until you hear the context.",
    ]
    tease_id = [
        "Okay, this is the part I didn't expect.",
        "Which brings us to something a bit surprising.",
        "And now, the part of the story people usually miss.",
    ]
    tn = tna = ti = 0
    for i, fact in enumerate(facts):
        reader = "A" if i % 2 == 0 else "B"
        other = "B" if reader == "A" else "A"
        if i > 0:
            kind, sal = _salience(fact)
            if kind == "number":
                react = tease_num[tn % len(tease_num)]
                tn += 1
            elif kind == "name":
                react = tease_name[tna % len(tease_name)].replace("{sal}", sal)
                tna += 1
            else:
                react = tease_id[ti % len(tease_id)]
                ti += 1
            L.append((other, react))
        prefix = "So let's start from the beginning. " if i == 0 else ""
        L.append((reader, prefix + fact))
    s0 = _salience(facts[0])[1]
    sN = _salience(facts[-1])[1]
    short = topic
    if len(short.split()) > 7:
        short = " ".join(short.split()[:7]).rstrip(",;: ")
    if sN and sN not in short:
        L.append(("A", f"Here's the detail I'll leave you with: {sN}."))
    elif s0 and sN and s0 != sN and s0 not in short:
        L.append(("A", f"So, {short} — from {s0} all the way to {sN}. That's the whole arc in two lines."))
    else:
        L.append(("A", f"So, {short}. Big ideas, a big ending — that's the story in a nutshell."))
    L.append(("B", "And I think that's the takeaway. Everything else in the material is just detail."))
    L.append(("A", "Well, that's time for today. Thanks so much for listening."))
    L.append(("B", "And thanks to all of you tuning in. See you in the next one."))
    return [{"s": s, "text": t} for s, t in L]


def _auto_th(text):
    B = BRIDGES["th"]
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()] or [text.strip()]
    topic = _topic_of(text)
    L = [("A", f"ยินดีต้อนรับสู่รายการของเรา วันนี้เรามาคุยกันเรื่อง {topic}"),
         ("B", "ใช่แล้ว เรื่องนี้มีอะไรมากกว่าที่คิดเยอะ")]
    bi = ai = 0
    for i, para in enumerate(paras):
        if i > 0:
            if i % 2 == 0:
                L.append(("B", B["B"][bi % len(B["B"])]))
                bi += 1
            else:
                L.append(("A", B["A"][ai % len(B["A"])]))
                ai += 1
        L.append(("A" if i % 2 == 0 else "B", para))
    L.append(("A", B["outro"][0]))
    L.append(("B", B["outro"][1]))
    return [{"s": s, "text": t} for s, t in L]


def _auto_km(text):
    B = BRIDGES["km"]
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()] or [text.strip()]
    topic = _topic_of(text)
    L = [("A", f"សូមស្វាគមន៍មកកាន់កម្មវិធីរបស់យើង។ ថ្ងៃនេះយើងនិយាយគ្នាអំពី {topic}"),
         ("B", "បាទ រឿងនេះមានអ្វីៗច្រើនជាងដែលគិតទុក។")]
    bi = ai = 0
    for i, para in enumerate(paras):
        if i > 0:
            if i % 2 == 0:
                L.append(("B", B["B"][bi % len(B["B"])]))
                bi += 1
            else:
                L.append(("A", B["A"][ai % len(B["A"])]))
                ai += 1
        L.append(("A" if i % 2 == 0 else "B", para))
    L.append(("A", B["outro"][0]))
    L.append(("B", B["outro"][1]))
    return [{"s": s, "text": t} for s, t in L]


def auto_lines(text: str, language: str = "auto"):
    if language in ("en", "th", "km"):
        lang = language
    elif is_khmer(text):
        lang = "km"
    elif is_thai(text):
        lang = "th"
    else:
        lang = "en"
    lines = _auto_km(text) if lang == "km" else (_auto_th(text) if lang == "th" else _auto_en(text))
    return lines, lang


def parse_script_lines(text: str):
    lines = []
    pat = re.compile(r"^\s*\[?\s*(?:HOST\s+)?([AB])\s*\]?\s*[:\-–—]\s*(.+)$", re.IGNORECASE)
    for raw in (text or "").splitlines():
        m = pat.match(raw)
        if m:
            lines.append({"s": m.group(1).upper(), "text": m.group(2).strip()})
        elif raw.strip():
            lines.append({"s": "A" if len(lines) % 2 == 0 else "B", "text": raw.strip()})
    return lines


def scripts_to_text(lines):
    return "\n".join(f"HOST {l['s']}: {l['text']}" for l in lines)


def smart_script(text: str, language: str, api: dict):
    base = (api.get("baseUrl") or "https://api.openai.com/v1").rstrip("/")
    key = (api.get("key") or "").strip()
    model = (api.get("model") or "gpt-4o-mini").strip()
    if not key:
        raise ValueError("Smart mode needs an API key. Paste one, or use Auto dialogue instead.")
    lang_map = {"auto": "the same language as the source material", "en": "English", "th": "Thai"}
    lang_instruction = lang_map.get(language, lang_map["auto"])
    system = "You are a podcast script writer. You turn source material into a natural, engaging conversation between two hosts."
    user = f"""Write a two-host podcast conversation about the source material below.

Rules:
- Output ONLY conversation lines. Every line MUST start with "HOST A: " or "HOST B: ". No other text.
- Alternate speakers; never the same host twice in a row.
- 18 to 30 lines; each line at most 2 short sentences.
- Write in {lang_instruction}.
- Be conversational: ask questions, react, add light humor. Do not sound like a news broadcast.
- Use only facts from the source material. Never mention "the source", "the document", or being an AI.
- Start with a short welcome from HOST A, end with a short sign-off from HOST B.

SOURCE MATERIAL:
{(text or "").strip()[:12000]}"""
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "temperature": 0.9,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        ).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.load(r)
    except Exception as e:
        raise RuntimeError(f"LLM request failed: {e}")
    content = data["choices"][0]["message"]["content"]
    lines = parse_script_lines(content)
    if len(lines) < 2:
        raise RuntimeError("The model did not return a valid script. Try again, or use Auto dialogue.")
    return lines

# -------------------------------------------------------- job status --------

STATUS = {}
STATUS_LOCK = threading.Lock()


_JOBS_PATH = os.path.join(CACHE_DIR, ".job_state.json")
_JOBS_LOCK = threading.Lock()
_JOBS = {"pending": {}, "keep": {}}   # pending = still to do, keep = Continue-able
_QUEUE_ORDER = []                # waiting keys, in submission order (display)
_CANCEL = set()
_STALL_S = 420.0                 # no progress for 7 min = stalled


def _jobs_write():
    """Atomic, throttled snapshot of the unfinished jobs."""
    try:
        with _JOBS_LOCK:
            data = {"v": 1, "t": time.time(),
                    "pending": {k: {"args": v.get("args"), "t": v.get("t")}
                                for k, v in _JOBS["pending"].items()}}
        tmp = _JOBS_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, _JOBS_PATH)
    except Exception as e:
        print("[jobs] could not save the job list: %s" % str(e)[:120], flush=True)


def _jobs_finish(key, state="done"):
    """Done -> forget it. Stopped/failed -> keep the plan so Continue works
    (kept in memory only, so a restart never resumes a job on its own)."""
    with _JOBS_LOCK:
        hit = _JOBS["pending"].pop(key, None)
        if hit is not None and state in ("error", "stopped"):
            _JOBS["keep"][key] = hit
    if state == "done":
        try:
            os.remove(os.path.join(CACHE_DIR, key + ".args.json"))
        except OSError:
            pass
    if hit is not None or state in ("done", "error"):
        _jobs_write()


def _args_path(key):
    return os.path.join(CACHE_DIR, key + ".args.json")


def _args_save(key, args):
    try:
        with open(_args_path(key), "w", encoding="utf-8") as f:
            json.dump(list(args), f, ensure_ascii=False)
    except Exception as e:
        print("[jobs] could not store the plan for %s: %s" % (key, str(e)[:80]),
              flush=True)


def _jobs_load():
    try:
        with open(_JOBS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _enqueue(key, args, note=""):
    with _JOBS_LOCK:
        _JOBS["pending"][key] = {"args": list(args), "t": time.time()}
        if key not in _QUEUE_ORDER:
            _QUEUE_ORDER.append(key)
        pos = _QUEUE_ORDER.index(key) + 1
    _jobs_write()
    _args_save(key, args)
    _status(key, ("queued (#%d in line)" % pos) + (" " + note if note else ""),
            0, 0, state="working")
    _CANCEL.discard(key)
    JOB_QUEUE.put((key, list(args)))


def _jobs_restore():
    """After a studio restart: pick up the episodes that were still running."""
    data = _jobs_load()
    pend = (data or {}).get("pending") or {}
    n = 0
    for key, rec in pend.items():
        args = (rec or {}).get("args")
        if not args:
            continue
        try:
            _status(key, "resumed automatically after a restart", 0, 0,
                    state="working")
            _enqueue(key, args, note="— resumed after a restart")
            n += 1
        except Exception as e:
            print("[jobs] could not resume %s: %s" % (key, str(e)[:100]), flush=True)
    if n:
        print("[jobs] %d unfinished episode(s) resumed automatically" % n, flush=True)
    return n


def _queue_positions():
    """Refresh "queued (#n in line)" for everything still waiting."""
    try:
        with _JOBS_LOCK:
            order = list(_QUEUE_ORDER)
        for i, k in enumerate(order):
            with STATUS_LOCK:
                rec = STATUS.get(k)
                live = bool(rec) and rec.get("state") == "working"
                started = bool(rec) and (rec.get("done") or rec.get("total"))
            if live and not started:
                _status(k, "queued (#%d in line)" % (i + 1), 0, 0)
    except Exception:
        pass


def _status(key: str, stage: str, done=None, total=None, state=None, error=None, duration=None, degraded=None, note=None, detail=None, words=None):
    with STATUS_LOCK:
        now = time.time()
        # only FINISHED records age out, and only after 6 hours. A queued or
        # running job must never vanish from under the browser: that is what
        # made an episode sit at "queued · 0 %" for ten minutes.
        for k in [k for k, v in STATUS.items()
                  if now - v.get("t", now) > 6 * 3600
                  and v.get("state") in ("done", "error", "stopped")]:
            STATUS.pop(k, None)
        rec = STATUS.get(key, {})
        STATUS[key] = {
            "state": state or rec.get("state", "working"),
            "stage": stage,
            "done": done if done is not None else rec.get("done", 0),
            "total": total if total is not None else rec.get("total", 0),
            "duration": duration if duration is not None else rec.get("duration"),
            "error": error if error is not None else rec.get("error"),
            "degraded": bool(degraded if degraded is not None else rec.get("degraded", False)),
            "note": note if note is not None else rec.get("note"),
            "detail": detail if detail is not None else rec.get("detail"),
            "words": words if words is not None else rec.get("words", 0),
            "t": now,
            "beat": now,          # the progress watchdog reads this
        }
        _RUNNER["beat"] = now
        if state in ("done", "error", "stopped"):
            _jobs_finish(key, state)

# -------------------------------------------------------------- produce -----

# Professional rhythm per narration style. `ramp` = speech-rate multipliers
# (start, end) across the episode; `emph` = extra pause on exclamations;
# `para` = breath at paragraph/line ends. Layered on top of the user's
# speed/pause sliders — each style sounds unmistakably its own thing.
# Narration styles now come from the performance engine (narration.py), which
# carries the full delivery specification for every style. STYLE_RULES stays as
# a compatibility view (ramp/emph/para) for the few places that still read it.
DEBUG_PERFORMANCE = os.environ.get("SONORA_DEBUG_PERFORMANCE", "") not in ("", "0")

STYLE_RULES = {
    sid: dict(ramp=s["pace"], emph=s["pauses"]["exclaim"],
              para=s["pauses"]["para"])
    for sid, s in NAR.STYLE_SPECS.items()
}
for _sid, _al in NAR.STYLE_ALIASES.items():          # accept old spellings too
    STYLE_RULES.setdefault(_al.replace(" ", "_"), STYLE_RULES[_al])

def _gap_for(boundary, speaker_change, pause, rule):
    """Punctuation-aware dramatic pause (seconds) before the next unit."""
    if speaker_change:
        return max(0.45, pause * 1.6)  # host hand-offs keep their fixed beat
    if pause <= 0:
        return 0.0
    if boundary == "!":
        return pause * rule["emph"]
    if boundary == "?":
        return pause * min(1.25, max(1.0, rule["emph"]))
    if boundary == "…":
        return pause * 1.4
    if boundary == "para":
        return pause * rule["para"]
    return pause  # "."

def _hd_cleanup_clone(key, master_path, plan_text, rvc_on, words_done=0, ffmpeg=None,
                      plan_n=0):
    """HD Cleanup for one finished job: returns (note, state).

    The tool belongs to the RVC VOICE CLONE path and it is Khmer only (§2). It
    runs ONCE, on the audio the clone just produced — the “original TTS” from the
    engine’s point of view — and it never chains (§19). The original clone audio
    is copied aside before anything is replaced (§16), the enhanced file is
    written next to it as `enhanced_hd.wav`, and only a success lets it become
    what the episode exports. A failure leaves the original in place and says so
    (§24). Everything the browser needs (the two previews, the score, the kept
    original) is returned in the state, and stored in HD_STATE for the status
    endpoint.
    """
    if not rvc_on:
        return (" HD Cleanup belongs to the RVC VOICE CLONE — skipped on this job.", None)
    try:
        ok, why = HDC.khmer_only_ok(plan_text, "auto")
    except Exception as e:
        ok, why = False, "the Khmer check failed (%s)" % type(e).__name__
    if not ok:
        print(f"[hd] {key}: skipped ({why})", flush=True)
        return (" HD Cleanup is Khmer only — skipped (%s)." % why, None)

    _status(key, "HD Cleanup: analysing the cloned voice…", plan_n, plan_n,
            words=words_done)
    original_keep = os.path.join(CACHE_DIR, key + ".original.wav")
    hd_out = os.path.join(CACHE_DIR, key + ".enhanced_hd.wav")
    prev_dir = os.path.join(CACHE_DIR, key + ".hd_preview")
    log = []
    try:
        rep = HDC.enhance_keep_original(master_path, hd_out, original_keep, log=log,
                                        ffmpeg=ffmpeg or FFMPEG, preview_dir=prev_dir)
    except Exception as e:
        rep = {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "note": HD_NOTE_FAIL}
    if rep.get("ok") and os.path.exists(hd_out) and os.path.getsize(hd_out) > 44:
        os.replace(hd_out, master_path)          # the HD file becomes the episode
        state = {
            "ok": True,
            "score_before": rep.get("score_before"),
            "score_after": rep.get("score_after"),
            "stages": rep.get("stages") or [],
            "original": os.path.basename(original_keep),
            "hd": "enhanced_hd.wav",
            "previews": {k: ("/hd-preview/%s/%s" % (key, os.path.basename(v)))
                         for k, v in (rep.get("previews") or {}).items()
                         if isinstance(v, str)},
            "sr": (rep.get("out") or {}).get("sr"),
            "bits": (rep.get("out") or {}).get("bits"),
            "lufs": (rep.get("out") or {}).get("lufs"),
            "true_peak_db": (rep.get("analysis_after") or {}).get("true_peak_db"),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        note = (" HD Cleanup: score %s → %s · %s."
                % (rep.get("score_before"), rep.get("score_after"),
                   "; ".join(rep.get("stages") or []) or "the clone was already clean"))
        print(f"[hd] {key}:{note} ({len(log)} steps)", flush=True)
    else:
        state = {"ok": False, "error": rep.get("error"),
                 "note": rep.get("note") or HD_NOTE_FAIL,   # the exact sentence, in the UI too
                 "time": time.strftime("%Y-%m-%d %H:%M:%S")}
        note = " " + (rep.get("note") or HD_NOTE_FAIL)
        print(f"[hd] {key}: FAILED -> {rep.get('error')}", flush=True)
    if state:
        HD_STATE[key] = state
    return note, state


def produce(key: str, lines, voices, speed: float, pause: float,
            bed: str, bed_level: float, fmt: str, style: str = "natural",
            bed_file: str = None, bed_speed: float = 1.0,
            rvc_cfg=None, clean: bool = False, hd: bool = False):
    """Two-pass streaming pipeline — works at any length (1h, 2h, 4h+).

    Pass 1: synthesize each unit and stream its PCM to a temp raw file,
            tracking the global peak.
    Pass 2: read the raw file in 1-minute chunks, peak-normalize, mix the
            studio bed (continuous across chunks), and write the final WAV.

    Memory stays flat (one minute of audio at a time) regardless of length.
    """
    speed = min(1.5, max(0.5, speed))
    pause = min(2.0, max(0.0, pause))
    bed_level = min(1.0, max(0.0, bed_level))
    rule = STYLE_RULES.get(style) or STYLE_RULES["natural"]
    gap_line = int(max(0.45, pause * 1.6) * SR)

    all_units = []  # (speaker, unit_text, boundary)
    for line in lines:
        spk = (line.get("s") or "S").upper()
        raw = line.get("text", "")
        # LAYER 1+2 BEFORE SPLITTING. "គ.ស. ១៣២៧" must reach the dictionary as
        # ONE word: split first and the abbreviation becomes "គ." + "ស." and the
        # number stays a bare digit — exactly what the frontend exists to stop.
        # marks first, then the language layer (Khmer keeps its own dash rule
        # so that ២០២០–២០២៣ still reads as "… ដល់ …")
        _kh = is_khmer(raw)
        norm = _manuscript_clean(raw, keep_dashes=_kh)
        norm = _tts_safe_text(norm) if _kh else norm
        for u, bnd in sentence_units(norm):
            all_units.append((spk, u, bnd))
    # a unit with nothing to say can only fail at the engine: drop it here
    all_units = [(spk, u, bnd) for spk, u, bnd in all_units
                 if re.search(r"[^\W_]", u or "", re.UNICODE)]
    if not all_units:
        raise ValueError("Nothing to narrate — that text has no readable words "
                         "(only symbols, punctuation or emoji?). Paste the script "
                         "and press Generate again.")
    if len(all_units) > MAX_UNITS:
        raise ValueError(f"Episode extremely long ({len(all_units)} units, max {MAX_UNITS}). For very large books, split it into volumes.")
    if sum(len(t) for _, t, _ in all_units) > MAX_CHARS:
        raise ValueError("Text too long for one pass — please split it into volumes.")

    # ---- the performance plan -------------------------------------------------
    # Not a label change: every sentence gets emotion, intensity, pace, pitch,
    # loudness, pause length, emphasis and (where it belongs) a breath — from
    # the style specification in narration.py.
    plan = NAR.plan(all_units, style=style, speed=speed, pause=pause)
    if not plan:
        raise ValueError("Nothing to narrate")
    n = len(plan)
    if DEBUG_PERFORMANCE:
        print(f"[style] {NAR.spec(style)['label']} — {n} sentences\n"
              + NAR.plan_summary(plan), flush=True)

    raw_path = os.path.join(CACHE_DIR, key + ".raw")
    master_path = os.path.join(CACHE_DIR, key + ".master")  # 24 kHz/16-bit mono working file
    degraded = False  # True if any line needed the backup/Google engine

    # ---- Pass 1: synthesize (4 units in parallel — ~4x faster) + stream raw PCM ----
    vpeak = 0.0
    total_samples = 0
    done = 0
    skipped = []  # (index, preview) — lines that could not be voiced at all
    unit_words = [max(1, int(round(p["words"]))) for p in plan]
    words_done = 0

    # lines with nothing a voice can read (symbols, emoji, stray punctuation)
    # never reach an engine: they would fail on every provider and be reported
    # as an outage. They are skipped, named, and the job carries on.
    unreadable = [i for i, item in enumerate(plan) if not _speakable(item["text"])]
    if len(unreadable) == len(plan):
        raise ValueError("Nothing to narrate — the text has no readable words "
                         "(only symbols or punctuation?). Paste the actual script.")

    rvc_on = bool(rvc_cfg) and any(v == RVC_VOICE_ID for v in voices.values())

    def _perform(arr, pitch_st, gain_db, engine_of="", rate=1.0):
        """Everything the plan asks for that the engine did not do itself:
        pace (time-stretch), a large pitch shift, and per-sentence loudness.
        Returns the performed float array."""
        if arr.size == 0:
            return arr
        if engine_of != "edge" and abs(rate - 1.0) >= 0.02:
            arr = _tempo_f32(arr, rate)          # local/google engines
        if engine_of != "edge" and abs(pitch_st) >= 1.0:
            # formant-shifting shift (asetrate + atempo back to length) —
            # used only when the style asks for a real register change
            semis = max(-4.0, min(4.0, pitch_st))
            factor = 2.0 ** (semis / 12.0)
            arr = _pitch_f32(arr, factor)
        if abs(gain_db) >= 0.05:
            arr = arr * (10.0 ** (gain_db / 20.0))
        return arr

    def _whisper_stage(arr, item, idx=0):
        """Does nothing — the whisper stage is removed (build 2026-09-30n).

        This used to whisper every line the planner marked: in practice one
        line every few sentences in the cinematic and thriller reads, and (with
        an intimacy cue in the text) in others. A whispered line is written as a
        breath carrying the words — a different sound from the voice that was
        speaking — so mid-read it stopped being that voice. The user heard it as
        the whisper arriving loudly and replacing the normal reading.

        Nothing whispers now. The function stays because the render loop calls
        it, and it returns the line untouched: the voice you hear is the voice
        the clone produced, from the first line to the last.
        """
        return arr

    def _save_clone_cache(ckey, rate, ut, f32):
        """Write the clone unit's mp3 cache in the background.

        This used to be a blocking ffmpeg encode per sentence. The audio
        itself does not wait for it — it goes straight into the episode — so
        the encode now runs on a small pool while the next lines are made.
        """
        def work():
            try:
                with tempfile.TemporaryDirectory() as td:
                    wp = os.path.join(td, "u.wav")
                    with open(wp, "wb") as f:
                        f.write(f32_to_wav_bytes(f32))
                    mp2 = os.path.join(td, "u.mp3")
                    wav_to_mp3(wp, mp2, kbps=128)
                    with open(mp2, "rb") as f:
                        data = f.read()
                _save_unit(ckey, rate, ut, data, engine="edge")
            except Exception:
                pass
        CACHE_POOL.submit(work)

    def prepare_unit(spk, u, rate, pitch_st=0.0, gain_db=0.0, whisper=False):
        """Stage 1 for one line — everything EXCEPT the clone pass.

        Returns one of:
          {"kind": "ready", "arr": f32, "engine": str}
              finished line, ready to be written to the episode
          {"kind": "rvc", "base": f32, ...}
              the carrier's audio; it still has to go through the RVC model,
              and that happens in ONE batch for the whole group.
        """
        voice = voices.get(spk) or voices.get("S") or "en-US-AvaNeural"
        ut = _tts_safe_text(u)
        if rvc_on and voice == RVC_VOICE_ID:
            base_voice = rvc_cfg.get("carrier") or "km-KH-SreymomNeural"
            do_conv = rvc_cfg.get("scope") == "all" or is_khmer(ut)
            if do_conv:
                # cache key carries the clone params + base voice, so a pitch
                # or index-rate change never reuses a stale converted unit
                ckey = (f"{RVC_VOICE_ID}#{rvc_cfg.get('pitch')}#"
                        f"{rvc_cfg.get('indexRate')}#{rvc_cfg.get('protect')}#"
                        f"{rvc_cfg.get('f0Method')}#{base_voice}")
            else:
                ckey = base_voice  # out-of-scope line: plain carrier, shared cache
        else:
            base_voice, ckey, do_conv = voice, voice, False
        # the performance is part of the cache identity: a different style,
        # pitch or loudness must never reuse another style's audio
        ckey = (f"{ckey}#{style}@{pitch_st:+.1f}st{gain_db:+.1f}dB"
                + ("~w" if whisper else ""))
        cached = _cached_unit(ckey, rate, ut)
        if cached is not None:
            c_mp3, c_engine = cached
            # `c_engine`, not "cache": the pace/loudness the engine already did
            # must not be applied a second time
            return {"kind": "ready", "engine": "cache",
                    "arr": _perform(mp3_to_f32(c_mp3), pitch_st, gain_db,
                                    engine_of=c_engine, rate=rate)}
        mp3, engine = asyncio.run(
            synth_unit_mp3(ut, base_voice, NAR.rate_percent(rate),
                           NAR.st_to_hz(pitch_st)))
        if do_conv:
            return {"kind": "rvc", "base": mp3_to_f32(mp3), "ckey": ckey,
                    "ut": ut, "rate": rate, "gain_db": gain_db}
        _save_unit(ckey, rate, ut, mp3, engine=engine)
        # engine_of=engine: edge already applied the rate and the pitch, the
        # local engines did not — the bug here doubled edge's rate (0.96 -> 0.92)
        return {"kind": "ready", "engine": engine,
                "arr": _perform(mp3_to_f32(mp3), pitch_st, gain_db,
                                engine_of=engine, rate=rate)}

    def finish_rvc(converted, prep):
        """Stage 2 for one clone line: the batch pass returned its audio.
        Perform + cache exactly as the one-line-at-a-time path used to."""
        _save_clone_cache(prep["ckey"], prep["rate"], prep["ut"], converted)
        return (_perform(converted, 0.0, prep["gain_db"],
                         engine_of="edge", rate=prep["rate"]), "rvc")

    def make_unit(spk, u, rate, pitch_st=0.0, gain_db=0.0, whisper=False):
        """(f32, engine) for ONE line, the old way — used only by the rescue
        path for a single line that the batch could not handle."""
        prep = prepare_unit(spk, u, rate, pitch_st, gain_db, whisper)
        if prep["kind"] == "ready":
            return prep["arr"], prep["engine"]
        f32 = _rvc_convert_f32(prep["base"], rvc_cfg)
        return finish_rvc(f32, prep)

    def prepare_one(i, item):
        """One sentence. A provider that throttles a PARALLEL burst can still
        answer the same text on its own a moment later, so a failed unit is
        retried twice sequentially (0.8 s, 2.2 s) before it is declared bad."""
        last = None
        for attempt, wait in enumerate((0.0, 0.8, 2.2)):
            if wait:
                time.sleep(wait)
            try:
                return i, prepare_unit(item["speaker"], item["text"], item["rate"],
                                       item["pitch_st"], item["gain_db"],
                                       bool(item.get("whisper")))
            except Exception as e:                      # retryable provider error
                last = e
                if _definitive_block(e):
                    break
                if attempt < 2:
                    print("[tts] unit %d failed (%s) — retrying on its own"
                          % (i + 1, str(e)[:70]), flush=True)
        raise last

    pending = []            # [(index, prep)] waiting for the next clone pass
    pending_secs = 0.0
    next_i = 0              # first line not yet written into the raw stream

    def write_ready():
        """Write every line that is finished, in order. Lines that are still
        waiting for the clone simply hold the cursor until they arrive."""
        nonlocal next_i, vpeak, total_samples, degraded
        while next_i < len(plan) and next_i in res:
            i = next_i
            arr, engine = res.pop(i)
            if engine not in ("edge", "rvc", "cache", "skipped"):
                degraded = True
            next_i += 1
            if i > 0:
                prev, cur = plan[i - 1], plan[i]
                if cur["speaker"] != prev["speaker"]:
                    gap_s = max(0.45, pause * 1.6)   # host hand-offs keep their beat
                else:
                    gap_s = prev["pause_s"]          # the plan's pause
                # REMOVED (build 2026-09-30o): the pause used to carry a
                # synthesised breath here — a soft filtered-noise inhale in
                # every few sentence gaps, which is what the user heard as a
                # whisper arriving ~10-15 times in a five-minute read. The
                # pause is now exact silence, exactly like the style demo
                # clips. Pace, pauses and delivery are untouched.
                gap = np.zeros(int(gap_s * SR), dtype=np.float32)
                raw.write(f32_to_i16_bytes(gap)); total_samples += gap.size
            pre_ms = int(plan[i].get("pre_pause_ms") or 0)
            if pre_ms > 0:
                pre = np.zeros(int(pre_ms / 1000.0 * SR), dtype=np.float32)
                raw.write(f32_to_i16_bytes(pre)); total_samples += pre.size
            arr = _whisper_stage(arr, plan[i], i)
            vpeak = max(vpeak, float(np.max(np.abs(arr))))
            raw.write(f32_to_i16_bytes(arr))
            total_samples += arr.size

    def clone_pass(final=False):
        _check_cancel(key)
        """Convert the queue through the model in one pass, biggest first-fit
        window that fits the caps; `final` forces the pass even when small."""
        nonlocal pending, pending_secs
        if not pending:
            return
        take, acc = 0, 0.0
        for _i, prep in pending:
            s_len = prep["base"].size / float(SR)
            if take and (take >= RVC_BATCH_UNITS or acc + s_len > RVC_BATCH_SECS):
                break
            take += 1
            acc += s_len
        full = (take >= RVC_BATCH_UNITS) or (acc >= RVC_BATCH_SECS
                                             or acc >= RVC_BATCH_SECS * 0.75)
        if not full and not final:
            return                       # wait: the next group will add more
        chunk, pending = pending[:take], pending[take:]
        pending_secs = sum(p["base"].size / float(SR) for _i, p in pending)
        _status(key, f"clone voice: {len(chunk)} line(s) in one pass…",
                done, len(plan), words=words_done)
        try:
            outs = _rvc_convert_f32_batch([p["base"] for _i, p in chunk], rvc_cfg)
        except Exception as e:
            # A clone job runs for hours; the worker is a separate process and
            # can die on a long job. Bring it back and continue — this is the
            # one failure that used to end a Khmer episode (English jobs do not
            # go through the clone, which is why they never failed this way).
            print("[rvc] pass failed (%s) — restarting the clone worker and "
                  "continuing" % str(e)[:120], flush=True)
            try:
                _p = RVC_STATE.get("proc")
                if _p and _p.poll() is None:
                    _p.kill()
            except Exception:
                pass
            ok_w, why = _rvc_ensure_worker(rvc_cfg)
            if ok_w:
                _status(key, "clone voice restarted — continuing…",
                        done, len(plan), words=words_done)
                try:
                    outs = _rvc_convert_f32_batch([p["base"] for _i, p in chunk],
                                                  rvc_cfg)
                except Exception as e2:
                    failures.extend([(i, e2) for i, _p in chunk])
                    return
            else:
                failures.extend([(i, e) for i, _p in chunk])
                print("[rvc] could not restart the clone worker: %s" % why, flush=True)
                return
        for (i, prep), conv in zip(chunk, outs):
            try:
                res[i] = finish_rvc(conv, prep)
            except Exception as e:
                failures.append((i, e))

    with open(raw_path, "wb") as raw:
        width = SYNTH_WORKERS          # narrows when the provider resists
        for start in range(0, len(plan), width):
            _check_cancel(key)
            grp = list(enumerate(plan[start:start + width], start=start))
            res = {}
            failures = []
            for i, item in list(grp):
                if i in unreadable:
                    grp.remove((i, item))
                    skipped.append((i, (item["text"] or "")[:60]))
                    res[i] = (np.zeros(int(0.5 * SR), dtype=np.float32), "skipped")
                    done += 1
                    words_done += unit_words[i]
                    _status(key, f"voice {done}/{len(plan)} "
                                 f"({len(skipped)} line(s) with nothing to read)",
                            done, len(plan), words=words_done)
            preps = {}
            # a throttled provider is asked for fewer lines at a time
            with ThreadPoolExecutor(max_workers=max(1, len(grp))) as ex:
                futs = {ex.submit(prepare_one, i, item): i for i, item in grp}
                for fut in as_completed(futs):
                    i = futs[fut]
                    try:
                        _, prep = fut.result()
                        preps[i] = prep
                        if prep["kind"] == "ready":
                            res[i] = (prep["arr"], prep["engine"])
                            done += 1
                            words_done += unit_words[i]
                            _status(key, f"voice {done}/{len(plan)}" + _eta_note(
                                len(plan), done), done, len(plan), words=words_done)
                    except Exception as e:
                        failures.append((i, e))

            # ---- clone queue ------------------------------------------------
            # Lines waiting for the clone are queued and converted in ONE pass
            # once the queue is worth a pass (12 lines / 30 s of audio). The
            # queue fills ACROSS groups, so a Khmer chapter becomes a handful
            # of big GPU passes instead of one pass per sentence — and the
            # writer below simply waits for the lines it needs.
            for i in sorted(preps):
                if preps[i]["kind"] == "rvc":
                    pending.append((i, preps[i]))
                    pending_secs += preps[i]["base"].size / float(SR)
            # this group had no clone lines at all: nothing more is coming
            # right now, so do not sit on the queue
            group_had_rvc = any(preps[i]["kind"] == "rvc" for i in preps)
            if pending and not group_had_rvc:
                clone_pass(final=True)
            else:
                clone_pass()
            write_ready()
            probe_voice = (voices.get(plan[grp[0][0]]["speaker"]) if grp else None) \
                or voices.get("S") or "km-KH-SreymomNeural"
            # --- burst control -------------------------------------------------
            if failures:
                SERVICE_STATE["burst_fail_streak"] = \
                    SERVICE_STATE.get("burst_fail_streak", 0) + len(failures)
                if len(failures) >= len(grp) and len(grp) > 1:
                    width = max(SYNTH_WORKERS_MIN, width // 2)
                    print("[tts] that whole group failed — going down to %d "
                          "line(s) at a time" % width, flush=True)
            else:
                SERVICE_STATE["burst_fail_streak"] = 0
                if _EDGE_PACE["interval"] > 0 and done % 300 < width:
                    _edge_pace_set(0.0)          # pressure gone: full speed
                if width < SYNTH_WORKERS and done % 200 < width:
                    width = min(SYNTH_WORKERS, width * 2)
                    print("[tts] provider is steady again — back to %d line(s) "
                          "at a time" % width, flush=True)
            if SERVICE_STATE.get("burst_fail_streak", 0) >= BURST_FAIL_LIMIT:
                alive = _burst_protection(probe_voice)
                if not alive:
                    raise VoiceServiceDown(
                        "the voice service stopped answering after "
                        "%d units (%d of %d lines are already saved)"
                        % (SERVICE_STATE["burst_fail_streak"], done, len(plan)))
            if failures and len(grp) and len(failures) == len(grp):
                # A whole batch failed. Two very different causes:
                #   * the provider is down / throttled  -> fail fast, retry later
                #   * these particular lines are the problem (nothing readable in
                #     them, a provider filter on that text) -> skip them instead
                #     of telling the user the service is down.
                if _edge_probe(probe_voice, tries=2):
                    print(f"[tts] the provider answered a plain probe, so these "
                          f"{len(failures)} line(s) are the problem — skipping them",
                          flush=True)
                    for i, e in failures:
                        skipped.append((i, (plan[i]["text"] or "")[:60]))
                        res[i] = (np.zeros(int(0.5 * SR), dtype=np.float32), "skipped")
                        done += 1
                        words_done += unit_words[i]
                        _status(key, f"voice {done}/{len(plan)} "
                                     f"({len(skipped)} line(s) could not be read)",
                                done, len(plan), words=words_done)
                    failures = []
                else:
                    raise VoiceServiceDown(" | ".join(str(e)[:250]
                                                      for _, e in failures[:2]))
            for i, e in failures:
                # A down voice service (incl. the RVC worker) raises
                # VoiceServiceDown — fail the job for the auto-retry rather
                # than silently skipping the line. BUT: before blaming the
                # service, ask it to say one trivial word. If it can, then the
                # service is fine and THIS line is the problem (nothing
                # readable in it, or a provider filter on that text) — skip the
                # line and keep the episode.
                if isinstance(e, VoiceServiceDown):
                    if _is_rvc_error(e):
                        # the clone layer broke (worker died, model missing…):
                        # the TTS provider being fine says nothing about it —
                        # never answer this by skipping the line
                        raise e
                    if _edge_probe(probe_voice, tries=2):
                        print(f"[tts] provider is answering, so line {i+1} is the "
                              f"problem — skipping it, the rest of the episode "
                              f"continues", flush=True)
                        skipped.append((i, (plan[i]["text"] or "")[:60]))
                        res[i] = (np.zeros(int(0.5 * SR), dtype=np.float32), "skipped")
                        done += 1
                        words_done += unit_words[i]
                        _status(key, f"voice {done}/{len(plan)} "
                                     f"({len(skipped)} line(s) could not be read)",
                                done, len(plan), words=words_done)
                        continue
                    raise e
                # ONE line failed every engine. Rescue it so it cannot kill the job:
                # try a sanitized version of the text, then skip it with a 0.5s pause.
                item = plan[i]
                spk, u = item["speaker"], item["text"]
                if _tts_safe_text(u) != u:
                    try:
                        res[i] = make_unit(spk, u, item["rate"],
                                           item["pitch_st"], item["gain_db"],
                                           bool(item.get("whisper")))
                        done += 1
                        words_done += unit_words[i]
                        _status(key, f"voice {done}/{len(plan)}", done, len(plan), words=words_done)
                        continue
                    except VoiceServiceDown:
                        raise
                    except Exception:
                        pass
                skipped.append((i, (u or "")[:60]))
                res[i] = (np.zeros(int(0.5 * SR), dtype=np.float32), "skipped")
                done += 1
                words_done += unit_words[i]
                _status(key, f"voice {done}/{len(plan)} (1 line skipped)", done, len(plan), words=words_done)
        # anything still queued: one last pass, then flush the tail
        clone_pass(final=True)
        write_ready()

    if failures:
        # clone failures during the final flush never went through the
        # per-group handler — a broken clone must fail the job, never be
        # answered with silence
        for _i, e in failures:
            if isinstance(e, VoiceServiceDown):
                raise e
        raise VoiceServiceDown(" | ".join(str(e)[:250] for _i, e in failures[:2]))

    if total_samples == 0:
        raise ValueError("No audio was produced")

    # ---- Pass 2: normalize + bed + final WAV, 1-minute chunks ----
    scale = (0.85 / (vpeak + 1e-9)) if vpeak > 0.01 else 1.0
    has_music = bool(bed_file)
    bed_on = bed_level > 0 and (bed not in ("none", "") or has_music)
    gain = bed_level * (0.40 if has_music else 0.5)
    total_secs = total_samples / SR
    carry = 0.0
    seed = 1234567
    chunk_samples = BATCH
    chunk_bytes = BATCH * 2

    # Uploaded music bed: decode once (cached) and stream it, looped, across the
    # whole episode. This runs while the user watches, so keep it transparent.
    bed_reader = None
    if bed_on and has_music:
        _status(key, "preparing your music bed…", len(plan), len(plan), words=words_done)
        bed_reader = BedLoopReader(_bed_raw(bed_file, bed_speed), total_samples)

    # Placeholder 44-byte WAV header (sizes patched at the end)
    placeholder = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 0, b"WAVE", b"fmt ", 16, 1, 1, SR, SR * 2, 2, 16, b"data", 0,
    )

    _status(key, "mixing music bed…" if has_music else ("mixing studio bed…" if bed_on else "finalizing audio…"), len(plan), len(plan), words=words_done)
    with open(raw_path, "rb") as raw, open(master_path, "wb") as wav:
        wav.write(placeholder)
        written = 0
        while True:
            b = raw.read(chunk_bytes)
            if not b:
                break
            x = np.frombuffer(b, dtype="<i2").astype(np.float32) / 32767.0
            x = x * scale
            if bed_on:
                if bed_reader is not None:
                    b_chunk = bed_reader.read(x.size)
                else:
                    b_chunk, carry = gen_bed(bed, x.size, written / SR,
                                             seed + written // BATCH, total_secs, carry)
                x = np.clip(x + b_chunk * gain, -1.0, 1.0)
            wav.write(f32_to_i16_bytes(x))
            written += x.size
    os.remove(raw_path)
    if bed_reader is not None:
        bed_reader.close()

    # Patch the master WAV header sizes now that we know the exact total
    data_bytes = total_samples * 2
    with open(master_path, "r+b") as f:
        f.seek(4)
        f.write(struct.pack("<I", 36 + data_bytes))
        f.seek(40)
        f.write(struct.pack("<I", data_bytes))

    clean_note = ""
    if clean:
        _status(key, "clean & clear: denoise + 48 kHz master…",
                len(plan), len(plan), words=words_done)
        cleaned = master_path + ".clean.wav"
        try:
            rep = E.enhance_file(
                master_path, cleaned, tier="auto", ffmpeg=FFMPEG,
                lufs=CLEAN_DEFAULTS["lufs"], peak=CLEAN_DEFAULTS["peak"],
                sr=CLEAN_DEFAULTS["sr"], denoise=True, eq=True,
                deess=CLEAN_DEFAULTS["deess"], super_res=True,
                base=CLEAN_CKPT)     # neural weights -> checkpoints/
            # Sonora may run on a plain system python (no torch): if this
            # process could only do the ffmpeg tier, try the engine python.
            if (not rep.get("ok")) or rep.get("backend") == "ffmpeg":
                ext = _clean_with_engine_python(master_path, cleaned,
                                                _rvc_dir_current())
                if ext and ext.get("ok"):
                    rep = ext
                    print(f"[clean] neural engine via {ext.get('ran_in')}",
                          flush=True)
            if rep.get("ok") and os.path.exists(cleaned)                     and os.path.getsize(cleaned) > 44:
                os.replace(cleaned, master_path)
                duration_s = wav_duration(master_path)
                if duration_s > 0:
                    total_samples = int(round(duration_s * SR))
                CLEAN_STATE["last"] = {
                    "engine": rep.get("backend"), "ok": True,
                    "ran_in": rep.get("ran_in") or sys.executable,
                    "bandwidth_extension": rep.get("bandwidth_extension"),
                    "lufs": (rep.get("out") or {}).get("lufs"),
                    "true_peak_db": (rep.get("out") or {}).get("true_peak_db"),
                    "master_sr": (rep.get("out") or {}).get("sr"),
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
                print(f"[clean] {key}: engine={rep.get('backend')} "
                      f"out={CLEAN_STATE['last']['lufs']} LUFS, "
                      f"TP {CLEAN_STATE['last']['true_peak_db']} dB", flush=True)
                _msr = int(CLEAN_STATE["last"].get("master_sr") or 0)
                _eng = str(rep.get("backend") or "engine")
                clean_note = (" Clean & Clear: " + _eng
                              + (f" · {_msr // 1000} kHz master" if _msr else "")
                              + (f" · {CLEAN_STATE['last']['lufs']} LUFS"
                                 if CLEAN_STATE["last"].get("lufs") else "")
                              + (" · true 48 kHz super-resolution"
                                 if _eng not in ("ffmpeg", "") and _msr >= 48000
                                 else ""))
            else:
                raise RuntimeError("clean master failed validation")
        except Exception as e:
            clean_note = (" Clean & Clear was skipped on this job "
                          f"({type(e).__name__}).")
            CLEAN_STATE["last"] = {"ok": False, "error": f"{type(e).__name__}: {e}",
                                   "time": time.strftime("%Y-%m-%d %H:%M:%S")}
            print(f"[clean] {key}: FAILED -> {e}", flush=True)
            try:
                if os.path.exists(cleaned):
                    os.remove(cleaned)
            except OSError:
                pass

    hd_note = ""
    if hd:
        hd_note, _hd_st = _hd_cleanup_clone(
            key, master_path, " ".join((it.get("text") or "") for it in plan)[:4000],
            rvc_on, words_done=words_done, ffmpeg=FFMPEG, plan_n=len(plan))

    _status(key, f"encoding {fmt.upper()}…" if fmt != "wav" else "mastering HD audio…", len(plan), len(plan), words=words_done)
    duration = total_samples / SR
    if fmt == "wav":
        # HD deliverable: 48 kHz / 24-bit / stereo (~2304 kbps)
        final_path = os.path.join(CACHE_DIR, key + ".wav")
        wav_to_hd(master_path, final_path)
    else:
        final_path = os.path.join(CACHE_DIR, key + ".mp3")
        wav_to_mp3(master_path, final_path)
    _evict_cache()
    if skipped:
        read_less = [sk for sk in skipped
                     if not _READABLE_RE.search(_tts_safe_text(sk[1]))]
        if read_less:
            note = (f"{len(skipped)} line(s) had nothing a voice can read "
                    f"(symbols / punctuation only) — a short pause stands in their "
                    f"place. First: “{skipped[0][1]}…”")
        else:
            note = (f"{len(skipped)} line(s) could not be voiced and were skipped "
                    f"(a short pause is in their place). First: “{skipped[0][1]}…”")
        _status(key, "done", len(plan), len(plan), note=note)
    elif clean_note:
        _status(key, "done", len(plan), len(plan),
                note=(clean_note + hd_note).strip())
    elif hd_note:
        _status(key, "done", len(plan), len(plan), note=hd_note.strip())
    return final_path, duration, degraded

# ------------------------------------------------- serial job queue --------
# Jobs run ONE AT A TIME, in submission order (the client's paste/upload
# order). This keeps multi-document queues predictable and avoids piling
# parallel pressure onto the voice providers.
JOB_QUEUE = _queue.Queue()
_RUNNER = {"beat": 0.0, "busy": False, "key": None, "alive": 0}


# The dependency step runs INSIDE the target python (enhance.resolve_dependencies
# asks it which modules are missing and installs exactly those, always with
# --no-deps so numpy/torch can never be touched).


def _resolve_deps_cmd(python, root):
    code = ("import sys; sys.path.insert(0, r'%s');"
            "import enhance as E;"
            "log = [];"
            "ok, steps = E.resolve_dependencies(log=log);"
            "[print('   ' + s, flush=True) for s in steps];"
            "sys.exit(0 if ok else 1)" % root)
    return [python, "-c", code]


def _clean_install_start(python: str, pkg: str):
    """Install a Clean & Clear engine with the RVC python, in the background.

    Deliberately defensive: checks pip + internet first, installs with
    --no-deps (so pip can never try to compile numpy 1.x or touch torch),
    installs only the support packages that are actually missing, and records
    every step's exit code + last log lines so the UI can show the real cause
    without a second click.
    """
    import threading
    log_path = os.path.join(ROOT, ".clean_install.log")
    st = {"running": True, "package": pkg, "python": python, "ok": None,
          "error": "", "tail": "", "steps": [],
          "started": time.strftime("%Y-%m-%d %H:%M:%S"), "log": "",
          "log_file": log_path, "stage": "checking the environment…"}
    CLEAN_STATE["install"] = st

    def run_step(title, cmd, timeout=3600, logf=None):
        st["stage"] = title
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=timeout)
            code = r.returncode
            out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "ignore")
        except Exception as e:
            code, out = -1, f"{type(e).__name__}: {e}"
        if logf:
            try:
                logf.write("\n=== " + title + "\n$ " + " ".join(cmd) + "\n"
                           + out + "\n")
                logf.flush()
            except Exception as le:            # logging must never kill the install
                try:
                    logf.write("\n=== " + title + "\n(log write failed: "
                               + str(le) + ")\n")
                except Exception:
                    pass
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        tail = ""
        for line in reversed(lines):
            low = line.lower()
            if ("error" in low or "no matching" in low or "could not fetch" in low
                    or "modulenotfound" in low or "failed" in low):
                tail = line
                break
        if not tail:
            tail = " | ".join(lines[-3:])
        st["steps"].append({"title": title, "cmd": " ".join(cmd),
                            "code": code, "tail": tail[:400]})
        if code != 0:
            st["tail"] = tail[:400]
        return code, out

    def work():
        try:
            with open(log_path, "w", encoding="utf-8", errors="replace") as f:
                f.write("Clean & Clear engine install\npython: " + python +
                        "\npackage: " + pkg + "\nstarted: " + st["started"] + "\n")

                # 1) pip present?
                code, out = run_step("checking pip",
                                     [python, "-m", "pip", "--version"], 120, f)
                if code != 0:
                    if "No module named pip" in out:
                        run_step("bootstrapping pip",
                                 [python, "-m", "ensurepip"], 900, f)
                    code, out = run_step("re-checking pip",
                                         [python, "-m", "pip", "--version"],
                                         120, f)
                if code != 0:
                    st.update(running=False, ok=False,
                              error="this python has no working pip — see steps")
                    return

                # 2) internet?
                net = ("import urllib.request as u;"
                       "u.urlopen('https://pypi.org/simple/', timeout=15).read(1);"
                       "print('ok')")
                code, out = run_step("checking internet access to pypi.org",
                                     [python, "-c", net], 120, f)
                if code != 0:
                    st.update(running=False, ok=False,
                              error="that python cannot reach pypi.org "
                                    "(offline / firewall / proxy) — see steps")
                    return

                # 3) the engine itself (--no-deps: never touches numpy/torch)
                code, out = run_step("installing " + pkg,
                                     [python, "-m", "pip", "install",
                                      "--no-deps", pkg], 3600, f)
                if code != 0:
                    st.update(running=False, ok=False,
                              error="pip failed while installing " + pkg +
                                    " — see steps")
                    return

                # 4) dependencies — the target python reports what it lacks
                if pkg == "clearvoice":
                    code, out = run_step(
                        "resolving dependencies (the RVC python lists them)",
                        _resolve_deps_cmd(python, ROOT), 3600, f)
                    if code != 0:
                        st.update(running=False, ok=False,
                                  error="could not satisfy all dependencies — "
                                        "the last step above names the module "
                                        "that failed")
                        return

                # 5) import check
                mod = "clearvoice" if pkg == "clearvoice" else "df"
                code, out = run_step("verifying the import",
                                     [python, "-c", "import " + mod + "; print('ok')"],
                                     600, f)
                if code != 0:
                    st.update(running=False, ok=False,
                              error=pkg + " installed but does not import — see steps")
                    return

                # 6) fetch the neural weights now so the first job is fast
                if pkg == "clearvoice":
                    st["stage"] = "downloading neural weights (one time, ~220 MB)…"
                    run_step("downloading neural weights",
                             [python, "-c",
                              "import sys; sys.path.insert(0, r'%s');"
                              "import enhance as E;"
                              "E.ensure_cv_models(r'%s', True, [])" % (CLEAN_CKPT, ROOT)],
                             3000, f)

                st.update(running=False, ok=True, error="", stage="done")
                print("[clean] install " + pkg + ": OK", flush=True)
        except Exception as e:
            st.update(running=False, ok=False,
                      error=type(e).__name__ + ": " + str(e))
        finally:
            try:
                with open(log_path, "rb") as f:
                    st["log"] = f.read().decode("utf-8", "ignore")[-4000:]
            except Exception:
                pass

    threading.Thread(target=work, daemon=True).start()


def _rvc_dir_current():
    try:
        cfg = RVC_STATE.get("cfg") or _rvc_load_cfg()
        return cfg.get("rvcDir") or ""
    except Exception:
        return ""


def _clean_with_engine_python(src_wav, dst_wav, rvc_dir=""):
    """Run Clean & Clear as a subprocess with the python that HAS the neural
    engine (your RVC env). Needed because Sonora itself may run on a plain
    system python without torch: installing clearvoice into the RVC python
    then would otherwise never be used by this app.

    Returns the report dict, or None when no such python/engine exists.
    """
    try:
        py = _discover_torch_python(rvc_dir)
    except Exception:
        py = None
    if not py:
        return None
    cli = os.path.join(ROOT, "enhance.py")
    if not os.path.isfile(cli):
        return None
    try:
        probe = subprocess.run([py, cli, "--probe"], capture_output=True,
                               timeout=300)
        info = json.loads((probe.stdout or b"{}").decode("utf-8", "ignore")
                          .strip().splitlines()[-1])
        if not info.get("model_backends"):
            return None
    except Exception:
        return None
    rep_path = dst_wav + ".report.json"
    cmd = [py, cli, "--in", src_wav, "--out", dst_wav, "--tier", "model",
           "--base", CLEAN_CKPT,
           "--json", rep_path,
           "--lufs", str(CLEAN_DEFAULTS["lufs"]),
           "--peak", str(CLEAN_DEFAULTS["peak"]),
           "--sr", str(CLEAN_DEFAULTS["sr"]),
           "--deess", str(CLEAN_DEFAULTS["deess"])]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=7200,
                           cwd=ROOT)
        if r.returncode != 0:
            print("[clean] engine python failed: "
                  + (r.stderr or b"").decode("utf-8", "ignore")[-400:], flush=True)
            return None
        with open(rep_path, "r", encoding="utf-8") as fh:
            rep = json.load(fh)
        rep["ran_in"] = py
        return rep
    except Exception as e:
        print(f"[clean] engine python error: {type(e).__name__}: {e}", flush=True)
        return None
    finally:
        try:
            os.remove(rep_path)
        except OSError:
            pass


def _clean_key_files(key):
    for ext in ("mp3", "wav", "m4a", "ogg", "master", "raw"):
        p = os.path.join(CACHE_DIR, key + "." + ext)
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass

_ETA = {"t0": 0.0, "start_done": 0}


def _eta_note(total, done):
    """A short "— about N min left" for long jobs (hidden while it is warming
    up, because an estimate from three sentences is a lie)."""
    try:
        now = time.time()
        if done < 60 or total <= done:
            return ""
        if _ETA["t0"] == 0.0 or done < _ETA["start_done"]:
            _ETA.update(t0=now, start_done=done)
            return ""
        dt = now - _ETA["t0"]
        dd = done - _ETA["start_done"]
        if dd < 25 or dt < 5:
            return ""
        left = (total - done) * (dt / dd)
        if left < 45:
            return ""
        if left < 5400:
            return " — about %d min left" % max(1, round(left / 60))
        return " — about %.1f h left" % (left / 3600)
    except Exception:
        return ""


def _burst_protection(probe_voice):
    """Called when a run of units has failed: pause instead of hammering.

    Returns True when the provider answered again after the pause.
    """
    n = SERVICE_STATE.get("burst_fail_streak", 0)
    if n < BURST_FAIL_LIMIT:
        return True
    print("[tts] %d unit(s) failed in a row — pausing %.0fs to let the provider "
          "recover instead of retrying the whole job" % (n, BURST_PAUSE_S),
          flush=True)
    SERVICE_STATE["throttle_until"] = time.time() + BURST_PAUSE_S
    time.sleep(BURST_PAUSE_S)
    SERVICE_STATE["burst_fail_streak"] = 0
    SERVICE_STATE["throttle_until"] = 0.0
    # come back politely: requests are spaced out from here on
    _edge_pace_set(0.5)
    return _edge_probe(probe_voice or "km-KH-SreymomNeural", tries=2)


class _Cancelled(Exception):
    """The user pressed Stop (or the queue was cleared)."""


def _check_cancel(key):
    if key in _CANCEL:
        raise _Cancelled()


def _produce_job(key, lines, voices, speed, pause, bed, bed_level, fmt, style,
                 bed_file=None, bed_speed=1.0, rvc_cfg=None, clean=False, hd=False):
    """Background production with automatic whole-job retries.

    If every engine is down (transient Microsoft block), wait and retry
    the entire job up to 2 more times instead of failing on the first blip.
    """
    # GO STRAIGHT: a long episode must never end in FAILED because the voice
    # service had a bad minute. The job waits and continues by itself — every
    # attempt resumes from the units already made, so the waiting costs nothing
    # but time, and the user never has to press Generate again.
    waits = (20, 30, 45, 60, 90, 120, 180, 300)     # seconds between attempts
    patience_s = float(os.environ.get("SONORA_PATIENCE_S", "2700"))   # 45 min
    deadline = time.time() + patience_s
    attempt = 0
    while True:
        attempt += 1
        try:
            # RVC clone: the model is loaded in the BACKGROUND while the first
            # lines are already being spoken — loading it up front used to sit
            # at 0 % for a minute before any audio existed. A broken setup is
            # still caught immediately by the fast path checks below.
            if rvc_cfg and any(v == RVC_VOICE_ID for v in voices.values()):
                try:
                    _rvc_resolve_cfg(rvc_cfg)          # fast: paths + files only
                except Exception as e:
                    raise VoiceServiceDown("the RVC voice is not usable: %s"
                                           % str(e)[:200])
                RVC_STATE["cfg"] = rvc_cfg
                if not (_rvc_health() or {}).get("state") == "ready":
                    _status(key, "voice model loading in the background…", 0, 0)
                    threading.Thread(target=_rvc_ensure_worker,
                                     args=(rvc_cfg,), daemon=True).start()
            final_path, duration, degraded = produce(key, lines, voices, speed, pause,
                                                     bed, bed_level, fmt, style, bed_file, bed_speed,
                                                     rvc_cfg, clean, hd)
            _status(key, "done", state="done", duration=duration, degraded=degraded)
            return
        except _Cancelled:
            print("[worker] job %s stopped by the user" % key, flush=True)
            _status(key, "stopped — press Continue to finish it later",
                    state="stopped")
            return
        except VoiceServiceDown as e:
            print(f"[worker] job {key} attempt {attempt}: voice service failure -> {e}",
                  flush=True)
            with STATUS_LOCK:
                rec = dict(STATUS.get(key) or {})
            done_n, total_n = rec.get("done", 0), rec.get("total", 0)
            left = deadline - time.time()
            if left > 5:
                wait_s = int(min(waits[min(attempt - 1, len(waits) - 1)], left))
                pct = (f" {done_n}/{total_n} lines are saved and will be reused."
                       if total_n else "")
                _status(key, f"voice service is busy — waiting {wait_s}s, then "
                             f"continuing automatically (attempt {attempt})."
                             + pct, state="working")
                time.sleep(wait_s)
                continue
            err = ("The voice service stayed unavailable for a long time "
                   "(about %.0f minutes of automatic waiting). "
                   "Press Generate and the episode continues from where it "
                   "stopped — nothing already made is lost."
                   % (patience_s / 60.0)
                   + f" [studio build {STUDIO_BUILD}]")
            if total_n:
                pct = max(0, round(done_n / total_n * 100))
                err += f" Saved: {pct}% ({done_n}/{total_n} lines)."
            _status(key, "failed", state="error", error=err,
                    detail=str(e)[:400].replace("\n", " ")
                           + f" | studio build {STUDIO_BUILD}")
            _clean_key_files(key)
            return
        except Exception as e:
            _status(key, "failed", state="error",
                    error=str(e)[:400] +
                    " — press Continue to finish this episode; the lines "
                    "already made are kept.")
            _clean_key_files(key)
            return

def _job_runner():
    """Single worker thread — the heart of the multi-generation queue.

    It can never die: anything that escapes a job is caught, reported on the
    job itself, and the next episode starts. A supervisor thread below brings
    the runner back if the thread itself is ever lost.
    """
    _RUNNER["alive"] = _RUNNER.get("alive", 0) + 1
    while True:
        _RUNNER["beat"] = time.time()
        try:
            item = JOB_QUEUE.get()
        except Exception:
            time.sleep(1.0)
            continue
        if item is None:
            break
        key, args = item
        with _JOBS_LOCK:
            if key in _QUEUE_ORDER:
                _QUEUE_ORDER.remove(key)
        _RUNNER.update(busy=True, key=key, beat=time.time())
        try:
            _status(key, "starting…", 0, 0)
            _produce_job(key, *args)
        except BaseException as e:                 # never lose the thread
            print(f"[job-runner] unexpected error on {key}: {e}", flush=True)
            _status(key, "failed", state="error",
                    error="%s: %s — press Continue to finish this episode; "
                          "the lines already made are kept."
                          % (type(e).__name__, str(e)[:200]))
            _jobs_finish(key, "error")
        finally:
            _RUNNER.update(busy=False, key=None, beat=time.time())
            _queue_positions()


def _queue_supervisor():
    """Watches the runner and the running job. Brings the runner back if it is
    gone; reports (and offers Continue for) a job that stopped progressing."""
    time.sleep(8)
    while True:
        time.sleep(15)
        try:
            now = time.time()
            beat = _RUNNER.get("beat") or now
            if _RUNNER.get("busy"):
                key = _RUNNER.get("key")
                with STATUS_LOCK:
                    rec = dict(STATUS.get(key) or {})
                if rec and (now - rec.get("beat", beat) > _STALL_S):
                    mins = int((now - rec.get("beat", beat)) // 60)
                    print("[supervisor] %s: no progress for %d min" % (key, mins),
                          flush=True)
                    _status(key, "no progress for %d min — still holding your "
                                 "place; press Continue to restart this "
                                 "episode from the lines already made" % mins,
                            state="working", note="stalled")
            elif not JOB_QUEUE.empty() and now - beat > 45:
                print("[supervisor] the job runner stopped — starting a new one",
                      flush=True)
                threading.Thread(target=_job_runner, daemon=True).start()
            # a live runner also means the waiting list should be renumbered
            if not JOB_QUEUE.empty():
                _queue_positions()
        except Exception as e:
            print("[supervisor] %s: %s" % (type(e).__name__, str(e)[:120]),
                  flush=True)

# --------------------------------------------------------------- HTTP -------


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "Sonora/1.0"

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args), flush=True)

    # -- helpers -------------------------------------------------------------
    def _json(self, code, obj):
        try:
            _rq_log("%s %s -> %s" % (self.command, self.path.split("?")[0], code))
            if code >= 400 and isinstance(obj, dict) and obj.get("error"):
                _rq_log("      " + str(obj["error"])[:200].replace("\n", " "))
        except Exception:
            pass
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _audio_file(self, path, content_type, extra=None):
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _chunk(self, data: bytes):
        self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
        self.wfile.flush()

    def _stream_file(self, path, content_type, key, duration=None):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("X-Job-Key", key)
        if duration is not None:
            self.send_header("X-Duration", f"{duration:.2f}")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.flush()
        try:
            with open(path, "rb") as f:
                while True:
                    b = f.read(262144)
                    if not b:
                        break
                    self._chunk(b)
        finally:
            self._chunk(b"")

    def _read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 60_000_000:
            raise ValueError("request too large")
        raw = self.rfile.read(n) if n else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        fp = os.path.normpath(os.path.join(PUBLIC, path.lstrip("/")))
        if not fp.startswith(PUBLIC) or not os.path.isfile(fp):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".json": "application/json",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".m4a": "audio/mp4",
        }
        if os.path.basename(fp) == "index.html":
            # stamp the page with THIS build, so the page and the server can
            # never warn about each other because of a forgotten constant
            try:
                with open(fp, "rb") as f:
                    body = f.read().replace(b"__PAGE_BUILD__",
                                            STUDIO_BUILD.encode("ascii"))
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            except Exception as e:
                print("[static] stamping failed: %s" % str(e)[:120], flush=True)
        self._audio_file(fp, types.get(os.path.splitext(fp)[1].lower(), "application/octet-stream"))

    # -- routes --------------------------------------------------------------
    def _method_not_used(self):
        self._json(405, {"error": "this address only answers GET/POST/OPTIONS "
                                  "requests (got " + self.command + ")"})

    def do_PUT(self):
        self._method_not_used()

    def do_PATCH(self):
        self._method_not_used()

    def do_DELETE(self):
        self._method_not_used()

    def do_HEAD(self):
        self._method_not_used()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        try:
            _rq_log("-> GET " + self.path.split("?")[0])
        except Exception:
            pass
        try:
            path = self.path.split("?")[0]
            if path == "/api/ping":
                self._json(200, {"ok": True, "build": STUDIO_BUILD})
                return
            if path == "/api/khmer/emotions":
                xp = _khmer_expressive()
                if xp is None:
                    self._json(200, {"available": False, "families": {}})
                    return
                self._json(200, {"available": True, "count": len(xp.EMOTIONS),
                                 "families": {k: sorted(v) for k, v in
                                              xp.EMOTION_FAMILIES.items()},
                                 "styles": {sid: xp.STYLE_DEFAULT_EMOTION.get(sid)
                                            for sid in (NAR.STYLE_ORDER
                                                        if "NAR" in globals()
                                                        else xp.STYLE_DEFAULT_EMOTION)}})
                return
            if path == "/api/khmer/lexicon":
                kt = _khmer_module()
                lex = kt.load_lexicon(_KH_LEXICON_PATH) if kt else {}
                self._json(200, {"path": _KH_LEXICON_PATH,
                                 "available": bool(kt), "lexicon": lex,
                                 "counts": {k: len(v) for k, v in lex.items()},
                                 "notes": _KH_NOTES[-12:]})
                return
            if path == "/api/version":
                self._json(200, {"build": STUDIO_BUILD,
                                 "features": STUDIO_FEATURES.split(", ")})
                return
            if path.startswith("/audio/"):
                self._handle_audio_file(path)
                return
            if path == "/api/voices":
                refresh = "refresh=1" in self.path
                self._json(200, {"voices": get_voices(refresh=refresh)})
                return
            if path == "/api/enhance/installlog":
                p = os.path.join(ROOT, ".clean_install.log")
                text = ""
                try:
                    with open(p, "rb") as f:
                        data = f.read()
                    text = data.decode("utf-8", "ignore")
                except Exception as e:
                    text = f"(no log file yet — {type(e).__name__})"
                lines = text.splitlines()
                body_txt = "\n".join(lines[-400:])
                self.send_response(200)
                self.send_header("Content-Type",
                                 "text/plain; charset=utf-8")
                self.send_header("Content-Disposition",
                                 'inline; filename="clean_install.log"')
                self.send_header("Cache-Control", "no-store")
                raw = body_txt.encode("utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            if path == "/api/enhance/status":
                have = E.model_backends()
                self._json(200, {
                    "ffmpeg": bool(FFMPEG),
                    "backends": have,
                    "engine": (" + ".join(have) if have else "ffmpeg"),
                    "defaults": CLEAN_DEFAULTS,
                    "last": CLEAN_STATE.get("last"),
                    "install": CLEAN_STATE.get("install"),
                })
                return
            if path == "/api/rvc/status":
                cfg = RVC_STATE.get("cfg") or _rvc_load_cfg()
                h = _rvc_health() or {}
                cmd = _rvc_worker_cmd(cfg)
                self._json(200, {
                    "configured": bool(cfg.get("rvcDir") and cfg.get("model")),
                    "cfg": cfg,
                    "worker": h.get("state", "down"),
                    "device": h.get("device", ""),
                    "half": bool(h.get("half")),
                    "rtf": h.get("rtf"),
                    "warmup_s": h.get("warmup_s"),
                    "model": h.get("model", ""),
                    "api": h.get("api", ""),
                    "notes": h.get("notes", []),
                    "identity": h.get("identity", {}),
                    "server_log": "\n".join(RQ_LOG[-80:]),
                    "python": (cmd or ["?"])[0],
                    "log": h.get("log", "") or _rvc_log_tail(1200),
                })
                return
            if path == "/api/beds":
                with BEDI_LOCK:
                    idx = _beds_load()
                beds = sorted(idx.values(), key=lambda b: -b.get("mtime", 0))
                for b in beds:
                    b.pop("path", None)
                self._json(200, {"beds": beds})
                return
            if path.startswith("/beds/"):
                self._serve_bed_file(path[len("/beds/"):])
                return
            if path.startswith("/hd-preview/"):
                parts = path.split("/")
                if len(parts) == 4 and re.fullmatch(r"[0-9a-zA-Z-]{16,64}", parts[2]) \
                        and re.fullmatch(r"[\w.\-]+\.mp3", parts[3]):
                    f = os.path.join(CACHE_DIR, parts[2] + ".hd_preview", parts[3])
                    if os.path.exists(f):
                        self._audio_file(f, "audio/mpeg")
                        return
                self._json(404, {"error": "no such preview"})
                return
            if path == "/api/status":
                from urllib.parse import parse_qs
                qs = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
                key = (qs.get("key") or [""])[0]
                with STATUS_LOCK:
                    st = dict(STATUS.get(key) or {})
                if st:
                    st.pop("t", None)
                    _hid = HD_STATE.get(key)
                    if _hid:
                        st["hd"] = _hid
                    self._json(200, st)
                else:
                    self._json(404, {"error": "no such job"})
                return
            if path.startswith("/api/"):
                self._json(404, {"error": "not found"})
                return
            self._static(path)
        except Exception as e:
            self._json(500, {"error": str(e)})

    def do_POST(self):
        try:
            _rq_log("-> POST " + self.path.split("?")[0])
        except Exception:
            pass
        try:
            path = self.path.split("?")[0]
            if path == "/api/produce":
                self._handle_produce()
            elif path == "/api/cancel":
                self._handle_cancel()
            elif path == "/api/resume":
                self._handle_resume()
            elif path == "/api/convert":
                self._handle_convert()
            elif path == "/api/khmer/prepare":
                body = self._read_body() or {}
                txt = str(body.get("text") or "")
                self._json(200, khmer_prepare(txt))
            elif path == "/api/khmer/learn":
                body = self._read_body() or {}
                term = str(body.get("term") or "").strip()
                spoken = str(body.get("spoken") or "").strip()
                kind = str(body.get("kind") or "word").strip() or "word"
                if not term or not spoken:
                    raise ValueError("two fields are needed: the text as written "
                                     "and how it must be spoken")
                kt = _khmer_module()
                if kt is None:
                    raise ValueError("pipeline/khmer_text.py was not found next to "
                                     "the studio - the correction cannot be stored")
                lex = kt.learn(term, spoken, kind, _KH_LEXICON_PATH)
                _KH_CACHE.clear()
                self._json(200, {"learned": {"term": term, "spoken": spoken,
                                             "kind": kind},
                                 "path": _KH_LEXICON_PATH,
                                 "counts": {k: len(v) for k, v in lex.items()}})
            elif path == "/api/khmer/perform":
                body = self._read_body() or {}
                txt = str(body.get("text") or "")
                style = str(body.get("style") or "natural")
                inten = body.get("intensity")
                try:
                    inten = int(inten) if inten not in (None, "") else None
                except Exception:
                    inten = None
                xp = _khmer_expressive()
                if xp is None:
                    raise ValueError("pipeline/khmer_expressive.py was not found "
                                     "next to the studio")
                plan = xp.perform(txt, style=style, intensity=inten,
                                  speed=float(body.get("speed") or 1.0),
                                  pause=float(body.get("pause") or 0.25))
                plan["sheet"] = xp.sheet(plan)
                plan["summary"] = xp.summary(plan)
                self._json(200, plan)
            elif path == "/api/script":
                self._handle_script()
            elif path == "/api/try":
                self._handle_try()
            elif path == "/api/rvc/config":
                body = self._read_body()
                cfg = _rvc_cfg_from_body(body)
                if not cfg.get("rvcDir") or not cfg.get("model"):
                    raise ValueError("set the RVC folder and model fields in the RVC section first — one of them is empty")
                if not os.path.isdir(cfg["rvcDir"]):
                    raise ValueError(f"RVC folder not found: {cfg['rvcDir']}")
                model_p = (cfg["model"] if os.path.isabs(cfg["model"])
                           else os.path.join(cfg["rvcDir"], cfg["model"]))
                if not os.path.exists(model_p):
                    raise ValueError(f"model file not found: {model_p}")
                RVC_STATE["cfg"] = cfg
                _rvc_save_cfg(cfg)
                self._json(200, {"saved": True,
                                 "worker": (_rvc_health() or {}).get("state", "down")})
                return
            elif path == "/api/enhance/install":
                body = self._read_body()
                pkg = (body.get("package") or "clearvoice").strip().lower()
                if pkg not in ("clearvoice", "deepfilternet"):
                    raise ValueError("package must be clearvoice or deepfilternet")
                cfg = RVC_STATE.get("cfg") or _rvc_load_cfg()
                cmd = _rvc_worker_cmd(cfg) or []
                py = (cfg.get("python") or "").strip() or (cmd[0] if cmd else "")
                if not py:
                    raise ValueError("could not resolve the RVC python — set "
                                     "the RVC PYTHON field in the RVC section")
                if body.get("dry"):
                    self._json(200, {"ok": True, "dry": True, "python": py,
                                     "command": f'"{py}" -m pip install {pkg}'})
                    return
                cur = CLEAN_STATE.get("install") or {}
                if cur.get("running"):
                    self._json(200, {"ok": True, "already_running": True})
                    return
                _clean_install_start(py, pkg)
                self._json(202, {"ok": True, "started": True, "python": py,
                                 "package": pkg})
                return
            elif path == "/api/rvc/scan":
                cands, dirs, roots = _rvc_scan()
                self._json(200, {"candidates": cands, "scanned": dirs,
                                 "drives": roots})
                return
            elif path == "/api/rvc/test":
                body = self._read_body()
                cfg = _rvc_cfg_from_body(body)
                if not cfg.get("rvcDir") or not cfg.get("model"):
                    raise ValueError("set the RVC folder and model fields in the RVC section first — one of them is empty")
                if not os.path.isdir(cfg["rvcDir"]):
                    raise ValueError(f"RVC folder not found: {cfg['rvcDir']}")
                notes = _rvc_resolve_cfg(cfg)
                for n in notes:
                    print("[rvc] " + n, flush=True)
                    _rq_log("[rvc] " + n)
                model_p = (cfg["model"] if os.path.isabs(cfg["model"])
                           else os.path.join(cfg["rvcDir"], cfg["model"]))
                if os.path.isdir(model_p):
                    raise ValueError(
                        "the MODEL (.PTH) field is a folder, not a file: "
                        + model_p + " — either put the .pth file name on the "
                        "end (e.g. assets/weights/Sonaro-kh.pth) or just leave "
                        "the folder there and Sonora will pick the .pth inside "
                        "it, once one exists")
                if not os.path.exists(model_p):
                    have = []
                    for sub in ("assets/weights", "weights"):
                        d = os.path.join(cfg["rvcDir"], *sub.split("/"))
                        if os.path.isdir(d):
                            have += [f for f in os.listdir(d)
                                     if f.lower().endswith(".pth")][:6]
                    raise ValueError("model file not found: " + model_p
                                     + ((" — the RVC folder has: " + ", ".join(have))
                                        if have else ""))
                carrier = cfg.get("carrier") or "km-KH-SreymomNeural"
                if carrier == RVC_VOICE_ID:
                    raise ValueError("base voice cannot be the RVC clone itself")
                RVC_STATE["cfg"] = cfg
                _rvc_save_cfg(cfg)
                ok, detail = _rvc_ensure_worker(cfg)
                if not ok:
                    raise ValueError(detail + (" | " + _rvc_log_tail(300)
                                               if _rvc_log_tail() else ""))
                # "Hello, my name is Sonaro. This is my voice." (Khmer)
                text = ("\u179f\u17bd\u179f\u178f\u17b8 \u1781\u178e\u17d2\u17bb\u17c9 "
                        "\u1788\u17d2\u1798\u17b6\u17c7 Sonaro\u17d4 "
                        "\u1793\u17c7 \u1787\u17b6 \u179f\u17c9\u17a1\u17c1\u1784 "
                        "\u179a\u1794\u179f\u17d2\u179f\u17c7 "
                        "\u1781\u178e\u17d2\u17bb\u17c9\u17d4")
                hsh = hashlib.sha1(json.dumps(
                    [carrier, cfg["pitch"], cfg["indexRate"], cfg["protect"],
                     cfg["f0Method"]]).encode()).hexdigest()[:12]
                out_mp3 = os.path.join(CACHE_DIR, "rvc_test_" + hsh + ".mp3")
                side = out_mp3 + ".pitch.json"
                report = ""
                if not os.path.exists(out_mp3) or os.path.getsize(out_mp3) < 600:
                    mp3, _eng = asyncio.run(
                        synth_unit_mp3(text, carrier, "+0%"))
                    c_hz = _median_f0(mp3_to_f32(mp3))
                    f32 = _rvc_convert_f32(mp3_to_f32(mp3), cfg)
                    v_hz = _median_f0(f32)
                    with tempfile.TemporaryDirectory() as td:
                        wp = os.path.join(td, "t.wav")
                        with open(wp, "wb") as f:
                            f.write(f32_to_wav_bytes(f32))
                        wav_to_mp3(wp, out_mp3)
                    try:
                        with open(side, "w", encoding="utf-8") as f:
                            json.dump({"carrier": c_hz, "clone": v_hz}, f)
                    except Exception:
                        pass
                    report = (_pitch_report(c_hz, v_hz) + "  —  "
                              + _model_identity_note(cfg, _rvc_health(),
                                                     c_hz, v_hz))
                    _evict_cache()
                else:
                    try:
                        with open(side, "r", encoding="utf-8") as f:
                            d = json.load(f)
                        report = (_pitch_report(d.get("carrier"), d.get("clone"))
                                  + "  —  "
                                  + _model_identity_note(cfg, _rvc_health(),
                                                         d.get("carrier") or 0.0,
                                                         d.get("clone") or 0.0))
                    except Exception:
                        # an older cached clip has no pitch sidecar: measure the
                        # clone from the file, and remember it for next time
                        v_hz = _median_f0(mp3_to_f32(out_mp3))
                        report = (_pitch_report(0, v_hz) + "  —  "
                                  + _model_identity_note(cfg, _rvc_health(),
                                                         0.0, v_hz))
                        try:
                            with open(side, "w", encoding="utf-8") as f:
                                json.dump({"carrier": 0.0, "clone": v_hz}, f)
                        except Exception:
                            pass
                hdrs = {}
                if report:
                    from urllib.parse import quote
                    hdrs["X-Sonora-Note"] = quote(report)
                self._audio_file(out_mp3, "audio/mpeg", hdrs)
                return
            elif path == "/api/generate":
                self._handle_generate()
            elif path == "/api/beds":
                self._handle_beds_upload()
            elif path == "/api/beds/delete":
                self._handle_beds_delete()
            else:
                self._json(404, {"error": "not found"})
        except ValueError as e:
            self._json(400, {"error": str(e)})
        except VoiceServiceDown:
            self._json(502, {"error": "The voice service is temporarily unavailable — please press Generate again in a few seconds."})
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._json(500, {"error": f"production failed: {e}"})

    # -- handlers ------------------------------------------------------------
    def _handle_audio_file(self, path):
        """Serve a cached generated file with a download filename (for new-tab saves)."""
        from urllib.parse import parse_qs
        parts = path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "audio":
            self._json(404, {"error": "not found"})
            return
        _, key, fmt = parts
        if not re.fullmatch(r"[0-9a-zA-Z-]{16,64}", key) or fmt not in ("mp3", "wav", "m4a", "ogg"):
            self._json(404, {"error": "not found"})
            return
        fp = os.path.join(CACHE_DIR, key + "." + fmt)
        if not os.path.exists(fp):
            self._json(410, {"error": "audio expired — press Generate again"})
            return
        qs = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
        name = (qs.get("name") or [key + "." + fmt])[0]
        root = re.sub(r"[^a-zA-Z0-9\u0e00-\u0e7f _-]", "", name.rpartition(".")[0]).strip()[:76]
        safe = (root + "." + fmt) if root else (key + "." + fmt)
        ct = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4", "ogg": "audio/ogg"}[fmt]
        with open(fp, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % safe)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # -- music beds ------------------------------------------------------------
    def _handle_beds_upload(self):
        """Raw-body upload (the client POSTs the file bytes directly with an
        X-File-Name header). Streams to disk in chunks — 1–2h files are fine."""
        from urllib.parse import unquote
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            raise ValueError("empty upload")
        if n > BEDI_MAX_BYTES:
            raise ValueError("file too large (max ~2 hours of audio)")
        fname = unquote(self.headers.get("X-File-Name") or "music")
        ext = (fname.rpartition(".")[2] or "").lower()
        if ext not in BEDI_EXTS:
            ext = "mp3"
        import random as _rnd
        # take the SIGNIFICANT (right-hand) hex digits, and guarantee uniqueness
        with BEDI_LOCK:
            existing = set(_beds_load())
        while True:
            bid = ("%032x" % (int(time.time() * 1e6) ^ _rnd.getrandbits(48)))[-20:]
            if bid not in existing:
                break
            existing.add(bid)
        os.makedirs(BEDI_DIR, exist_ok=True)
        tmp = os.path.join(BEDI_DIR, ".upload_" + bid + "." + ext)
        final = os.path.join(BEDI_DIR, bid + "." + ext)
        written = 0
        with open(tmp, "wb") as f:
            while written < n:
                chunk = self.rfile.read(min(1 << 22, n - written))
                if not chunk:
                    break
                f.write(chunk)
                written += len(chunk)
        if written != n:
            try: os.remove(tmp)
            except OSError: pass
            raise ValueError("upload was cut short — try again")
        dur = _bed_duration(tmp)
        os.replace(tmp, final)
        entry = {"id": bid, "name": os.path.basename(fname), "ext": ext,
                 "path": final, "size": written, "duration": dur, "mtime": time.time()}
        with BEDI_LOCK:
            idx = _beds_load()
            idx[bid] = entry
            _beds_save(idx)
        print(f"[beds] uploaded {fname} ({written // (1024*1024)} MB, {dur or '?'}s) as {bid}", flush=True)
        self._json(200, {"ok": True, "bed": entry})

    def _handle_beds_delete(self):
        body = self._read_body()
        bid = (body.get("id") or "").strip()
        if not re.fullmatch(r"[0-9a-f]{12,40}", bid):
            raise ValueError("bad id")
        with BEDI_LOCK:
            idx = _beds_load()
            entry = idx.pop(bid, None)
            if entry:
                _beds_save(idx)
        if not entry:
            raise ValueError("bed not found")
        for p in [entry.get("path"),
                  os.path.join(BEDI_DIR, bid + "." + entry.get("ext", "mp3")),
                  os.path.join(BEDI_DIR, bid + "_s100.raw"),
                  os.path.join(BEDI_DIR, bid + "_s150.raw"),
                  os.path.join(BEDI_DIR, bid + "_s200.raw"),
                  os.path.join(BEDI_DIR, bid + "_s050.raw"),
                  os.path.join(BEDI_DIR, bid + "_s120.raw"),
                  os.path.join(BEDI_DIR, bid + "_s075.raw"),
                  os.path.join(BEDI_DIR, bid + "_s090.raw")]:
            if p and os.path.exists(p):
                try: os.remove(p)
                except OSError: pass
        self._json(200, {"ok": True})

    def _serve_bed_file(self, bid):
        """Stream an uploaded bed for ▶ preview (Range support for seeking)."""
        if not re.fullmatch(r"[0-9a-f]{12,40}", bid):
            self._json(404, {"error": "not found"})
            return
        with BEDI_LOCK:
            entry = _beds_load().get(bid)
        if not entry:
            self._json(404, {"error": "not found"})
            return
        fp = os.path.join(BEDI_DIR, bid + "." + entry.get("ext", "mp3"))
        if not os.path.exists(fp):
            self._json(410, {"error": "bed expired"})
            return
        size = os.path.getsize(fp)
        ctype = {"mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4",
                 "ogg": "audio/ogg", "flac": "audio/flac", "aac": "audio/aac",
                 "opus": "audio/ogg", "webm": "audio/webm", "mp4": "audio/mp4"}.get(entry.get("ext"), "application/octet-stream")
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        code = 200
        if rng and rng.startswith("bytes="):
            try:
                part = rng[6:].split("-")[0]
                start = int(part) if part else 0
                if "-" in rng and rng[6:].split("-")[1]:
                    end = int(rng[6:].split("-")[1])
                end = min(end, size - 1)
                code = 206
            except ValueError:
                pass
        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(length))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            with open(fp, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(1 << 20, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _handle_produce(self):
        """Two-phase production: kick off the job, return immediately.
        The client polls /api/status, then downloads via /audio/<key>/<fmt>.
        This survives proxies/timeouts that kill one long silent request."""
        body = self._read_body()
        lines = body.get("lines") or []
        if not isinstance(lines, list) or not lines:
            raise ValueError("lines required")
        for l in lines:
            t = l.get("text") if isinstance(l, dict) else None
            if not isinstance(t, str) or not t.strip():
                raise ValueError("each line needs a non-empty text string")
        voices = body.get("voices") or {}
        key = (body.get("job") or "").strip()
        if not re.fullmatch(r"[0-9a-zA-Z-]{16,64}", key):
            raise ValueError("job id required (16-64 chars)")
        key = key[:48]
        fmt = (body.get("format") or "mp3").lower()
        if fmt not in ("mp3", "wav"):
            raise ValueError("format must be mp3 or wav")
        speed = float(body.get("speed", 1.0))
        pause = float(body.get("pause", 0.1))
        bed = (body.get("bed") or "none").lower()
        if bed not in ("none", "warm", "drone", "crackle", "pad"):
            bed = "none"
        bed_level = float(body.get("bed_level", 0))
        style = (body.get("style") or "natural").lower()
        style = NAR.style_id(style)          # accepts "Novel Narration" etc.
        # Optional uploaded music bed (id + loop speed). Validated against the
        # beds index so a stale id can't read an arbitrary path.
        bed_file = (body.get("bed_file") or "").strip()
        bed_speed = float(body.get("bed_speed", 1.0))
        bed_speed = min(2.0, max(0.5, bed_speed))
        if bed_file and not re.fullmatch(r"[0-9a-f]{12,40}", bed_file):
            bed_file = ""
        if bed_file and bed_file not in _beds_load():
            bed_file = ""

        # HD wav files are 48 kHz / 24-bit / stereo = 288000 bytes/sec
        hd_bytes_per_sec = 48000 * 3 * 2
        cached = os.path.join(CACHE_DIR, key + "." + fmt)
        if os.path.exists(cached):
            dur = None
            if fmt == "wav":
                dur = max(0.0, (os.path.getsize(cached) - 44) / hd_bytes_per_sec)
            elif os.path.exists(os.path.join(CACHE_DIR, key + ".master")):
                dur = wav_duration(os.path.join(CACHE_DIR, key + ".master"))
            _status(key, "done", state="done", duration=dur)
        else:
            # already known? do not run the same episode twice
            with STATUS_LOCK:
                live = dict(STATUS.get(key) or {})
            with _JOBS_LOCK:
                known = key in _JOBS["pending"]
            if known or (live and live.get("state") == "working"):
                self._json(202, {"job": key, "started": True, "already": True})
                return
            # Enqueue — the serial job runner picks it up in order.
            has_rvc = any(v == RVC_VOICE_ID for v in voices.values())
            rvc_cfg = _rvc_cfg_from_body(body)
            if has_rvc:
                RVC_STATE["cfg"] = rvc_cfg
                _rvc_save_cfg(rvc_cfg)
            _enqueue(key, (lines, voices, speed, pause, bed, bed_level, fmt, style,
                           bed_file, bed_speed,
                           rvc_cfg if has_rvc else None,
                           bool(body.get("clean")),
                           bool(body.get("hd"))))
        self._json(202, {"job": key, "started": True})

    def _clean_key(self, key):
        _clean_key_files(key)

    def _handle_cancel(self):
        """Stop a running or waiting episode. Finished lines stay on disk, so
        Continue picks up exactly where it stopped."""
        body = self._read_body()
        key = (body.get("key") or "").strip()
        if not re.fullmatch(r"[0-9a-zA-Z-]{16,64}", key):
            raise ValueError("bad job id")
        _CANCEL.add(key)
        with STATUS_LOCK:
            rec = dict(STATUS.get(key) or {})
        if rec:
            _status(key, "stopped by you — press Continue to finish it later",
                    state="stopped")
        self._json(200, {"job": key, "stopped": True})

    def _handle_resume(self):
        """Continue an episode (stalled, stopped, failed or after a restart).
        Every line already made is reused — this never starts from zero."""
        body = self._read_body()
        key = (body.get("key") or "").strip()
        if not re.fullmatch(r"[0-9a-zA-Z-]{16,64}", key):
            raise ValueError("bad job id")
        with _JOBS_LOCK:
            rec = (_JOBS["pending"].get(key) or _JOBS["keep"].get(key))
        args = (rec or {}).get("args")
        if not args:
            # no live plan (studio restarted?): rebuild it from what is on disk
            try:
                with open(_args_path(key), "r", encoding="utf-8") as f:
                    args = json.load(f)
            except Exception:
                args = None
        if not args:
            self._json(404, {"error": "this episode's plan is no longer stored — "
                                      "press Generate to continue it"})
            return
        _CANCEL.discard(key)
        _enqueue(key, args, note="— continuing")
        self._json(200, {"job": key, "resumed": True})

    def _handle_convert(self):
        body = self._read_body()
        key = (body.get("key") or "").strip()
        fmt = (body.get("format") or "wav").lower()
        if not re.fullmatch(r"[0-9a-zA-Z-]{16,64}", key):
            raise ValueError("bad key")
        ref = os.path.join(CACHE_DIR, key + ".wav")
        if not os.path.exists(ref) and not os.path.exists(os.path.join(CACHE_DIR, key + ".mp3")):
            self._json(410, {"error": "source audio expired; generate again"})
            return
        out_path = convert(ref, fmt)
        ct = {"wav": "audio/wav", "m4a": "audio/mp4", "ogg": "audio/ogg", "mp3": "audio/mpeg"}[fmt]
        self._audio_file(out_path, ct)

    def _handle_script(self):
        body = self._read_body()
        mode = (body.get("mode") or "auto").lower()
        text = clean_text(body.get("text") or "")
        if not text:
            raise ValueError("text required")
        if mode == "smart":
            lines = smart_script(text, body.get("language", "auto"), body.get("api") or {})
            note = "Generated with your LLM (OpenAI-compatible API)."
        else:
            lines, lang = auto_lines(text, body.get("language", "auto"))
            note = "Auto dialogue: two hosts alternate through your text with conversational bridges (no API key needed)."
        self._json(200, {"lines": lines, "script_text": scripts_to_text(lines), "note": note})

    def _handle_try(self):
        body = self._read_body()
        voice = (body.get("voice") or "").strip()
        if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}-\w+Neural", voice):
            raise ValueError("bad voice id")
        key = "try-" + voice
        path = os.path.join(CACHE_DIR, key + ".mp3")
        if not os.path.exists(path):
            first = voice.split("-")[2].replace("Neural", "")
            text = f"Hi, I'm {first}. Let me tell you something interesting."
            _status(key, "warming up…")
            mp3, _engine = asyncio.run(synth_unit_mp3(text, voice, "+0%"))
            with open(path, "wb") as f:
                f.write(mp3)
            _status(key, "done")
            _evict_cache()
        self._audio_file(path, "audio/mpeg")

    def _handle_generate(self):
        """Legacy single-voice streaming endpoint (kept for compatibility)."""
        body = self._read_body()
        segments = body.get("segments") or []
        if not segments:
            raise ValueError("segments required")
        key = (body.get("job") or "").strip()
        if not re.fullmatch(r"[0-9a-zA-Z-]{16,64}", key):
            raise ValueError("job id required")
        lines = [{"s": "S", "text": s.get("text", "")} for s in segments]
        voices = {"S": (segments[0] or {}).get("voice", "en-US-AvaNeural")}
        speed = 1.0 + float(segments[0].get("rate", 0)) / 100.0
        fmt = (body.get("format") or "mp3").lower()
        _status(key, "starting…")
        final_path, duration, _degraded = produce(key, lines, voices, speed, 0.12, "none", 0.0, fmt)
        _status(key, "done")
        ct = "audio/mpeg" if fmt == "mp3" else "audio/wav"
        self._stream_file(final_path, ct, key, duration)


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    print(f"Sonora running on http://0.0.0.0:{PORT}", flush=True)

    def warm():
        try:
            get_voices()
            print(f"voice list ready: {len(get_voices())} voices", flush=True)
        except Exception as e:
            print(f"voice list warning: {e}", flush=True)

    threading.Thread(target=warm, daemon=True).start()
    threading.Thread(target=_job_runner, daemon=True).start()
    threading.Thread(target=_queue_supervisor, daemon=True).start()
    try:
        _jobs_restore()
    except Exception as e:
        print("[jobs] restore skipped: %s" % str(e)[:120], flush=True)
    print("job queue ready (one job at a time, in order)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
