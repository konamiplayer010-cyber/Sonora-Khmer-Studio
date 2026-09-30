#!/usr/bin/env python3
"""05_clean_master.py — "Clean & Clear" stage (runs after 04_merge_audio.py).

    final/chapter_XX.wav          (from stage 04)
        -> master/chapter_XX.wav          (denoised, de-essed, 48 kHz,
                                           loudness-mastered)
        -> master/<final_name>_CLEAN.wav  (all chapters, numeric order)
        -> master/report.txt              (full production report)

Resume-aware and non-destructive, exactly like the other stages:
  * a chapter whose master already exists and validates is SKIPPED,
  * a failing chapter stops assembly of the final master with the exact
    reason, other chapters are left alone,
  * stage 04's final/ files are never modified or deleted.

Which engine runs? cfg["clean_master"]["tier"]:
  auto    -> best available (model backends if importable, else ffmpeg)
  ffmpeg  -> always works; spectral denoise + resample to 48 kHz
  model   -> requires clearvoice or deepfilternet in the RVC python
The report states exactly which engine and stages really ran.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import common as C
import enhance as E


def probe_python(py, module_probe=None):
    """Cheap probe: which model backends does this python have?"""
    code = ("import json,importlib.util as u;"
            "print(json.dumps([n for n,s in (('clearvoice','clearvoice'),"
            "('deepfilternet','df')) if u.find_spec(s)]))")
    try:
        r = subprocess.run([py, "-c", code], capture_output=True, timeout=60)
        if r.returncode == 0:
            return json.loads((r.stdout or b"[]").decode() or "[]")
    except Exception:
        pass
    return []


def pick_python(cfg, tier):
    """Return (python, backends). Prefers a python that has a model backend;
    ffmpeg tier doesn't care."""
    cands = []
    rpy = C.detect_rvc_python(cfg)
    if rpy:
        cands.append(rpy)
    if cfg.get("rvc_python"):
        cands.append(cfg["rvc_python"])
    cands.append(sys.executable)
    seen, best = set(), []
    for py in cands:
        key = str(py).lower()
        if key in seen or not py:
            continue
        seen.add(key)
        have = probe_python(py)
        if have:
            return py, have
        best.append((py, have))
    if tier == "model":
        return None, []
    return sys.executable, []


def enhance_via_python(py, src_wav, dst_wav, base, ffmpeg, lufs, peak, sr,
                       denoise, eq, deess, super_res):
    """Run enhance.py as a SUBPROCESS with the python that has the engine.

    Needed because this stage may run on a plain system python (no torch):
    the engine then lives in the RVC python, and importing it here would
    fail. Same approach Sonora uses, so both apps behave identically.
    """
    cmd = [py, str(C.ROOT / "enhance.py"), "--in", str(src_wav),
           "--out", str(dst_wav), "--tier", "model",
           "--lufs", str(lufs), "--peak", str(peak), "--sr", str(sr),
           "--deess", str(deess), "--base", str(base)]
    if ffmpeg:
        cmd += ["--ffmpeg", str(ffmpeg)]
    if not denoise:
        cmd += ["--no-denoise"]
    if not eq:
        cmd += ["--no-eq"]
    if not super_res:
        cmd += ["--no-super-res"]
    rep_path = str(dst_wav) + ".report.json"
    cmd += ["--json", rep_path]
    r = subprocess.run(cmd, capture_output=True, timeout=7200, cwd=str(C.ROOT))
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or b"").decode("utf-8", "ignore")[-600:]
        return {"ok": False, "backend": "", "error": tail or "engine python failed"}
    try:
        with open(rep_path, "r", encoding="utf-8") as fh:
            rep = json.load(fh)
    except Exception:
        rep = {"ok": os.path.exists(str(dst_wav)), "backend": "clearvoice"}
    finally:
        try:
            os.remove(rep_path)
        except OSError:
            pass
    rep["ran_in"] = py
    return rep


def main():
    cfg = C.load_config()
    log = C.load_log()
    cm = dict(cfg.get("clean_master") or {})
    if not cm:
        print("[SKIP] no 'clean_master' block in config.json — stage 05 is off")
        print("STAGE 5 SKIPPED (Clean & Clear not configured)")
        return
    if not cm.get("enabled", True):
        print("[SKIP] clean_master.enabled = false in config.json")
        print("STAGE 5 SKIPPED (Clean & Clear disabled)")
        return

    final_dir = C.sub_dir("final")
    master_dir = C.sub_dir("master")
    os.makedirs(master_dir, exist_ok=True)
    tier = cm.get("tier", "auto")
    sr = int(cm.get("sample_rate", 48000))
    lufs = float(cm.get("target_lufs", -16.0))
    peak = float(cm.get("true_peak_db", -1.0))

    ppt = cm.get("python", "")          # optional: pin the enhancement python
    if ppt:
        py, have = (ppt, probe_python(ppt))
    else:
        py, have = pick_python(cfg, tier)
    if py is None:
        print("[FAIL] clean_master.tier = 'model' but no python with "
              "clearvoice/deepfilternet was found.")
        print("       Install one in the RVC environment:")
        print("         pip install clearvoice     (best: denoise + 48 kHz SR)")
        print("         pip install deepfilternet  (light denoise only)")
        sys.exit(1)
    if tier == "auto" and not have:
        tier = "ffmpeg"
    engine = ", ".join(have) if have else "ffmpeg"

    t0 = time.time()
    print(f"[OK]   engine: {engine}   (tier={tier}, python={py})")
    if not have:
        print("[info] the model backends are not installed in that python —")
        print("       using the built-in ffmpeg chain (still a real cleanup:")
        print("       spectral denoise, de-ess, 48 kHz, loudness master).")
        print("       For maximum clarity, install the neural engine:")
        print("         double-click install_clean_engine.bat - it finds your")
        print("         python itself, installs safely, and needs no terminal.")

    chapters = sorted(final_dir.glob("chapter_*.wav"))
    if not chapters:
        print("[MISSING] no final/chapter_XX.wav — run 04_merge_audio.py first")
        sys.exit(1)

    state = log.setdefault("master", {})
    bad, made, rebuilt = [], [], []
    for ch_path in chapters:
        cid = ch_path.stem
        target = master_dir / ch_path.name
        if target.exists():
            ok, info, probs = C.validate_wav(target)
            if ok and state.get(cid, {}).get("status") == "success":
                print(f"[OK]   {target.name}  SKIP (valid, {info['duration']}s)")
                made.append((cid, target))
                continue
        # the combined package points both apps at one weights folder
        CLEAN_BASE = os.environ.get("CLEAN_CHECKPOINTS_DIR") or str(C.ROOT)
        denoise, eq = cm.get("denoise", True), cm.get("eq", True)
        deess = float(cm.get("de_ess_db", 2.5))
        sres = cm.get("super_res", True)
        ff = C.find_ffmpeg(cfg)
        try:
            here_backends = E.model_backends()   # can THIS process do it?
            if have and not here_backends:
                # engine installed in another python (your RVC env): run there
                print(f"[info] running the neural engine through {py}")
                rep = enhance_via_python(py, ch_path, target, CLEAN_BASE, ff,
                                         lufs, peak, sr, denoise, eq, deess, sres)
            else:
                rep = E.enhance_file(
                    ch_path, target, tier=("model" if have else "ffmpeg"),
                    ffmpeg=ff, lufs=lufs, peak=peak, sr=sr,
                    denoise=denoise, eq=eq, deess=deess, super_res=sres,
                    base=CLEAN_BASE)
        except Exception as e:
            rep = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        ok2, info2, probs2 = C.validate_wav(target)
        if not (rep.get("ok") and ok2):
            reason = rep.get("error") or "; ".join(probs2) or "unknown"
            state[cid] = {"status": "failed", "error": reason,
                          "time": time.strftime("%Y-%m-%d %H:%M:%S")}
            bad.append(f"{cid}: {reason}")
            print(f"[FAIL] {target.name}: {reason}")
            C.save_log(log)
            continue
        state[cid] = {
            "status": "success",
            "engine": rep.get("backend", "ffmpeg"),
            "bandwidth_extension": bool(rep.get("bandwidth_extension")),
            "in_lufs": (rep.get("in") or {}).get("lufs"),
            "out_lufs": (rep.get("out") or {}).get("lufs"),
            "true_peak_db": (rep.get("out") or {}).get("true_peak_db"),
            "sr": info2["sr"], "duration": info2["duration"],
            "stages": rep.get("stages", []),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        C.save_log(log)
        print(f"[OK]   {target.name}  ({info2['duration']}s, {info2['sr']} Hz, "
              f"engine={rep.get('backend', 'ffmpeg')})")
        made.append((cid, target))
        rebuilt.append(cid)

    if bad:
        print("\nCLEAN & CLEAR NOT COMPLETE — fix and re-run (valid chapters "
              "are kept):")
        for b in bad:
            print("  " + b)
        sys.exit(1)

    # ---- clean final master: numeric chapter order, same loudness target ---
    base = Path(cfg.get("final_name", "History_Narration_SONARO_KH.wav")).stem
    out_name = f"{base}_CLEAN.wav"
    out_path = master_dir / out_name
    made.sort(key=lambda x: int(x[0].split("_")[1]))
    need = os.environ.get("CLEAN_FORCE") == "1" or bool(rebuilt)
    skip_final = False
    if out_path.exists() and not need:
        ok, info, probs = C.validate_wav(out_path)
        if ok:
            print(f"[OK]   {out_name}  SKIP (valid, {info['duration']}s)")
            skip_final = True
    if not skip_final:
        C.atomic_audio(out_path, lambda tmp: concat([p for _, p in made],
                                                    tmp, sr))
        ok, info, probs = C.validate_wav(out_path)
        if not ok:
            print(f"[FAIL] {out_name} validation: {probs}")
            sys.exit(1)
        print(f"[OK]   {out_name}  ({info['duration']}s, {info['sr']} Hz)")

    # ---- optional delivery MP3 (only ever at the very end) ----
    mp3_line = "MP3 delivery:   not requested (clean_master.export_mp3=false)"
    if cm.get("export_mp3"):
        mp3_path = master_dir / (Path(out_name).stem + ".mp3")
        ff = C.find_ffmpeg(cfg)
        try:
            subprocess.run([ff, "-hide_banner", "-nostats", "-y", "-i",
                            str(out_path), "-b:a",
                            str(cm.get("mp3_bitrate", "192k")), str(mp3_path)],
                           capture_output=True, timeout=3600, check=True)
            mp3_line = f"MP3 delivery:   {mp3_path}"
            print(f"[OK]   {mp3_path.name} ({mp3_path.stat().st_size // 1024} KB)")
        except Exception as e:
            mp3_line = f"MP3 delivery:   FAILED ({type(e).__name__})"

    # ---- report ----
    total, per = C.counts(log)
    m_ok = sum(1 for v in state.values() if v.get("status") == "success")
    m_fail = sum(1 for v in state.values() if v.get("status") == "failed")
    ext = sum(1 for v in state.values() if v.get("bandwidth_extension"))
    lines = [
        "", "CLEAN & CLEAR (stage 05)", "=" * 40,
        f"Engine:         {engine} ({tier})",
        f"Chapters:       {m_ok} mastered, {m_fail} failed",
        f"48 kHz SR:      {sr} Hz" + ("  (true super-resolution)"
                                      if ext else "  (resampled)"),
        f"Loudness:       {lufs} LUFS, true peak {peak} dB",
        f"Clean master:   {out_path}",
        mp3_line,
        "",
    ]
    rep_path = master_dir / "report.txt"
    prev = ""
    fr = final_dir / "report.txt"
    if fr.exists():
        prev = fr.read_text(encoding="utf-8")
    text = (prev.rstrip() + "\n" + "\n".join(lines)) if prev \
        else "\n".join(lines)
    rep_path.write_text(text, encoding="utf-8")
    C.save_log(log)

    # listen.html — the A/B page: raw (final/) vs clean (master/) per chapter
    groups = [("Deliverable — Clean & Clear master", [(out_name, out_name)])]
    ab = []
    for cid, p in made:
        fin = final_dir / p.name
        if fin.exists():
            ab.append((f"{cid} — raw (before)", f"../final/{p.name}"))
        ab.append((f"{cid} — Clean & Clear", p.name))
    if ab:
        groups.append(("Chapter-by-chapter A/B", ab))
    C.write_listen_page(
        master_dir, f"Listen clean — {cfg.get('project')}", groups,
        note=f"Engine: {engine}. Loudness target {lufs} LUFS, true peak "
             f"{peak} dB, 48 kHz. 'raw' rows play the stage-04 file from "
             f"../final/ for direct comparison.")

    print("\n" + "\n".join(lines))
    print(f"open this to listen:  {master_dir / 'listen.html'}")
    print(f"STAGE 5 COMPLETE (Clean & Clear) — {time.time() - t0:.0f}s")


def concat(sources, target, rate):
    import numpy as np
    try:
        from scipy.signal import resample_poly
    except Exception:
        resample_poly = None
    parts = []
    for s in sources:
        sr, data = C.read_wav_f32(s)
        if resample_poly is not None and sr != rate:
            from math import gcd
            g = gcd(int(sr), int(rate))
            data = resample_poly(data, rate // g, sr // g)
        parts.append(data)
    C.write_wav(target, np.concatenate(parts), rate)


if __name__ == "__main__":
    main()
