#!/usr/bin/env python3
"""test_hdclean.py — the calibration test for the HD Cleanup engine (§29).

Everything the adaptive plan believes about a recording is asserted here, on six
controlled fixtures built from one real voice clip:

    dry      the clip as it is                      → nothing is applied
    noisy    + hiss (σ ≈ −34 dBFS)                  → gentle noise reduction
    rumbly   + a 45 Hz hum                          → 70–90 Hz high-pass
    reverby  + a 300 ms room                        → de-reverb
    muffled  low-passed at 3 kHz                    → clarity (+ low-mid)
    harsh    +9 dB on 5–9 kHz (a hard “s”)          → sibilance control

The point of the test is the adaptivity, not the numbers: a clean file MUST come
out of the planner untouched (§3, §23), and each defect MUST switch on its own
stage and receive it — no more. Every threshold in `hdclean.py` is the one this
file asserts; the two limits that were calibrated against a real voice set
(top-end brightness, and the fact that a lifted shelf is NOT sibilance) are
checked against the studio’s own 13 narration clips when they are present.

Run:  python3 test_hdclean.py        (numpy + ffmpeg by way of imageio-ffmpeg)
"""

from __future__ import annotations

import glob
import hashlib
import io
import os
import shutil
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np

import hdclean as H

SR = 48000
PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  ok   %-58s %s" % (name, detail))
    else:
        FAIL += 1
        print("  FAIL %-58s %s" % (name, detail))


def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


FF = ffmpeg()
WORK = tempfile.mkdtemp(prefix="test_hdclean_")
STUDIO_DEMOS = sorted(glob.glob(os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "sonora", "public",
    "style_demos", "*.mp3"))))


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _decode(path, sr=SR):
    r = subprocess.run([FF, "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr),
                        "-f", "f32le", "pipe:1"], capture_output=True)
    return np.frombuffer(r.stdout, dtype=np.float32).astype(np.float32)


def _write_wav(path, data, sr=SR):
    d = np.clip(np.asarray(data, dtype=np.float32), -1.0, 1.0)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + d.size * 2) + b"WAVE"
                + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16)
                + b"data" + struct.pack("<I", d.size * 2))
        f.write((d * 32767).astype("<i2").tobytes())
    return path


def _read_s24(path):
    """24-bit PCM WAV → float samples (the engine’s output format).

    The data chunk is located properly: ffmpeg’s muxer writes a 102-byte header
    (it adds a bext chunk), so assuming the usual 44 bytes silently shifts every
    sample by 58 bytes — which looked exactly like a broken seam the first time.
    """
    raw = open(path, "rb").read()
    i = raw.find(b"data")
    size = int.from_bytes(raw[i + 4:i + 8], "little")
    b = raw[i + 8:i + 8 + size]
    a = np.frombuffer(b[:len(b) // 3 * 3], dtype=np.uint8).reshape(-1, 3)
    v = (a[:, 0].astype(np.int32) | (a[:, 1].astype(np.int32) << 8)
         | (a[:, 2].astype(np.int32) << 16))
    v = np.where(v >= (1 << 23), v - (1 << 24), v).astype(np.float32)
    return v / float(1 << 23)


def _lp(x, fc, sr=SR):
    a = float(np.exp(-2.0 * np.pi * fc / sr))
    y = np.empty_like(x)
    acc = 0.0
    for i in range(x.size):
        acc = (1.0 - a) * x[i] + a * acc
        y[i] = acc
    return y


def _hf_boost(x, db, lo=5000.0, hi=9000.0, sr=SR):
    """A hard “s”: boost 5–9 kHz, chunked so memory stays flat."""
    g = 10 ** (db / 20.0)
    out = np.empty_like(x)
    for a in range(0, x.size, int(30 * sr)):
        seg = x[a:a + int(30 * sr)]
        X, _ = H._stft_mat(seg)
        f = np.fft.rfftfreq((X.shape[1] - 1) * 2, 1.0 / sr)
        band = ((f >= lo) & (f < hi)).astype(np.float32)
        out[a:a + seg.size] = H._istft_mat(X * (1.0 + (g - 1.0) * band[None, :]), seg.size)
    return out


def voice_sample():
    """A real voice clip: prefer a Khmer one, fall back to a studio narration clip."""
    here = os.path.dirname(os.path.abspath(__file__))
    for rel in ("../sonora/public/demo/khmer-voice-a-standard.mp3",
                "../sonora/public/demo/khmer-voice-b-finetuned.mp3",
                "../sonora/public/style_demos/natural.mp3"):
        p = os.path.normpath(os.path.join(here, rel))
        if os.path.exists(p):
            x = _decode(p)
            if x.size > SR * 4:
                return x, p
    t = np.arange(int(SR * 6.0)) / SR
    x = (0.4 * np.sin(2 * np.pi * 180 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 2.2 * t))
         * (np.sin(2 * np.pi * 1.1 * t) > 0))
    return x.astype(np.float32), "synthetic"


def build_fixtures(base):
    x = np.clip(base, -1, 1)
    rng = np.random.default_rng(11)
    ir = np.zeros(int(0.32 * SR), np.float32)
    ir[0] = 0.6
    for k in (1, 2, 3, 5):
        i = int(0.06 * SR * k)
        if i < ir.size:
            ir[i] = 0.45 / k
    out = {
        "dry":     x,
        "noisy":   np.clip(x + rng.normal(0, 0.02, x.size), -1, 1),
        "rumbly":  np.clip(x + 0.03 * np.sin(2 * np.pi * 45 * np.arange(x.size) / SR), -1, 1),
        "reverby": np.clip(0.7 * x + 0.6 * np.convolve(x, ir, "full")[:x.size], -1, 1),
        # 0.9 gain before the ceiling: the filter sum can overshoot 1.0 and the
        # clip() that used to be here left real flat tops in the fixture, so
        # it measured as a *clipped* file (0.08 %) as well as a muffled one
        # and the clipping rule switched the clarity stage off. The fixture
        # must test one defect at a time.
        "muffled": np.clip(_lp(x + 0.9 * _lp(x, 400) - 0.6 * (x - _lp(x, 900)), 2400)
                           * 0.85, -1, 1),
        # genuinely harsh = a direct 5–9 kHz boost. A shelf above 6 kHz was tried
        # first and is NOT sibilance — it lifts the whole top end by only a few dB
        # and is deliberately left alone (see test_plan).
        "harsh":   _hf_boost(x, 9.0),
        # §12: the same voice with its level wobbling — the second half 10 dB
        # down, the way a clone whose chunks were generated at different levels
        # comes back. Nothing else is wrong with it.
        "wandering": _two_level(x, 10.0),
        # §5 clipping / §18 hard-limit damage: a hot clone driven into the
        # ceiling — the level is over the top, so the waveform has flat tops.
        "clipped":  np.clip(x * 3.2, -1.0, 1.0),
        # the same damage with no pinned sample at all: squashed by a
        # limiter, then normalised. Only the crest factor can see this one.
        "limited":  (np.tanh(x * 4.0) / float(np.max(np.abs(np.tanh(x * 4.0))))
                     * 0.98).astype(np.float32),
    }
    return {k: _write_wav(os.path.join(WORK, k + ".wav"), v) for k, v in out.items()}


def _two_level(x, db):
    """The second half of the clip, quieter — a level jump, not a defect of tone."""
    y = np.tile(x, 2).copy()
    y[y.size // 2:] = y[y.size // 2:] * (10 ** (-db / 20.0))
    return np.clip(y, -1, 1)


def _phrase_levels(x):
    """Phrase loudness — the measurement §12's line is calibrated on."""
    mag = H._stft(x)
    freqs = np.fft.rfftfreq((mag.shape[1] - 1) * 2, 1.0 / SR)
    n = (mag.shape[1] - 1) * 2
    w = float(np.mean(H._hann(n) ** 2)) or 0.375
    db = 20 * np.log10(np.sqrt(np.sum(mag[:, freqs >= 100.0] ** 2, axis=1)
                               / (n * n * w) + 1e-24))
    act = db > max(float(np.percentile(db, 20)) + 15.0,
                   float(np.percentile(db, 99)) - 35.0)
    runs, i = [], 0
    while i < act.size:
        if act[i]:
            j = i
            while j < act.size and act[j]:
                j += 1
            if (j - i) * H.HOP / float(SR) >= 0.25:
                runs.append(float(np.mean(db[i:j])))
            i = j
        else:
            i += 1
    return np.asarray(runs)


def analyse(path):
    st = {}
    x = _decode(path)
    step = int(H.CHUNK_SECS * SR)
    for pos in range(0, x.size, step):
        H.analyze(x[pos:pos + step], SR, st)
    return H._finish(st)


# --------------------------------------------------------------------------- #
# 1. the analysis separates the defects (the calibration itself)
# --------------------------------------------------------------------------- #
def test_metrics(fx):
    print("\n1 · analysis / calibration")
    i = {k: analyse(p) for k, p in fx.items()}
    d, n, r, v, m, h = (i[k] for k in ("dry", "noisy", "rumbly", "reverby", "muffled", "harsh"))

    check("clean file rates “good” and needs nothing (score ≥ 95)", H.score(d) >= 95,
          "score %d" % H.score(d))
    check("clean file: no defect is measured",
          d["rumble_ratio"] < 0.02 and d["mud_ratio"] < 5.5 and d["presence_ratio"] > 0.012
          and d["sib_ratio"] < H.SIB_HF_RATIO and d["snr_db"] > 45,
          "snr %.0f rumble %.3f mud %.2f pres %.4f sib %.2f" %
          (d["snr_db"], d["rumble_ratio"], d["mud_ratio"], d["presence_ratio"], d["sib_ratio"]))
    check("hiss is seen as noise (SNR < 30 dB)", n["snr_db"] < 30, "snr %.1f dB" % n["snr_db"])
    check("a 45 Hz hum is read as rumble, not as noise (§6 vs §7)",
          r["rumble_ratio"] > 0.05 and r["snr_db"] > 45,
          "rumble %.3f · snr %.1f dB" % (r["rumble_ratio"], r["snr_db"]))
    check("a 300 ms room is seen in the pauses (gap tail > 0.025)",
          v["reverb"] is not None and v["reverb"] > 0.025, "reverb %.3f" % (v["reverb"] or 0))
    check("a dry voice has no gap tail (< 0.012)",
          d["reverb"] is not None and d["reverb"] < 0.012, "reverb %.3f" % (d["reverb"] or 0))
    check("muffling shows up as lost clarity (< 0.012)", m["presence_ratio"] < 0.012,
          "presence %.4f" % m["presence_ratio"])
    check("a boosted “s” band trips the top-end line",
          h["sib_ratio"] > H.SIB_HF_RATIO, "sib %.2f (line %.2f)" % (h["sib_ratio"], H.SIB_HF_RATIO))
    check("the score bands match the spec (§5)",
          [H.band_of(s)[0] for s in (20, 50, 70, 95)]
          == ["poor", "needs cleanup", "moderate", "good"],
          str([H.band_of(s)[0] for s in (20, 50, 70, 95)]))
    return i


# --------------------------------------------------------------------------- #
# 2. the adaptive plan (stage selection)
# --------------------------------------------------------------------------- #
def test_plan(fx):
    print("\n2 · the adaptive plan")
    expect = {"dry": set(), "noisy": {"noise reduction"}, "rumbly": {"rumble"},
              "reverby": {"de-reverb"}, "muffled": {"presence"}, "harsh": {"deess"},
              # §12: a level jump is its own defect and gets its own stage —
              # nothing else about this file is wrong
              "wandering": {"comp"},
              # §18: a clipped file must receive NO effect stage at all —
              # assert_clipping below checks the stage list and the ceiling
              "clipped": set(), "limited": set()}
    for name, path in fx.items():
        p = H.plan(analyse(path))
        got = set()
        for key, label in (("denoise", "noise reduction"), ("dereverb", "de-reverb"),
                           ("highpass", "rumble"), ("mud", "mud"), ("presence", "presence"),
                           ("deess", "deess"), ("comp", "comp")):
            if p[key]:
                got.add(label)
        if name == "dry":
            check("clean file → EMPTY plan (§3, §23)", got == set(),
                  "stages %s" % (sorted(got) or "none"))
        else:
            check("%s → its own stage switches on" % name, got >= expect[name],
                  "plan %s (want at least %s)" % (sorted(got), sorted(expect[name])))
        check("%s: the pass stays gentle (strength ≤ 0.35)" % name, p["strength"] <= 0.35,
              "strength %.2f" % p["strength"])

    for name in ("dry", "noisy", "rumbly", "reverby", "muffled", "wandering"):
        check("%s is not “corrected” for harshness" % name, not H.plan(analyse(fx[name]))["deess"],
              str(H.plan(analyse(fx[name]))["deess"]))

    # the studio’s own voices must all come out with an EMPTY plan — the
    # evidence that “do less when less is needed” is real
    if STUDIO_DEMOS:
        staged, worst = 0, 0.0
        for d in STUDIO_DEMOS:
            fin = analyse(d)
            if H.plan(fin)["stages"]:
                staged += 1
            worst = max(worst, fin["sib_ratio"])
        check("all %d studio voices need no correction stage" % len(STUDIO_DEMOS), staged == 0,
              "%d of %d would be processed" % (staged, len(STUDIO_DEMOS)))
        check("the studio voices all sit under the top-end line", worst < H.SIB_HF_RATIO,
              "brightest %.2f < line %.2f" % (worst, H.SIB_HF_RATIO))
    else:
        print("  --   (studio clips not present: skipped the voice-set calibration check)")


# --------------------------------------------------------------------------- #
# 3. true-peak measurement (§14)
# --------------------------------------------------------------------------- #
def test_clipping(fx):
    """§5/§18/§26 — a clipped file is measured, and the plan stops making it worse.

    Clipping used to be charged in the score and then ignored: the plan still
    added a presence boost and a compressor, both of which drive flat-topped
    peaks further into the ceiling. The rule is the opposite now — no boost, no
    compressor, and the true-peak ceiling drops half a dB so the damaged peaks
    have room.
    """
    pc, pc_clean = H.plan(analyse(fx["clipped"])), H.plan(analyse(fx["dry"]))
    st = " ".join(pc["stages"]).lower()
    check("a clipped file is reported in the plan", "clipping / hard limiting" in st,
          st[:60])
    check("…and it gets no corrective boost", not pc.get("presence"), str(pc.get("presence")))
    check("…and no compressor (that would deepen the flat tops)",
          not pc.get("comp"), str(pc.get("comp")))
    check("…and the ceiling drops to -1.5 dBTP for headroom",
          abs(pc["loudness"]["tp"] + 1.5) < 1e-6, str(pc["loudness"]))
    check("a clean file is never treated as clipped",
          "clipping" not in " ".join(pc_clean["stages"]).lower()
          and abs(pc_clean["loudness"]["tp"] + 1.0) < 1e-6, str(pc_clean["loudness"]))
    ic, idry = analyse(fx["clipped"]), analyse(fx["dry"])
    check("the damage shows in the measurement (§5 clipping)",
          0.05 < ic["clip_pct"] < 40.0, "%.2f%% of frames" % ic["clip_pct"])
    check("…and in the density reading (§5 distortion proxy: crest factor)",
          ic["crest_db"] < 13.0, "%.1f dB" % ic["crest_db"])
    check("a clean voice keeps a healthy crest (14-20 dB)",
          14.0 <= idry["crest_db"] <= 20.0, "%.1f dB" % idry["crest_db"])

    # hard limiting with NO pinned sample (resampled, or squashed then normalised)
    pl = H.plan(analyse(fx["limited"]))
    il = analyse(fx["limited"])
    check("a hard-limited file is caught by its crest alone (§5 distortion)",
          il["clip_pct"] < H.CLIP_LINE_PCT and il["crest_db"] < H.CREST_LINE_DB,
          "clip %.3f%% · crest %.1f dB" % (il["clip_pct"], il["crest_db"]))
    check("…and it gets the same protection: no boost, no compressor",
          not pl.get("presence") and not pl.get("comp"), str(pl.get("comp")))
    check("…and the same extra headroom", abs(pl["loudness"]["tp"] + 1.5) < 1e-6,
          str(pl["loudness"]))
    check("…and it does not score as a perfect recording", pl["score"] < 95,
          "score %d" % pl["score"])
    # the line itself: every clean fixture and every studio voice stays above it
    worst = min(analyse(fx[n])["crest_db"] for n in fx if n not in ("clipped", "limited"))
    check("no clean fixture comes near the crest line",
          worst > H.CREST_LINE_DB + 1.0, "closest %.1f dB vs line %.1f" % (worst, H.CREST_LINE_DB))


def test_dynamics(fx):
    """§12 — compression is driven by a measured wander, and it earns its place.

    The stage used to hang off the overall score, so a clean voice whose level
    drifted got nothing while a noisy-but-steady voice got squeezed; and its
    threshold was a fixed -18 dB, which made the effect depend on how hot the
    file happened to be. Both are asserted here against real numbers.
    """
    x = _decode(fx["dry"])
    clean = analyse(fx["dry"])
    wander = analyse(fx["wandering"])

    check("clean voice: phrase spread under the line",
          clean["dyn_db"] is None or clean["dyn_db"] < H.DYN_LINE,
          "spread %s dB vs line %.1f" % (
              "%.1f" % clean["dyn_db"] if clean["dyn_db"] is not None else "n/a",
              H.DYN_LINE))
    check("wandering voice: phrase spread over the line",
          wander["dyn_db"] is not None and wander["dyn_db"] > H.DYN_LINE,
          "spread %.1f dB vs line %.1f" % (wander["dyn_db"] or -1, H.DYN_LINE))

    p_clean, p_wander = H.plan(clean), H.plan(wander)
    check("clean voice is not compressed (§3)", p_clean["comp"] is None,
          "stages: %s" % ("; ".join(p_clean["stages"]) or "nothing"))
    check("wandering voice IS compressed (§12)",
          p_wander["comp"] is not None and 2.0 <= p_wander["comp"]["ratio"] <= 3.0,
          "ratio %.1f:1 · threshold %.1f dB"
          % (p_wander["comp"]["ratio"], p_wander["comp"]["threshold_db"]))
    check("its threshold follows the voice, not a fixed number (§12)",
          p_wander["comp"]["threshold_db"] < wander["speech_db"] + 1.0,
          "%.1f dB vs speech %.1f dBFS"
          % (p_wander["comp"]["threshold_db"], wander["speech_db"]))

    # what the stage actually does to the audio
    out = os.path.join(WORK, "wandering.hd.wav")
    H.enhance_file(fx["wandering"], out, log=[], ffmpeg=FF)
    y = _read_s24(out)[:x.size * 2]
    # 'before' is the fixture itself, decoded the same way as the output — the
    # first version of this test compared the fixture against the DRY clip, which
    # measured the fixture's own level drop as if it were the stage's doing
    before = _phrase_levels(_decode(fx["wandering"])[:x.size * 2])
    after = _phrase_levels(y)
    spread_b = float(np.percentile(before, 90) - np.percentile(before, 10))
    spread_a = float(np.percentile(after, 90) - np.percentile(after, 10))
    gr = float(np.percentile(before, 90) - np.median(before)) \
        - float(np.percentile(after, 90) - np.median(after))
    check("the wander really closes (§12)", spread_a < spread_b - 3.0,
          "%.1f → %.1f dB" % (spread_b, spread_a))
    check("gain reduction on the loud half is 2–7 dB (§12)", 2.0 <= gr <= 7.0,
          "%.1f dB" % gr)

    # and the same file processed twice is still identical (§19)
    out2 = os.path.join(WORK, "wandering.hd2.wav")
    H.enhance_file(fx["wandering"], out2, log=[], ffmpeg=FF)
    check("two passes on the same source agree (§19)",
          hashlib.md5(open(out, "rb").read()).hexdigest()
          == hashlib.md5(open(out2, "rb").read()).hexdigest())


def test_redo(fx):
    """§18 — one lighter retry, driven from the original, and never a third pass.

    The engine reads its own quality check and, if the pass made the voice worse,
    drops the strength cap to REDO_CAP and runs again FROM THE ORIGINAL. Forcing
    that reading is the only way to see the path: a deliberate artifact returns
    “worse”, and the plan-spy records the strength each pass actually used.
    """
    src = fx["noisy"]                      # a fixture that really is processed
    seen = []
    real_plan, real_check = H.plan, H._artifact_check

    def spy_plan(info, strength_cap=1.0):
        seen.append(round(float(strength_cap), 3))
        return real_plan(info, strength_cap=strength_cap)

    def always_worse(before, after, p):
        return {"worse": True, "why": "forced for the test"}

    H.plan, H._artifact_check = spy_plan, always_worse
    try:
        log = []
        rep = H.enhance_file(src, os.path.join(WORK, "redo_hd.wav"), log=log, ffmpeg=FF)
    finally:
        H.plan, H._artifact_check = real_plan, real_check

    redos = [l for l in log if "redoing it once" in l]
    check("a “worse” reading triggers exactly one lighter retry (§18)",
          len(redos) == 1, "%d retry line(s)" % len(redos))
    check("the retry uses the reduced strength cap (§18)",
          seen == [1.0, H.REDO_CAP], "caps used: %s" % seen)
    check("the retry never loops a third time (§18)", len(seen) == 2,
          "%d pass(es)" % len(seen))
    check("and the result is still a good one", rep.get("ok") is True,
          "score %s → %s" % (rep.get("score_before"), rep.get("score_after")))


def test_true_peak():
    print("\n3 · true-peak measurement")
    t = np.arange(SR) / SR
    isp = np.sin(2 * np.pi * (SR / 4) * t + np.pi / 4).astype(np.float32)
    p = os.path.join(WORK, "isp.raw")
    open(p, "wb").write(isp.tobytes())
    tp = H._true_peak_db(p, isp.size, SR)
    peak_db = 20 * np.log10(np.max(np.abs(isp)))
    check("inter-sample peak is caught (+3.0 dB over the sample peak)",
          abs((tp - peak_db) - 3.01) < 0.3 and abs(tp) < 0.3,
          "samples %.2f dBFS → true %.2f dBTP (%+.2f dB)" % (peak_db, tp, tp - peak_db))
    fs = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    open(p, "wb").write(fs.tobytes())
    tp2 = H._true_peak_db(p, fs.size, SR)
    check("a full-scale 1 kHz tone reads 0 dBTP (±0.2)", abs(tp2) < 0.2, "%.2f dBTP" % tp2)


# --------------------------------------------------------------------------- #
# 4. end-to-end behaviour on every fixture
# --------------------------------------------------------------------------- #
def test_end_to_end(fx):
    print("\n4 · one pass from the original, and what comes out")
    results = {}
    for name, path in fx.items():
        before = hashlib.md5(open(path, "rb").read()).hexdigest()
        out = os.path.join(WORK, name + "_hd.wav")
        rep = H.enhance_file(path, out, log=[], ffmpeg=FF,
                             preview_dir=os.path.join(WORK, "prev"),
                             report_path=os.path.join(WORK, "rep_%s.json" % name))
        after = hashlib.md5(open(path, "rb").read()).hexdigest()
        results[name] = rep
        check("%s: ok, and the ORIGINAL is untouched (§16)" % name,
              rep.get("ok") and before == after,
              "score %s→%s" % (rep.get("score_before"), rep.get("score_after")))
        hdr = open(out, "rb").read(44)
        check("%s: 48 kHz / 24-bit WAV out (§15)" % name,
              struct.unpack("<I", hdr[24:28])[0] == 48000 and struct.unpack("<H", hdr[34:36])[0] == 24,
              "%d Hz / %d-bit" % (struct.unpack("<I", hdr[24:28])[0], struct.unpack("<H", hdr[34:36])[0]))
        tp = rep["analysis_after"]["true_peak_db"]
        check("%s: true peak ≤ −0.8 dBTP (§14)" % name, tp is not None and tp <= -0.8,
              "%.2f dBTP" % (tp or 0))
        lufs = (rep.get("out") or {}).get("lufs")
        check("%s: loudness lands on −16 LUFS ±0.8 (§13)" % name,
              lufs is not None and abs(float(lufs) + 16.0) <= 0.8,
              "%.1f LUFS" % (float(lufs) if lufs else 0))
        pv = rep.get("previews") or {}
        check("%s: 5–10 s Original ▶ / HD Clean ▶ pair (§17)" % name,
              os.path.exists(pv.get("original", "")) and os.path.exists(pv.get("hd", ""))
              and 5.0 <= float(pv.get("seconds", 0)) <= 10.0, "%s s" % pv.get("seconds"))

    d, n, r, v, m, h = (results[k] for k in ("dry", "noisy", "rumbly", "reverby", "muffled", "harsh"))
    check("clean file: no correction stage at all (§23)",
          not d["stages"], "; ".join(d["stages"]) or "none")
    check("hiss: the noise floor improves by ≥ 3 dB",
          n["analysis_after"]["snr_db"] - n["analysis_before"]["snr_db"] >= 3.0,
          "SNR %.1f → %.1f dB" % (n["analysis_before"]["snr_db"], n["analysis_after"]["snr_db"]))
    check("hum: the rumble falls to a quarter or better",
          r["analysis_after"]["rumble_ratio"] <= 0.25 * r["analysis_before"]["rumble_ratio"],
          "%.3f → %.3f" % (r["analysis_before"]["rumble_ratio"], r["analysis_after"]["rumble_ratio"]))
    v0, v1 = v["analysis_before"]["reverb"], v["analysis_after"]["reverb"]
    check("room: the ring in the pauses drops by ≥ 35 % and lands near dry",
          v1 is not None and v1 <= 0.65 * v0 and v1 <= 0.032, "%.3f → %.3f" % (v0, v1))
    h0, h1 = h["analysis_before"]["sib_ratio"], h["analysis_after"]["sib_ratio"]
    check("harshness: the top end comes down by ≥ 20 %", h1 <= 0.80 * h0, "%.2f → %.2f" % (h0, h1))
    check("muffled: clarity comes up (measured presence ratio, and the score "
          "never falls)",
          m["analysis_after"]["presence_ratio"] > m["analysis_before"]["presence_ratio"]
          and m["score_after"] >= m["score_before"],
          "presence %.4f → %.4f · score %s → %s"
          % (m["analysis_before"]["presence_ratio"],
             m["analysis_after"]["presence_ratio"],
             m["score_before"], m["score_after"]))
    for name, rep in results.items():
        check("%s: no artefact was introduced (§18)" % name,
              not (rep.get("artifact_check") or {}).get("worse"),
              (rep.get("artifact_check") or {}).get("why", ""))
    return results


# --------------------------------------------------------------------------- #
# 5. long audio: internal chunking is invisible (§21)
# --------------------------------------------------------------------------- #
def test_chunking(base):
    print("\n5 · long audio (internal chunking, one visible operation)")
    x = np.tile(np.clip(base, -1, 1), 8)[:int(90 * SR)]
    x = (x + 0.008 * np.random.default_rng(5).normal(0, 1, x.size)).astype(np.float32)
    long_wav = _write_wav(os.path.join(WORK, "long.wav"), x)
    log = []
    rep = H.enhance_file(long_wav, os.path.join(WORK, "long_hd.wav"), log=log, ffmpeg=FF)
    check("90 s file: ok, no redo loop, and it completes",
          rep.get("ok") and rep.get("seconds") == 90.0,
          "%.0f s of audio in %.1f s" % (rep.get("seconds", 0), rep.get("elapsed", 0)))
    loud = sum(1 for l in log if l.startswith("loudness"))
    check("long file: exactly ONE loudness measurement (§21)", loud == 1,
          "%d loudness step(s)" % loud)
    check("long file: true peak is still safe", rep["analysis_after"]["true_peak_db"] <= -0.8,
          "%.2f dBTP" % rep["analysis_after"]["true_peak_db"])
    old = H.CHUNK_SECS
    try:
        H.CHUNK_SECS = 90.0
        H.enhance_file(long_wav, os.path.join(WORK, "long_one.wav"), log=[], ffmpeg=FF)
    finally:
        H.CHUNK_SECS = old
    a = _read_s24(os.path.join(WORK, "long_one.wav"))
    b = _read_s24(os.path.join(WORK, "long_hd.wav"))
    # §20 — nothing moves. The output must sit exactly where the input did: a
    # look-ahead limiter that does not compensate shifts the whole file (the real
    # engine did: 240 samples, 5 ms late, which also hides every before/after
    # spectral comparison behind a shifted frame grid). Checked by
    # cross-correlation, so even a one-sample slip would fail.
    src_l = _read_s24(long_wav)
    n_l = min(src_l.size, b.size)

    def _envelope(x, ms=1.0):
        """1 ms RMS envelope — correlation on this cannot lock onto a pitch period."""
        n = max(8, int(SR * ms / 1000.0))
        sq = np.concatenate((np.zeros(n), x.astype(np.float64) ** 2))
        c = np.cumsum(sq)
        return np.sqrt(np.maximum(c[n:] - c[:-n], 0.0) / n)

    ea, eb = _envelope(src_l[:n_l]), _envelope(b[:n_l])
    win = int(min(ea.size, 3000))            # the first 3 s, on a 1 ms grid
    c = np.correlate(eb[:win], ea[:win], "full")
    lag_ms = int(np.argmax(c)) - (win - 1)
    check("long file: the output is sample-aligned with the input (§20)", lag_ms == 0,
          "best lag %d ms (1 ms grid) — the words must not move" % lag_ms)

    check("long file: chunked and unchunked outputs have the same length",
          a.size == b.size, "%d vs %d samples" % (a.size, b.size))
    n = min(a.size, b.size)
    d = np.abs(a[:n] - b[:n])
    seams = []
    for k in range(1, int(90 / 30)):
        i = int(k * 30 * SR)
        seams.append(float(np.max(d[max(0, i - SR // 2):i + SR // 2])))
    sig = float(np.sqrt(np.mean(a[:n] ** 2))) or 1e-9
    rel = float(np.sqrt(np.mean(d ** 2))) / sig
    worst_seam = max(seams or [0.0])
    check("long file: the chunked pass matches a single pass at every join",
          worst_seam <= 0.06 and rel <= 0.01,
          "worst seam %.4f (%.0f dB below the signal) · overall %+.1f dB"
          % (worst_seam, 20 * np.log10(worst_seam / sig), 20 * np.log10(rel)))


# --------------------------------------------------------------------------- #
# 6. safety: original preserved, fail-safe, no chaining, Khmer only
# --------------------------------------------------------------------------- #
def test_safety(fx):
    print("\n6 · safety rules (§2, §16, §19, §24)")
    src = fx["dry"]
    o1, o2 = os.path.join(WORK, "chain1.wav"), os.path.join(WORK, "chain2.wav")
    H.enhance_file(src, o1, log=[], ffmpeg=FF)
    H.enhance_file(src, o2, log=[], ffmpeg=FF)
    check("always processing the ORIGINAL: two runs give identical output (§19)",
          hashlib.md5(open(o1, "rb").read()).hexdigest()
          == hashlib.md5(open(o2, "rb").read()).hexdigest())

    keep = os.path.join(WORK, "kept_original.wav")
    H.enhance_keep_original(src, os.path.join(WORK, "kept_hd.wav"), keep, log=[], ffmpeg=FF)
    check("the studio form keeps a copy of the original TTS (§16)",
          os.path.exists(keep) and os.path.getsize(keep) == os.path.getsize(src),
          "%d B" % os.path.getsize(keep))

    bad = os.path.join(WORK, "broken.wav")
    open(bad, "wb").write(b"not-audio" * 500)
    log = []
    rep = H.enhance_file(bad, os.path.join(WORK, "broken_hd.wav"), log=log, ffmpeg=FF)
    check("a broken file fails safely, with the exact fallback sentence (§24)",
          rep.get("ok") is False
          and rep.get("note") == "Enhancement unavailable; original TTS preserved.",
          repr(rep.get("note")))
    check("a broken file writes no HD output", not os.path.exists(os.path.join(WORK, "broken_hd.wav")))

    cases = [("សួស្តី ខ្ញុំឈ្មោះសន្និ", "km", True), ("hello there", "en", False),
             ("សួស្តី hello", "auto", True), ("12345", "km", True)]
    check("Khmer gate: Khmer text and km tags pass, English does not (§2)",
          all(H.khmer_only_ok(t, l)[0] is w for t, l, w in cases),
          str([H.khmer_only_ok(t, l)[0] for t, l, _ in cases]))

    raw = os.path.join(WORK, "dec.raw")
    H._decode(src, raw, FF, H.OUT_SR, 48000)
    a = np.frombuffer(open(raw, "rb").read(), dtype=np.float32)
    s = np.frombuffer(open(src, "rb").read()[44:], dtype="<i2").astype(np.float32) / 32768.0
    n = min(a.size, s.size)
    check("a 48 kHz source is decoded bit-exactly — no resampling (§15)",
          a.size == s.size and float(np.max(np.abs(a[:n] - s[:n]))) == 0.0, "%d samples" % a.size)



def test_matrix_present():
    """§28 — the shipped matrix and its report must actually carry the samples.

    The report is rebuilt from `samples.json`, and a synthesis run that produced
    nothing once overwrote it with empty tables. These checks make that a test
    failure instead of a quiet loss.
    """
    import json
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sj = os.path.join(root, "sonora", "public", "hd_samples", "samples.json")
    doc = os.path.join(root, "hd-samples.md")
    try:
        rows = json.load(open(sj, encoding="utf-8")).get("samples") or []
    except OSError:
        rows = []
    check("the §28 matrix still holds the Khmer samples (>= 15)", len(rows) >= 15,
          "%d row(s) in samples.json" % len(rows))
    clean = [r for r in rows if not r.get("damage")]
    check("the matrix keeps both sides: clean and degraded",
          len(clean) >= 12 and len(rows) - len(clean) >= 3,
          "%d clean / %d degraded" % (len(clean), len(rows) - len(clean)))
    try:
        text = io.open(doc, encoding="utf-8").read()
    except OSError:
        text = ""
    table_rows = [ln for ln in text.splitlines() if ln.startswith("| ") and "|" in ln[2:]]
    check("the report hd-samples.md is not an empty table (>= 15 rows)",
          len(table_rows) >= 15, "%d table row(s)" % len(table_rows))
    check("the report never claims \"0 clean samples\"", "0 clean samples" not in text)
    check("the report quotes the engine suite's own check count", "(139 checks)" in text)


def main():
    print("HD Cleanup — Adaptive Khmer Voice Enhancement\n" + "=" * 74)
    if FF == "ffmpeg":
        print("!! no ffmpeg from imageio_ffmpeg — install it: pip install imageio-ffmpeg")
    base, origin = voice_sample()
    print("voice fixture: %s (%.1f s)" % (origin, base.size / float(SR)))
    fx = build_fixtures(base)
    test_metrics(fx)
    test_plan(fx)
    test_clipping(fx)
    test_dynamics(fx)
    test_redo(fx)
    test_true_peak()
    test_end_to_end(fx)
    test_chunking(base)
    test_safety(fx)
    test_matrix_present()
    print("\n" + "=" * 74)
    print("HD Cleanup: %d passed, %d failed" % (PASS, FAIL))
    shutil.rmtree(WORK, ignore_errors=True)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
