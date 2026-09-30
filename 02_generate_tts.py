#!/usr/bin/env python3
"""02_generate_tts.py — for every chunk text file, produce a validated TTS WAV.

    normalized/chapter_XX_chunk_NNNN.txt
        -> Khmer TTS (khmer_tts.py: edge-tts -> MMS -> gTTS fallback chain)
        -> WAV (24 kHz mono s16)
        -> validate (exists, opens, duration, not silent)
        -> tts/chapter_XX_chunk_NNNN.wav

The engine used for every chunk is written into the processing log, and the
config switches stay simple:  tts_engine "auto" (default) = best available,
or force one: "edge" | "voxcpm" | "mms" | "gtts".

Rules: a chunk whose WAV already exists AND passes validation is SKIPPED
(spec 13, 33 — never overwrite a successful file). Failed chunks get up to
`retries` automatic retries, then are marked failed and the STAGE stops for
them (other chunks continue). The processing log is updated after every
chunk, so a crash resumes cleanly.
"""
import os
import sys
import time

import common as C

try:
    import khmer_tts as KT          # Khmer engines + fallback chain
except Exception:                    # pragma: no cover
    KT = None

try:
    import narration as NAR          # Narration Style & Voice Performance engine
except Exception:                    # pragma: no cover
    NAR = None

_ENGINE_USED = {"engine": "", "voice": "", "style": ""}


def make_wav(cfg, text, target):
    """Synthesize one chunk with the best available Khmer engine.

    The part-file is written by the engine itself, then moved into place, so
    a half-written file never looks like success.
    """
    part = target.parent / (target.name + ".wav.part")
    style = (cfg.get("narration_style") or "").strip()
    if KT is not None and style and style.lower() not in ("", "off", "none", "plain"):
        # ---- performed reading: one TTS call per sentence, styled ----
        if NAR is None:
            print("      [style] narration.py missing — falling back to a plain read")
        else:
            ff = C.find_ffmpeg(cfg) or "ffmpeg"
            def _one(t, out, rate_pct, pitch_hz):
                return KT.synth(
                    t, out, engine=(cfg.get("tts_engine") or "auto"),
                    voice=cfg.get("tts_voice", "km-KH-SreymomNeural"),
                    rate=rate_pct, pitch=(f"{pitch_hz:+d}Hz" if pitch_hz else "+0Hz"),
                    ffmpeg=ff, log=lambda m: print("        " + m, flush=True))
            r = NAR.render_styled(
                text, str(part), style, _one, ffmpeg=ff,
                pause=float(cfg.get("narration_pause", 0.3)), sr=24000,
                engine_name=(cfg.get("tts_engine") or "auto"),
                log=lambda m: print("      " + m, flush=True))
            if r.get("ok"):
                _ENGINE_USED["engine"] = r.get("engine", "")
                _ENGINE_USED["style"] = (f"{NAR.spec(style)['label']} | "
                                         f"{r['rendered']}/{r['sentences']} sentences | "
                                         f"intensity {r['intensity'][0]}-{r['intensity'][1]}"
                                         + (f" | {r['breaths']} breath(s)" if r["breaths"] else ""))
                os.replace(part, target)
                print(f"      style '{NAR.spec(style)['label']}': {r['rendered']}/{r['sentences']} "
                      f"sentences, {r['seconds']}s", flush=True)
                return target
            print(f"      [style] styled read failed ({str(r.get('error'))[:70]}) — "
                  f"using a plain read for this chunk", flush=True)

    if KT is not None:
        r = KT.synth(
            text, str(part),
            engine=(cfg.get("tts_engine") or "auto"),
            voice=cfg.get("tts_voice", "km-KH-SreymomNeural"),
            rate=cfg.get("tts_rate", "+0%"),
            ffmpeg=C.find_ffmpeg(cfg) or "ffmpeg",
            log=lambda m: print("      " + m, flush=True))
        if not r.get("ok"):
            raise RuntimeError(r.get("error") or "all TTS engines failed")
        _ENGINE_USED["engine"], _ENGINE_USED["voice"] = r["engine"], r.get("voice", "")
        os.replace(part, target)
        return target
    # last-ditch: plain edge-tts (module missing, should not happen)
    import asyncio
    import edge_tts

    async def go():
        comm = edge_tts.Communicate(text, cfg.get("tts_voice", "km-KH-SreymomNeural"),
                                    rate=cfg.get("tts_rate", "+0%"))
        await comm.save(str(part) + ".mp3")
    asyncio.run(go())
    C.mp3_to_wav(cfg, str(part) + ".mp3", str(part))
    os.replace(part, target)
    return target


def main():
    cfg = C.load_config()
    log = C.load_log()
    chunks = sorted(log["chunks"].keys())
    if not chunks:
        print("[MISSING] no chunks in processing_log.json — run 01_normalize_khmer.py first")
        sys.exit(1)

    if KT is not None:
        usable = KT.available_engines()
        if not usable:
            print("[MISSING] no Khmer TTS engine is installed. Fix with:")
            print("          pip install edge-tts         (internet, best free)")
            print("          pip install gTTS             (internet, emergency)")
            print("          pip install transformers torch  (offline fallback)")
            sys.exit(1)
        print("Khmer TTS engines available: " + " -> ".join(usable))
    else:
        try:
            import edge_tts  # noqa: F401
        except Exception:
            print("[MISSING] edge-tts — run:  pip install -r requirements_system.txt")
            sys.exit(1)
    ff = C.find_ffmpeg(cfg)
    if not ff:
        print("[MISSING] ffmpeg (pip install imageio-ffmpeg) — needed for MP3->WAV")
        sys.exit(1)

    retries = int(cfg.get("retries", 2))
    done = skipped = failed = 0
    failures = []
    t0 = time.time()

    for i, cid in enumerate(chunks, 1):
        text_path = C.chunk_text_path(
            int(cid.split("/")[0].split("_")[1]),
            int(cid.split("/")[1].split("_")[1]))
        target = C.tts_path(cid)
        if not text_path.exists():
            failed += 1
            failures.append((cid, "tts", "chunk text file missing"))
            C.set_stage(log, cid, "tts", "failed", error="chunk text missing")
            continue

        # skip valid existing output (never overwrite success)
        if target.exists():
            ok, info, probs = C.validate_wav(target)
            if ok:
                skipped += 1
                C.set_stage(log, cid, "tts", "success")
                print(f"[{i}/{len(chunks)}] {cid}  SKIP (valid, {info['duration']}s)")
                C.save_log(log)
                continue
            print(f"[{i}/{len(chunks)}] {cid}  existing file INVALID ({probs}) — regenerating")

        text = text_path.read_text(encoding="utf-8").strip()
        text = C.normalize_khmer(text)[0]  # idempotent safety pass

        def attempt():
            out = C.ROOT / "tts" / (cid + ".part")
            C.atomic_audio(str(out), lambda t: make_wav(cfg, text, t))
            ok, info, probs = C.validate_wav(str(out))
            if not ok:
                out.unlink(missing_ok=True)
                raise RuntimeError("validation: " + "; ".join(probs))
            out.rename(target)
            return info

        res, attempts, err = C.retry_call(attempt, retries, 3.0, cid)
        if res is not None:
            done += 1
            extra = {"attempts": attempts}
            if _ENGINE_USED["engine"]:
                extra["engine"] = _ENGINE_USED["engine"]
                extra["voice"] = _ENGINE_USED["voice"]
            if _ENGINE_USED["style"]:
                extra["style"] = _ENGINE_USED["style"]
            C.set_stage(log, cid, "tts", "success", extra=extra)
            eng = f" [{_ENGINE_USED['engine']}]" if _ENGINE_USED["engine"] else ""
            print(f"[{i}/{len(chunks)}] {cid}  OK  {res['duration']}s{eng} "
                  f"({'retried' if attempts > 1 else ''})")
        else:
            failed += 1
            msg = str(err)[:200]
            failures.append((cid, "tts", msg))
            C.set_stage(log, cid, "tts", "failed", error=msg)
            print(f"[{i}/{len(chunks)}] {cid}  FAILED after {attempts} attempts: {msg}")
        C.save_log(log)

    C.save_log(log)
    print()
    print(f"TTS STAGE: {done} made, {skipped} skipped, {failed} failed "
          f"({time.time() - t0:.0f}s)")
    if failures:
        print("\nFAILED CHUNKS:")
        for cid, stage, err in failures:
            print(f"  {cid}  [{stage}]  {err}")
        print("\nFix the cause (network? voice name?) and re-run this stage — "
              "successful chunks are not touched.")
        sys.exit(1)
    print("STAGE 2 COMPLETE (TTS)")


if __name__ == "__main__":
    main()
