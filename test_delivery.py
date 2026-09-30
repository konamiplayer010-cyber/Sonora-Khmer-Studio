#!/usr/bin/env python3
"""test_delivery.py — checks for the FEELING layer (delivery.py).

The specification this guards (the user's 14-style emotional delivery engine):

    STYLE     = FIXED      the selected style is the permanent framework
    EMOTION   = VARIABLE   what the narrator feels
    DELIVERY  = VARIABLE   pacing, pauses, energy, emphasis, breath, pitch
                           movement, rhythm, sentence ending
    INTENSITY = VARIABLE   0 neutral … 5 extreme, default 1–3
    VOICE     = FIXED      the same speaker, untouched

What this suite proves:
  1. 13 styles × 4 emotional deliveries = 52, with the exact names of the spec;
  2. both apps ship the SAME file (studio + batch pipeline);
  3. STYLE PROTECTION: a feeling can never turn one style into another —
     every foreign delivery is refused, and nothing else gets through;
  4. DELIVERY ONLY: the layer itself moves pauses, emphasis, breath and rhythm.
     Since build 2026-09-29j the STYLE owns its pace and softness (narration's
     STYLE_DELIVERY: meditation 0.84x/-1.2 dB, news 1.07x, …) and the feeling
     may colour that by a hair — but the SPEAKER never changes (pitch 0.0);
  5. the whisper rule: every whisper is a brief moment (build l removed the
     brief moment;
  6. automatic emotion selection reads the text (Khmer and English);
  7. contrast: a long piece never sits on one delivery;
  8. the engines really use the layer — every planned sentence of all 14
     styles carries one of ITS OWN style's four deliveries, and the batch
     performance planner (khmer_expressive) does the same.

    python pipeline/test_delivery.py
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

OK, FAIL = [], []


def check(name, cond, extra=""):
    (OK if cond else FAIL).append(name)
    print("  [%s] %s%s" % ("OK  " if cond else "FAIL", name,
                           "  — " + str(extra) if extra else ""))


import delivery as D                                              # noqa: E402
import narration as N                                              # noqa: E402

#: the exact names of the specification (sections 1–14, in order)
SPEC = {
    "natural": ["Natural / Comfortable", "Warm / Personal",
                "Reflective / Thoughtful", "Subtle Emotion"],
    "storytelling": ["Inviting Storyteller", "Suspenseful Storyteller",
                     "Wonder / Imagination", "Personal / Heartfelt"],
    "novel": ["Immersive Emotion", "Character-Aware", "Reflective / Literary",
              "Intimate / Vulnerable"],
    "documentary": ["Serious / Reflective", "Historical / Solemn",
                    "Hopeful / Uplifting", "Human / Compassionate"],
    "trailer": ["Powerful / Anticipatory", "Dark / Threatening",
                "Emotional / Epic", "Shock / Revelation"],
    "audiobook": ["Immersive / Emotional", "Character / Feeling Driven",
                  "Deep / Reflective", "Dramatic but Natural"],
    "news": ["Serious / Respectful", "Urgent / Important", "Somber / Sensitive",
             "Reassuring / Stable"],
    "explainer": ["Friendly / Helpful", "Curious / Engaging",
                  "Reassuring / Patient", "Encouraging / Motivational"],
    "thriller": ["Suspenseful", "Fearful / Scared", "Dark / Mysterious",
                 "Shock / Panic"],
    "meditation": ["Deep Calm", "Comforting / Reassuring",
                   "Reflective / Healing", "Peaceful / Hopeful"],
    "inner_monologue": ["Private / Intimate", "Lonely / Empty",
                        "Vulnerable / Confessional", "Regretful / Reflective"],
    "sad_romantic": ["Soft Heartbreak", "Deep Sadness",
                     "Longing / Missing Someone", "Love Through Tears"],
    "cinematic": ["Deep Emotional", "Whisper / Intimate", "Fear / Suspense",
                  "Grief / Emotional Climax"],
}

print("1. the 13 styles and their four emotional deliveries")
check("13 styles are described", len(D.DELIVERIES) == 13, len(D.DELIVERIES))
for sid, want in SPEC.items():
    check("the four deliveries of %s match the specification" % sid,
          D.STYLE_DELIVERIES.get(sid) == want, D.STYLE_DELIVERIES.get(sid))
check("52 deliveries in total", len(D.DELIVERY_STYLE) == 52,
      len(D.DELIVERY_STYLE))
check("every delivery has moves and a description",
      all(n in D.MOVES and n in D.DELIVERY_DESC for n in D.DELIVERY_STYLE))
check("every delivery belongs to exactly one style",
      all(sum(1 for s in D.STYLE_DELIVERIES.values() if n in s) == 1
          for n in D.DELIVERY_STYLE))

print("\n2. both apps ship the same layer")
_a = io.open(os.path.join(HERE, "delivery.py"), "rb").read()
_b = io.open(os.path.join(ROOT, "sonora", "delivery.py"), "rb").read()
check("pipeline/delivery.py == sonora/delivery.py", _a == _b,
      "%d vs %d bytes" % (len(_a), len(_b)))
_nar = io.open(os.path.join(HERE, "narration.py"), encoding="utf-8").read()
_snr = io.open(os.path.join(ROOT, "sonora", "narration.py"), encoding="utf-8").read()
check("both engines call the layer (narration.plan)",
      "_apply_delivery(plans, style)" in _nar and "_apply_delivery(plans, style)" in _snr)
check("the batch performance planner calls it too (khmer_expressive.perform)",
      "_DL.choose_delivery" in io.open(os.path.join(HERE, "khmer_expressive.py"),
                                       encoding="utf-8").read())

print("\n3. STYLE PROTECTION — a feeling never turns one style into another")
names_all = list(D.DELIVERY_STYLE)
for sid in SPEC:
    foreign = [n for n in names_all if D.DELIVERY_STYLE[n] != sid]
    refused = 0
    for n in foreign:
        _mv, notes = D.style_guard(sid, n)
        if notes:
            refused += 1
    check("%s refuses every foreign delivery" % sid, refused == len(foreign),
          "%d/%d refused" % (refused, len(foreign)))
check("the spec's examples hold (documentary+sad, thriller+sad, audiobook+fear)",
      D.DELIVERY_STYLE["Deep Sadness"] == "sad_romantic"
      and D._style_id("documentary") == "documentary"
      and D.protect("documentary", {"delivery": "Deep Sadness"}) is False
      and D.protect("documentary", {"delivery": "Serious / Reflective"}) is True)
_env = D.ENVELOPE["news"]
_mv, notes = D.style_guard("news", "Urgent / Important",
                           dict(D.MOVES["Urgent / Important"], pause=1.9))
check("a delivery is clamped to its style's envelope",
      _mv["pause"] <= _env["pause"][1] and notes, _mv["pause"])

print("\n4. DELIVERY ONLY — the voice is fixed")
fake = dict(text="She opened the door and the house was silent.",
            boundary=".", speaker=None, emotion="tension", intensity=40,
            attitude="tense", words=9, rate=1.0, pitch_st=0.0, gain_db=0.0,
            pause_s=0.4, breath=False, pre_pause_ms=0, stress="the door",
            ending=False, is_dialogue=False, whisper=False, breaking=False,
            suspended=False, fear=False)
bad = []
for sid in SPEC:
    for name in D.STYLE_DELIVERIES[sid]:
        it = dict(fake)
        D.apply_to_plan_item(it, D.MOVES[name], name=name, style=sid)
        if (it["pitch_st"], it["gain_db"], it["rate"]) != (0.0, 0.0, 1.0):
            bad.append((sid, name, it["pitch_st"], it["gain_db"], it["rate"]))
check("no delivery touches pitch, loudness or pace", not bad, bad[:2])
it = dict(fake)
D.apply_to_plan_item(it, D.MOVES["Grief / Emotional Climax"],
                     name="Grief / Emotional Climax", style="cinematic")
check("a delivery does move the pauses / emphasis / breath",
      it["pause_s"] != fake["pause_s"] and it["delivery"] == "Grief / Emotional Climax"
      and it["delivery_vars"], (it["pause_s"], it["pre_pause_ms"], it["breath"]))
unit = dict(style="audiobook", pauses=dict(before=0.3, after=0.4, clause=0.05),
            quality=dict(breath=0.1, tension=0.2, projection=0.4),
            emotion="neutral", intensity=30, pitch_st=0.0, energy_db=0.0,
            rate=1.0, rhythm="flowing", emphasis=["door"])
D.apply_to_unit(unit, D.MOVES["Deep / Reflective"], name="Deep / Reflective",
                style="audiobook")
check("a unit's pauses move, its voice does not",
      unit["pauses"]["after"] != 0.4
      and (unit["pitch_st"], unit["energy_db"], unit["rate"]) == (0.0, 0.0, 1.0)
      and unit["delivery"] == "Deep / Reflective"
      and unit["delivery_vars"], unit["delivery_vars"])

print("\n5. the whisper rule")
check("nothing whispers a whole piece any more (build l)",
      D.SUSTAINED_WHISPER == set() and D.whisper_depth("bedtime") == 0.0)
check("no delivery whispers at all any more (build 2026-09-30n)",
      D.whisper_depth("cinematic", "Whisper / Intimate") == 0.0
      and D.whisper_depth("audiobook") == 0.0
      and D.whisper_depth("news") == 0.0)
_whisperers = [(sid, n) for sid, names in D.STYLE_DELIVERIES.items() for n in names
               if D.whisper_depth(sid, n) > 0.0]
check("no style × delivery pair reports a whisper depth",
      _whisperers == [], _whisperers or "none")
check("the intimate slot survives as a delivery, with no whisper in it",
      "Whisper / Intimate" in D.MOVES
      and not D.MOVES["Whisper / Intimate"].get("whisper"))

print("\n6. automatic emotion selection (the spec: analyse the text)")
cases = [("គាត់បានស្លាប់នៅពេលព្រឹក", "grieving"),
         ("She was afraid of the dark house", "fearful"),
         ("ខ្ញុំស្រលាញ់អ្នកណាស់", "romantic"),
         ("He laughed and the light came back", "joyful"),
         ("គាត់អង្គុយម្នាក់ឯងក្នុងផ្ទះ", "lonely"),
         ("Finally, everyone was safe again", "relieved")]
for text, want in cases:
    got = D.auto_emotion(text, "audiobook")
    check("“%s…” -> %s" % (text[:24], want), got == want, got)
check("no feeling in the text -> neutral", D.auto_emotion("The table is brown.", "news")
      == "neutral")

print("\n7. contrast — never one setting for the whole chapter")
seq = [D.choose_delivery("audiobook", "The room was quiet.", position=i / 11.0,
                         phase=("opening", "build", "turn", "climax", "release")[i % 5],
                         prev=(None if i == 0 else "x"))[0] for i in range(12)]
check("a long piece uses three or more of the four deliveries",
      len(set(seq)) >= 3, seq)
check("the intensity scale is the spec's (0–5, default 1–3)",
      sorted(D.INTENSITY) == [0, 1, 2, 3, 4, 5] and D.DEFAULT_INTENSITY == (1, 3))
check("all eight delivery variables are named", len(D.VARIABLES) == 8,
      ", ".join(sorted(D.VARIABLES)))

print("\n8. the engines really use it — all 13 styles, every sentence")
TEXT = ("She opened the door, but he wasn't there. The house was silent. "
        "Then, suddenly, she understood. She remembered his voice. "
        "In the end, the truth found her.")
wrong, missing, whisper_mix = [], [], {}
for sid in N.STYLE_ORDER:
    pl = N.plan_text(TEXT, style=sid, speed=1.0, pause=0.3)
    whisper_mix[sid] = sum(1 for p in pl if p.get("whisper"))
    for p in pl:
        if not p.get("delivery"):
            missing.append(sid)
        elif p["delivery"] not in D.STYLE_DELIVERIES[sid]:
            wrong.append((sid, p["delivery"]))
check("every planned sentence carries a delivery", not missing, missing)
check("every delivery belongs to the style that produced it", not wrong, wrong[:2])
check("no style whispers the whole piece",
      max(whisper_mix.values()) < 5 and whisper_mix["cinematic"] >= 0,
      {k: v for k, v in whisper_mix.items() if v})
check("VOICE LOCK holds: the SPEAKER is identical in all 13 styles and 52 feelings",
      all(p["pitch_st"] == 0.0 for sid in N.STYLE_ORDER
          for p in N.plan_text(TEXT, style=sid, speed=1.0, pause=0.3)))
_bad = [(sid, p["gain_db"], p["rate"]) for sid in N.STYLE_ORDER
        for p in N.plan_text(TEXT, style=sid, speed=1.0, pause=0.3)
        if abs(p["gain_db"] - N.style_delivery(sid)["gain_db"]) > N.STYLE_GAIN_TOL + 0.01
        or abs(p["rate"] - N.style_delivery(sid)["pace"]) > N.STYLE_PACE_TOL + 0.01]
check("each style keeps its OWN pace and softness while the feeling moves",
      not _bad,
      f"{len(_bad)} line(s) outside their style's band"
      + (f" e.g. {_bad[0]}" if _bad else
         " | pace %.2f–%.2f, softness %.1f–%.1f dB"
         % (min(N.style_delivery(s)["pace"] for s in N.STYLE_ORDER),
            max(N.style_delivery(s)["pace"] for s in N.STYLE_ORDER),
            min(N.style_delivery(s)["gain_db"] for s in N.STYLE_ORDER),
            max(N.style_delivery(s)["gain_db"] for s in N.STYLE_ORDER))))
check("the user's own speed scales every style linearly (cinematic × 1.4)",
      all(abs(N.plan_text(TEXT, style=sid, speed=1.4, pause=0.3)[0]["rate"]
              - 1.4 * N.plan_text(TEXT, style=sid, speed=1.0, pause=0.3)[0]["rate"]) < 1e-3
          for sid in N.STYLE_ORDER))

try:
    import khmer_expressive as X
    plan = X.perform("គាត់បានដឹងការពិត។ បន្ទាប់មក គាត់បានយំដោយស្ងាត់ៗ។",
                     style="cinematic")
    check("the batch planner names its deliveries",
          bool(plan.get("deliveries"))
          and all(u.get("delivery") in D.STYLE_DELIVERIES["cinematic"]
                  for u in plan["units"]), plan.get("deliveries"))
    check("…and a whispered moment is marked for the audio stage, a moment deep",
          all((not u.get("whisper")) or 0.0 < u.get("whisper_depth", 0.0) < 1.0
              for u in plan["units"]))
    check("…and says so in the sheet",
          "feeling:" in X.sheet(plan)
          and "Emotional Cinematic" in X.sheet(plan))
except Exception as e:                                            # pragma: no cover
    check("the batch planner is importable", False, e)

print("\nfeeling layer: %d passed, %d failed" % (len(OK), len(FAIL)))
for f in FAIL:
    print("  FAILED:", f)
sys.exit(1 if FAIL else 0)
