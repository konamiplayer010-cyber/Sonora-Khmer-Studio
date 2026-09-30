#!/usr/bin/env python3
"""hdclean.py — Adaptive Khmer Voice Enhancement (the “HD Cleanup” tool).

The contract is the 30-section **HD KHMER VOICE ENHANCEMENT** specification
(see `HD-Cleanup-Khmer.md`). Scope, exactly as asked:

  * it belongs to the **RVC VOICE CLONE** path, and it is **Khmer only**;
  * it runs only when the user switches it on (the studio shows it only when
    the clone is checked);
  * it treats “TTS + enhancement” as ONE pipeline, and the user sees ONE
    operation — no EQ/compressor/denoiser knobs.

HOW IT WORKS (spec §3, §5, §23, §25, §26)

    preserve the original  →  analyse  →  decide (adaptive plan)  →
    ONE pass from the original  →  quality check  →  loudness  →
    true-peak  →  48 kHz / 24-bit WAV

Nothing is applied “because HD is on”: every stage is switched on by the
analysis of the source audio, and its strength comes from a 0–100 quality
score (§5). A clean input is barely touched (§23). The voice is never the
subject of the processing: no pitch shift, no formant change, no re-tuning —
only noise, rumble, reverb, mud, harshness, dynamics and loudness (§4, §27).

Long audio (spec §21) is processed in internal 30 s chunks with an overlap and
a cross-fade, and gets exactly ONE global loudness measurement and ONE final
limiter, so a four-hour book sounds like one operation.

Safety (spec §16, §18, §19, §24)

  * the original TTS audio is never overwritten or deleted;
  * processing always starts from the ORIGINAL, never from an already
    enhanced file;
  * if the quality check says the result is worse, the strength is reduced and
    the pass is repeated ONCE from the original;
  * if anything fails, the original audio is returned untouched and the log
    says “Enhancement unavailable; original TTS preserved.”
"""

from __future__ import annotations

import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
import time

try:
    import numpy as np
except Exception:                                            # pragma: no cover
    np = None

# --------------------------------------------------------------------------- #
# the standard this engine aims at
# --------------------------------------------------------------------------- #
TARGET_LUFS = -16.0          # the studio's loudness standard (Clean & Clear too)
TRUE_PEAK_DBTP = -1.0        # §14
OUT_SR = 48000               # §15 preferred output
OUT_BITS = 24                # §15
PREVIEW_SECS = 8.0           # §17 (5–10 s is enough to hear it)
CHUNK_SECS = 30.0            # §21 internal chunk
OVERLAP_SECS = 0.75          # …with an overlap, so there is no seam
REDO_CAP = 0.4               # §18: the single reduced-strength retry, never twice

#: analysis frame
N_FFT = 1024
HOP = 256

#: §5 — the quality score bands
#: the top end is only touched when it is brighter than every one of the
#: studio’s own voices: they measure 0.28–0.98 on this ratio (13/13, measured),
#: so 1.2 is clear of all of them and only genuinely harsh output is corrected.
SIB_HF_RATIO = 1.2

#: §7 — rumble is a steady low-frequency bed, so it is measured while NOBODY is
#: speaking: a hum is still there in the pauses, a deep voice’s own low end is
#: not. LF band (20–80 Hz) power in the quiet frames ÷ the voice’s body power
#: (300–3000 Hz) in the speech frames. Measured: clean Khmer and English voices
#: ≤ 0.006, a hiss floor 0.010–0.016, a 45 Hz hum 0.20 — and the reading is the
#: same at 24 kHz and 48 kHz. (A speech-frame LF/body ratio was tried first and
#: read 0.11–0.37 on clean Khmer male TTS: it was measuring the voice, not a
#: defect — and a 20–80 Hz band is one bin wide at 48 kHz.)
RUMBLE_LINE = 0.02
#: §8 — 150–350 Hz ÷ 350–1500 Hz. The studio’s own voices sit at 2.9–4.4 and
#: the two Khmer TTS voices at 3.0–13.5, so the line is above a healthy voice’s
#: own low-mid weight; only a real build-up is cut.
MUD_LINE = 7.0
#: §9 — 2–4 kHz ÷ 500–2000 Hz, measured at 48 kHz. The studio’s 13 voices sit at
#: 0.025–0.079 and the Khmer TTS voices at 0.012–0.041 (a deep male voice simply
#: has less 2–4 kHz than a bright English narrator), so the line is set below
#: every healthy voice in both sets: only genuinely dull audio — the muffled
#: fixture reads 0.006 here — gets a lift, and never more than 1.6 dB.
PRESENCE_LINE = 0.008
#: §12 — how much a voice's own phrase levels may wander before gentle
#: compression is justified, as p90-p10 of per-phrase loudness (a phrase is a
#: run of clearly-voiced frames of 0.25 s or more; pauses are not phrases).
#: Measured on 46 healthy files — the 15 Khmer samples and the studio's own 13
#: narration voices — the spread is 4-9.3 dB, so nothing healthy sits near this
#: line. A voice that swells by +-7 dB reads 10.5, a clone whose second half is
#: 10 dB down reads 11.2, a +-10 dB swell reads 14.5. Expressive reads are not
#: touched: what this measures is drift BETWEEN phrases, which is the defect,
#: not the dynamics WITHIN a phrase, which is the performance (§4, §27).
DYN_LINE = 10.0
#: §5 clipping / §18 hard-limit damage. Measured as the share of frames that
#: sit at full scale. Above this the plan stops adding anything that raises a
#: peak and delivers with extra headroom instead (see plan()).
#: Calibrated: a clean voice and the studio's 13 demos read 0.000 %, a
#: low-passed fixture reads 0.083 % (its own filter maths overshoots a
#: handful of samples — not a clipped recording), a hot clone driven 3.2x
#: into the ceiling reads 5.36 % of samples pinned at the ceiling.
#: Calibrated across everything shipped: the studio's 13 demo voices sit at
#: 16.4-17.6 dB and the 15 clean Khmer samples at 15.0-16.1, while a take
#: driven 2x into the ceiling reads 12.5 and 3.2x reads 9.5.
CREST_LINE_DB = 13.5
CLIP_LINE_PCT = 0.02

BANDS = ((40, "poor", "strong corrective cleanup"),
         (60, "needs cleanup", "noticeable cleanup"),
         (80, "moderate", "moderate cleanup"),
         (101, "good", "very light processing"))


def _ffmpeg(explicit=None):
    if explicit:
        return explicit
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _db(x, floor=-120.0):
    return max(floor, 20.0 * math.log10(max(float(x), 1e-12)))


# --------------------------------------------------------------------------- #
# 1. analysis (spec §5)
#
# Every metric below was calibrated on six controlled fixtures (a real Khmer
# clip, and the same clip with hiss / rumble / reverb / muffling / harshness
# added) so that each one separates its own defect from a clean file — see
# `test_hdclean.py`, which asserts exactly that.
# --------------------------------------------------------------------------- #
def _hann(n):
    return np.hanning(n).astype(np.float32)


def _stft(x, n=N_FFT, hop=HOP):
    """Magnitude spectrogram of one chunk (float32)."""
    win = _hann(n)
    if x.size < n:
        x = np.pad(x, (0, n - x.size))
    frames = 1 + (x.size - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(frames)[:, None]
    return np.abs(np.fft.rfft(x[idx] * win, axis=1)).astype(np.float32)


def _frame_rms(x, n=N_FFT, hop=HOP):
    """Frame levels in true dBFS (plain frame RMS, no window)."""
    if x.size < n:
        x = np.pad(x, (0, n - x.size))
    frames = 1 + (x.size - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(frames)[:, None]
    return np.sqrt(np.mean(x[idx].astype(np.float32) ** 2, axis=1) + 1e-18)


def _highpass80(x, sr):
    """One-pole high-pass — used ONLY for metering, so a 45 Hz hum is not
    counted as “noise” by the SNR (§7 handles rumble separately)."""
    a = float(np.exp(-2.0 * np.pi * 80.0 / sr))
    y = np.empty_like(x)
    acc = 0.0
    for i in range(x.size):
        acc = (1.0 - a) * x[i] + a * acc
        y[i] = acc
    return x - y


def _band_power(mag, sr, lo, hi):
    f = np.fft.rfftfreq((mag.shape[1] - 1) * 2, 1.0 / sr)
    m = (f >= lo) & (f < hi)
    return float(np.mean(mag[:, m] ** 2)) if m.any() else 0.0


def _rms_env(x, n):
    """15 ms RMS envelope of a chunk, one pass (cumulative sum, not convolution)."""
    sq = np.concatenate((np.zeros(n, dtype=np.float64), np.asarray(x, dtype=np.float64) ** 2))
    c = np.cumsum(sq)
    env = np.sqrt(np.maximum(c[n:] - c[:-n], 0.0) / n)
    return env[:x.size]


def _gap_tail_ratio(x, sr):
    """How much voice is still ringing in the pauses — the reverb indicator.

    A dry file falls to its noise floor between words; a reverby one keeps
    ringing. Calibrated: a dry TTS clip measures ~0.008, the same clip with a
    300 ms room measures ~0.042. Returns (ratio, gaps_found). When the file is
    noisy there are no clean gaps, so the answer is “not measurable”, and the
    de-reverb stays off (spec §11: never process what you cannot hear).
    """
    n = int(0.015 * sr)
    if x.size < n * 40:
        return None, 0
    e = _rms_env(x, n)
    peak = float(np.max(e)) or 1e-9
    speech = float(np.mean(e[e >= 0.30 * peak])) if (e >= 0.30 * peak).any() else 1e-9
    quiet = e < 0.04 * peak
    runs, i, min_len = [], 0, int(0.25 * sr)
    while i < quiet.size:
        if quiet[i]:
            j = i
            while j < quiet.size and quiet[j]:
                j += 1
            if (j - i) > min_len:
                runs.append((i, j))
            i = j
        else:
            i += 1
    if not runs:
        return None, 0
    t = int(0.12 * sr)
    vals = [float(np.mean(e[a:a + t])) for a, b in runs if (b - a) > t]
    if not vals:
        return None, len(runs)
    return float(np.median(vals)) / speech, len(runs)


def analyze(x, sr, state=None):
    """Everything §5 asks to look at. `state` accumulates across chunks, so a
    long file is measured with flat memory."""
    if np is None:                                           # pragma: no cover
        raise RuntimeError("numpy is required for the HD analysis")
    x = np.asarray(x, dtype=np.float32).reshape(-1)
    mag = _stft(x)
    frame_rms = _frame_rms(x)
    m = min(frame_rms.size, mag.shape[0])
    mag, frame_rms = mag[:m], frame_rms[:m]
    frame_db = 20.0 * np.log10(np.maximum(frame_rms, 1e-9))      # true dBFS

    # Which frames are speech and which are the floor, and the SNR itself, are
    # judged on energy ABOVE 100 Hz only: a 45 Hz hum inflates a broadband
    # reading and would make a clean recording look noisy (§6). Low rumble is
    # measured on its own, by §7.
    # (Parseval) — so the meter is real dBFS and the per-chunk min/max below
    # keep meaning what they say; a raw FFT-unit meter is all positive numbers
    # and silently collapses the floor.
    freqs = np.fft.rfftfreq((mag.shape[1] - 1) * 2, 1.0 / sr)
    _n = max(2, (mag.shape[1] - 1) * 2)
    _win_sq = float(np.mean(_hann(_n) ** 2)) or 0.375
    meter_rms = np.sqrt(np.sum(mag[:, freqs >= 100.0] ** 2, axis=1)
                        / (_n * _n * _win_sq) + 1e-24)
    meter_db = 20.0 * np.log10(meter_rms)
    quiet_thr = float(np.percentile(meter_db, 20))
    loud_thr = float(np.percentile(meter_db, 90))
    quiet = meter_db <= quiet_thr
    speech = meter_db >= loud_thr - 10.0
    # §12 — the level of each phrase, so _finish() can say how much the voice
    # wanders between phrases. A phrase is a run of clearly-voiced frames; the
    # run's own mean removes syllable-to-syllable movement, which is performance,
    # not a defect. Runs are collected per chunk (a boundary splits at most one).
    _active = meter_db > max(float(np.percentile(meter_db, 20)) + 15.0,
                             float(np.percentile(meter_db, 99)) - 35.0)
    _runs = []
    _i = 0
    while _i < _active.size:
        if _active[_i]:
            _j = _i
            while _j < _active.size and _active[_j]:
                _j += 1
            if (_j - _i) * HOP / float(sr) >= 0.25:
                _runs.append(float(np.mean(meter_db[_i:_j])))
            _i = _j
        else:
            _i += 1

    noise_db = float(np.mean(frame_db[quiet])) if quiet.any() else -120.0
    noise_meter = float(np.mean(meter_db[quiet])) if quiet.any() else -120.0
    speech_db = float(np.mean(meter_db[speech])) if speech.any() else -120.0

    ms = mag[speech] if speech.any() else mag          # tonal balance, speech only
    body = _band_power(ms, sr, 300, 3000)
    rv, gaps = _gap_tail_ratio(x, sr)

    st = state if state is not None else {}
    st["frames"] = st.get("frames", 0) + int(frame_rms.size)
    st["sum_db"] = st.get("sum_db", 0.0) + float(np.sum(frame_db))
    st["peak"] = max(st.get("peak", 0.0), float(np.max(np.abs(x)) if x.size else 0.0))
    # §5 clipping — measured as FLAT TOPS, not as "samples at digital full
    # scale". The old test counted |x| > 0.999, which misses every clipped
    # file that was normalised afterwards: the flat tops are still there,
    # they simply sit at 0.98 instead of 1.0. A flat top is a run of at
    # least three samples pinned within 0.5 % of the loudest peak, and the
    # peak itself has to be near the ceiling for the reading to mean
    # anything (a quiet file has no ceiling to hit).
    # §5 clipping — measured as PINNED samples, not as "samples at digital
    # full scale" and not as "samples near the peak". Both of those were
    # tried and both are wrong here: the first misses every clipped file
    # that was normalised afterwards (the flat tops are still there, they
    # simply sit at 0.98), and the second fires on any smooth low-frequency
    # peak — a 230 Hz vowel puts several samples within 0.5 % of its own
    # maximum and a low-passed fixture read 0.02 % "clipped" while being
    # nothing of the kind. Real clipping pins consecutive samples at a
    # value they do not move from: a run of at least three samples that
    # share the loudest value within 1e-4 of each other.
    _pk = float(np.max(np.abs(x))) if x.size else 0.0
    if _pk >= 0.90:
        _flat = np.abs(x) >= _pk * 0.99
        _flat_n, _fk = 0, 0
        while _fk < _flat.size:
            if _flat[_fk]:
                _fk2 = _fk
                while _fk2 < _flat.size and _flat[_fk2]:
                    _fk2 += 1
                if (_fk2 - _fk) >= 3 and float(np.ptp(x[_fk:_fk2])) <= 1e-4:
                    _flat_n += (_fk2 - _fk)
                _fk = _fk2
            else:
                _fk += 1
        st["clip"] = st.get("clip", 0.0) + (_flat_n / float(x.size)) * frame_rms.size
    else:
        st["clip"] = st.get("clip", 0.0)
    st["silence"] = st.get("silence", 0.0) + float(np.mean(frame_db < (noise_db + 3.0)))
    _lf_bins = (freqs >= 20.0) & (freqs < 80.0)
    _body_bins = (freqs >= 300.0) & (freqs < 3000.0)
    st["rumble"] = st.get("rumble", 0.0) + (
        float(np.mean(np.sum(mag[quiet][:, _lf_bins] ** 2, axis=1)))
        if quiet.any() and _lf_bins.any() else 0.0)
    st["rumble_n"] = st.get("rumble_n", 0) + (1 if quiet.any() and _lf_bins.any() else 0)
    st["body_sum"] = st.get("body_sum", 0.0) + (
        float(np.mean(np.sum(ms[:, _body_bins] ** 2, axis=1)))
        if ms.size and _body_bins.any() else 0.0)
    st["body_n"] = st.get("body_n", 0) + (1 if ms.size and _body_bins.any() else 0)
    st["mud"] = st.get("mud", 0.0) + _band_power(ms, sr, 150, 350)
    st["mud_ref"] = st.get("mud_ref", 0.0) + _band_power(ms, sr, 350, 1500)
    st["presence"] = st.get("presence", 0.0) + _band_power(ms, sr, 2000, 4000)
    st["presence_ref"] = st.get("presence_ref", 0.0) + _band_power(ms, sr, 500, 2000)
    # Harshness is judged on the ABSOLUTE 5–9 kHz / 2–5 kHz balance and against
    # the studio’s own voices: those 13 measure 0.28–0.98 on it (measured), so
    # the line sits above all of them and normal output is never “corrected”.
    # A per-file “burst” test was tried first and rejected: the brightest 8 % of
    # frames sit 16–42 dB above a voice’s own median even when the voice is
    # perfectly healthy, and a genuinely harsh fixture only reaches 48 dB — too
    # close to separate, so it would have fired on everything or on nothing.
    st["env_peak"] = max(st.get("env_peak", 0.0), float(np.max(_rms_env(x, max(8, int(0.015 * sr))))))

    st["sib"] = st.get("sib", 0.0) + _band_power(ms, sr, 5000, 9000)
    st["mid2"] = st.get("mid2", 0.0) + _band_power(ms, sr, 2000, 5000)
    st["body"] = st.get("body", 0.0) + body
    st["noise_db"] = min(st.get("noise_db", 0.0), noise_db)
    st["speech_db"] = max(st.get("speech_db", -120.0), speech_db)
    st["noise_meter"] = min(st.get("noise_meter", 0.0), noise_meter)
    st["rv"] = st.get("rv", 0.0) + (rv or 0.0)
    st["rv_ok"] = st.get("rv_ok", 0) + (1 if rv is not None else 0)
    st["gaps"] = st.get("gaps", 0) + gaps
    st.setdefault("runs", []).extend(_runs)
    st["sr"] = sr
    st["chunks"] = st.get("chunks", 0) + 1
    return _finish(st)


def _run_spread(runs):
    """p90-p10 of the per-phrase levels; None when there are too few phrases."""
    if len(runs) < 6:
        return None
    r = np.asarray(runs, dtype=np.float64)
    return float(np.percentile(r, 90) - np.percentile(r, 10))


def _finish(st):
    n = max(1, st["frames"])
    ch = max(1, st["chunks"])
    body = max(st["body"] / ch, 1e-12)
    info = {
        "sr": int(st["sr"]),
        "peak": float(st["peak"]),
        "peak_db": _db(st["peak"]),
        "mean_db": float(st["sum_db"] / n),
        "noise_db": float(st["noise_db"]),
        "speech_db": float(st["speech_db"]),
        "snr_db": float(min(120.0, st["speech_db"] - max(st.get("noise_meter", -120.0), -120.0))),
        "clip_pct": 100.0 * float(st["clip"]) / n,
        # §5 distortion, as far as a single file can show it: with clipping
        # charged above, this is how hard-limited the signal is — the gap
        # between the loudest peak and the speech body. A healthy read sits
        # near 14-18 dB; a squashed or re-limited one collapses toward 6.
        "crest_db": float(_db(st["peak"]) - st["speech_db"]),
        "silence_pct": 100.0 * float(st["silence"]) / ch,
        # the five calibrated defect metrics (each ~0 on a clean file)
        # §7 — a steady low-frequency bed, measured while nobody is speaking,
        # against the voice’s own body level (see RUMBLE_LINE)
        "rumble_ratio": _rumble_ratio(st),
        "mud_ratio": float((st["mud"] / ch) / max(st["mud_ref"] / ch, 1e-12)),
        "presence_ratio": float((st["presence"] / ch) / max(st["presence_ref"] / ch, 1e-12)),
        # calibrated: clean ~0.032 · +6 dB shelf 0.043 · +10 dB 0.064 · +14 dB 0.23
        # 5–9 kHz against 2–5 kHz: how bright the voice is (reported, never acted on)
        "sib_ratio": float((st["sib"] / ch) / max(st["mid2"] / ch, 1e-12)),

        # §12 — phrase-to-phrase level spread, and how many phrases it saw
        "dyn_db": _run_spread(st.get("runs") or []),
        "phrases": len(st.get("runs") or []),

        "env_peak": float(st.get("env_peak", 0.0)),
        "reverb": (float(st["rv"] / st["rv_ok"]) if st.get("rv_ok") else None),
        "gaps_found": int(st.get("gaps", 0)),
    }
    info["true_peak_db"] = info["peak_db"]
    return info


def _rumble_ratio(st):
    """§7 — LF while nobody speaks ÷ the body level of the voice itself.

    Both sides are summed over their band and then averaged over frames, so the
    number does not depend on how many FFT bins a band happens to hold — that
    matters because 20–80 Hz is 3 bins at 24 kHz but a single one at 48 kHz, and
    a bin-count-weighted version read 4× differently between the two rates.
    """
    lf = st.get("rumble", 0.0) / max(1, st.get("rumble_n", 1))
    body = st.get("body_sum", 0.0) / max(1, st.get("body_n", 1))
    return float(np.sqrt(max(lf, 0.0) / max(body, 1e-20)))


def _depth_body(st):
    """The 300–3000 Hz reference, averaged over the chunks seen so far."""
    ch = max(1, st["chunks"])
    return max(st["body"] / ch, 1e-12)


def score(info):
    """§5 — 0–100, where 100 is “already good → very light processing”."""
    s = 100.0
    snr = info.get("snr_db", 60.0)
    if snr < 45:      s -= min(22.0, (45 - snr) * 0.9)
    # reverb is only judged on a genuinely quiet recording: on a noisy one the
    # “ringing” reading is the floor, not the room (§11)
    rv = info.get("reverb")
    if rv is not None and rv > 0.025 and snr > 45: s -= min(18.0, (rv - 0.025) * 300)
    if info.get("rumble_ratio", 0) > RUMBLE_LINE:
        s -= min(10.0, (info["rumble_ratio"] - RUMBLE_LINE) * 40)
    if info.get("mud_ratio", 0) > MUD_LINE:
        s -= min(10.0, (info["mud_ratio"] - MUD_LINE) * 3)
    if info.get("presence_ratio", 1) < PRESENCE_LINE:
        s -= min(10.0, (PRESENCE_LINE - info["presence_ratio"]) * 400)
    if info.get("sib_ratio", 0.0) > SIB_HF_RATIO:
        s -= min(8.0, (info["sib_ratio"] - SIB_HF_RATIO) * 6.0)
    dyn = info.get("dyn_db")
    if dyn is not None and dyn > DYN_LINE:
        s -= min(8.0, (dyn - DYN_LINE) * 1.5)
    if info.get("clip_pct", 0) > 0.01: s -= min(12.0, info["clip_pct"] * 200)
    # §5 distortion / §18 hard-limit damage: a file with no headroom between
    # its peak and its body is not a 100/100 recording, even when no sample
    # is pinned — a squashed take reads 9-13 dB against a healthy 15-18.
    _cr = info.get("crest_db")
    if _cr is not None and _cr < CREST_LINE_DB:
        s -= min(12.0, (CREST_LINE_DB - _cr) * 3.0)
    return int(max(0, min(100, round(s))))


def band_of(sc):
    for hi, name, what in BANDS:
        if sc < hi:
            return name, what
    return BANDS[-1][1], BANDS[-1][2]


# --------------------------------------------------------------------------- #
# 2. the adaptive plan (spec §3, §26)
# --------------------------------------------------------------------------- #
def plan(info, strength_cap=1.0):
    """Which stages run, and how strongly — decided by the analysis alone.

    Every threshold here is the calibrated one: a clean file produces an EMPTY
    plan, and only loudness + true-peak safety still run (those two are the
    delivery standard, not an effect).
    """
    sc = score(info)
    st = (100 - sc) / 100.0 * float(strength_cap)
    st = max(0.0, min(1.0, st))
    dyn = info.get("dyn_db")
    p = {"score": sc, "strength": round(st, 3), "stages": [], "reasons": []}

    # clipping / hard-limit damage (§5, §18, §26) -------------------------
    # Clipping was measured and charged in the score, but the plan still
    # added a presence BOOST and compression on top of it — both of which
    # push flat-topped peaks further into the ceiling. Now a clipped input
    # gets the opposite treatment: no boost, no compressor, more headroom.
    clip_pct = float(info.get("clip_pct") or 0.0)
    crest = info.get("crest_db")
    p["clipped_pct"] = round(clip_pct, 4)
    p["crest_db"] = round(crest, 2) if crest is not None else None
    pinned = clip_pct > CLIP_LINE_PCT
    dense = crest is not None and crest < CREST_LINE_DB
    clipped = bool(pinned or dense)
    if clipped:
        if pinned:
            _why = "%0.2f%% of samples pinned at the ceiling" % clip_pct
            if crest is not None:
                _why += ", crest %.1f dB" % crest
        else:
            _why = ("no headroom left between peak and body: crest %.1f dB, "
                    "healthy voices 15-18" % crest)
        p["stages"].append("clipping / hard limiting found (%s) — no boost, "
                           "extra headroom" % _why)
        p["reasons"].append("the file is already damaged at the peak: boosting "
                            "or compressing it would only deepen it")

    # noise reduction (§6)
    snr = info.get("snr_db", 60.0)
    if snr < 42.0:
        heavy = min(1.0, (42.0 - snr) / 22.0)
        nr = 6.0 + 14.0 * heavy * (0.6 + 0.4 * st)
        p["denoise"] = {"nr": round(min(20.0, nr), 1),
                        "nf": round(max(-60.0, min(-30.0, info.get("noise_db", -50.0))), 1)}
        p["stages"].append("noise reduction")
        p["reasons"].append("noise floor %.0f dB, SNR %.0f dB" % (info.get("noise_db", -120), snr))
    else:
        p["denoise"] = None

    # de-reverb (§11) — only when the pauses really ring
    rv = info.get("reverb")
    if rv is not None and rv > 0.02:
        amt = min(0.50, 0.20 + (rv - 0.02) * 7.0) * (0.6 + 0.4 * st)
        p["dereverb"] = {"amount": round(max(0.1, amt), 3)}
        p["stages"].append("de-reverb")
        p["reasons"].append("ringing after the words (%.3f of speech energy)" % rv)
    else:
        p["dereverb"] = None
        if rv is None:
            p["reasons"].append("reverb not measurable (no quiet gaps)")

    # rumble (§7)
    if info.get("rumble_ratio", 0.0) > RUMBLE_LINE:
        hz = 70 if st < 0.5 else 80 if st < 0.8 else 90
        p["highpass"] = {"hz": hz}
        p["stages"].append("rumble filter %d Hz" % hz)
        p["reasons"].append("low rumble %.3f" % info["rumble_ratio"])
    else:
        p["highpass"] = None

    # mud (§8)
    if info.get("mud_ratio", 0.0) > MUD_LINE:
        g = min(2.0, 0.5 + (info["mud_ratio"] - MUD_LINE) * 0.35) * (0.6 + 0.4 * st)
        p["mud"] = {"hz": 250, "gain": round(-g, 2)}
        p["stages"].append("low-mid -%.1f dB @250 Hz" % g)
        p["reasons"].append("low-mid weight high (%.2f)" % info["mud_ratio"])
    else:
        p["mud"] = None

    # clarity (§9)
    _p = info.get("presence_ratio", 1.0)
    raw = min(1.6, 0.5 + (PRESENCE_LINE - _p) * 40.0) if _p < PRESENCE_LINE else 0.0
    # the floor is checked BEFORE the strength scaling and kept afterwards: a
    # file that needs clarity gets a real (if small) lift, not a 0.3 dB token,
    # and a file that needs less than half a dB gets no EQ stage at all (§22)
    g = max(0.25, raw * (0.6 + 0.4 * st)) if raw > 0 else 0.0
    if clipped:
        g = 0.0        # §18: never boost a clipped file
    if g > 0:
        p["presence"] = {"hz": 3300, "gain": round(g, 2)}
        p["stages"].append("presence +%.1f dB @3.3 kHz" % g)
        p["reasons"].append("clarity low (%.4f)" % info["presence_ratio"])
    else:
        p["presence"] = None

    # sibilance (§10) — calibrated against the studio’s own 13 voices (1.0–1.6)
    # and a burst fixture (2.6+): only frames that stick out of the voice’s own
    # median are touched, so a bright voice is never “corrected”, and a lifted
    # top end — which is a tilt, not sibilance — is left alone
    sib = info.get("sib_ratio", 0.0)
    if sib > SIB_HF_RATIO:
        g = min(3.0, 0.8 + (sib - SIB_HF_RATIO) * 1.2) * (0.6 + 0.4 * st)
        p["deess"] = {"gain": round(g, 2), "hz": 7200}
        p["stages"].append("harshness -%.1f dB @7.2 kHz" % g)
        p["reasons"].append("top end %.2f× its own body (voice range 0.28–0.98)" % sib)
    else:
        p["deess"] = None

    if clipped:
        # §12/§18: a compressor on a clipped file squeezes the flat tops even
        # harder — the plan leaves the dynamics alone and delivers headroom.
        p["comp"] = None
    # gentle compression (§12) — only when the level really wanders, and placed
    # against the voice's OWN level. The threshold used to be a fixed -18 dB,
    # which made the stage's effect depend on how hot the file happened to be:
    # measured on a +-10 dB fixture it removed 3.4 dB of the wander at one input
    # level and nothing at all 8 dB quieter. A threshold 6 dB under the measured
    # speech level engages by design, so the 3-6 dB of gain reduction §12 asks
    # for is a property of the passage, not of the delivery level.
    if dyn is not None and dyn > DYN_LINE:
        ratio = 2.0 + min(1.0, (dyn - DYN_LINE) / 8.0)
        # -4 dB: measured on a +-10 dB swell the loud sections come down 2.8 dB
        # and the wander closes by 7 dB; on a half-script 10 dB jump, 5.2 dB of
        # gain reduction — §12's "approximately 3-6 dB when necessary".
        thr = max(-40.0, min(-12.0, float(info.get("speech_db", -22.0)) - 4.0))
        p["comp"] = {"ratio": round(ratio, 1), "threshold_db": round(thr, 1),
                     "attack": 10.0, "release": 180.0}
        p["stages"].append("gentle compression %.1f:1" % ratio)
        p["reasons"].append("phrase level wanders %.1f dB (healthy voices \u2264 9.3)"
                            % dyn)
    elif st > 0.25:
        # a bad score can justify a light hand even without the wander reading
        ratio = 2.0 + min(1.0, st)
        thr = max(-40.0, min(-12.0, float(info.get("speech_db", -22.0)) - 3.0))
        p["comp"] = {"ratio": round(ratio, 1), "threshold_db": round(thr, 1),
                     "attack": 10.0, "release": 180.0}
        p["stages"].append("gentle compression %.1f:1" % ratio)
    else:
        p["comp"] = None

    name, what = band_of(sc)
    p["band"] = name
    p["what"] = what
    p["loudness"] = {"lufs": TARGET_LUFS,
                     "tp": (TRUE_PEAK_DBTP - 0.5) if clipped else TRUE_PEAK_DBTP}
    if clipped:
        p["reasons"].append("true-peak ceiling lowered to %.1f dBTP so the "
                            "damaged peaks have room" % p["loudness"]["tp"])
    return p


# --------------------------------------------------------------------------- #
# 3. the pass (spec §25 order)
# --------------------------------------------------------------------------- #
def _f(x):
    return ("%g" % float(x))


def tone_chain(p, sr):
    """The non-linear stages that ffmpeg does best, in the spec's order."""
    f = []
    if p.get("highpass"):
        # §7 — twice, because one highpass is only 6 dB/octave: measured, it
        # takes just −8.4 dB out of a 45 Hz hum (a tilt, not a rumble cut),
        # while the cascade is −16.7 dB there and still only −1.9 dB at 100 Hz,
        # so the voice itself is barely touched. The corner comes from the plan.
        _hp = "highpass=f=%d" % int(p["highpass"]["hz"])
        f.append(_hp)
        f.append(_hp)
    if p.get("mud"):
        f.append("equalizer=f=%d:t=q:w=0.9:g=%s" % (int(p["mud"]["hz"]), _f(p["mud"]["gain"])))
    if p.get("presence"):
        f.append("equalizer=f=%d:t=q:w=1.4:g=%s" % (int(p["presence"]["hz"]), _f(p["presence"]["gain"])))
    if p.get("deess"):
        f.append("equalizer=f=%d:t=q:w=2.0:g=-%s" % (int(p["deess"].get("hz", 7200)),
                                                     _f(abs(p["deess"]["gain"]))))
    if p.get("comp"):
        c = p["comp"]
        f.append("acompressor=threshold=%sdB:ratio=%s:attack=%s:release=%s"
                 % (_f(c["threshold_db"]), _f(c["ratio"]), _f(c["attack"]), _f(c["release"])))
    return ",".join(f)


def _run(cmd, timeout=7200):
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or b"").decode("utf-8", "ignore")[-400:] or "ffmpeg failed")
    return r


def _decode(src, dst_f32, ffmpeg, sr=OUT_SR, native_sr=None):
    """Decode anything to raw float32 mono at the engine rate (§15).

    This is the ONE rate conversion in the whole pipeline: a 48 kHz source is
    only re-formatted (never resampled), anything else is resampled once, here,
    with soxr. Every measurement and every stage below therefore works at a
    known 48 kHz, and the output needs no further conversion.
    """
    af = []
    if native_sr != sr:                       # already 48 kHz → no conversion at all
        af = ["-af", "aresample=resampler=soxr:precision=28:osr=%d" % sr]
    _run([ffmpeg, "-hide_banner", "-nostats", "-loglevel", "error", "-y", "-i", src,
          "-ac", "1"] + af + ["-f", "f32le", dst_f32])


def _wav_header(path, n_frames, sr, bits, channels=1):
    ba = channels * bits // 8
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + n_frames * ba) + b"WAVE")
        f.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, sr,
                                      sr * ba, ba, bits))
        f.write(b"data" + struct.pack("<I", n_frames * ba))


def _read_f32(path, offset, count):
    with open(path, "rb") as f:
        f.seek(offset * 4)
        buf = f.read(count * 4)
    return np.frombuffer(buf, dtype=np.float32).copy()


# ---------------------------------------------------------------- DSP stages #
def _stft_mat(x, n=N_FFT, hop=HOP):
    """Complex STFT of a whole chunk, and the frame count."""
    win = _hann(n)
    if x.size < n:
        x = np.pad(x, (0, n - x.size))
    frames = 1 + (x.size - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(frames)[:, None]
    return np.fft.rfft(x[idx] * win, axis=1), frames


def _istft_mat(X, length, n=N_FFT, hop=HOP):
    """Overlap-add inverse of `_stft_mat` (vectorised, no per-frame loop)."""
    win = _hann(n)
    frames = X.shape[0]
    y = np.fft.irfft(X, n=n, axis=1).astype(np.float32) * win
    idx = (np.arange(n)[None, :] + hop * np.arange(frames)[:, None]).ravel()
    total = length + n
    out = np.bincount(idx, weights=y.ravel().astype(np.float64),
                      minlength=total)[:total].astype(np.float32)
    wsum = np.bincount(idx, weights=np.tile((win ** 2).astype(np.float64), frames),
                       minlength=total)[:total].astype(np.float32)
    nz = wsum > 1e-6
    out[nz] /= wsum[nz]
    return out[:length]


def _smooth_time(g, k=3):
    """A short moving average along time — no “musical noise” from the gate.

    Edge-held, NOT `np.roll`: a circular shift made the first frames of every
    chunk borrow their gain from the END of that chunk, which is exactly the
    kind of thing that leaves a step at a chunk join in a long file.
    """
    if g.shape[0] <= k:
        return g
    pad = np.concatenate((np.repeat(g[:1], k - 1, axis=0), g,
                          np.repeat(g[-1:], k - 1, axis=0)), axis=0)
    out = np.zeros_like(g)
    for i in range(k):
        out += pad[i:i + g.shape[0]]
    return out / float(k)


def _spectral_gate(x, sr, noise_mag, strength, floor_db=-18.0):
    """Gentle spectral noise reduction with a measured noise profile (§6)."""
    if strength <= 0 or noise_mag is None or noise_mag.size == 0:
        return x
    X, _ = _stft_mat(x)
    mag = np.abs(X) + 1e-12
    ratio = np.minimum(1.0, noise_mag[:mag.shape[1]] / mag)
    gain = np.clip(1.0 - float(strength) * ratio ** 1.2, 10.0 ** (floor_db / 20.0), 1.0)
    gain = _smooth_time(gain)
    return _istft_mat(X * gain, x.size)


def _movavg(x, n):
    """Moving average of a 1-D signal, edge-held, one pass."""
    n = max(1, int(n))
    if n == 1 or x.size < 2:
        return np.asarray(x, dtype=np.float64)
    pad = np.concatenate((np.full(n, x[0], dtype=np.float64), np.asarray(x, dtype=np.float64)))
    c = np.cumsum(pad)
    return (c[n:] - c[:-n]) / n


def _dereverb(x, sr, amount, peak=None):
    """Late-reverb suppression (§11) — in the pauses, where a room is audible.

    What makes a voice sound “roomy” is the ringing that keeps going while the
    speaker has stopped, so that is what is treated: an envelope follower marks
    the low-level residue between words, and a soft downward expansion pulls
    only that down. Above the speech level the gain is exactly 1.0, so the
    voice, its consonants and its identity are untouched (§4, §27); the change
    is inaudible inside words and obvious between them.

    (Two spectral attempts came first and both failed: an estimate built from
    the *present* frame can never go below the speech, and one built from the
    summed past saturates at the speech level as well — each collapsed into a
    plain gain, which reduces level, not reverb. This one moves the measured
    ring-in-the-gaps figure, which is the only thing that counts.)
    """
    if amount <= 0:
        return x
    xf = np.asarray(x, dtype=np.float32)
    e = _rms_env(xf, int(0.015 * sr))
    if peak is None:
        peak = float(np.max(e)) or 1e-9
    peak = max(float(peak), 1e-9)          # the SAME threshold in every chunk
    thr = 0.12 * peak                      # below this the speaker has stopped
    # downward expansion, in dB, proportional to how far below the threshold
    # the residue is — the further into a pause, the more of the ring is taken,
    # and it is capped so nothing is ever gated away into silence
    rel_db = 20.0 * np.log10(np.maximum(e, 1e-9) / thr)
    below = np.clip(-rel_db, 0.0, None)
    ratio = 1.0 + 3.0 * float(amount)
    cap_db = 8.0 + 16.0 * float(amount)
    gain_db = np.clip(-below * ratio, -cap_db, 0.0)
    gain = _movavg(_movavg(np.power(10.0, gain_db / 20.0), int(0.010 * sr)),
                   int(0.020 * sr))                     # soft ramps: no clicks
    return (xf * gain.astype(np.float32)).astype(np.float32)


def _noise_profile(path, sr, info):
    """Per-bin noise magnitude, measured on the quietest frames of the file."""
    mags = []
    step = max(1, info.get("frames", 1) // 400)
    size = step * HOP + N_FFT
    with open(path, "rb") as f:
        f.seek(0)
        pos = 0
        while len(mags) < 400:
            f.seek(pos * 4)
            chunk = np.frombuffer(f.read(size * 4), dtype=np.float32)
            if chunk.size < N_FFT:
                break
            m = _stft(chunk)
            rms = np.sqrt(np.mean(m ** 2, axis=1) + 1e-18)
            k = max(1, rms.size // 6)
            idx = np.argsort(rms)[:k]
            mags.append(np.median(m[idx], axis=0))
            pos += size
            if chunk.size < size:
                break
    if not mags:
        return None
    prof = np.median(np.stack(mags), axis=0)
    return prof.astype(np.float32)


def _apply_spectral_stages(src_f32, dst_f32, sr, p, info, log):
    """The two stages ffmpeg cannot do well, chunked with an overlap (§21)."""
    need = bool(p.get("denoise")) or bool(p.get("dereverb"))
    n_bytes = os.path.getsize(src_f32)
    n_total = n_bytes // 4
    if not need:
        shutil.copyfile(src_f32, dst_f32)
        return n_total

    prof = _noise_profile(src_f32, sr, info) if p.get("denoise") else None
    nr_strength = 0.0
    if p.get("denoise"):
        # afftdn’s nr value (6–16 dB) → a gentle spectral gain floor
        nr_strength = min(0.85, float(p["denoise"]["nr"]) / 20.0)

    chunk = int(max(2.0, CHUNK_SECS) * sr)
    over = int(max(0.25, OVERLAP_SECS) * sr)

    # Each chunk is processed WITH context on both sides and only its clean
    # middle is written: the first and last `over` seconds of a processed
    # segment are the parts a denoiser or a de-reverb has no history for, so
    # they are thrown away instead of being glued to the next chunk. The written
    # ranges still tile the file exactly, and every sample that ends up in the
    # output was decided with at least `over` seconds of real audio around it —
    # which is what makes a 3-minute file identical to a single-pass one.
    with open(dst_f32, "wb") as out:
        pos = 0
        while pos < n_total:
            take = min(chunk, n_total - pos)
            a = max(0, pos - over)
            b = min(n_total, pos + take + over)
            seg = _read_f32(src_f32, a, b - a).astype(np.float32)
            if p.get("dereverb"):
                seg = _dereverb(seg, sr, p["dereverb"]["amount"], peak=info.get("env_peak") or None)
            if prof is not None:
                seg = _spectral_gate(seg, sr, prof, nr_strength)
            w0 = pos - a
            out.write(np.ascontiguousarray(seg[w0:w0 + take]).tobytes())
            pos += take
    log.append("spectral stages: %s"
               % ", ".join(n for n, on in (("denoise", prof is not None),
                                           ("de-reverb", bool(p.get("dereverb")))) if on))
    return n_total


# --------------------------------------------------------------------------- #
# 4. the whole thing (spec §16–§25)
# --------------------------------------------------------------------------- #
def enhance_file(src, hd_out, log=None, ffmpeg=None, preview_dir=None,
                 report_path=None, strength_cap=1.0, lufs=TARGET_LUFS):
    """One controlled enhancement pass, always from the ORIGINAL (§19).

    Returns the report dict. The source file is never modified. If anything
    fails, `ok` is False, `hd_out` is not created (or is a copy of the source)
    and the caller keeps the original audio (§24).
    """
    log = log if log is not None else []
    ffmpeg = _ffmpeg(ffmpeg)
    t0 = time.time()
    report = {"ok": False, "engine": "hdclean", "source": os.path.abspath(src),
              "stages": [], "note": "", "log": log}
    tmp = tempfile.mkdtemp(prefix="hdclean_")
    try:
        if np is None:
            raise RuntimeError("numpy is required")
        if not os.path.exists(src) or os.path.getsize(src) < 2000:
            raise RuntimeError("source audio is missing or empty")

        # --- 0. keep the original (§16) --------------------------------------
        src_sr_native = _probe_sr(src, ffmpeg)
        src_sr = OUT_SR                       # the engine’s internal rate (§15)
        report["source_sr"] = src_sr_native

        # --- 1. decode + analyse the ORIGINAL --------------------------------
        raw = os.path.join(tmp, "src.raw")
        _decode(src, raw, ffmpeg, OUT_SR, src_sr_native)
        n_total = os.path.getsize(raw) // 4
        st = {}
        step = int(CHUNK_SECS * src_sr)
        for pos in range(0, n_total, step):
            analyze(_read_f32(raw, pos, min(step, n_total - pos)), src_sr, st)
        info = _finish(st) if "frames" in st else None
        if info is None:
            raise RuntimeError("nothing to analyse")
        info["true_peak_db"] = float(_true_peak_db(raw, n_total, src_sr))
        report["analysis_before"] = info
        report["score_before"] = score(info)
        log.append("analysis: score %d (%s) — %s" % (report["score_before"],
                                                     band_of(report["score_before"])[0],
                                                     band_of(report["score_before"])[1]))

        # --- 2. the adaptive plan (§26) --------------------------------------
        p = plan(info, strength_cap=strength_cap)
        report["plan"] = {k: v for k, v in p.items() if k not in ("loudness",)}
        log.append("plan: " + ("; ".join(p["stages"]) or "nothing needed"))
        report["stages"] = list(p["stages"])

        # --- 3. ONE pass: spectral stages, then the tone/loudness chain -------
        staged = os.path.join(tmp, "staged.raw")
        _apply_spectral_stages(raw, staged, src_sr, p, info, log)

        # write the staged audio as a WAV for ffmpeg
        staged_wav = os.path.join(tmp, "staged.wav")
        hdr = _wav_f32_header(src_sr, n_total)
        with open(staged_wav, "wb") as w:
            w.write(hdr)
            with open(staged, "rb") as r:
                shutil.copyfileobj(r, w, 1 << 22)

        # tone chain + two-pass loudness + true-peak limiter + 24-bit output
        tone = tone_chain(p, src_sr)
        chain_wav = os.path.join(tmp, "chain.wav")
        af = tone or "anull"          # already 48 kHz: no second conversion
        _run([ffmpeg, "-hide_banner", "-nostats", "-loglevel", "error", "-y",
              "-i", staged_wav, "-af", af, "-ac", "1", "-c:a", "pcm_f32le", chain_wav])
        if tone:
            log.append("tone chain: " + tone)

        meas = _measure_loudness(ffmpeg, chain_wav)
        ln = ("loudnorm=I=%s:TP=%s:LRA=%s" % (_f(lufs), _f(TRUE_PEAK_DBTP), _f(9.0)))
        if meas:
            ln += (":measured_I=%s:measured_TP=%s:measured_LRA=%s:measured_thresh=%s"
                   ":offset=%s:linear=true"
                   % (_f(meas.get("input_i", lufs)), _f(meas.get("input_tp", TRUE_PEAK_DBTP)),
                      _f(meas.get("input_lra", 9.0)), _f(meas.get("input_thresh", -40.0)),
                      _f(meas.get("target_offset", 0.0))))
            log.append("loudness: %.1f LUFS → %.1f LUFS (two-pass, linear)"
                       % (float(meas.get("input_i", 0.0)), lufs))
        lim = min(0.99, 10 ** (TRUE_PEAK_DBTP / 20.0))
        # latency=1: ffmpeg’s alimiter looks ahead by 240 samples (5 ms) and does
        # NOT compensate for it by default — measured on a master whose only
        # difference should have been 5.3 dB of gain, the output came back 5 ms
        # late, which is a real timing error in a narration (and it hid every
        # spectral comparison behind a shifted frame grid). Compensating beats
        # trimming: nothing is cut off the front and no samples are lost.
        master = "%s,alimiter=limit=%s:level=0:latency=1" % (ln, _f(lim))
        _run([ffmpeg, "-hide_banner", "-nostats", "-loglevel", "error", "-y",
              "-i", chain_wav, "-af", master, "-ac", "1", "-ar", str(OUT_SR),
              "-c:a", "pcm_s24le", hd_out])
        log.append("true-peak: limiter at %.1f dBTP" % TRUE_PEAK_DBTP)

        # --- 4. quality check on the RESULT (§18) ----------------------------
        out_raw = os.path.join(tmp, "out.raw")
        _decode(hd_out, out_raw, ffmpeg, OUT_SR, OUT_SR)
        n_out = os.path.getsize(out_raw) // 4
        st2 = {}
        for pos in range(0, n_out, step):
            analyze(_read_f32(out_raw, pos, min(step, n_out - pos)), OUT_SR, st2)
        info2 = _finish(st2)
        info2["true_peak_db"] = float(_true_peak_db(out_raw, n_out, OUT_SR))
        report["analysis_after"] = info2
        report["score_after"] = score(info2)

        artifact = _artifact_check(info, info2, p)
        report["artifact_check"] = artifact
        if artifact.get("worse") and strength_cap > REDO_CAP + 1e-6:
            log.append("quality check: %s → reducing strength and redoing it once "
                       "from the ORIGINAL" % artifact["why"])
            return enhance_file(src, hd_out, log=log, ffmpeg=ffmpeg,
                                preview_dir=preview_dir, report_path=report_path,
                                strength_cap=REDO_CAP, lufs=lufs)
        if artifact.get("worse"):
            log.append("quality check: %s — keeping the lightest pass" % artifact["why"])

        # --- 5. previews (§17) -----------------------------------------------
        report["previews"] = _write_previews(src, hd_out, preview_dir, ffmpeg, tmp)

        report["ok"] = True
        report["out"] = {"lufs_in": _round(meas.get("input_i")),
                         "lufs": _measure_lufs_only(ffmpeg, hd_out),
                         "true_peak_db": info2["true_peak_db"],
                         "sr": OUT_SR, "bits": OUT_BITS}
        report["hd"] = os.path.abspath(hd_out)
        report["seconds"] = round(n_total / float(OUT_SR), 2)
        report["elapsed"] = round(time.time() - t0, 1)
        report["note"] = ("HD Cleanup: score %d → %d (%s). %s"
                          % (report["score_before"], report["score_after"],
                             band_of(report["score_after"])[0],
                             "; ".join(p["stages"]) or "the file was already clean"))
        if src_sr_native != OUT_SR:
            report["note"] += (" · source %d kHz → 48 kHz container (a format "
                               "change, not added detail)" % (src_sr_native // 1000))
        log.append("done: score %d → %d in %.1f s"
                   % (report["score_before"], report["score_after"], report["elapsed"]))
        return report

    except Exception as e:                                    # §24 fail-safe
        report["ok"] = False
        report["error"] = "%s: %s" % (type(e).__name__, e)
        report["note"] = "Enhancement unavailable; original TTS preserved."
        log.append("FAILED: %s — %s" % (report["error"], report["note"]))
        return report
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            if report_path:
                with open(report_path, "w", encoding="utf-8") as f:
                    json.dump(report, f, indent=1, ensure_ascii=False)
        except Exception:
            pass


def _wav_f32_header(sr, n_frames):
    return (b"RIFF" + struct.pack("<I", 36 + n_frames * 4) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 3, 1, sr, sr * 4, 4, 32)
            + b"data" + struct.pack("<I", n_frames * 4))


def _probe_sr(src, ffmpeg):
    """The SOURCE sample rate (informational — the engine itself runs at 48 kHz).

    Only the audio-stream line is trusted; a free scan of the banner picked up
    numbers from other parts of it and silently returned the wrong rate.
    """
    try:
        import re
        r = subprocess.run([ffmpeg, "-hide_banner", "-i", src], capture_output=True)
        txt = (r.stderr or b"").decode("utf-8", "ignore")
        for line in txt.splitlines():
            if "Audio:" in line:
                m = re.search(r"(\d{4,6})\s*Hz", line)
                if m:
                    return int(m.group(1))
    except Exception:
        pass
    return OUT_SR


def _interp4_kernel(taps=24):
    """Windowed-sinc interpolator for 4× oversampling (unit DC gain per phase)."""
    n = np.arange(-taps, taps + 1, dtype=np.float64)
    h = np.sinc(n / 4.0) * np.hanning(n.size)
    h *= 4.0 / h.sum()          # zero-stuffing loses 3/4 of the samples: give it back
    return h.astype(np.float32)


def _true_peak_db(raw_path, n, sr):
    """4× oversampled peak, in dBTP (§14 measurement).

    Zero-stuffing + windowed-sinc; a plain low-pass of the stuffed signal reads
    ~12 dB low, which is what the first version did. Verified against a known
    inter-sample peak: a 0.7071-amplitude sine at fs/4 measures ≈ +3.0 dBTP.
    """
    peak = 0.0
    step = sr * 10
    b = _interp4_kernel()
    for pos in range(0, n, step):
        x = _read_f32(raw_path, pos, min(step, n - pos))
        if x.size < 8:
            continue
        up = np.zeros(x.size * 4, dtype=np.float32)
        up[::4] = x
        up = np.convolve(up, b, "same")
        peak = max(peak, float(np.max(np.abs(up))) if up.size else 0.0)
    return _db(peak)


def _measure_loudness(ffmpeg, path):
    """ffmpeg loudnorm’s own measurement (the studio’s standard)."""
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-i", path, "-af",
                            "loudnorm=I=%s:TP=%s:LRA=9:print_format=json"
                            % (_f(TARGET_LUFS), _f(TRUE_PEAK_DBTP)),
                            "-f", "null", "-"], capture_output=True)
        txt = (r.stderr or b"").decode("utf-8", "ignore")
        i = txt.rfind("{")
        j = txt.rfind("}")
        if i >= 0 and j > i:
            return json.loads(txt[i:j + 1])
    except Exception:
        pass
    return {}


def _round(v):
    try:
        return round(float(v), 1)
    except Exception:
        return None


def _measure_lufs_only(ffmpeg, path):
    m = _measure_loudness(ffmpeg, path)
    try:
        return round(float(m.get("input_i")), 1)
    except Exception:
        return None


def _artifact_check(before, after, p):
    """§18 — did the pass make anything worse?"""
    why = []
    if after.get("sib_ratio", 0) > max(SIB_HF_RATIO, before.get("sib_ratio", 0) * 1.35):
        why.append("added harshness")
    if after.get("rumble_ratio", 0) > before.get("rumble_ratio", 0) * 1.5 + 0.01:
        why.append("added low rumble")
    if (after.get("snr_db", 99) < before.get("snr_db", 0) - 3
            and after.get("noise_db", -120.0) > -70.0):
        why.append("made the noise floor worse")
    if after.get("presence_ratio", 1) < before.get("presence_ratio", 1) * 0.6:
        why.append("lost clarity")
    return {"worse": bool(why), "why": ", ".join(why) or "cleaner, nothing added"}


def _write_previews(src, hd_out, preview_dir, ffmpeg, tmp):
    """§17 — a short Original ▶ / HD Clean ▶ pair for the interface."""
    if not preview_dir:
        return {}
    try:
        os.makedirs(preview_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(hd_out))[0]
        a = os.path.join(preview_dir, base + ".original.mp3")
        b = os.path.join(preview_dir, base + ".hd.mp3")
        for source, dst in ((src, a), (hd_out, b)):
            _run([ffmpeg, "-hide_banner", "-nostats", "-loglevel", "error", "-y",
                  "-t", _f(PREVIEW_SECS), "-i", source, "-ac", "1",
                  "-c:a", "libmp3lame", "-b:a", "192k", dst])
        return {"original": a, "hd": b, "seconds": PREVIEW_SECS}
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# 5. what the studio and the pipeline call
# --------------------------------------------------------------------------- #
def khmer_only_ok(text, language=""):
    """§ “Khmer language only” — the tool is applied to Khmer jobs only."""
    lang = (language or "").strip().lower()
    compact = "".join(ch for ch in (text or "") if not ch.isspace())
    kh = sum(1 for c in compact if "\u1780" <= c <= "\u17ff")
    ratio = (kh / len(compact)) if compact else 0.0
    if lang.startswith("km") or lang in ("khmer", "cambodian"):
        return True, "Khmer"
    # the same 30 %-Khmer test the studio uses to route Khmer jobs (`is_khmer`),
    # so a Khmer script whose tag says “auto” is still treated as Khmer
    if ratio > 0.3:
        return True, "Khmer"
    if lang and lang not in ("auto", ""):
        return False, "language is %s, not Khmer" % language
    if not compact:
        return False, "no text"
    return False, "not Khmer"


def enhance_keep_original(src, hd_out, original_copy=None, log=None, **kw):
    """The form the studio uses: never lose the original (§16 + §24)."""
    log = log if log is not None else []
    rep = enhance_file(src, hd_out, log=log, **kw)
    if original_copy:
        try:
            os.makedirs(os.path.dirname(original_copy) or ".", exist_ok=True)
            shutil.copyfile(src, original_copy)
            rep["original"] = os.path.abspath(original_copy)
        except Exception as e:
            log.append("could not store the original copy (%s)" % e)
    return rep


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Adaptive Khmer Voice Enhancement "
                                             "(HD Cleanup) for one audio file")
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--log", action="store_true", help="print the step log")
    ap.add_argument("--report", default="", help="write the JSON report here")
    ap.add_argument("--previews", default="", help="folder for Original/HD previews")
    a = ap.parse_args(argv)
    lines = []
    rep = enhance_file(a.src, a.dst, log=lines, preview_dir=a.previews or None,
                       report_path=a.report or None)
    if a.log:
        for l in lines:
            print("  " + l)
    print(json.dumps({k: v for k, v in rep.items()
                      if k in ("ok", "score_before", "score_after", "stages", "note",
                               "error", "out", "seconds", "elapsed")},
                     indent=1, ensure_ascii=False))
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
