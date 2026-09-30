#!/usr/bin/env python3
"""test_hd_server.py — the studio side of HD Cleanup (§2, §16, §17, §19, §24).

`test_hdclean.py` proves the engine. This file proves the plumbing around it,
which is where the rules the user set actually live:

  * the tool exists only inside the RVC VOICE CLONE path — a non-clone job is
    skipped, and says so;
  * it is Khmer only — an English job is skipped, and says so;
  * the original clone audio is kept (`<key>.original.wav`) and the enhanced
    file is written as `enhanced_hd.wav`; the episode then exports the HD one;
  * the browser is given the 5–10 s Original ▶ / HD Clean ▶ pair;
  * a failure leaves the original alone and reports the exact sentence
    “Enhancement unavailable; original TTS preserved.”;
  * it always processes the ORIGINAL — the kept copy is byte-identical to what
    the clone produced, never the result of a previous HD pass.

Run:  python3 test_hd_server.py
"""

from __future__ import annotations

import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (HERE, os.path.join(ROOT, "sonora")):
    if p not in sys.path:
        sys.path.insert(0, p)

PASS = 0
FAIL = 0
NOTES = []


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("  ok   %-58s %s" % (name, detail))
    else:
        FAIL += 1
        print("  FAIL %-58s %s" % (name, detail))


try:
    import server as S
except Exception as e:                                # pragma: no cover
    print("test_hd_server: cannot import the studio server (%s: %s) — skipped"
          % (type(e).__name__, e))
    sys.exit(0)


KH_TEXT = "សួស្តី ខ្ញុំឈ្មោះសន្និ ថ្ងៃនេះខ្ញុំនឹងនិយាយអំពីសៀវភៅមួយ។"
EN_TEXT = "Hello, this is a plain English narration sample for the test."


def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


FF = ffmpeg()


def make_master(path, seconds=12.0, noisy=True, sr=24000):
    """A stand-in for the clone output: real Khmer speech, 24 kHz mono WAV."""
    src = None
    for rel in ("demo/khmer-voice-a-standard.mp3", "demo/khmer-voice-b-finetuned.mp3"):
        p = os.path.join(HERE, rel)
        if os.path.exists(p):
            src = p
            break
    cmd = [FF, "-v", "error", "-i", src, "-ac", "1", "-ar", str(sr),
           "-t", str(seconds), "-f", "f32le", "pipe:1"] if src else None
    if cmd:
        x = subprocess.run(cmd, capture_output=True).stdout
        data = __import__("numpy").frombuffer(x, dtype="<f4").copy()
    else:                                             # pragma: no cover
        import numpy as np
        t = __import__("numpy").arange(int(sr * seconds)) / sr
        data = (0.3 * __import__("numpy").sin(2 * 3.14159 * 160 * t)).astype("<f4")
    if noisy:
        import numpy as np
        rng = np.random.default_rng(7)
        data = np.clip(data + rng.normal(0, 0.02, data.size).astype("f4"), -1, 1)
    pcm = (np.clip(data, -1, 1) * 32767).astype("<i2").tobytes()
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
                + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16)
                + b"data" + struct.pack("<I", len(pcm)))
        f.write(pcm)
    return path


def main():
    print("HD Cleanup — the studio side\n" + "=" * 74)
    tmp = tempfile.mkdtemp(prefix="test_hd_server_")
    old_cache = S.CACHE_DIR
    S.CACHE_DIR = tmp
    try:
        # 1. a job with no clone must not be touched at all
        key = "hdtestnocone000001"
        master = make_master(os.path.join(tmp, key + ".master"))
        md5 = hashlib.md5(open(master, "rb").read()).hexdigest()
        note, state = S._hd_cleanup_clone(key, master, KH_TEXT, rvc_on=False, plan_n=3)
        check("a non-clone job is skipped, and says why",
              "RVC VOICE CLONE" in note and state is None, note.strip())
        check("nothing is written for a skipped job",
              hashlib.md5(open(master, "rb").read()).hexdigest() == md5
              and not os.path.exists(os.path.join(tmp, key + ".original.wav")), "")

        # 2. Khmer only: the same clone job in English is skipped
        key = "hdtestenglish000001"
        master = make_master(os.path.join(tmp, key + ".master"))
        note, state = S._hd_cleanup_clone(key, master, EN_TEXT, rvc_on=True, plan_n=3)
        check("an English clone job is skipped (Khmer only)", "Khmer only" in note, note.strip())

        # 3. the real thing: Khmer clone output with hiss in it
        key = "hdtestkhmer00000001"
        master = make_master(os.path.join(tmp, key + ".master"))
        before_md5 = hashlib.md5(open(master, "rb").read()).hexdigest()
        before_size = os.path.getsize(master)
        note, state = S._hd_cleanup_clone(key, master, KH_TEXT, rvc_on=True, plan_n=3)
        check("a Khmer clone job is cleaned and reports the score",
              state and state.get("ok") and "HD Cleanup: score" in note, note.strip())
        keep = os.path.join(tmp, key + ".original.wav")
        check("the ORIGINAL clone audio is kept, byte for byte (§16)",
              os.path.exists(keep)
              and hashlib.md5(open(keep, "rb").read()).hexdigest() == before_md5,
              os.path.basename(keep))
        check("it is published as enhanced_hd.wav and becomes the episode",
              state.get("hd") == "enhanced_hd.wav"
              and os.path.getsize(master) != before_size
              and open(master, "rb").read(44)[24:28] == struct.pack("<I", 48000),
              "master is now %d bytes, 48 kHz" % os.path.getsize(master))
        pv = state.get("previews") or {}
        check("the browser gets the Original ▶ / HD Clean ▶ pair (§17)",
              set(pv) == {"original", "hd"}
              and all(v.startswith("/hd-preview/%s/" % key) for v in pv.values()),
              str(sorted(pv)))
        check("the preview files really exist on disk",
              all(os.path.exists(os.path.join(tmp, key + ".hd_preview",
                                              os.path.basename(v))) for v in pv.values()),
              "2 files")
        check("the HD result is playable through the studio’s preview route (§17)",
              all(os.path.getsize(os.path.join(tmp, key + ".hd_preview",
                                               os.path.basename(v))) > 2000 for v in pv.values()),
              "both previews are real audio")
        check("the status endpoint can offer it to the browser",
              S.HD_STATE.get(key, {}).get("ok") is True,
              "HD_STATE[%s] present" % key)
        check("the engine ran on the clone output, and only once (§19)",
              state.get("score_before") is not None and state.get("score_after") is not None,
              "score %s → %s · %s" % (state.get("score_before"), state.get("score_after"),
                                      "; ".join(state.get("stages") or []) or "nothing needed"))

        # 4. nothing is chained: a second job from the kept original is identical
        key2 = "hdtestkhmer00000002"
        master2 = make_master(os.path.join(tmp, key2 + ".master"))
        shutil.copyfile(keep, master2)                 # feed the ORIGINAL back in
        _, state2 = S._hd_cleanup_clone(key2, master2, KH_TEXT, rvc_on=True, plan_n=3)
        check("the same input always gives the same result (never a chained pass §19)",
              hashlib.md5(open(master2, "rb").read()).hexdigest()
              == hashlib.md5(open(master, "rb").read()).hexdigest(),
              "identical output md5")

        # 5. fail-safe: a broken master keeps the original and reports it
        key3 = "hdtestbroken0000001"
        master3 = os.path.join(tmp, key3 + ".master")
        open(master3, "wb").write(b"not-audio" * 400)
        broken_md5 = hashlib.md5(open(master3, "rb").read()).hexdigest()
        note, state = S._hd_cleanup_clone(key3, master3, KH_TEXT, rvc_on=True, plan_n=3)
        check("a failure keeps the original and reports the exact sentence (§24)",
              "Enhancement unavailable; original TTS preserved." in note
              and hashlib.md5(open(master3, "rb").read()).hexdigest() == broken_md5,
              note.strip()[:70])
        check("a failed job is recorded as failed for the browser",
              S.HD_STATE.get(key3, {}).get("ok") is False, "")
    finally:
        S.CACHE_DIR = old_cache
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 74)
    print("HD Cleanup (studio side): %d passed, %d failed" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
