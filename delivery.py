#!/usr/bin/env python3
"""delivery.py — the FEELING layer (14 narration styles × emotional delivery).

The 14 narration styles say HOW the story is narrated.
This module says HOW THE NARRATOR FEELS while narrating it.

    STYLE     = FIXED      the selected style is the permanent framework
    EMOTION   = VARIABLE   what the narrator feels right now
    DELIVERY  = VARIABLE   pacing, pauses, energy, emphasis, breath, pitch
                           movement, rhythm, sentence ending
    INTENSITY = VARIABLE   0 neutral … 5 extreme (default 1–3)
    VOICE     = FIXED      the same speaker, unchanged (VOICE LOCK: pitch 0.0,
                           loudness 0.0, pace = the user's own speed)

MASTER RULE — STYLE PROTECTION
------------------------------
An emotion may never turn one style into another:

    DOCUMENTARY + SAD  = sad feeling performed as Documentary
    THRILLER    + SAD  = sad feeling performed as Thriller
    AUDIOBOOK   + FEAR = fear performed as Audiobook
    INNER MONOLOGUE + LOVE = love performed as Inner Monologue

The selected style stays recognisable at all times. `style_guard()` enforces
that in code: every delivery belongs to one style, and its moves are clamped
to that style's envelope. Nothing here can make a Documentary read sound like
a Movie Trailer.

WHAT A DELIVERY MAY MOVE
------------------------
Only the delivery variables of the specification:

    pacing · pause · energy · emphasis · breath · pitch movement · rhythm ·
    sentence ending

Under VOICE LOCK the engine keeps pitch and loudness exactly 0.0 and the pace
at the user's own speed, so in the rendered audio the feeling is carried by
pauses, emphasis and breath — the parts of delivery that do not re-tune a
voice. `moves` still names the full set (energy, pitch movement) because that
is the language of the specification, and the tests assert they never reach
the voice.

WHISPER RULE
------------
Whisper is a delivery effect and always a brief MOMENT (build l removed
whose identity IS a soft, slow whisper before sleep. The whisper depths live
here (`whisper_depth()`), the audio lives in whisper.py.

    python delivery.py --list
    python delivery.py --check
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# 1. the 14 styles and their four emotional deliveries                        #
# --------------------------------------------------------------------------- #
#: the core identity sentence of every style (spec, section “CORE IDENTITY”)
STYLE_CORE = {
    "natural": "Natural human reading — spontaneous and conversational.",
    "storytelling": "Storytelling / story narration (Khmer: និទានរឿង).",
    "novel": "Novel / literary narration — immersive across long-form reading.",
    "documentary": "Documentary / factual narration — controlled, informative, respectful.",
    "trailer": "Movie trailer / cinematic promotional narration — powerful, deliberate, contrasted.",
    "audiobook": "Professional audiobook narration — adapts to story and characters, comfortable for hours.",
    "news": "News anchor / news reading — disciplined and information-first.",
    "explainer": "Explainer / educational narration — supports understanding, attention, connection.",
    "thriller": "Thriller / suspense narration — tension through contrast, uncertainty, silence, controlled reaction.",
    "meditation": "Meditation / relaxation narration — peaceful, spacious, gentle, emotionally safe.",
    "inner_monologue": "Private thought and internal emotional narration (Khmer: និយាយរឿងក្នុងចិត្ត).",
    "sad_romantic": "Love mixed with sadness, longing, distance, memory, heartbreak or loss.",
    "cinematic": "Emotional cinematic storytelling — the most emotionally dynamic, still natural.",
}

#: every style ships exactly four emotional deliveries (spec, sections 1–14)
DELIVERIES = {
    "natural": [
        ("Natural / Comfortable",
         "Relaxed, easy conversational flow with small pauses and subtle inflection — "
         "the words feel naturally spoken, not read from a page."),
        ("Warm / Personal",
         "Sincere, personal delivery with gentle emotional variation; important words "
         "breathe, so the listener feels personally included."),
        ("Reflective / Thoughtful",
         "Calm and thoughtful; meaningful ideas get a little more space, with quiet "
         "pauses and gentle sentence endings."),
        ("Subtle Emotion",
         "Restrained, believable emotion — feeling appears through small changes in "
         "pace, emphasis, hesitation and silence rather than acting."),
    ],
    "storytelling": [
        ("Inviting Storyteller",
         "Engaging storytelling that draws the listener in; expressive pauses and small "
         "moments of anticipation lead each sentence forward."),
        ("Suspenseful Storyteller",
         "Curiosity through controlled pacing and meaningful pauses; important details "
         "get room to land, uncertainty becomes restrained."),
        ("Wonder / Imagination",
         "Discovery and emotional wonder; descriptive moments receive gentle expressive "
         "emphasis so places and people feel vivid without over-dramatising."),
        ("Personal / Heartfelt",
         "The story feels personally meaningful — soft hesitation, expressive pauses and "
         "subtle intensity change bring the listener close to it."),
    ],
    "novel": [
        ("Immersive Emotion",
         "Emotion develops gradually through the prose; subtle pacing and expressive "
         "pauses keep the listener inside the world of the novel."),
        ("Character-Aware",
         "The narration responds to what the character experiences — pain, joy, "
         "uncertainty and hope through pacing, emphasis and restraint, never theatre."),
        ("Reflective / Literary",
         "Emotionally layered reading that lingers slightly on important lines while "
         "keeping the natural flow of literary narration."),
        ("Intimate / Vulnerable",
         "A close connection to the character's inner experience — gentler in vulnerable "
         "moments, with restrained feeling and carefully placed silence."),
    ],
    "documentary": [
        ("Serious / Reflective",
         "Composed, restrained seriousness; important events carry weight through slower "
         "pacing, careful emphasis and respectful pauses."),
        ("Historical / Solemn",
         "Dignified delivery for loss, death, destruction or major historical change — "
         "quieter, more reflective, letting silence carry the seriousness."),
        ("Hopeful / Uplifting",
         "A controlled sense of hope: slightly lighter pacing and a gently more open "
         "feeling, while the documentary identity stays factual and professional."),
        ("Human / Compassionate",
         "Informative, with subtle human feeling heard; suffering and personal "
         "consequences receive more emotional care without becoming drama."),
    ],
    "trailer": [
        ("Powerful / Anticipatory",
         "Deliberate, emotionally charged build-up; key phrases get weight and carefully "
         "timed pauses — something important is approaching."),
        ("Dark / Threatening",
         "Darker through restraint: controlled silence and slower delivery of crucial "
         "words; tension builds from what is left unsaid."),
        ("Emotional / Epic",
         "Highly expressive, growing toward a peak; important phrases are emphasised and "
         "pauses make space for the feeling to land."),
        ("Shock / Revelation",
         "Expectation is built, then a deliberate pause and a strong emotional shift "
         "arrives with the reveal — contrast, not loudness."),
    ],
    "audiobook": [
        ("Immersive / Emotional",
         "Continuous, alive delivery that responds to the story's changing emotions while "
         "staying smooth and believable over long passages."),
        ("Character / Feeling Driven",
         "Subtly follows what the characters feel: happier is more open, sadness more "
         "restrained, fear more cautious, love more intimate — no exaggerated acting."),
        ("Deep / Reflective",
         "Emotion develops slowly; thoughtful pauses, restrained emphasis and gentle "
         "pacing create a deeper connection."),
        ("Dramatic but Natural",
         "Important scenes become more intense without losing realism; peaks land harder "
         "because the surrounding delivery stays controlled."),
    ],
    "news": [
        ("Serious / Respectful",
         "Controlled and respectful for serious information — emotion through careful "
         "emphasis and slightly slower phrasing, never dramatic expression."),
        ("Urgent / Important",
         "Urgency through clearer emphasis and tighter pacing while the professional news "
         "style stays intact; important information becomes noticeable without panic."),
        ("Somber / Sensitive",
         "Measured and respectful for tragic or sensitive news; pauses and careful wording "
         "carry the emotional weight."),
        ("Reassuring / Stable",
         "Calm and reassuring; the listener feels informed and grounded while the "
         "professional tone softens the pressure of the information."),
    ],
    "explainer": [
        ("Friendly / Helpful",
         "Approachable and encouraging; important concepts get gentle emphasis and the "
         "rhythm stays comfortable and natural."),
        ("Curious / Engaging",
         "Curiosity runs through the explanation; small emphasis and pacing changes "
         "highlight interesting ideas without theatre."),
        ("Reassuring / Patient",
         "Calm and patient: difficult information feels manageable, key explanations "
         "breathe, nothing is rushed."),
        ("Encouraging / Motivational",
         "A subtle sense of encouragement; emphasis becomes slightly stronger at useful "
         "moments without turning the explanation into a speech."),
    ],
    "thriller": [
        ("Suspenseful",
         "Controlled build-up: important information arrives gradually, with meaningful "
         "pauses and slightly slower moments before the reveal."),
        ("Fearful / Scared",
         "Restrained fear — quieter delivery, cautious pacing, subtle hesitation and "
         "strategic silence; aware of danger rather than frightened the whole time."),
        ("Dark / Mysterious",
         "Mysterious and charged; certain words carry more weight while silence creates "
         "unanswered space."),
        ("Shock / Panic",
         "The rhythm changes suddenly — a faster, more urgent reaction, then a brief "
         "silence that lets the shock register."),
    ],
    "meditation": [
        ("Deep Calm",
         "Deeply peaceful, slow natural phrasing with generous emotional space; each "
         "thought settles before the next."),
        ("Comforting / Reassuring",
         "Soothing presence that makes the listener feel safe and supported, with soft "
         "transitions and calm pauses."),
        ("Reflective / Healing",
         "Quiet reflection for memory or emotional release; sadness or pain is "
         "acknowledged gently, never dramatically."),
        ("Peaceful / Hopeful",
         "A calm sense of hope gradually appears; the feeling opens slightly while the "
         "peaceful meditation experience stays intact."),
    ],
    "inner_monologue": [
        ("Private / Intimate",
         "Deeply personal and inward — subtle pauses and quiet hesitation, as though the "
         "thoughts are experienced rather than spoken."),
        ("Lonely / Empty",
         "Spacious and emotionally distant: slower pacing and longer silence, thoughts "
         "lingering without overacting."),
        ("Vulnerable / Confessional",
         "Fragile and honest, like an unspoken confession — important lines slow slightly, "
         "with restrained breath and hesitation."),
        ("Regretful / Reflective",
         "Shaped by memory and regret; certain phrases soften and linger, as if replaying "
         "moments in the mind."),
    ],
    "sad_romantic": [
        ("Soft Heartbreak",
         "Gentle but painful; slower speech, silence and restrained emphasis carry a heart "
         "that has been hurt — never melodrama."),
        ("Deep Sadness",
         "Heavy, intimate sadness: slower pacing, quieter energy, longer pauses and soft "
         "sentence endings; affected but still in control."),
        ("Longing / Missing Someone",
         "Tender longing — memories feel close and distant at once; certain words linger, "
         "pauses suggest wanting someone who is no longer there."),
        ("Love Through Tears",
         "Love and sadness together: gentle and intimate, with small breaks, subtle breath "
         "and hesitation for feelings that are hard to express."),
    ],
    "cinematic": [
        ("Deep Emotional",
         "Deeply felt performance where emotion grows through the scene — softness, "
         "tension, sadness, fear, hope and release, driven by the story."),
        ("Whisper / Intimate",
         "Highly intimate, for private thoughts, secrets, fear or confession; the whisper "
         "appears briefly and naturally, then the delivery returns to normal."),
        ("Fear / Suspense",
         "Fear through controlled pacing, quiet moments, hesitation and strategic silence; "
         "intensity rises before danger or revelation, not throughout."),
        ("Grief / Emotional Climax",
         "For major loss or climax — slower, softer, more fragile and more silent, then a "
         "gradual release instead of staying overwhelmed."),
    ],
}

#: the delivery variables of the specification (the only things a delivery moves)
VARIABLES = {
    "pacing": ["slightly slower", "slower", "very slow", "moderate",
               "slightly faster", "urgent"],
    "pause": ["micro pause", "short pause", "reflective pause", "emotional pause",
              "suspense pause", "full pause"],
    "energy": ["restrained", "gentle", "moderate", "heightened", "intense"],
    "emphasis": ["subtle", "selective", "emotional", "strong", "restrained"],
    "breath": ["minimal", "subtle", "natural", "slightly emotional",
               "brief breath before difficult lines"],
    "pitch_movement": ["restrained", "gentle fall", "gentle rise", "emotional rise",
                       "rise and fall", "uncertain movement"],
    "rhythm": ["smooth", "flowing", "reflective", "hesitant", "tense", "urgent",
               "spacious"],
    "sentence_ending": ["natural fall", "soft fall", "reflective release",
                        "suspended ending", "firm ending", "emotionally weakened ending"],
}

#: intensity scale of the specification
INTENSITY = {0: "neutral", 1: "subtle", 2: "noticeable", 3: "strong",
             4: "very strong", 5: "extreme"}
DEFAULT_INTENSITY = (1, 3)          # only 4–5 when clearly justified

#: what each delivery does to the PERFORMANCE (delivery-only moves).
#:   pause      multiplier on the planned pause
#:   emphasis   strength of the emphasis pause before the stressed phrase (0–1)
#:   breath     how audible the breath is in this delivery (0–1)
#:   rhythm     the named rhythm (spec vocabulary)
#:   ending     the named sentence ending (spec vocabulary)
#:   intensity  bias inside the style's own band (-1 … +1)
MOVES = {
    # ---------------------------------------------------------------- natural
    "Natural / Comfortable": dict(pause=0.95, emphasis=0.35, breath=0.20,
                                  rhythm="flowing", ending="natural fall",
                                  intensity=0.0),
    "Warm / Personal": dict(pause=1.05, emphasis=0.45, breath=0.30,
                            rhythm="smooth", ending="natural fall", intensity=+0.10),
    "Reflective / Thoughtful": dict(pause=1.20, emphasis=0.35, breath=0.25,
                                    rhythm="reflective", ending="reflective release",
                                    intensity=-0.10),
    "Subtle Emotion": dict(pause=1.08, emphasis=0.40, breath=0.35,
                           rhythm="hesitant", ending="soft fall", intensity=+0.05),
    # ----------------------------------------------------------- storytelling
    "Inviting Storyteller": dict(pause=1.05, emphasis=0.55, breath=0.30,
                                 rhythm="flowing", ending="natural fall",
                                 intensity=+0.05),
    "Suspenseful Storyteller": dict(pause=1.30, emphasis=0.60, breath=0.25,
                                    rhythm="tense", ending="suspended ending",
                                    intensity=+0.15),
    "Wonder / Imagination": dict(pause=1.25, emphasis=0.60, breath=0.30,
                                 rhythm="spacious", ending="gentle rise",
                                 intensity=+0.10),
    "Personal / Heartfelt": dict(pause=1.20, emphasis=0.55, breath=0.45,
                                 rhythm="reflective", ending="soft fall",
                                 intensity=+0.10),
    # ------------------------------------------------------------------ novel
    "Immersive Emotion": dict(pause=1.10, emphasis=0.45, breath=0.25,
                              rhythm="flowing", ending="natural fall",
                              intensity=+0.05),
    "Character-Aware": dict(pause=1.05, emphasis=0.45, breath=0.30,
                            rhythm="smooth", ending="soft fall", intensity=+0.05),
    "Reflective / Literary": dict(pause=1.20, emphasis=0.40, breath=0.25,
                                  rhythm="reflective", ending="reflective release",
                                  intensity=-0.05),
    "Intimate / Vulnerable": dict(pause=1.28, emphasis=0.40, breath=0.50,
                                  rhythm="hesitant", ending="soft fall",
                                  intensity=-0.10),
    # ------------------------------------------------------------ documentary
    "Serious / Reflective": dict(pause=1.20, emphasis=0.35, breath=0.15,
                                 rhythm="reflective", ending="firm ending",
                                 intensity=-0.05),
    "Historical / Solemn": dict(pause=1.45, emphasis=0.30, breath=0.15,
                                rhythm="spacious", ending="reflective release",
                                intensity=-0.20),
    "Hopeful / Uplifting": dict(pause=1.05, emphasis=0.45, breath=0.25,
                                rhythm="smooth", ending="gentle rise",
                                intensity=+0.15),
    "Human / Compassionate": dict(pause=1.22, emphasis=0.40, breath=0.35,
                                  rhythm="reflective", ending="soft fall",
                                  intensity=-0.05),
    # ---------------------------------------------------------------- trailer
    "Powerful / Anticipatory": dict(pause=1.25, emphasis=0.85, breath=0.15,
                                    rhythm="tense", ending="firm ending",
                                    intensity=+0.20),
    "Dark / Threatening": dict(pause=1.50, emphasis=0.60, breath=0.20,
                               rhythm="tense", ending="suspended ending",
                               intensity=+0.10),
    "Emotional / Epic": dict(pause=1.35, emphasis=0.90, breath=0.25,
                             rhythm="spacious", ending="emotionally weakened ending",
                             intensity=+0.25),
    "Shock / Revelation": dict(pause=1.60, emphasis=0.80, breath=0.30,
                               rhythm="hesitant", ending="suspended ending",
                               intensity=+0.20),
    # -------------------------------------------------------------- audiobook
    "Immersive / Emotional": dict(pause=1.08, emphasis=0.45, breath=0.25,
                                  rhythm="flowing", ending="natural fall",
                                  intensity=+0.05),
    "Character / Feeling Driven": dict(pause=1.05, emphasis=0.45, breath=0.30,
                                       rhythm="smooth", ending="soft fall",
                                       intensity=+0.10),
    "Deep / Reflective": dict(pause=1.25, emphasis=0.40, breath=0.30,
                              rhythm="reflective", ending="reflective release",
                              intensity=-0.05),
    "Dramatic but Natural": dict(pause=1.15, emphasis=0.65, breath=0.25,
                                 rhythm="flowing", ending="firm ending",
                                 intensity=+0.15),
    # ------------------------------------------------------------------- news
    "Serious / Respectful": dict(pause=1.15, emphasis=0.35, breath=0.00,
                                 rhythm="smooth", ending="firm ending",
                                 intensity=-0.05),
    "Urgent / Important": dict(pause=0.80, emphasis=0.50, breath=0.00,
                               rhythm="urgent", ending="firm ending", intensity=+0.20),
    "Somber / Sensitive": dict(pause=1.35, emphasis=0.30, breath=0.15,
                               rhythm="reflective", ending="reflective release",
                               intensity=-0.15),
    "Reassuring / Stable": dict(pause=1.10, emphasis=0.35, breath=0.10,
                                rhythm="smooth", ending="natural fall",
                                intensity=0.00),
    # -------------------------------------------------------------- explainer
    "Friendly / Helpful": dict(pause=1.00, emphasis=0.40, breath=0.20,
                               rhythm="smooth", ending="natural fall", intensity=+0.05),
    "Curious / Engaging": dict(pause=0.95, emphasis=0.45, breath=0.25,
                               rhythm="flowing", ending="gentle rise", intensity=+0.10),
    "Reassuring / Patient": dict(pause=1.25, emphasis=0.35, breath=0.25,
                                 rhythm="spacious", ending="soft fall", intensity=-0.05),
    "Encouraging / Motivational": dict(pause=1.05, emphasis=0.55, breath=0.20,
                                       rhythm="flowing", ending="firm ending",
                                       intensity=+0.20),
    # --------------------------------------------------------------- thriller
    "Suspenseful": dict(pause=1.45, emphasis=0.60, breath=0.25,
                        rhythm="tense", ending="suspended ending", intensity=+0.10),
    "Fearful / Scared": dict(pause=1.50, emphasis=0.45, breath=0.55,
                             rhythm="hesitant", ending="suspended ending",
                             intensity=+0.05),
    "Dark / Mysterious": dict(pause=1.55, emphasis=0.55, breath=0.30,
                              rhythm="spacious", ending="suspended ending",
                              intensity=+0.05),
    "Shock / Panic": dict(pause=0.85, emphasis=0.70, breath=0.60,
                          rhythm="urgent", ending="firm ending", intensity=+0.25),
    # ------------------------------------------------------------- meditation
    "Deep Calm": dict(pause=1.35, emphasis=0.25, breath=0.20,
                      rhythm="spacious", ending="reflective release", intensity=-0.10),
    "Comforting / Reassuring": dict(pause=1.30, emphasis=0.30, breath=0.30,
                                    rhythm="smooth", ending="soft fall", intensity=-0.05),
    "Reflective / Healing": dict(pause=1.40, emphasis=0.25, breath=0.35,
                                 rhythm="reflective", ending="reflective release",
                                 intensity=-0.05),
    "Peaceful / Hopeful": dict(pause=1.25, emphasis=0.30, breath=0.25,
                               rhythm="spacious", ending="gentle rise", intensity=+0.05),
    # -------------------------------------------------------- inner_monologue
    "Private / Intimate": dict(pause=1.30, emphasis=0.35, breath=0.45,
                               rhythm="hesitant", ending="soft fall", intensity=-0.05),
    "Lonely / Empty": dict(pause=1.60, emphasis=0.25, breath=0.40,
                           rhythm="spacious", ending="emotionally weakened ending",
                           intensity=-0.15),
    "Vulnerable / Confessional": dict(pause=1.45, emphasis=0.35, breath=0.60,
                                      rhythm="hesitant", ending="soft fall",
                                      intensity=+0.05),
    "Regretful / Reflective": dict(pause=1.40, emphasis=0.35, breath=0.40,
                                   rhythm="reflective", ending="reflective release",
                                   intensity=0.00),
    # ----------------------------------------------------------- sad_romantic
    "Soft Heartbreak": dict(pause=1.45, emphasis=0.35, breath=0.50,
                            rhythm="hesitant", ending="soft fall", intensity=-0.05),
    "Deep Sadness": dict(pause=1.60, emphasis=0.30, breath=0.45,
                         rhythm="reflective", ending="emotionally weakened ending",
                         intensity=-0.15),
    "Longing / Missing Someone": dict(pause=1.70, emphasis=0.40, breath=0.50,
                                      rhythm="spacious", ending="soft fall",
                                      intensity=-0.05),
    "Love Through Tears": dict(pause=1.55, emphasis=0.40, breath=0.65,
                               rhythm="hesitant", ending="emotionally weakened ending",
                               intensity=+0.05),
    # -------------------------------------------------------------- cinematic
    "Deep Emotional": dict(pause=1.25, emphasis=0.55, breath=0.35,
                           rhythm="flowing", ending="natural fall", intensity=+0.10),
    # The slot keeps its name — it is a real delivery (close, soft, hesitant,
    # lots of air) — but it no longer whispers: build 2026-09-30n removed the
    # whisper stage, and `whisper_depth()` returns 0.0 for every delivery.
    "Whisper / Intimate": dict(pause=1.45, emphasis=0.45, breath=0.70,
                               rhythm="hesitant", ending="soft fall", intensity=0.00),
    "Fear / Suspense": dict(pause=1.50, emphasis=0.60, breath=0.50,
                            rhythm="tense", ending="suspended ending", intensity=+0.15),
    "Grief / Emotional Climax": dict(pause=1.75, emphasis=0.45, breath=0.60,
                                     rhythm="spacious",
                                     ending="emotionally weakened ending",
                                     intensity=+0.10),
    "Gentle / Comforting": dict(pause=1.30, emphasis=0.25, breath=0.35,
                                rhythm="smooth", ending="soft fall", intensity=-0.10),
    "Warm / Caring": dict(pause=1.25, emphasis=0.30, breath=0.40,
                          rhythm="smooth", ending="soft fall", intensity=-0.05),
    "Dreamy / Imaginative": dict(pause=1.40, emphasis=0.25, breath=0.35,
                                 rhythm="spacious", ending="reflective release",
                                 intensity=-0.05),
    "Sleepy / Peaceful": dict(pause=1.55, emphasis=0.20, breath=0.45,
                              rhythm="spacious", ending="soft fall", intensity=-0.15),
}

#: every delivery belongs to exactly one style — the style-protection table
DELIVERY_STYLE = {name: sid for sid, items in DELIVERIES.items() for name, _d in items}
STYLE_DELIVERIES = {sid: [n for n, _d in items] for sid, items in DELIVERIES.items()}
DELIVERY_DESC = {name: d for items in DELIVERIES.values() for name, d in items}

#: how far a delivery may move the pauses inside a style (the envelope).
#: Clamped by style_guard(): a delivery can lean, it cannot become another style.
ENVELOPE = {sid: dict(pause=(0.75, 1.85), emphasis=(0.0, 0.95)) for sid in DELIVERIES}
ENVELOPE["news"].update(pause=(0.75, 1.40))          # news never drags
ENVELOPE["trailer"].update(pause=(1.10, 1.75))       # trailer never hurries
ENVELOPE["meditation"].update(pause=(1.20, 1.70))

#: styles whose identity is a sustained whisper (spec: whisper is a moment
#: the sustained-whisper style, so nothing whispers a whole narration any more)
SUSTAINED_WHISPER = set()  # no style whispers a whole piece any more (build l)
MOMENT_WHISPER_DELIVERY = "Whisper / Intimate"


def whisper_depth(style, delivery_name=None):
    """Always 0.0 — the whisper stage is REMOVED (build 2026-09-30n).

    A whispered line is generated as a different *sound* (a breath carrying the
    words), so wherever it lands mid-read it stops being the voice that was
    speaking. The user's report was exactly that: in every voice, Khmer and
    English, the reading would sometimes drop into a whisper that arrived
    louder than the sentence it replaced.

    An intimate passage is still performed close, soft and slow — by the same
    voice, with no whisper anywhere in it.
    """
    return 0.0


def _style_id(style):
    try:
        import narration as NAR
        return NAR.style_id(style)
    except Exception:
        return str(style or "").strip().lower().replace("-", "_") or "natural"


# --------------------------------------------------------------------------- #
# 2. automatic emotion selection (spec: analyse the text)                     #
# --------------------------------------------------------------------------- #
#: the spec's categories, with the cue words that reveal them (Khmer first)
AUTO_EMOTION_CUES = {
    "sadness": ["យំ", "ទុក្ខ", "ឈឺចាប់", "ការបាត់បង់", "អស់សង្ឃឹម", "ខ្លោចផ្សា",
                "sad", "sadness", "tears", "cried", "crying", "sorrow"],
    "grief": ["ស្លាប់", "បាត់បង់", "ពិធីបុណ្យសព", "ផ្នូរ", "សោក",
              "grief", "grieving", "died", "death", "funeral", "buried", "grave",
              "never came back"],
    "fear": ["ខ្លាច", "ភ័យ", "រន្ធត់", "គ្រោះថ្នាក់", "រត់",
             "afraid", "fear", "fearful", "terrified", "scared", "danger"],
    "tension": ["ស្ងាត់", "នៅសល់", "កាំបិត", "ឈាម", "លាក់", "សម្ងាត់",
                "tense", "tension", "knife", "blood", "hidden", "secret", "silence"],
    "suspense": ["រង់ចាំ", "មិនដឹង", "ទ្វារ", "ស្រាប់តែ", "ងងឹត",
                 "suspense", "waited", "door", "behind", "dark", "suddenly", "unknown"],
    "joy": ["សប្បាយ", "រីករាយ", "សើច", "ជោគជ័យ", "ញញឹម", "ពន្លឺ",
            "joy", "happy", "laughed", "smile", "victory", "celebrate", "light"],
    "love": ["ស្រលាញ់", "ស្រឡាញ់", "ថើប", "ឱប", "ស្នេហា", "ដៃគូ",
             "love", "loved", "kiss", "kissed", "hug", "held", "beloved"],
    "loneliness": ["ឯកា", "ម្នាក់ឯង", "ស្ងាត់ជ្រងំ", "គ្មាននរណា",
                   "alone", "lonely", "empty", "no one", "nobody"],
    "regret": ["ស្តាយ", "អស់ឱកាស", "បើបាន", "ខុស", "មិនគួរ",
               "regret", "wish", "should have", "too late", "if only"],
    "nostalgia": ["កាលពី", "អតីតកាល", "កុមារភាព", "ថ្ងៃនោះ", "ចងចាំ",
                  "remember", "memories", "once", "back then", "childhood", "long ago"],
    "curiosity": ["ហេតុអ្វី", "យ៉ាងដូចម្តេច", "សំណួរ", "រកឃើញ",
                  "why", "how", "question", "wonder", "discovered", "found out"],
    "relief": ["ស្រាលចិត្ត", "ស្អាត", "រួចផុត", "សុវត្ថិភាព",
               "relief", "relieved", "safe", "finally", "at last", "breathed"],
    "hope": ["សង្ឃឹម", "អនាគត", "ព្រឹកថ្មី", "ជឿ",
             "hope", "hopeful", "tomorrow", "believe", "future", "dawn"],
    "vulnerability": ["ទន់ខ្សោយ", "ភ័យខ្លាច", "ការសារភាព", "ទឹកភ្នែក",
                      "vulnerable", "confession", "confessed", "fragile", "barely"],
    "confidence": ["ជឿជាក់", "ឈ្នះ", "ខ្លាំង", "សម្រេច",
                   "confident", "won", "strong", "decided", "determined"],
    "anger": ["ខឹង", "ក្តៅក្រហាយ", "ស្តីបន្ទោស", "ឈ្លោះ",
              "angry", "anger", "furious", "shouted", "rage"],
    "peace": ["ស្ងប់", "សន្តិភាព", "ស្ងៀម", "ដកដង្ហើម",
              "calm", "peace", "peaceful", "quiet", "breathe", "still"],
}

#: the spec's category -> the engine's emotion name (the 52-emotion set)
CATEGORY_EMOTION = {
    "sadness": "sad", "grief": "grieving", "fear": "fearful", "tension": "tense",
    "suspense": "suspense", "joy": "joyful", "love": "romantic",
    "loneliness": "lonely", "regret": "regretful", "nostalgia": "nostalgic",
    "curiosity": "curious", "relief": "relieved", "hope": "hopeful",
    "vulnerability": "heartbroken", "confidence": "confident", "anger": "angry",
    "peace": "calm",
}

#: which of a style's four deliveries a feeling belongs to.
#: 0, 1, 2, 3 = the four deliveries of the style, in the spec's order.
FEELING_SLOT = {
    "natural": {"peace": 0, "joy": 1, "love": 1, "nostalgia": 2, "curiosity": 2,
                "relief": 2, "hope": 2, "sadness": 3, "vulnerability": 3,
                "regret": 3, "tension": 3, "fear": 3, "grief": 3},
    "storytelling": {"curiosity": 0, "hope": 0, "suspense": 1, "tension": 1,
                     "fear": 1, "joy": 2, "peace": 2, "love": 3, "nostalgia": 3,
                     "sadness": 3, "grief": 3, "loneliness": 3, "relief": 0},
    "novel": {"peace": 0, "joy": 0, "hope": 0, "love": 1, "sadness": 1, "fear": 1,
              "nostalgia": 2, "regret": 2, "grief": 3, "loneliness": 3,
              "vulnerability": 3, "tension": 1, "relief": 2, "curiosity": 0},
    "documentary": {"tension": 0, "curiosity": 0, "confidence": 0, "grief": 1,
                    "regret": 1, "nostalgia": 1, "hope": 2, "joy": 2, "sadness": 3,
                    "love": 3, "peace": 3, "fear": 0, "relief": 2},
    "trailer": {"hope": 0, "confidence": 0, "tension": 1, "fear": 1, "anger": 1,
                "love": 2, "sadness": 2, "grief": 2, "joy": 2, "suspense": 3,
                "relief": 3, "curiosity": 3, "peace": 0, "nostalgia": 2},
    "audiobook": {"peace": 0, "joy": 0, "love": 1, "hope": 1, "fear": 1, "anger": 1,
                  "nostalgia": 2, "regret": 2, "relief": 2, "sadness": 3, "grief": 3,
                  "tension": 3, "suspense": 3, "curiosity": 0, "loneliness": 2},
    "news": {"confidence": 0, "tension": 0, "fear": 1, "anger": 1, "hope": 1,
             "grief": 2, "sadness": 2, "regret": 2, "relief": 3, "peace": 3,
             "love": 3, "nostalgia": 3, "joy": 3, "curiosity": 0, "suspense": 1},
    "explainer": {"joy": 0, "hope": 0, "curiosity": 1, "confidence": 1, "tension": 2,
                  "fear": 2, "suspense": 2, "regret": 2, "peace": 2, "love": 3,
                  "relief": 3, "anger": 3, "sadness": 3, "grief": 3, "nostalgia": 2},
    "thriller": {"tension": 0, "suspense": 0, "curiosity": 0, "fear": 1,
                 "vulnerability": 1, "loneliness": 2, "regret": 2, "nostalgia": 2,
                 "grief": 2, "joy": 3, "sadness": 3, "anger": 3, "peace": 2,
                 "love": 1, "hope": 1, "confidence": 1},
    "meditation": {"peace": 0, "relief": 0, "love": 1, "hope": 1, "sadness": 2,
                   "grief": 2, "regret": 2, "nostalgia": 2, "joy": 3, "curiosity": 3,
                   "tension": 3, "fear": 3, "loneliness": 2, "vulnerability": 2},
    "inner_monologue": {"love": 0, "vulnerability": 0, "curiosity": 0,
                        "loneliness": 1, "peace": 1, "nostalgia": 3, "regret": 3,
                        "sadness": 3, "grief": 3, "fear": 1, "tension": 1,
                        "joy": 1, "hope": 1, "relief": 1, "suspense": 1},
    "sad_romantic": {"sadness": 0, "vulnerability": 0, "regret": 0, "grief": 1,
                     "loneliness": 1, "peace": 1, "nostalgia": 2, "love": 3,
                     "hope": 2, "relief": 3, "joy": 1, "tension": 1, "fear": 1},
    "cinematic": {"suspense": 0, "tension": 0, "love": 0, "vulnerability": 1,
                  "peace": 1, "fear": 2, "anger": 2, "grief": 3, "sadness": 3,
                  "regret": 3, "joy": 0, "hope": 0, "nostalgia": 0, "relief": 0},
}

#: cues that force a specific delivery inside a style (text > feeling slot)
#: the words that EARN a whispered line (build l: the whisper is never handed
#: out by position any more — if the text says nothing intimate, the line is
#: performed normally, so nothing arrives whispered by accident)
WHISPER_CUE = re.compile(
    r"(សម្ងាត់|ខ្សឹប|ខ្សឹបខ្សៀវ|ស្និទ្ធស្នាល|secret|whisper|whispered|leaned close|"
    r"close to (her|his|my) ear)", re.I)

SPECIAL_CUES = [
    (re.compile(r"(ភ្លាមៗ|ស្រាប់តែ|suddenly|screamed|all at once|in an instant)", re.I),
     "shock"),
    (WHISPER_CUE, "whisper"),
    (re.compile(r"(ចងចាំ|នឹក|remember|memory|memories|long ago|used to)", re.I),
     "memory"),
    (re.compile(r"(ទឹកភ្នែក|យំ|tears|crying|cried)", re.I), "grief"),
]

#: slot for those cues, per style
SPECIAL_SLOT = {
    "shock": {"trailer": 3, "thriller": 3, "storytelling": 1, "audiobook": 3,
              "cinematic": 2, "novel": 1, "natural": 3, "documentary": 0,
              "news": 2, "explainer": 2, "meditation": 3, "inner_monologue": 1,
              "sad_romantic": 1},
    "whisper": {"cinematic": 1, "inner_monologue": 0, "novel": 3, "sad_romantic": 3,
                "storytelling": 3, "thriller": 1, "audiobook": 1,
                "meditation": 1, "natural": 3, "documentary": 3, "news": 3,
                "explainer": 3, "trailer": 1},
    "memory": {"novel": 2, "storytelling": 3, "audiobook": 2, "sad_romantic": 2,
               "inner_monologue": 3, "natural": 2, "documentary": 1, "cinematic": 0,
               "meditation": 2, "news": 3, "explainer": 3, "trailer": 2,
               "thriller": 2},
    "grief": {"sad_romantic": 1, "cinematic": 3, "novel": 3, "documentary": 1,
              "audiobook": 3, "storytelling": 3, "thriller": 2, "natural": 3,
              "news": 2, "explainer": 3, "meditation": 2, "inner_monologue": 3,
              "trailer": 2},
}

#: the arc: an opening line, a build, a turn, a climax and a release
PHASE_SLOT = {"opening": 0, "build": 1, "turn": 2, "climax": 3, "release": 1}


def detect_feelings(text):
    """The spec's automatic emotion selection — which feelings the text carries."""
    found = []
    low = (text or "")
    for cat, words in AUTO_EMOTION_CUES.items():
        for w in words:
            if w.lower() in low.lower():
                found.append(cat)
                break
    return found


def auto_emotion(text, style="natural"):
    """The feeling to perform when the user did not name one."""
    cats = detect_feelings(text)
    if not cats:
        return "neutral"
    slot_map = FEELING_SLOT.get(_style_id(style), {})
    # the first feeling the text carries that this style knows how to perform
    best = min(cats, key=lambda c: (abs(slot_map.get(c, 1) - 1), cats.index(c)))
    return CATEGORY_EMOTION.get(best, "neutral")


def choose_delivery(style, sentence, position=0.0, phase=None, emotion=None,
                    intensity5=None, prev=None):
    """Which of this style's four emotional deliveries this sentence gets.

    Pure function of the text, the style and the position in the piece — the
    same script always performs the same way. Returns (name, moves).
    """
    sid = _style_id(style)
    names = STYLE_DELIVERIES.get(sid) or STYLE_DELIVERIES["natural"]

    slot = None
    for rx, cue in SPECIAL_CUES:
        if rx.search(sentence or ""):
            slot = SPECIAL_SLOT.get(cue, {}).get(sid)
            if slot is not None:
                break
    if slot is None and phase:
        slot = PHASE_SLOT.get(str(phase).strip().lower())
    if slot is None:
        cats = detect_feelings(sentence)
        slot_map = FEELING_SLOT.get(sid, {})
        if cats:
            slot = slot_map.get(cats[0])
    if slot is None:
        slot = FEELING_SLOT.get(sid, {}).get(
            _emotion_category(emotion), int(round(position * 3)))
    if slot is None:
        slot = int(round(max(0.0, min(1.0, position)) * 3))
    slot = int(max(0, min(len(names) - 1, slot)))

    # CONTRAST: never the same delivery three lines in a row — the spec's
    # "do not keep one emotional setting for the entire chapter"
    if prev and names[slot] == prev and slot + 1 < len(names):
        slot += 1

    # A WHISPERED LINE NEEDS THE WORDS TO EARN IT (build l). The cinematic
    # "Whisper / Intimate" slot used to be reachable by POSITION alone, so a
    # plain line could arrive whispered — the user heard that as the voice
    # being wrong. Now the line must carry an intimacy cue; otherwise it takes
    # the style's opening delivery, which never whispers.
    if MOVES.get(names[slot], {}).get("whisper") and not WHISPER_CUE.search(sentence or ""):
        for cand in (names[0],) + tuple(names):
            if not MOVES.get(cand, {}).get("whisper"):
                slot = names.index(cand)
                break
    name = names[slot]
    return name, dict(MOVES.get(name) or {})


def _emotion_category(emotion):
    """Engine emotion name -> the spec's feeling category (best match)."""
    e = str(emotion or "").strip().lower()
    if not e:
        return None
    for cat, name in CATEGORY_EMOTION.items():
        if name == e:
            return cat
    alias = {"sad": "sadness", "grieving": "grief", "fearful": "fear",
             "terrified": "fear", "tense": "tension", "suspense": "suspense",
             "joyful": "joy", "romantic": "love", "tender": "love",
             "affectionate": "love", "lonely": "loneliness", "regretful": "regret",
             "nostalgic": "nostalgia", "wistful": "nostalgia", "curious": "curiosity",
             "relieved": "relief", "hopeful": "hope", "heartbroken": "vulnerability",
             "confident": "confidence", "determined": "confidence", "angry": "anger",
             "frustrated": "anger", "defiant": "anger", "calm": "peace",
             "neutral": "peace", "warm": "love", "compassionate": "love",
             "melancholic": "sadness", "bittersweet": "sadness", "longing": "love",
             "thoughtful": "peace", "reverent": "peace", "solemn": "grief",
             "mysterious": "suspense", "anxious": "fear", "worried": "fear",
             "dread": "fear", "desperate": "vulnerability", "exhausted": "sadness",
             "surprised": "shock", "awed": "hope", "revelation": "shock",
             "epic": "confidence", "proud": "confidence", "inspired": "hope",
             "triumphant": "confidence", "amused": "joy", "playful": "joy",
             "informative": "curiosity", "formal": "confidence",
             "conclusive": "confidence", "urgent": "tension"}
    return alias.get(e)


# --------------------------------------------------------------------------- #
# 3. style protection (the master rule)                                       #
# --------------------------------------------------------------------------- #
def style_guard(style, delivery_name, moves=None):
    """Clamp one delivery to its own style. Returns (moves, notes).

    This is the MASTER RULE in code: a feeling may lean a style, never replace
    it. Anything outside the style's envelope is pulled back to the edge and
    reported, so a log always says what was clamped.
    """
    sid = _style_id(style)
    notes = []
    if delivery_name not in DELIVERY_STYLE:
        return dict(moves or {}), [f"unknown delivery {delivery_name!r} — ignored"]
    owner = DELIVERY_STYLE[delivery_name]
    if owner != sid:
        return dict(MOVES[delivery_name]), [
            f"{delivery_name!r} belongs to {owner}; refused for {sid} "
            f"(a feeling never turns one style into another)"]
    mv = dict(moves if moves is not None else MOVES[delivery_name])
    env = ENVELOPE.get(sid) or {}
    for key, key_name in (("pause", "pause"), ("emphasis", "emphasis")):
        lo, hi = env.get(key_name, (None, None))
        if lo is None or key not in mv:
            continue
        v = float(mv[key])
        if v < lo or v > hi:
            mv[key] = round(max(lo, min(hi, v)), 3)
            notes.append(f"{sid}/{delivery_name}: {key} {v} -> {mv[key]} "
                         f"(envelope {lo}–{hi})")
    return mv, notes


def protect(style, unit):
    """True when this performed unit still belongs to its own style."""
    sid = _style_id(style)
    name = (unit or {}).get("delivery")
    if not name:
        return True
    return DELIVERY_STYLE.get(name) == sid


# --------------------------------------------------------------------------- #
# 4. applying a delivery (delivery-only — never the voice)                    #
# --------------------------------------------------------------------------- #
def apply_to_plan_item(item, moves, name=None, style=None, breath=False):
    """narration.py plan item: pauses, emphasis, breath. Nothing else.

    `breath` is decided by the caller, not by the delivery: the specification
    allows a breath ("subtle", "brief breath before difficult lines") but the
    engine's own restraint rule wins — breath is never on every sentence and
    never before the first word of a piece.
    """
    if not item or not moves:
        return item
    q, _notes = style_guard(_style_id(style or item.get("style") or "natural"),
                            name, moves) if name else (dict(moves), [])
    pm = float(q.get("pause", 1.0) or 1.0)
    item["pause_s"] = round(max(0.0, float(item.get("pause_s") or 0.0) * pm), 3)
    em = float(q.get("emphasis", 0.0) or 0.0)
    if item.get("stress"):
        item["pre_pause_ms"] = int(max(item.get("pre_pause_ms") or 0,
                                       round(70 * em * 2)))
    elif em >= 0.6 and item.get("words", 0) >= 5:
        item["pre_pause_ms"] = int(max(item.get("pre_pause_ms") or 0,
                                       round(40 * em)))
    # REMOVED (build 2026-09-30o): a delivery no longer marks a line for a
    # synthesised breath. The intimate, suspense and grief moves still shape
    # pace, pauses and emphasis — the airy noise between sentences is gone.
    if breath and False:
        item["breath"] = True
    # Whisper REMOVED (build 2026-09-30n): this used to mark the line for the
    # whisper stage whenever the chosen delivery carried a whisper depth — the
    # last route by which a normal read could arrive whispered. Nothing marks a
    # line for whispering any more; `q` no longer carries the key at all, and
    # the guard is kept only so an old saved plan cannot re-introduce it.
    if q.get("whisper") and False:                       # never again
        item["whisper"] = True
    if name:
        item["delivery"] = name
        item["delivery_vars"] = delivery_vars(q)
    return item


def apply_to_unit(unit, moves, name=None, style=None):
    """khmer_expressive unit: pauses, breath, rhythm, emphasis. Not the voice."""
    if not unit or not moves:
        return unit
    sid = _style_id(style or unit.get("style") or "natural")
    q, notes = style_guard(sid, name or "", moves) if name else (dict(moves), [])
    pm = float(q.get("pause", 1.0) or 1.0)
    pauses = unit.get("pauses") or {}
    for k in ("before", "after", "clause"):
        if k in pauses:
            pauses[k] = round(max(0.0, float(pauses[k]) * pm), 3)
    unit["pauses"] = pauses
    qual = unit.get("quality") or {}
    if "breath" in qual:
        qual["breath"] = round(min(0.6, float(qual["breath"])
                                   + 0.25 * float(q.get("breath", 0.0) or 0.0)), 2)
    unit["quality"] = qual
    unit["rhythm"] = q.get("rhythm", unit.get("rhythm"))
    wd = whisper_depth(sid)
    if wd <= 0.0 and q.get("whisper"):
        wd = float(q["whisper"])                      # a brief whisper moment
    if wd > 0:
        unit["whisper"] = True
        unit["whisper_depth"] = wd
    if name:
        unit["delivery"] = name
        unit["delivery_vars"] = delivery_vars(q)
        unit["ending_name"] = q.get("ending")
        unit["style_notes"] = list(unit.get("style_notes") or []) + notes
    return unit


def delivery_vars(moves):
    """The specification's variable names this delivery moves."""
    used = []
    if moves.get("pause") or moves.get("pacing"):
        used.append("pause")
        used.append("pacing")
    if moves.get("emphasis"):
        used.append("emphasis")
    if moves.get("breath"):
        used.append("breath")
    if moves.get("rhythm"):
        used.append("rhythm")
    if moves.get("ending"):
        used.append("sentence_ending")
    if moves.get("intensity"):
        used.append("intensity")
    return used


def style_notes(units, style):
    """Post-pass check: the delivery pass moved no style, no voice, no band."""
    sid = _style_id(style)
    notes = []
    for u in units or []:
        if not protect(sid, u):
            notes.append("style protection: a unit carries another style's "
                         "delivery (%s)" % u.get("delivery"))
    return notes


# --------------------------------------------------------------------------- #
# 5. CLI / self-check                                                         #
# --------------------------------------------------------------------------- #
def _check():
    ok, bad = [], []
    def chk(name, cond, extra=""):
        (ok if cond else bad).append(name)
        print("  [%s] %s%s" % ("OK  " if cond else "FAIL", name,
                               "  — " + str(extra) if extra else ""))
    print("1. the 14 styles and their deliveries")
    chk("14 styles with an identity and four deliveries",
        len(DELIVERIES) == 14 and all(len(v) == 4 for v in DELIVERIES.values()),
        f"{len(DELIVERIES)} styles")
    chk("every delivery has moves and a description",
        all(n in MOVES and n in DELIVERY_DESC for n in DELIVERY_STYLE))
    chk("every delivery belongs to exactly one style",
        len(DELIVERY_STYLE) == 56, len(DELIVERY_STYLE))
    print("\n2. style protection")
    for sid in DELIVERIES:
        names = STYLE_DELIVERIES[sid]
        other = [n for n in DELIVERY_STYLE if n not in names][0]
        _mv, notes = style_guard(sid, other)
        chk(f"{sid} refuses {other}", bool(notes))
    print("\n3. the variables, the intensity scale, the whisper rule")
    chk("all eight delivery variables are named", len(VARIABLES) == 8,
        ", ".join(VARIABLES))
    chk("intensity 0–5 as specified", sorted(INTENSITY) == [0, 1, 2, 3, 4, 5]
        and DEFAULT_INTENSITY == (1, 3))
    chk("nothing whispers a whole piece any more (the sustained style is gone)",
        SUSTAINED_WHISPER == set() and whisper_depth("bedtime") == 0.0)
    chk("a whisper moment elsewhere is partial",
        0.0 < whisper_depth("cinematic", MOMENT_WHISPER_DELIVERY) < 1.0
        and whisper_depth("audiobook") == 0.0)
    print("\n4. automatic emotion selection")
    cases = [("គាត់បានស្លាប់នៅពេលព្រឹក", "grieving"),
             ("She was afraid of the dark house", "fearful"),
             ("ខ្ញុំស្រលាញ់អ្នកណាស់", "romantic"),
             ("He laughed and the light came back", "joyful")]
    for text, want in cases:
        got = auto_emotion(text, "audiobook")
        chk(f"“{text[:26]}…” -> {want}", got == want, got)
    print("\n5. contrast (never one setting for the whole chapter)")
    seq = [choose_delivery("audiobook", "…", position=i / 9.0,
                           phase=("opening", "build", "turn", "climax", "release")[i % 5])[0]
           for i in range(10)]
    chk("a long piece uses at least three deliveries", len(set(seq)) >= 3,
        seq)
    print("\nfeeling layer: %d passed, %d failed" % (len(ok), len(bad)))
    return 1 if bad else 0


def _list():
    for sid, items in DELIVERIES.items():
        print("\n%-16s %s" % (sid, STYLE_CORE.get(sid, "")))
        for i, (name, desc) in enumerate(items, 1):
            mv = MOVES[name]
            extra = " whisper %.2f" % mv["whisper"] if mv.get("whisper") else ""
            wd = whisper_depth(sid) if sid in SUSTAINED_WHISPER else 0.0
            if wd:
                extra += " (sustained whisper)"
            print("   %d. %-28s pause×%.2f  emphasis %.2f  breath %.2f  %s%s"
                  % (i, name, mv["pause"], mv["emphasis"], mv["breath"],
                     mv["rhythm"], extra))
    return 0


def main():
    import argparse
    ap = argparse.ArgumentParser(description="the FEELING layer (14 styles)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--style", default="")
    ap.add_argument("--text", default="")
    a = ap.parse_args()
    if a.check or (not a.style and not a.text and not a.list):
        return _check()
    if a.list:
        return _list()
    style = a.style or "audiobook"
    text = a.text or ("She opened the door, but he wasn't there. "
                      "The house was silent. Then, suddenly, the truth arrived.")
    sents = [s.strip() for s in re.split(r"(?<=[.!?។])\s+", text) if s.strip()]
    print("style : %s — %s" % (style, STYLE_CORE.get(_style_id(style), "")))
    print("voice : unchanged (pitch 0.0, loudness 0.0, pace = user's own)\n")
    prev = None
    for i, s in enumerate(sents):
        name, mv = choose_delivery(style, s, position=i / max(1, len(sents) - 1),
                                   prev=prev)
        prev = name
        print("  %2d. %-28s pause×%.2f emphasis %.2f breath %.2f %s"
              % (i + 1, name, mv.get("pause", 1.0), mv.get("emphasis", 0.0),
                 mv.get("breath", 0.0), mv.get("rhythm", "")))
        print("      %s" % s[:88])
        if mv.get("whisper"):
            print("      (whisper moment, depth %.2f)" % mv["whisper"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
