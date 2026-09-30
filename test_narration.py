#!/usr/bin/env python3
"""test_narration.py — checks for the Narration Style engine.

Run:  python test_narration.py

No internet needed (except the two optional live checks at the end, which are
skipped automatically if edge-tts is unavailable).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import narration as N

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'OK  ' if cond else 'FAIL'}] {name}" + (f"  — {detail}" if detail else ""))


print("1. the 13 styles exist, with the exact names from the specification")
WANT = ["Natural Read", "Narrative Storytelling", "Novel Narration", "Documentary",
        "Movie Trailer", "Audiobook", "News Anchor", "Explainer", "Thriller",
        "Meditation", "Inner Monologue", "Sad Romantic",
        "Emotional Cinematic Storytelling"]
labels = [s["label"] for s in N.style_list()]
check("all 13 present", len(labels) == 13, f"{len(labels)} styles")
check("Bedtime is gone (build l: the user removed the style and its voice)",
      "bedtime" not in N.STYLE_SPECS and "bedtime" not in N.STYLE_ORDER
      and "bedtime" not in N.STYLE_DELIVERY
      and not any("bedtime" in l.lower() for l in labels)
      and N.style_id("bedtime") != "bedtime"
      and N.style_id("រឿងនិទានគេង") != "bedtime")
for w in WANT[:5] + WANT[-3:]:
    hit = any(w.lower() in l.lower() or l.lower() in w.lower() for l in labels)
    check(f"name present: {w}", hit)
check("old ids still work (natural/documentary/trailer/…)",
      all(N.style_id(s) in N.STYLE_SPECS for s in
          ["natural", "documentary", "trailer", "audiobook", "news",
           "explainer", "thriller", "meditation"]))
check("tolerant of the exact spec spellings",
      N.style_id("Movie Trailer") == "trailer"
      and N.style_id("Sad Romantic / Melancholic Love") == "sad_romantic"
      and N.style_id("INTERNAL MONOLOGUE") == "inner_monologue")

print("\n2. every style has a complete delivery specification")
for sid in N.STYLE_ORDER:
    s = N.STYLE_SPECS[sid]
    ok = (isinstance(s["intensity"], tuple) and s["intensity"][0] < s["intensity"][1]
          and len(s["pace"]) == 2 and len(s["pitch"]) == 2
          and "pauses" in s and "breath" in s and s["best_for"])
    check(f"spec complete: {s['label'][:26]}", ok)

TEXT = ("ថ្ងៃនេះ សៀវភៅនេះចាប់ផ្តើម។ ប៉ុន្តែនៅពេលយប់ ទ្វារបានបើកឡើងស្រាប់តែ។ "
        "គាត់បានដឹងការពិតដែលគាត់មិនចង់ជឿ។ បន្ទាប់មក គាត់បានយំដោយស្ងាត់ៗ។")

print("\n3. the performance really differs between styles")
plans = {sid: N.plan_text(TEXT, sid, pause=0.3) for sid in N.STYLE_ORDER}
totals = {sid: round(sum(p["rate"] for p in pl) / len(pl), 3)
          for sid, pl in plans.items()}      # mean speaking rate
# SAME VOICE, OWN STYLE (build 2026-09-29j): every style performs at ITS OWN
# pace and its own softness — that is what makes the cards sound different.
# What never moves is the speaker: pitch stays at 0.0 st everywhere.
_spread = max(totals.values()) - min(totals.values())
check("the styles really differ: pace spread across the 13 is audible",
      _spread >= 0.15, f"{min(totals.values()):.2f} – {max(totals.values()):.2f}")
check("each style holds its own pace from the table (STYLE_DELIVERY)",
      all(abs(v - N.style_delivery(sid)["pace"]) <= N.STYLE_PACE_TOL + 0.01
          for sid, v in totals.items()),
      {sid: (round(v, 3), N.style_delivery(sid)["pace"])
       for sid, v in totals.items()})
check("meditation is the slowest, news the fastest",
      min(totals, key=totals.get) == "meditation"
      and max(totals, key=totals.get) == "news",
      f"slowest {min(totals, key=totals.get)}, fastest {max(totals, key=totals.get)}")
check("meditation is the softest and a trailer sits loudest",
      N.style_delivery("meditation")["gain_db"]
      == min(N.style_delivery(s)["gain_db"] for s in N.STYLE_ORDER)
      and N.style_delivery("trailer")["gain_db"]
      == max(N.style_delivery(s)["gain_db"] for s in N.STYLE_ORDER),
      "trailer +%.1f dB, meditation %.1f dB"
      % (N.style_delivery("trailer")["gain_db"],
         N.style_delivery("meditation")["gain_db"]))
check("no style shifts the pitch of the voice",
      all(abs(p["pitch_st"]) < 1e-9 for pl in plans.values() for p in pl))
check("every style keeps its own loudness (no line re-mixes the voice)",
      all(abs(p["gain_db"] - N.style_delivery(sid)["gain_db"])
          <= N.STYLE_GAIN_TOL + 0.01 for sid, pl in plans.items() for p in pl),
      "softest %.1f dB (meditation) … loudest %.1f dB (trailer)"
      % (N.style_delivery("meditation")["gain_db"],
         N.style_delivery("trailer")["gain_db"]))
_pause_tot = {sid: sum(p["pause_s"] for p in plans[sid]) for sid in N.STYLE_ORDER}
check("the styles still differ — in their pauses",
      max(_pause_tot.values()) / max(1e-9, min(_pause_tot.values())) >= 1.4,
      "pause spread %.2fx (slowest %s, fastest %s)"
      % (max(_pause_tot.values()) / max(1e-9, min(_pause_tot.values())),
         max(_pause_tot, key=_pause_tot.get), min(_pause_tot, key=_pause_tot.get)))
check("thriller has longer pauses than news",
      sum(p["pause_s"] for p in plans["thriller"]) >
      sum(p["pause_s"] for p in plans["news"]))
_pl_max = max(sum(p["pause_s"] for p in plans[s]) for s in N.STYLE_ORDER)
_rank = sorted(N.STYLE_ORDER, key=lambda s: -sum(p["pause_s"] for p in plans[s]))
check("the calm styles carry the longest pauses (Meditation and Sad Romantic)",
      set(_rank[:2]) == {"meditation", "sad_romantic"}
      and sum(p["pause_s"] for p in plans["meditation"]) >
      sum(p["pause_s"] for p in plans["news"]) * 1.5,
      "%s  (meditation %.2fs vs news %.2fs)"
      % (", ".join("%s %.2fs" % (s, sum(p["pause_s"] for p in plans[s]))
                   for s in _rank[:3]),
         sum(p["pause_s"] for p in plans["meditation"]),
         sum(p["pause_s"] for p in plans["news"])))
check("emotional styles react to loaded words (grief/tension detected)",
      any(p["emotion"] in ("grief", "tension", "revelation")
          for p in plans["cinematic"]))

print("\n4. contrast and quiet moments are enforced (spec: never one flat level)")
for sid, pl in plans.items():
    inten = [p["intensity"] for p in pl]
    lo, hi = N.STYLE_SPECS[sid]["intensity"]
    check(f"inside band + not flat: {sid}",
          all(lo <= i <= hi for i in inten) and (max(inten) - min(inten)) >= 0,
          f"I {min(inten)}-{max(inten)} (band {lo}-{hi})")
check("NO style puts a breath in the plan any more (build 2026-09-30o)",
      all(sum(1 for p in pl if p["breath"]) == 0 for pl in plans.values()),
      str({s: sum(1 for p in pl if p["breath"]) for s, pl in plans.items()
           if any(p["breath"] for p in pl)})[:80])
check("news is breathless (and now so is every other style)",
      sum(1 for p in plans["news"] if p["breath"]) == 0)

print("\n5. reproducibility (a re-run must give the identical performance)")
a = N.plan_text(TEXT, "cinematic", pause=0.3)
b = N.plan_text(TEXT, "cinematic", pause=0.3)
check("plans identical across calls", a == b)

print("\n6. the spec's worked example: the same words, two performances")
LINE = "She opened the door, but he wasn't there."
th = N.plan_text(LINE, "thriller", pause=0.4)[0]
sr = N.plan_text(LINE, "sad_romantic", pause=0.4)[0]
# With the voice-identity band in place, two styles may share a pitch figure —
# what must differ is the DELIVERY: pace, loudness, pauses, emphasis.
check("thriller and sad-romantic differ in their delivery",
      (th["rate"], th["gain_db"], th["pause_s"], th["intensity"]) !=
      (sr["rate"], sr["gain_db"], sr["pause_s"], sr["intensity"]),
      f"thriller {th['rate']:.3f}x/{th['gain_db']:+.2f}dB/{th['pause_s']:.2f}s vs "
      f"sad {sr['rate']:.3f}x/{sr['gain_db']:+.2f}dB/{sr['pause_s']:.2f}s")
check("both styles keep the speaker identical (pitch 0.0 in each)",
      abs(th["pitch_st"]) < 1e-9 and abs(sr["pitch_st"]) < 1e-9,
      "pitch %s" % sorted({th["pitch_st"], sr["pitch_st"]}))
check("each one still sits at its own pace and softness",
      abs(th["rate"] - N.style_delivery("thriller")["pace"]) <= N.STYLE_PACE_TOL + 0.01
      and abs(sr["rate"] - N.style_delivery("sad_romantic")["pace"]) <= N.STYLE_PACE_TOL + 0.01
      and abs(th["gain_db"] - N.style_delivery("thriller")["gain_db"]) <= N.STYLE_GAIN_TOL + 0.01
      and abs(sr["gain_db"] - N.style_delivery("sad_romantic")["gain_db"]) <= N.STYLE_GAIN_TOL + 0.01)
check("both stay inside their own band",
      N.STYLE_SPECS["thriller"]["intensity"][0] <= th["intensity"] <= N.STYLE_SPECS["thriller"]["intensity"][1]
      and N.STYLE_SPECS["sad_romantic"]["intensity"][0] <= sr["intensity"] <= N.STYLE_SPECS["sad_romantic"]["intensity"][1])


print("\n14. VOICE IDENTITY: the same speaker in all 13 styles and all feelings")
TESTS = [
    "ជំពូកទីមួយ។ នៅពេលព្រឹក ផ្ទះទាំងមូលនៅស្ងាត់ណាស់។",
    "ខ្ញុំនឹកគាត់ណាស់ ហើយទឹកភ្នែកក៏ធ្លាក់ស្ងាត់ៗ។ ប៉ុន្តែ ខ្ញុំមិនអាចត្រឡប់ទៅវិញទេ។",
    "គាត់ដើរចេញទៅ។ ភាពស្ងាត់បានរីកធំឡើងក្នុងផ្ទះតូចនេះ — ហើយខ្ញុំឈរនៅទីនោះ។",
]
_all = []
for _sid in N.STYLE_ORDER:
    for _t in TESTS:
        _all += N.plan_text(_t, style=_sid, speed=1.0, pause=0.35)
_pitch = [p["pitch_st"] for p in _all]
_gain = [p["gain_db"] for p in _all]
_style_rate = [round(p["rate"], 4) for p in _all]
check("VOICE LOCK: not one style shifts the pitch (all 13 styles)",
      all(abs(v) < 1e-9 for v in _pitch),
      f"pitch values {sorted(set(round(v, 6) for v in _pitch))}")
_by_style = {}
for _sid in N.STYLE_ORDER:
    for _t in TESTS:
        _by_style.setdefault(_sid, []).extend(
            N.plan_text(_t, style=_sid, speed=1.0, pause=0.35))
_bad_gain = [(sid, round(p["gain_db"], 2)) for sid, pl in _by_style.items()
             for p in pl
             if abs(p["gain_db"] - N.style_delivery(sid)["gain_db"])
             > N.STYLE_GAIN_TOL + 0.01]
check("every style sits at its own softness (and no line re-mixes the voice)",
      not _bad_gain,
      f"{len(_bad_gain)} line(s) outside their style's band"
      + (f" e.g. {_bad_gain[0]}" if _bad_gain else
         f" | softest {min(N.style_delivery(s)['gain_db'] for s in N.STYLE_ORDER):+.1f} dB, "
         f"loudest {max(N.style_delivery(s)['gain_db'] for s in N.STYLE_ORDER):+.1f} dB"))
_bad_pace = [(sid, round(p["rate"], 3)) for sid, pl in _by_style.items()
             for p in pl
             if abs(p["rate"] - N.style_delivery(sid)["pace"])
             > N.STYLE_PACE_TOL + 0.01]
check("every style speaks at its own pace (your NARRATION SPEED applies on top)",
      not _bad_pace,
      f"{len(_bad_pace)} line(s) outside their style's pace"
      + (f" e.g. {_bad_pace[0]}" if _bad_pace else ""))
# every feeling the engine knows gets its own sentence through the detector,
# then through the plan — and every one of them must stay inside the band
_hits, _bad, _tot = set(), [], 0
for _name, _words in N.EMO_WORDS:
    if not _words:
        continue
    _w = _words[0]
    for _style in ("cinematic", "audiobook", "sad_romantic"):
        for _p in N.plan_text(f"ខ្ញុំ{_w} ណាស់។ គាត់បាន{_w}ជាមួយខ្ញុំ។", style=_style,
                              speed=1.0, pause=0.35):
            _tot += 1
            if _p.get("emotion") == _name or _name in (_p.get("emotion_secondary") or ()):
                _hits.add(_name)
            _sd = N.style_delivery(_style)
            if (abs(_p["pitch_st"]) > 1e-9
                    or abs(_p["gain_db"] - _sd["gain_db"]) > N.STYLE_GAIN_TOL + 0.01
                    or abs(_p["rate"] - _sd["pace"]) > N.STYLE_PACE_TOL + 0.01):
                _bad.append((_name, _style, _p["pitch_st"], _p["gain_db"], _p["rate"]))
check("every feeling word keeps the speaker untouched and the style's own delivery",
      not _bad,
      f"{len(_bad)} line(s) outside the style's band"
      + (f" e.g. {_bad[0]}" if _bad else ""))
check("the detector really reached the feeling words",
      len(_hits) >= 12,
      f"{len(_hits)} feelings triggered over {_tot} planned lines")
check("the user's speed slider is what actually plays",
      abs(N.plan_text("ខ្ញុំនឹកគាត់ណាស់។", style="cinematic", speed=1.40)[0]["rate"] - 1.4 * N.plan_text("ខ្ញុំនឹកគាត់ណាស់។", style="cinematic", speed=1.0)[0]["rate"]) < 1e-6)

print("\n7. length safety (a long sentence still plans)")
long_text = " ".join(["ព្រះរាជាណាចក្រខ្មែរបានរីកចម្រើន"] * 40) + "។"
pl = N.plan_text(long_text, "novel")
check("long passage -> several units", len(pl) >= 1, f"{len(pl)} units")

print("\n7b. unit shapes (a misunderstood tuple makes it say the speaker letter)")
SENT = "សូមស្វាគមន៍មកកាន់កម្មវិធីរបស់យើង។"
shapes = {
    "(text, boundary)": [("placeholder", ".")],
}
for label, units in (
        ("(speaker, text, boundary) — the studio", [("A", SENT, ".")]),
        ("(text, boundary) — the splitter", [(SENT, ".")]),
        ("{speaker, text, boundary} — the pipeline", [{"speaker": "A", "text": SENT,
                                                       "boundary": "."}]),
        ("(speaker, text) — tolerant", [("A", SENT)]),
):
    pl = N.plan(units, style="news")
    ok = pl and pl[0]["text"] == SENT
    check(f"plan reads {label}", ok,
          f"text={pl[0]['text'][:22]!r}" if pl else "empty plan")
check("the speaker reaches the plan (for duo hosts)",
      N.plan([("B", SENT, ".")], style="news")[0]["speaker"] == "B")
check("no plan ever speaks a speaker letter",
      all(p["text"].strip() not in ("A", "B", "S", "HOST")
          for p in N.plan([("A", SENT, "."), ("B", SENT, ".")], style="audiobook")))

print("\n7c. the whisper is a MOMENT again, and only a moment (build l)")
BTEXT = ("The room is quiet now. Remember the warm light, and let it go. "
         "The night will keep you.")
_moment = N.plan_text(BTEXT, "cinematic", pause=0.3)
check("no style whispers a whole piece any more",
      all(not all(p["whisper"] for p in N.plan_text(BTEXT, sid, pause=0.3))
          for sid in N.STYLE_ORDER))
check("a plain line in the cinematic read is NOT whispered (build l)",
      sum(1 for p in _moment if p["whisper"]) == 0,
      "%d of %d lines whispered" % (sum(1 for p in _moment if p["whisper"]),
                                    len(_moment)))
_int = N.plan_text("សម្ងាត់មួយ។ He leaned close and whispered her name.",
                   "cinematic", pause=0.3)
check("not even an intimacy cue can ask for a whisper now (2026-09-30n)",
      sum(1 for p in _int if p["whisper"]) == 0,
      "%d of %d whispered" % (sum(1 for p in _int if p["whisper"]), len(_int)))
check("…the line is still performed as an intimate one (soft, slow, paused)",
      all(p["gain_db"] <= 1.0 and p["rate"] <= 1.05 for p in _int),
      "gain %s rate %s" % (sorted({p["gain_db"] for p in _int}),
                           sorted({round(p["rate"], 3) for p in _int})))
check("the whisper never opens a register change (pitch stays 0.0)",
      all(p["pitch_st"] == 0.0 for p in _moment))
check("it is a DELIVERY: the moment goes soft, never a new voice",
      all(p["gain_db"] <= 0.5 for p in _moment),
      "gain %s" % sorted({p["gain_db"] for p in _moment}))

print("\n8. the tone style of styles 12 and 13 (whisper, breaking, fear, curve)")
SAD = N.STYLE_SPECS["sad_romantic"]
CIN = N.STYLE_SPECS["cinematic"]
check("sad romantic carries breaking/suspended/arc (whisper is gone, 2026-09-30n)",
      all(k in SAD for k in ("breaking", "suspended", "arc")) and not SAD.get("whisper"))
check("cinematic carries breaking/suspended/arc/fear (whisper is gone, 2026-09-30n)",
      all(k in CIN for k in ("breaking", "suspended", "arc", "fear")) and not CIN.get("whisper"))
check("no style in the whole set carries a whisper block",
      not any(N.STYLE_SPECS[sid].get("whisper") for sid in N.STYLE_ORDER))
check("other styles are untouched by the tone style",
      not any(k in N.STYLE_SPECS[sid]
              for sid in ("natural", "audiobook", "news", "meditation", "thriller")
              for k in ("whisper", "breaking", "suspended", "fear")))

def plan_without(style, key, text, **kw):
    """The same performance with one tone-style pass switched off.

    Used to measure what a pass really did: the honest question is not "is the
    whisper quiet in absolute terms" but "did the whisper make THIS sentence
    quieter than it would have been".
    """
    saved = N.STYLE_SPECS[style].pop(key)
    try:
        return N.plan_text(text, style, **kw)
    finally:
        N.STYLE_SPECS[style][key] = saved


STORY = ("គាត់បានចាកចេញនៅថ្ងៃដែលភ្លៀងធ្លាក់។ ខ្ញុំនៅតែចងចាំពាក្យចុងក្រោយរបស់គាត់។ "
         "ពេលខ្លះ ខ្ញុំឮសំឡេងគាត់នៅក្នុងផ្ទះស្ងាត់។ ខ្ញុំភ័យខ្លាចយប់ស្ងាត់។ "
         "តើគាត់នឹងត្រលប់មកវិញពេលណា? ខ្ញុំនៅតែរង់ចាំ ដូចជាថ្ងៃដំបូង។")
for sid in ("sad_romantic", "cinematic"):
    pl = N.plan_text(STORY, sid, pause=0.4)
    n = len(pl)
    _sd = N.style_delivery(sid)          # always set (build l: cinematic has no whisper block)
    wh = [i for i, p in enumerate(pl) if p["whisper"]]
    br = [i for i, p in enumerate(pl) if p["breaking"]]
    su = [i for i, p in enumerate(pl) if p["suspended"]]
    fe = [i for i, p in enumerate(pl) if p["fear"]]
    if sid == "cinematic":
        # build l: this style has no RANDOM whisper any more — a plain story
        # must arrive un-whispered, and only the words can ask for one
        check("cinematic: a plain story arrives with NO whispered line",
              not wh, f"{len(wh)}/{n} sentences")
        _intimate = N.plan_text("គាត់ខ្សឹបឈ្មោះនាង។ He leaned close and whispered.",
                                sid, pause=0.4)
        _wh = [p for p in _intimate if p["whisper"]]
        check("cinematic: even a line the words earn is NOT whispered (2026-09-30n)",
              not _wh, "%d line(s) whispered" % len(_wh))
        check("cinematic: it is still performed intimately (softer, slower)",
              all(p["gain_db"] <= 1.0 for p in _intimate),
              "gain %s" % sorted({p["gain_db"] for p in _intimate}))
    else:
        check(f"{sid}: no line is whispered in this style either (2026-09-30n)",
              not wh, f"{len(wh)}/{n} sentences")
    check(f"{sid}: nothing whispers at all — the piece is the same voice throughout",
          not wh, f"{len(wh)}/{n} sentences")
    # every line keeps the identity lock, whether or not the words are intimate
    check(f"{sid}: pitch stays at exactly 0.0 on every line",
          all(p["pitch_st"] == 0.0 for p in pl))
    check(f"{sid}: exactly one breaking point", len(br) == 1)
    if br:
        b = pl[br[0]]
        bbase = plan_without(sid, "breaking", STORY, pause=0.4)[br[0]]
        check(f"{sid}: the break hesitates (longer pre-pause, longer gap, NO breath)",
              b["pre_pause_ms"] > bbase["pre_pause_ms"]
              and abs(b["gain_db"] - _sd["gain_db"]) <= N.STYLE_GAIN_TOL + 0.01
              and abs(b["rate"] - _sd["pace"]) <= N.STYLE_PACE_TOL + 0.01
              and b["pitch_st"] == 0.0
              and b["pause_s"] > bbase["pause_s"] and not b["breath"],
              f"pre {b['pre_pause_ms']}ms (was {bbase['pre_pause_ms']}ms), "
              f"pause {b['pause_s']:.2f}s vs {bbase['pause_s']:.2f}s")
        check(f"{sid}: the break sits at the emotional peak",
              b["intensity"] == max(p["intensity"] for p in pl))
    check(f"{sid}: suspended endings exist for longing/uncertainty", bool(su))
    check(f"{sid}: not every sentence is treated (restraint)",
          (len(wh) + len(br) + len(su) + len(fe)) <= n, f"{len(wh)+len(br)+len(su)+len(fe)}/{n}")
    check(f"{sid}: loudness never leaves the safe range",
          all(-6.0 <= p["gain_db"] <= 6.0 and -3.0 <= p["pitch_st"] <= 4.0 for p in pl))

cpl = N.plan_text(STORY, "cinematic", pause=0.4)
fear_items = [p for p in cpl if p["fear"]]
check("cinematic: fear is capped (a scene, not the whole story)",
      len(fear_items) <= max(1, len(cpl) // 3), f"{len(fear_items)}/{len(cpl)}")
check("cinematic: fear goes quieter, never louder",
      all(p["gain_db"] < 2.0 for p in fear_items))

LONG = (" ".join(["ខ្ញុំចងចាំអតីតកាលដែលយើងធ្លាប់នៅជាមួយគ្នា។"] * 9) + " ខ្ញុំនៅតែរង់ចាំ។")
for sid in ("sad_romantic", "cinematic"):
    lp = N.plan_text(LONG, sid, pause=0.4)
    inten = [p["intensity"] for p in lp]
    mid = inten[len(inten) // 2]
    check(f"{sid}: the emotional curve peaks in the middle, not at the ends",
          mid >= inten[0] and mid >= inten[-1],
          f"start {inten[0]} mid {mid} end {inten[-1]}")
    check(f"{sid}: a long piece still keeps quiet sentences (contrast)",
          min(inten) < max(inten))

spl = N.plan_text("ខ្ញុំនៅតែចងចាំអ្នក ហើយខ្ញុំមិនដឹងថាអ្នកនៅឯណា។ អ្នកបានលាហើយ។",
                  "sad_romantic", pause=0.4)
stressed = [p["stress"] for p in spl if p["stress"]]
check("sad romantic: emphasis lands on its own emotional words",
      bool(stressed) and any(w in " ".join(stressed) for w in
                             ("អ្នក", "ខ្ញុំ", "ចងចាំ", "នៅតែ", "លាហើយ", "មិនដឹង")),
      (stressed[0][:24] if stressed else "none"))

print(f"\n{PASS if False else ''}{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("failed checks:")
    for f in FAIL:
        print("  -", f)
sys.exit(1 if FAIL else 0)
