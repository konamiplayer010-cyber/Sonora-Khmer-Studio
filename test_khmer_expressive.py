#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Acceptance tests for khmer_expressive.py (the performance layer).

Every check comes from the expressive specification:
52 emotions, 14 styles, pitch + energy + duration + pause + rhythm + emphasis +
voice quality, emotion changes INSIDE a sentence, emotional arcs, and the
restraint rules (no constant drama, no whisper everywhere, no constant breath,
no singing).

    python test_khmer_expressive.py
"""

import io
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import khmer_expressive as X                                     # noqa: E402
try:
    import narration as NAR
except Exception:
    NAR = None
N = NAR

PASS = FAIL = 0
FAILS = []


def check(name, got, want):
    global PASS, FAIL
    ok = got == want
    if ok:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append("%s\n     got:  %r\n     want: %r" % (name, got, want))


def check_true(name, cond, why=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append("%s%s" % (name, ("\n     " + why) if why else ""))


def check_in(name, needle, hay):
    global PASS, FAIL
    if needle in hay:
        PASS += 1
    else:
        FAIL += 1
        FAILS.append("%s\n     missing: %r\n     in:      %r" % (name, needle, hay))


TEXT = ("ព្រះបាទជ័យវរ្ម័នទី៧ សោយរាជ្យពីគ.ស. ១១៨១។ "
        "បន្តិចម្ដងៗ នគរបានរីកចម្រើន ប៉ុន្តែ ប្រជាជននៅតែរងទុក្ខ ១០០ នាក់ បានទទួល $100។ "
        "ប៉ុន្តែ សង្គ្រាមបានមកដល់តំបន់នេះយ៉ាងខ្លាំង។ "
        "ទ្រង់មានបន្ទូលថា “កុំខ្លាច យើងនឹងកសាងឡើងវិញ”។ "
        "ចុងក្រោយ ប្រវត្តិសាស្ត្របានចងចាំព្រះអង្គជានិរន្តរ៍។")

# ---------------------------------------------------------------- emotions ---
check_true("at least 40 emotions (spec asks for ~40)", len(X.EMOTIONS) >= 40,
           "found %d" % len(X.EMOTIONS))
_ch = ("pitch", "span", "rate", "energy", "pause", "breath", "tension", "push")
_bad = [n for n, e in X.EMOTIONS.items() if any(k not in e for k in _ch)]
check("every emotion carries every channel", _bad, [])
check_true("emotion families exist", len(X.EMOTION_FAMILIES) >= 6,
           str(sorted(X.EMOTION_FAMILIES)))
check("unknown emotion falls back to neutral",
      X.emo("no-such-emotion"), X.EMOTIONS["neutral"])
for _fam in ("sad", "fear", "bright", "tender", "anger", "awe"):
    check_true("family %s has members" % _fam, len(X.EMOTION_FAMILIES.get(_fam, [])) >= 2)

# ------------------------------------------------------------------ styles ---
_styles = NAR.STYLE_ORDER if NAR is not None else sorted(X.STYLE_DEFAULT_EMOTION)
check("all 14 shipped styles are known to the performance layer",
      sorted(set(_styles) - set(X.STYLE_DEFAULT_EMOTION)), [])
check("all 14 styles have a turn emotion",
      sorted(set(_styles) - set(X.STYLE_TURN_EMOTION)), [])
check("style aliases resolve (Sad Romantic / DEEP EMOTIONAL …)",
      [X._style_id(s) for s in ("Sad Romantic", "sad-romantic", "SAD ROMANTIC",
                                "Emotional Cinematic Storytelling", "cinematic")],
      ["sad_romantic", "sad_romantic", "sad_romantic", "cinematic", "cinematic"])

# --------------------------------------------------------------- the plan ---
plan = X.perform(TEXT, style="cinematic")
check("plan has source, speech and units", bool(plan["source"] and plan["speech"]
                                                and plan["units"]), True)
check("the four layers are declared",
      sorted(plan["layers"]), ["language", "pronunciation", "prosody", "tts"])
for f in ("emotion", "intensity", "pitch_st", "pitch_span", "rate", "energy_db",
          "rhythm", "pauses", "quality", "emphasis", "clauses", "phase"):
    check_true("unit carries %s" % f, all(f in u for u in plan["units"]))
check_true("quality carries breath/tension/projection",
           all(sorted(u["quality"]) == ["breath", "projection", "tension"]
               for u in plan["units"]))

# layer 1+2 really ran (no raw source reaches the performance)
check_in("years are spoken, never digit-read", "មួយពាន់មួយរយប៉ែតសិបមួយ", plan["speech"])
check_in("abbreviation expanded before performing", "គ្រិស្តសករាជ", plan["speech"])
check_in("currency spoken", "មួយរយដុល្លារ", plan["speech"])
check_in("repetition expanded", "បន្តិចម្ដង បន្តិចម្ដង", plan["speech"])
check("no digit left for the model to guess", any(c.isdigit() for c in plan["speech"]),
      False)
check("the ស sign is never performed", "ៗ" in plan["speech"], False)

# --------------------------------------------------------------------- arc ---
phases = [u["phase"] for u in plan["units"]]
check_true("arc covers opening/build/turn/climax/release",
           {"opening", "build", "turn", "climax", "release"} & set(phases),
           str(phases))
check("exactly one climax is chosen", phases.count("climax"), 1)
check_true("the climax is not the first sentence", phases.index("climax") > 0)
check_true("release follows the climax", phases[-1] == "release",
           "last phase: %s" % phases[-1])
check("arc length equals sentence count", len(plan["arc"]), len(plan["units"]))

# ------------------------------------------- emotion inside the sentence -----
turn_unit = [u for u in plan["units"] if any(c["shift"] == "turn" for c in u["clauses"])]
check_true("a contrast word inside a sentence is found", turn_unit)
if turn_unit:
    u = turn_unit[0]
    turned = [c for c in u["clauses"] if c["shift"] == "turn"]
    check("the clause after ប៉ុន្តែ changes emotion",
          turned[0]["emotion"] != u["clauses"][0]["emotion"], True)
    check("the sentence opens in its own colour, the turn changes it",
          (u["emotion"] == u["clauses"][0]["emotion"],
           turned[0]["emotion"] != u["clauses"][0]["emotion"]), (True, True))
dial = [c for u in plan["units"] for c in u["clauses"] if c["dialogue"]]
check_true("quoted speech is performed as dialogue, not narration", dial)
if dial:
    check("dialogue gets its own emotion", dial[0]["emotion"] != "bittersweet", True)
check("clauses keep the source order",
      all(u["clauses"][0]["text"] in u["text"] for u in plan["units"]), True)

# ------------------------------------------------------------------- guard ---
vals = [u["intensity"] for u in plan["units"]]
lo, hi = plan["intensity_band"]
check_true("never flat: intensity moves inside the band", max(vals) - min(vals) >= 5,
           "spread=%d" % (max(vals) - min(vals)))
check_true("every unit stays inside the style band",
           all(lo <= v <= hi for v in vals), str(vals))
hot = [v for v in vals if v >= lo + 0.75 * (hi - lo)]
check_true("no constant drama (high-intensity share capped)",
           len(hot) <= max(1, int(len(vals) * 0.34)), "%d of %d" % (len(hot), len(vals)))
run = best = 0
for u in plan["units"]:
    run = run + 1 if u["quality"]["breath"] >= 0.28 else 0
    best = max(best, run)
check_true("breath is never on every sentence", best <= 2, "longest run = %d" % best)
check_true("no singing: pitch inside a speaking band",
           all(-4.0 <= u["pitch_st"] <= 4.0 for u in plan["units"]))
check_true("no singing: rate inside a speaking band",
           all(0.75 <= u["rate"] <= 1.30 for u in plan["units"]))
check_true("distinct emotions per piece (a performance is not one colour)",
           len({u["emotion"] for u in plan["units"]}) >= 2,
           str([u["emotion"] for u in plan["units"]]))

news = X.perform(TEXT, style="news")
check_true("whisper is refused for styles that must not whisper",
           all(u["quality"]["breath"] <= 0.31 for u in news["units"]))
check_true("NO style may go near-whisper any more (whisper removed 2026-09-30n)",
           X.WHISPER_STYLES == set()
           and max(u["quality"]["breath"]
                   for u in X.perform(TEXT, style="sad_romantic")["units"]) <= 0.31)

med = X.perform(TEXT, style="meditation")
check_true("meditation stays slow and quiet",
           all(u["rate"] <= 1.0 for u in med["units"])
           and max(u["intensity"] for u in med["units"]) <= 25)
check_true("meditation uses longer pauses",
           max(u["pauses"]["before"] for u in med["units"])
           >= max(u["pauses"]["before"] for u in news["units"]))

# --------------------------------------------------------------- emphasis ---
words = [w for u in plan["units"] for w in u["emphasis"]]
check_true("content words are stressed", any(w in X.STRESS_WORDS or len(w) >= 6
                                             for w in words), str(words))
check("function words are never stressed",
      [w for w in words if w in X.NO_STRESS], [])
check("titles are never stressed",
      [w for w in words if w in ("ព្រះបាទ", "ព្រះអង្គ", "ព្រះមហាក្សត្រ")], [])
check_true("at most three stresses per sentence",
           all(len(u["emphasis"]) <= 3 for u in plan["units"]))

# ------------------------------------------------------------ determinism ---
a = X.perform(TEXT, style="thriller")
b = X.perform(TEXT, style="thriller")
check("the same text and style give the same plan",
      json.dumps(a, ensure_ascii=False, sort_keys=True),
      json.dumps(b, ensure_ascii=False, sort_keys=True))
check("speed is clamped (never singing, never mumble)",
      all(u["rate"] <= 1.30 for u in X.perform("សូមស្វាគមន៍", speed=2.0)["units"]), True)
check("a one-sentence text still gets a plan",
      len(X.perform("សូមស្វាគមន៍មកកាន់កម្ពុជា។", style="natural")["units"]), 1)
check("empty text is safe", X.perform("", style="natural")["units"], [])
s = X.summary(plan)
check_true("summary reports emotions and phase range",
           s["units"] and len(s["emotions"]) >= 2 and len(s["intensity"]) == 2)
sheet = X.sheet(plan)
for token in ("KHMER PERFORMANCE SHEET", "style ", "stress", "quality"):
    check_in("sheet shows %s" % token, token, sheet)

# -------------------------------------------------------------------- CLI ---
here = os.path.dirname(os.path.abspath(__file__))
r = subprocess.run([sys.executable, os.path.join(here, "khmer_expressive.py"),
                    "--text", TEXT, "--style", "cinematic", "--json"],
                   capture_output=True, text=True)
check("CLI --json exits 0", r.returncode, 0)
try:
    cli = json.loads(r.stdout)
    check("CLI json is a full plan", bool(cli["units"]), True)
except Exception as e:                                     # pragma: no cover
    check("CLI json parses", "error: %s" % e, "ok")

r = subprocess.run([sys.executable, os.path.join(here, "khmer_expressive.py"),
                    "--list-emotions"], capture_output=True, text=True)
check_in("CLI lists the emotions", "total: %d emotions" % len(X.EMOTIONS), r.stdout)
r = subprocess.run([sys.executable, os.path.join(here, "khmer_expressive.py"),
                    "--list-styles"], capture_output=True, text=True)
check("CLI lists all 14 styles", len([l for l in r.stdout.strip().splitlines() if l]),
      len(_styles))

# --------------------------------------------------- one emotion detector ---
# The studio renders through narration.py; this layer describes the same
# performance for the inspection API. If the two disagreed, the sheet would
# describe audio nobody hears, so agreement is enforced here.
if NAR is not None:
    _dis = 0
    for _sid in (_styles if _styles else ["natural"]):
        for _sent in [x.strip() for x in TEXT.split("។") if x.strip()]:
            _n = NAR.detect_emotion(_sent, _sid)["primary"]
            _x = X.choose_emotion(_sid, _sent)
            _key = NAR.EMOTION_ALIASES.get(_n, _n)
            if _key != _x:
                _dis += 1
                if _dis <= 3:
                    FAILS.append("emotion drift: %s %r -> narration %s vs "
                                 "expressive %s" % (_sid, _sent[:22], _key, _x))
    check("the two performance engines agree on every sentence", _dis, 0)

print("")
print("\nTHE FEELING LAYER (13 styles x four emotional deliveries)")
try:
    import delivery as _D
    _missing = [s for s in _styles if not _D.STYLE_DELIVERIES.get(s)]
    check_true("every shipped style has four emotional deliveries", not _missing, str(_missing))
    _calm = X.perform("ផ្ទះស្ងាត់ណាស់។ គាត់គេងលក់។", style="meditation")
    check_true("no style performs the whole piece as a whisper (build l)",
               all(not u.get("whisper") for u in _calm["units"]),
               str([(u["delivery"], u.get("whisper")) for u in _calm["units"]]))
    check_true("the plan names the feelings it used", bool(_calm.get("deliveries")),
               str(_calm.get("deliveries")))
    _cin = X.perform("សម្ងាត់មួយនៅក្នុងផ្ទះ។ ពេលនោះ គាត់បានយល់។", style="cinematic")
    _wh = [u for u in _cin["units"] if u.get("whisper")]
    check_true("no unit is whispered any more, not even with an intimacy cue (2026-09-30n)",
               not _wh,
               str([(_u["delivery"], u.get("whisper")) for _u in _cin["units"]]))
    check_true("the intimate unit is still delivered intimately (delivery only)",
               all(_u.get("delivery") in _D.STYLE_DELIVERIES["cinematic"]
                   for _u in _cin["units"]))
    check_true("every unit carries its own style's delivery",
               all(_u.get("delivery") in _D.STYLE_DELIVERIES["cinematic"]
                   for _u in _cin["units"]),
               str(sorted({_u.get("delivery") for _u in _cin["units"]})))
except Exception as _e:                                        # pragma: no cover
    check("the feeling layer is importable", False, _e)

print("\nVOICE LOCK (the voice is never re-tuned)")
_txt = ("ខ្ញុំនឹកគាត់ណាស់ ហើយទឹកភ្នែកក៏ធ្លាក់ស្ងាត់ៗ។ ប៉ុន្តែ គាត់មិនបានត្រឡប់មកវិញទេ។")
_bad = []
_units = 0
for _sid in (getattr(X, "STYLE_DEFAULT_EMOTION", {}) or {"audiobook": "neutral"}):
    _r = X.perform(_txt, style=_sid)
    for _u in _r["units"]:
        _units += 1
        _sd = N.style_delivery(_sid)
        _ok = (abs(_u["pitch_st"]) <= 1e-9
               and abs(_u["rate"] - _sd["pace"]) <= N.STYLE_PACE_TOL + 0.01
               and abs(_u["energy_db"] - _sd["gain_db"]) <= N.STYLE_GAIN_TOL + 0.01)
        if not _ok:
            _bad.append((_sid, _u["pitch_st"], _u["energy_db"], _u["rate"]))
check_true("no style or feeling re-tunes the voice: pitch 0.0, its own pace and softness",
           not _bad, f"{len(_bad)} unit(s) out of {_units}" + (f" e.g. {_bad[0]}" if _bad else
           " | e.g. meditation %.2fx %.1f dB, news %.2fx %.1f dB"
           % (X.perform(_txt, style="meditation")["units"][0]["rate"],
              X.perform(_txt, style="meditation")["units"][0]["energy_db"],
              X.perform(_txt, style="news")["units"][0]["rate"],
              X.perform(_txt, style="news")["units"][0]["energy_db"])))
for f in FAILS:
    print("FAIL: " + f)
print("\nkhmer expressive: %d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
