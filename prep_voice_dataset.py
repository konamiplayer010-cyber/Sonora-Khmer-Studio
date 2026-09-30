#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""prep_voice_dataset.py — turn a folder of your recordings into a dataset
that the RVC-WebUI "Train" tab can digest, and tell you honestly whether it
is good enough to sound professional.

WHY THIS EXISTS
    RVC copies a TIMBRE. Everything the ears call "quality" comes from the
    recordings you feed it:
      * one speaker, one microphone, one distance, one room
      * no music, no reverb/echo, no clipping, no background voices
      * 10-50 minutes of clean speech (30-60 is the sweet spot)
    This tool does the mechanical part (mono, 40 kHz, silence trimmed,
    optional noise reduction, consistent level) and then MEASURES the result
    so you know before you spend an hour training.

WHAT IT DOES (per input file)
    1. decode anything ffmpeg can read (wav/mp3/m4a/aac/flac/ogg/opus/wma...)
    2. mono, 40 000 Hz, high-pass 70 Hz (kills rumble/DC)
    3. optional light spectral denoise  (--denoise)
    4. trim long silences at both ends and between sentences
    5. peak-limited to -1 dBFS (no dynamic pumping — RVC normalises slices)
    6. WAV 16-bit PCM, ASCII name:  km_0001.wav, km_0002.wav ...
    7. measure: duration, peak, RMS, silence %, clipped sample %,
       estimated noise floor
    8. write DATASET-REPORT.txt + RVC-TRAIN-SETTINGS.txt into the output
       folder, and print a GO / THIN / NO-GO verdict

It never touches your source recordings. It never deletes anything.

USAGE (Windows: double-click prep_voice_dataset.bat, or menu 13)
    python prep_voice_dataset.py --in "D:\\my recordings" --out "D:\\khmer-dataset"
    python prep_voice_dataset.py --in ... --out ... --denoise
    python prep_voice_dataset.py --out "D:\\khmer-dataset" --check     # report only
"""
import argparse
import array
import json
import math
import os
import shutil
import subprocess
import sys
import time

AUDIO_EXT = (".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus",
             ".wma", ".aiff", ".aif", ".mp4", ".mkv", ".webm", ".amr", ".3gp")

HERE = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------
# ffmpeg: use the copy the user already has (RVC folder, PATH, or the studio's)
# --------------------------------------------------------------------------
def find_ffmpeg():
    cands = []
    if os.environ.get("FFMPEG"):
        cands.append(os.environ["FFMPEG"])
    for name in ("ffmpeg.exe", "ffmpeg"):
        w = shutil.which(name)
        if w:
            cands.append(w)
    # next to the pipeline, or inside the configured RVC folder
    roots = [HERE, os.path.dirname(HERE),
             os.path.dirname(os.path.dirname(HERE))]
    try:
        with open(os.path.join(HERE, "config.json"), "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if cfg.get("rvc_root"):
            roots.append(cfg["rvc_root"])
    except Exception:
        pass
    for r in roots:
        for name in ("ffmpeg.exe", "ffmpeg", os.path.join("ffmpeg", "ffmpeg.exe"),
                     os.path.join("ffmpeg", "bin", "ffmpeg.exe")):
            cands.append(os.path.join(r, name))
    for c in cands:
        try:
            if c and os.path.exists(c):
                return c
        except Exception:
            pass
    try:  # the studio's bundled binary, if this python happens to have it
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return ""


def run(cmd, timeout=3600):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=timeout)
    return p.returncode, p.stdout.decode("utf-8", "replace"), \
        p.stderr.decode("utf-8", "replace")


def probe_duration(ffmpeg, path):
    """Duration in seconds using ffmpeg itself (no ffprobe dependency)."""
    rc, out, err = run([ffmpeg, "-hide_banner", "-i", path, "-f", "null", "-"])
    txt = err
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            try:
                hms = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = hms.split(":")
                return int(h) * 3600 + int(m) * 60 + float(s)
            except Exception:
                return 0.0
    return 0.0


# --------------------------------------------------------------------------
# measuring a finished WAV (pure stdlib — no numpy needed on the user's PC)
# --------------------------------------------------------------------------
def wav_stats(path, sr=40000):
    """peak dBFS, RMS dBFS, silence %, clipped %, noise-floor estimate."""
    with open(path, "rb") as f:
        data = f.read()
    # find the data chunk (44-byte canonical header, but stay tolerant)
    i = data.find(b"data")
    if i < 0:
        return None
    pcm = data[i + 8:]
    samples = array.array("h")
    samples.frombytes(pcm[:len(pcm) - (len(pcm) % 2)])
    n = len(samples)
    if n == 0:
        return None
    win = max(1, int(sr * 0.02))              # 20 ms windows
    peak = 0
    clip = 0
    sil = 0
    sum_sq = 0.0
    win_rms = []
    for w0 in range(0, n, win):
        chunk = samples[w0:w0 + win]
        if not chunk:
            break
        s = 0.0
        pk = 0
        for v in chunk:
            av = v if v >= 0 else -v
            if av > pk:
                pk = av
            if av >= 32700:
                clip += 1
            s += float(v) * float(v)
        sum_sq += s
        r = math.sqrt(s / len(chunk)) / 32768.0
        win_rms.append(r)
        if r < 0.0032:                        # about -50 dBFS
            sil += len(chunk)
        if pk > peak:
            peak = pk
    rms = math.sqrt(sum_sq / n) / 32768.0
    # noise floor: the 10th percentile of window levels
    win_rms.sort()
    nf = win_rms[int(len(win_rms) * 0.10)] if win_rms else 0.0

    def db(x):
        return round(20 * math.log10(x), 1) if x > 0 else -99.0
    return {
        "seconds": round(n / float(sr), 2),
        "peak_db": db(peak / 32768.0),
        "rms_db": db(rms),
        "silence_pct": round(100.0 * sil / n, 1),
        "clipped_pct": round(100.0 * clip / n, 3),
        "noisefloor_db": db(nf),
    }


# --------------------------------------------------------------------------
def convert_one(ffmpeg, src, dst, sr, denoise, trim=True):
    af = ["highpass=f=70"]
    if denoise:
        af.append("afftdn=nr=10:nf=-45")
    # keep 0.2 s of any silence so nothing sounds chopped; drop long dead air
    if trim:
        af.append("silenceremove=stop_periods=-1:stop_duration=0.4:"
                  "stop_threshold=-45dB:stop_silence=0.2")
    af.append("alimiter=limit=0.89:level=0")          # ceiling -1 dBFS, no pumping
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-i", src, "-vn", "-ac", "1", "-ar", str(sr),
           "-af", ",".join(af), "-c:a", "pcm_s16le", dst]
    rc, out, err = run(cmd)
    return rc, err.strip()


def split_long(ffmpeg, path, minutes):
    """Cut one long file into <=minutes parts (silence-aware enough: RVC slices
    every file again anyway). Keeps the first part in place, returns all paths."""
    base, ext = os.path.splitext(path)
    pattern = base + "_pt%02d" + ext
    rc, out, err = run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                        "-i", path, "-f", "segment",
                        "-segment_time", str(int(minutes) * 60),
                        "-reset_timestamps", "1", "-c", "copy", pattern])
    if rc != 0:
        return []
    folder = os.path.dirname(path)
    stem = os.path.basename(base)
    parts = sorted(os.path.join(folder, f) for f in os.listdir(folder)
                   if f.startswith(stem + "_pt") and f.endswith(ext))
    return parts


def main():
    ap = argparse.ArgumentParser(
        description="Prepare your recordings for RVC voice training.")
    ap.add_argument("--in", dest="indir", default="",
                    help="folder with your recordings (searched recursively)")
    ap.add_argument("--out", dest="outdir", default="",
                    help="folder for the training-ready dataset")
    ap.add_argument("--sr", type=int, default=40000,
                    help="sample rate: 40000 (recommended) or 48000")
    ap.add_argument("--denoise", action="store_true",
                    help="light spectral noise reduction (use if you hear hiss)")
    ap.add_argument("--no-trim", action="store_true",
                    help="keep the pauses exactly as recorded (default: trim long silence)")
    ap.add_argument("--check", action="store_true",
                    help="only measure an existing --out folder, no conversion")
    ap.add_argument("--split-long", type=int, default=0, metavar="MIN",
                    help="also split output files longer than MIN minutes")
    args = ap.parse_args()

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("=" * 70)
        print(" FFMPEG NOT FOUND")
        print("=" * 70)
        print(" Your RVC folder, this package and the PATH were all checked.")
        print(" Fix it one of these ways:")
        print("   * put ffmpeg.exe next to this script (the RVC-WebUI folder has one),")
        print("   * or tell us where it is:  set FFMPEG=D:\\path\\ffmpeg.exe")
        print("     (then run this tool again in the same window)")
        return 2

    print("=" * 70)
    print(" SONORA — KHMER VOICE DATASET PREPARATION")
    print("=" * 70)
    print(" ffmpeg : " + ffmpeg)

    if args.check:
        if not os.path.isdir(args.outdir):
            print(" !! folder not found: " + args.outdir)
            return 2
        files = [os.path.join(args.outdir, f) for f in sorted(os.listdir(args.outdir))
                 if f.lower().endswith(".wav")]
        report_all(files, args.outdir, [], 0.0)
        return 0

    if not os.path.isdir(args.indir):
        print(" !! folder not found: " + (args.indir or "(no --in given)"))
        return 2
    if not args.outdir:
        print(" !! --out is required (where the dataset should be written)")
        return 2
    if os.path.abspath(args.indir) == os.path.abspath(args.outdir):
        print(" !! --in and --out must be different folders (your recordings are never touched)")
        return 2

    os.makedirs(args.outdir, exist_ok=True)

    srcs = []
    for dp, dn, fn in os.walk(args.indir):
        for f in sorted(fn):
            if f.lower().endswith(AUDIO_EXT):
                srcs.append(os.path.join(dp, f))
    if not srcs:
        print(" !! no audio files in " + args.indir)
        print("    (looked for: " + ", ".join(AUDIO_EXT[:8]) + " ...)")
        return 2

    print(" source : " + args.indir)
    print(" output : " + args.outdir)
    print(" found  : %d file(s)" % len(srcs))
    print("")

    t0 = time.time()
    made, failed = [], []
    n = 0
    src_seconds = 0.0
    for src in srcs:
        n += 1
        name = "km_%04d.wav" % n
        dst = os.path.join(args.outdir, name)
        dur_in = probe_duration(ffmpeg, src)
        src_seconds += dur_in
        rc, err = convert_one(ffmpeg, src, dst, args.sr, args.denoise,
                              trim=not args.no_trim)
        if rc != 0 or not os.path.exists(dst) or os.path.getsize(dst) < 2000:
            failed.append((src, err[:200] or "conversion failed"))
            print("  [FAIL] %s" % os.path.basename(src))
            continue
        if args.split_long and dur_in > args.split_long * 60 + 5:
            parts = split_long(ffmpeg, dst, args.split_long)
            if parts:
                os.remove(dst)
                for extra in parts[1:]:
                    made.append(extra)
                dst = parts[0]
        made.append(dst)
        st = wav_stats(dst, args.sr)
        print("  [ ok ] %-34s %6.1f s in -> %6.1f s out  peak %5.1f dBFS  "
              "silence %4.1f%%" % (os.path.basename(src)[:34],
                                   dur_in, st["seconds"] if st else 0,
                                   st["peak_db"] if st else 0,
                                   st["silence_pct"] if st else 0))
    print("")
    print(" converted %d of %d in %.0f s" % (len(made), len(srcs), time.time() - t0))
    if failed:
        print(" FAILED:")
        for s, e in failed[:8]:
            print("   %s\n     %s" % (s, e))

    report_all(made, args.outdir, failed, src_seconds, args.sr)


def report_all(files, outdir, failed, src_seconds, sr=40000):
    rows, total, bad = [], 0.0, []
    for p in files:
        st = wav_stats(p, sr)
        if not st:
            continue
        total += st["seconds"]
        rows.append((os.path.basename(p), st))
        if st["clipped_pct"] > 0.5:
            bad.append((os.path.basename(p),
                        "clipping %.2f%% — record quieter (peak -3 dBFS)" % st["clipped_pct"]))
        elif st["noisefloor_db"] > -38:
            bad.append((os.path.basename(p),
                        "noisy (floor %.0f dBFS) — try --denoise, or record in a quieter room"
                        % st["noisefloor_db"]))
        elif st["seconds"] < 2.0:
            bad.append((os.path.basename(p),
                        "only %.1f s of speech — too short to help" % st["seconds"]))

    mins = total / 60.0
    print("_" * 70)
    print(" DATASET REPORT")
    print("_" * 70)
    print(" clips            : %d" % len(rows))
    print(" clean speech     : %.1f min  (%.0f s)" % (mins, total))
    if rows:
        avg = total / len(rows)
        print(" average clip     : %.1f s" % avg)
        print(" peak / RMS       : %.1f / %.1f dBFS (typical)"
              % (rows[0][1]["peak_db"], rows[0][1]["rms_db"]))
    if failed:
        print(" unreadable files : %d  (see list above)" % len(failed))

    if mins >= 30:
        verdict = ("GOOD — %.1f minute(s) is in the professional range. "
                   "Train it and it will sound like you." % mins)
    elif mins >= 10:
        verdict = ("WORKABLE — %.1f minute(s). RVC's own guidance is 10-50 min; "
                   "more recordings = fuller, more natural voice." % mins)
    elif mins >= 5:
        verdict = ("THIN — only %.1f minute(s). It will work, but expect the "
                   "carrier's accent to leak through. Aim for 20-30 min." % mins)
    else:
        verdict = ("TOO LITTLE — %.1f minute(s). Record more before training; "
                   "under 5 minutes rarely gives a usable voice." % mins)
    print("")
    print(" VERDICT: " + verdict)
    if bad:
        print("")
        print(" %d file(s) to look at:" % len(bad))
        for n, why in bad[:12]:
            print("   - %s : %s" % (n, why))

    # ---- write the two text files into the dataset folder ----------------
    rp = os.path.join(outdir, "DATASET-REPORT.txt")
    with open(rp, "w", encoding="utf-8") as f:
        f.write("SONORA — KHMER VOICE DATASET REPORT\n")
        f.write("written: %s\n\n" % time.strftime("%Y-%m-%d %H:%M"))
        f.write("clips        : %d\n" % len(rows))
        f.write("clean speech : %.1f min\n" % mins)
        f.write("verdict      : %s\n" % verdict)
        if failed:
            f.write("\nunreadable:\n")
            for s, e in failed:
                f.write("  %s\n    %s\n" % (s, e))
        if bad:
            f.write("\nneeds attention:\n")
            for n, why in bad:
                f.write("  %s : %s\n" % (n, why))
        f.write("\nper clip:\n")
        for n, st in rows:
            f.write("  %-14s %7.2f s  peak %6.1f  rms %6.1f  silence %5.1f%%  "
                    "floor %6.1f  clipped %.3f%%\n"
                    % (n, st["seconds"], st["peak_db"], st["rms_db"],
                       st["silence_pct"], st["noisefloor_db"], st["clipped_pct"]))
    print("")
    print(" written: " + rp)

    tip = os.path.join(outdir, "RVC-TRAIN-SETTINGS.txt")
    with open(tip, "w", encoding="utf-8") as f:
        f.write(RVC_SETTINGS_TEXT % {"folder": outdir})
    print(" written: " + tip)
    print("")
    print(" NEXT: open RVC-WebUI -> Train tab and use RVC-TRAIN-SETTINGS.txt")
    print("       (step-by-step walkthrough: Khmer-RVC-Training-Walkthrough.md)")
    return rows


RVC_SETTINGS_TEXT = """\
SONORA — SETTINGS FOR THE RVC-WebUI TRAIN TAB  (step by step)
============================================================
Everything below matches the boxes you see on the Train screen.

STEP 1  (top row)
  Enter the experiment name ............ sonaro_kh2
  Target sample rate .................. select 40k
  Whether the model has pitch guidance . true
  Version ............................. v2
  Number of CPU processes ............. 4   (11 pegs the CPU; 4 keeps the PC usable)

STEP 2a (process the audio)
  Enter the path of the training folder  %(folder)s
  Please specify the speaker/singer ID . 0
  -> press  Process data
     wait for "step 1: processing data ... Successfully"

STEP 2b (features)
  Enter the GPU index(es) .............. 0
  Select the pitch extraction algorithm  rmvpe   (do NOT change this)
  -> press  Feature extraction
     wait for "step 2b: extracting features ... Successfully"

STEP 3 (the model)
  Save frequency (save_every_epoch) .... 10
  Total training epochs (total_epoch) .. 200
  Batch size per GPU ................... 3    (RTX 3060 Laptop 6 GB; if it says
                                             CUDA out of memory, use 2)
  Save only the latest .pth file ...... No   (keep the history, test several)
  Cache all training set to GPU memory . No   (6 GB is not enough)
  Save a small model to the 'weights' folder at each save point ... YES  <-- set this
  Load pre-trained base model G path .. assets\\pretrained_v2\\f0G40k.pth
  Load pre-trained base model D path .. assets\\pretrained_v2\\f0D40k.pth
  Enter the GPU index(es) .............. 0
  -> press  Train model
     watch the console: the first 10 epochs tell you the total time.

STEP 4 (the index — this is what removes the "accent leak")
  -> press  Train feature index
     result:  logs\\<experiment>\\added_IVF*.index
  Copy that .index into  assets\\indices\\   (next to your other .index files)
  Sonora finds it automatically when the name matches the model.

STEP 5 (put it in Sonora)
  RVC VOICE CLONE -> MODEL (.PTH)   assets\\weights\\<experiment>_...e_...s.pth
  INDEX (.INDEX)                    leave blank  (auto-detect)
  PITCH                             0        (try +1 / +2 only if the clone
                                              sounds lower or duller than you)
  INDEX RATE                        0.75     (0.6 = safer/faster, 0.8 = closer to you)
  BASE VOICE                        the Khmer voice you already use
  -> press  Test clone  and then  A/B  to hear it against the plain voice

WHAT "GOOD" SOUNDS LIKE
  * same words, same pronunciation as the plain voice
  * the timbre is YOU, not the base voice
  * no metallic ring, no crackle, no breathing gaps
  * if it sounds muffled -> train more epochs (150-250)
  * if it sounds noisy/warbly -> too many epochs, or noisy recordings
"""


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\n stopped.")
        sys.exit(1)
