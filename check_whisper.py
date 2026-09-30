#!/usr/bin/env python3
"""check_whisper.py — find whisper-like passages in an audio file.

Point it at any file the studio produced (or at your clone's output) and it
prints where a whisper-like passage starts and ends, with the measurement that
flagged it. This exists because "it sounds like a whisper" is hard to act on and
easy to disprove: a whisper has a signature, and the signature is measurable.

A whisper-like passage is one that is, at the same time:

  * AIRY      — 2.5-9 kHz sits far above the file's own voice range
                (measured against the file, so a naturally bright voice is not
                accused; sustained, not a single /s/);
  * APERIODIC — no usable pitch period (a whisper has no vibrating folds, so the
                autocorrelation that tracks a spoken vowel is absent);
  * PRESENT   — loud enough to be heard as voice (a breath in a pause is not a
                whispered line, and is reported separately).

Everything is measured on the file's own scale, so a quiet or a loud master both
work. Nothing here changes the audio; it only looks.

    python3 pipeline/check_whisper.py episode.wav
    python3 pipeline/check_whisper.py *.mp3 --json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys

import numpy as np

SR = 48000
N_FFT = 1024
HOP = 256
FRAME_S = HOP / float(SR)                 # 5.33 ms
MIN_PASSAGE_S = 0.25                      # a whisper moment is at least this long
AIR_LINE_DB = 6.0                         # above the file's own voice air level
PERIODICITY_LINE = 0.30                   # per frame: below this there is no pitch
#: A hissing consonant is airy, aperiodic and lasts a third of a second — it
#: passed a per-frame test and produced false alarms in normal speech (measured:
#: a clean take reported a 0.35 s "whisper" at 0:00.4). A whispered passage is
#: LONGER and stays pitchless the whole way through, so the passage itself is
#: judged on its own means: >= 0.8 s and mean periodicity <= 0.28. The whispered
#: line in the test fixture reads 2.9 s / 0.24; the sibilants read 0.33-0.35 s /
#: 0.35-0.37 and are reported only as a note, never as a whisper.
PASSAGE_MIN_S = 0.8
PASSAGE_PERIODICITY = 0.28
#: a whole file can be whispered, in which case "relative to the file" measures
#: nothing — the reference must be absolute too. Measured: a whispered take reads
#: air -4.7 dB / periodicity 0.23, and every real voice reads -18 to -21 dB /
#: 0.66-0.74 (the 13 style demos and the Khmer samples). The lines sit between.
AIR_ABS_DB = -12.0
PERIODICITY_FILE = 0.40
#: The pause audit (build 2026-09-30o). A finished read is silence between the
#: sentences. The generator used to synthesise a soft inhale into every few
#: gaps — filtered noise, about -53 dBFS on a -16 LUFS master, ~10-15 times in a
#: five-minute piece — and that is what sounded like a whisper arriving
#: mid-read. Pauses are measured on their own (trimmed at both ends, so the
#: decay of the last word is not counted), and anything above PAUSE_NOISE_DB is
#: reported with its time and level. Digital silence — what the engine writes
#: now — measures below -120 dBFS, and mp3 room floor below -77 dBFS.
PAUSE_NOISE_DB = -70.0
PAUSE_QUIET_DB = 30.0                     # this far below the voice = a pause
PAUSE_MIN_S = 0.40                        # a sentence gap, not a word gap
PAUSE_TRIM = 0.30                         # of each quiet run, ignore at the ends


def ffmpeg(explicit=None):
    if explicit:
        return explicit
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def decode(path, ffmpeg_bin, sr=SR):
    r = subprocess.run([ffmpeg_bin, "-v", "error", "-i", path, "-ac", "1",
                        "-ar", str(sr), "-f", "f32le", "pipe:1"],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError("could not decode %s (%s)" % (path, r.stderr[:120].decode("utf-8", "ignore")))
    return np.frombuffer(r.stdout, dtype=np.float32).astype(np.float32)


def _hann(n):
    return np.hanning(n).astype(np.float32)


def frames(x, sr=SR, n_fft=N_FFT, hop=HOP):
    """Magnitude frames, chunked so a long file does not blow up memory."""
    win = _hann(n_fft)
    n = 1 + max(0, (x.size - n_fft)) // hop
    if n <= 0:
        return np.zeros((0, n_fft // 2 + 1), np.float32)
    out = np.empty((n, n_fft // 2 + 1), np.float32)
    for i in range(n):
        seg = x[i * hop: i * hop + n_fft]
        out[i] = np.abs(np.fft.rfft(seg * win))
    return out


def _band(mag, freqs, lo, hi):
    m = (freqs >= lo) & (freqs < hi)
    return np.sum(mag[:, m] ** 2, axis=1) if m.any() else np.zeros(mag.shape[0])


def periodicity(x, sr=SR, f_lo=70.0, f_hi=400.0, hop=HOP, win=1024):
    """Autocorrelation peak in the voice range, per frame — 0 means no pitch."""
    n = 1 + max(0, (x.size - win)) // hop
    out = np.zeros(max(0, n), np.float32)
    lo, hi = int(sr / f_hi), int(sr / f_lo)
    for i in range(n):
        seg = x[i * hop: i * hop + win].astype(np.float64)
        seg = seg - seg.mean()
        e = float(np.dot(seg, seg))
        if e <= 1e-12:
            continue
        a = np.correlate(seg, seg, "full")[win - 1:]
        out[i] = float(np.max(a[lo:hi])) / e if hi > lo else 0.0
    return out


def frame_rms_db(x, sr=SR, n_fft=N_FFT, hop=HOP):
    """Per-frame level in real dBFS (Hann window, corrected for its own RMS)."""
    w = np.hanning(n_fft)
    wr = float(np.sqrt(np.mean(w ** 2))) or 1.0
    n = max(0, (x.size - n_fft) // hop + 1)
    out = np.full(n, -200.0)
    for i in range(n):
        seg = x[i * hop:i * hop + n_fft]
        out[i] = 20.0 * np.log10(max(1e-12, float(np.sqrt(np.mean((seg * w) ** 2))) / wr))
    return out


def analyse(path, ffmpeg_bin=None, sr=SR):
    ff = ffmpeg(ffmpeg_bin)
    x = decode(path, ff, sr)
    if x.size < sr // 2:
        return {"file": os.path.basename(path), "error": "shorter than half a second"}
    mag = frames(x, sr)
    if mag.shape[0] < 4:
        return {"file": os.path.basename(path), "error": "too short to measure"}
    freqs = np.fft.rfftfreq((mag.shape[1] - 1) * 2, 1.0 / sr)
    voiced_band = _band(mag, freqs, 300.0, 2500.0)
    air_band = _band(mag, freqs, 2500.0, 9000.0)
    air = 10.0 * np.log10(np.maximum(air_band, 1e-30) / np.maximum(voiced_band, 1e-30))
    level = 10.0 * np.log10(np.maximum(_band(mag, freqs, 100.0, 10000.0), 1e-30))
    m = min(level.size, air.size)
    level, air = level[:m], air[:m]
    per = periodicity(x[:m * HOP + N_FFT])[:m]
    m = min(m, per.size)
    level, air, per = level[:m], air[:m], per[:m]

    # the file's own scales: a voice is what is loud, its air level is its own
    speech = level >= (np.percentile(level, 95) - 25.0)
    if speech.sum() < 10:
        return {"file": os.path.basename(path), "error": "no speech found"}
    air_ref = float(np.median(air[speech]))
    level_ref = float(np.median(level[speech]))
    # "audible" means above the file's own floor, NOT close to the loud voice: a
    # whispered line measured 14.8 dB below the voice in a normal read, and the
    # first version of this rule (level within 12 dB of the voice) walked right
    # past it. The floor anchor also keeps a breath in a pause out — and the
    # airiness test above rejects the studio's own breaths anyway, because they
    # are low-passed and carry no top end.
    floor = float(np.percentile(level, 10))
    quiet_cut = max(floor + 12.0, level_ref - 30.0)

    airy = (air - air_ref) > AIR_LINE_DB
    aperiodic = per < PERIODICITY_LINE
    present = level > quiet_cut
    flag = airy & aperiodic & present

    # the whole-file view: a file that was whispered end to end has no quiet
    # passages to compare against, so it is judged on absolute air + periodicity
    sp_per = per[speech]
    file_air = float(np.median(air[speech]))
    file_per = float(np.median(sp_per))
    whisper_dominant = bool(file_per < PERIODICITY_FILE and file_air > AIR_ABS_DB)

    # merge runs separated by a blink (a word boundary inside one whispered
    # passage used to split it into pieces too short to report — the first
    # version found 0.25 s and 0.44 s pieces of a 3.8 s whispered line)
    merged = flag.copy()
    gap = int(round(0.35 / FRAME_S))
    i = 0
    while i < merged.size:
        if merged[i]:
            j = i
            while j < merged.size and merged[j]:
                j += 1
            k = j
            while k < merged.size and not merged[k] and (k - j) <= gap:
                k += 1
            if k < merged.size and merged[k]:
                merged[j:k] = True
                continue
            i = j
        else:
            i += 1
    flag = merged

    passages, shorts = [], []
    i = 0
    while i < flag.size:
        if flag[i]:
            j = i
            while j < flag.size and flag[j]:
                j += 1
            dur = (j - i) * FRAME_S
            p_air = float(np.mean(air[i:j]) - air_ref)
            p_per = float(np.mean(per[i:j]))
            if dur >= PASSAGE_MIN_S and p_per <= PASSAGE_PERIODICITY:
                passages.append({
                    "start_s": round(i * FRAME_S, 2),
                    "end_s": round(j * FRAME_S, 2),
                    "seconds": round(dur, 2),
                    "air_over_voice_db": round(p_air, 1),
                    "level_vs_voice_db": round(float(np.mean(level[i:j]) - level_ref), 1),
                    "periodicity": round(p_per, 2),
                })
            elif dur >= MIN_PASSAGE_S:
                shorts.append({"start_s": round(i * FRAME_S, 2), "seconds": round(dur, 2),
                               "air_over_voice_db": round(p_air, 1),
                               "periodicity": round(p_per, 2)})
            i = j
        else:
            i += 1

    breaths = int(np.sum((~present) & aperiodic & (level > level_ref - 40.0)))

    # ---- the pause audit (build 2026-09-30o) -------------------------------
    # A pause is where the voice is not: anything with energy in there is a
    # sound the piece did not mean to make. The removed breath lived here. The
    # measurement is a true frame RMS in dBFS, trimmed at both ends of each
    # quiet run so the decay of the last word is never counted as pause tone.
    rdb = frame_rms_db(x, sr)
    quiet = rdb < (float(np.percentile(rdb, 95)) - PAUSE_QUIET_DB)
    pause_noise, i = [], 0
    while i < quiet.size:
        if quiet[i]:
            j = i
            while j < quiet.size and quiet[j]:
                j += 1
            if (j - i) * HOP / float(sr) >= PAUSE_MIN_S:
                k = max(1, int((j - i) * PAUSE_TRIM))
                a, b = i + k, max(i + k + 1, j - k)
                pk = float(np.max(rdb[a:b]))
                if pk > PAUSE_NOISE_DB:
                    pause_noise.append({
                        "start_s": round(i * HOP / float(sr), 2),
                        "seconds": round((j - i) * HOP / float(sr), 2),
                        "peak_db": round(pk, 1),
                        "vs_voice_db": round(pk - float(np.percentile(rdb, 95)), 1),
                    })
            i = j
        else:
            i += 1

    if whisper_dominant:
        verdict = ("the WHOLE FILE reads as whispered (air %+.1f dB, pitch "
                   "periodicity %.2f)" % (file_air, file_per))
    elif passages:
        verdict = "%d whisper-like passage(s)" % len(passages)
    else:
        verdict = "no whisper-like passage found"
    return {
        "file": os.path.basename(path),
        "seconds": round(x.size / float(sr), 2),
        "voice_air_db": round(air_ref, 2),
        "file_air_db": round(file_air, 2),
        "file_periodicity": round(file_per, 2),
        "whisper_dominant": whisper_dominant,
        "whisper_passages": passages,
        "short_airy_moments": shorts,
        "breath_frames": breaths,
        "pause_noise": pause_noise,
        "verdict": verdict,
    }


def _mmss(t):
    return "%d:%05.2f" % (int(t // 60), t % 60)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="audio file(s) to check (globs are fine)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--ffmpeg", default=None, help="path to ffmpeg (default: imageio-ffmpeg)")
    a = ap.parse_args(argv)

    paths = []
    for p in a.files:
        paths.extend(sorted(glob.glob(p)) or [p])
    reports = []
    for p in paths:
        if not os.path.exists(p):
            reports.append({"file": p, "error": "not found"})
            continue
        try:
            reports.append(analyse(p, a.ffmpeg))
        except Exception as e:                                    # never crash on one file
            reports.append({"file": os.path.basename(p), "error": "%s: %s" % (type(e).__name__, e)})

    if a.json:
        print(json.dumps(reports, indent=2))
    else:
        bad = 0
        for r in reports:
            print("=" * 72)
            print(r["file"])
            if r.get("error"):
                print("  !! %s" % r["error"]); continue
            print("  %.2f s · voice air %+.2f dB · pitch periodicity %.2f · %d breath frame(s)"
                  % (r["seconds"], r["file_air_db"], r["file_periodicity"],
                     r["breath_frames"]))
            if r.get("whisper_dominant"):
                bad += 1
                print("  **   %s" % r["verdict"])
            elif not r["whisper_passages"]:
                print("  OK   no whisper-like passage found")
            else:
                bad += 1
                for i, w in enumerate(r["whisper_passages"], 1):
                    print("  **   #%d %s - %s (%.2f s): air %+.1f dB over the voice, "
                          "level %+.1f dB, periodicity %.2f"
                          % (i, _mmss(w["start_s"]), _mmss(w["end_s"]), w["seconds"],
                             w["air_over_voice_db"], w["level_vs_voice_db"], w["periodicity"]))
            for m in r.get("short_airy_moments") or []:
                print("       note: %s for %.2f s is airy (air %+.1f dB, pitch %.2f) — "
                      "a consonant, not a passage" % (_mmss(m["start_s"]), m["seconds"],
                                                      m["air_over_voice_db"], m["periodicity"]))
            pn = r.get("pause_noise") or []
            if not pn:
                print("  OK   pauses are silent (no noise between the sentences)")
            else:
                print("  **   %d pause(s) carry noise (a breath-like sound between "
                      "the sentences):" % len(pn))
                for e in pn[:6]:
                    print("       %s for %.2f s at %+.1f dBFS" %
                          (_mmss(e["start_s"]), e["seconds"], e["peak_db"]))
                if len(pn) > 6:
                    print("       … %d more" % (len(pn) - 6))
        print("=" * 72)
        noisy = sum(1 for r in reports if r.get("pause_noise"))
        print("%d file(s) checked · %d with a whisper-like passage · %d with noise in "
              "the pauses" % (len(reports), bad, noisy))
    return 0


if __name__ == "__main__":
    sys.exit(main())
