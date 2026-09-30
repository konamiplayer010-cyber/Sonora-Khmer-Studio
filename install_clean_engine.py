#!/usr/bin/env python3
"""install_clean_engine.py — one-time setup for the best Clean & Clear engine.

Installs `clearvoice` (MossFormer2 neural denoise + true 48 kHz
super-resolution) into the python that already runs your RVC-WebUI.

The tricky part is finding that python — this script does it for you:
  1. `rvc_python` from config.json (if set)
  2. the launcher .bat(s) inside your RVC folder (they name the interpreter)
  3. a python anywhere under the RVC folder (venv / python / runtime /
     py311 / system / ... — integrated packs hide it in a subfolder)
  4. the pythons installed system-wide (py launcher)
  5. the python that runs this script
The first interpreter that can `import torch` is the RVC one; the choice is
saved into config.json so Sonora and the pipeline use it too.

Usage:
    double-click  install_clean_engine.bat      (recommended)
    python install_clean_engine.py             # real install
    python install_clean_engine.py --dry-run   # just show the plan
    python install_clean_engine.py --package deepfilternet
    python install_clean_engine.py --python "C:\\path\\python.exe"
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C          # noqa: E402
import find_rvc_python as FRP   # noqa: E402

PACKAGES = {
    "clearvoice": ("clearvoice", "neural denoise + true 48 kHz super-resolution (best)"),
    "deepfilternet": ("deepfilternet", "light neural denoise (fast, smaller download)"),
}

# clearvoice's own metadata pins numpy<2.0. On a machine that already has
# numpy 2.x (your RVC env does), pip then tries to COMPILE numpy 1.x from
# source, needs a C compiler (cl/gcc) and dies with
# "metadata-generation-failed … Running `cl /?` gave WinError 2".
# Installing with --no-deps avoids that entirely — and clearvoice works fine
# with numpy 2 (verified: MossFormer2_SE_48K ran on numpy 2.3.5).
# (kept for the manual instructions printed at the end)
CV_MODEL_NOTE = ("first use downloads the neural weights (~220 MB for the "
                 "enhancer, ~220 MB more for super-resolution) — needs "
                 "internet once")


def has(python, code, timeout=90):
    try:
        r = subprocess.run([python, "-c", code], capture_output=True,
                           timeout=timeout)
        return r.returncode == 0
    except Exception:
        return False


def candidates(cfg):
    """Every interpreter that could be the RVC one, most likely first."""
    try:
        return FRP.candidates(cfg.get("rvc_root") or "",
                              cfg.get("rvc_python") or "")
    except Exception:
        return []


def ask_for_python(found, tries=3):
    """No torch anywhere: ask the user, validating each answer."""
    print()
    print("Your RVC folder is:")
    print("   " + (C.load_config().get("rvc_root") or "(not set in config.json)"))
    print("I looked inside it (including subfolders) and at every python")
    print("installed on this PC. None of them has torch, which means the")
    print("RVC python is somewhere I cannot guess.")
    print()
    print("Find it like this: right-click the file that starts your")
    print("RVC-WebUI -> Edit (or open it in Notepad) and look for a line")
    print("with python.exe in it. That path is the one I need.")
    print()
    for i in range(tries):
        try:
            ans = input("Paste that python.exe path here and press Enter"
                        " (or just Enter to stop): ").strip().strip('"')
        except (EOFError, KeyboardInterrupt):
            return None
        if not ans:
            return None
        if not os.path.isfile(ans):
            print(f"   [no file at that path] {ans}")
            continue
        print(f"   checking {ans} ...")
        if FRP.has_torch(ans):
            print("   [OK] that one has torch - using it.")
            return ans
        print("   [no torch in that python] try the next candidate, or a")
        print("   different python.exe from the RVC launcher.")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", default="clearvoice", choices=list(PACKAGES))
    ap.add_argument("--python", default="", help="use this python explicitly")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-warmup", action="store_true",
                    help="skip pre-downloading the neural weights")
    a = ap.parse_args()

    cfg = C.load_config()
    pkg, what = PACKAGES[a.package]

    print("=" * 62)
    print("Clean & Clear engine setup — " + pkg)
    print("=" * 62)
    print(f"package: {pkg}   ({what})")
    print("This installs into the python that runs your RVC-WebUI. It may")
    print("take a few minutes and needs internet. Nothing is removed.")
    print()

    if a.python:
        cands = [a.python]
    else:
        cands = candidates(cfg)
    if not cands:
        print("[MISSING] no python found to install into.")
        print("  Tell this script where it is:")
        print('    python install_clean_engine.py --python "C:\\...\\python.exe"')
        print("  How to find it: open the .bat/shortcut that starts your")
        print("  RVC-WebUI in Notepad and read the python path it calls; or")
        print("  open a terminal in your RVC folder and run:  where python")
        sys.exit(1)

    mod = "clearvoice" if pkg == "clearvoice" else "df"
    print("candidate pythons (checked for torch):")
    chosen, torch_list, seen_any = None, [], []
    if cands:
        # not too many checks: only until we find torch + one spare confirmation
        for p in cands[:14]:
            torch_ok = has(p, "import torch")
            cv_ok = has(p, f"import {mod}") if torch_ok or len(cands) <= 6 else False
            mark = "torch OK" if torch_ok else "no torch"
            if cv_ok:
                mark += " | already installed"
            print(f"  - {p}   [{mark}]")
            if torch_ok:
                torch_list.append(p)
                if chosen is None and not cv_ok:
                    chosen = p
    if torch_list and chosen is None:
        chosen = torch_list[0]
    if chosen is None:
        chosen = ask_for_python(cands)
    if chosen is None:
        print()
        print("[FAIL] no python with torch was found - so I cannot tell which")
        print("       one runs your RVC-WebUI. Two ways to fix this:")
        print("       1. re-run menu 4 and paste the path when I ask, or")
        print('       2. run:  python install_clean_engine.py --python "C:\\...\\python.exe"')
        print("       (your RVC folder + every python found are listed above;")
        print("        send me that list and I will point at the right file)")
        sys.exit(1)

    print()
    print(f"using: {chosen}")

    # Remember the choice: Sonora and the pipeline then use the SAME python
    # (Sonora keeps its RVC settings in .rvc_config.json next to server.py).
    if not a.dry_run:
        try:
            cfg2 = C.load_config()
            if (cfg2.get("rvc_python") or "").strip().lower() != chosen.lower():
                cfg2["rvc_python"] = chosen
                C.save_config(cfg2)
                print("saved to config.json  ->  rvc_python = " + chosen)
        except Exception as e:
            print("(could not save the choice into config.json: %s)" % e)
        here = Path(__file__).resolve().parent
        for rel in ("../sonora/.rvc_config.json", "../studio/.rvc_config.json",
                    "../.rvc_config.json"):
            sp = (here / rel).resolve()
            try:
                if sp.is_file():
                    import json as _json
                    data = _json.load(open(sp, encoding="utf-8"))
                    if (data.get("python") or "").strip().lower() != chosen.lower():
                        data["python"] = chosen
                        _json.dump(data, open(sp, "w", encoding="utf-8"), indent=1)
                        print("saved to Sonora settings -> python = " + chosen)
                    break
            except Exception:
                pass

    # Install with --no-deps so pip can never try to downgrade/compile numpy
    # or touch torch. Then let the TARGET python itself report what is missing
    # and install exactly that (clearvoice pulls a long tail of small deps).
    print("command:", f'"{chosen}" -m pip install --no-deps {pkg}')
    print("then: import-driven resolution — that python tells us exactly "
          "which modules are missing and they are installed one by one")
    print("(--no-deps is deliberate: it is what prevents the numpy "
          "source-build error)")
    if a.dry_run:
        print("\n[dry-run] nothing installed. Remove --dry-run to install.")
        return

    print("\n--- installing (this can take a few minutes) ---\n")
    r = subprocess.run([chosen, "-m", "pip", "install", "--no-deps", pkg])
    if r.returncode != 0:
        print("\n[FAIL] pip could not install " + pkg + " (see above).")
        print("Common causes: no internet / proxy, or this python has no pip")
        print("(check:  \"" + chosen + "\" -m pip --version )")
        sys.exit(1)

    if pkg == "clearvoice":
        print("\n--- resolving dependencies (the target python lists them) ---")
        code = ("import sys; sys.path.insert(0, r'%s');"
                "import enhance as E;"
                "log = [];"
                "ok, steps = E.resolve_dependencies(log=log);"
                "[print('   ' + s, flush=True) for s in steps];"
                "sys.exit(0 if ok else 1)" % str(Path(__file__).parent))
        r = subprocess.run([chosen, "-c", code])
        if r.returncode != 0:
            print("[FAIL] dependency resolution did not complete — the steps "
                  "above show the last module that failed.")
            sys.exit(1)

    print("\n--- verifying ---")
    mod = "clearvoice" if pkg == "clearvoice" else "df"
    ok = has(chosen, f"import {mod}; print('ok')", timeout=600)
    if not ok:
        print(f"[FAIL] {pkg} installed but does not import. Copy the output")
        print("       above and check the model/version messages.")
        sys.exit(1)
    print(f"[OK]   {pkg} imports in {chosen}")

    if pkg == "clearvoice" and not a.no_warmup:
        print()
        print("--- downloading the neural weights once (" + CV_MODEL_NOTE + ") ---")
        code = (f"import sys; sys.path.insert(0, r'{Path(__file__).parent}');"
                "import enhance as E;"
                f"E.ensure_cv_models(r'{Path(__file__).parent}', True, []);"
                "print('weights:', E.cv_weights_ready(r'%s','MossFormer2_SE_48K'),"
                " E.cv_weights_ready(r'%s','MossFormer2_SR_48K'))"
                % (Path(__file__).parent, Path(__file__).parent))
        r = subprocess.run([chosen, "-c", code])
        if r.returncode == 0:
            print("[OK]   neural weights present (no download needed at job time)")
        else:
            print("[NOTE] weights were not downloaded now — they will be "
                  "fetched on the first Clean & Clear job instead.")

    print("\nDone. Now run 00_preflight.py (or run_all.bat) — check H")
    print("should say: clearvoice — best quality (neural denoise + SR).")
    print("In Sonora the label under CLEAN & CLEAR will show the engine.")


if __name__ == "__main__":
    main()
