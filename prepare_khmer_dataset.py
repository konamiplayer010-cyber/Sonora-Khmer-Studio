#!/usr/bin/env python3
"""prepare_khmer_dataset.py — turn your recordings into a TTS training set.

Run this on YOUR PC, before (or alongside) the Colab notebook. It takes
recordings + text and produces the exact dataset shape the VITS/MMS
fine-tuning recipe expects:

    khmer-dataset/
        audio/0001.wav ...          mono 16-bit wav, 1-20 s each
        metadata.jsonl              {"audio": "...", "text": "..."} per line
        report.txt                  what was found / fixed / skipped

Accepted inputs (pick whichever matches what you have):

  1. a folder of pairs            clip1.wav + clip1.txt (same name)
       python prepare_khmer_dataset.py --in "D:\\my recordings"
  2. one text file, one line per clip
       file-or-name|Khmer text here
       python prepare_khmer_dataset.py --in "D:\\rec" --texts script.txt
  3. an OpenSLR-style line index (e.g. SLR42 Khmer)
       python prepare_khmer_dataset.py --in "D:\\km_kh_male" --openslr

What it checks (and why each one matters for a good voice):
  * text is actually Khmer script          -> the MMS tokenizer is Khmer-only
  * one speaker only                       -> mixed voices = smeared voice
  * 1-20 s per clip                        -> the recipe's own window
  * not silent / not clipping              -> silent clips teach nothing
  * wav is readable and mono-ised          -> VITS wants plain PCM
It rewrites audio to 16 kHz mono wav by default (what MMS trains on).
"""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
# the package's Khmer normalizer lives in ../pipeline (bundle) or ../AI_Agent;
# try both so this script also runs straight from a checkout
for _cand in (HERE.parent / "pipeline", HERE.parent / "AI_Agent",
              HERE.parent.parent / "pipeline"):
    if (_cand / "common.py").exists():
        sys.path.insert(0, str(_cand))
        break
try:
    import common as C            # the package's Khmer normalizer
except Exception as _e:
    C = None
    print(f"[note] Khmer normalizer not available ({_e}); "
          f"text will be kept as written")

KHMER_RE = re.compile(r"[\u1780-\u17FF]")
MIN_S, MAX_S = 1.0, 20.0
TARGET_SR = 16000


def find_ffmpeg():
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return ""


def wav_info(path):
    """(seconds, rate, channels, peak, rms) or None."""
    try:
        with wave.open(str(path), "rb") as w:
            n, sr, ch = w.getnframes(), w.getframerate(), w.getnchannels()
            data = w.readframes(n)
        import array
        a = array.array("h")
        a.frombytes(data[:len(data) // 2 * 2])
        if not len(a):
            return None
        peak = max(abs(min(a)), abs(max(a))) / 32768.0
        rms = (sum(v * v for v in a) / len(a)) ** 0.5 / 32768.0
        return n / float(sr), sr, ch, peak, rms
    except Exception:
        return None


def to_wav16k(src, dst, ffmpeg):
    cmd = [ffmpeg, "-v", "error", "-y", "-i", str(src),
           "-ac", "1", "-ar", str(TARGET_SR), "-c:a", "pcm_s16le",
           "-f", "wav", str(dst)]
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0 and os.path.exists(dst)


def load_pairs(args):
    """-> list of (audio_path, text, source_label)"""
    root = Path(args.in_dir)
    out = []
    if not root.exists():
        print(f"[FAIL] input folder not found: {root}")
        sys.exit(1)

    if args.openslr:
        idx = None
        for cand in ("line_index.tsv", "line_index.txt", "metadata.csv"):
            if (root / cand).exists():
                idx = root / cand
                break
        if idx is None:
            print("[FAIL] no line_index.tsv / metadata.csv in that folder")
            sys.exit(1)
        sep = "\t" if idx.suffix == ".tsv" else ","
        with open(idx, encoding="utf-8") as fh:
            for row in csv.reader(fh, delimiter=sep):
                if len(row) < 2:
                    continue
                name, text = row[0].strip(), sep.join(row[1:]).strip()
                for sub in ("wavs", "wav", ""):
                    p = root / sub / (name + ".wav") if sub else root / (name + ".wav")
                    if p.exists():
                        out.append((p, text, name))
                        break
        return out

    if args.texts:
        tf = Path(args.texts)
        if not tf.is_absolute():
            tf = root / tf
        with open(tf, encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line.strip() or "|" not in line:
                    continue
                name, text = line.split("|", 1)
                name, text = name.strip(), text.strip()
                hit = None
                for ext in (".wav", ".mp3", ".m4a", ".flac", ".ogg"):
                    p = root / (name + ext)
                    if p.exists():
                        hit = p
                        break
                if hit:
                    out.append((hit, text, name))
        return out

    for p in sorted(root.rglob("*")):
        if p.suffix.lower() not in (".wav", ".mp3", ".m4a", ".flac", ".ogg"):
            continue
        txt = p.with_suffix(".txt")
        if txt.exists():
            out.append((p, txt.read_text(encoding="utf-8").strip(), p.stem))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_dir", required=True,
                    help="folder with your recordings")
    ap.add_argument("--out", default="khmer-dataset",
                    help="where to build the training set")
    ap.add_argument("--texts", default="", help="one 'name|text' per line")
    ap.add_argument("--openslr", action="store_true",
                    help="input is an OpenSLR-style folder (line_index.tsv)")
    ap.add_argument("--no-normalize", action="store_true",
                    help="keep text exactly as written (default: apply the "
                         "package's Khmer normalizer so numbers are spoken)")
    ap.add_argument("--keep-rate", action="store_true",
                    help="do not convert audio (must already be 16 kHz mono)")
    a = ap.parse_args()

    pairs = load_pairs(a)
    print(f"found {len(pairs)} audio/text pair(s) in {a.in_dir}")
    if not pairs:
        print("\nNothing to do. Layouts accepted:")
        print("  clip1.wav + clip1.txt (same name, same folder)")
        print("  name|Khmer text in a single file   (--texts file.txt)")
        print("  OpenSLR folder with line_index.tsv  (--openslr)")
        sys.exit(1)

    ff = find_ffmpeg()
    if not ff and not a.keep_rate:
        print("[FAIL] ffmpeg not found (pip install imageio-ffmpeg)")
        sys.exit(1)

    out = Path(a.out)
    (out / "audio").mkdir(parents=True, exist_ok=True)
    kept, skipped = [], []
    total_s = 0.0

    for audio, text, label in pairs:
        raw_text = text
        if C is not None and not a.no_normalize:
            text = C.normalize_khmer(text)[0]
        if not KHMER_RE.search(text):
            skipped.append((label, "no Khmer script in the text"))
            continue
        if len(text) < 2:
            skipped.append((label, "text too short"))
            continue

        dst = out / "audio" / (re.sub(r"[^\w.-]", "_", label) + ".wav")
        if a.keep_rate:
            shutil.copy(audio, dst)
        else:
            if not to_wav16k(audio, dst, ff):
                skipped.append((label, "could not convert audio"))
                continue

        info = wav_info(dst)
        if not info:
            skipped.append((label, "unreadable wav"))
            dst.unlink(missing_ok=True)
            continue
        dur, sr, ch, peak, rms = info
        if dur < MIN_S:
            skipped.append((label, f"too short ({dur:.2f}s < {MIN_S}s)"))
            dst.unlink(missing_ok=True)
            continue
        if dur > MAX_S:
            skipped.append((label, f"too long ({dur:.1f}s > {MAX_S}s) — "
                                   f"split it and re-run"))
            dst.unlink(missing_ok=True)
            continue
        if rms < 0.002:
            skipped.append((label, f"almost silent (rms {rms:.4f})"))
            dst.unlink(missing_ok=True)
            continue
        if peak > 0.999:
            note = "clipping — consider lowering the level"

        kept.append({"audio": str((Path("audio") / dst.name).as_posix()),
                     "text": text})
        total_s += dur
        if len(kept) % 25 == 0:
            print(f"  ... {len(kept)} clips ({total_s / 60:.1f} min)")

    with open(out / "metadata.jsonl", "w", encoding="utf-8") as fh:
        for row in kept:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    lines = [f"clips kept     : {len(kept)}",
             f"clips skipped  : {len(skipped)}",
             f"total duration : {total_s / 60:.1f} min",
             f"sample rate    : {TARGET_SR} Hz mono (or original with --keep-rate)",
             ""]
    if kept:
        avg = total_s / len(kept)
        lines.append(f"average clip   : {avg:.1f} s")
        if total_s < 3 * 60:
            lines.append("NOTE: under ~3 minutes of audio. The recipe can work "
                         "with 80-150 short clips, but 20-60+ minutes gives a "
                         "much steadier voice.")
    for label, why in skipped[:40]:
        lines.append(f"  skipped {label}: {why}")
    if len(skipped) > 40:
        lines.append(f"  ... and {len(skipped) - 40} more")
    report = "\n".join(lines)
    (out / "report.txt").write_text(report, encoding="utf-8")

    print("\n" + report)
    print(f"\ndataset -> {out.resolve()}")
    print("Next: upload that folder in the Colab notebook "
          "(khmer-colab/Khmer_Voice_Colab.ipynb).")
    return 0 if kept else 1


if __name__ == "__main__":
    sys.exit(main())
