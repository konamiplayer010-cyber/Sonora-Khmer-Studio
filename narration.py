#!/usr/bin/env python3
"""narration.py — the Narration Style & Voice Performance engine.

What this module is for
-----------------------
Choosing a narration style must not merely relabel the voice: the whole
performance has to change — pace, pitch movement, loudness, pauses, breathing,
emphasis, emotional curve. This module turns a style name plus the text into a
per-sentence PERFORMANCE PLAN, which both tools (Sonora Studio and the batch
pipeline) then render.

    text + style  ->  plan:  [{text, emotion, intensity, rate, pitch_st, gain_db,
                               pause_s, breath, pre_pause_ms, stress, ending}]

Design rules taken from the style specification
-----------------------------------------------
* every style has an intensity band (0-100) and the engine must move inside it
  (neutral -> subtle -> expressive -> strong -> peak), never sit at one level
* contrast is enforced: a plan that came out flat is spread out again, and a
  quiet share of sentences is guaranteed for every style
* pauses are punctuation-aware AND style-aware (a thriller before a reveal is
  not the same as a news bulletin between headlines)
* emphasis is applied where it can actually be heard: a short pre-pause before
  the stressed phrase, plus a small gain/rate lift on that phrase
* breathing is optional, subtle, gated (never on every sentence)
* a paragraph's last sentence gets an ending cadence (rate, pitch, extra pause)

Engines and what each can physically do
---------------------------------------
The plan is engine-independent. The RENDERER decides how much of it an engine
can honour (see renderer notes in `apply_plan` callers):

    edge     native rate + pitch + volume  -> the full plan
    local    (MMS / fine-tuned VITS)       -> pace via time-stretch, gain,
                                              pauses, breaths, pitch for large
                                              shifts only
    google   (gTTS)                        -> gain, pauses, breaths, pace
"""
from __future__ import annotations

import math
import re
import zlib

try:
    import delivery as _DL          # the FEELING layer (14 styles)
except Exception:                   # pragma: no cover
    _DL = None

# ---------------------------------------------------------------------------
# 1. Style specifications
# ---------------------------------------------------------------------------
# Every field is taken from the professional style document. Names/ids of the
# styles that already shipped are kept exactly as they were (natural,
# documentary, trailer, audiobook, news, explainer, thriller, meditation);
# the five that were missing are added with the exact names from the spec.

STYLE_SPECS = {
    # ---------------------------------------------------------------- 01 ---
    "natural": dict(
        label="Natural read",
        definition="A relaxed, authentic, conversational reading that sounds "
                   "like a real person speaking to the listener.",
        best_for="Everyday narration, personal stories, blogs, casual nonfiction.",
        tone=("warm", "relaxed", "believable"),
        intensity=(10, 40), base=22,
        pace=(0.97, 1.04),
        pitch=(0.00, 0.30),            # bias, span (semitones)
        pitch_dir=+1,
        volume=(-0.45, 0.45),          # dB around the norm
        pauses=dict(period=1.0, question=1.05, exclaim=1.25, ellipsis=1.4,
                    para=1.7, comma=0.55),
        breath=dict(mode="natural", chance=0.22, level_db=-40.0, min_gap=3),
        micro=0.25,                  # phrase-emphasis strength
        ending=dict(rate=0.98, pitch=-0.4, pause=1.15),
        dialogue=dict(rate=1.02, pitch=0.06, volume=0.20),
        contrast=0.55,
        bed=("none", 0),
    ),
    # ---------------------------------------------------------------- 02 ---
    "storytelling": dict(
        label="Narrative Storytelling",
        definition="An engaging storyteller's voice that makes the listener "
                   "feel someone is personally telling them a story.",
        best_for="Short stories, legends, personal stories, YouTube storytelling.",
        tone=("warm", "expressive", "inviting", "intimate"),
        intensity=(20, 75), base=38,
        pace=(0.90, 1.10),
        pitch=(0.05, 0.60),
        pitch_dir=+1,
        volume=(-0.68, 1.12),
        pauses=dict(period=1.15, question=1.15, exclaim=1.45, ellipsis=1.7,
                    para=2.2, comma=0.65),
        breath=dict(mode="natural", chance=0.3, level_db=-38.0, min_gap=3),
        micro=0.55,
        ending=dict(rate=0.93, pitch=-1.0, pause=1.35),
        dialogue=dict(rate=1.04, pitch=0.06, volume=0.32),
        contrast=0.8,
        bed=("none", 0)          # the narration bed stays OFF: performance must not change the sound of the voice,
    ),
    # ---------------------------------------------------------------- 03 ---
    "novel": dict(
        label="Novel Narration",
        definition="Sophisticated literary narration for novels and long-form "
                   "fiction: rich, controlled, cinematic but restrained.",
        best_for="Novels, fiction, fantasy, romance, mystery, long audiobooks.",
        tone=("rich", "controlled", "immersive"),
        intensity=(15, 60), base=30,
        pace=(0.94, 1.05),
        pitch=(-0.07, 0.42),
        pitch_dir=+1,
        volume=(-0.45, 0.81),
        pauses=dict(period=1.15, question=1.1, exclaim=1.3, ellipsis=1.6,
                    para=2.0, comma=0.6),
        breath=dict(mode="subtle", chance=0.2, level_db=-41.0, min_gap=4),
        micro=0.4,
        ending=dict(rate=0.95, pitch=-0.6, pause=1.3),
        dialogue=dict(rate=1.03, pitch=0.06, volume=0.32),
        contrast=0.7,
        bed=("none", 0)          # the narration bed stays OFF: performance must not change the sound of the voice,
    ),
    # ---------------------------------------------------------------- 04 ---
    "documentary": dict(
        label="Documentary",
        definition="Authoritative, informative, immersive narration that "
                   "communicates significance without sounding sensational.",
        best_for="History, science, biography, true stories, documentaries.",
        tone=("calm", "intelligent", "confident", "observational"),
        intensity=(12, 48), base=26,
        pace=(0.94, 1.02),
        pitch=(-0.15, 0.30),
        pitch_dir=+1,
        volume=(-0.36, 0.54),
        pauses=dict(period=1.2, question=1.05, exclaim=1.2, ellipsis=1.5,
                    para=2.3, comma=0.6),
        breath=dict(mode="subtle", chance=0.18, level_db=-42.0, min_gap=4),
        micro=0.45,
        ending=dict(rate=0.96, pitch=-0.7, pause=1.4),
        dialogue=dict(rate=1.0, pitch=0.05, volume=0.12),
        contrast=0.6,
        bed=("none", 0)          # the narration bed stays OFF: performance must not change the sound of the voice,
    ),
    # ---------------------------------------------------------------- 05 ---
    "trailer": dict(
        label="Movie trailer",
        definition="Cinematic, dramatic, high-impact narration built to create "
                   "anticipation and emotional scale.",
        best_for="Trailers, cinematic intros, dramatic promotions.",
        tone=("powerful", "controlled", "commanding"),
        intensity=(35, 100), base=58,
        pace=(0.78, 1.18),
        pitch=(-0.35, 0.48),
        pitch_dir=-1,                # louder/bigger = lower and grounded
        volume=(-0.68, 1.60),
        pauses=dict(period=1.5, question=1.4, exclaim=1.7, ellipsis=2.1,
                    para=2.8, comma=0.85),
        breath=dict(mode="gated", chance=0.35, level_db=-36.0, min_gap=3),
        micro=0.85,
        ending=dict(rate=0.85, pitch=-1.8, pause=1.8),
        dialogue=dict(rate=0.98, pitch=0.06, volume=0.32),
        contrast=0.95,
        bed=("none", 0)          # the narration bed stays OFF: performance must not change the sound of the voice,
    ),
    # ---------------------------------------------------------------- 06 ---
    "audiobook": dict(
        label="Audiobook",
        definition="Professional long-form performance: clarity, immersion, "
                   "character differentiation, listener comfort.",
        best_for="Complete audiobooks, novels, nonfiction, romance, mystery.",
        tone=("natural", "intimate", "clear", "consistent"),
        intensity=(15, 55), base=28,
        pace=(0.95, 1.06),
        pitch=(-0.05, 0.36),
        pitch_dir=+1,
        volume=(-0.27, 0.72),
        pauses=dict(period=1.15, question=1.1, exclaim=1.3, ellipsis=1.55,
                    para=2.1, comma=0.6),
        breath=dict(mode="subtle", chance=0.16, level_db=-42.0, min_gap=4),
        micro=0.4,
        ending=dict(rate=0.96, pitch=-0.5, pause=1.35),
        dialogue=dict(rate=1.05, pitch=0.06, volume=0.28),
        contrast=0.65,
        bed=("none", 0)          # the narration bed stays OFF: performance must not change the sound of the voice,
    ),
    # ---------------------------------------------------------------- 07 ---
    "news": dict(
        label="News anchor",
        definition="Precise, authoritative broadcast narration optimized for "
                   "clarity, information hierarchy and credibility.",
        best_for="News, current events, reports, announcements.",
        tone=("clear", "confident", "controlled", "neutral"),
        intensity=(10, 38), base=20,
        pace=(1.04, 1.10),
        pitch=(-0.10, 0.30),
        pitch_dir=+1,
        volume=(-0.18, 0.63),
        pauses=dict(period=1.05, question=1.15, exclaim=1.3, ellipsis=1.3,
                    para=1.3, comma=0.45),
        breath=dict(mode="off", chance=0.0, level_db=-44.0, min_gap=99),
        micro=0.3,
        ending=dict(rate=1.0, pitch=-0.3, pause=1.05),
        dialogue=dict(rate=1.0, pitch=0.00, volume=0.00),
        contrast=0.35,
        bed=("none", 0),
    ),
    # ---------------------------------------------------------------- 08 ---
    "explainer": dict(
        label="Explainer",
        definition="A friendly, intelligent teaching voice that makes complex "
                   "information easy to understand.",
        best_for="Education, tutorials, technology, business, explainers.",
        tone=("clear", "friendly", "approachable", "patient"),
        intensity=(18, 52), base=28,
        pace=(0.98, 1.07),
        pitch=(0.00, 0.39),
        pitch_dir=+1,
        volume=(-0.27, 0.72),
        pauses=dict(period=1.1, question=1.2, exclaim=1.3, ellipsis=1.4,
                    para=1.8, comma=0.6),
        breath=dict(mode="natural", chance=0.2, level_db=-40.0, min_gap=4),
        micro=0.5,
        ending=dict(rate=0.97, pitch=-0.4, pause=1.2),
        dialogue=dict(rate=1.02, pitch=0.06, volume=0.16),
        contrast=0.55,
        bed=("none", 0)          # the narration bed stays OFF: performance must not change the sound of the voice,
    ),
    # ---------------------------------------------------------------- 09 ---
    "thriller": dict(
        label="Thriller",
        definition="Suspense-driven narration: uncertainty, tension, "
                   "anticipation, psychological pressure.",
        best_for="Thrillers, mystery, psychological fiction, horror, suspense.",
        tone=("controlled", "dark", "intimate", "tense"),
        intensity=(25, 88), base=42,
        pace=(0.84, 1.16),
        pitch=(-0.35, 0.30),
        pitch_dir=-1,                # tension lives low and restrained
        volume=(-0.90, 0.99),
        pauses=dict(period=1.5, question=1.6, exclaim=1.5, ellipsis=2.0,
                    para=2.5, comma=0.9),
        breath=dict(mode="gated", chance=0.28, level_db=-37.0, min_gap=3),
        micro=0.6,
        ending=dict(rate=0.88, pitch=-1.4, pause=1.7),
        dialogue=dict(rate=0.97, pitch=-0.10, volume=0.16),
        contrast=0.9,
        bed=("none", 0)          # the narration bed stays OFF: performance must not change the sound of the voice,
    ),
    # ---------------------------------------------------------------- 10 ---
    "meditation": dict(
        label="Meditation",
        definition="Calm, spacious, soothing narration that lowers stimulation "
                   "and invites relaxation.",
        best_for="Meditation, sleep stories, mindfulness, calming narration.",
        tone=("warm", "soft", "gentle", "reassuring"),
        intensity=(5, 25), base=10,
        pace=(0.78, 0.86),
        pitch=(-0.25, 0.30),
        pitch_dir=+1,
        volume=(-0.90, 0.23),
        pauses=dict(period=1.9, question=1.7, exclaim=1.7, ellipsis=2.4,
                    para=3.2, comma=1.1),
        breath=dict(mode="open", chance=0.5, level_db=-38.0, min_gap=2),
        micro=0.15,
        ending=dict(rate=0.9, pitch=-0.4, pause=1.8),
        dialogue=dict(rate=0.92, pitch=0.00, volume=0.00),
        contrast=0.25,
        bed=("none", 0)          # the narration bed stays OFF: performance must not change the sound of the voice,
    ),
    # ---------------------------------------------------------------- 11 ---
    "inner_monologue": dict(
        label="Inner Monologue",
        definition="An intimate internal voice: a character's private thoughts, "
                   "doubts, memories and realizations.",
        best_for="Psychological fiction, romance, character studies, reflection.",
        tone=("intimate", "reflective", "honest", "close"),
        intensity=(12, 62), base=26,
        pace=(0.82, 0.98),
        pitch=(-0.25, 0.36),
        pitch_dir=+1,
        volume=(-0.99, 0.54),
        pauses=dict(period=1.4, question=1.5, exclaim=1.4, ellipsis=1.9,
                    para=2.2, comma=0.85),
        breath=dict(mode="subtle", chance=0.34, level_db=-39.0, min_gap=3),
        micro=0.5,
        ending=dict(rate=0.9, pitch=-0.9, pause=1.5),
        dialogue=dict(rate=0.98, pitch=0.06, volume=0.12),
        contrast=0.7,
        bed=("none", 0),
    ),
    # ---------------------------------------------------------------- 12 ---
    "sad_romantic": dict(
        label="Sad Romantic",
        definition="Intimate, emotionally restrained narration for stories of "
                   "lost love, separation, memory and regret: the narrator "
                   "sounds like someone remembering late at night, carrying an "
                   "emotion they are trying not to reveal. Quiet pain, not tears.",
        best_for="Sad romance, breakups, lost love, long-distance love, "
                 "nostalgic memories, letters to an ex, unrequited love, "
                 "lonely-night stories, romantic monologues, heartbreak novels.",
        tone=("private", "warm", "soft", "vulnerable", "deeply human",
              "restrained"),
        intensity=(20, 70), base=34,
        pace=(0.86, 1.0),
        pitch=(-0.30, 0.30),
        pitch_dir=+1,
        volume=(-1.08, 0.45),
        pauses=dict(period=1.45, question=1.6, exclaim=1.35, ellipsis=2.0,
                    para=2.4, comma=0.9),
        breath=dict(mode="subtle", chance=0.32, level_db=-39.0, min_gap=3),
        micro=0.6,
        ending=dict(rate=0.88, pitch=-1.1, pause=1.6),
        dialogue=dict(rate=0.96, pitch=0.05, volume=0.08),
        contrast=0.85,
        # --- the tone style (professional spec: whisper mode, breaking voice,
        # slow reading, pauses as emotional language) ---------------------------
        # Near-whisper passages for intimacy, memory, loneliness and
        # vulnerability. Never the whole piece: gated by min_gap, always
        # separated by normal soft-voice sentences, always a breath before.
        # whisper REMOVED (2026-09-30n): no style may whisper a line any more
        whisper=None,
        # The "trying not to cry" moment: the emotional peak loses volume,
        # slows down, hesitates before the painful words, then real silence.
        # Restraint over sobbing.
        breaking=dict(gain_db=-2.6, rate=0.90, pitch=-0.45,
                      pre_pause_ms=300, after_ms=420),
        # Unfinished / suspended endings for longing and uncertainty, so not
        # every sentence falls the same way.
        suspended=dict(rate=1.0, pitch=0.45, pause_add=0.22),
        # The emotional build (calm -> memory -> warmth -> longing -> pain ->
        # silence -> acceptance -> quiet sadness): peak around 62 % of the
        # text, calmer first and last sentences so the peak lands.
        arc=dict(peak=0.62, lift=15.0, calm=0.72),
        stress_words=("អ្នក", "ខ្ញុំ", "យើង", "ធ្លាប់", "នៅតែ", "មិនដែល",
                      "ម្តងទៀត", "ចងចាំ", "បាត់", "ផ្ទះ", "ម្នាក់ឯង", "ស្អែក",
                      "លាហើយ", "អតីតកាល", "ស្នេហ៍"),
        bed=("none", 0)          # the narration bed stays OFF: performance must not change the sound of the voice,
    ),
    # ---------------------------------------------------------------- 13 ---
    "cinematic": dict(
        label="Emotional Cinematic Storytelling",
        definition="Cinematic storytelling the listener lives inside: whisper, "
                   "soft narration, quiet fear, suspense, emotional pain, "
                   "silence, warm resolution. Close and intimate, a human "
                   "storyteller in real time, never a trailer announcer.",
        best_for="Emotional cinematic stories, romance, sad stories, mystery, "
                 "psychological stories, suspense, horror, dramatic novels, "
                 "audio dramas, immersive audiobooks.",
        tone=("intimate", "cinematic", "deeply emotional", "controlled",
              "warm when it fits", "dark when it fits"),
        intensity=(25, 95), base=44,
        pace=(0.86, 1.14),
        pitch=(-0.35, 0.54),
        pitch_dir=+1,
        volume=(-1.17, 1.44),
        pauses=dict(period=1.4, question=1.35, exclaim=1.6, ellipsis=2.0,
                    para=2.6, comma=0.8),
        breath=dict(mode="gated", chance=0.3, level_db=-37.0, min_gap=3),
        micro=0.75,
        ending=dict(rate=0.88, pitch=-1.3, pause=1.7),
        dialogue=dict(rate=1.03, pitch=0.06, volume=0.32),
        contrast=1.0,
        # --- the tone style (professional spec: whisper storytelling, fear
        # mode, breaking point, cinematic curve) ------------------------------
        # build l (the user's re-set): no RANDOM whisper in this style.
        # What is left is the storyteller READ — unhurried, phrase by
        # phrase, gentle landings — and the text may still ask for the
        # 'Whisper / Intimate' feeling, which is a delivery, not a voice.
        whisper=None,
        breaking=dict(gain_db=-2.8, rate=0.89, pitch=-0.5,
                      pre_pause_ms=280, after_ms=430),
        suspended=dict(rate=1.0, pitch=0.5, pause_add=0.20),
        # Scene curve: neutral -> curiosity -> unease -> fear -> pressure ->
        # peak -> silence -> reflection. The peak lands later than in a sad
        # romance and the ending settles back down (resolution).
        arc=dict(peak=0.68, lift=18.0, calm=0.66),
        # Fear sounds like someone trying NOT to be heard: lower, slower, less
        # certain, quieter — never louder (spec: "scared / fear mode").
        fear=dict(gain_db=-3.0, rate=0.90, pitch=-0.5, pause_add=0.25,
                  breath=False),
        stress_words=("សំឡេង", "ទ្វារ", "ខ្មៅ", "ខ្លាច", "លាក់", "អាថ៌កំបាំង",
                      "ស្ងាត់", "ម្នាក់ឯង", "ចងចាំ", "ស្រមោល", "ញាប់ញ័រ",
                      "ភ្លេច", "ស្នេហ៍", "ជីវិត"),
        bed=("none", 0)          # the narration bed stays OFF: performance must not change the sound of the voice,
    ),
}

# old ids / spellings / the names people type -> canonical id
STYLE_ALIASES = {
    "natural": "natural", "natural read": "natural", "natural_read": "natural",
    "narrative storytelling": "storytelling", "narrative": "storytelling",
    "storytelling": "storytelling", "narrative_storytelling": "storytelling",
    "novel narration": "novel", "novel": "novel", "novel_narration": "novel",
    "documentary": "documentary",
    "movie trailer": "trailer", "trailer": "trailer", "movie_trailer": "trailer",
    "audiobook": "audiobook", "audio book": "audiobook",
    "news anchor": "news", "news": "news", "news_anchor": "news",
    "explainer": "explainer",
    "thriller": "thriller",
    "meditation": "meditation",
    "inner monologue": "inner_monologue", "inner_monologue": "inner_monologue",
    "internal monologue": "inner_monologue", "monologue": "inner_monologue",
    "sad romantic": "sad_romantic", "sad_romantic": "sad_romantic",
    "melancholic love": "sad_romantic", "sad romantic / melancholic love":
        "sad_romantic",
    "emotional cinematic storytelling": "cinematic",
    "emotional_cinematic_storytelling": "cinematic", "cinematic": "cinematic",
    }

STYLE_ORDER = ["natural", "storytelling", "novel", "documentary", "trailer",
               "audiobook", "news", "explainer", "thriller", "meditation",
               "inner_monologue", "sad_romantic", "cinematic"]


#: HOW EACH STYLE PERFORMS — the style's own pace and its own softness.
#: This is what the ear actually uses to tell one style from another, and it
#: is the second half of the specification's own definition of a style
#: ("pace, energy, pauses, breathing, emphasis, ending cadence"). What never
#: moves is the SPEAKER: pitch stays exactly 0.0 st in every style and every
#: feeling, so the same person is heard whether the piece is a trailer or a
#: a news bulletin.
#:
#:     pace     multiplier on the words (the user's NARRATION SPEED applies
#:              on top of it, as it always has)
#:     gain_db  how soft / strong the delivery sits (−1.2 … +0.6 dB)
#:     hint     one line, used by the docs and the style table
STYLE_DELIVERY = {
    "natural":         dict(pace=1.00, gain_db=0.0,  hint="the base read: comfortable, neutral"),
    "storytelling":    dict(pace=0.96, gain_db=0.3,  hint="warm and building, a storyteller"),
    "novel":           dict(pace=0.95, gain_db=-0.4, hint="literary, controlled, cinematic"),
    "documentary":     dict(pace=0.94, gain_db=-0.5, hint="measured, unhurried, facts carry weight"),
    "trailer":         dict(pace=0.90, gain_db=0.7,  hint="slow and weighty, every line lands"),
    "audiobook":       dict(pace=0.99, gain_db=-0.2, hint="even long-form comfort"),
    "news":            dict(pace=1.07, gain_db=0.4,  hint="crisp and brisk, facts in order"),
    "explainer":       dict(pace=1.02, gain_db=0.1,  hint="bright and friendly, step by step"),
    "thriller":        dict(pace=0.93, gain_db=-0.9, hint="hushed and tense — soft on purpose"),
    "meditation":      dict(pace=0.84, gain_db=-1.2, hint="very slow, very soft, long breathing gaps"),
    "inner_monologue": dict(pace=0.91, gain_db=-0.7, hint="close and quiet, thinking rather than speaking"),
    "sad_romantic":    dict(pace=0.90, gain_db=-0.7, hint="restrained longing, lingering endings"),
    "cinematic":       dict(pace=0.99, gain_db=0.0,  hint="the storyteller read: unhurried, phrase by phrase, gentle landings"),
}
STYLE_PACE_TOL = 0.03          # how much a single feeling may move the pace
STYLE_GAIN_TOL = 0.5           # …and how much softer/stronger one line may sit
STYLE_GAIN_CAP = 1.6           # the hard cap: colour, never a re-mix


def style_delivery(style):
    """The style's own pace / softness (a copy, safe to edit)."""
    try:
        return dict(STYLE_DELIVERY[style_id(style)])
    except Exception:
        return dict(STYLE_DELIVERY["natural"])


def style_id(style):
    """'Novel Narration' / 'novel_narration' / 'novel' -> 'novel'."""
    if not style:
        return "natural"
    key = str(style).strip().lower().replace("-", "_")
    if key in STYLE_SPECS:
        return key
    return STYLE_ALIASES.get(key, STYLE_ALIASES.get(key.replace("_", " "), "natural"))


def spec(style):
    """The full specification dict for a style name/id."""
    return STYLE_SPECS[style_id(style)]


def style_list():
    """UI-ready list: [{id, label, definition, best_for, bed, bed_level}]."""
    out = []
    for sid in STYLE_ORDER:
        s = STYLE_SPECS[sid]
        out.append({"id": sid, "label": s["label"], "definition": s["definition"],
                    "best_for": s["best_for"], "bed": s["bed"][0],
                    "bed_level": s["bed"][1]})
    return out


# ---------------------------------------------------------------------------
# 2. Content cues -> emotion channels (Khmer first, then English)
# ---------------------------------------------------------------------------
CUE_LEXICON = {
    "loss": [
        "ស្លាប់", "ស្លាប់បាត់", "បាត់បង់", "បាត់", "យំ", "ទឹកភ្នែក", "ឈឺចាប់",
        "ការបាត់បង់", "ខ្មោច", "ពិធីបុណ្យសព", "ទុក្ខ", "ស្រវឹងចិត្ត", "អស់សង្ឃឹម",
        "died", "death", "dead", "gone", "lost", "loss", "tears", "crying",
        "funeral", "grief", "empty", "never came back", "buried"],
    "love": [
        "ស្នេហា", "ស្រលាញ់", "ស្រឡាញ់", "ចិត្ត", "ថើប", "ដៃ", "ឱប", "អារម្មណ៍",
        "នឹក", "រំលឹក", "ចងចាំ", "អភ័យទោស", "ស្មោះ", "ភក្តី", "ក្តីសង្ឃឹម",
        "love", "loved", "heart", "kiss", "kissed", "held", "hug", "missing you",
        "miss you", "remember", "still", "again", "home", "forever", "promise"],
    "danger": [
        "គ្រោះថ្នាក់", "ភ័យ", "ខ្លាច", "សម្ងាត់", "លាក់", "ឃាតកម្ម", "កាំបិត",
        "កាំភ្លើង", "ឈាម", "ងងឹត", "ស្ងាត់", "រត់", "ស្រែក", "គេច", "តាម",
        "មនុស្សចម្លែក", "ទ្វារ", "ស្លាប់", "អន្ទាក់",
        "danger", "dangerous", "fear", "afraid", "secret", "hidden", "blood",
        "knife", "gun", "dark", "silent", "quiet", "suddenly", "scream", "ran",
        "escape", "watched", "followed", "door", "trap", "something was wrong"],
    "revelation": [
        "ភ្ញាក់ផ្អើល", "រកឃើញ", "តាមពិត", "ពិតប្រាកដ", "ទើបដឹង", "ចម្លើយ", "ការពិត",
        "ភ្លាមៗ", "ស្រាប់តែ", "បង្ហាញ", "ដឹង", "សម្រេច",
        "revealed", "discovered", "truth", "realized", "realised", "finally",
        "suddenly", "found out", "in fact", "actually", "the answer"],
    "joy": [
        "សប្បាយ", "រីករាយ", "សង្ឃឹម", "ជោគជ័យ", "ញញឹម", "សើច", "ពន្លឺ", "អបអរ",
        "ស្រស់ស្អាត", "អច្ឆរិយៈ",
        "joy", "happy", "hope", "victory", "smile", "laughed", "light",
        "beautiful", "wonderful", "celebrate"],
    "memory": [
        "អតីតកាល", "កាលពី", "ពេលនោះ", "ថ្ងៃនោះ", "រំលឹក", "នឹកឃើញ", "ចាស់",
        "កុមារភាព", "ធ្លាប់",
        "memory", "memories", "once", "used to", "back then", "that day",
        "childhood", "long ago", "remember when"],
    "scale": [                                    # documentary / news weight
        "រាជាណាចក្រ", "ចក្រភព", "សតវត្ស", "ប្រវត្តិសាស្ត្រ", "សង្គ្រាម",
        "បដិវត្តន៍", "អរិយធម៌", "រាជវង្ស", "បុរាណ",
        "empire", "kingdom", "century", "history", "war", "revolution",
        "civilization", "ancient", "dynasty", "nations"],
}

# how much each channel lifts the intensity, per style family
CHANNEL_WEIGHTS = {
    "natural":        dict(loss=6, love=5, danger=8, revelation=6, joy=6, memory=4, scale=3),
    "storytelling":   dict(loss=12, love=11, danger=14, revelation=13, joy=12, memory=9, scale=4),
    "novel":          dict(loss=10, love=10, danger=11, revelation=11, joy=9, memory=9, scale=5),
    "documentary":    dict(loss=6, love=4, danger=7, revelation=9, joy=4, memory=4, scale=12),
    "trailer":        dict(loss=12, love=8, danger=18, revelation=16, joy=10, memory=6, scale=16),
    "audiobook":      dict(loss=11, love=10, danger=12, revelation=12, joy=9, memory=8, scale=5),
    "news":           dict(loss=6, love=2, danger=9, revelation=8, joy=4, memory=2, scale=10),
    "explainer":      dict(loss=4, love=4, danger=6, revelation=10, joy=8, memory=4, scale=8),
    "thriller":       dict(loss=10, love=6, danger=20, revelation=17, joy=4, memory=6, scale=4),
    "meditation":     dict(loss=3, love=4, danger=2, revelation=3, joy=3, memory=3, scale=1),
    "inner_monologue": dict(loss=13, love=13, danger=11, revelation=13, joy=8, memory=12, scale=3),
    "sad_romantic":   dict(loss=15, love=15, danger=6, revelation=11, joy=5, memory=13, scale=3),
    "cinematic":      dict(loss=14, love=13, danger=15, revelation=15, joy=11, memory=11, scale=9),
}

EMOTION_NAME = {"loss": "grief", "love": "tenderness", "danger": "tension",
                "revelation": "revelation", "joy": "hope", "memory": "reflection",
                "scale": "gravity", "none": "neutral"}

# ---------------------------------------------------------------------------
# 3. Sentence splitting and per-sentence analysis
# ---------------------------------------------------------------------------
_END_RE = re.compile(r"([.!?…\u17D4])\s*$")
_QUOTE_RE = re.compile(r"[\"“”«»‘’']")


def split_sentences(text, max_len=450):
    """[(sentence, boundary)] — boundary is '.', '!', '?', '…' or 'para'.

    Mirrors the studio's splitter: Khmer ។ (khan) counts as a full stop, and a
    line without closing punctuation still ends the paragraph.
    """
    text = (text or "").strip()
    if not text:
        return []
    units = []
    for para in [p.strip() for p in text.split("\n") if p.strip()]:
        pieces = [p.strip() for p in
                  re.findall(r"[^.!?…\u17D4]*[.!?…\u17D4]*", para) if p.strip()]
        for piece in (pieces or [para]):
            m = _END_RE.search(piece)
            boundary = m.group(1) if m else "para"
            while len(piece) > max_len:
                cut = piece.rfind(" ", 60, max_len)
                if cut < 60:
                    cut = max_len
                units.append((piece[:cut].strip(), "."))
                piece = piece[cut:].strip()
            if piece.strip():
                units.append((piece.strip(), boundary))
    return [u for u in units if u[0]]


def _words(text):
    """Crude word count that still works for unsegmented Khmer."""
    spaced = len(re.findall(r"\s+", text or ""))
    if spaced >= 3:
        return spaced + 1
    khmer = re.findall(r"[\u1780-\u17FF]", text or "")
    return max(1, len(khmer) // 4)          # ~4 Khmer chars per syllable-ish


def _channel_hits(low):
    hits = {}
    for chan, words in CUE_LEXICON.items():
        n = sum(1 for w in words if w in low)
        if n:
            hits[chan] = min(3, n)          # cap so one repeat is not a frenzy
    return hits


def analyse(text, boundary=".", style="natural", position=None, is_dialogue=None):
    """Per-sentence analysis -> the 9 fields the performance spec asks for.

    Returns dict(text, emotion, intensity, attitude, pace_hint, stress, ...).
    """
    s = spec(style)
    sid = style_id(style)
    low = (text or "").lower()
    weights = CHANNEL_WEIGHTS[sid]

    hits = _channel_hits(low)
    score, best_chan, best_w = 0.0, "none", 0
    for chan, n in hits.items():
        w = weights.get(chan, 0) * n
        score += w * 0.7
        if w > best_w:
            best_chan, best_w = chan, w

    # punctuation and shape
    if boundary == "!":
        score += 10
    elif boundary == "?":
        score += 6
    elif boundary == "…":
        score += 4
    if _QUOTE_RE.search(text or ""):
        is_dialogue = True if is_dialogue is None else is_dialogue
    n_words = _words(text)
    if sid in ("trailer", "thriller", "cinematic", "storytelling") and n_words <= 7:
        score += 7                        # short punchy lines carry weight
    if sid in ("documentary", "news") and re.search(r"\d", text or ""):
        score += 8                        # numbers/dates are the substance
    if position is not None and position == "last":
        score += 4                        # a paragraph's last line lands it

    lo, hi = s["intensity"]
    raw = s["base"] + score
    intensity = max(lo, min(hi, raw))

    return {
        "text": text,
        "emotion": EMOTION_NAME.get(best_chan, "neutral"),
        "intensity": int(round(intensity)),
        "attitude": s["tone"][0],
        "is_dialogue": bool(is_dialogue),
        "words": n_words,
        "boundary": boundary,
        "channels": hits,
        "score": round(score, 1),
    }


def _add_contrast(units, style):
    """The spec forbids one flat level: spread the curve, keep quiet moments.

    * expands deviations from the mean when the spread is too small
      (style['contrast'] says how much movement the style wants)
    * guarantees a quiet share (>= 25 %) so no style is wall-to-wall emotion
    """
    s = spec(style)
    lo, hi = s["intensity"]
    vals = [u["intensity"] for u in units]
    if len(vals) < 3:
        return units
    mean = sum(vals) / len(vals)
    spread = max(vals) - min(vals)
    want = (hi - lo) * s["contrast"] * 0.55
    if spread < want and spread > 0:
        k = want / spread
        for u in units:
            dev = (u["intensity"] - mean) * k
            u["intensity"] = int(round(max(lo, min(hi, mean + dev))))

    # guarantee quiet moments
    vals = sorted(u["intensity"] for u in units)
    quiet_line = lo + (hi - lo) * 0.3
    quiet = [u for u in units if u["intensity"] <= quiet_line]
    need = max(1, int(round(len(units) * 0.25)))
    if len(quiet) < need:
        for u in sorted(units, key=lambda x: x["intensity"])[:need]:
            u["intensity"] = int(round(min(u["intensity"], quiet_line)))
    return units


def _lerp(a, b, t):
    return a + (b - a) * max(0.0, min(1.0, t))


# ---------------------------------------------------------------------------
# 3b. The tone style of the two emotional styles (spec: style 12 and 13)
# ---------------------------------------------------------------------------
# These passes only fold their decisions into the fields the renderers already
# understand (rate / pitch / gain / pause / breath / pre_pause), so the studio
# and the batch pipeline both inherit them with no extra code.

# only real longing / uncertainty words — not everyday particles, or half the
# paragraph would end "unfinished"
SUSPEND_CUES = ("ពេលណា", "ប្រហែល", "សង្ស័យ", "នឹកដល់", "រង់ចាំ", "សង្ឃឹម",
                "មិនដឹង", "ចង់ដឹង", "ឬមួយ")


def _arc_value(i, n, peak):
    """0 at the ends, 1 at the peak position (the emotional build curve)."""
    if n <= 1:
        return 1.0
    x = i / float(n - 1)
    span = max(peak, 1.0 - peak) or 1.0
    return max(0.0, min(1.0, 1.0 - abs(x - peak) / span))


def _apply_arc(items, style):
    """Shape intensity as a curve instead of letting it drift.

    sad_romantic: calm -> memory -> warmth -> longing -> pain -> silence ->
    acceptance -> quiet sadness. cinematic: the peak arrives later and the
    ending settles back down. Either way the first and last sentences stay
    calmer than the middle, because contrast is what makes a peak land.
    """
    s = spec(style)
    arc = s.get("arc") or {}
    if not arc or len(items) < 3:
        return items
    peak = float(arc.get("peak", 0.62))
    lift = float(arc.get("lift", 15.0))
    calm = float(arc.get("calm", 0.7))
    lo, hi = s["intensity"]
    n = len(items)
    for i, u in enumerate(items):
        v = _arc_value(i, n, peak)
        delta = (v - 0.5) * 2.0 * lift
        if i == 0 or i == n - 1:
            delta -= lift * (1.0 - calm)
        u["intensity"] = int(round(max(lo, min(hi, u["intensity"] + delta))))
    return items


def _apply_fear(plans, style):
    """Fear mode (style 13): quieter, slower, more uncertain — never louder."""
    s = spec(style)
    f = s.get("fear") or {}
    if not f:
        return
    # only a share of the piece gets the fear colour (a scene, not everything):
    # calm narration between the dark parts is what makes them feel dark
    cap = max(1, len(plans) // 3)
    for p in plans:
        if cap <= 0:
            break
        if p["emotion"] not in ("tension", "revelation"):
            continue
        cap -= 1
        p["gain_db"] += float(f.get("gain_db", -2.5))
        p["rate"] *= float(f.get("rate", 0.92))
        p["pitch_st"] += float(f.get("pitch", -0.4))
        p["pause_s"] += float(f.get("pause_add", 0.2))
        # breath marking removed (build 2026-09-30o)
        p["fear"] = True


def _silence_scale(n, full_at=8):
    """How much of the spec's extra silence this piece can carry.

    The pauses in the style spec are written for prose (the silence between
    sentences that keeps a chapter breathing). In a four-sentence demo there are
    far fewer gaps, so the extras scale down instead of swallowing the piece —
    and the slow styles (meditation) keep the longest gaps overall.
    """
    return min(1.0, max(0.3, float(n) / float(full_at)))


def _apply_whisper(plans, style):
    """Does nothing — the whisper stage is removed (build 2026-09-30n).

    Kept as a function so the planner keeps its shape, but no line is ever
    marked `whisper` any more: a whispered line is a different *sound* wearing
    the speaker's shape, and mid-read that stops being the voice (the user's
    report: it arrived louder than the sentence it replaced).

    What stays is the performance that was doing the real work: an intimate
    passage is still slower, softer, closer and better spaced — same voice.
    """
    return
    s = spec(style)
    w = s.get("whisper") or {}
    if not w or not plans:
        return
    scale = _silence_scale(len(plans))
    if w.get("mode") == "sustained":
        depth = float(w.get("depth", 1.0))
        for i, p in enumerate(plans):
            p["whisper"] = True
            p["whisper_depth"] = depth
            p["gain_db"] += float(w.get("gain_db", -2.4))
            p["rate"] *= float(w.get("rate", 0.92))
            p["pause_s"] += float(w.get("after_ms", 200)) / 1000.0 * scale
            # breath marking removed (build 2026-09-30o)
        return
    if len(plans) < 3:
        return
    lo, hi = s["intensity"]
    quiet_max = lo + (hi - lo) * 0.5
    gap = max(2, min(int(w.get("min_gap", 3)), max(2, len(plans) // 2)))
    chance = float(w.get("chance", 0.3))
    chosen, last = [], -99
    for i, p in enumerate(plans):
        if i == 0 or p.get("breaking"):
            continue
        if i - last < gap:
            continue
        if p["intensity"] > quiet_max and not p["is_dialogue"]:
            continue          # the loud sentences stay loud (contrast)
        roll = (zlib.crc32(f"whisper|{style_id(style)}|{i}|{p['text'][:14]}"
                           .encode("utf-8")) % 100) / 100.0
        if roll >= chance:
            continue
        chosen.append(i)
        last = i
    if not chosen:
        # a short piece still has to demonstrate the mode: take the quietest
        # sentence that is not the opening one and not already the peak
        cand = [i for i, p in enumerate(plans)
                if i > 0 and not p.get("breaking")]
        if cand:
            chosen = [min(cand, key=lambda i: (plans[i]["intensity"], i))]
    for i in chosen:
        p = plans[i]
        p["whisper"] = True
        # relative, and small: a whisper is SOFTER and SLOWER, never a new voice
        depth = min(1.6, abs(float(w.get("gain_db", 1.6))))
        p["gain_db"] = round(max(-IDENTITY_GAIN_DB, p["gain_db"] - depth), 2)
        p["rate"] = round(max(WHISPER_RATE_FLOOR,
                              min(1.15, p["rate"] * max(0.94, min(0.98,
                                  float(w.get("rate", 0.96)))))), 4)
        p["pitch_st"] = round(max(-IDENTITY_PITCH_ST,
                                  p["pitch_st"] + max(-0.20, min(0.0,
                                     float(w.get("pitch", -0.12))))), 3)
        p["pause_s"] += float(w.get("after_ms", 180)) / 1000.0 * scale


def _apply_breaking(plans, style):
    """The "trying not to cry" moment: the peak goes quiet, slow, hesitant."""
    s = spec(style)
    b = s.get("breaking") or {}
    if not b or not plans:
        return
    # the strongest sentence carries the break (ties resolve to the later one,
    # so the break sits inside the piece rather than at its first line)
    idx = max(range(len(plans)), key=lambda i: (plans[i]["intensity"], i))
    if idx == 0 and len(plans) > 1:
        idx = max(range(1, len(plans)),
                  key=lambda i: (plans[i]["intensity"], i))
    p = plans[idx]
    p["breaking"] = True
    p["whisper"] = False
    p["gain_db"] += float(b.get("gain_db", -2.4))
    p["rate"] *= float(b.get("rate", 0.9))
    p["pitch_st"] += float(b.get("pitch", -0.4))
    scale = _silence_scale(len(plans))
    p["pre_pause_ms"] = max(int(p.get("pre_pause_ms") or 0),
                            int(b.get("pre_pause_ms", 300) * scale))
    p["pause_s"] += float(b.get("after_ms", 450)) / 1000.0 * scale
    # breath marking removed (build 2026-09-30o)


def _apply_delivery(plans, style):
    """The FEELING layer — 14 styles × four emotional deliveries (delivery.py).

    Every sentence is performed with one of ITS OWN style's four deliveries
    (spec sections 1–14). The delivery moves pauses, emphasis, breath and
    rhythm — the delivery variables of the specification. It never moves the
    speaker: pitch, loudness and pace leave this function untouched, and the
    VOICE LOCK below has the last word. `style_guard` inside delivery.py
    refuses any delivery that belongs to a different style, so a feeling can
    never turn a Documentary read into a Movie Trailer.
    """
    if _DL is None or not plans:
        return
    prev, last_breath = None, -9
    for i, p in enumerate(plans):
        pos = i / max(1, len(plans) - 1)
        i5 = max(0, min(5, int(round(float(p.get("intensity") or 0) / 20.0))))
        try:
            name, moves = _DL.choose_delivery(
                style, p.get("text", ""), position=pos, intensity5=i5,
                emotion=p.get("emotion"), prev=prev)
        except Exception:
            return
        if not name:
            continue
        # REMOVED (build 2026-09-30o): a delivery may still describe itself as
        # breathing, but nothing inserts a breath any more — the delivery now
        # shows itself in pace, pauses and emphasis only.
        _DL.apply_to_plan_item(p, moves, name=name, style=style,
                               breath=False)
        p["delivery"] = name
        prev = name


def _apply_suspended(plans, style):
    """Unfinished endings for longing / uncertainty (not every sentence falls)."""
    s = spec(style)
    su = s.get("suspended") or {}
    if not su:
        return
    scale = _silence_scale(len(plans))
    for p in plans:
        if p.get("breaking"):
            continue
        why = p.get("boundary") in ("…", "?") or \
            any(w in p["text"] for w in SUSPEND_CUES)
        if not why:
            continue
        p["suspended"] = True
        p["pitch_st"] += float(su.get("pitch", 0.4))
        p["rate"] *= float(su.get("rate", 1.0))
        p["pause_s"] += float(su.get("pause_add", 0.3)) * scale


# boundaries the splitters produce (produce()/split_sentences pass them along)
_BOUND_MARKS = (".", "!", "?", "\u2026", "para", "\u17D4", "\u17D5")


def _unpack_unit(u):
    """One input unit -> (text, boundary, speaker, is_dialogue).

    Accepts every shape the callers use, because getting this wrong is not a
    detail: a misunderstood tuple makes the narrator say the SPEAKER LETTER
    instead of the sentence (that bug shipped once — the studio spoke "A").

        ("sentence", ".")                  split_sentences()
        (speaker, "sentence", ".")         the studio's produce()
        {"speaker", "text", "boundary"}    the pipeline
    """
    u = list(u)
    if len(u) == 1:
        return str(u[0]), ".", None, None
    if len(u) == 2:
        # (text, boundary) — but tolerate (speaker, text) as well
        if u[1] in _BOUND_MARKS:
            return str(u[0]), u[1], None, None
        if _looks_like_speaker(u[0]):
            return str(u[1]), ".", str(u[0]), None
        return str(u[0]), ".", None, None
    a, b, c = u[0], u[1], u[2]
    if c in _BOUND_MARKS:                       # (speaker, text, boundary)
        return str(b), c, (str(a) if a else None), (u[3] if len(u) > 3 else None)
    if b in _BOUND_MARKS:                       # (text, boundary, speaker)
        return str(a), b, (str(c) if c else None), (u[3] if len(u) > 3 else None)
    if _looks_like_speaker(a):                  # (speaker, text, ?)
        return str(b), ".", str(a), None
    return str(a), ".", None, None


def _looks_like_speaker(x):
    """'A', 'B', 'HOST 2' — a label, not a sentence."""
    t = str(x or "").strip()
    return 0 < len(t) <= 4 and all(ch.isalnum() or ch in " _-" for ch in t) \
        and not any("\u1780" <= ch <= "\u17ff" for ch in t)



# =============================================================================
# VOICE IDENTITY + EMOTION  (delivery only)
# =============================================================================
# The rule this section enforces, in the words of the specification:
#
#     STYLE CHANGE:          yes
#     EMOTION CHANGE:        yes
#     DELIVERY CHANGE:       yes
#     VOICE IDENTITY CHANGE: NO
#
# A style and an emotion may change pace, energy, pauses, breath, emphasis,
# rhythm, endings and the *direction* of the pitch — they may NOT re-tune the
# voice. That is why pitch movement and loudness are hard-capped here: a shift
# of a few semitones is what made the same speaker sound like a different
# (deeper, male-sounding) person.
#
#     ≤ 0.6 st  pitch movement   (≈ 3.5 % of frequency — movement you feel,
#                                 not a different speaker)
#     ≤ 2.0 dB  loudness change  (softer / stronger, same voice)
#     0.80–1.15 pace             (slow is slow, never a mumble)
#
# Pitch is compressed with tanh, not clipped, so a slower style still sits
# slightly lower than a brighter one (order is preserved, magnitude is not).

# VOICE LOCK — the style never touches the voice.
# Your voice is the voice. A style may move SILENCE (pauses, phrase rhythm,
# emphasis before the key phrase) and nothing else: no pitch shift, no loudness
# change, no pace change. Your own NARRATION SPEED is the only thing that moves
# the pace, and it is applied by the studio, exactly as you set it.
VOICE_LOCK = True

IDENTITY_PITCH_ST = 0.25      # kept for the guard math; the lock forces 0.0
IDENTITY_GAIN_DB = 0.8        # loudness may colour, never re-mix the voice
IDENTITY_RATE = (0.94, 1.06)  # the STYLE may move the pace ±6 % only
WHISPER_RATE_FLOOR = 0.92     # a whispered line may be a touch slower…
WHISPER_GAIN_DB = 1.6         # …and softer, but it is the same speaker
#: A whisper MOMENT may move the pace a little under the voice lock: a
#: whisper before sleep is soft and slow by definition (spec section 14,
#: “slower pacing, longer comfortable pauses”), and pacing is a delivery
#: variable, never a re-tune of the speaker. Bounded to −8 % so it can never
#: become another style's pace. Pitch and loudness stay exactly 0.0.
SPEED_MIN, SPEED_MAX = 0.5, 2.0   # the user's own NARRATION SPEED is free


def identity_guard(pitch_st, gain_db, rate):
    """Keep the performance inside the identity band. Returns the safe trio."""
    import math
    cap, gcap = IDENTITY_PITCH_ST, IDENTITY_GAIN_DB
    p = cap * math.tanh(float(pitch_st) / cap) if cap else float(pitch_st)
    g = gcap * math.tanh(float(gain_db) / gcap) if gcap else float(gain_db)
    r = max(IDENTITY_RATE[0], min(IDENTITY_RATE[1], float(rate)))
    return round(p, 3), round(g, 2), round(r, 4)


# --- emotion table -----------------------------------------------------------
# One entry per emotion: everything here is DELIVERY.
#   rate     multiplier band applied inside the style's own pace
#   energy   dB bias (after the identity guard, so it stays a colour)
#   pause    multiplier on the planned pause
#   pitch    (direction, amount in semitones) — small by design
#   breath   how audible the breath may be (0..1)
#   tension  0 soft/relaxed … 1 pressed
#   emphasis none / subtle / medium / strong  (how hard the key words are held)
#   ending   fall / rise / open / flat / firm / fragile
#   hold     how much the last important word of the phrase is prolonged
EMOTIONS = {
    "neutral":      dict(rate=(1.00, 1.00), energy=0.0, pause=1.00, pitch=(0, 0.0), breath=0.10, tension=0.15, emphasis="subtle", ending="flat",  hold=0.0),
    "calm":         dict(rate=(0.95, 0.99), energy=-0.5, pause=1.18, pitch=(-1, 0.15), breath=0.14, tension=0.08, emphasis="none",  ending="fall",  hold=0.0),
    "peaceful":     dict(rate=(0.92, 0.97), energy=-0.7, pause=1.28, pitch=(-1, 0.10), breath=0.16, tension=0.05, emphasis="none",  ending="fall",  hold=0.0),
    "warm":         dict(rate=(0.96, 1.00), energy=-0.2, pause=1.08, pitch=(+1, 0.20), breath=0.20, tension=0.10, emphasis="subtle", ending="fall",  hold=0.1),
    "tender":       dict(rate=(0.90, 0.96), energy=-0.8, pause=1.25, pitch=(+1, 0.15), breath=0.32, tension=0.06, emphasis="subtle", ending="fall",  hold=0.2),
    "comforting":   dict(rate=(0.92, 0.97), energy=-0.5, pause=1.22, pitch=(+1, 0.18), breath=0.24, tension=0.08, emphasis="subtle", ending="fall",  hold=0.1),
    "happy":        dict(rate=(1.00, 1.05), energy=+0.55, pause=0.92, pitch=(+1, 0.35), breath=0.16, tension=0.10, emphasis="subtle", ending="rise",  hold=0.0),
    "joyful":       dict(rate=(1.03, 1.09), energy=+0.95, pause=0.86, pitch=(+1, 0.45), breath=0.18, tension=0.10, emphasis="medium", ending="rise",  hold=0.0),
    "excited":      dict(rate=(1.05, 1.12), energy=+1.05, pause=0.80, pitch=(+1, 0.50), breath=0.20, tension=0.22, emphasis="medium", ending="rise",  hold=0.0),
    "hopeful":      dict(rate=(0.97, 1.02), energy=+0.25, pause=1.02, pitch=(+1, 0.28), breath=0.16, tension=0.12, emphasis="subtle", ending="open",  hold=0.1),
    "romantic":     dict(rate=(0.90, 0.96), energy=-0.6, pause=1.24, pitch=(+1, 0.22), breath=0.34, tension=0.12, emphasis="subtle", ending="fall",  hold=0.25),
    "nostalgic":    dict(rate=(0.91, 0.96), energy=-0.6, pause=1.26, pitch=(-1, 0.18), breath=0.26, tension=0.10, emphasis="subtle", ending="fall",  hold=0.2),
    "longing":      dict(rate=(0.90, 0.95), energy=-0.6, pause=1.28, pitch=(+1, 0.20), breath=0.32, tension=0.14, emphasis="subtle", ending="fall",  hold=0.3),
    "yearning":     dict(rate=(0.89, 0.95), energy=-0.5, pause=1.30, pitch=(+1, 0.24), breath=0.34, tension=0.20, emphasis="medium", ending="fall",  hold=0.3),
    "bittersweet":  dict(rate=(0.92, 0.97), energy=-0.4, pause=1.22, pitch=(-1, 0.12), breath=0.28, tension=0.14, emphasis="subtle", ending="fall",  hold=0.2),
    "sad":          dict(rate=(0.88, 0.94), energy=-0.8, pause=1.32, pitch=(-1, 0.18), breath=0.28, tension=0.16, emphasis="subtle", ending="fall",  hold=0.25),
    "deeply_sad":   dict(rate=(0.85, 0.92), energy=-1.0, pause=1.42, pitch=(-1, 0.15), breath=0.30, tension=0.18, emphasis="none",  ending="fall",  hold=0.3),
    "grief":        dict(rate=(0.84, 0.92), energy=-1.1, pause=1.50, pitch=(-1, 0.12), breath=0.38, tension=0.30, emphasis="subtle", ending="fragile", hold=0.35),
    "heartbroken":  dict(rate=(0.85, 0.93), energy=-0.9, pause=1.46, pitch=(-1, 0.14), breath=0.36, tension=0.32, emphasis="subtle", ending="fragile", hold=0.35),
    "lonely":       dict(rate=(0.86, 0.93), energy=-1.0, pause=1.48, pitch=(-1, 0.10), breath=0.34, tension=0.14, emphasis="none",  ending="fall",  hold=0.2),
    "regretful":    dict(rate=(0.88, 0.94), energy=-0.8, pause=1.38, pitch=(-1, 0.14), breath=0.30, tension=0.20, emphasis="subtle", ending="fall",  hold=0.25),
    "guilty":       dict(rate=(0.92, 0.97), energy=-0.7, pause=1.28, pitch=(-1, 0.12), breath=0.26, tension=0.30, emphasis="none",  ending="fall",  hold=0.15),
    "ashamed":      dict(rate=(0.91, 0.96), energy=-0.9, pause=1.34, pitch=(-1, 0.14), breath=0.28, tension=0.34, emphasis="none",  ending="fall",  hold=0.2),
    "vulnerable":   dict(rate=(0.90, 0.96), energy=-0.8, pause=1.30, pitch=(+1, 0.10), breath=0.40, tension=0.24, emphasis="subtle", ending="fragile", hold=0.25),
    "worried":      dict(rate=(0.96, 1.04), energy=-0.3, pause=1.06, pitch=(+1, 0.22), breath=0.28, tension=0.46, emphasis="subtle", ending="open",  hold=0.1),
    "anxious":      dict(rate=(1.00, 1.09), energy=-0.2, pause=0.88, pitch=(+1, 0.30), breath=0.34, tension=0.55, emphasis="subtle", ending="open",  hold=0.0),
    "fearful":      dict(rate=(0.96, 1.05), energy=-0.6, pause=1.00, pitch=(+1, 0.30), breath=0.40, tension=0.62, emphasis="medium", ending="open",  hold=0.1),
    "scared":       dict(rate=(1.00, 1.10), energy=-0.4, pause=0.92, pitch=(+1, 0.35), breath=0.44, tension=0.70, emphasis="medium", ending="fragile", hold=0.0),
    "panicked":     dict(rate=(1.08, 1.15), energy=+0.6, pause=0.72, pitch=(+1, 0.50), breath=0.50, tension=0.85, emphasis="strong", ending="open",  hold=0.0),
    "shocked":      dict(rate=(0.94, 1.02), energy=-0.2, pause=1.55, pitch=(+1, 0.40), breath=0.30, tension=0.50, emphasis="strong", ending="fragile", hold=0.2),
    "surprised":    dict(rate=(1.00, 1.08), energy=+0.30, pause=0.98, pitch=(+1, 0.45), breath=0.22, tension=0.30, emphasis="medium", ending="rise",  hold=0.0),
    "angry":        dict(rate=(0.98, 1.06), energy=+1.10, pause=0.86, pitch=(+1, 0.35), breath=0.12, tension=0.78, emphasis="strong", ending="firm",  hold=0.1),
    "controlled_anger": dict(rate=(0.94, 1.00), energy=+0.55, pause=1.06, pitch=(-1, 0.10), breath=0.10, tension=0.68, emphasis="strong", ending="firm", hold=0.2),
    "irritated":    dict(rate=(0.99, 1.06), energy=+0.35, pause=0.94, pitch=(+1, 0.22), breath=0.16, tension=0.52, emphasis="medium", ending="firm",  hold=0.0),
    "frustrated":   dict(rate=(0.97, 1.04), energy=+0.45, pause=1.00, pitch=(+1, 0.20), breath=0.20, tension=0.56, emphasis="strong", ending="firm",  hold=0.1),
    "resentful":    dict(rate=(0.95, 1.01), energy=+0.25, pause=1.10, pitch=(-1, 0.12), breath=0.14, tension=0.60, emphasis="medium", ending="firm",  hold=0.15),
    "mysterious":   dict(rate=(0.88, 0.95), energy=-0.9, pause=1.42, pitch=(-1, 0.12), breath=0.30, tension=0.30, emphasis="subtle", ending="open",  hold=0.2),
    "suspenseful":  dict(rate=(0.86, 0.94), energy=-1.0, pause=1.55, pitch=(-1, 0.10), breath=0.26, tension=0.62, emphasis="subtle", ending="open",  hold=0.25),
    "serious":      dict(rate=(0.94, 0.99), energy=-0.2, pause=1.12, pitch=(-1, 0.10), breath=0.10, tension=0.40, emphasis="medium", ending="firm",  hold=0.1),
    "solemn":       dict(rate=(0.86, 0.93), energy=-0.6, pause=1.45, pitch=(-1, 0.10), breath=0.14, tension=0.28, emphasis="medium", ending="firm",  hold=0.25),
    "confused":     dict(rate=(0.96, 1.06), energy=-0.3, pause=1.12, pitch=(+1, 0.25), breath=0.26, tension=0.38, emphasis="subtle", ending="open",  hold=0.1),
    "uncertain":    dict(rate=(0.95, 1.04), energy=-0.3, pause=1.15, pitch=(+1, 0.22), breath=0.24, tension=0.32, emphasis="none",  ending="open",  hold=0.1),
    "relieved":     dict(rate=(0.94, 0.99), energy=-0.35, pause=1.20, pitch=(-1, 0.12), breath=0.34, tension=0.06, emphasis="subtle", ending="fall",  hold=0.15),
    "curious":      dict(rate=(0.99, 1.05), energy=+0.10, pause=1.00, pitch=(+1, 0.35), breath=0.18, tension=0.14, emphasis="subtle", ending="open",  hold=0.05),
    "determined":   dict(rate=(0.98, 1.04), energy=+0.55, pause=0.94, pitch=(+1, 0.15), breath=0.10, tension=0.45, emphasis="strong", ending="firm",  hold=0.1),
    "confident":    dict(rate=(0.97, 1.02), energy=+0.30, pause=1.00, pitch=(0, 0.05), breath=0.08, tension=0.32, emphasis="medium", ending="firm",  hold=0.05),
    "triumphant":   dict(rate=(0.98, 1.05), energy=+1.20, pause=1.10, pitch=(+1, 0.40), breath=0.10, tension=0.35, emphasis="strong", ending="firm",  hold=0.2),
    "desperate":    dict(rate=(1.02, 1.10), energy=+0.45, pause=0.86, pitch=(+1, 0.40), breath=0.44, tension=0.70, emphasis="strong", ending="fragile", hold=0.0),
    "revelation":   dict(rate=(0.85, 0.93), energy=-0.3, pause=1.58, pitch=(+1, 0.25), breath=0.20, tension=0.40, emphasis="strong", ending="fall",  hold=0.35),
    "tense":        dict(rate=(0.92, 0.99), energy=-0.4, pause=1.18, pitch=(0, 0.10), breath=0.22, tension=0.72, emphasis="medium", ending="open",  hold=0.15),
}

#: names the specification lists that map onto the table above
EMOTION_ALIASES = {
    "deeply sad": "deeply_sad", "deep_sad": "deeply_sad", "very sad": "deeply_sad",
    "fear": "fearful", "afraid": "fearful", "panic": "panicked",
    "anger": "angry", "rage": "angry", "controlled anger": "controlled_anger",
    "frustration": "frustrated", "irritation": "irritated", "resentment": "resentful",
    "suspense": "suspenseful", "mystery": "mysterious", "seriousness": "serious",
    "regret": "regretful", "guilt": "guilty", "shame": "ashamed",
    "confusion": "confused", "relief": "relieved", "surprise": "surprised",
    "shock": "shocked", "hope": "hopeful", "joy": "joyful", "happiness": "happy",
    "excitement": "excited", "triumph": "triumphant", "determination": "determined",
    "confidence": "confident", "vulnerability": "vulnerable", "longing": "longing",
    "yearning": "yearning", "loneliness": "lonely", "grief": "grief",
    "heartbreak": "heartbroken", "nostalgia": "nostalgic", "sadness": "sad",
    "tenderness": "tender", "comfort": "comforting", "peace": "peaceful",
    "calmness": "calm", "warmth": "warm", "curiosity": "curious",
    "thoughtful": "nostalgic", "conclusive": "serious", "informative": "neutral",
    "formal": "serious", "epic": "triumphant", "awed": "hopeful",
    "dread": "suspenseful", "exhausted": "deeply_sad", "wistful": "nostalgic",
    "compassionate": "comforting", "affectionate": "tender", "reverent": "solemn",
    "amused": "happy", "playful": "happy", "proud": "confident",
    "inspired": "hopeful", "urgent": "panicked", "thoughtful ": "nostalgic",
}


def emo(name):
    """Delivery channels for an emotion name (unknown -> neutral)."""
    if not name:
        return EMOTIONS["neutral"]
    key = str(name).strip().lower().replace("-", "_").replace(" ", "_")
    if key in EMOTIONS:
        return EMOTIONS[key]
    alt = EMOTION_ALIASES.get(str(name).strip().lower())
    return EMOTIONS.get(alt, EMOTIONS["neutral"])


# --- what the text is doing --------------------------------------------------
#: words that carry a feeling; the emotion engine looks for them, not for luck
EMO_WORDS = (
    # words taken from real Khmer fiction (the story this was built against)
    ("sad", ("ទឹកភ្នែក", "ភាពស្ងាត់", "ស្ងាត់", "ចម្ងាយ", "រង់ចាំ", "រំភើបចិត្ត",
             "ត្រូវការអ្នក", "ខ្ញុំស្រឡាញ់អ្នក", "ការភ័យ", "លាហើយ")),
    ("lonely", ("គ្មានសារ", "មិនបានឆ្លើយ", "មិនលើក", "ដេក", "យប់", "ម្នាក់ឯង")),
    ("grief", ("ស្លាប់", "បាត់បង់", "យំ", "ខ្មោច", "ឈឺចាប់", "សង្រ្គោះ", "អនិច្ចា")),
    ("heartbroken", ("បែកបាក់", "ចិត្តបែក", "កំព្រា", "បោះបង់ខ្ញុំ", "ចាកចេញពីខ្ញុំ")),
    ("sad", ("ខកចិត្ត", "ស្តាយ", "ឈឺចិត្ត", "ក្រៀមក្រំ", "ទុក្ខ", "មិនស្រួលចិត្ត")),
    ("lonely", ("ម្នាក់ឯង", "ឯកា", "គ្មានអ្នកណា", "ស្ងាត់ជ្រងំ")),
    ("romantic", ("ស្រលាញ់", "ស្រឡាញ់", "នឹក", "ចងចាំ", "ថើប", "ឱប", "ជាទីស្រលាញ់")),
    ("nostalgic", ("ធ្លាប់", "អតីត", "កាលពី", "ពីមុន", "រូបថត", "ចាស់")),
    ("yearning", ("ចង់ឃើញ", "ចង់ជួប", "ត្រូវការអ្នក", "សង្ស័យថា")),
    ("fearful", ("ខ្លាច", "ភ័យ", "គ្រោះថ្នាក់", "អាសន្ន", "រត់គេច")),
    ("anxious", ("បារម្ភ", "កង្វល់", "មិនស្រួលខ្លួន", "ចង្អៀតចង្អល់")),
    ("panicked", ("ស្រែក", "ជួយ", "រត់", "ភ្លាមៗណាស់")),
    ("angry", ("ខឹង", "ក្តៅចិត្ត", "ឈ្លោះ", "ចោទប្រកាន់", "អាស្រូវ")),
    ("frustrated", ("ហត់", "អស់កម្លាំងចិត្ត", "មិនចេះចប់")),
    ("guilty", ("កំហុស", "សុំទោស", "ខ្ញុំខុស", "អៀនខ្មាស")),
    ("relieved", ("ស្រួលចិត្ត", "ធូរស្រាល", "រួចផុត", "អស់បារម្ភ")),
    ("hopeful", ("សង្ឃឹម", "អនាគត", "ភ្លឺ", "បានឆាប់", "ជឿថា")),
    ("triumphant", ("ជ័យជម្នះ", "ឈ្នះ", "សម្រេច", "បានធ្វើវា")),
    ("joyful", ("សប្បាយ", "រីករាយ", "ញញឹម", "សើច")),
    ("curious", ("ហេតុអ្វី", "អ្វីទៅ", "ចង់ដឹង", "តើ")),
    ("worried", ("សង្ស័យ", "មិនប្រាកដ", "ប្រហែល", "ឬអត់")),
    ("mysterious", ("អាថ៌កំបាំង", "សម្ងាត់", "អ្នកណា", "លាក់")),
    ("solemn", ("ព្រះ", "បុណ្យ", "អរគុណព្រះ", "សព", "គោរព")),
    ("serious", ("សំខាន់", "ចាំបាច់", "ពិតប្រាកដ", "សេចក្តីពិត")),
    ("desperate", ("សុំ", "កុំបោះបង់", "ជួយខ្ញុំ", "អង្វរ")),
)


def detect_emotion(text, style="natural", position=None, is_dialogue=None):
    """Automatic emotion detection (primary, secondary, intensity 0–5).

    The STORY decides, the STYLE only frames it: a sad passage in Documentary
    stays documentary-sad (see `style_frame`). Returns
    {primary, secondary, intensity, confidence, why}.
    """
    sid = style_id(style)
    t = (text or "").strip()
    low = t.lower()
    hits = []
    for name, words in EMO_WORDS:
        for w in words:
            if w in t:
                hits.append((name, w))
    q = t.endswith("?") or "?" in t[-3:]
    ex = t.endswith("!") or "!" in t[-3:]
    ell = "..." in t or "…" in t
    caps = len(re.findall(r"[�-�]", t))       # Khmer has no case; kept for Latin
    latin_caps = len(re.findall(r"\b[A-Z]{3,}\b", t))
    quoted = bool(re.search(r'["“”]', t)) and is_dialogue is None
    n = max(1, len(re.findall(r"\S+", t)))

    primary, why = None, ""
    if hits:
        # the strongest feeling named in the sentence wins; ties -> first
        prio = {"grief": 6, "heartbroken": 6, "panicked": 6, "angry": 5,
                "fearful": 5, "sad": 4, "lonely": 4, "romantic": 4,
                "triumphant": 4, "joyful": 3, "hopeful": 3, "nostalgic": 3,
                "anxious": 3, "guilty": 3, "mysterious": 2, "serious": 2,
                "solemn": 2, "curious": 1, "worried": 1, "relieved": 2,
                "yearning": 3, "frustrated": 3, "desperate": 5, "confused": 1}
        hits.sort(key=lambda h: (-prio.get(h[0], 1), t.find(h[1])))
        primary, why = hits[0][0], "word: " + hits[0][1]
    if primary is None:
        if ex:
            primary, why = "surprised", "exclamation"
        elif q:
            primary, why = ("curious" if sid in ("explainer", "documentary",
                                                 "natural", "news") else "worried"), "question"
        elif ell:
            primary, why = "uncertain", "trailing off"
        elif t.endswith("—") or t.endswith("-"):
            primary, why = "suspenseful", "cut-off line"
        elif is_dialogue or quoted:
            primary, why = "warm", "dialogue"
        else:
            primary, why = "neutral", "plain narration"

    secondary = None
    for name, _w in hits[1:3]:
        if name != primary:
            secondary = name
            break

    # intensity 0–5: feeling words + punctuation + length (his scale)
    i = 0
    if hits:
        i += 1
    if len(hits) > 1:
        i += 1
    if ex:
        i += 1
    if primary in ("panicked", "grief", "heartbroken", "desperate"):
        i += 1
    if latin_caps or caps:
        i += 1
    if n <= 3:
        i = max(0, i - 1)          # a two-word line cannot carry a big feeling
    if n > 18:
        i += 1                     # a long build-up does
    intensity = int(max(0, min(5, i)))
    if primary == "neutral":
        intensity = 1 if n > 2 else 0        # the spec: default is 1–3
    if position == 0:
        intensity = min(intensity, 3)          # do not open at maximum

    conf = "HIGH" if hits and len(hits) > 1 else ("MED" if hits else "LOW")
    return dict(primary=primary, secondary=secondary, intensity=intensity,
                confidence=conf, why=why, hits=[h[1] for h in hits[:3]])


#: how each style reacts to a feeling — the style controls the frame
STYLE_EMOTION_FRAME = {
    #                 soft  normal  strong   (multiplier on the emotion's energy)
    "natural":        (0.5, 0.7, 0.8), "storytelling": (0.8, 1.0, 1.05),
    "novel":          (0.7, 0.85, 0.9), "documentary":  (0.6, 0.75, 0.85),
    "trailer":        (0.9, 1.1, 1.15), "audiobook":    (0.75, 0.95, 1.05),
    "news":           (0.35, 0.5, 0.6), "explainer":    (0.6, 0.75, 0.85),
    "thriller":       (0.85, 1.0, 1.1), "meditation":   (0.4, 0.5, 0.6),
    "inner_monologue": (0.7, 0.85, 0.95), "sad_romantic": (0.8, 0.95, 1.0),
    "cinematic":      (0.9, 1.05, 1.15),
}


def style_frame(style, emotion, intensity5):
    """The style's control over an emotion: it never changes WHAT is felt,
    only how strongly the frame of that style allows it to show."""
    sid = style_id(style)
    frame = STYLE_EMOTION_FRAME.get(sid, (0.7, 0.9, 1.0))
    band = 0 if intensity5 <= 1 else (1 if intensity5 <= 3 else 2)
    return frame[band]


# --- clause level: emotion changes inside one sentence -----------------------
CLAUSE_MARKERS = {
    "ប៉ុន្តែ": ("turn", "suspenseful"), "តែ": ("turn", "uncertain"),
    "ផ្ទុយទៅវិញ": ("turn", "serious"), "ផ្ទុយមកវិញ": ("turn", "serious"),
    "ទោះបីជា": ("turn", "uncertain"), "ទោះជាយ៉ាងណា": ("turn", "serious"),
    "ស្រាប់តែ": ("shock", "shocked"), "ភ្លាមៗ": ("shock", "shocked"),
    "ដូច្នេះ": ("result", "serious"), "ហេតុនេះ": ("result", "serious"),
    "ព្រោះ": ("result", "thoughtful"), "ដោយសារតែ": ("result", "serious"),
    "ចុងក្រោយ": ("result", "solemn"), "បន្ទាប់មក": ("result", "neutral"),
    "ក្រោយមក": ("result", "neutral"), "ឥឡូវ": ("result", "confident"),
    "ហើយ": ("add", None), "បន្ទាប់ពី": ("result", None),
}


def clause_emotions(text, base_emotion):
    """Split a sentence where the emotion turns: [(text, emotion, marker, kind)].

    "…នឹងល្អ… ប៉ុន្តែ ពេលខ្ញុំបើកទ្វារ ខ្ញុំបានឃើញវា។" is not one colour.
    """
    t = (text or "").strip()
    if not t:
        return []
    # a sentence that OPENS with a contrast word is a turn by itself
    for marker, (kind, emo_name) in CLAUSE_MARKERS.items():
        if t.startswith(marker):
            rest = t[len(marker):].strip(" ,")
            own = emo_name or base_emotion
            if rest:
                return [(rest, own, marker, kind)]
    bounds = []
    for marker, (kind, emo_name) in CLAUSE_MARKERS.items():
        for m in re.finditer(re.escape(marker), t):
            at = m.start()
            before = t[max(0, at - 1):at]
            if before and ("ក" <= before <= "៿"):
                continue
            if at == 0:
                continue
            bounds.append((at, marker, kind, emo_name))
    for m in re.finditer(r"[,;\u17d6]\s+|\u2014", t):
        at = m.end()
        if 0 < at < len(t):
            bounds.append((at, m.group(0).strip(), "phrase", None))
    if not bounds:
        return [(t, base_emotion, "", "whole")]
    bounds.sort()
    edges, meta = [0], []
    seen = set()
    for at, marker, kind, emo_name in bounds:
        if at in seen:
            continue
        seen.add(at)
        edges.append(at)
        meta.append((marker, kind, emo_name))
    edges.append(len(t))
    out = []
    for i in range(len(edges) - 1):
        part = t[edges[i]:edges[i + 1]].strip()
        if not part:
            continue
        if i == 0:
            out.append((part, base_emotion, "", "open"))
        else:
            marker, kind, emo_name = meta[i - 1]
            names = [emo_name] if emo_name else []
            own = detect_emotion(part, "natural")["primary"]
            if own == "neutral" and kind == "add":
                own = base_emotion
            out.append((part, own if names == [] else names[0], marker, kind))
    return out or [(t, base_emotion, "", "whole")]


# --- the arc over a whole piece ---------------------------------------------
ARC_PHASES = ("opening", "development", "conflict", "rising", "climax",
              "release", "ending")


def emotion_arc(items):
    """INTRODUCTION → DEVELOPMENT → CONFLICT → RISING → CLIMAX → RELEASE → ENDING.
    The climax is chosen (the longest build-up before the end), never assumed."""
    n = len(items)
    if n == 0:
        return []
    if n == 1:
        return ["whole"]
    # the climax lives in the MIDDLE of the piece (30 %–75 %), never at an end:
    # a peak in the first or last sentence is not a narrative arc
    lo_i = max(1, int(round(n * 0.30)))
    hi_i = max(lo_i, int(round(n * 0.75)))
    cand = [i for i in range(lo_i, min(hi_i, n - 2) + 1)] or \
           [i for i in range(1, n - 1)] or [0]
    climax = max(cand, key=lambda i: (items[i].get("words", 0), -i))
    out = []
    for i in range(n):
        t = i / (n - 1)
        if i == climax:
            out.append("climax")
        elif i > climax:
            out.append("release" if i < n - 1 else "ending")
        elif t < 0.20:
            out.append("opening")
        elif t < 0.45:
            out.append("development")
        elif t < 0.68:
            out.append("conflict")
        else:
            out.append("rising")
    return out


#: how much each phase lifts the feeling (0..1 of the style band, roughly)
ARC_LIFT = {"opening": -0.14, "development": -0.02, "conflict": 0.10,
            "rising": 0.22, "climax": 0.34, "release": 0.04, "ending": -0.20,
            "whole": 0.0}


def apply_emotion(plan_items, style="natural"):
    """Second pass: give every sentence a feeling, an intensity, a delivery.

    Called by `plan()` after the style pass. Only delivery changes — see
    `identity_guard` for the hard limits on pitch and loudness.
    """
    if not plan_items:
        return plan_items
    s = spec(style)
    lo, hi = s["intensity"]
    span = max(1.0, hi - lo)
    phases = emotion_arc(plan_items)
    out = []
    for i, p in enumerate(plan_items):
        det = detect_emotion(p["text"], style, position=(0 if i == 0 else None),
                             is_dialogue=p.get("is_dialogue"))
        emo_name = det["primary"]
        e = emo(emo_name)
        phase = phases[i]
        # intensity: the feeling's own 0–5 scale, placed inside the style band
        t_style = (p["intensity"] - lo) / span
        t_emo = det["intensity"] / 5.0
        t = max(0.0, min(1.0, 0.45 * t_style + 0.55 * t_emo + ARC_LIFT[phase]))
        p["intensity"] = int(round(lo + span * t))
        p["emotion"] = emo_name
        p["emotion_secondary"] = det["secondary"]
        p["emotion_intensity5"] = det["intensity"]
        p["emotion_confidence"] = det["confidence"]
        p["phase"] = phase
        p["delivery"] = ("soft" if e["energy"] < -0.4 else
                         "strong" if e["energy"] > 0.5 else "medium")
        p["pause_class"] = ("very_long" if e["pause"] >= 1.45 else
                            "long" if e["pause"] >= 1.25 else
                            "medium" if e["pause"] >= 1.05 else "short")
        p["ending_style"] = e["ending"]
        p["emphasis_strength"] = e["emphasis"]
        p["tension"] = e["tension"]
        p["hold"] = e["hold"]
        p["clauses"] = clause_emotions(p["text"], emo_name)
        # a turn INSIDE the sentence colours the sentence (the clauses keep the
        # local detail, so the quiet beginning is still quiet in the render)
        for _c, _ce, _mk, _kind in p["clauses"]:
            if _kind in ("turn", "shock"):
                emo_name = _ce
                e = emo(emo_name)
                p["emotion"] = emo_name
                p["pause_s"] = round(p["pause_s"] * 1.08, 3)
                break

        # --- the emotion modulates the style's frame (never replaces it) ----
        frame = style_frame(style, emo_name, det["intensity"])
        r = _lerp(e["rate"][0], e["rate"][1], t_emo)
        p["rate"] = round(p["rate"] * (1.0 + (r - 1.0) * frame), 4)
        p["gain_db"] = round(p["gain_db"] + e["energy"] * frame, 2)
        p["pitch_st"] = round(p["pitch_st"] + e["pitch"][0] * e["pitch"][1] * frame, 3)
        p["pause_s"] = round(p["pause_s"] * _lerp(1.0, e["pause"], 0.55 + 0.45 * t_emo), 3)
        p["_breath_emo"] = e["breath"]
        out.append(p)

    # --- guards: contrast, no overacting, endings that differ ---------------
    out = _no_same_emotion_run(out)
    out = _ending_variety(out)
    out = _release_after_climax(out)
    for p in out:                          # the identity guard, LAST word
        p["intensity"] = int(max(lo, min(hi, p["intensity"])))
        p["pitch_st"], p["gain_db"], p["rate"] = identity_guard(
            p["pitch_st"], p["gain_db"], p["rate"])
        p["pause_s"] = max(0.0, min(4.0, p["pause_s"]))
    return out


def _no_same_emotion_run(items):
    """Never sad + sad + sad + sad for a whole chapter."""
    if len(items) < 4:
        return items
    run = 1
    for i in range(1, len(items)):
        if items[i]["emotion"] == items[i - 1]["emotion"]:
            run += 1
            if run >= 4:
                e = items[i]["emotion"]
                alt = {"sad": "reflective", "grief": "reverent", "lonely": "quiet",
                       "angry": "firm", "joyful": "warm", "neutral": "warm"}.get(e)
                items[i]["emotion"] = alt or ("thoughtful" if e != "thoughtful"
                                              else "warm")
                items[i]["emotion_secondary"] = e
                run = 1
        else:
            run = 1
    return items


def _ending_variety(items):
    """Paragraph endings must not all fall the same way (spec: ENDING ENGINE)."""
    cycle = ["fall", "firm", "open", "fall", "fragile", "firm"]
    k = 0
    for p in items:
        if p.get("boundary") == "para" or p.get("ending"):
            p["ending_style"] = cycle[k % len(cycle)]
            k += 1
    return items


def _release_after_climax(items):
    """After the peak: less energy, less tension, slower — the release."""
    idx = [i for i, p in enumerate(items) if p.get("phase") == "climax"]
    if not idx:
        return items
    c = idx[0]
    for p in items[c + 1:]:
        p["intensity"] = int(max(0, p["intensity"] - 6))
        p["gain_db"] = round(p["gain_db"] - 0.35, 2)
        p["pause_s"] = round(p["pause_s"] * 1.12, 3)
    return items


def emotion_report(plan_items):
    """Debug/output view: what the narrator is doing, sentence by sentence."""
    lines = []
    for p in plan_items:
        lines.append("%-16s i5=%d %-9s rate %.2f  pitch %+.2f st  %+0.1f dB  "
                     "pause %s (%.2fs)  ending=%s  %s"
                     % (p.get("emotion", "-"), p.get("emotion_intensity5", 0),
                        p.get("delivery", "-"), p.get("rate", 1.0),
                        p.get("pitch_st", 0.0), p.get("gain_db", 0.0),
                        p.get("pause_class", "-"), p.get("pause_s", 0.0),
                        p.get("ending_style", "-"),
                        (p.get("text") or "")[:42]))
    return "\n".join(lines)


def plan(units, style="natural", speed=1.0, pause=0.25, voice_pitch_st=0.0):
    """Turn analysed sentences into the performance plan.

    `units` is [(text, boundary)] or [{text, boundary}]. `speed` is the user's
    slider, `pause` the user's pause slider; both scale the style, they do not
    replace it. Returns a list of plan dicts used by the renderers.
    """
    s = spec(style)
    lo, hi = s["intensity"]

    items = []
    for i, u in enumerate(units):
        if isinstance(u, dict):
            text, boundary = u.get("text", ""), u.get("boundary", ".")
            spk = u.get("speaker")
            is_dialogue = u.get("is_dialogue")
        else:
            text, boundary, spk, is_dialogue = _unpack_unit(u)
        if not (text or "").strip():
            continue
        pos = "last" if i == len(units) - 1 else None
        a = analyse(text, boundary, style, position=pos, is_dialogue=is_dialogue)
        a["speaker"] = spk
        items.append(a)

    if not items:
        return []

    items = _add_contrast(items, style)
    items = _apply_arc(items, style)          # the style's emotional curve

    plans = []
    for i, a in enumerate(items):
        t = (a["intensity"] - lo) / max(1.0, (hi - lo))          # 0..1 in band
        # the style's own pace only — the user's speed slider is applied after
        # the identity guard, so it can never be mistaken for a voice change
        rate = _lerp(s["pace"][0], s["pace"][1], t)
        pitch = s["pitch"][0] + s["pitch"][1] * (2 * t - 1) * s["pitch_dir"]
        gain = _lerp(s["volume"][0], s["volume"][1], t)

        # dialogue gets its own (small, non-cartoonish) colouring
        if a["is_dialogue"]:
            d = s["dialogue"]
            rate *= d["rate"]
            pitch += d["pitch"]
            gain += d["volume"]

        # a different host/character shifts rhythm and register slightly, so
        # two speakers stay distinguishable without becoming caricatures
        if a["speaker"]:
            idx = (sum(ord(c) for c in str(a["speaker"])) % 3) - 1
            rotate = 0.02 * idx
            rate *= (1.0 + rotate)
            pitch += 0.25 * idx
            gain += 0.25 * idx

        b = a["boundary"]
        mult = s["pauses"].get("para" if b == "para" else
                               "question" if b == "?" else
                               "exclaim" if b == "!" else
                               "ellipsis" if b == "…" else "period", 1.0)
        # movement inside the pause: dramatic styles open up as intensity rises
        pause_s = float(pause) * mult * (1.0 + (t - 0.5) * 0.5 * s["contrast"])
        pause_s = max(0.0, min(4.0, pause_s))

        plan_item = {
            "text": a["text"], "boundary": b, "speaker": a["speaker"],
            "emotion": a["emotion"], "intensity": a["intensity"],
            "attitude": a["attitude"], "words": a["words"],
            "rate": round(max(0.5, min(1.6, rate)), 4),
            "pitch_st": round(pitch + voice_pitch_st, 3),
            "gain_db": round(max(-6.0, min(6.0, gain)), 2),
            "pause_s": round(pause_s, 3),
            "breath": False, "pre_pause_ms": 0, "stress": "",
            "ending": False, "is_dialogue": a["is_dialogue"],
            # tone-style flags (styles 12 and 13); renderers only need the
            # numbers above, these exist for logs, tests and the summary line
            "whisper": False, "breaking": False, "suspended": False,
            "fear": False,
        }

        # --- phrase emphasis: pause before the phrase that carries the line ---
        if s["micro"] > 0 and t > 0.45 and a["words"] >= 6:
            phrase = _stress_phrase(a["text"], extra=s.get("stress_words"))
            if phrase:
                plan_item["stress"] = phrase
                plan_item["pre_pause_ms"] = int(round(90 * s["micro"] * t * 2))
        plans.append(plan_item)

    # --- the emotion pass: feeling, intensity, delivery (identity-safe) ----
    plans = apply_emotion(plans, style)

    # --- paragraph endings get a cadence (rate, pitch, extra silence) ------
    for i, p in enumerate(plans):
        nxt = plans[i + 1] if i + 1 < len(plans) else None
        is_last_of_para = (nxt is None) or (nxt["boundary"] == "para") or \
                          (p["boundary"] == "para")
        if is_last_of_para:
            e = s["ending"]
            p["ending"] = True
            p["rate"] *= e["rate"]
            p["pitch_st"] += e["pitch"]
            p["pause_s"] += float(pause) * (e["pause"] - 1.0)

    # --- the tone style of the two emotional styles ------------------------
    # Fear before the others (it colours whole scenes); the whisper gate then
    # picks its quiet passages, the break takes the peak, the suspended
    # endings soften the lines that are still waiting for an answer.
    _apply_fear(plans, style)
    _apply_whisper(plans, style)
    _apply_breaking(plans, style)
    _apply_suspended(plans, style)

    # --- the FEELING layer (14 styles × four emotional deliveries) ---------
    # STYLE stays fixed; the feeling moves pauses, emphasis, breath and rhythm
    # only. This is the delivery-only half of the specification — the pitch and
    # loudness it names are recorded in the plan for the logs, never applied
    # to the voice (VOICE LOCK, right below, is the last word).
    _apply_delivery(plans, style)

    # --- breathing: gated, never mechanical -------------------------------
    bmode = s["breath"]
    if bmode["mode"] != "off":
        spacing = {"open": 3, "gated": 4, "natural": 5, "subtle": 6}.get(
            bmode["mode"], 5)
        last_breath = -99
        for i, p in enumerate(plans):
            if i == 0 or i - last_breath < bmode["min_gap"]:
                continue        # never before the first word of a piece
            after_para = (plans[i - 1]["boundary"] == "para" or
                          plans[i - 1]["ending"])
            after_strong = plans[i - 1]["intensity"] >= lo + (hi - lo) * 0.7
            emotional = p["intensity"] >= lo + (hi - lo) * 0.6
            due = (i - last_breath) >= spacing
            # stable "chance" (crc32, not hash(): Python randomises str hashes
            # per process, which would make runs irreproducible)
            roll = (zlib.crc32(f"{style_id(style)}|{i}|{p['text'][:12]}"
                               .encode("utf-8")) % 100) / 100.0
            # REMOVED (build 2026-09-30o): the pauses stay, the synthesised
            # breath does not. `roll`/`due` are kept so the rule reads as it
            # did, but nothing is marked any more.
            _ = (after_para, after_strong, emotional, due, roll)

    for p in plans:
        p["rate"] = round(max(0.5, min(1.6, p["rate"])), 4)
        p["pause_s"] = round(max(0.0, min(5.0, p["pause_s"])), 3)
        p["gain_db"] = round(max(-6.0, min(6.0, p["gain_db"])), 2)
        p["pitch_st"] = round(max(-3.0, min(4.0, p["pitch_st"])), 3)
    # --- IDENTITY GUARD: the last word before the plan leaves the engine ----
    # Speed/HD, ending cadences and breath passes have all had their say; the
    # pitch and loudness limits are applied here so nothing can creep past them
    # and re-tune the voice. Delivery only — never a different speaker.
    for _p in plans:
        _p["intensity"] = int(max(s["intensity"][0], min(s["intensity"][1],
                                                         _p["intensity"])))
        # A whispered or breaking sentence is a MOMENT, not the voice of the
        # book: it may go softer and slower for that one line (that is what
        # makes it land). Its pitch is still held to the same identity band —
        # hesitation and quiet carry the break, never a changed timbre.
        if VOICE_LOCK:
            # SAME VOICE, ITS OWN STYLE (build 2026-09-29j).
            # The speaker never changes — pitch is pinned to 0.0 st here, and
            # nothing upstream can move it. What DOES move is the style's own
            # pace and softness (STYLE_DELIVERY): meditation is slow and soft,
            # news is brisk, a trailer is slow and heavy. Each feeling may
            # nudge that by a hair (STYLE_PACE_TOL), never more.
            _sd = style_delivery(style)
            _p["pitch_st"] = 0.0
            _p["gain_db"] = round(max(-STYLE_GAIN_CAP, min(STYLE_GAIN_CAP,
                max(_sd["gain_db"] - STYLE_GAIN_TOL,
                    min(_sd["gain_db"] + STYLE_GAIN_TOL, float(_p["gain_db"]))))), 2)
            _p["rate"] = round(max(SPEED_MIN, min(SPEED_MAX,
                max(_sd["pace"] - STYLE_PACE_TOL,
                    min(_sd["pace"] + STYLE_PACE_TOL, float(_p["rate"])))
                * float(speed))), 4)
            _p["pause_s"] = max(0.0, min(4.0, _p["pause_s"]))
            continue
        _moment = bool(_p.get("whisper") or _p.get("breaking"))
        _r_floor = WHISPER_RATE_FLOOR if _moment else IDENTITY_RATE[0]
        _g_cap = WHISPER_GAIN_DB if _moment else IDENTITY_GAIN_DB
        import math as _math
        _p["pitch_st"], _p["gain_db"], _rate = identity_guard(
            _p["pitch_st"], _p["gain_db"], _p["rate"])
        _p["gain_db"] = round(_g_cap * _math.tanh(_p["gain_db"] / _g_cap), 2)
        # a whispered sentence is allowed its own, slightly slower/softer floor
        _p["rate"] = round(max(_r_floor, min(IDENTITY_RATE[1], _p["rate"])), 4)
        # USER SPEED goes on last: it is a listening choice, not a performance
        # choice, so it is never squeezed by the identity band
        _p["rate"] = round(max(SPEED_MIN, min(SPEED_MAX,
                                              _p["rate"] * float(speed))), 4)
        _p["pause_s"] = max(0.0, min(4.0, _p["pause_s"]))
    # GUARANTEE (build 2026-09-30o): no style, feeling or delivery may put a
    # synthesised breath into a pause. The plan has no breath audio in it.
    for p in plans:
        p["breath"] = False
    return plans


def plan_text(text, style="natural", speed=1.0, pause=0.25):
    return plan(split_sentences(text), style=style, speed=speed, pause=pause)


_STRESS_CUES = re.compile(
    "|".join(re.escape(w) for words in CUE_LEXICON.values() for w in words),
    re.IGNORECASE)


def _stress_phrase(text, max_chars=42, extra=None):
    """The clause that carries the sentence — used for the emphasis pause.

    `extra` are the style's own emotional words (styles 12/13: you, me, us,
    once, still, never, again, remember, gone, home, alone, tomorrow, goodbye),
    so the emphasis lands on the word the sentence is really about.
    """
    pattern = _STRESS_CUES
    if extra:
        own = "|".join(re.escape(w) for w in extra if w)
        if own:
            pattern = re.compile(_STRESS_CUES.pattern + "|" + own, re.IGNORECASE)
    m = pattern.search(text or "")
    if not m:
        return ""
    start = max(0, text.rfind(" ", 0, m.start()))
    end = text.find(",", m.end())
    for stop in ("។", ".", "!", "?", "…"):
        k = text.find(stop, m.end())
        end = k if (end < 0 or (0 <= k < end)) else end
    if end < 0:
        end = min(len(text), m.end() + max_chars)
    return text[start:end].strip(" ,")[:max_chars]


# ---------------------------------------------------------------------------
# 4. Rendering helpers
# ---------------------------------------------------------------------------
def st_to_hz(semitones, base_hz=150.0):
    """Semitone shift -> the Hz figure the edge voices accept."""
    return int(round(base_hz * (2.0 ** (semitones / 12.0) - 1.0)))


def rate_percent(rate, base=1.0):
    """Multiplier -> the '+8%' string edge-tts wants."""
    pct = (float(rate) / float(base) - 1.0) * 100.0
    return f"{pct:+.0f}%"


def plan_summary(plans):
    """One compact line per sentence — for logs, tests and the CLI."""
    rows = []
    for i, p in enumerate(plans, 1):
        rows.append(
            f"{i:2d}. {p['emotion']:11s} I={p['intensity']:3d} "
            f"rate={p['rate']:.2f} pitch={p['pitch_st']:+.1f}st "
            f"gain={p['gain_db']:+.1f}dB pause={p['pause_s']:.2f}s"
            + (" breath" if p["breath"] else "")
            + (" end" if p["ending"] else "")
            + (" ~whisper" if p.get("whisper") else "")
            + (" !break" if p.get("breaking") else "")
            + (" ~~sus" if p.get("suspended") else "")
            + ("  [" + p["delivery"] + "]" if p.get("delivery") else "")
            + (" ^fear" if p.get("fear") else "")
            + (f" stress~{p['stress'][:18]!r}" if p["stress"] else "")
            + f"  {p['text'][:38]}")
    return "\n".join(rows)


def render_styled(text, dst, style, synth_fn, ffmpeg="ffmpeg", speed=1.0,
                  pause=0.25, sr=24000, engine_name="", log=print, breath=False):   # breath audio removed (build 2026-09-30o)
    """Render one block of text as a PERFORMED wav (used by the batch pipeline).

    `synth_fn(text, out_path, rate_percent, pitch_hz)` must synthesize one
    sentence with the plain engine and return a dict with "ok"/"engine".
    Every sentence is synthesized on its own so it can be performed (pace,
    pitch, loudness), then the pieces are joined with the planned pauses and
    breaths. If any sentence fails, the caller can fall back to plain synth —
    the return value says what happened.
    """
    import os
    import subprocess
    import wave as _wave

    try:
        import numpy as np
    except Exception:
        return {"ok": False, "error": "numpy missing"}

    plans = plan_text(text, style=style, speed=speed, pause=pause)
    if not plans:
        return {"ok": False, "error": "nothing to perform"}

    spec_ = spec(style)
    level_db = spec_["breath"]["level_db"]
    pieces, engines, tmpdir = [], [], None
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="narration_")

    def decode(path):
        cmd = [ffmpeg, "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr),
               "-f", "f32le", "pipe:1"]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0 or not r.stdout:
            return None
        return np.frombuffer(r.stdout, dtype=np.float32)

    def stretch(arr, rate):
        if abs(rate - 1.0) < 0.02:
            return arr
        rate = max(0.5, min(1.6, rate))
        chain, r = [], rate
        while r > 2.0:
            chain.append("atempo=2.0"); r /= 2.0
        while r < 0.5:
            chain.append("atempo=0.5"); r /= 0.5
        chain.append(f"atempo={r:.4f}")
        p = subprocess.Popen(
            [ffmpeg, "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", "1",
             "-i", "pipe:0", "-filter:a", ",".join(chain), "-f", "f32le",
             "-ar", str(sr), "-ac", "1", "pipe:1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, _ = p.communicate(arr.astype("<f4").tobytes(), timeout=300)
        return np.frombuffer(out, dtype=np.float32) if (p.returncode == 0 and out) else arr

    ok_count = 0
    for i, item in enumerate(plans):
        raw = os.path.join(tmpdir, f"u{i:03d}.wav")
        try:
            r = synth_fn(item["text"], raw,
                         rate_percent(item["rate"]),
                         st_to_hz(item["pitch_st"]))
        except Exception as e:
            r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if not r.get("ok"):
            log(f"[style] sentence {i+1} failed ({str(r.get('error'))[:60]}) — "
                f"keeping the previous audio")
            continue
        arr = decode(raw)
        if arr is None or not arr.size:
            continue
        ok_count += 1
        engines.append(r.get("engine", ""))
        if engine_name != "edge":                 # engine had no rate control
            arr = stretch(arr, item["rate"])
        if abs(item["gain_db"]) >= 0.05:
            arr = arr * (10.0 ** (item["gain_db"] / 20.0))
        # Whisper REMOVED (build 2026-09-30n): this line used to call
        # whisper.py to turn the sentence into a breath carrying the words —
        # a different sound from the voice that was speaking, which is why a
        # whisper arriving mid-read sounded like the voice being replaced. The
        # performance (rate, gain, pauses) is already applied above; the audio
        # now goes to the master exactly as the engine produced it.
        if i > 0:
            gap = plans[i - 1]["pause_s"]
            # REMOVED (build 2026-09-30o): no breath is written into the gap;
            # the pause is exact silence (the style demo clips have always
            # been built this way, and the user wants the generator to match).
            if gap > 0:
                pieces.append(np.zeros(int(gap * sr), dtype=np.float32))
        if item.get("pre_pause_ms"):
            pieces.append(np.zeros(int(item["pre_pause_ms"] / 1000.0 * sr),
                                   dtype=np.float32))
        pieces.append(arr)

    try:
        os.remove(os.path.join(tmpdir, "")) if False else None
        for f in os.listdir(tmpdir):
            os.remove(os.path.join(tmpdir, f))
        os.rmdir(tmpdir)
    except Exception:
        pass

    if not pieces:
        return {"ok": False, "error": "no sentence could be synthesized"}

    audio = np.concatenate(pieces)
    audio = np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)
    peak = float(np.max(np.abs(audio))) or 1.0
    if peak > 0.995:
        audio = audio / peak * 0.98
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2")
    with _wave.open(dst, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return {"ok": True, "style": style_id(style), "sentences": len(plans),
            "rendered": ok_count, "seconds": round(len(audio) / sr, 2),
            "engine": engines[0] if engines else "",
            "breaths": sum(1 for p in plans if p["breath"]),
            "intensity": [min(p["intensity"] for p in plans),
                          max(p["intensity"] for p in plans)]}


def _breath_np(seconds, level_db, seed):
    """SILENCE — the pause breath was removed in build 2026-09-30o.

    This used to return a soft filtered-noise inhale, the sound the user
    kept hearing as a whisper between sentences. It stays as a named
    function only so that no stale caller can put that noise back: it
    returns exactly zero samples, for any duration, level or seed.
    """
    import numpy as np
    return np.zeros(max(1, int(seconds * 24000)), dtype=np.float32)


def style_table():
    """Text table of every style: band, pace, pitch, pauses, best for."""
    out = [f"{'style':22s} {'intensity':10s} {'pace':12s} {'pitch':12s} best for"]
    for sid in STYLE_ORDER:
        s = STYLE_SPECS[sid]
        out.append(
            f"{s['label'][:21]:22s} "
            f"{str(s['intensity'][0]) + '-' + str(s['intensity'][1]):10s} "
            f"{s['pace'][0]:.2f}-{s['pace'][1]:.2f}    "
            f"{s['pitch'][0]:+.1f}..{s['pitch'][1]:+.1f}st  {s['best_for'][:44]}")
    return "\n".join(out)


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Narration style engine")
    ap.add_argument("--styles", action="store_true", help="show every style")
    ap.add_argument("--typeset", action="store_true", help="show the UI list")
    ap.add_argument("--plan", default="", help="plan this text")
    ap.add_argument("--style", default="natural")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--pause", type=float, default=0.25)
    a = ap.parse_args()

    if a.typeset:
        print(json.dumps(style_list(), ensure_ascii=False, indent=1))
    elif a.plan:
        pl = plan_text(a.plan, a.style, a.speed, a.pause)
        print(plan_summary(pl))
        lo = min(p["intensity"] for p in pl)
        hi = max(p["intensity"] for p in pl)
        print(f"\n{len(pl)} sentences | style={style_id(a.style)} | "
              f"intensity {lo}-{hi} | total pause "
              f"{sum(p['pause_s'] for p in pl):.1f}s | "
              f"breaths {sum(1 for p in pl if p['breath'])}")
    else:
        print(style_table())
