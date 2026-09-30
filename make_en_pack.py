#!/usr/bin/env python3
"""make_en_pack.py — the 13 style clips as ONE file (English demo pack).

Takes the clips that are already in the panel (`public/style_demos/`), puts
them back to back **in the panel's own order** with a 0.7 s beat between them,
masters the result to −16 LUFS / 48 kHz / 192 kbps and writes:

    ../all-13-narration-styles.mp3     the audio
    ../all-13-narration-styles.txt     the times + what each style does

Because it reads the clips and their measurements instead of re-rendering
them, the pack can never sound like a different build than the panel:

    python make_en_pack.py            # rebuild the pair
    python make_en_pack.py --check    # only compare and report
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

DEMO_DIR = os.path.join(HERE, "public", "style_demos")
REPORT = os.path.join(DEMO_DIR, "performance.json")
PAGE = os.path.join(HERE, "public", "index.html")
OUT_MP3 = os.path.abspath(os.path.join(HERE, "..", "all-13-narration-styles.mp3"))
OUT_TXT = os.path.abspath(os.path.join(HERE, "..", "all-13-narration-styles.txt"))
GAP_S = 0.7
RATE = 48000
KBPS = 192


def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def ui_order():
    """The order the cards are in on the page (fallback: the demo list)."""
    try:
        page = io.open(PAGE, encoding="utf-8").read()
        i = page.find("const STYLES = [")
        if i >= 0:
            ids = re.findall(r'\{id:"([a-z_]+)"', page[i:i + 8000])
            if ids:
                return ids
    except Exception:
        pass
    try:
        import style_demos as SD
        return list(SD.ORDER)
    except Exception:
        return []


def studio_build():
    try:
        srv = io.open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
        m = re.search(r'STUDIO_BUILD\s*=\s*"([^"]+)"', srv)
        return m.group(1) if m else "?"
    except Exception:
        return "?"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="report what would be written, change nothing")
    args = ap.parse_args()

    import numpy as np

    with io.open(REPORT, encoding="utf-8") as f:
        infos = {i["style"]: i for i in json.load(f)}
    order = [s for s in ui_order() if s in infos]
    if not order:
        print("no clips/measurements found — run: python style_demos.py")
        return 1
    missing = [s for s in order if not os.path.exists(os.path.join(DEMO_DIR, s + ".mp3"))]
    if missing:
        print("missing clips:", ", ".join(missing))
        return 1

    pieces, marks, t = [], [], 0.0
    gap = np.zeros(int(GAP_S * RATE), dtype=np.float32)
    for sid in order:
        path = os.path.join(DEMO_DIR, sid + ".mp3")
        r = subprocess.run([ffmpeg(), "-v", "error", "-i", path, "-ac", "1",
                            "-ar", str(RATE), "-f", "f32le", "pipe:1"],
                           capture_output=True)
        if r.returncode != 0 or not r.stdout:
            print("cannot decode", path)
            return 1
        x = np.frombuffer(r.stdout, dtype=np.float32).copy()
        marks.append((t, sid, len(x) / float(RATE)))
        pieces.append(x)
        pieces.append(gap)
        t += len(x) / float(RATE) + GAP_S

    audio = np.concatenate(pieces) if pieces else np.zeros(1, np.float32)
    audio = np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)
    peak = float(np.max(np.abs(audio))) or 1.0
    if peak > 0.999:
        audio = audio / peak * 0.99
    total = len(audio) / float(RATE)
    print("%d clips, %.1f s, order: %s" % (len(order), total, ", ".join(order)))
    if args.check:
        print("(--check: nothing written)")
        return 0

    import wave
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        wav = os.path.join(td, "pack.wav")
        with wave.open(wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
        r = subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", wav, "-af",
                            "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", str(RATE),
                            "-ac", "1", "-codec:a", "libmp3lame",
                            "-b:a", "%dk" % KBPS, OUT_MP3], capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(OUT_MP3):
            print("master failed:", (r.stderr or "")[-300:])
            return 1

    def stamp(sec):
        m, s = divmod(sec, 60)
        return "%d:%05.2f" % (int(m), s)

    lines = ["ALL 13 NARRATION STYLES — one file, in order",
             "=" * 45, "",
             "The 13 clips from the Narration Style panel, back to back, in",
             "panel order (%.1f s between clips). Each clip is the style" % GAP_S,
             "PERFORMED by the studio engine — its own pace, its own",
             "softness, its own pauses — and it names itself, so this file is",
             "also the spoken guide to the panel.",
             "",
             "PURE VOICE, OWN STYLE: every style performs differently",
             "(meditation 0.84x at -1.2 dB with 1.4 s gaps, news 1.07x and",
             "brisk, trailer 0.90x and +0.7 dB, cinematic 0.99x at 0.0 dB —",
             "the storyteller read, unhurried, phrase by phrase). The SPEAKER",
             "never changes: pitch stays at 0.0 st in all 13 styles and all 52",
             "feelings.",
             "",
             "BUILD %s:" % studio_build(),
             "  cinematic — reset to the ORIGINAL voice: pace 0.99x at 0.0 dB,",
             "              no tone shaping. The style is the storyteller READ",
             "              (unhurried, phrase by phrase, gentle landings), and",
             "              one line inside its clip is a brief whisper moment.",
             "  no style whispers a whole narration in this build — a whisper is",
             "              only ever a brief moment inside a style,",
             "",
             "Master: 48 kHz / %d kbps mp3, loudness -16 LUFS, voice en-US-JennyNeural."
             % KBPS, ""]
    for (t0, sid, secs) in marks:
        i = infos[sid]
        lines.append("%s  %-36s (%5.1fs, %.2fx, %+.1f dB, pause %.2fs%s)"
                     % (stamp(t0), i["label"], secs, i["pace"], i["softness_db"],
                        i["pauses_s"],
                        ", whisper %d/%d" % (i["whisper_lines"], i["lines"])
                        if i["whisper_lines"] else ""))
    lines += ["", "Total %.1f s" % total, "",
              "Rebuild:  cd sonora && python style_demos.py && python make_en_pack.py",
              "The pack is assembled from the panel clips — never re-rendered —",
              "so it always matches the build that ships with it."]
    with io.open(OUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    kb = os.path.getsize(OUT_MP3) / 1024.0
    print("wrote %s (%.1f KB, %.1f s)" % (OUT_MP3, kb, total))
    print("wrote %s" % OUT_TXT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
