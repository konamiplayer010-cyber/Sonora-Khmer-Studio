"""Shared helpers for the Khmer history narration production pipeline.

Sonaro-Kh RVC pipeline:
    input script -> normalize -> chunk -> TTS WAV -> RVC WAV -> chapters -> final WAV

Design rules (from the production spec):
  * RESUMABLE     — processing_log.json drives skip/resume; nothing is redone.
  * NON-DESTRUCTIVE — valid outputs are never overwritten or deleted; a failed
                      candidate is written to a .part file, validated, and only
                      then moved into place.
  * NO GUESSING   — every path (RVC root, model, index) must exist before use;
                      missing things are reported, not invented.
  * VALIDATED     — a stage only counts as successful when the output file
                      exists, opens, has duration, and is not silent.
"""
import json
import os
import re
import shutil
import sys
import time
import unicodedata
import wave
from pathlib import Path

# Normally every stage works inside this folder. A test run can point the whole
# pipeline somewhere else (SONARO_PIPELINE_ROOT), so a test can never collide
# with a real book's chunks, log or audio — see test_clone.py.
_HERE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("SONARO_PIPELINE_ROOT") or _HERE)
CONFIG_PATH = ROOT / "config.json"

KHMER_STOP = "\u17D4"  # ។

# ================================================================ config ===

DEFAULT_CONFIG = {
    "project": "History_Narration_SONARO_KH",
    # input script (one file; chapter headers like "Chapter 1" split it)
    "input_file": "input/history_kh.txt",
    # --- RVC (verified against the installed RVC-WebUI) ---
    "rvc_root": r"E:\Audio Books\History\TH\RVC20260718Nvidia\RVC20260718Nvidia",
    "rvc_python": "",          # "" = auto-detect venv inside rvc_root
    "model_file": "assets/weights/Sonaro-kh.pth",   # relative to rvc_root
    "index_file": r"E:\Audio Books\History\TH\RVC20260718Nvidia\RVC20260718Nvidia"
                     r"\assets\indices\Sonaro-kh_added_IVF248_Flat_nprobe_1_Sonaro-kh_v2.index",
    "test_voice": r"E:\Audio Books\History\TH\Sonaro-kh_test.wav",
    # --- TTS (Khmer Microsoft voice used as the RVC carrier) ---
    "tts_engine": "auto",   # auto|edge|voxcpm|mms|gtts (see khmer_tts.py)
    # Narration style (optional). "" = plain chunk-level reading (fastest).
    # Set a style and every sentence is performed: pace, pitch, loudness,
    # pauses, emphasis, breathing — see narration.py or menu 5 of START.bat.
    #   natural | storytelling | novel | documentary | trailer | audiobook |
    #   news | explainer | thriller | meditation | inner_monologue |
    #   sad_romantic | cinematic
    #   "audiobook" is the default: the long-form listening style.
    #   Set "" for a plain read (one TTS call per chunk, fastest).
    "narration_style": "audiobook",
    "tts_voice": "km-KH-SreymomNeural",
    "tts_rate": "+0%",
    # --- RVC conversion settings (match Sonaro-kh_test.wav; do not change
    #     between chunks) ---
    "rvc": {
        "f0_method": "rmvpe",
        "pitch": 0,
        "index_rate": 0.75,
        "protect": 0.33,
        "rms_mix_rate": 0.13,
        "resample_sr": 0,
    },
    "final_sample_rate": 44100,
    "retries": 2,
    "final_name": "History_Narration_SONARO_KH.wav",
}


def load_config():
    if not CONFIG_PATH.exists():
        _atomic_write(CONFIG_PATH,
                      json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False))
        print(f"[config] created default config.json — review it, then re-run")
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    return merged


def _atomic_write(path: Path, text: str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def save_config(cfg):
    _atomic_write(CONFIG_PATH, json.dumps(cfg, indent=2, ensure_ascii=False))


def sub_dir(name):
    p = ROOT / name
    p.mkdir(parents=True, exist_ok=True)
    return p


# ================================================================= log =====

LOG_DIR = ROOT / "logs"
LOG_PATH = LOG_DIR / "processing_log.json"


def load_log():
    if LOG_PATH.exists():
        try:
            with open(LOG_PATH, encoding="utf-8") as f:
                log = json.load(f)
            log.setdefault("meta", {})
            log.setdefault("chunks", {})
            return log
        except Exception as e:
            print(f"[log] WARNING: processing_log.json is unreadable ({e}); "
                  f"starting a new log (old file kept as .corrupt)")
            try:
                os.replace(LOG_PATH, str(LOG_PATH) + ".corrupt")
            except OSError:
                pass
    return {"meta": {}, "chunks": {}}


def save_log(log):
    log["meta"]["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _atomic_write(LOG_PATH, json.dumps(log, indent=1, ensure_ascii=False))


def set_stage(log, cid, stage, status, error=None, extra=None):
    """stage in {tts, rvc, validation} — status in {success, failed, skipped}"""
    entry = log["chunks"].setdefault(cid, {})
    entry[stage] = status
    if error is not None:
        entry["error"] = error
    elif status == "success":
        entry.pop("error", None)
    if extra:
        entry.update(extra)


def counts(log):
    """(total, {stage: {status: n}})"""
    total = len(log["chunks"])
    per = {}
    for _, e in log["chunks"].items():
        for stage in ("tts", "rvc", "validation"):
            if stage in e:
                per.setdefault(stage, {})
                per[stage][e[stage]] = per[stage].get(e[stage], 0) + 1
    return total, per


# =============================================================== naming ====

def chapter_id(num):
    return f"chapter_{int(num):02d}"


def chunk_id(ch_num, n):
    return f"{chapter_id(ch_num)}/chunk_{int(n):04d}"


def tts_path(cid):
    return ROOT / "tts" / f"{cid}.wav"


def rvc_path(cid):
    return ROOT / "rvc_output" / f"{cid}.wav"


def chunk_text_path(ch_num, n):
    return ROOT / "normalized" / f"{chapter_id(ch_num)}_chunk_{int(n):04d}.txt"


# ======================================================== Khmer text ======

_KHMER_DIGITS = {"០": "0", "១": "1", "២": "2", "៣": "3", "៤": "4",
                 "៥": "5", "៦": "6", "៧": "7", "៨": "8", "៩": "9"}

_KHMER_DIGIT_WORDS = {"0": "សូន្យ", "1": "មួយ", "2": "ពីរ", "3": "បី", "4": "បួន",
                      "5": "ប្រាំ", "6": "ប្រាំមួយ", "7": "ប្រាំពីរ", "8": "ប្រាំបី", "9": "ប្រាំបួន"}

_KHMER_TENS = {"1": "ដប់", "2": "ម្ភៃ", "3": "សាមសិប", "4": "សែសិប", "5": "ហាសិប",
               "6": "ហុកសិប", "7": "ចិត្តសិប", "8": "ប៉ែតសិប", "9": "កៅសិប"}

# up to 10^5 — 10^6 and above are built with លាន (see _khmer_number_words)
_KHMER_UNITS = ["", "ដប់", "រយ", "ពាន់", "ម៉ឺន", "សែន"]

# A number, comma groups included:  1,200 | 2,500,000 | 3.5 | 85
_KH_NUM = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"

# words read digit-by-digit instead of as a quantity (phone numbers, IDs)
_KH_SPELL_LIMIT = 8        # 9+ ungrouped digits = identifier


def khmer_digits_to_arabic(s):
    for k, a in _KHMER_DIGITS.items():
        s = s.replace(k, a)
    return s


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
    # phone numbers / IDs are spoken digit by digit — but a comma-grouped
    # number is always a quantity, never a phone number
    if not grouped and len(num_str) > _KH_SPELL_LIMIT:
        return " ".join(_KHMER_DIGIT_WORDS[d] for d in num_str)
    # a leading zero is never a quantity: 012 345 678 is a phone number
    if (not grouped and num_str.startswith("0") and len(num_str) >= 8):
        return " ".join(_KHMER_DIGIT_WORDS[d] for d in num_str)
    if len(num_str) > 15:                     # keep pathological input sane
        return " ".join(_KHMER_DIGIT_WORDS[d] for d in num_str)
    # build in 10^6 blocks so លាន / ពាន់លាន come out right
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

    # --- times: 3:30 -> ម៉ោងបី សាមសិបនាទី   (guard: valid clock values only)
    #     If the writer already wrote ម៉ោង before it, or នាទី after it, we do
    #     not repeat the word — "ម៉ោង 3:30 នាទី" must read "ម៉ោងបី សាមសិប នាទី",
    #     never "ម៉ោង ម៉ោងបី ... នាទី នាទី".
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

    # --- ranges: 1990-1995 -> ពីមួយពាន់... ដល់ មួយពាន់...
    text = re.sub(r"(%s)\s*[-–—~]\s*(%s)" % (_KH_NUM, _KH_NUM),
                  lambda m: "ពី" + _khmer_decimal(m.group(1)) + " ដល់ " +
                            _khmer_decimal(m.group(2)), text)

    # --- ordinals: ទី 5 / ទី5 -> ទីប្រាំ
    text = re.sub(r"ទី\s*(%s)" % _KH_NUM,
                  lambda m: "ទី" + _khmer_decimal(m.group(1)), text)

    # --- percentages / currency (comma groups supported)
    def _add_word(m, word):
        """' … 12 ' + the unit word, unless the writer already wrote it next."""
        after = m.string[m.end():m.end() + len(word) + 2]
        return " " + _khmer_decimal(m.group(1)) + ("" if after.lstrip().startswith(word) else " " + word)

    text = re.sub(r"(%s)\s*%%" % _KH_NUM, lambda m: _add_word(m, "ភាគរយ"), text)
    text = re.sub(r"\$\s*(%s)" % _KH_NUM, lambda m: _add_word(m, "ដុល្លារ"), text)
    text = re.sub(r"\u17DB\s*(%s)" % _KH_NUM, lambda m: _add_word(m, "រៀល"), text)
    text = re.sub(r"(?<![A-Za-z])(?:riel|រៀល)\s*(%s)" % _KH_NUM,
                  lambda m: " " + _khmer_decimal(m.group(1)) + " រៀល", text,
                  flags=re.IGNORECASE)

    # --- spaced phone groups: 012 345 678 -> every digit spoken
    def _spaced_phone(m):
        return " ".join(_KHMER_DIGIT_WORDS[d] for d in m.group(0) if d.isdigit())
    text = re.sub(r"\b0\d{1,3}(?:[ ]\d{2,4}){2,}\b", _spaced_phone, text)

    # --- everything else that is still a number
    text = re.sub(_KH_NUM, lambda m: _khmer_decimal(m.group(0)), text)
    return re.sub(r"  +", " ", text).strip()


# ---------------------------------------------------------------------------
# KHMER LANGUAGE FRONTEND
# The batch pipeline and the studio must speak with one voice: both call
# pipeline/khmer_text.py (normalizer -> abbreviation/pronunciation dictionary ->
# number-by-meaning -> the ស sign -> punctuation/pause plan -> phrase spacing ->
# the user's own lexicon). The old rule set below stays as the fallback for the
# case where the module is missing, so nothing regresses.
# ---------------------------------------------------------------------------
_KT = {"mod": None, "tried": False}


def khmer_text_module():
    if _KT["tried"]:
        return _KT["mod"]
    _KT["tried"] = True
    try:
        import khmer_text as kt
        _KT["mod"] = kt
    except Exception:
        try:
            import importlib.util, os as _os
            here = _os.path.dirname(_os.path.abspath(__file__))
            path = _os.path.join(here, "khmer_text.py")
            spec = importlib.util.spec_from_file_location("khmer_text", path)
            kt = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(kt)
            _KT["mod"] = kt
        except Exception:
            _KT["mod"] = None
    return _KT["mod"]


def lexicon_path():
    import os as _os
    here = _os.path.dirname(_os.path.abspath(__file__))
    return _os.path.join(here, "khmer_lexicon.json")


def normalize_khmer_frontend(text, lexicon=None):
    """The full frontend. Returns (speech, stats, notes, extras)."""
    kt = khmer_text_module()
    src = text or ""
    if kt is None:
        out, stats = normalize_khmer(src, lexicon)
        return out, stats, ["frontend module missing - the simple rules were used"], {}
    if lexicon is None:
        lexicon = kt.load_lexicon(lexicon_path())
    r = kt.prepare(src, lexicon)
    stats = dict(r["stats"])
    stats["segmented"] = True
    extras = {"pause_plan": r["pause_plan"], "repetitions": r["repetitions"],
              "unknown_abbreviations": r["unknown_abbreviations"],
              "low_confidence": r["low_confidence"], "phrased": r["phrased"],
              "source": r["source"]}
    return r["speech"], stats, list(r["notes"]), extras


def normalize_khmer(text, lexicon=None):
    """Pronunciation-safe normalization (the reference rule set — identical to
    Sonora's Khmer pipeline).

    Applies, in order: Khmer digits -> Arabic; %/$/Riel/bare numbers ->
    spoken Khmer words; punctuation tidy-up (repeated stops, smart quotes);
    NFC; control-character removal; word segmentation (khmercut, when
    installed). Never rewrites words — meaning is preserved.
    Returns (normalized_text, stats).
    """
    t = unicodedata.normalize("NFC", text or "")
    stats = {
        "khmer_digits": sum(t.count(k) for k in _KHMER_DIGITS),
        "percent": len(re.findall(r"\d+(?:\.\d+)?\s*%", t)),
        "currency": len(re.findall(r"(\$|\u17DB|\briel)\s*\d", t, re.IGNORECASE)),
        "numbers": len(re.findall(r"\b\d+(?:\.\d+)?\b", t)),
        "segmented": False,
    }
    t = _khmer_phonetics(t)
    # punctuation tidy-up: repeated stops, smart quotes
    t = re.sub(r"([.!?\u17D4]{2,})", lambda m: m.group(1)[0], t)
    t = t.replace("\u201C", '"').replace("\u201D", '"')
    t = t.replace("\u2018", "'").replace("\u2019", "'")
    t = "".join(c for c in t if c.isprintable() or c in "\n\t")
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\ufeff]", "", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r" ?\n ?", "\n", t)
    try:
        import khmercut
        compact = re.sub(r"\s", "", t)
        if len(compact) and sum(1 for c in compact if "\u1780" <= c <= "\u17ff") \
                / len(compact) > 0.3:
            toks = khmercut.tokenize(t)
            out = " ".join(x for x in toks if x and x.strip())
            if out:
                t = out
                stats["segmented"] = True
    except Exception:
        pass
    return t.strip(), stats



    """Pronunciation-safe normalization (the reference rule set).

    Applies, in order: Khmer digits -> Arabic; %/$/Riel/bare numbers ->
    spoken Khmer words; punctuation tidy-up (repeated stops, smart quotes);
    NFC; control-character removal; word segmentation (khmercut, when
    installed). Never rewrites words — meaning is preserved.
    Returns (normalized_text, stats).
    """
    stats = {"khmer_digits": 0, "percent": 0, "currency": 0, "numbers": 0,
             "segmented": False}
    t = unicodedata.normalize("NFC", text or "")
    for k, a in _KHMER_DIGITS.items():
        stats["khmer_digits"] += t.count(k)
        t = t.replace(k, a)
    t, n = re.subn(r"(\d+(?:\.\d+)?)\s*%",
                   lambda m: " " + _khmer_decimal(m.group(1)) + " \u179B\u1799\u1795\u1791", t)
    stats["percent"] = n
    for sym, name in ((r"\$", "\u1793\u17D2\u179A\u1792\u1789"),
                      (r"\u17DB", "\u1792\u17D2\u178F"),
                      (r"(?<![A-Za-z])riel", "\u1792\u17D2\u178F")):
        t, n = re.subn(sym + r"\s*(\d+(?:\.\d+)?)",
                       lambda m, nm=name: " " + _khmer_decimal(m.group(1)) + " " + nm,
                       t, flags=re.IGNORECASE)
        stats["currency"] += n
    t, n = re.subn(r"\b\d+(?:\.\d+)?\b", lambda m: _khmer_decimal(m.group(0)), t)
    stats["numbers"] = n
    # punctuation tidy-up: repeated stops, smart quotes, straighten brackets
    t = re.sub(r"([.!?%s]{2,})" % KHMER_STOP, lambda m: m.group(1)[0], t)
    t = re.sub(r"([.!?]{3,})", r"\1\1", t)
    t = t.replace("\u201C", '"').replace("\u201D", '"')
    t = t.replace("\u2018", "'").replace("\u2019", "'")
    t = "".join(c for c in t if c.isprintable() or c in "\n\t")
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\ufeff]", "", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r" ?\n ?", "\n", t)
    try:
        import khmercut
        compact = re.sub(r"\s", "", t)
        if len(compact) and sum(1 for c in compact if "\u1780" <= c <= "\u17ff") \
                / len(compact) > 0.3:
            toks = khmercut.tokenize(t)
            out = " ".join(x for x in toks if x and x.strip())
            if out:
                t = out
                stats["segmented"] = True
    except Exception:
        pass
    return t.strip(), stats


_CHAPTER_RE = re.compile(
    r"^\s*(?:(?:[Cc][Hh]\.?\s*)|(?:[Cc][Hh][Aa][Pp][Tt][Ee][Rr]\s+)|(?:\u178A\u17ED\u179A\u17D2\u1785))"
    r"\s*([0-9\u17E0-\u17E9]+)\b", re.MULTILINE)


def parse_chapters(text):
    """Split the script into [(num, title, body)].

    A chapter starts at a line like 'Chapter 1', 'CH. 2', 'CHAPTER 10: ...'
    or Khmer '\u178A\u17ED\u179A\u17D2\u1785 5'. No headers -> single chapter 1.
    Text before the first header (if any) becomes chapter 0 (preamble).
    """
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    marks = []
    for m in _CHAPTER_RE.finditer(text):
        num = int(khmer_digits_to_arabic(m.group(1)))
        marks.append((m.start(), num, m.end()))
    if not marks:
        return [(1, "", text.strip())]
    out = []
    if marks[0][0] > 0 and text[:marks[0][0]].strip():
        out.append((0, "preamble", text[:marks[0][0]].strip()))
    for i, (start, num, end) in enumerate(marks):
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        line_end = text.find("\n", end)
        if line_end == -1 or line_end > stop:
            line_end = stop
        # the header line itself (number + title) is NOT spoken — it only
        # labels the chapter; body starts at the next line
        title = re.sub(r"^[:\u00A0\s-]+", "", text[end:line_end]).strip()
        out.append((num, title, text[line_end:stop].strip()))
    return [(n, t, b) for n, t, b in out if b.strip()]


def split_sentences(body):
    """Sentence list — never splits inside a sentence."""
    body = (body or "").strip()
    if not body:
        return []
    out = []
    for para in [p.strip() for p in body.split("\n") if p.strip()]:
        para = re.sub(r"^\s*(?:-|\*|\u2022)\s+", "", para)  # list markers
        pieces = [p.strip() for p in re.findall(
            r"[^.!?%s\u0E40]*[.!?%s\u0E40]*" % (KHMER_STOP, KHMER_STOP), para)
            if p.strip()]
        out.extend(pieces or [para])
    return [p for p in (s.strip() for s in out) if p]


def group_chunks(sentences, max_per_chunk=4, max_chars=280):
    """1-4 sentences per chunk, split only at sentence boundaries."""
    chunks = []
    cur = ""
    n = 0
    for s in sentences:
        if cur and (n >= max_per_chunk or len(cur) + len(s) + 1 > max_chars):
            chunks.append(cur.strip())
            cur, n = "", 0
        cur = (cur + " " + s).strip() if cur else s
        n += 1
        if len(s) > max_chars:  # one very long sentence: give it its own chunk
            chunks.append(s)
            cur, n = "", 0
    if cur:
        chunks.append(cur)
    return [c for c in (x.strip() for x in chunks) if c]


# ================================================================ audio ===

def find_ffmpeg(cfg=None):
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    if cfg:
        c = Path(cfg.get("rvc_root") or "") / "ffmpeg.exe"
        if c.exists():
            return str(c)
    return None


def read_wav_f32(path):
    """(sr, mono float32 numpy array)"""
    import numpy as np
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        width = w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if width == 2:
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        data = np.frombuffer(frames, dtype=np.uint8).astype(np.float32)
        data = (data - 128.0) / 128.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return sr, data


def write_wav(path, data, sr):
    """data: numpy array (int16 or float32) or bytes. Writes 16-bit PCM mono."""
    import numpy as np
    if isinstance(data, (bytes, bytearray)):
        arr = np.frombuffer(bytes(data), dtype=np.int16)
    else:
        arr = np.asarray(data)
        if np.issubdtype(arr.dtype, np.floating):
            arr = np.clip(arr, -1.0, 1.0)
            arr = (arr * 32767.0).astype(np.int16)
        else:
            arr = arr.astype(np.int16)
    if arr.ndim > 1:
        arr = arr.mean(axis=1).astype(np.int16)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(arr.tobytes())


def validate_wav(path, min_seconds=0.2):
    """Spec section 16. Returns (ok, info, problems)."""
    path = Path(path)
    problems = []
    info = {"path": str(path)}
    if not path.exists():
        return False, info, ["file missing"]
    size = path.stat().st_size
    info["size"] = size
    if size == 0:
        return False, info, ["zero-byte file"]
    try:
        with wave.open(str(path), "rb") as w:
            sr = w.getframerate()
            ch = w.getnchannels()
            nf = w.getnframes()
            width = w.getsampwidth()
        info.update({"sr": sr, "channels": ch, "frames": nf, "width": width})
        dur = nf / float(sr) if sr else 0.0
        info["duration"] = round(dur, 3)
        if sr < 8000:
            problems.append(f"implausible sample rate {sr}")
        if ch not in (1, 2):
            problems.append(f"unexpected channel count {ch}")
        if dur <= 0:
            problems.append("zero duration")
        elif dur < min_seconds:
            problems.append(f"too short ({dur:.2f}s) — likely truncated")
        if not problems:
            import numpy as np
            _, data = read_wav_f32(path)
            peak = float(np.abs(data).max()) if data.size else 0.0
            rms = float(np.sqrt((data ** 2).mean())) if data.size else 0.0
            info["peak"] = round(peak, 4)
            info["rms"] = round(rms, 5)
            if peak > 0.999:
                problems.append("clipping (peak at full scale)")
            if rms < 0.002:
                problems.append("silent or near-silent")
            elif rms < 0.01:
                info["warning"] = "very low level"
    except Exception as e:
        problems.append(f"cannot open as WAV: {e}")
    return (not problems and info.get("duration", 0) > 0), info, problems


def mp3_to_wav(cfg, mp3_path, wav_path, rate=24000):
    ff = find_ffmpeg(cfg)
    if not ff:
        raise RuntimeError("ffmpeg not found (install it or pip install imageio-ffmpeg)")
    import subprocess
    tmp = Path(str(wav_path) + ".part")
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(mp3_path),
                        "-ar", str(rate), "-ac", "1", "-c:a", "pcm_s16le",
                        "-f", "wav", str(tmp)], capture_output=True, timeout=600)
    if r.returncode != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        raise RuntimeError("ffmpeg failed: " + r.stderr.decode("utf-8", "ignore")[:200])
    os.replace(tmp, wav_path)


def atomic_audio(target, produce):
    """produce(tmp_path) writes the candidate file; validate happens in the
    caller; then it is moved into place. A failed run leaves no partial file
    at the final name."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    if tmp.exists():
        tmp.unlink()
    produce(tmp)
    os.replace(tmp, target)
    return target


def retry_call(fn, retries=2, base_delay=3.0, label=""):
    """Initial attempt + up to `retries` retries (spec section 18).
    Returns (result, attempts, last_error)."""
    last = None
    for attempt in range(retries + 1):
        try:
            return fn(), attempt + 1, None
        except Exception as e:
            last = e
            if attempt < retries:
                time.sleep(base_delay * (attempt + 1))
    return None, retries + 1, last


def write_listen_page(directory, title, groups, note=""):
    """Write listen.html — a plain local page with play buttons, so you can
    hear the results without any server. Open it by double-clicking.

    groups: [(heading, [(label, relative_path), ...]), ...]
    """
    import html as _html
    rows = []
    for heading, items in groups:
        rows.append(f'<h2>{_html.escape(heading)}</h2>')
        for label, rel in items:
            rows.append(
                '<div class="row"><div class="lbl">' + _html.escape(label)
                + '</div><audio controls preload="none" src="'
                + _html.escape(rel) + '"></audio></div>')
    doc = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>""" + _html.escape(title) + """</title>
<style>
 body{background:#0f1115;color:#e8eaf0;font:15px/1.5 system-ui,Segoe UI,sans-serif;
      margin:0;padding:28px 32px;max-width:900px}
 h1{font-size:20px;margin:0 0 6px;letter-spacing:.02em}
 h2{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#9aa3b2;
    margin:26px 0 8px;border-bottom:1px solid #232833;padding-bottom:6px}
 .row{display:flex;align-items:center;gap:14px;background:#161a22;border:1px solid #232833;
      border-radius:10px;padding:10px 14px;margin:6px 0}
 .lbl{flex:0 0 260px;color:#cfd6e4}
 audio{width:100%;height:34px}
 .note{color:#9aa3b2;font-size:13px;margin-top:22px;border-top:1px solid #232833;padding-top:12px}
</style></head><body>
<h1>""" + _html.escape(title) + """</h1>
""" + "\n".join(rows) + """
<div class="note">""" + _html.escape(note) + """</div>
</body></html>
"""
    p = Path(directory) / "listen.html"
    p.write_text(doc, encoding="utf-8")
    return p


def report_line(ok, tag, detail):
    print(f"[{'OK' if ok else 'FAIL'}]   {tag}: {detail}")
    return ok


# =============================================================== RVC =======

def resolve_index(cfg):
    """Exact index path from config (absolute, or relative to rvc_root).
    Spec 38: if it does not exist -> raise; never invent a replacement."""
    raw = cfg.get("index_file") or ""
    p = Path(raw)
    if not p.is_absolute():
        p = Path(cfg.get("rvc_root") or "") / raw
    if not p.exists():
        raise FileNotFoundError(
            "index file not found: " + str(p) + "\n"
            "Expected location: <rvc_root>\\assets\\indices\\Sonaro-kh_added_IVF248_Flat_nprobe_1_Sonaro-kh_v2.index\n"
            "Required information: the exact .index path from your RVC-WebUI "
            "(Feature index path field). Not creating a replacement.")
    return str(p)


def resolve_model(cfg):
    """(path, how). Config value first; if absent/missing, discover *.pth in
    the RVC weights folders. Multiple candidates -> raise (spec 37: ask)."""
    mf = (cfg.get("model_file") or "").strip()
    root = Path(cfg.get("rvc_root") or "")
    if mf:
        p = Path(mf)
        if not p.is_absolute():
            p = root / mf
        if p.exists():
            return str(p), "config"
        raise FileNotFoundError("configured model not found: " + str(p))
    found = []
    for sub in (root / "assets" / "weights", root / "weights"):
        if sub.is_dir():
            found += sorted(sub.glob("*.pth"))
    if len(found) == 1:
        return str(found[0]), "discovered"
    if len(found) > 1:
        raise RuntimeError(
            "multiple .pth models found — set config \"model_file\" to the "
            "correct Sonaro Khmer one:\n  " + "\n  ".join(str(f) for f in found))
    raise FileNotFoundError("no .pth model found under " + str(root))


def detect_rvc_python(cfg):
    """Config rvc_python, else any python under the RVC folder that has torch
    (venv, embedded python, integrated-pack runtime folder), else None — the
    caller then falls back to the current interpreter."""
    py = (cfg.get("rvc_python") or "").strip()
    if py:
        return py if os.path.exists(py) else None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import find_rvc_python as FRP
        best, _ = FRP.find(cfg.get("rvc_root") or "", "", include_self=False)
        return best
    except Exception:
        pass
    root = Path(cfg.get("rvc_root") or "")
    for rel in ("venv/Scripts/python.exe", "venv/bin/python",
                ".venv/Scripts/python.exe", ".venv/bin/python"):
        p = root / rel
        if p.exists():
            return str(p)
    return None


def detect_rvc_api(rvc_root):
    """Which VC module layout the installation has (verified dual-generation
    list from the RVC source). Returns module name or None."""
    root = Path(rvc_root or "")
    for mod in ("infer.vc.modules", "infer.modules.vc.modules"):
        if (root / (mod.replace(".", "/") + ".py")).exists():
            return mod
    return None
