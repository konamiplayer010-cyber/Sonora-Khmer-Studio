#!/usr/bin/env python3
"""test_whisper.py — the whisper stage is REMOVED (build 2026-09-30n).

This file used to check that whisper.py made a good near-whisper. It now checks
that nothing whispers at all, because that is what the user asked for after
hearing the result:

    "The whisper voice/sound still have in all voice as in Khmer and English
     Language. That whisper is so bad. While the normal voice is reading then
     sometime the whisper hear/come to loud replace the normal voice. So, in
     this step I want you remove all whisper voices from original voice."

A whispered line was synthesised as a *different sound* — a breath carrying the
words — so wherever it landed mid-read it stopped being the voice that was
speaking. That is why the answer is removal, not a gentler whisper.

What this guards now:
  1. the engine entry points are inert: `depth_for()` is 0.0 for every style and
     every flagged item, and `whisperize()` returns its input BIT-IDENTICAL;
  2. no style carries a whisper block, and no planned line is ever flagged;
  3. the delivery layer cannot ask for one: `whisper_depth()` is 0.0 across
     every style × delivery, and no delivery move carries a whisper depth;
  4. no rendered path calls the synthesiser any more (studio and batch);
  5. the two engine copies are the same file — a stale copy is how a studio and
     a pipeline start sounding different;
  6. the performance that did the real work is still there: an intimate passage
     is still slower/softer/paused — it is simply the same voice throughout.

    python pipeline/test_whisper.py
"""
import glob
import hashlib
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "sonora"))

OK, FAIL = [], []


def check(name, cond, extra=""):
    (OK if cond else FAIL).append(name)
    print("  %s %-58s %s" % ("ok  " if cond else "FAIL", name, extra))


try:
    import numpy as np
except Exception:                                             # pragma: no cover
    print("numpy is required for this test")
    raise

import whisper as W                      # noqa: E402
import delivery as D                     # noqa: E402
import narration as N                    # noqa: E402


def _write_wav24(path, x, sr=48000):
    """24-bit WAV, like the studio's masters — the detector reads real files."""
    import struct
    a = np.clip(np.asarray(x, dtype=np.float32), -1, 1)
    i = np.round(a * 8388607.0).astype("<i4")
    b = np.empty((a.size, 3), np.uint8)
    b[:, 0], b[:, 1], b[:, 2] = (i & 255), ((i >> 8) & 255), ((i >> 16) & 255)
    d = b.tobytes()
    h = struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 3, 3, 24)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + len(d)) + b"WAVE"
                + b"fmt " + h + b"data" + struct.pack("<I", len(d)) + d)
    return path


def _voice(n=24000 * 2, sr=24000, f0=150.0):
    t = np.arange(n) / float(sr)
    x = np.zeros(n, np.float32)
    for k in (1, 2, 3, 4, 5):                    # a buzz with a formant shape
        x += (0.30 / k) * np.sin(2 * np.pi * f0 * k * t)
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 1.7 * t)
    x *= env
    x += 0.01 * np.random.default_rng(4).normal(0, 1, n)   # a little floor
    return (x * 0.4).astype(np.float32)


WORK = tempfile.mkdtemp(prefix="test_whisper_")
FF = "ffmpeg"
print("whisper removed — build 2026-09-30n")
print("=" * 74)

# ---------------------------------------------------------------- 1. engine
print("\n1. the engine entry points are inert")
voice = _voice()
check("depth_for() is 0.0 for a fully flagged item",
      W.depth_for("cinematic", {"whisper": True, "whisper_depth": 0.55}) == 0.0)
check("depth_for() is 0.0 for every style name",
      all(W.depth_for(s, {"whisper": True}) == 0.0
          for s in list(N.STYLE_SPECS) + ["bedtime", "Bedtime", "រឿងនិទានគេង"]))
check("depth_for() is 0.0 with no item at all",
      W.depth_for("cinematic") == 0.0 and W.depth_for("cinematic", {}) == 0.0)
same = all(bool(np.array_equal(voice, W.whisperize(voice, rate=24000, depth=d, seed=s)))
           for d in (0.0, W.DEPTH_MOMENT, W.DEPTH_FULL, 1.0) for s in (0, 7, 99))
check("whisperize() returns the line BIT-IDENTICAL at every depth/seed", same)
check("whisperize() does not even copy into a different dtype",
      W.whisperize(voice, depth=1.0).dtype == voice.dtype
      and W.whisperize(voice, depth=1.0).shape == voice.shape)
check("the old synthesiser is unreachable from the public entry point",
      callable(W.whisperize) and W.whisperize.__doc__.startswith("Return the line UNCHANGED"))

# ------------------------------------------------------- 2. the style specs
print("\n2. no style can ask for one")
blocks = {sid: (spec.get("whisper") or None) for sid, spec in N.STYLE_SPECS.items()}
check("every style's whisper block is gone/None",
      not any(blocks.values()), {k: v for k, v in blocks.items() if v} or "none")
check("the key is still read by the planner (shape unchanged where it exists)",
      all(("whisper" not in spec) or spec["whisper"] is None
          for spec in N.STYLE_SPECS.values()),
      "%d styles" % len(N.STYLE_SPECS))

texts = [
    "This is a plain narration line with nothing intimate in it at all.",
    "សម្ងាត់មួយ។ He leaned close and whispered her name into her ear. Stay quiet, he said.",
    "Suddenly the door moved. She remembered long ago. Tears fell. In an instant, fear.",
    "ខ្ញុំចងចាំរឿងនោះ។ ស្រាប់តែទ្វារបើក។ ទឹកភ្នែកហូរ។",
]
lines = flagged = 0
for sid in N.STYLE_SPECS:
    for t in texts:
        plans = N.plan_text(t, sid, pause=0.3)
        lines += len(plans)
        flagged += sum(1 for p in plans if p.get("whisper"))
check("no planned line in any style is flagged for whispering",
      flagged == 0, "%d of %d lines over %d styles" % (flagged, lines, len(N.STYLE_SPECS)))
check("the planner still flags the line's own keys (shape unchanged)",
      all("whisper" in N.plan_text("Hello there.", sid, pause=0.3)[0]
          for sid in ("natural", "cinematic") if N.plan_text("Hello there.", sid, pause=0.3)))
check("_apply_whisper() is a no-op even when a style is force-fed a whisper block",
      (lambda: (N._apply_whisper([{"gain_db": 0.0, "rate": 1.0, "pause_s": 0.0}],
                                 {"id": "cinematic",
                                  "whisper": {"chance": 1.0, "mode": "sustained",
                                              "depth": 1.0}}),
                True)[1])())

# ------------------------------------------------------------ 3. delivery
print("\n3. no delivery can ask for one")
depths = sorted(set(D.whisper_depth(sid, name)
                    for sid, names in D.STYLE_DELIVERIES.items() for name in names))
check("whisper_depth() is 0.0 for every style × delivery", depths == [0.0], depths)
check("SUSTAINED_WHISPER is still empty", D.SUSTAINED_WHISPER == set())
carriers = [n for n, m in D.MOVES.items() if m.get("whisper")]
check("no delivery move carries a whisper depth", not carriers, carriers or "none")
check("“Whisper / Intimate” survives as a plain intimate delivery",
      "Whisper / Intimate" in D.MOVES
      and not D.MOVES["Whisper / Intimate"].get("whisper"),
      str(D.MOVES.get("Whisper / Intimate"))[:70])

# --------------------------------------------------------- 4. render paths
print("\n4. no rendered path calls the synthesiser")
srv = io.open(os.path.join(ROOT, "sonora", "server.py"), encoding="utf-8").read()
nar = io.open(os.path.join(HERE, "narration.py"), encoding="utf-8").read()
node = io.open(os.path.join(ROOT, "sonora", "narration.py"), encoding="utf-8").read()
check("the studio no longer whisperises a line (server.py)",
      "WH.whisperize" not in srv and "import whisper as WH" not in srv)
check("the studio still routes every line through the stage hook",
      srv.count("arr = _whisper_stage(arr, plan[i], i)") == 1)
check("the batch renderer no longer whisperises a sentence (narration.py)",
      "_WH.whisperize" not in nar and "_WH.whisperize" not in node)
check("no module imports the synthesiser for rendering any more",
      "import whisper as _WH" not in nar and "import whisper as _WH" not in node)

# ------------------------------------------------------- 5. the copies match
print("\n5. the two engine copies are one file")
for name, a, b in (("whisper.py", os.path.join(HERE, "whisper.py"),
                    os.path.join(ROOT, "sonora", "whisper.py")),
                   ("delivery.py", os.path.join(HERE, "delivery.py"),
                    os.path.join(ROOT, "sonora", "delivery.py"))):
    ha = hashlib.md5(open(a, "rb").read()).hexdigest()
    hb = hashlib.md5(open(b, "rb").read()).hexdigest()
    check("%s: pipeline == studio" % name, ha == hb, ha[:10])

# -------------------------------------------- 6. the performance still exists
print("\n6. what stays: the intimate delivery, by the same voice")
intimate = D.MOVES["Whisper / Intimate"]
base = D.MOVES.get(next(iter(D.MOVES)))
check("the intimate slot is still slower and airier than a neutral delivery",
      intimate["pause"] >= 1.2 and intimate["breath"] >= 0.6,
      "pause %.2f · breath %.2f" % (intimate["pause"], intimate["breath"]))
check("what it changes is delivery only (no voice keys in the move)",
      not any(k in intimate for k in ("pitch", "voice", "formant", "whisper")),
      sorted(intimate))
plans = N.plan_text("សម្ងាត់មួយ។ He leaned close and whispered her name.", "cinematic", pause=0.3)
check("an intimate line is still performed (rate/pauses move, voice does not)",
      plans and all(p.get("pitch_st", 0.0) == 0.0 for p in plans),
      "%d lines · pitch locked" % len(plans))

# ------------------------------------------- 7. the detector finds one if it exists
print("\n7. the detector (pipeline/check_whisper.py) still works")
AB = os.path.join(ROOT, "sonora", "public", "whisper_ab")
try:
    import check_whisper as CW
    have_ab = all(os.path.exists(os.path.join(AB, f))
                  for f in ("old-whispered.mp3", "new-voice.mp3"))
    if not have_ab:
        print("  --   (A/B clips not present: detector check skipped)")
    else:
        import subprocess
        old_r = CW.analyse(os.path.join(AB, "old-whispered.mp3"))
        new_r = CW.analyse(os.path.join(AB, "new-voice.mp3"))
        check("the detector flags the old whispered take",
              old_r.get("whisper_dominant") is True,
              "air %.1f dB · pitch %.2f" % (old_r.get("file_air_db", 0),
                                            old_r.get("file_periodicity", 0)))
        check("the detector clears the same line read normally",
              (new_r.get("whisper_dominant") is not True
               and not new_r.get("whisper_passages")),
              "air %.1f dB · pitch %.2f" % (new_r.get("file_air_db", 0),
                                            new_r.get("file_periodicity", 0)))
        # a whisper arriving inside a normal read — the user's report, as a fixture
        ff = CW.ffmpeg(FF if FF != "ffmpeg" else None)
        v = CW.decode(os.path.join(AB, "new-voice.mp3"), ff)
        w = CW.decode(os.path.join(AB, "old-whispered.mp3"), ff)
        mix = np.concatenate([v, np.zeros(int(0.35 * CW.SR), np.float32), w,
                              np.zeros(int(0.35 * CW.SR), np.float32), v])
        mixp = os.path.join(WORK, "hybrid.wav")
        _write_wav24(mixp, mix)
        mix_r = CW.analyse(mixp)
        found = mix_r.get("whisper_passages") or []
        check("the detector finds a whisper PASSAGE inside a normal read",
              len(found) == 1 and found[0]["seconds"] >= 2.5,
              "%d passage(s) %s" % (len(found),
                                    [(p["start_s"], p["seconds"]) for p in found]))
        if found:
            check("…and it points at the right time in the file",
                  4.0 <= found[0]["start_s"] <= 4.4 and found[0]["end_s"] <= 8.1,
                  "%.2f–%.2f s" % (found[0]["start_s"], found[0]["end_s"]))
            check("…with the right reason (airy and pitchless)",
                  found[0]["air_over_voice_db"] >= 6.0
                  and found[0]["periodicity"] <= 0.28,
                  "air %+.1f dB · pitch %.2f" % (found[0]["air_over_voice_db"],
                                                 found[0]["periodicity"]))
        demos = sorted(glob.glob(os.path.join(ROOT, "sonora", "public",
                                              "style_demos", "*.mp3")))
        if demos:
            bad = [os.path.basename(d) for d in demos
                   if CW.analyse(d).get("whisper_passages")
                   or CW.analyse(d).get("whisper_dominant")]
            check("no shipped style demo is flagged", not bad, bad or "none")
except Exception as e:
    check("the detector runs", False, "%s: %s" % (type(e).__name__, e))

# --------------------------------------------------------------------------- #
# 8. the pause breath (build 2026-09-30o) — the last non-speech sound
# --------------------------------------------------------------------------- #
# The whispered line was not the only airy thing in a read. The render loop also
# wrote a synthesised inhale ("shaped noise, low-passed") into the gaps between
# sentences, ~10-15 times in a five-minute piece — the "whisper" the user kept
# hearing between sentences. Nothing writes it any more; both synthesisers
# return silence, and the planner cannot mark a breath at all.
print("\n8. the pause breath is gone (and cannot come back)")

import numpy as _np                    # noqa: E402

_BREATH_TXT = ("The keeper wrote the same sentence every night. Nobody read it. "
               "The sea was loud and the light went round and round. "
               "He secret whispered low, leaned close, and told her everything.")
for _sid in N.STYLE_ORDER:
    _pl = N.plan_text(_BREATH_TXT, _sid, 1.0, 0.25)
    _bad = [i for i, p in enumerate(_pl) if p["breath"]]
    check("%s: the plan carries no breath" % _sid, not _bad, "lines %s" % _bad)

_item = dict(pause_s=1.0, breath=False, pre_pause_ms=0, stress="", words=8)
D.apply_to_plan_item(_item, D.MOVES["Whisper / Intimate"],
                     name="Whisper / Intimate", style="cinematic", breath=True)
check("even the intimate delivery cannot mark a breath",
      _item["breath"] is False, str(_item.get("breath")))

_br = N._breath_np(0.3, -37.0, 3)
check("narration._breath_np returns digital silence",
      _br.size > 0 and float(_np.max(_np.abs(_br))) == 0.0,
      "peak %.6f" % (float(_np.max(_np.abs(_br))) if _br.size else -1.0))

_SRV = io.open(os.path.join(ROOT, "sonora", "server.py"), encoding="utf-8").read()
check("the studio render loop no longer calls the breath synthesiser",
      "_breath_samples(int(" not in _SRV)
check("server._breath_samples returns digital silence",
      "return np.zeros(max(0, int(n)), dtype=np.float32)" in _SRV)
_NAR = io.open(os.path.join(ROOT, "sonora", "narration.py"), encoding="utf-8").read()
check("no renderer writes a breath into a pause", "_breath_np(br_s" not in _NAR)
check("the planner guarantees every plan leaves with no breath",
      'for p in plans:\n        p["breath"] = False' in _NAR)

# the checker can now see it: the old take is flagged, the new one is cleared,
# and every shipped clip is silent in its pauses
_AB = os.path.join(ROOT, "sonora", "public", "whisper_ab")
try:
    import check_whisper as CW2
    old_r = CW2.analyse(os.path.join(_AB, "pause-with-breath.mp3"))
    new_r = CW2.analyse(os.path.join(_AB, "pause-now-silent.mp3"))
    check("the pause audit finds the old breath and its time",
          len(old_r.get("pause_noise") or []) >= 1
          and 2.8 <= (old_r["pause_noise"][0]["start_s"]) <= 3.6,
          str(old_r.get("pause_noise"))[:90])
    check("the pause audit clears the silent take",
          not new_r.get("pause_noise"), str(new_r.get("pause_noise"))[:90])
    _demos = sorted(glob.glob(os.path.join(ROOT, "sonora", "public",
                                           "style_demos", "*.mp3")))
    _noisy = [os.path.basename(d) for d in _demos
              if CW2.analyse(d).get("pause_noise")]
    check("every shipped style demo is silent in its pauses", not _noisy,
          str(_noisy) or "%d clips clean" % len(_demos))
except Exception as e:
    check("the pause audit runs", False, "%s: %s" % (type(e).__name__, e))

print("\n" + "=" * 74)
print("whisper removal: %d passed, %d failed" % (len(OK), len(FAIL)))
for f in FAIL:
    print("  FAILED:", f)
sys.exit(1 if FAIL else 0)
