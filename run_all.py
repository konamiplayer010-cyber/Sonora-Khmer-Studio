#!/usr/bin/env python3
"""run_all.py — run the whole pipeline in order, stopping on the first
failed stage (spec section 44). Re-run at any time: completed chunks are
skipped, so it resumes instead of restarting."""
import os
import subprocess
import sys

import common as C


def run(script, py=None, extra=None):
    cmd = [py or sys.executable, str(C.ROOT / script)] + (extra or [])
    print("\n" + "=" * 60)
    print("$ " + " ".join(cmd))
    print("=" * 60)
    env = dict(os.environ)
    # stage 03 runs with the RVC python (possibly an embedded one that does not
    # add the script folder to sys.path) — tell it where the pipeline lives
    env["PYTHONPATH"] = str(C.ROOT) + (
        (os.pathsep + env["PYTHONPATH"]) if env.get("PYTHONPATH") else "")
    r = subprocess.run(cmd, cwd=str(C.ROOT), env=env)
    if r.returncode != 0:
        print(f"\n>>> {script} stopped with code {r.returncode}.")
        print(">>> Fix the cause, then re-run run_all.bat — nothing")
        print(">>> already validated will be redone.")
        sys.exit(r.returncode)


def main():
    cfg = C.load_config()
    run("00_preflight.py", extra=["--full"])
    run("01_normalize_khmer.py")
    run("02_generate_tts.py")
    rpy = C.detect_rvc_python(cfg)
    if rpy:
        print(f"\n[info] RVC python: {rpy}")
    else:
        print("\n[info] no RVC venv found — 03 will run with the system python")
        print("       (it must have torch + the RVC packages)")
    run("03_rvc_convert.py", py=rpy)
    run("04_merge_audio.py")
    run("05_clean_master.py")
    print("\nPRODUCTION COMPLETE (see final/report.txt and master/report.txt)")


if __name__ == "__main__":
    main()
