#!/usr/bin/env python3
"""test_clone.py — the ONE SMALL TEST before any batch work (spec: verify first).

It runs the real pipeline on ONE short Khmer paragraph, end to end, and leaves
your book completely untouched:

    pipeline/clone_test/            <- everything the test makes lives here
        input/test_paragraph_kh.txt
        config.json                 <- a copy of yours (same RVC paths/settings)
        normalized/  tts/  rvc_output/  final/  logs/

Why a separate folder: chunk names (chapter_01/chunk_0001) are what the log uses
to decide "already done". If the test wrote into the real folder, a later book
run could reuse the test's audio. Different folder = no collision, ever.

What it proves
    00 preflight   your paths/index/model are valid
    01 normalize   Khmer text handling
    02 TTS         the voice engines work
    03 RVC         YOUR clone actually converts through your RVC install
    -> a wav you can listen to, converted with rmvpe / pitch 0 / index 0.75 /
       protect 0.33 — the settings that are then used for the book

Nothing is deleted, renamed or overwritten. Your real folder is not touched.

Usage:   test_clone.py            (from test_clone.bat, or by hand)
         test_clone.py --clean    also run stage 05 (Clean & Clear) if installed
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common as C  # noqa: E402

TEST_ROOT = HERE / "clone_test"
TEST_SENTENCES = [
    "ព្រះរាជាណាចក្រខ្មែរបានរីកចម្រើននៅក្នុងសតវត្សទីប្រាំបួន។",
    "បន្ទាប់មក ទីក្រុងថ្មីមួយត្រូវបានសាងសង់ឡើង ហើយប្រជាជនបានរស់នៅដោយសុខសាន្ត។",
]


def say(msg):
    print(msg, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true",
                    help="also run stage 05 (Clean and Clear) on the test audio")
    ap.add_argument("--style", default="", help="override the narration style")
    a = ap.parse_args()

    real_cfg = HERE / "config.json"
    if not real_cfg.exists():
        say("[FAIL] config.json not found next to this script.")
        return 1
    with open(real_cfg, encoding="utf-8") as f:
        cfg = json.load(f)

    say("=" * 68)
    say("CLONE TEST — one paragraph, through the real pipeline")
    say("=" * 68)
    say(f"RVC root : {cfg.get('rvc_root')}")
    say(f"model    : {cfg.get('model_file')}")
    say(f"index    : {Path(str(cfg.get('index_file'))).name}")
    say(f"engine   : {cfg.get('tts_engine')} | style: "
        f"{a.style or cfg.get('narration_style') or '(plain read)'}")
    rpy = C.detect_rvc_python(cfg)
    say(f"RVC py   : {rpy or '(none found — set \"rvc_python\" in config.json)'}")
    say("           (text + voice run with the pipeline python; step 03 and the")
    say("            preflight conversion run with THIS one, because RVC lives in it)")
    say("")
    say("Your book is NOT touched — this test works in pipeline/clone_test/.")
    say("")

    # ---- build the isolated workspace -----------------------------------
    if TEST_ROOT.exists():
        shutil.rmtree(TEST_ROOT, ignore_errors=True)
    (TEST_ROOT / "input").mkdir(parents=True, exist_ok=True)
    (TEST_ROOT / "input" / "test_paragraph_kh.txt").write_text(
        "\n".join(TEST_SENTENCES) + "\n", encoding="utf-8")

    tcfg = dict(cfg)
    tcfg["input_file"] = "input/test_paragraph_kh.txt"
    tcfg["project"] = "CLONE_TEST"
    tcfg["final_name"] = "CLONE_TEST.wav"
    if a.style:
        tcfg["narration_style"] = a.style
    # copy the RVC/model settings exactly — the point is to test YOUR settings
    with open(TEST_ROOT / "config.json", "w", encoding="utf-8") as f:
        json.dump(tcfg, f, indent=2, ensure_ascii=False)

    env = dict(os.environ)
    env["SONARO_PIPELINE_ROOT"] = str(TEST_ROOT)
    # stage 03 runs with the RVC python, which can be an embedded python that
    # does not add the script folder to sys.path by itself
    env["PYTHONPATH"] = str(HERE) + (
        (os.pathsep + env["PYTHONPATH"]) if env.get("PYTHONPATH") else "")

    def stage(script, py=None, extra=None):
        cmd = [py or sys.executable, str(HERE / script)] + (extra or [])
        say("")
        say("-" * 68)
        say("$ " + " ".join(cmd))
        say("-" * 68)
        r = subprocess.run(cmd, cwd=str(HERE), env=env)
        return r.returncode

    if stage("00_preflight.py", extra=["--full"]):
        say("\n[STOP] preflight failed — fix the item above, then run this again.")
        return 1
    for script in ("01_normalize_khmer.py", "02_generate_tts.py"):
        if stage(script):
            say(f"\n[STOP] {script} failed. Nothing else was run.")
            return 1

    say("")
    say(f"[info] RVC python for stage 03: {rpy or '(none found — using the system python)'}")
    if stage("03_rvc_convert.py", py=rpy):
        say("\n[STOP] RVC conversion failed (that is the important one — the "
            "message above says why). Nothing else was run.")
        return 1
    if stage("04_merge_audio.py"):
        say("\n[STOP] merge failed.")
        return 1
    if a.clean:
        stage("05_clean_master.py")     # optional: not fatal

    # ---- where to listen -------------------------------------------------
    final_dir = TEST_ROOT / "final"
    rvc_dir = TEST_ROOT / "rvc_output"
    say("")
    say("=" * 68)
    say("TEST DONE — listen to this file:")
    found = sorted(final_dir.glob("*.wav")) if final_dir.is_dir() else []
    if found:
        say("   " + str(found[0]))
    else:
        chunks = sorted(rvc_dir.glob("*/*.wav")) if rvc_dir.is_dir() else []
        if chunks:
            say("   " + str(chunks[0]))
        else:
            say("   (no wav produced — send me the output above)")
    say("")
    say("What to check while listening:")
    say("  * does it sound like your Sonaro-kh voice, at speech tempo (not slowed)?")
    say("  * any crackle, buzz, metallic edge, or robotic wobble?")
    say("  * are Khmer numbers/dates read as words, not symbol-by-symbol?")
    say("")
    say("Then:")
    say("  GOOD -> run the real book: START.bat -> 2")
    say("  NOT GOOD -> send me this whole window; nothing was lost or overwritten.")
    say("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
