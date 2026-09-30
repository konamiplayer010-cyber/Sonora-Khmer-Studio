#!/usr/bin/env python3
"""03_rvc_convert.py — convert every valid TTS WAV through the Sonaro-Kh RVC
model into rvc_output/ (spec sections 14, 15, 30).

    tts/chapter_XX_chunk_NNNN.wav
        -> RVC (verified in-process VC API, ONE loaded model)
        -> rvc_output/chapter_XX_chunk_NNNN.wav  (validated)

Run with the RVC python (run_all.bat does this automatically). With the
system python it checks for torch and tells you which interpreter to use.

Settings come from config.json "rvc" and are identical for every chunk
(spec 15: ONE verified configuration for the whole project). The index is
the exact file from config — never a guessed replacement (spec 38).
"""
import os
import sys
import time

# Stage 03 runs with the python that owns RVC (stage 03 in run_all.bat, and the
# same step inside test_clone). An embedded RVC python (a `runtime` folder with
# a python._pth) may not add this script's folder to sys.path by itself, so do
# it here — otherwise "import common" fails and nothing else is attempted.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common as C


def main():
    cfg = C.load_config()

    # Some RVC installs keep their python packages inside the RVC folder itself
    # (an "extralibs"/runtime layout). Append it (never prepend) so RVC's own
    # modules are importable while the pipeline's modules still win.
    _rr = (cfg.get("rvc_root") or "").strip()
    if _rr and os.path.isdir(_rr) and _rr not in sys.path:
        sys.path.append(_rr)

    log = C.load_log()
    chunks = sorted(log["chunks"].keys())
    if not chunks:
        print("[MISSING] no chunks — run 01 + 02 first")
        sys.exit(1)

    # --- this script needs torch + the RVC packages ---
    try:
        import torch  # noqa: F401
    except Exception:
        rpy = C.detect_rvc_python(cfg)
        print("[FAIL] this python has no torch. Run 03 with the RVC python:")
        if rpy:
            print(f"       {rpy} 03_rvc_convert.py")
        else:
            print("       (no venv found under rvc_root — set \"rvc_python\" in config.json)")
        sys.exit(1)

    # --- resolve model + index (no guessing; report exact problems) ---
    try:
        model, how = C.resolve_model(cfg)
    except (FileNotFoundError, RuntimeError) as e:
        print("[MISSING]\n  item:         RVC model (.pth)")
        print(str(e))
        sys.exit(1)
    try:
        index = C.resolve_index(cfg)
    except FileNotFoundError as e:
        print("[MISSING]\n  item:         RVC index (.index)")
        print(str(e))
        sys.exit(1)
    if how == "discovered":
        cfg["model_file"] = str(model)
        C.save_config(cfg)
    print(f"[OK]   model: {model} ({how})")
    print(f"[OK]   index: {index}")
    print(f"[OK]   settings: {cfg.get('rvc')}")

    import rvc_engine
    try:
        rvc_engine.get_loaded(cfg.get("rvc_root"), model, index)
        log["meta"]["rvc_api"] = rvc_engine._LOADED[
            (os.path.abspath(cfg.get("rvc_root")), os.path.abspath(model))][1]
        C.save_log(log)
    except Exception as e:
        print("[FAIL] could not load the RVC model in this environment:")
        print(str(e)[:500])
        sys.exit(1)

    retries = int(cfg.get("retries", 2))
    settings = cfg.get("rvc", {})
    done = skipped = failed = 0
    failures = []
    t0 = time.time()

    for i, cid in enumerate(chunks, 1):
        src = C.tts_path(cid)
        target = C.rvc_path(cid)
        st_tts = log["chunks"].get(cid, {}).get("tts")
        if st_tts != "success":
            print(f"[{i}/{len(chunks)}] {cid}  SKIP (TTS not successful)")
            continue
        if not src.exists():
            msg = "TTS wav missing (log says success — re-run 02)"
            failures.append((cid, "rvc", msg))
            C.set_stage(log, cid, "rvc", "failed", error=msg)
            C.save_log(log)
            continue

        if target.exists():
            ok, info, probs = C.validate_wav(target)
            if ok:
                skipped += 1
                C.set_stage(log, cid, "rvc", "success")
                print(f"[{i}/{len(chunks)}] {cid}  SKIP (valid, {info['duration']}s)")
                C.save_log(log)
                continue
            print(f"[{i}/{len(chunks)}] {cid}  existing file INVALID ({probs}) — regenerating")

        def attempt():
            out = C.ROOT / "rvc_output" / (cid + ".part")
            C.atomic_audio(str(out), lambda t: rvc_engine.convert_wav(
                cfg.get("rvc_root"), model, index, str(src), str(t), settings))
            out.rename(target)
            return True

        res, attempts, err = C.retry_call(attempt, retries, 4.0, cid)
        if res is not None:
            done += 1
            C.set_stage(log, cid, "rvc", "success", extra={"attempts": attempts})
            print(f"[{i}/{len(chunks)}] {cid}  OK ({'retried' if attempts > 1 else ''})")
        else:
            failed += 1
            msg = str(err)[:200]
            failures.append((cid, "rvc", msg))
            C.set_stage(log, cid, "rvc", "failed", error=msg)
            print(f"[{i}/{len(chunks)}] {cid}  FAILED after {attempts} attempts: {msg}")
        C.save_log(log)

    C.save_log(log)
    print()
    print(f"RVC STAGE: {done} converted, {skipped} skipped, {failed} failed "
          f"({time.time() - t0:.0f}s)")
    if failures:
        print("\nFAILED CHUNKS:")
        for cid, stage, err in failures:
            print(f"  {cid}  [{stage}]  {err}")
        print("\nRe-run this stage — successful chunks are not re-converted.")
        sys.exit(1)
    print("STAGE 3 COMPLETE (RVC)")


if __name__ == "__main__":
    main()
