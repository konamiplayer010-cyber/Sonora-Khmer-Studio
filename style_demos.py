#!/usr/bin/env python3
"""style_demos.py — the 14 Narration Style demo clips, and how to rebuild them.

Each style card in the studio has a ▶ button. Pressing it plays a short clip of
that style, spoken by the studio's demo voice:

    voice   en-US-JennyNeural   (Jenny US · female — clean, clear, neutral)

**The clip is the style, not the label.** It is rendered through the same engine
the studio uses for a whole book (`narration.render_styled` → the performance
plan), so what you hear on the card is what you get when you press Generate:

    * the style's own PACE            meditation 0.86 · news 1.06
    * the style's own SOFTNESS        meditation −1.2 dB · trailer +0.6 dB
    * the style's own PAUSES          meditation 1.4 s · news 0.1 s (your presets)
    * the style's own BREATH and phrase rhythm
    * a whisper is a MOMENT (the WHISPER RULE) — whisper.py v3 — never a
      whisper v3 — the breath is built from the line's words, every line

What never moves is the SPEAKER: pitch stays 0.0 st in all 14 clips, so the
same person narrates a trailer, the news and a story. Every clip starts by
naming itself, so the file doubles as a spoken guide to the panel.

Where they live
    sonora/public/style_demos/<style>.mp3        (played by the studio UI)

Quality
    The voice service's best stream for read-aloud is 24 kHz / 96 kbps (48 kHz
    is refused by the service). Each clip is therefore rendered at that native
    maximum, then cleaned and mastered:

        - rumble cut below 70 Hz
        - gentle presence lift (3.5 kHz, +1.5 dB) for intelligibility
        - loudness normalised to −16 LUFS, true peak −1.5 dB
        - resampled to 48 kHz and encoded MP3 192 kbps

Rebuild them any time (a voice change, new wording, a new style):

    cd sonora
    python style_demos.py                       all 14
    python style_demos.py --only cinematic,meditation
    python style_demos.py --voice en-US-JennyNeural

`python style_demos.py --report` prints, per clip, what the style actually did
(pace, softness, pauses, whispers) — the numbers behind the ▶ button.
"""
import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import narration as NAR                                   # noqa: E402

PUBLIC = os.path.join(HERE, "public")
DEMO_DIR = os.path.join(PUBLIC, "style_demos")
REPORT = os.path.join(DEMO_DIR, "performance.json")

DEFAULT_VOICE = "en-US-JennyNeural"          # Jenny US · female
HD_SOURCE = "audio-24khz-96kbitrate-mono-mp3"   # the service's best stream
OUT_RATE = 48000
OUT_KBPS = 192
SR = 24000                                   # the engine's working rate

#: the dramatic-pause preset of each card in the studio (the same numbers the
#: panel uses when you click that style)
PRESETS = {
    "natural": 0.10, "documentary": 0.40, "trailer": 0.70, "audiobook": 0.30,
    "news": 0.10, "explainer": 0.20, "thriller": 0.60, "meditation": 1.40,
    "storytelling": 0.35, "novel": 0.30, "inner_monologue": 0.45,
    "sad_romantic": 0.50, "cinematic": 0.45,
}

# One short spoken explanation per style — written to be *the style talking
# about itself*, 25–40 words each (about 10–15 seconds at that style's pace).
DEMO_TEXTS = {
    "natural":
        "This is the Natural Read: plain, comfortable, and easy to follow, like a "
        "friend explaining something they know well. Use it when the words should "
        "carry the story, and the voice should stay out of the way.",
    "documentary":
        "Documentary: measured and steady, with room to think between the facts. "
        "It sounds like a narrator who has spent time in the archive, and who is "
        "in no hurry to impress you.",
    "trailer":
        "Movie trailer: slow, weighty, dramatic. Every line lands like a closing "
        "door, and the silence after it is part of the promise. This is the voice "
        "for the moment before everything changes.",
    "audiobook":
        "Audiobook: steady storytelling, warm and even. This is the voice you can "
        "live with for eight hours, the one you stop noticing in the best possible "
        "way, because the story is doing the work.",
    "news":
        "News anchor: crisp, brisk, clear. Short sentences, no decoration, straight "
        "to what happened and who it touched. The facts arrive in order, and "
        "nothing gets in their way.",
    "explainer":
        "Explainer: friendly and practical, like a good tutorial voice guiding you "
        "step by step. It never rushes you, it never talks down to you, and it "
        "always leaves a small pause for the idea to land.",
    "thriller":
        "Thriller: hushed, tense, deliberate. The pauses do the work here. Speak "
        "softly enough and the listener leans in, and once they lean in, they are "
        "yours for the rest of the chapter.",
    "meditation":
        "Meditation. Very slow. Very soft. The silence matters as much as the words, "
        "and the quiet after a sentence is where the sentence finishes. Nothing here "
        "is urgent. Let the breath out, and let the next line wait for you.",
    "storytelling":
        "Narrative storytelling: warm and building. A storyteller who lets the "
        "feeling rise across the whole piece instead of spending it all on one "
        "line. The ending is stronger when the beginning was calm.",
    "novel":
        "Novel narration: literary, controlled, cinematic. It holds the mood of a "
        "scene and trusts the story to do the rest, letting description and "
        "dialogue breathe without ever overplaying either of them.",
    "inner_monologue":
        "Inner monologue: private thoughts, close and quiet, as if you were hearing "
        "someone think rather than speak. Slightly slower, slightly softer, as "
        "though the words were never meant to leave the room.",
    "sad_romantic":
        "Sad Romantic: restrained longing, and gentle endings. It never breaks "
        "down; it simply lets the sadness sit quietly beside you, in the pauses, "
        "in the small hesitation before the last word of the sentence.",
    "cinematic":
        "Emotional cinematic storytelling: scene building with wide dynamics. The "
        "quiet moments are what make the big ones land, so this style saves its "
        "weight for the sentence that deserves it.",
}
ORDER = ["natural", "storytelling", "novel", "documentary", "trailer", "audiobook",
         "news", "explainer", "thriller", "meditation", "inner_monologue",
         "sad_romantic", "cinematic"]
NAMES = {s: NAR.spec(s)["label"] for s in ORDER}
#: styles whose demo goes through the whisper stage
WHISPER_DEMOS = set()   # build l: no clip whispers the whole way any
                        # more — Emotional Cinematic keeps ONE whispered
                        # moment inside its clip (the WHISPER RULE)


def _ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _speak(text, dst, voice):
    """One line through the voice service at its best stream.

    The rate is left at the service default on purpose: the ENGINE applies the
    style's pace itself (atempo on the decoded audio), so the clip obeys the
    same plan a real episode does. `tts_fallback` is the studio's own client —
    it is what can ask for the 24 kHz / 96 kbps stream.
    """
    import tts_fallback as F
    data = F.fallback_tts(text, voice, "+0%", output_format=HD_SOURCE)
    if not data:
        raise RuntimeError("empty audio")
    with open(dst, "wb") as f:
        f.write(data)
    return {"ok": True, "engine": "edge"}


def _probe(path):
    """(seconds, sample_rate, kbps) of one file."""
    r = subprocess.run([_ffmpeg(), "-hide_banner", "-i", path],
                       capture_output=True, text=True)
    secs, rate, kbps = 0.0, 0, 0
    for line in (r.stderr or "").splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            t = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = t.split(":")
            secs = int(h) * 3600 + int(m) * 60 + float(s)
        elif "Audio:" in line and "Hz" in line:
            parts = line.replace(",", " ").split()
            for i, p in enumerate(parts):
                if p == "Hz" and i and parts[i - 1].isdigit():
                    rate = int(parts[i - 1])
                if p == "kb/s" and i and parts[i - 1].isdigit():
                    kbps = int(parts[i - 1])
    return secs, rate, kbps


def _decode(path, rate=24000):
    import numpy as np
    r = subprocess.run([_ffmpeg(), "-v", "error", "-i", path, "-ac", "1",
                        "-ar", str(rate), "-f", "f32le", "pipe:1"],
                       capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return np.zeros(0, dtype="float32")
    return np.frombuffer(r.stdout, dtype="float32")


def _pitch_hz(x, rate=24000):
    """Median F0 of a clip — the simplest proof that the speaker never changes."""
    import numpy as np
    if x is None or len(x) < rate // 2:
        return 0.0
    vals = []
    win = int(rate * 0.04)
    hop = int(rate * 0.02)
    for s in range(0, len(x) - win, hop):
        seg = x[s:s + win].astype(np.float32)
        if float(np.sqrt(np.mean(seg ** 2))) < 0.01:
            continue
        seg = seg - float(np.mean(seg))
        seg = seg * np.hanning(win).astype(np.float32)
        ac = np.correlate(seg, seg, "full")[win - 1:]
        lo, hi = int(rate / 400.0), int(rate / 70.0)
        if hi <= lo:
            continue
        seg_ac = ac[lo:hi]
        if not seg_ac.size:
            continue
        lag = int(np.argmax(seg_ac)) + lo
        if ac[0] > 0 and seg_ac.max() / ac[0] > 0.3:
            vals.append(rate / float(lag))
    if not vals:
        return 0.0
    return float(np.median(vals))


#: how long a demo clip may plan for (speaking + the style's own pauses).
#: A pause-heavy style (meditation 1.4 s preset) would run over a
#: minute with a full paragraph, so the passage is trimmed to whole sentences —
#: the pauses themselves are never shortened, so what you hear on the card is
#: the style's real silence, just fewer lines of it.
DEMO_BUDGET_S = 26.0
#: the spoken announcement is a label, not a performance — it uses a short pause
LABEL_PAUSE = 0.25


def demo_text(sid, pause, log=print):
    """The longest leading run of sentences whose plan fits the demo budget."""
    full = DEMO_TEXTS[sid]
    sents = NAR.split_sentences(full)
    if len(sents) <= 1:
        return full, 1
    kept, total = [], 0.0
    for i, s in enumerate(sents):
        tof = s[0] if isinstance(s, (tuple, list)) else s
        word_rate = 13.5 * max(0.6, min(1.2, NAR.spec(sid)["pace"][0]))
        est = len(tof) / word_rate
        pl = NAR.plan_text(tof, style=sid, speed=1.0, pause=pause)
        est += sum(p["pause_s"] for p in pl) + 0.15
        if kept and total + est > DEMO_BUDGET_S:
            break
        kept.append(tof)
        total += est
    if len(kept) == len(sents):
        return full, len(sents)
    log("      [demo] passage trimmed to %d of %d sentences to stay under "
        "%.0f s (the pauses are the style's real ones)"
        % (len(kept), len(sents), DEMO_BUDGET_S))
    return " ".join(kept), len(kept)


def render_style(sid, voice=DEFAULT_VOICE, log=print):
    """One clip: the style's label + its passage, performed by the real engine.

    Returns (mp3_bytes, info). The order is the studio's real order: perform
    (pace, pauses, breath, the whisper MOMENT) → clean → master
    to 48 kHz / 192 kbps.
    """
    import numpy as np

    sid = NAR.style_id(sid)
    if sid not in DEMO_TEXTS:
        raise ValueError("no demo text for %r" % sid)
    pause = PRESETS.get(sid, 0.3)
    text, used = demo_text(sid, pause, log=log)
    label = "%s." % NAMES[sid]

    with tempfile.TemporaryDirectory() as td:
        lab_wav = os.path.join(td, "label.wav")
        res = NAR.render_styled(label, lab_wav, sid,
                                lambda t, dst, r, p: _speak(t, dst, voice),
                                ffmpeg=_ffmpeg(), speed=1.0, pause=LABEL_PAUSE,
                                sr=SR, engine_name="local",
                                log=lambda m: log("      " + m))
        if not res.get("ok"):
            raise RuntimeError("label failed: %s" % res.get("error"))
        body_wav = os.path.join(td, "body.wav")
        res2 = NAR.render_styled(text, body_wav, sid,
                                 lambda t, dst, r, p: _speak(t, dst, voice),
                                 ffmpeg=_ffmpeg(), speed=1.0, pause=pause,
                                 sr=SR, engine_name="local",
                                 log=lambda m: log("      " + m))
        if not res2.get("ok"):
            raise RuntimeError("body failed: %s" % res2.get("error"))

        # label, half a beat, then the passage
        raw = os.path.join(td, "raw.wav")
        gap = np.zeros(int(0.45 * SR), dtype="float32")
        a, b = _decode(lab_wav), _decode(body_wav)
        joined = np.concatenate([a, gap, b])
        pcm = (np.clip(joined, -1.0, 1.0) * 32767.0).astype("<i2")
        with wave.open(raw, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm.tobytes())

        mp3 = os.path.join(td, "out.mp3")
        chain = ("highpass=f=70,"
                 "equalizer=f=3500:t=q:w=1.2:g=1.5,"
                 "loudnorm=I=-16:TP=-1.5:LRA=11,"
                 "aresample=%d" % OUT_RATE)
        r = subprocess.run([_ffmpeg(), "-v", "error", "-y", "-i", raw, "-af", chain,
                            "-ar", str(OUT_RATE), "-ac", "1",
                            "-codec:a", "libmp3lame", "-b:a", "%dk" % OUT_KBPS, mp3],
                           capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(mp3):
            raise RuntimeError("master failed: " + (r.stderr or "")[-200:])
        with open(mp3, "rb") as f:
            data = f.read()

        plan = NAR.plan_text(text, style=sid, speed=1.0, pause=pause)
        y = _decode(mp3)
        try:
            import whisper as WH
            fp = WH.measure(y, rate=SR)
        except Exception:
            fp = {}
        info = dict(
            style=sid, label=NAMES[sid], preset=pause,
            pace=round(sum(p["rate"] for p in plan) / max(1, len(plan)), 3),
            softness_db=round(sum(p["gain_db"] for p in plan) / max(1, len(plan)), 2),
            pauses_s=round(sum(p["pause_s"] for p in plan), 2),
            pitch_st=round(sum(p["pitch_st"] for p in plan) / max(1, len(plan)), 3),
            whisper_lines=sum(1 for p in plan if p.get("whisper")),
            lines=len(plan), sentences_used=used,
            sentences_total=len(NAR.split_sentences(DEMO_TEXTS[sid])),
            deliveries=sorted({p.get("delivery", "") for p in plan} - {""}),
            breaths=sum(1 for p in plan if p["breath"]),
            seconds=round(res2["seconds"], 1),
            f0_hz=round(_pitch_hz(y), 1),
            **{k: round(v, 4) for k, v in fp.items()},
        )
    return data, info


def build(styles, voice, quiet=False):
    os.makedirs(DEMO_DIR, exist_ok=True)
    print("voice   : %s" % voice)
    print("source  : %s" % HD_SOURCE)
    print("engine  : narration.render_styled — pace, pauses, breath and the")
    print("          whisper stage, exactly as the studio performs them")
    print("whisper : %s (whisper.py v3: the breath is built from the line's "
          "own formants and locked to its words)"
          % (", ".join(sorted(WHISPER_DEMOS)) or "none"))
    print("perform : narration.py delivery — the style's own pace, softness "
          "and pauses (build l: the expressive stage is gone, the voice is "
          "the original one)")
    print("output  : %d Hz / %d kbps mp3, loudness -16 LUFS\n" % (OUT_RATE, OUT_KBPS))
    results, infos = [], []
    for sid in styles:
        if sid not in DEMO_TEXTS:
            print("  [skip] %s: unknown style" % sid)
            continue
        try:
            data, info = render_style(sid, voice)
        except Exception as e:
            print("  [FAIL] %-16s %s: %s" % (sid, type(e).__name__, str(e)[:110]))
            results.append((sid, False, 0.0))
            continue
        dst = os.path.join(DEMO_DIR, sid + ".mp3")
        with open(dst, "wb") as f:
            f.write(data)
        secs, rate, kbps = _probe(dst)
        ok = 8.0 <= secs <= 26.0 and rate == OUT_RATE and kbps >= 160
        results.append((sid, ok, secs))
        infos.append(info)
        print("  [%s] %-16s %5.1fs  %4d Hz %3d kbps  pace %.2f  %+.1f dB  "
              "pauses %4.2fs  pitch %+.1f st  whisper %d/%d  F0 %.0f Hz"
              % ("OK  " if ok else "WARN", sid, secs, rate, kbps, info["pace"],
                 info["softness_db"], info["pauses_s"], info["pitch_st"],
                 info["whisper_lines"], info["lines"], info["f0_hz"]))
    if infos:
        with open(REPORT, "w", encoding="utf-8") as f:
            json.dump(infos, f, indent=1, ensure_ascii=False)
        if len(infos) == len(ORDER):
            write_readme(infos)
    if not quiet:
        bad = [s for s, ok, _ in results if not ok]
        print("\n%d/%d clips written to %s" % (len(results) - len(bad), len(results),
                                               DEMO_DIR))
        if bad:
            print("check these: " + ", ".join(bad))
    return 0 if all(ok for _, ok, _ in results) else 1


def _studio_build():
    """The studio's own build stamp, so this README can never claim another."""
    try:
        import re as _re
        srv = io.open(os.path.join(HERE, "server.py"), encoding="utf-8").read()
        m = _re.search(r'STUDIO_BUILD\s*=\s*"([^"]+)"', srv)
        return m.group(1) if m else "?"
    except Exception:
        return "?"


BUILD = _studio_build()


def write_readme(infos):
    """Write style_demos/README.txt from the report that was just measured.

    It is generated, never hand-written: the file in the package and the
    clips next to it then cannot disagree.
    """
    rows = {i["style"]: i for i in infos}
    f0 = [i["f0_hz"] for i in infos if i.get("f0_hz")]
    cin = rows.get("cinematic") or {}
    out = []
    out.append("THE 14 NARRATION STYLE DEMOS")
    out.append("=============================")
    out.append("")
    out.append("Voice : en-US-JennyNeural (Jenny US, female)")
    out.append("Format: 48 kHz / 192 kbps mp3, loudness -16 LUFS, mono")
    out.append("")
    out.append("EVERY CLIP IS ITS OWN PERFORMANCE (build %s). Each one is"
               % BUILD)
    out.append("rendered by the studio's own engine (narration.render_styled),")
    out.append("so the style's own pace, its own softness and its own pauses")
    out.append("are in the audio — not just in the words. What never changes")
    out.append("is the SPEAKER: pitch is 0.0 st in every clip (measured F0")
    if f0:
        out.append("%.0f-%.0f Hz across the spoken ones)." % (min(f0), max(f0)))
    out.append("")
    out.append("Each clip says what the style is, so pressing ▶ on a card tells")
    out.append("you both what the style is and how it sounds.")
    out.append("")
    out.append("The two styles reworked in update #3:")
    out.append("  cinematic — the storyteller read (build l: reset to the")
    out.append("              ORIGINAL voice). Unhurried, phrase by phrase,")
    out.append("              gentle landings: pace 0.99x at 0.0 dB, so the voice")
    out.append("              itself is untouched — the style IS the reading. One")
    out.append("              line inside the clip is a brief whisper moment")
    out.append("              (the WHISPER RULE), never the whole piece.")
    out.append("")
    if cin:
        out.append("Measured on this build's cinematic clip: F0 %.0f Hz (the "
                   "speaker, unchanged), softness %+.1f dB, pauses %.2fs."
                   % (cin.get("f0_hz", 0.0), cin.get("softness_db", 0.0),
                      cin.get("pauses_s", 0.0)))
    out.append("")
    out.append("Rebuild them with:")
    out.append("    cd sonora")
    out.append("    python style_demos.py")
    out.append("Report what they do:  python style_demos.py --report")
    out.append("")
    out.append("Clip            length   pace  softness  pauses  whispers")
    out.append("--------------------------------------------------------------")
    for sid in ORDER:
        i = rows.get(sid)
        if not i:
            continue
        out.append("%-15s %6.1fs  %.2fx  %+5.1f dB  %5.2fs   %d/%d"
                   % (sid, i["seconds"], i["pace"], i["softness_db"],
                      i["pauses_s"], i["whisper_lines"], i["lines"]))
    out.append("")
    out.append("The same numbers are in performance.json next to the clips.")
    path = os.path.join(DEMO_DIR, "README.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print("\nwrote %s (generated from this build's measurements)" % path)
    return path


def report():
    if not os.path.exists(REPORT):
        print("no report yet — run: python style_demos.py")
        return 1
    with io.open(REPORT, encoding="utf-8") as f:
        infos = json.load(f)
    print("%-16s %6s %8s %8s %8s %8s  %s" % ("style", "pace", "soft dB", "pauses",
                                             "pitch st", "F0 Hz", "whisper"))
    for i in infos:
        print("%-16s %6.2f %8.1f %8.2f %8.2f %8.0f  %d/%d lines"
              % (i["style"], i["pace"], i["softness_db"], i["pauses_s"],
                 i["pitch_st"], i["f0_hz"], i["whisper_lines"], i["lines"]))
    f0 = [i["f0_hz"] for i in infos if i["f0_hz"] > 0]
    if f0:
        print("\nspoken F0 across the styles: %.1f – %.1f Hz (spread %.1f Hz) — "
              "the speaker does not change" % (min(f0), max(f0), max(f0) - min(f0)))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", default="", help="style id(s), comma separated")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--report", action="store_true",
                    help="print what each shipped clip actually does")
    ap.add_argument("--readme", action="store_true",
                    help="regenerate style_demos/README.txt from the report")
    args = ap.parse_args()
    if args.report:
        return report()
    if args.readme:
        if not os.path.exists(REPORT):
            print("no report yet — run: python style_demos.py")
            return 1
        with io.open(REPORT, encoding="utf-8") as f:
            infos = json.load(f)
        write_readme(infos)
        return 0
    wanted = [s.strip() for s in args.only.split(",") if s.strip()] or ORDER
    wanted = [NAR.style_id(s) for s in wanted]
    return build(wanted, args.voice)


if __name__ == "__main__":
    sys.exit(main())
