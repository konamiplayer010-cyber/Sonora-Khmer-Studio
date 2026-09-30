#!/usr/bin/env python3
"""build_style_demo.py — hear every narration style on one Khmer passage.

Rebuilds `demo/narration-styles.mp3` (+ `narration-styles.txt`): the same
passage performed in ALL FOURTEEN narration styles, in the same order as the
studio panel, each segment announced by its own name in Khmer.

  python build_style_demo.py                 # all 13 -> demo/narration-styles.mp3
  python build_style_demo.py --only cinematic  # one segment -> its own file,
                                             # the full demo is left alone
  python build_style_demo.py --voice km-KH-PisethNeural

It speaks with the same engine the studio uses (edge-tts) and runs the real
engine (`narration.render_styled`), so the pauses, the pace and the whisper are
the shipped behaviour, not a re-recording. Each style performs the passage in
its own way — its own pace, its own softness, its own pauses — while the
speaker never changes: pitch stays at 0.0 st in all 13. A whisper is a MOMENT
`whisper.py`, the same stage a brief whispered line uses.

Needs internet (edge-tts). Output: 48 kHz / 192 kbps mp3, -16 LUFS.
"""

import argparse
import asyncio
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import narration as NAR                                   # noqa: E402

DEMO_DIR = os.path.join(HERE, "demo")
OUT_RATE = 48000
OUT_KBPS = 192

VOICE = "km-KH-SreymomNeural"

# the panel order, the Khmer name of the style, and that style's pause preset
# (identical to the studio cards)
STYLES = [
    ("natural",       "ការអានធម្មជាតិ",             0.10),
    ("documentary",   "ខ្សែភាពយន្តឯកសារ",            0.40),
    ("trailer",       "ឈុតផ្សាយភាពយន្ត",              0.70),
    ("audiobook",     "សៀវភៅសំឡេង",                 0.30),
    ("news",          "អ្នកអានសារព័ត៌មាន",            0.10),
    ("explainer",     "ការពន្យល់",                    0.20),
    ("thriller",      "រឿងភ័យរន្ធត់",                 0.60),
    ("meditation",    "សមាធិ",                        1.40),
    ("storytelling",  "ការនិទានរឿង",                  0.35),
    ("novel",         "ប្រលោមលោក",                     0.30),
    ("inner_monologue", "ការគិតក្នុងចិត្ត",             0.45),
    ("sad_romantic",  "ស្នេហាសោកសង្រេង",             0.50),
    ("cinematic",     "រឿងភាគអារម្មណ៍ខ្លាំង",         0.45),
]

ORDINALS = ["មួយ", "ពីរ", "បី", "បួន", "ប្រាំ", "ប្រាំមួយ", "ប្រាំពីរ",
            "ប្រាំបី", "ប្រាំបួន", "ដប់", "ដប់មួយ", "ដប់ពីរ", "ដប់បី"]

# one passage, all thirteen styles — calm, concrete, and it gives the
# performance something to do (a night scene, a voice, a reveal at the end)
PASSAGE = (
    "រាត្រីនៅភូមិភ្នំស្ងប់ស្ងាត់។ "
    "ផ្កាយរាប់ពាន់បំភ្លឺផ្ទៃមេឃ ហើយខ្យល់ត្រជាក់បក់មកពីជ្រលង។ "
    "យុវតីម្នាក់អង្គុយក្បែរភ្លើង រៀបរាប់រឿងព្រេងរបស់ភូមិ "
    "ឲ្យកូនតូចស្តាប់។"
)


def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def speak(text, dst, rate="+0%", voice=VOICE):
    """One plain sentence through edge-tts -> dst (mp3)."""
    import edge_tts

    async def run():
        comm = edge_tts.Communicate(text, voice, rate=rate)
        buf = b""
        async for msg in comm.stream():
            if msg.get("type") == "audio":
                buf += msg["data"]
        if not buf:
            raise RuntimeError("empty audio")
        return buf

    data = asyncio.run(run())
    with open(dst, "wb") as f:
        f.write(data)
    return {"ok": True, "engine": "edge"}


def decode(path, rate=OUT_RATE):
    import numpy as np
    r = subprocess.run([ffmpeg(), "-v", "error", "-i", path, "-ac", "1",
                        "-ar", str(rate), "-f", "f32le", "pipe:1"],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return np.zeros(0, dtype="float32")
    return np.frombuffer(r.stdout, dtype="float32")


def write_wav(path, arr, rate=OUT_RATE):
    import numpy as np
    pcm = (np.clip(arr, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def stamp(sec):
    m, s = divmod(sec, 60)
    return "%d:%05.2f" % (int(m), s)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", action="append", default=[],
                    help="style id (repeatable)")
    ap.add_argument("--voice", default=VOICE)
    ap.add_argument("--speed", type=float, default=1.0,
                    help="the studio's NARRATION SPEED (1.0 = as shipped)")
    args = ap.parse_args()

    import numpy as np

    wanted = [(s, n, p) for (s, n, p) in STYLES
              if not args.only or s in args.only]
    if not wanted:
        print("no such style:", ", ".join(args.only))
        return 2

    os.makedirs(DEMO_DIR, exist_ok=True)
    print("voice   : %s" % args.voice)
    print("passage : %d sentences, %d characters"
          % (len(NAR.split_sentences(PASSAGE)), len(PASSAGE)))
    print("output  : %d Hz / %d kbps mp3, -16 LUFS\n" % (OUT_RATE, OUT_KBPS))

    with tempfile.TemporaryDirectory() as td:
        pieces, index, t = [], [], 0.0
        for i, (sid, name, pause) in enumerate(STYLES, 1):
            if sid not in [w[0] for w in wanted]:
                continue
            label_txt = "រចនាបទទី%s។ %s។" % (ORDINALS[i - 1], name)
            label_mp3 = os.path.join(td, "label_%s.mp3" % sid)
            try:
                speak(label_txt, label_mp3, "+0%", args.voice)
            except Exception as e:
                print("  [FAIL] label %s: %s" % (sid, str(e)[:90]))
                continue
            block_wav = os.path.join(td, "block_%s.wav" % sid)
            res = NAR.render_styled(PASSAGE, block_wav, sid,
                                    lambda text, dst, rate, pitch: speak(
                                        text, dst, rate, args.voice),
                                    ffmpeg=ffmpeg(), speed=args.speed,
                                    pause=pause, sr=24000, engine_name="edge",
                                    log=lambda m: print("    " + m))
            if not res.get("ok"):
                print("  [FAIL] %-16s %s" % (sid, res.get("error")))
                continue
            label = decode(label_mp3)
            block = decode(block_wav)
            index.append((t, sid, name, pause, res))
            pieces.append(label)
            t += len(label) / float(OUT_RATE)
            gap = np.zeros(int(0.55 * OUT_RATE), dtype="float32")
            pieces.append(gap)
            t += 0.55
            pieces.append(block)
            t += len(block) / float(OUT_RATE)
            parts = [x for x in (label, block)]
            peak = max(float(np.max(np.abs(x))) if x.size else 0.0 for x in parts)
            print("  [ OK ] %-16s %5.1fs  pause %.2fs  rate %s  whisper %s  "
                  "deliveries %s"
                  % (sid, res["seconds"], pause,
                     ",".join("%.2f" % r for r in
                              sorted({p["rate"] for p in
                                      NAR.plan_text(PASSAGE, style=sid,
                                                    speed=args.speed,
                                                    pause=pause)})),
                     "yes" if any(p.get("whisper") for p in
                                  NAR.plan_text(PASSAGE, style=sid,
                                                speed=args.speed, pause=pause))
                     else "no",
                     ", ".join(sorted({p.get("delivery", "-") for p in
                                       NAR.plan_text(PASSAGE, style=sid,
                                                     speed=args.speed,
                                                     pause=pause)}))))
            silence = np.zeros(int(1.0 * OUT_RATE), dtype="float32")
            pieces.append(silence)
            t += 1.0

        if not pieces:
            print("nothing rendered")
            return 1

        audio = np.concatenate(pieces)
        audio = np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)
        peak = float(np.max(np.abs(audio))) or 1.0
        if peak > 0.999:
            audio = audio / peak * 0.99
        full_wav = os.path.join(td, "demo.wav")
        write_wav(full_wav, audio)

        if args.only:
            mp3 = os.path.join(DEMO_DIR, "narration-styles-%s.mp3"
                               % "-".join(sorted(args.only)))
        else:
            mp3 = os.path.join(DEMO_DIR, "narration-styles.mp3")
        cmd = [ffmpeg(), "-v", "error", "-y", "-i", full_wav, "-af",
               "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", str(OUT_RATE), "-ac", "1",
               "-codec:a", "libmp3lame", "-b:a", "%dk" % OUT_KBPS, mp3]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(mp3):
            print("master failed:", (r.stderr or "")[-300:])
            return 1

    total = os.path.getsize(mp3) / 1024.0
    print("\nwrote %s  (%.1f KB, %.1f s)" % (mp3, total, t))

    if args.only:
        print("(one segment — the full demo/ is untouched)")
        return 0

    txt = os.path.join(DEMO_DIR, "narration-styles.txt")
    lines = ["ALL 13 NARRATION STYLES — one Khmer passage, in order",
             "=" * 54, "",
             "Same words in every segment — and each style performs them its",
             "own way: its own pace, its own softness, its own pauses (meditation",
             "is slow and soft with long gaps, news is brisk, a trailer is slow",
             "and heavy, cinematic reads like a storyteller). What never",
             "changes is the speaker: pitch stays at 0.0 st in all 13, so it is",
             "always the same voice. Build l: the sustained-whisper style was",
             "removed, so no style whispers a whole narration. In the cinema",
             "style you hear ONE whispered moment, then it returns to normal.",
             "Voice: %s   Master: -16 LUFS, %d kHz, %d kbps" %
             (args.voice, OUT_RATE // 1000, OUT_KBPS), ""]
    for (t0, sid, name, pause, res) in index:
        pl = NAR.plan_text(PASSAGE, style=sid, speed=args.speed, pause=pause)
        pace = sum(p["rate"] for p in pl) / max(1, len(pl))
        soft = sum(p["gain_db"] for p in pl) / max(1, len(pl))
        wh = sum(1 for p in pl if p.get("whisper"))
        lines.append("%s  %-18s %-22s (%5.1fs, pace %.2fx, %+.1f dB, pause "
                     "%.2fs%s)" %
                     (stamp(t0), name, sid, res["seconds"], pace, soft, pause,
                      ", whisper %d/%d" % (wh, len(pl)) if wh else ""))
    lines += ["", "Rebuild:  python build_style_demo.py",
              "Every segment is the shipped engine, rendered on the base voice",
              "(no clone), so it can be rebuilt on any machine with internet."]
    with open(txt, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote %s" % txt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
