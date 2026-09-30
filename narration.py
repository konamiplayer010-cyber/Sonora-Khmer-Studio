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
        pitch=(0.0, 0.8),            # bias, span (semitones)
        pitch_dir=+1,
        volume=(-1.0, 1.0),          # dB around the norm
        pauses=dict(period=1.0, question=1.05, exclaim=1.25, ellipsis=1.4,
                    para=1.7, comma=0.55),
        breath=dict(mode="natural", chance=0.22, level_db=-40.0, min_gap=3),
        micro=0.25,                  # phrase-emphasis strength
        ending=dict(rate=0.98, pitch=-0.4, pause=1.15),
        dialogue=dict(rate=1.02, pitch=0.3, volume=0.5),
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
        pitch=(0.2, 2.2),
        pitch_dir=+1,
        volume=(-1.5, 2.5),
        pauses=dict(period=1.15, question=1.15, exclaim=1.45, ellipsis=1.7,
                    para=2.2, comma=0.65),
        breath=dict(mode="natural", chance=0.3, level_db=-38.0, min_gap=3),
        micro=0.55,
        ending=dict(rate=0.93, pitch=-1.0, pause=1.35),
        dialogue=dict(rate=1.04, pitch=0.9, volume=1.0),
        contrast=0.8,
        bed=("warm", 20),
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
        pitch=(-0.3, 1.4),
        pitch_dir=+1,
        volume=(-1.0, 1.8),
        pauses=dict(period=1.15, question=1.1, exclaim=1.3, ellipsis=1.6,
                    para=2.0, comma=0.6),
        breath=dict(mode="subtle", chance=0.2, level_db=-41.0, min_gap=4),
        micro=0.4,
        ending=dict(rate=0.95, pitch=-0.6, pause=1.3),
        dialogue=dict(rate=1.03, pitch=0.9, volume=0.8),
        contrast=0.7,
        bed=("warm", 15),
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
        pitch=(-0.6, 0.9),
        pitch_dir=+1,
        volume=(-0.8, 1.2),
        pauses=dict(period=1.2, question=1.05, exclaim=1.2, ellipsis=1.5,
                    para=2.3, comma=0.6),
        breath=dict(mode="subtle", chance=0.18, level_db=-42.0, min_gap=4),
        micro=0.45,
        ending=dict(rate=0.96, pitch=-0.7, pause=1.4),
        dialogue=dict(rate=1.0, pitch=0.2, volume=0.3),
        contrast=0.6,
        bed=("warm", 40),
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
        pitch=(-2.6, 1.6),
        pitch_dir=-1,                # louder/bigger = lower and grounded
        volume=(-1.5, 4.0),
        pauses=dict(period=1.5, question=1.4, exclaim=1.7, ellipsis=2.1,
                    para=2.8, comma=0.85),
        breath=dict(mode="gated", chance=0.35, level_db=-36.0, min_gap=3),
        micro=0.85,
        ending=dict(rate=0.85, pitch=-1.8, pause=1.8),
        dialogue=dict(rate=0.98, pitch=0.5, volume=0.8),
        contrast=0.95,
        bed=("drone", 45),
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
        pitch=(-0.2, 1.2),
        pitch_dir=+1,
        volume=(-0.6, 1.6),
        pauses=dict(period=1.15, question=1.1, exclaim=1.3, ellipsis=1.55,
                    para=2.1, comma=0.6),
        breath=dict(mode="subtle", chance=0.16, level_db=-42.0, min_gap=4),
        micro=0.4,
        ending=dict(rate=0.96, pitch=-0.5, pause=1.35),
        dialogue=dict(rate=1.05, pitch=0.8, volume=0.7),
        contrast=0.65,
        bed=("warm", 25),
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
        pitch=(-0.4, 0.7),
        pitch_dir=+1,
        volume=(-0.4, 1.4),
        pauses=dict(period=1.05, question=1.15, exclaim=1.3, ellipsis=1.3,
                    para=1.3, comma=0.45),
        breath=dict(mode="off", chance=0.0, level_db=-44.0, min_gap=99),
        micro=0.3,
        ending=dict(rate=1.0, pitch=-0.3, pause=1.05),
        dialogue=dict(rate=1.0, pitch=0.0, volume=0.0),
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
        pitch=(0.0, 1.3),
        pitch_dir=+1,
        volume=(-0.6, 1.6),
        pauses=dict(period=1.1, question=1.2, exclaim=1.3, ellipsis=1.4,
                    para=1.8, comma=0.6),
        breath=dict(mode="natural", chance=0.2, level_db=-40.0, min_gap=4),
        micro=0.5,
        ending=dict(rate=0.97, pitch=-0.4, pause=1.2),
        dialogue=dict(rate=1.02, pitch=0.4, volume=0.4),
        contrast=0.55,
        bed=("crackle", 30),
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
        pitch=(-1.8, 0.9),
        pitch_dir=-1,                # tension lives low and restrained
        volume=(-2.0, 2.2),
        pauses=dict(period=1.5, question=1.6, exclaim=1.5, ellipsis=2.0,
                    para=2.5, comma=0.9),
        breath=dict(mode="gated", chance=0.28, level_db=-37.0, min_gap=3),
        micro=0.6,
        ending=dict(rate=0.88, pitch=-1.4, pause=1.7),
        dialogue=dict(rate=0.97, pitch=-0.4, volume=0.4),
        contrast=0.9,
        bed=("drone", 30),
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
        pitch=(-1.0, 0.5),
        pitch_dir=+1,
        volume=(-2.0, 0.5),
        pauses=dict(period=1.9, question=1.7, exclaim=1.7, ellipsis=2.4,
                    para=3.2, comma=1.1),
        breath=dict(mode="open", chance=0.5, level_db=-38.0, min_gap=2),
        micro=0.15,
        ending=dict(rate=0.9, pitch=-0.4, pause=1.8),
        dialogue=dict(rate=0.92, pitch=0.0, volume=0.0),
        contrast=0.25,
        bed=("pad", 50),
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
        pitch=(-1.0, 1.2),
        pitch_dir=+1,
        volume=(-2.2, 1.2),
        pauses=dict(period=1.4, question=1.5, exclaim=1.4, ellipsis=1.9,
                    para=2.2, comma=0.85),
        breath=dict(mode="subtle", chance=0.34, level_db=-39.0, min_gap=3),
        micro=0.5,
        ending=dict(rate=0.9, pitch=-0.9, pause=1.5),
        dialogue=dict(rate=0.98, pitch=0.3, volume=0.3),
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
        pitch=(-1.2, 1.0),
        pitch_dir=+1,
        volume=(-2.4, 1.0),
        pauses=dict(period=1.45, question=1.6, exclaim=1.35, ellipsis=2.0,
                    para=2.4, comma=0.9),
        breath=dict(mode="subtle", chance=0.32, level_db=-39.0, min_gap=3),
        micro=0.6,
        ending=dict(rate=0.88, pitch=-1.1, pause=1.6),
        dialogue=dict(rate=0.96, pitch=0.2, volume=0.2),
        contrast=0.85,
        # --- the tone style (professional spec: whisper mode, breaking voice,
        # slow reading, pauses as emotional language) ---------------------------
        # whisper REMOVED (2026-09-30n): this style used to whisper roughly one
        # line in three mid-read (chance=0.34). No style whispers now — the
        # intimate passages are still performed softly, slowly and close, by the
        # same voice, but the whisper sound itself is gone.
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
        bed=("pad", 22),
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
        pitch=(-1.6, 1.8),
        pitch_dir=+1,
        volume=(-2.6, 3.2),
        pauses=dict(period=1.4, question=1.35, exclaim=1.6, ellipsis=2.0,
                    para=2.6, comma=0.8),
        breath=dict(mode="gated", chance=0.3, level_db=-37.0, min_gap=3),
        micro=0.75,
        ending=dict(rate=0.88, pitch=-1.3, pause=1.7),
        dialogue=dict(rate=1.03, pitch=1.0, volume=1.0),
        contrast=1.0,
        # --- the tone style (professional spec: whisper storytelling, fear
        # mode, breaking point, cinematic curve) ------------------------------
        # whisper REMOVED (2026-09-30n): no style may whisper a line any more
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
        bed=("drone", 30),
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
        p["gain_db"] += float(w.get("gain_db", -3.6))
        p["rate"] *= float(w.get("rate", 0.96))
        p["pitch_st"] += float(w.get("pitch", -0.3))
        # breath marking removed (build 2026-09-30o)
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


# --------------------------------------------------------------------------- #
# VOICE LOCK — shared by the studio and the batch pipeline
# --------------------------------------------------------------------------- #
# Your voice is the voice. A style (and a feeling) may move SILENCE — pauses,
# phrase rhythm, emphasis before the key phrase — and nothing else: no pitch
# shift, no loudness change, no pace change. Your own NARRATION SPEED is the
# only thing that moves the pace. Each style also has its own pace and its own
# softness from STYLE_DELIVERY (the specification's definition of a style),
# and a whisper MOMENT may slow the pace by up to -8 %. Pitch and loudness
# stay 0.0 in every style and every feeling.
VOICE_LOCK = True
IDENTITY_PITCH_ST = 0.25      # kept for the guard math; the lock forces 0.0
IDENTITY_GAIN_DB = 0.8        # loudness may colour, never re-mix the voice
IDENTITY_RATE = (0.94, 1.06)  # the STYLE may move the pace +/-6 % only
WHISPER_RATE_FLOOR = 0.92     # a whispered line may be a touch slower...
WHISPER_GAIN_DB = 1.6         # ...and softer, but it is the same speaker
SPEED_MIN, SPEED_MAX = 0.5, 2.0   # the user's own NARRATION SPEED is free


def identity_guard(pitch_st, gain_db, rate):
    """Keep the performance inside the identity band. Returns the safe trio."""
    import math
    cap, gcap = IDENTITY_PITCH_ST, IDENTITY_GAIN_DB
    p = cap * math.tanh(float(pitch_st) / cap) if cap else float(pitch_st)
    g = gcap * math.tanh(float(gain_db) / gcap) if gcap else float(gain_db)
    r = max(IDENTITY_RATE[0], min(IDENTITY_RATE[1], float(rate)))
    return round(p, 3), round(g, 2), round(r, 4)


def _apply_delivery(plans, style):
    """The FEELING layer — 14 styles x four emotional deliveries (delivery.py).

    Every sentence is performed with one of ITS OWN style's four deliveries
    (spec sections 1-14): pauses, emphasis, breath and rhythm only. `style_guard`
    inside delivery.py refuses any delivery that belongs to another style, so a
    feeling can never turn one style into another.
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


def _looks_like_speaker(x):
    """'A', 'B', 'HOST 2' — a label, not a sentence."""
    t = str(x or "").strip()
    return 0 < len(t) <= 4 and all(ch.isalnum() or ch in " _-" for ch in t) \
        and not any("\u1780" <= ch <= "\u17ff" for ch in t)


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
        rate = _lerp(s["pace"][0], s["pace"][1], t) * float(speed)
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

    # --- the FEELING layer (14 styles x four emotional deliveries) ---------
    # STYLE stays fixed; the feeling moves pauses, emphasis, breath and rhythm
    # only. The VOICE LOCK below has the last word, so nothing a feeling asks
    # for can re-tune the speaker.
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
    # The studio and the batch pipeline must agree: the style and the feeling
    # shape DELIVERY only. Pitch, loudness and pace are held to the speaker
    # and to the user's own NARRATION SPEED. A user's explicit voice pitch
    # (voice_pitch_st) is a listening choice, not a style choice, and survives.
    for p in plans:
        p["intensity"] = int(max(s["intensity"][0],
                                 min(s["intensity"][1], p["intensity"])))
        if VOICE_LOCK:
            # SAME VOICE, ITS OWN STYLE (build 2026-09-29j): the speaker never
            # changes (pitch pinned to the user's own choice, which defaults to
            # 0.0 st) but the style has its own pace and softness, so
            # meditation is slow and soft and news is brisk. STYLE_DELIVERY
            # holds the table; STYLE_PACE_TOL is what a feeling may add.
            _sd = style_delivery(style)
            p["pitch_st"] = round(float(voice_pitch_st or 0.0), 3)
            p["gain_db"] = round(max(-STYLE_GAIN_CAP, min(STYLE_GAIN_CAP,
                max(_sd["gain_db"] - STYLE_GAIN_TOL,
                    min(_sd["gain_db"] + STYLE_GAIN_TOL, float(p["gain_db"]))))), 2)
            p["rate"] = round(max(SPEED_MIN, min(SPEED_MAX,
                max(_sd["pace"] - STYLE_PACE_TOL,
                    min(_sd["pace"] + STYLE_PACE_TOL, float(p["rate"])))
                * float(speed))), 4)
            p["pause_s"] = round(max(0.0, min(4.0, p["pause_s"])), 3)
    # GUARANTEE (build 2026-09-30o): the performance carries no breath audio
    # in any style, at any intensity, whatever the rules above decided.
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
