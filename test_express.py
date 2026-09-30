#!/usr/bin/env python3
"""test_express.py — checks for the expressive stage (express.py).

What this guards (update #3, build 2026-09-29k):

  1. the stage exists in BOTH apps and both copies are the same file;
  2. only the two styles the user named are switched ON (Emotional Cinematic
     Storytelling + Bedtime); every other row is written down but off, so
     switching one on later is a one-line change that the tests will notice;
  3. the performance is really inside the sentence: the loudest moment is the
     emphasis beat, the sentence eases away at the end, and the presence band
     (2.2–5.2 kHz — the "closer, clearer" band) is lifted on the beat;
  4. it never touches the speaker: pitch is unchanged, the length is
     unchanged (nothing is time-stretched), nothing clips, no NaN;
  5. a style with no plan is handed back bit-for-bit untouched;
  6. the rendered paths really call it (server.py + narration.render_styled);
  7. it is deterministic (same line, same position -> same audio).

    python pipeline/test_express.py
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "sonora"))

OK, FAIL = [], []


def check(name, cond, extra=""):
    (OK if cond else FAIL).append(name)
    print("  [%s] %s%s" % ("OK  " if cond else "FAIL", name,
                           "  — " + str(extra) if extra else ""))


try:
    import numpy as np
except Exception:                                             # pragma: no cover
    np = None
try:
    import express as EX
except Exception as e:                                        # pragma: no cover
    print("cannot import express.py:", e)
    sys.exit(1)

print("1. the stage exists in both apps, and both copies are identical")
_pp = os.path.join(HERE, "express.py")
_sp = os.path.join(ROOT, "sonora", "express.py")
check("pipeline/express.py exists", os.path.exists(_pp))
check("sonora/express.py exists", os.path.exists(_sp))
if os.path.exists(_pp) and os.path.exists(_sp):
    a = io.open(_pp, "rb").read()
    b = io.open(_sp, "rb").read()
    check("the two copies are byte-identical (no stale studio copy)", a == b,
          "%d vs %d bytes" % (len(a), len(b)))

print("\n2. only the two reworked styles are switched on")
for sid in ("cinematic", "bedtime"):
    p = EX.plan(sid)
    check("%s has a live plan (update #3 rework)" % sid, bool(p),
          p and "build %+.2f dB / beat %+.2f dB / ease %+.2f dB"
          % (p["swell_db"], p["beat_db"], p["ease_db"]))
off = [s for s in ("natural", "storytelling", "novel", "documentary", "trailer",
                   "audiobook", "news", "explainer", "thriller", "meditation",
                   "inner_monologue", "sad_romantic") if EX.plan(s)]
check("every other style is left alone", not off, off)
check("the off rows are still written down (so they can be switched on)",
      len(EX.EXPRESS) >= 8, "%d rows in the table" % len(EX.EXPRESS))
check("an unknown / plain style is a no-op", EX.plan("") is None
      and EX.plan("not-a-style") is None)
check("the caps exist and are enforced",
      EX.SWELL_CAP_DB <= 2.0 and EX.BEAT_CAP_DB <= 1.0
      and min(p["ease_db"] for p in (EX.plan("cinematic"), EX.plan("bedtime")))
      >= EX.EASE_CAP_DB,
      "build<=%.1f beat<=%.1f ease>=%.1f" % (EX.SWELL_CAP_DB, EX.BEAT_CAP_DB,
                                             EX.EASE_CAP_DB))
check("the plan refuses to swallow a too-short line",
      EX.plan("cinematic")["min_words"] >= 4, EX.plan("cinematic")["min_words"])

if np is None:
    print("\n(numpy missing — the DSP checks below are skipped)")
    print("\nexpress: %d passed, %d failed" % (len(OK), len(FAIL)))
    sys.exit(1 if FAIL else 0)

rate = 24000
print("\n3. the performance inside one sentence")
t = np.arange(int(rate * 4.0), dtype=np.float32) / rate
# a sentence-ish signal: three words, the middle one accented, then a tail
env = np.zeros_like(t)
for a, b, g in ((0.15, 1.05, 0.45), (1.25, 2.05, 1.0), (2.25, 3.30, 0.5)):
    s = t[int(a * rate):int(b * rate)]
    env[int(a * rate):int(b * rate)] = g * (0.75 + 0.25 * np.sin(2 * np.pi * 4.5 * s))
tone = sum((1.0 / k) * np.sin(2 * np.pi * 150.0 * k * t) for k in (1, 2, 3, 4, 5))
# …plus a presence-band ingredient, so the 2.2–5.2 kHz lift is measurable
# (a bare tone has nothing up there and would score 0 on both sides)
rng = np.random.default_rng(4)
air = rng.normal(0.0, 1.0, t.size).astype(np.float32)
sp_air = np.fft.rfft(air)
f_air = np.fft.rfftfreq(t.size, 1.0 / rate)
sp_air[(f_air < 2600.0) | (f_air > 4600.0)] = 0.0
air = np.fft.irfft(sp_air, n=t.size).astype(np.float32)
air = air / (float(np.max(np.abs(air))) or 1.0) * 0.35
voice = ((tone * 0.9 + air) * env).astype(np.float32) * 0.25


def db_env(x, hop_ms=20.0):
    hop = max(1, int(rate * hop_ms / 1000.0))
    n = int(np.ceil(x.size / float(hop)))
    pad = n * hop - x.size
    y = np.concatenate([x, np.zeros(pad, np.float32)]) if pad else x
    e = np.sqrt(np.mean(y.reshape(n, hop).astype(np.float64) ** 2, axis=1))
    return e, hop


def presence_share(x):
    n = min(x.size, 1 << 18)
    sp = np.abs(np.fft.rfft(x[:n] * np.hanning(n).astype(np.float32))) ** 2
    f = np.fft.rfftfreq(n, 1.0 / rate)
    return float(sp[(f >= 2200) & (f <= 5200)].sum() / (sp.sum() + 1e-12))


def f0_hz(x):
    n = min(x.size, 1 << 16)
    seg = x[:n] * np.hanning(n).astype(np.float32)
    sp = np.abs(np.fft.rfft(seg))
    f = np.fft.rfftfreq(n, 1.0 / rate)
    m = (f > 80.0) & (f < 400.0)
    return float(f[m][int(np.argmax(sp[m]))])


st = {}
cin = EX.expressize(voice.copy(), rate=rate, style="cinematic", index=0,
                    words=9, stats=st)
check("cinematic really changes the line", not np.array_equal(cin, voice))
check("…and it reports what it did", st.get("style") == "cinematic"
      and "swell_db" in st and "ease_db" in st,
      "%s" % {k: st[k] for k in ("swell_db", "ease_db", "beat_s")})
check("the length is untouched (nothing is time-stretched)",
      cin.shape == voice.shape, "%s vs %s" % (cin.shape, voice.shape))
check("no clipping", float(np.max(np.abs(cin))) <= 0.981,
      "peak %.3f" % float(np.max(np.abs(cin))))
check("finite, no NaN", bool(np.isfinite(cin).all()))
check("THE PITCH IS UNTOUCHED (same speaker, only delivery)", 
      abs(f0_hz(cin) - f0_hz(voice)) < 2.0,
      "%.1f Hz -> %.1f Hz" % (f0_hz(voice), f0_hz(cin)))
check("deterministic (same line, same place -> same audio)",
      bool(np.array_equal(cin, EX.expressize(voice.copy(), rate=rate,
                                             style="cinematic", index=0,
                                             words=9))))
eb, _ = db_env(voice)
ec, _ = db_env(cin)
# the emphasis beat is lifted against the rest of the sentence
beat = int(st["beat_s"] / 0.02)
body_slice = slice(int(len(eb) * 0.92), int(len(eb) * 0.99))
lift_now = 20 * float(np.log10((ec[beat] + 1e-9) / (ec[body_slice].mean() + 1e-9)))
lift_before = 20 * float(np.log10((eb[beat] + 1e-9) / (eb[body_slice].mean() + 1e-9)))
check("the emphasis beat is lifted against the rest of the sentence",
      lift_now > lift_before + 0.15,
      "%+.1f dB -> %+.1f dB over the body" % (lift_before, lift_now))
# the end of the sentence eases away — measured on the last words, not on the
# silence after them
def tail_vs_body(x):
    e, hop = db_env(x)
    loud = e > 0.05 * e.max()
    last = int(np.where(loud)[0][-1]) if loud.any() else len(e) - 1
    tail = slice(max(0, last - 8), max(1, last))
    body = slice(int(len(e) * 0.45), int(len(e) * 0.65))
    return 20 * float(np.log10((e[tail].mean() + 1e-9) / (e[body].mean() + 1e-9)))


drop, drop0 = tail_vs_body(cin), tail_vs_body(voice)
check("the sentence eases away at the end (that is the 'trailing off')",
      drop < drop0 - 0.4, "%.1f dB -> %.1f dB vs its body" % (drop0, drop))
check("the presence band is lifted (closer and clearer, not brighter)",
      presence_share(cin) > presence_share(voice) * 1.05,
      "%.4f -> %.4f" % (presence_share(voice), presence_share(cin)))

bed = EX.expressize(voice.copy(), rate=rate, style="bedtime", index=1, words=9)
check("Bedtime gets its own, gentler performance",
      not np.array_equal(bed, cin) and bed.shape == voice.shape)
check("Bedtime adds no brightness (a whisper must not turn into a hiss)",
      abs(presence_share(bed) - presence_share(voice)) < 0.02,
      "%.4f vs %.4f" % (presence_share(voice), presence_share(bed)))

plain = EX.expressize(voice.copy(), rate=rate, style="natural", index=0, words=9)
check("a style with no plan comes back untouched", bool(np.array_equal(plain, voice)))
short = EX.expressize(voice[:int(0.2 * rate)].copy(), rate=rate,
                      style="cinematic", index=0, words=2)
check("a too-short line is handed back untouched",
      bool(np.array_equal(short, voice[:int(0.2 * rate)])))

print("\n4. the rendered paths really call the expressive stage")
srv = io.open(os.path.join(ROOT, "sonora", "server.py"), encoding="utf-8").read()
nar = io.open(os.path.join(HERE, "narration.py"), encoding="utf-8").read()
_sn = io.open(os.path.join(ROOT, "sonora", "narration.py"), encoding="utf-8").read()
check("the studio applies it per line (server.py)",
      "_express_stage" in srv and "EX.expressize" in srv
      and srv.count("arr = _express_stage(arr, plan[i], i)") == 1)
check("the batch renderer applies it per sentence (narration.render_styled)",
      "_EX.expressize" in nar and "_EX.expressize" in _sn)
check("it runs after the whisper stage (the breath is shaped, not the reverse)",
      srv.index("_whisper_stage(arr, plan[i], i)")
      < srv.index("_express_stage(arr, plan[i], i)"))
check("it never runs for a line it has no plan for",
      "if p is None:\n        return arr" in io.open(_pp, encoding="utf-8").read())

print("\nexpress: %d passed, %d failed" % (len(OK), len(FAIL)))
for f in FAIL:
    print("  FAILED:", f)
sys.exit(1 if FAIL else 0)
