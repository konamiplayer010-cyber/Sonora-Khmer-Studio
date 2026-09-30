#!/usr/bin/env python3
"""fix_rvc_env.py — find out what your RVC python is missing, and install it.

Menu 12 in START.bat ("Fix the RVC python"). It is for one message, in the
preflight or the clone test:

    [FAIL] G2. clone conversion (RVC): ... it is missing 'fairseq'

RVC runs in its OWN python (a venv, or a `runtime` folder shipped with an
integrated RVC pack). The pipeline's python installs nothing there, so if that
environment is short of a package RVC needs for the actual voice conversion,
the conversion fails while the rest of the pipeline is perfectly fine.

What this does

    1. finds the python that runs your RVC-WebUI (same discovery as menu 6)
    2. asks it to import RVC's VC class the way the pipeline does, from inside
       the RVC folder
    3. reads the exact answer: which package is missing (if that is the reason)
    4. installs ONLY those packages, INTO THAT python, with your OK
    5. asks RVC to load again and tells you whether it worked

It never touches your models, index, presets, config.json or recordings.
Nothing is deleted or renamed.

Usage
    fix_rvc_env.py              check, show the plan, ask before installing
    fix_rvc_env.py --yes        install without asking (unattended)
    fix_rvc_env.py --check      only check and report, install nothing
"""
import argparse
import json
import os
import re
import subprocess
import sys

# An embedded RVC python may not add this folder to sys.path by itself.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common as C  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

# the two VC-class layouts RVC has shipped (2.3+ and 2.0-2.2)
LAYOUTS = ("infer.vc.modules", "infer.modules.vc.modules")

# 'No module named X' where X is one of these means the ROOT FOLDER is wrong,
# not that a package has to be installed
RVC_OWN = ("infer", "configs", "i18n", "lib", "uvr5", "assets")

# module name -> pip package name (only where they differ)
PIP_NAME = {
    "faiss": "faiss-cpu",
    "sklearn": "scikit-learn",
    "cv2": "opencv-python-headless",
    "parselmouth": "praat-parselmouth",
    "PIL": "pillow",
    "yaml": "pyyaml",
    "ffmpeg": "ffmpeg-python",
    "g2p_en": "g2p-en",
    "jaconv": "jaconv",
    "sounddevice": "sounddevice",
}

# packages a working RVC inference environment should always have
BASICS = ("torch", "numpy", "soundfile")


def say(msg=""):
    print(msg, flush=True)


def probe(python, cwd, module, timeout=600):
    """Can this python import `module` (with the RVC folder on its path)?"""
    code = ("import sys; sys.path.insert(0, %r); import %s; print('PROBE_OK')"
            % (cwd, module))
    env = dict(os.environ)
    env["PYTHONPATH"] = HERE + (
        (os.pathsep + env["PYTHONPATH"]) if env.get("PYTHONPATH") else "")
    try:
        r = subprocess.run([python, "-c", code], cwd=cwd, capture_output=True,
                           text=True, env=env, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "timed out after %ds" % timeout
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    # NOTE: do not test for the marker text — a failing import prints the source
    # line back in its traceback, which contains the marker as a literal. The
    # exit code is the honest answer.
    return (r.returncode == 0), out


def missing_modules(text):
    """Module names RVC says it cannot find — excluding RVC's own folders."""
    out = []
    for m in re.findall(r"No module named '([^']+)'", text or ""):
        top = m.split(".")[0]
        if top in RVC_OWN or m in LAYOUTS:
            continue
        if m not in out:
            out.append(m)
    return out


def pip_version(python, cwd):
    try:
        r = subprocess.run([python, "-m", "pip", "--version"], cwd=cwd,
                           capture_output=True, text=True, timeout=180)
    except Exception as e:
        return ""
    return ((r.stdout or "") + (r.stderr or "")).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="install without asking")
    ap.add_argument("--check", action="store_true",
                    help="only report, install nothing")
    ap.add_argument("--add", default="",
                    help="extra pip packages to install (comma separated)")
    a = ap.parse_args()

    cfg = C.load_config()
    root = (cfg.get("rvc_root") or "").strip()
    say("=" * 68)
    say("FIX THE RVC PYTHON — what RVC itself is missing")
    say("=" * 68)
    say("RVC folder : " + (root or "(not set in config.json)"))

    if not root or not os.path.isdir(root):
        say("")
        say("[FAIL] that folder does not exist. Fix \"rvc_root\" first "
            "(START.bat -> 3 shows what your config expects).")
        return 1

    rpy = C.detect_rvc_python(cfg)
    if not rpy:
        say("")
        say("[FAIL] no python with torch was found under the RVC folder.")
        say("       Run menu 6 (Find my RVC python), put the path it recommends")
        say("       into \"rvc_python\" in pipeline\\config.json, then run this again.")
        return 1
    say("RVC python : " + rpy + "   (nothing is installed anywhere else)")
    say("")

    # ---- 1. ask that python to do what the pipeline asks it to do ----------
    say("--- checking RVC in that python ---")
    loaded_with = ""
    errors = []
    for mod in LAYOUTS:
        ok, out = probe(rpy, root, mod)
        # the honest one-liner from the traceback: the last line that is an
        # actual error, otherwise the last thing it said
        reason = ""
        lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
        for ln in reversed(lines):
            if "Error" in ln or "Exception" in ln or "Errno" in ln:
                reason = ln
                break
        if not reason and lines:
            reason = lines[-1]
        say(("  [OK]   " if ok else "  [--]   ") + mod +
            ("" if ok else "   -> " + (reason[:200] or "(no answer)")))
        if ok and not loaded_with:
            loaded_with = mod
        elif not ok:
            errors.append((mod, out))

    say("")
    say("--- the packages that python has ---")
    basics_missing = []
    for mod in BASICS:
        ok, out = probe(rpy, root, mod)
        say("  [%s]   %s" % ("OK" if ok else "MISSING", mod))
        if not ok:
            basics_missing.append(mod)

    found = []
    for mod, out in errors:
        for m in missing_modules(out):
            if m not in found:
                found.append(m)
    for m in missing_modules("\n".join(o for _, o in errors)):
        if m not in found:
            found.append(m)

    pkgs = []
    for m in found + basics_missing:
        name = PIP_NAME.get(m, m)
        if name not in pkgs:
            pkgs.append(name)
    for extra in (a.add or "").split(","):
        extra = extra.strip()
        if extra and extra not in pkgs:
            pkgs.append(extra)

    say("")
    if loaded_with and not pkgs:
        say("RESULT: nothing to fix — RVC loads in that python (" +
            loaded_with + ").")
        say("        If the clone test still fails, its own window says why:")
        say("        run START.bat -> 11 and send me that output.")
        return 0

    if not loaded_with and not pkgs:
        say("RESULT: RVC does not load, and it is not a missing package — the")
        say("        reason is one of these lines:")
        for mod, out in errors:
            say("")
            say("  " + mod + ":")
            for ln in (out or "").splitlines()[-6:]:
                say("      " + ln[:200])
        say("")
        say("        Send me this window (or logs\\fix_rvc_env.log). Menu 6 lists")
        say("        other pythons on this computer that might own your RVC-WebUI.")
        _save_log(cfg, rpy, root, loaded_with, errors, pkgs, installed=False)
        return 1

    # ---- 2. show the plan --------------------------------------------------
    say("PLAN: install into this python only:")
    say("   " + rpy)
    for p in pkgs:
        say("   + " + p)
    say("")
    say("Your models, index, presets, config.json and recordings are not touched.")
    if a.check:
        _save_log(cfg, rpy, root, loaded_with, errors, pkgs, installed=False)
        say("(--check: nothing was installed)")
        return 0

    if not a.yes:
        try:
            ans = input("Type Y to install, anything else to stop: ").strip().lower()
        except EOFError:
            ans = ""
        if ans not in ("y", "yes"):
            say("Stopped — nothing was changed.")
            return 0

    if not pip_version(rpy, root):
        say("")
        say("That python has no pip. Trying to add it (ensurepip) ...")
        try:
            r = subprocess.run([rpy, "-m", "ensurepip", "--upgrade"], cwd=root,
                               capture_output=True, text=True, timeout=600)
            ok = "pip" in ((r.stdout or "") + (r.stderr or ""))
        except Exception:
            ok = False
        if not ok:
            say("[FAIL] this python cannot install packages itself (no pip).")
            say("       Some integrated packs ship a python like that on purpose.")
            say("       Run menu 6: another python on this computer may be the one")
            say("       that starts your RVC-WebUI. Put it in \"rvc_python\".")
            _save_log(cfg, rpy, root, loaded_with, errors, pkgs, installed=False)
            return 1
        say("[OK] pip is available now.")

    # ---- 3. install --------------------------------------------------------
    say("")
    say("--- installing (this can take a few minutes) ---")
    cmd = [rpy, "-m", "pip", "install", "--upgrade"] + pkgs
    say("$ " + " ".join(cmd))
    env = dict(os.environ)
    env["PYTHONPATH"] = HERE + (
        (os.pathsep + env["PYTHONPATH"]) if env.get("PYTHONPATH") else "")
    try:
        rc = subprocess.call(cmd, cwd=root, env=env)
    except Exception as e:
        say("[FAIL] could not run pip: " + str(e)[:200])
        _save_log(cfg, rpy, root, loaded_with, errors, pkgs, installed=False)
        return 1
    say("pip exit code: %d" % rc)

    # ---- 4. ask RVC again --------------------------------------------------
    say("")
    say("--- checking RVC again ---")
    loaded_with = ""
    for mod in LAYOUTS:
        ok, out = probe(rpy, root, mod)
        say(("  [OK]   " if ok else "  [--]   ") + mod)
        if ok:
            loaded_with = mod
            break
    _save_log(cfg, rpy, root, loaded_with, errors, pkgs, installed=True)
    say("")
    if loaded_with:
        say("FIXED: RVC now loads in your RVC python (" + loaded_with + ").")
        say("Next:  START.bat -> 11   (the clone test, one paragraph).")
        return 0
    say("Still not loading. Send me this window (or logs\\fix_rvc_env.log) and I")
    say("will read the exact reason — nothing was deleted or overwritten.")
    return 1


def _save_log(cfg, rpy, root, loaded_with, errors, pkgs, installed):
    try:
        C.LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = C.LOG_DIR / "fix_rvc_env.log"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("fix_rvc_env report\n")
            fh.write("rvc_root   : %s\n" % root)
            fh.write("rvc_python : %s\n" % rpy)
            fh.write("python     : %s\n" % sys.version.split()[0])
            fh.write("loads with : %s\n" % (loaded_with or "(no layout loaded)"))
            fh.write("packages   : %s\n" % (", ".join(pkgs) or "(none)"))
            fh.write("installed  : %s\n\n" % installed)
            for mod, out in errors:
                fh.write("--- %s ---\n%s\n\n" % (mod, out))
        print("       (report saved: %s)" % path)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
