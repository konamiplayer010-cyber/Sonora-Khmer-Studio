#!/usr/bin/env python3
"""00_preflight.py — verify the whole production environment before any
narration is processed (spec sections 4, 6, 44).

    python 00_preflight.py            # checks A-F
    python 00_preflight.py --full     # A-F + G: one real TTS->RVC test
                                      # conversion (logs/preflight_test.wav)

Exit code 0 = all checks passed. On any failure it prints the exact
[MISSING] item, expected location, and what is required — then STOPS.
"""
import sys
import time

import common as C


def main():
    cfg = C.load_config()
    failed = False
    print("=" * 60)
    print("PRE-FLIGHT CHECK — " + str(cfg.get("project")))
    print("=" * 60)

    # A. RVC root
    root = (cfg.get("rvc_root") or "").strip()
    root_ok = bool(root)
    if root_ok:
        import os
        root_ok = os.path.isdir(root)
    failed = not C.report_line(root_ok, "A. RVC root", root or "(empty in config)") or failed

    # B. Index (exact file — never a replacement)
    try:
        idx = C.resolve_index(cfg)
        C.report_line(True, "B. RVC index", idx)
    except FileNotFoundError as e:
        failed = True
        print("[MISSING]\n  item:         RVC index (.index)\n  "
              "expected:     see error text\n  required:     exact path from your RVC-WebUI "
              "Feature index path field")
        print(str(e))

    # C. Model (.pth) — configured, or discovered (reported)
    model_ok = True
    model = ""
    try:
        model, how = C.resolve_model(cfg)
        note = "" if how == "config" else "  (discovered from installation — not in config)"
        # sanity: a training checkpoint (G_/D_ in logs/) is NOT a voice model
        import os as _os
        base = _os.path.basename(str(model))
        size_mb = _os.path.getsize(model) / 1048576.0
        if base[:2].upper() in ("G_", "D_") or size_mb >= 150:
            model_ok = False
            failed = True
            print("[MISSING]")
            print("  item:         RVC voice model (.pth) — usable one")
            print(f"  given:        {model}")
            print(f"  why:          this is a TRAINING CHECKPOINT ({size_mb:.0f} MB, "
                  f"'{base}'), not the small voice model inference needs")
            print("  required:     extract the small model first — RVC-WebUI →")
            print("                ckpt-processing tab (also holds 'model fusion')")
            print("                → 'extract small model' on the newest G_*.pth")
            print("                → save as assets/weights/Sonaro-kh.pth")
            print("                then run:  python check_model.py")
            model = str(model)
        else:
            C.report_line(True, "C. RVC model",
                          model + note + f"  ({size_mb:.0f} MB)")
            if how == "discovered":
                cfg["model_file"] = str(model)
                C.save_config(cfg)
                print("       saved the discovered model into config.json")
    except (FileNotFoundError, RuntimeError) as e:
        failed = True
        model_ok = False
        C.report_line(False, "C. RVC model", str(e)[:300])
        print("       tip: run  python check_model.py  to see every .pth in your")
        print("       RVC folder and which one is the real voice model.")
    except (FileNotFoundError, RuntimeError) as e:
        failed = True
        print("[MISSING]\n  item:         RVC model (.pth)\n  "
              "expected:     <rvc_root>\\assets\\weights\\<name>.pth\n  "
              "required:     the real filename — do not guess")
        print(str(e))

    # D. RVC inference entry point + python
    api = C.detect_rvc_api(root)
    C.report_line(api is not None, "D1. RVC inference API",
                  api or "NOT FOUND — is rvc_root the root of RVC-WebUI (the folder with RVC.py / infer/)?")
    rpy = C.detect_rvc_python(cfg)
    cur = sys.executable
    if rpy:
        import os
        same = os.path.abspath(rpy) == os.path.abspath(cur)
        C.report_line(True, "D2. RVC python",
                      rpy + ("" if same else "   (the RVC stages run with this one, "
                                             "not with the python you started)"))
    else:
        try:
            import torch  # noqa: F401
            C.report_line(True, "D2. RVC python",
                          cur + "  (no venv found; current interpreter has torch)")
        except Exception:
            failed = True
            print("[MISSING]\n  item:         RVC python environment\n"
                  "  expected:     <rvc_root>\\venv\\Scripts\\python.exe\n"
                  "  required:     the python that runs your RVC-WebUI, "
                  "set as \"rvc_python\" in config.json")

    # D2. Narration style (only when one is asked for)
    style = (cfg.get("narration_style") or "").strip()
    if style and style.lower() not in ("off", "none", "plain"):
        try:
            import narration as NAR
            sid = NAR.style_id(style)
            sp = NAR.spec(sid)
            if sid == "natural" and style.strip().lower() not in (
                    "natural", "natural read", "natural_read"):
                C.report_line(False, "F. Narration style",
                              f"'{style}' is not a known style — falling back to "
                              f"a plain read")
                print("         known styles: " + ", ".join(NAR.STYLE_ORDER))
                failed = True
            else:
                C.report_line(True, "F. Narration style",
                              f"{sp['label']} — one TTS call per sentence "
                              f"(intensity {sp['intensity'][0]}-{sp['intensity'][1]}, "
                              f"pace {sp['pace'][0]:.2f}-{sp['pace'][1]:.2f}x)")
        except Exception as e:
            C.report_line(False, "F. Narration style",
                          f"narration.py unavailable: {type(e).__name__}")

    # E. Khmer TTS engines (fallback chain)
    try:
        import khmer_tts as KT
        usable = KT.available_engines()
        try:
            import edge_tts  # noqa: F401
            edge_ok = True
        except Exception:
            edge_ok = False
        if usable:
            want = cfg.get("tts_engine", "auto")
            voice = cfg.get("tts_voice", "km-KH-SreymomNeural")
            note = " -> ".join(usable)
            if want != "auto":
                note = f"forced '{want}'; ready: {note}"
            else:
                note += f"   voice: {voice}"
            C.report_line(True, "E. Khmer TTS engines", note)
            for row in KT.status():
                if not row["installed"]:
                    print(f"         optional: {row['engine']:7s} "
                          f"{row['label']}  ->  {row['install']}")
            if not edge_ok:
                print("         NOTE: Microsoft edge-tts is not installed - the "
                      "fallback chain will be used.")
                failed = True
        else:
            failed = True
            print("[MISSING]\n  item:         a Khmer TTS engine\n"
                  "  expected:     edge-tts (internet) or transformers+torch "
                  "(offline)\n"
                  "  required:     pip install -r requirements_system.txt")
    except Exception as e:
        failed = True
        print("[MISSING]\n  item:         khmer_tts.py / edge-tts\n"
              f"  detail:       {type(e).__name__}: {e}\n"
              "  required:     run:  pip install -r requirements_system.txt")

    # F. Output folders
    try:
        for d in ("input", "normalized", "tts", "rvc_output", "final", "logs"):
            C.sub_dir(d)
        inp = C.ROOT / (cfg.get("input_file") or "input/history_kh.txt")
        if not inp.exists():
            print(f"[NOTE]   F. input script not present yet: {inp}  (create it to start a project)")
        else:
            C.report_line(True, "F. input script", str(inp))
        C.report_line(True, "F. output folders", "input/ normalized/ tts/ rvc_output/ final/ logs/")
    except Exception as e:
        failed = True
        C.report_line(False, "F. output folders", str(e))

    # H. Clean & Clear engine (informational — never blocks the pipeline)
    cm = cfg.get("clean_master") or {}
    if cm:
        if not cm.get("enabled", True):
            print("[SKIP]   H. Clean & Clear: disabled in config.json "
                  "(clean_master.enabled = false)")
        else:
            import enhance as E
            ff = C.find_ffmpeg(cfg)
            if not ff:
                print("[WARN]   H. Clean & Clear: ffmpeg not found — stage 05 "
                      "will fail. Set ffmpeg_exe in config.json or make sure "
                      "ffmpeg is on PATH.")
            else:
                have = E.model_backends()
                if have:
                    C.report_line(True, "H. Clean & Clear",
                                  f"ffmpeg + {' + '.join(have)} (best quality)")
                else:
                    C.report_line(True, "H. Clean & Clear",
                                  "ffmpeg chain (spectral denoise, de-ess, "
                                  "48 kHz, loudness master)")
                    print("         tip: for maximum clarity install the "
                          "neural engine -")
                    print("              double-click install_clean_engine.bat "
                          "(one click, no terminal):")
                    print("              it finds your python itself and "
                          "installs clearvoice safely.")

    if not root_ok or api is None:
        failed = True
        print("\nPRE-FLIGHT FAILED — fix the items above, then re-run. "
              "Not guessing. Not proceeding.")
        sys.exit(1)

    # G. Test conversion (optional, --full) — only when A-F all passed
    if "--full" in sys.argv and failed:
        print("\nSkipping G (test conversion): A-F has failures above. "
              "Fix those first.")
        print("PRE-FLIGHT: FAILED — see items above.")
        sys.exit(1)
    if "--full" in sys.argv:
        print("\n--- G. Test conversion (TTS -> RVC, one small sentence) ---")
        import json as _json
        import os as _os
        import re as _re
        import subprocess
        t0 = time.time()
        ok = True
        out_wav = str(C.LOG_DIR / "preflight_test.wav")

        # --- G1. the voice half (ordinary packages: this interpreter can do it)
        tts_wav = None
        try:
            import rvc_engine
            tts_wav = rvc_engine.make_test_tts(cfg)
            C.report_line(True, "G1. test sentence (TTS)", tts_wav)
        except Exception as e:
            ok = False
            C.report_line(False, "G1. test sentence (TTS)", str(e)[:400])

        # --- G2. the clone half: RVC lives in its own environment, so this runs
        # with the python that owns RVC (a venv, or the WebUI's runtime python).
        # Importing RVC with the pipeline's ordinary python is the wrong way
        # round: that interpreter has neither torch nor soundfile nor RVC.
        engine_py = str(_os.path.join(
            _os.path.dirname(_os.path.abspath(__file__)), "rvc_engine.py"))
        if tts_wav:
            try:
                if rpy and _os.path.abspath(rpy) != _os.path.abspath(cur):
                    cmd = [rpy, engine_py,
                           "--rvc-root", root, "--model", str(model),
                           "--in", tts_wav, "--out", out_wav]
                    if idx:
                        cmd += ["--index", str(idx)]
                    cmd += ["--settings-json",
                            _json.dumps(cfg.get("rvc", {}) or {}, ensure_ascii=False)]
                    env2 = _os.environ.copy()
                    _pp = _os.path.dirname(engine_py)
                    env2["PYTHONPATH"] = _pp + (
                        (_os.pathsep + env2["PYTHONPATH"]) if env2.get("PYTHONPATH") else "")
                    try:
                        # run it the way RVC's own launcher does: from inside
                        # the RVC folder (configs/, i18n/, assets/ are read
                        # relative to the working directory)
                        r = subprocess.run(
                            cmd,
                            cwd=(root if _os.path.isdir(root) else str(C.ROOT)),
                            capture_output=True, text=True, env=env2, timeout=900)
                    except subprocess.TimeoutExpired:
                        raise RuntimeError(
                            "the RVC python did not finish the test conversion "
                            "within 15 minutes — it may be waiting on a file or "
                            "on the GPU")
                    tail = [ln for ln in ((r.stdout or "") + (r.stderr or "")
                                          ).splitlines() if ln.strip()]
                    for ln in tail[-24:]:
                        print("       " + ln[:400])
                    _full = "\n".join(tail)
                    if r.returncode != 0 or not _os.path.exists(out_wav):
                        # which packages are genuinely missing? (a layout name
                        # such as 'infer.modules' is not a package to install —
                        # it only means that RVC version is not the layout here)
                        miss = [m for m in _re.findall(r"No module named '([^']+)'",
                                                       _full)
                                if not m.split(".")[0] in ("infer", "configs",
                                                           "i18n", "lib", "uvr5")]
                        if miss:
                            # keep the literal text too, so the hander below can
                            # see which package it is
                            why = ("RVC's python is missing the package '%s' "
                                   "(No module named '%s')" % (miss[0], miss[0]))
                        elif "no module named" in _full.lower() or tail:
                            why = ("RVC could not load in its own python — its "
                                   "own error lines are printed above (full text "
                                   "in logs\\preflight_rvc_error.txt)")
                        else:
                            why = ("the RVC python exited with code "
                                   + str(r.returncode))
                        raise RuntimeError("the RVC python could not do the "
                                           "conversion — " + why)
                else:
                    # same interpreter for both halves (a complete install, or a
                    # test harness) — do it in-process
                    import rvc_engine  # noqa: F811
                    rvc_engine.convert_wav(root, str(model), idx, tts_wav,
                                           out_wav, cfg.get("rvc", {}))
                g_ok, info, probs = C.validate_wav(out_wav)
                if not g_ok:
                    raise RuntimeError("test audio invalid: " + "; ".join(probs))
                C.report_line(True, "G2. clone conversion (RVC)",
                              f"{out_wav}  ({info.get('duration')}s, "
                              f"{info.get('sr')} Hz)")
            except Exception as e:
                ok = False
                msg = str(e)
                C.report_line(False, "G2. clone conversion (RVC)", msg[:700])
                print("       The clone stage runs with the python that owns RVC:")
                print("         " + (rpy or '(none found — nothing under the RVC '
                                            'folder has torch)'))
                misses = [m for m in _re.findall(r"No module named '([^']+)'", msg)
                          if m.split(".")[0] not in ("infer", "configs", "i18n",
                                                     "lib", "uvr5")]
                if misses:
                    print("       RVC itself needs the package '" + misses[0] +
                          "' to do a conversion, and that python does not have it.")
                    print("       One step installs it:   START.bat -> 12   "
                          "(Fix the RVC python)")
                else:
                    print("       The reason is in the line(s) above. Send me this "
                          "window and I will read it.")
                    print("       Another python might own your RVC-WebUI: menu 6 "
                          "lists the candidates;")
                    print("       the one you pick goes into \"rvc_python\" in "
                          "pipeline\\config.json.")
                try:
                    C.LOG_DIR.mkdir(parents=True, exist_ok=True)
                    with open(C.LOG_DIR / "preflight_rvc_error.txt", "w",
                              encoding="utf-8") as fh:
                        fh.write("command:\n" + " ".join(
                            (cmd if tts_wav else [engine_py])))
                        fh.write("\n\n--- the RVC python said ---\n")
                        fh.write(locals().get("_full", "") + "\n")
                        fh.write("\n--- report ---\n" + msg + "\n")
                    print("       Full detail saved to: logs\\preflight_rvc_error.txt")
                except Exception:
                    pass
        print(f"       ({time.time() - t0:.1f}s)")
        if not ok:
            failed = True
            print("G FAILED — TEST FAILED. Do not start a project until this passes.")
            sys.exit(1)
        print("TEST PASSED (technical). Listen to logs/preflight_test.wav and compare")
        print("it with your reference " + (cfg.get("test_voice") or "Sonaro-kh_test.wav") + ".")

    print()
    if failed:
        print("PRE-FLIGHT: FAILED — see items above.")
        sys.exit(1)
    print("PRE-FLIGHT: PASSED — configuration is valid. Ready to process.")


if __name__ == "__main__":
    main()
