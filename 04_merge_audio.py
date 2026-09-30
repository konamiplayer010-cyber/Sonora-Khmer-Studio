#!/usr/bin/env python3
"""04_merge_audio.py — assemble chapters from validated RVC chunks, then the
final narration (spec sections 21-24, 25, 31).

    rvc_output/chapter_XX_chunk_NNNN.wav  (ALL validated)
        -> final/chapter_XX.wav
        -> final/<final_name>.wav   (numeric chapter order — never lexical)

A chapter is only assembled when EVERY one of its chunks exists and passes
validation; a gap stops the stage with the exact missing list. Existing
valid chapter/final files are skipped (never overwritten).
"""
import re
import sys
import time

import common as C


def ch_num(cid):
    return int(cid.split("/")[0].split("_")[1])


def concat_wavs(sources, target, rate):
    """Load (resample if needed) and concatenate to a 16-bit WAV at `rate`."""
    import numpy as np
    try:
        from scipy.signal import resample_poly
        from math import gcd
    except Exception:
        resample_poly = None
    parts = []
    for s in sources:
        sr, data = C.read_wav_f32(s)
        if resample_poly is not None and sr != rate:
            g = gcd(int(sr), int(rate))
            data = resample_poly(data, rate // g, sr // g)
        parts.append(data)
    out = np.concatenate(parts) if parts else np.zeros(1, dtype=np.float32)
    C.write_wav(target, out, rate)


def main():
    cfg = C.load_config()
    log = C.load_log()
    chunks = log["chunks"]
    rate = int(cfg.get("final_sample_rate", 44100))
    final_dir = C.sub_dir("final")

    by_ch = {}
    for cid in chunks:
        by_ch.setdefault(ch_num(cid), []).append(cid)
    ch_nums = sorted(by_ch)
    if not ch_nums:
        print("[MISSING] no chunks — run the earlier stages first")
        sys.exit(1)

    t0 = time.time()
    missing_any = []
    chapter_files = []
    for ch in ch_nums:
        cids = sorted(by_ch[ch])
        bad = []
        for cid in cids:
            if chunks[cid].get("rvc") != "success":
                bad.append(f"{cid} (rvc status: {chunks[cid].get('rvc', 'missing')})")
                continue
            p = C.rvc_path(cid)
            if not p.exists():
                bad.append(f"{cid} (file missing)")
                continue
            ok, info, probs = C.validate_wav(p)
            if not ok:
                bad.append(f"{cid} ({'; '.join(probs)})")
        if bad:
            missing_any += bad
            print(f"[FAIL]   {C.chapter_id(ch)}: CANNOT assemble — {len(bad)} bad chunk(s):")
            for b in bad[:20]:
                print("         " + b)
            if len(bad) > 20:
                print(f"         ... and {len(bad) - 20} more")
            continue
        target = final_dir / f"{C.chapter_id(ch)}.wav"
        if target.exists():
            ok, info, probs = C.validate_wav(target)
            if ok:
                print(f"[OK]   {target.name}  SKIP (valid, {info['duration']}s)")
                chapter_files.append((ch, target, info["duration"]))
                continue
        concat_wavs([C.rvc_path(c) for c in cids], target, rate)
        ok, info, probs = C.validate_wav(target)
        if not ok:
            missing_any.append(f"{target.name}: {'; '.join(probs)}")
            print(f"[FAIL]   {target.name} failed validation: {probs}")
            continue
        print(f"[OK]   {target.name}  ({info['duration']}s, {len(cids)} chunks)")
        chapter_files.append((ch, target, info["duration"]))
        C.save_log(log)

    if missing_any:
        print("\nFINAL ASSEMBLY NOT DONE — fix and re-run (chapters with valid")
        print("chunks are not rebuilt):")
        sys.exit(1)

    # ---- final file: numeric order (spec 22) ----
    final_name = cfg.get("final_name", "History_Narration_SONARO_KH.wav")
    final_path = final_dir / final_name
    chapter_files.sort(key=lambda x: x[0])
    if final_path.exists():
        ok, info, probs = C.validate_wav(final_path)
        if ok and len(chapter_files) == len(by_ch):
            print(f"[OK]   final  SKIP (valid, {info['duration']}s)")
            total_dur = info["duration"]
        else:
            concat_wavs([f for _, f, _ in chapter_files], final_path, rate)
            ok, info, probs = C.validate_wav(final_path)
            total_dur = info["duration"] if ok else 0
    else:
        concat_wavs([f for _, f, _ in chapter_files], final_path, rate)
        ok, info, probs = C.validate_wav(final_path)
        total_dur = info["duration"] if ok else 0

    # ---- final report (spec 24 + 25) ----
    total, per = C.counts(log)
    tts_ok = per.get("tts", {}).get("success", 0)
    tts_fail = per.get("tts", {}).get("failed", 0)
    rvc_ok = per.get("rvc", {}).get("success", 0)
    rvc_fail = per.get("rvc", {}).get("failed", 0)
    retried = sum(1 for e in chunks.values()
                  if any(e.get(k, 0) > 1 for k in ("attempts",)))
    status = "SUCCESS" if (ok and rvc_fail == 0 and tts_fail == 0) else "FAILED"
    report = [
        "PRODUCTION REPORT", "=" * 40,
        f"Project:        {cfg.get('project')}",
        f"Total chapters: {len(ch_nums)}",
        f"Total chunks:   {total}",
        f"TTS successful: {tts_ok}   failed: {tts_fail}",
        f"RVC successful: {rvc_ok}   failed: {rvc_fail}",
        f"Retried chunks: {retried}",
        f"Final duration: {round(total_dur, 1)}s",
        f"Final WAV:      {final_path}",
        f"RVC API:        {log['meta'].get('rvc_api', '')}",
        f"RVC settings:   {cfg.get('rvc')}",
        f"Status:         {status}",
        "",
    ]
    if status == "FAILED":
        report.append("FAILURES:")
        for cid, e in chunks.items():
            for stage in ("tts", "rvc"):
                if e.get(stage) == "failed":
                    report.append(f"  {cid} [{stage}] {e.get('error', '')}")
    report_text = "\n".join(report)
    (final_dir / "report.txt").write_text(report_text, encoding="utf-8")

    # listen.html — double-click to hear every chapter with a ▶ button
    groups = [("Final narration", [(final_name, final_name)])]
    groups.append(("Chapters", [(f"chapter {ch}", f.name)
                                for ch, f, _ in chapter_files]))
    C.write_listen_page(
        final_dir, f"Listen — {cfg.get('project')}", groups,
        note="These files are the Sonaro-Kh narration before Clean & Clear. "
             "Run 05_clean_master.py (or run_all.bat) and open master/listen.html "
             "to compare raw vs clean.")

    C.save_log(log)
    print()
    print(report_text)
    print(f"FINAL VALIDATION: {'PASSED' if ok else 'FAILED'} "
          f"({time.time() - t0:.0f}s)")
    sys.exit(0 if ok and status == "SUCCESS" else 1)


if __name__ == "__main__":
    main()
