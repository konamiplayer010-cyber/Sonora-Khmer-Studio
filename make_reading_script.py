#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""make_reading_script.py — turn a Khmer text into something you can READ ALOUD
to record your RVC training dataset (menu 13, option 2).

WHY
    To train your own voice you need 30-60 minutes of YOU reading Khmer.
    Reading straight out of a book file is hard: no breath marks, no progress,
    no idea how long you have been going. This makes a clean reader's copy:

      * one sentence per line, numbered, with a running time estimate
      * a breath mark every 10 sentences ("pause 2 s")
      * chapter / paragraph breaks kept
      * a header with the recording rules (mic distance, no music, one room)
      * it stops at your target length (default 40 minutes of speech)

    Output is a plain .txt — open it in Notepad, or on your phone with any
    reader app, and start talking. It never modifies your source file.

USAGE (Windows: menu 13 -> option 2, or double-click)
    python make_reading_script.py --in "D:\\mybook.txt" --out "D:\\reading-script.txt"
    python make_reading_script.py --in book.md --minutes 60 --all
"""
import argparse
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# the pipeline's own Khmer tools (sentence splitting + number/digit normalising)
try:
    import common  # noqa: E402
    HAVE_COMMON = True
except Exception:
    HAVE_COMMON = False

CHARS_PER_SEC = 9.0        # calm read-aloud pace for Khmer (rough, +/-15%)
BREATH_EVERY = 10          # sentences between breath marks


def split_sentences(text):
    if HAVE_COMMON:
        try:
            out = common.split_sentences(text)
            if out:
                return [s.strip() for s in out if s and s.strip()]
        except Exception:
            pass
    # fallback: Khmer khan + western punctuation
    parts = re.split(r"(?<=[\u17D4\u17D5\u17D6.!?…])\s+|\n+", text)
    return [p.strip() for p in parts if p and p.strip()]


def normalize(text):
    """common.normalize_khmer returns (text, stats) — accept both shapes."""
    if HAVE_COMMON:
        try:
            r = common.normalize_khmer(text)
            if isinstance(r, tuple):
                r = r[0]
            if isinstance(r, str) and r.strip():
                return r
        except Exception:
            pass
    return text


def est_seconds(s):
    return len(s) / CHARS_PER_SEC


def mmss(seconds):
    seconds = int(round(seconds))
    return "%d:%02d" % (seconds // 60, seconds % 60)


HEADER = """\
================================================================
  KHMER RECORDING SCRIPT  —  read this aloud to train your voice
================================================================
  prepared      : {when}
  source        : {src}
  sentences     : {n}
  estimated read: {mins:.1f} minutes at a calm pace
  target        : {target} minutes   {note}

  HOW TO RECORD (this is what makes the clone sound like you)
   * the SAME microphone and the SAME distance (~15-20 cm) for every session
   * a quiet, soft room: curtains, clothes, bed. No fan, no music, no TV,
     no other people talking. Close the door and the window.
   * read at your normal, calm speed. Do not act, do not whisper.
   * if you make a mistake: stop, breathe, say the sentence again. The bad
     take is simply ignored by the trainer.
   * record in sessions of 15-20 minutes. Between sessions, do not move the
     microphone and do not change the room.
   * when you are done, put ALL the files of this script in ONE folder and
     run  menu 13 option 1  to build the training dataset.

  Pauses marked  >> pause 2 s  are for breathing - silence is fine and useful.

----------------------------------------------------------------
"""


def main():
    ap = argparse.ArgumentParser(description="Make a Khmer reading script for voice recording.")
    ap.add_argument("--in", dest="src", required=True, help="your Khmer text file (.txt/.md)")
    ap.add_argument("--out", dest="dst", default="", help="where to write the reading script")
    ap.add_argument("--minutes", type=float, default=40.0,
                    help="how many minutes of speech to include (default 40)")
    ap.add_argument("--all", action="store_true", help="include the whole text, ignore --minutes")
    ap.add_argument("--normalize", action="store_true",
                    help="also expand numbers/dates the way the studio speaks them "
                         "(default: keep your text as written - you are reading it, not a machine)")
    args = ap.parse_args()

    if not os.path.exists(args.src):
        print(" !! file not found: " + args.src)
        return 2
    dst = args.dst or os.path.splitext(args.src)[0] + "-reading-script.txt"

    with open(args.src, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    text = normalize(raw) if args.normalize else raw
    # drop lines that are pure markup (markdown headers keep their text)
    lines = []
    for ln in text.splitlines():
        ln = re.sub(r"^\s{0,3}#{1,6}\s*", "", ln.rstrip())
        ln = re.sub(r"^\s*[-*]\s+", "", ln)
        lines.append(ln)
    text = "\n".join(lines)

    sentences = split_sentences(text)
    if not sentences:
        print(" !! no text found in " + args.src)
        return 2

    # take sentences until the target length is reached
    picked, total = [], 0.0
    for s in sentences:
        if not args.all and total >= args.minutes * 60 and picked:
            break
        picked.append(s)
        total += est_seconds(s)
    if not args.all and len(picked) < len(sentences):
        note = "(stopped at the target - run again with --all for the whole text)"
    else:
        note = "(the whole text fits in the target)" if total <= args.minutes * 60 \
            else "(the whole text - longer than the target, that is fine)"

    body, sec, n = [], 0.0, 0
    for i, s in enumerate(picked, 1):
        n += 1
        body.append("%3d  %s" % (i, s))
        sec += est_seconds(s)
        if n % BREATH_EVERY == 0:
            body.append("")
            body.append("      >> pause 2 s   (breath)   ~ running time %s" % mmss(sec))
            body.append("")
    if n % BREATH_EVERY:
        body.append("")
        body.append("      >> pause 2 s   (breath)   ~ running time %s" % mmss(sec))

    with open(dst, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(HEADER.format(when=time.strftime("%Y-%m-%d %H:%M"), src=os.path.abspath(args.src),
                              n=len(picked), mins=total / 60.0, target=args.minutes, note=note))
        f.write("\n".join(body))
        f.write("\n\n=====================  END OF SCRIPT  =====================\n")

    print("=" * 64)
    print(" KHMER READING SCRIPT")
    print("=" * 64)
    print(" source      : " + os.path.abspath(args.src))
    print(" written     : " + os.path.abspath(dst))
    print(" sentences   : %d" % len(picked))
    print(" estimated   : %.1f min of speech (calm pace, +/-15%%)" % (total / 60.0))
    if len(picked) < len(sentences):
        print(" remaining   : %d sentence(s) left over — run again with --all"
              % (len(sentences) - len(picked)))
    print("")
    print(" NEXT: read it aloud and record. Then  menu 13 option 1  to build")
    print("       the training dataset, and RVC-TRAIN-SETTINGS.txt to train.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\n stopped.")
        sys.exit(1)
