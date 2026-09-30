#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""khmer_expressive.py — LAYER 3/4 of the Khmer narration engine.

THE FOUR LAYERS (a TTS model is only the last one):

    1  KHMER LANGUAGE       khmer_text.py    normalization, abbreviations,
                                             numbers by meaning, ស sign, pause
                                             levels, spacing, the user lexicon
    2  PRONUNCIATION        khmer_text.py    spelling -> the words a narrator
                                             actually says (គ.ស. -> គ្រិស្តសករាជ,
                                             8% -> ប្រាំបីភាគរយ, 010.. -> digits)
    3  PROSODY / PERFORMANCE  this file       pitch + energy + duration/rate +
                                             pause + rhythm + emphasis + voice
                                             quality, per sentence and INSIDE a
                                             sentence, for all 14 styles
    4  TTS                  the engine       renders what layers 1-3 decided

RULES THIS LAYER OBEYS (from the expressive specification):

* A style is a whole performance, not a label: it fixes the emotional band,
  the amount of contrast, the pause policy and the voice quality.
* Every sentence carries an emotion, an intensity (0-100) and a delivery
  intention; no sentence is allowed to be flat.
* Emotions change INSIDE a sentence: a contrast word (ប៉ុន្តែ, តែ, ផ្ទុយទៅវិញ,
  ដូច្នេះ ...) turns the emotion there, and a quoted line is performed as
  dialogue, not as narration.
* An emotional arc runs through the whole piece: opening -> build -> turn ->
  climax -> release. The climax is chosen, never reached by accident.
* Restraint: no constant drama (a hard cap on how much of the piece may sit at
  high intensity), no whisper everywhere, no constant breath, no singing
  (rate/pitch stay inside a human speaking band).

CLI
    python khmer_expressive.py --text "…" --style cinematic
    python khmer_expressive.py --in file.txt --style sad_romantic --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

try:
    import khmer_text as KT
except Exception:                                     # pragma: no cover
    KT = None

try:
    import narration as NAR                            # the 13 shipped styles
except Exception:                                     # pragma: no cover
    NAR = None

#: the ONE identity rule both performance engines obey (see narration.py).
#: A style or an emotion may change pace, energy, pauses, breath, emphasis and
#: the direction of the pitch — never the register or the loudness of the voice.
try:
    import delivery as _DL                             # the FEELING layer (14 styles)
except Exception:                                      # pragma: no cover
    _DL = None

try:
    from narration import (IDENTITY_PITCH_ST, IDENTITY_GAIN_DB, IDENTITY_RATE,
                           identity_guard, VOICE_LOCK, style_delivery,
                           STYLE_PACE_TOL, STYLE_GAIN_TOL, STYLE_GAIN_CAP)
except Exception:                                     # pragma: no cover
    IDENTITY_PITCH_ST, IDENTITY_GAIN_DB = 0.25, 0.8
    IDENTITY_RATE = (0.94, 1.06)
    STYLE_PACE_TOL, STYLE_GAIN_TOL, STYLE_GAIN_CAP = 0.03, 0.5, 1.6
    VOICE_LOCK = True

    def style_delivery(style):
        return dict(pace=1.0, gain_db=0.0, hint="base read")

    def identity_guard(pitch_st, gain_db, rate):
        import math
        cap, gcap = IDENTITY_PITCH_ST, IDENTITY_GAIN_DB
        return (round(cap * math.tanh(float(pitch_st) / cap), 3),
                round(gcap * math.tanh(float(gain_db) / gcap), 2),
                round(max(IDENTITY_RATE[0], min(IDENTITY_RATE[1],
                                                float(rate))), 4))


# ============================================================== emotions =====
# name -> channels. Values are BOUNDS, not constants: the guard stage keeps the
# performance inside them, so nothing is ever 100% one emotion.
#
#   pitch   semitones around the speaker's own pitch
#   span    how far the pitch may travel inside one sentence (semitones)
#   rate    speech rate multiplier
#   energy  loudness in dB around the mix norm
#   pause   multiplier on every planned pause
#   breath  how audible the breath is (0 = closed, 1 = near-whisper air)
#   tension 0 = relaxed/soft voice, 1 = pressed/tense voice
#   push    how much the sentence presses FORWARD (drive, momentum)
EMOTIONS = {
    # ---- calm / warm family -------------------------------------------------
    "neutral":      dict(pitch=(0.0, 0.3), span=1.2, rate=(0.98, 1.02), energy=(-0.5, 0.5), pause=1.00, breath=0.10, tension=0.15, push=0.30, family="calm"),
    "calm":         dict(pitch=(-0.7, 0.0), span=0.9, rate=(0.92, 0.98), energy=(-1.6, -0.4), pause=1.20, breath=0.14, tension=0.08, push=0.15, family="calm"),
    "warm":         dict(pitch=(0.1, 0.8), span=1.6, rate=(0.94, 1.00), energy=(-1.0, 0.6), pause=1.08, breath=0.20, tension=0.10, push=0.30, family="calm"),
    "tender":       dict(pitch=(0.2, 1.0), span=1.4, rate=(0.88, 0.96), energy=(-2.2, -0.6), pause=1.28, breath=0.34, tension=0.06, push=0.20, family="tender"),
    "affectionate": dict(pitch=(0.4, 1.3), span=1.8, rate=(0.92, 1.00), energy=(-1.4, 0.4), pause=1.12, breath=0.26, tension=0.08, push=0.34, family="tender"),
    "compassionate": dict(pitch=(-0.4, 0.6), span=1.5, rate=(0.90, 0.98), energy=(-1.8, -0.2), pause=1.18, breath=0.24, tension=0.12, push=0.26, family="tender"),
    "reverent":     dict(pitch=(-1.0, -0.1), span=1.1, rate=(0.86, 0.94), energy=(-2.0, -0.6), pause=1.35, breath=0.18, tension=0.10, push=0.20, family="solemn"),
    "solemn":       dict(pitch=(-1.2, -0.2), span=1.0, rate=(0.84, 0.92), energy=(-1.8, -0.2), pause=1.40, breath=0.12, tension=0.20, push=0.22, family="solemn"),
    "mysterious":   dict(pitch=(-1.4, -0.3), span=1.3, rate=(0.84, 0.93), energy=(-2.2, -0.6), pause=1.45, breath=0.30, tension=0.18, push=0.24, family="mystery"),

    # ---- bright / high energy ----------------------------------------------
    "joyful":       dict(pitch=(0.8, 2.2), span=2.6, rate=(1.02, 1.12), energy=(0.4, 2.2), pause=0.86, breath=0.16, tension=0.12, push=0.72, family="bright"),
    "playful":      dict(pitch=(0.6, 2.0), span=2.8, rate=(1.00, 1.12), energy=(0.2, 1.8), pause=0.84, breath=0.18, tension=0.10, push=0.68, family="bright"),
    "amused":       dict(pitch=(0.3, 1.6), span=2.2, rate=(0.98, 1.08), energy=(-0.2, 1.4), pause=0.92, breath=0.22, tension=0.10, push=0.55, family="bright"),
    "hopeful":      dict(pitch=(0.3, 1.5), span=2.0, rate=(0.96, 1.04), energy=(-0.6, 1.0), pause=1.02, breath=0.18, tension=0.12, push=0.48, family="bright"),
    "proud":        dict(pitch=(0.2, 1.2), span=1.8, rate=(0.94, 1.02), energy=(0.0, 1.6), pause=1.06, breath=0.12, tension=0.26, push=0.60, family="bright"),
    "inspired":     dict(pitch=(0.4, 1.8), span=2.4, rate=(0.96, 1.06), energy=(-0.2, 1.8), pause=1.00, breath=0.16, tension=0.20, push=0.70, family="bright"),
    "triumphant":   dict(pitch=(0.6, 2.4), span=3.0, rate=(0.96, 1.08), energy=(0.8, 2.8), pause=1.10, breath=0.10, tension=0.32, push=0.86, family="bright"),
    "relieved":     dict(pitch=(-0.2, 0.8), span=2.0, rate=(0.94, 1.04), energy=(-0.8, 0.8), pause=1.12, breath=0.26, tension=0.06, push=0.34, family="bright"),

    # ---- thinking / explaining ---------------------------------------------
    "informative":  dict(pitch=(0.0, 0.5), span=1.4, rate=(0.98, 1.05), energy=(-0.6, 0.6), pause=1.05, breath=0.10, tension=0.14, push=0.44, family="informative"),
    "formal":       dict(pitch=(-0.4, 0.2), span=1.1, rate=(0.96, 1.02), energy=(-0.8, 0.4), pause=1.10, breath=0.08, tension=0.20, push=0.40, family="informative"),
    "curious":      dict(pitch=(0.2, 1.2), span=2.0, rate=(0.98, 1.08), energy=(-0.6, 0.8), pause=0.98, breath=0.16, tension=0.12, push=0.52, family="informative"),
    "thoughtful":   dict(pitch=(-0.6, 0.2), span=1.4, rate=(0.90, 0.98), energy=(-1.6, -0.2), pause=1.26, breath=0.18, tension=0.12, push=0.22, family="informative"),
    "conclusive":   dict(pitch=(-0.3, 0.4), span=1.3, rate=(0.94, 1.00), energy=(-0.2, 1.2), pause=1.22, breath=0.10, tension=0.24, push=0.62, family="informative"),
    "determined":   dict(pitch=(0.0, 1.0), span=1.5, rate=(0.98, 1.06), energy=(0.2, 1.8), pause=0.94, breath=0.08, tension=0.40, push=0.78, family="driven"),
    "confident":    dict(pitch=(-0.1, 0.7), span=1.4, rate=(0.96, 1.03), energy=(-0.2, 1.2), pause=1.02, breath=0.08, tension=0.30, push=0.62, family="driven"),
    "urgent":       dict(pitch=(0.2, 1.4), span=1.8, rate=(1.06, 1.16), energy=(0.4, 2.2), pause=0.72, breath=0.14, tension=0.46, push=0.92, family="driven"),

    # ---- longing / melancholy ----------------------------------------------
    "nostalgic":    dict(pitch=(-0.8, 0.3), span=1.6, rate=(0.88, 0.96), energy=(-2.0, -0.4), pause=1.30, breath=0.28, tension=0.10, push=0.22, family="tender"),
    "wistful":      dict(pitch=(-1.0, 0.1), span=1.5, rate=(0.86, 0.94), energy=(-2.2, -0.6), pause=1.34, breath=0.30, tension=0.08, push=0.18, family="tender"),
    "longing":      dict(pitch=(-0.4, 0.6), span=1.9, rate=(0.86, 0.95), energy=(-2.0, -0.2), pause=1.30, breath=0.34, tension=0.16, push=0.28, family="tender"),
    "romantic":     dict(pitch=(0.1, 1.1), span=1.9, rate=(0.87, 0.95), energy=(-2.0, -0.2), pause=1.26, breath=0.36, tension=0.14, push=0.30, family="tender"),
    "bittersweet":  dict(pitch=(-0.6, 0.5), span=1.8, rate=(0.88, 0.96), energy=(-1.9, -0.1), pause=1.28, breath=0.30, tension=0.14, push=0.26, family="tender"),
    "melancholic":  dict(pitch=(-1.2, -0.1), span=1.3, rate=(0.84, 0.93), energy=(-2.4, -0.8), pause=1.38, breath=0.28, tension=0.12, push=0.16, family="sad"),
    "sad":          dict(pitch=(-1.2, -0.2), span=1.4, rate=(0.84, 0.93), energy=(-2.2, -0.6), pause=1.34, breath=0.30, tension=0.18, push=0.18, family="sad"),
    "grieving":     dict(pitch=(-1.6, -0.4), span=1.6, rate=(0.78, 0.90), energy=(-2.6, -0.8), pause=1.50, breath=0.40, tension=0.34, push=0.14, family="sad"),
    "heartbroken":  dict(pitch=(-1.8, -0.5), span=1.8, rate=(0.76, 0.90), energy=(-2.6, -0.6), pause=1.50, breath=0.42, tension=0.38, push=0.14, family="sad"),
    "regretful":    dict(pitch=(-1.3, -0.3), span=1.5, rate=(0.82, 0.92), energy=(-2.3, -0.7), pause=1.42, breath=0.32, tension=0.20, push=0.16, family="sad"),
    "lonely":       dict(pitch=(-1.4, -0.4), span=1.2, rate=(0.80, 0.90), energy=(-2.6, -1.0), pause=1.52, breath=0.38, tension=0.14, push=0.12, family="sad"),
    "exhausted":    dict(pitch=(-1.5, -0.4), span=1.1, rate=(0.80, 0.90), energy=(-2.6, -1.0), pause=1.48, breath=0.44, tension=0.06, push=0.10, family="sad"),

    # ---- fear / tension -----------------------------------------------------
    "anxious":      dict(pitch=(0.2, 1.4), span=2.2, rate=(1.02, 1.14), energy=(-1.0, 0.8), pause=0.86, breath=0.34, tension=0.52, push=0.66, family="fear"),
    "worried":      dict(pitch=(-0.2, 0.9), span=1.9, rate=(0.94, 1.06), energy=(-1.2, 0.4), pause=1.10, breath=0.30, tension=0.46, push=0.48, family="fear"),
    "fearful":      dict(pitch=(0.6, 2.0), span=2.6, rate=(1.00, 1.14), energy=(-0.6, 1.4), pause=0.92, breath=0.44, tension=0.64, push=0.72, family="fear"),
    "terrified":    dict(pitch=(1.0, 3.0), span=3.4, rate=(1.04, 1.20), energy=(0.2, 2.4), pause=0.78, breath=0.50, tension=0.80, push=0.90, family="fear"),
    "tense":        dict(pitch=(0.0, 1.0), span=1.4, rate=(0.92, 1.02), energy=(-0.8, 1.0), pause=1.16, breath=0.22, tension=0.72, push=0.58, family="fear"),
    "suspense":     dict(pitch=(-0.6, 0.6), span=1.4, rate=(0.80, 0.92), energy=(-1.8, 0.2), pause=1.55, breath=0.24, tension=0.66, push=0.30, family="fear"),
    "dread":        dict(pitch=(-1.4, -0.2), span=1.3, rate=(0.78, 0.90), energy=(-2.2, -0.2), pause=1.60, breath=0.30, tension=0.70, push=0.24, family="fear"),

    # ---- anger / conflict ---------------------------------------------------
    "angry":        dict(pitch=(0.6, 2.0), span=2.4, rate=(1.00, 1.12), energy=(0.8, 2.6), pause=0.82, breath=0.10, tension=0.78, push=0.88, family="anger"),
    "frustrated":   dict(pitch=(0.2, 1.4), span=2.0, rate=(0.96, 1.08), energy=(0.0, 1.8), pause=0.92, breath=0.16, tension=0.62, push=0.70, family="anger"),
    "defiant":      dict(pitch=(0.4, 1.6), span=2.0, rate=(0.96, 1.06), energy=(0.4, 2.2), pause=1.00, breath=0.10, tension=0.58, push=0.84, family="anger"),
    "desperate":    dict(pitch=(0.2, 1.8), span=2.4, rate=(0.94, 1.10), energy=(-0.6, 1.6), pause=0.94, breath=0.42, tension=0.66, push=0.76, family="anger"),

    # ---- surprise / awe -----------------------------------------------------
    "surprised":    dict(pitch=(0.6, 2.2), span=2.8, rate=(1.00, 1.12), energy=(0.0, 1.8), pause=0.94, breath=0.24, tension=0.30, push=0.70, family="awe"),
    "awed":         dict(pitch=(0.2, 1.6), span=2.2, rate=(0.84, 0.94), energy=(-1.0, 1.0), pause=1.36, breath=0.28, tension=0.16, push=0.34, family="awe"),
    "revelation":   dict(pitch=(-0.2, 1.2), span=1.8, rate=(0.80, 0.92), energy=(-0.8, 1.2), pause=1.62, breath=0.18, tension=0.34, push=0.40, family="awe"),
    "epic":         dict(pitch=(0.0, 1.4), span=2.2, rate=(0.88, 0.98), energy=(0.0, 2.2), pause=1.30, breath=0.14, tension=0.30, push=0.66, family="awe"),
}

EMOTION_FAMILIES = {}
for _n, _e in EMOTIONS.items():
    EMOTION_FAMILIES.setdefault(_e["family"], []).append(_n)

#: which emotion a sentence falls back to when nothing more specific is found
STYLE_DEFAULT_EMOTION = {
    "natural": "neutral", "storytelling": "warm", "novel": "thoughtful",
    "documentary": "informative", "trailer": "epic", "audiobook": "warm",
    "news": "formal", "explainer": "informative", "thriller": "suspense",
    "meditation": "calm", "inner_monologue": "thoughtful",
    "sad_romantic": "romantic", "cinematic": "bittersweet",
}

#: the emotion a style turns to when the text turns (contrast / stakes / end)
STYLE_TURN_EMOTION = {
    "natural": "surprised", "storytelling": "curious", "novel": "tense",
    "documentary": "revelation", "trailer": "triumphant", "audiobook": "thoughtful",
    "news": "informative", "explainer": "conclusive", "thriller": "fearful",
    "meditation": "awed", "inner_monologue": "longing",
    "sad_romantic": "heartbroken", "cinematic": "heartbroken",
}

#: styles allowed to use near-whisper delivery (the spec forbids it everywhere)
#: EMPTY — the whisper stage is removed (build 2026-09-30n). This set used to
#: name the styles allowed near-whisper air; the user's report was that the
#: whisper arrived mid-read, louder than the sentence it replaced, in every
#: voice. Nothing may go near-whisper now, so every style takes the capped
#: branch below (air ≤ 0.30 — audible breath, normal voice).
WHISPER_STYLES = set()

#: nothing whispers a whole piece any more (the sustained-whisper style was
#: removed at the user's request): every whisper here is the brief moment the
#: WHISPER RULE allows
SUSTAINED_WHISPER_STYLES = set()


# ======================================================= language signals ====
#: a contrast word turns the emotion of the clause that follows it
SHIFT_MARKERS = {
    "ប៉ុន្តែ": "turn", "តែ": "turn", "ផ្ទុយទៅវិញ": "turn", "ផ្ទុយមកវិញ": "turn",
    "ទោះបីជា": "turn", "ទោះជាយ៉ាងណា": "turn", "យ៉ាងណាក៏ដោយ": "turn",
    "ដូច្នេះ": "result", "ហេតុនេះ": "result", "ព្រោះ": "result",
    "ដោយសារតែ": "result", "ដោយសារ": "result", "សរុបមក": "result",
    "ចុងក្រោយ": "result", "ក្រោយមក": "result", "បន្ទាប់មក": "result",
    "ស្រាប់តែ": "shock", "ភ្លាមៗ": "shock", "មិនគួរឱ្យជឿ": "shock",
    "ជាការពិត": "confirm", "ពិតប្រាកដ": "confirm", "ការពិត": "confirm",
    "ហើយ": "add",
}
#: words that carry the sentence's feeling and must be stressed
STRESS_WORDS = (
    "ស្លាប់", "ឈឺចាប់", "ស្រលាញ់", "ស្រឡាញ់", "ចងចាំ", "អាណិត", "ខឹង", "ភ័យ",
    "ខ្លាច", "សង្ឃឹម", "អស់សង្ឃឹម", "ឈ្នះ", "ចាញ់", "បាត់បង់", "រកឃើញ",
    "ពិត", "កុហក", "ដ៏អស្ចារ្យ", "អស្ចារ្យ", "គ្រោះថ្នាក់", "សង្គ្រាម",
    "សន្តិភាព", "ឯករាជ្យ", "ដ៏ធំ", "ដ៏ខ្ពស់", "ដ៏ស្រស់ស្អាត", "នឹក",
    "យំ", "ញញឹម", "ព្រះ", "អច្ឆរិយៈ", "អាថ៌កំបាំង", "ជ័យជម្នះ",
)
#: never stressed — function words are what makes a machine read sound robotic
NO_STRESS = {"និង", "ឬ", "ដែល", "ដោយ", "នៅ", "ក្នុង", "លើ", "ក្រោម", "ពី",
             "ទៅ", "មក", "គឺ", "ជា", "នេះ", "នោះ", "បាន", "នឹង", "ក៏"}

QUOTE_RE = re.compile(r"[“\"'](.+?)[”\"']")
SENT_SPLIT = re.compile(r"(?<=[.!?។៕៖])\s+")
CLAUSE_SPLIT = re.compile(r"(?<=[,;៖])\s+")


def _style_id(style):
    if NAR is not None:
        try:
            return NAR.style_id(style)
        except Exception:
            pass
    return str(style or "natural").strip().lower().replace("-", "_") or "natural"


def _spec(style):
    if NAR is not None:
        try:
            return NAR.spec(style)
        except Exception:
            pass
    return {"label": _style_id(style), "intensity": (10, 60), "base": 30}


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _mid(band):
    return (band[0] + band[1]) / 2.0


# ============================================================ the planner ====

def emo(name):
    """The channel table of an emotion (never raises; unknown -> neutral)."""
    return EMOTIONS.get(str(name or "").strip().lower(), EMOTIONS["neutral"])


def emphases(text):
    """The words the performance must stress (content words only)."""
    out = []
    for w in re.split(r"\s+", text or ""):
        core = w.strip(".,!?។៕៖;:…”\"'()")
        if not core or core in NO_STRESS:
            continue
        if KT is not None and core in KT.PROTECTED_TITLES:
            continue                      # a title is not a stressed word
        if core in STRESS_WORDS or (len(core) >= 6 and KT is not None
                                    and core in KT.PROTECTED_NAMES):
            out.append(core)
        elif any(core.startswith(s) for s in STRESS_WORDS) and len(core) >= 4:
            out.append(core)
    return out[:3]


def shifts(sentence):
    """Emotion changes INSIDE one sentence.

    Returns [(index_in_text, kind, marker)] — 'kind' is turn / result / shock /
    confirm / add. A sentence with a contrast word is never performed in one
    colour; the clause after the marker gets a different emotion.
    """
    out = []
    for m in re.finditer(r"\s+|^", sentence or ""):
        pass
    for marker, kind in SHIFT_MARKERS.items():
        for m in re.finditer(re.escape(marker), sentence or ""):
            at = m.start()
            before = sentence[max(0, at - 1):at]
            if before and ("\u1780" <= before <= "\u17ff"):
                continue                      # part of a longer word
            out.append((at, kind, marker))
    out.sort()
    # keep the first marker of each kind: an avalanche of ហើយ is not a change
    seen, keep = set(), []
    for at, kind, marker in out:
        if kind in seen and kind in ("add", "result"):
            continue
        seen.add(kind)
        keep.append((at, kind, marker))
    return keep[:4]


def choose_emotion(style, sentence, kind=None, position=None, intensity=None,
                   avoid=None):
    """The emotion for one clause/sentence.

    ONE detector for the whole engine: the studio renders through narration.py,
    the inspection API renders through here — if the two disagreed, the sheet
    would describe a performance nobody hears. narration.detect_emotion() is
    therefore the first word; the rules below only fill the gaps it leaves.
    """
    sid = _style_id(style)
    if NAR is not None and hasattr(NAR, "detect_emotion"):
        try:
            det = NAR.detect_emotion(sentence, style, is_dialogue=None)
            pri = det.get("primary")
            from narration import EMOTION_ALIASES
            key = EMOTION_ALIASES.get(pri, pri)
            if kind in ("turn", "shock"):
                # the contrast word itself is the change: if the clause carries
                # no NEW feeling (it repeats the sentence's own colour), the
                # turn decides — that is where the listener hears the shift
                turn = STYLE_TURN_EMOTION.get(sid)
                if (not pri or pri == "neutral" or key == avoid) and turn in EMOTIONS:
                    return "surprised" if kind == "shock" else turn
            if pri and pri != "neutral":
                if key in EMOTIONS:
                    return key
            # neutral is neutral in BOTH engines: the style's own colour is a
            # property of the plan (rate/energy/frame), not of the emotion name
            if pri == "neutral" and kind in ("turn", "shock"):
                turn = STYLE_TURN_EMOTION.get(sid)
                if turn in EMOTIONS:
                    return turn
            if pri:
                return "neutral"
        except Exception:
            pass
    base = STYLE_DEFAULT_EMOTION.get(sid, "neutral")
    turn = STYLE_TURN_EMOTION.get(sid, "tense")
    low = (sentence or "").lower()
    n = len(sentence or "")

    # questions ask, quotes perform, exclamations lift
    stripped = (sentence or "").strip()
    if kind == "shock":
        return "surprised"
    if kind == "turn":
        return turn
    if kind == "result":
        return "conclusive" if sid in ("explainer", "documentary", "news") else base
    if stripped.endswith("?") or "?" in stripped[-3:]:
        return "curious" if sid in ("explainer", "documentary", "natural") else "worried"
    if stripped.endswith("!") or "!" in stripped[-3:]:
        return "urgent" if sid in ("news", "trailer", "thriller") else "surprised"
    if re.search(r"(មិន|គ្មាន|កុំ|ហាម)", stripped) and sid in ("sad_romantic", "cinematic"):
        return "regretful"
    if any(k in stripped for k in ("ស្លាប់", "បាត់បង់", "យំ", "ឈឺចាប់")):
        return "grieving" if sid in ("cinematic", "sad_romantic") else "sad"
    if any(k in stripped for k in ("ខ្លាច", "ភ័យ", "គ្រោះថ្នាក់")):
        return "fearful"
    if any(k in stripped for k in ("ស្រលាញ់", "ស្រឡាញ់", "ចងចាំ", "នឹក")):
        return "romantic" if sid in ("sad_romantic", "cinematic") else "tender"
    if any(k in stripped for k in ("ឈ្នះ", "ជ័យជម្នះ", "ជោគជ័យ")):
        return "triumphant"
    if n <= 24 and position is not None and position > 0.9:
        return "conclusive" if sid in ("documentary", "explainer", "news") else base
    return base


def arc(text, style):
    """The emotional arc of the whole piece: opening / build / turn / climax /
    release, with a chosen climax (never the last sentence by accident)."""
    sents = [s for s in SENT_SPLIT.split(text or "") if s.strip()]
    if not sents:
        return []
    n = len(sents)
    if n == 1:
        return [dict(phase="whole", index=0, share=1.0)]
    climax = max(range(n), key=lambda i: (len(sents[i]) if i < n - 1 else 0,
                                          i))          # the biggest build-up
    if climax == 0 and n > 2:
        climax = n - 2
    out = []
    for i in range(n):
        t = i / max(1, n - 1)
        if i == climax:
            phase = "climax"
        elif i > climax:
            phase = "release"
        elif t < 0.25:
            phase = "opening"
        elif t < 0.65:
            phase = "build"
        else:
            phase = "turn"
        out.append(dict(phase=phase, index=i, share=t,
                        climax=(i == climax)))
    return out


def _phase_intensity(phase, band, base):
    lo, hi = band
    room = hi - lo
    f = {"opening": 0.30, "build": 0.50, "turn": 0.68, "climax": 1.0,
         "release": 0.42, "whole": 0.5}.get(phase, 0.5)
    return int(round(_clamp(lo + room * f, lo, hi)))


def perform(text, style="natural", intensity=None, speed=1.0, pause=0.25,
            lexicon=None, with_emphasis=True):
    """SOURCE text -> a full performance plan (the thing a TTS engine plays).

    Each unit carries every channel the specification names:
    pitch, energy, rate/duration, pause, rhythm, emphasis, voice quality.
    """
    sid = _style_id(style)
    spec = _spec(style)
    band = tuple(spec.get("intensity") or (10, 60))
    base = int(spec.get("base") or _mid(band))

    # layer 1+2 first: never perform raw source text
    speech, stats, notes, extra = None, {}, [], {}
    if KT is not None:
        try:
            r = KT.prepare(text or "", lexicon)
            speech, stats = r["speech"], r["stats"]
            notes = list(r["notes"])
            extra = r
        except Exception:
            speech = text or ""
    else:
        speech = text or ""

    sents = [s.strip() for s in SENT_SPLIT.split(speech or "") if s.strip()]
    phases = arc(speech, sid)
    units = []
    for i, sent in enumerate(sents):
        ph = phases[i]["phase"] if i < len(phases) else "build"
        lo, hi = band
        unit_i = (base if intensity is None
                  else int(_clamp(intensity, lo, hi)))
        # the arc moves the sentence inside the style's own band
        arc_i = _phase_intensity(ph, band, base)
        val = int(round(_clamp((unit_i + arc_i) / 2.0, lo, hi)))
        emo_name = choose_emotion(sid, sent, None,
                                 position=(i / max(1, len(sents) - 1)))
        early = [k for at, k, mk in shifts(sent) if at <= 3]
        if early:
            emo_name = choose_emotion(sid, sent, early[0])
        # a turn INSIDE the sentence keeps the opening colour here and changes
        # it in the clauses below — that is where the listener hears it
        # --- inside the sentence: dialogue and contrast clauses ---------------
        clauses = []
        quote_hits = list(QUOTE_RE.finditer(sent))
        # a clause ends at punctuation AND at every contrast word — that is
        # where the emotion of this sentence changes
        bounds = set()
        for m in re.finditer(r"[,;\u17d6]\s*", sent):
            if m.end() < len(sent):
                bounds.add(m.end())
        by_pos = {}
        for at, k, mk in shifts(sent):
            if at > 0:
                bounds.add(at)
                by_pos[at] = (k, mk)
        edges = [0] + sorted(b for b in bounds if 0 < b < len(sent)) + [len(sent)]
        pieces = [sent[edges[i]:edges[i + 1]].strip()
                  for i in range(len(edges) - 1)]
        pieces = [x for x in pieces if x] or [sent]
        cursor = 0
        for j, piece in enumerate(pieces):
            kind, marker = by_pos.get(cursor, (None, ""))
            end = cursor + len(piece)
            quote = any(not (q.end() < cursor or q.start() > end)
                        for q in quote_hits)
            c_emo = emo_name
            if quote:
                c_emo = "fearful" if sid in ("thriller", "cinematic") else "affectionate"
                if sid in ("natural", "audiobook", "novel"):
                    c_emo = "warm"
            elif kind in ("turn", "shock"):
                c_emo = choose_emotion(sid, piece, kind, avoid=emo_name)
            elif kind == "confirm":
                c_emo = "conclusive" if sid in ("documentary", "explainer") else emo_name
            clauses.append(dict(text=piece.strip(), emotion=c_emo,
                                shift=kind, marker=marker, dialogue=quote))
            cursor = end + (1 if sent[end:end + 1].isspace() else 0)
        if not clauses:
            clauses = [dict(text=sent, emotion=emo_name, shift=None,
                            marker="", dialogue=False)]

        # --- channels ---------------------------------------------------------
        e = emo(emo_name)
        k = (val - lo) / max(1.0, (hi - lo))              # 0..1 inside the band
        # emotion gives the colour, the STYLE sets the limits it may move in
        sp = speed_guard(speed)
        pitch_bias, pitch_span_style = (spec.get("pitch") or (0.0, 1.5))
        pace = spec.get("pace") or (0.85, 1.15)
        vol = spec.get("volume") or (-3.0, 2.0)
        pitch = _clamp(_clamp(e["pitch"][0] + (e["pitch"][1] - e["pitch"][0]) * k,
                              -4.0, 4.0), pitch_bias - pitch_span_style,
                       pitch_bias + pitch_span_style) * sp
        span = _clamp(e["span"] * (0.75 + 0.5 * k), 0.6, 3.4)
        rate = _clamp(_clamp(e["rate"][0] + (e["rate"][1] - e["rate"][0]) * k,
                             0.70, 1.25), pace[0], pace[1]) * sp
        energy = round(_clamp(_clamp(e["energy"][0] + (e["energy"][1] - e["energy"][0]) * k,
                                     -4.0, 3.0), vol[0], vol[1]), 2)
        rhythm = ("flowing" if e["push"] < 0.3 else
                  "steady" if e["push"] < 0.55 else
                  "forward" if e["push"] < 0.78 else "driving")
        quality = dict(breath=round(_clamp(e["breath"] + 0.30 * k, 0.0, 0.6), 2),
                       tension=round(_clamp(e["tension"], 0.0, 0.9), 2),
                       projection=round(_clamp(0.25 + 0.6 * e["push"], 0.0, 1.0), 2))
        pl = extra.get("pause_plan") or []
        pauses = dict(
            before=round(pause * e["pause"], 3),
            after=round(pause * e["pause"] * (1.25 if ph == "climax" else 1.0), 3),
            clause=round(0.45 * e["pause"] * pause * 2 if pause else 0.05, 3),
        )
        # pause level of the sign that closed this sentence, when known
        for m in reversed(pl):
            try:
                if m.get("sign") in ("។", "៕"):
                    pauses["level"] = m.get("pause_level", 4)
                    break
                if m.get("sign") in (".", "!", "?"):
                    pauses["level"] = 4
                    break
            except Exception:
                continue
        unit = dict(
            index=i, text=sent, phase=ph, emotion=emo_name, intensity=val,
            pitch_st=round(pitch, 2), pitch_span=round(span, 2),
            rate=round(rate, 3), energy_db=energy, rhythm=rhythm,
            intensity5=max(0, min(5, int(round(k * 5)))),
            pauses=pauses, quality=quality,
            emphasis=(emphases(sent) if with_emphasis else []),
            clauses=clauses,
        )
        units.append(unit)

    # --- the FEELING layer: which of this style's four emotional deliveries --
    # STYLE stays fixed; the feeling moves pauses, emphasis, breath and rhythm
    # (the delivery variables of the specification). `choose_delivery` picks
    # inside the SAME style's four deliveries, and `style_guard` refuses any
    # delivery that belongs to another style — a feeling never turns a
    # Documentary read into a Movie Trailer.
    delivery_used = []
    if _DL is not None:
        prev = None
        for u in units:
            try:
                name, moves = _DL.choose_delivery(
                    sid, u["text"], position=(u["index"] / max(1, len(units) - 1)),
                    phase=u["phase"], emotion=u["emotion"],
                    intensity5=u["intensity5"], prev=prev)
            except Exception:
                break
            if not name:
                continue
            _DL.apply_to_unit(u, moves, name=name, style=sid)
            prev = name
            delivery_used.append(name)
    units, guard_notes = guard(units, sid, band)
    # VOICE LOCK: the two performance engines must agree — the feeling is
    # carried by PAUSES, phrase rhythm and emphasis, never by re-tuning the
    # voice. This mirrors narration.VOICE_LOCK exactly.
    for u in units:
        if VOICE_LOCK:
            # SAME VOICE, ITS OWN STYLE (build 2026-09-29j): the speaker never
            # changes — pitch is pinned to 0.0 here — but the style performs at
            # its own pace and its own softness (STYLE_DELIVERY in narration.py,
            # the one table both engines read): meditation slow and soft, news
            # brisk, a trailer slow and heavy. A feeling may colour that by a
            # hair (STYLE_PACE_TOL / STYLE_GAIN_TOL), never more.
            _sd = style_delivery(sid)
            u["pitch_st"] = 0.0
            u["energy_db"] = round(max(-STYLE_GAIN_CAP, min(STYLE_GAIN_CAP,
                max(_sd["gain_db"] - STYLE_GAIN_TOL,
                    min(_sd["gain_db"] + STYLE_GAIN_TOL, float(u["energy_db"]))))), 2)
            u["rate"] = round(max(0.5, min(1.6,
                max(_sd["pace"] - STYLE_PACE_TOL,
                    min(_sd["pace"] + STYLE_PACE_TOL, float(u["rate"]))))), 3)
        else:
            u["pitch_st"], u["energy_db"], u["rate"] = identity_guard(
                u["pitch_st"], u["energy_db"], u["rate"])
    if delivery_used:
        notes = notes + ["feeling: " + ", ".join(sorted(set(delivery_used)))]
    return dict(source=text, speech=speech or "", style=sid,
                style_label=spec.get("label", sid), intensity_band=list(band),
                deliveries=sorted(set(delivery_used)),
                units=units, arc=phases, notes=notes + guard_notes,
                stats=stats,
                unknown_abbreviations=(extra.get("unknown_abbreviations") or []),
                low_confidence=(extra.get("low_confidence") or []),
                layers=dict(language="khmer_text.prepare", pronunciation="lexicon",
                            prosody="khmer_expressive.perform", tts="engine"))


def speed_guard(speed):
    """Speed never turns into singing or into a mumble (0.75x–1.35x)."""
    try:
        s = float(speed)
    except Exception:
        return 1.0
    return _clamp(s, 0.75, 1.35) / 1.0


# ================================================================= guard ====
def guard(units, style, band):
    """The rules that keep a performance human.

    * never flat: every piece must move (intensity spread + emotion variety)
    * never constant drama: the share of high-intensity units is capped
    * whisper only in the styles allowed to whisper, and never everywhere
    * no constant breath, no singing pitch, no two identical units in a row
    """
    notes = []
    sid = _style_id(style)
    lo, hi = band
    if not units:
        return units, notes
    span = hi - lo

    # slope: a descending/ascending line, so no unit repeats the one before it
    for i, u in enumerate(units):
        if i and units[i - 1]["emotion"] == u["emotion"] and \
                abs(units[i - 1]["intensity"] - u["intensity"]) < 3:
            u["intensity"] = int(_clamp(u["intensity"] + (4 if i % 2 else -4), lo, hi))
    # 1) anti-flatness: guarantee a spread inside the band
    vals = [u["intensity"] for u in units]
    if len(units) >= 3 and (max(vals) - min(vals)) < max(6, 0.18 * span):
        units[0]["intensity"] = int(_clamp(lo + 0.18 * span, lo, hi))
        units[len(units) // 2]["intensity"] = int(_clamp(hi - 0.12 * span, lo, hi))
        notes.append("anti-flat: intensity spread enforced")
    # 2) no constant drama
    drama_cap = 0.34 if sid in ("cinematic", "trailer", "thriller") else 0.25
    hot = [u for u in units if u["intensity"] >= lo + 0.75 * span]
    if len(units) >= 4 and len(hot) > max(1, int(len(units) * drama_cap)):
        allowed = max(1, int(len(units) * drama_cap))
        for u in hot[allowed:]:
            u["intensity"] = int(_clamp(lo + 0.55 * span, lo, hi))
        notes.append("restraint: high-intensity units capped at %d%%" % int(drama_cap * 100))
    # 3) whisper policy
    if sid not in WHISPER_STYLES:
        for u in units:
            if u["quality"]["breath"] > 0.30:
                u["quality"]["breath"] = 0.30
        if any(u["quality"]["breath"] >= 0.30 for u in units):
            notes.append("whisper not allowed for this style: air capped")
    elif sid in SUSTAINED_WHISPER_STYLES:      # empty set — kept for clarity
        for u in units:
            u["quality"]["breath"] = round(_clamp(u["quality"]["breath"], 0.25, 0.60), 2)
    else:
        quiet = sorted(units, key=lambda u: u["intensity"])[:max(1, len(units) // 4)]
        allowed = {id(u) for u in quiet}
        for u in units:
            if u["quality"]["breath"] > 0.34 and id(u) not in allowed:
                u["quality"]["breath"] = 0.34
    # 4) no singing, no mumble: absolute pitch/rate ceiling
    for u in units:
        u["pitch_st"] = round(_clamp(u["pitch_st"], -4.0, 4.0), 2)
        u["rate"] = round(_clamp(u["rate"], 0.75, 1.30), 3)
        u["pitch_span"] = round(_clamp(u["pitch_span"], 0.6, 3.4), 2)
    # 5) breath is never on every sentence
    run = 0
    for u in units:
        if u["quality"]["breath"] >= 0.28:
            run += 1
            if run > 2:
                u["quality"]["breath"] = round(min(u["quality"]["breath"], 0.20), 2)
                notes.append("breath capped: never on every sentence")
        else:
            run = 0
    # 6) emotion variety
    distinct = len({u["emotion"] for u in units})
    if len(units) >= 5 and distinct == 1:
        units[len(units) // 2]["emotion"] = "thoughtful"
        units[-1]["emotion"] = "conclusive"
        notes.append("variety: one emotion per sentence is not a performance")
    return units, notes


# ============================================================= reporting ====
def sheet(plan):
    """A human-readable performance sheet (what the voice will actually do)."""
    L = []
    L.append("KHMER PERFORMANCE SHEET")
    L.append("=" * 62)
    L.append("style      : %s  (%s)" % (plan["style_label"], plan["style"]))
    L.append("band       : %d-%d" % tuple(plan["intensity_band"]))
    L.append("layers     : %s" % json.dumps(plan["layers"], ensure_ascii=False))
    if plan.get("unknown_abbreviations"):
        L.append("ASK        : unknown abbreviations left unchanged: %s"
                 % ", ".join(plan["unknown_abbreviations"]))
    for n in plan.get("notes", []):
        L.append("note       : %s" % n)
    L.append("")
    for u in plan["units"]:
        L.append("%2d  [%s] %-12s i=%-3d pitch=%+.2f st span=%.2f rate=%.2f "
                 "energy=%+.1f dB rhythm=%s"
                 % (u["index"] + 1, u["phase"], u["emotion"], u["intensity"],
                    u["pitch_st"], u["pitch_span"], u["rate"], u["energy_db"],
                    u["rhythm"]))
        if u.get("delivery"):
            L.append("     feeling: %s  (%s)"
                     % (u["delivery"], ", ".join(u.get("delivery_vars") or [])))
        L.append("     quality: breath=%.2f tension=%.2f projection=%.2f | "
                 "pause %.2fs before, %.2fs after"
                 % (u["quality"]["breath"], u["quality"]["tension"],
                    u["quality"]["projection"], u["pauses"]["before"],
                    u["pauses"]["after"]))
        if u["emphasis"]:
            L.append("     stress: " + ", ".join("«%s»" % w for w in u["emphasis"]))
        for c in u["clauses"]:
            tag = "dialogue" if c["dialogue"] else (c["shift"] or "narration")
            L.append("       - [%s] %-14s %s" % (tag, c["emotion"], c["text"][:52]))
        L.append("")
    return "\n".join(L).rstrip() + "\n"


def summary(plan):
    u = plan["units"]
    if not u:
        return {"units": 0}
    return dict(units=len(u),
                emotions=sorted({x["emotion"] for x in u}),
                intensity=[min(x["intensity"] for x in u), max(x["intensity"] for x in u)],
                phases=sorted({x["phase"] for x in u}),
                deliveries=sorted({x["delivery"] for x in u if x.get("delivery")}),
                whisper=[x["index"] + 1 for x in u if x.get("whisper")],
                mean_rate=round(sum(x["rate"] for x in u) / len(u), 3),
                mean_pitch=round(sum(x["pitch_st"] for x in u) / len(u), 2))


def prepare_and_perform(text, style="natural", **kw):
    """Convenience: run layers 1-3 and return the plan."""
    return perform(text, style=style, **kw)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Khmer expressive performance planner")
    ap.add_argument("--text")
    ap.add_argument("--in", dest="inp")
    ap.add_argument("--style", default="natural")
    ap.add_argument("--intensity", type=int)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--pause", type=float, default=0.25)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list-emotions", action="store_true")
    ap.add_argument("--list-styles", action="store_true")
    a = ap.parse_args(argv)

    if a.list_emotions:
        for fam, names in sorted(EMOTION_FAMILIES.items()):
            print("%-12s %s" % (fam, ", ".join(sorted(names))))
        print("\ntotal: %d emotions" % len(EMOTIONS))
        return 0
    if a.list_styles:
        for sid in (NAR.STYLE_ORDER if NAR is not None else sorted(STYLE_DEFAULT_EMOTION)):
            print("%-16s default=%-12s turn=%s" % (sid,
                  STYLE_DEFAULT_EMOTION.get(sid, "-"),
                  STYLE_TURN_EMOTION.get(sid, "-")))
        return 0

    text = a.text or ""
    if a.inp:
        with open(a.inp, "r", encoding="utf-8") as f:
            text = f.read()
    if not text.strip():
        print("no text given (use --text or --in)", file=sys.stderr)
        return 2
    plan = perform(text, style=a.style, intensity=a.intensity,
                   speed=a.speed, pause=a.pause)
    if a.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(sheet(plan))
        print(json.dumps(summary(plan), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
