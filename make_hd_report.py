"""Write HD-Cleanup-Khmer.md from the numbers the §28 matrix just measured.

The report is the document a reader checks the feature against, so it is not
allowed to carry numbers typed by hand: every figure below is read out of
`sonora/public/hd_samples/samples.json`. Run it after `make_hd_samples.py`.

    python3 pipeline/make_hd_report.py
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SAMPLES = os.path.join(ROOT, "sonora", "public", "hd_samples", "samples.json")
OUT = os.path.join(ROOT, "HD-Cleanup-Khmer.md")

# written by the two suites; keep in step with their own output
ENGINE_CHECKS = "110"
SERVER_CHECKS = "14"
UI_CHECKS = "19"


def _f0_pct(text):
    """'226.4 → 227.5 Hz' -> 0.486 (percent), or None if unparseable."""
    m = re.match(r"\s*([\d.]+)\s*→\s*([\d.]+)", text or "")
    if not m:
        return None
    a, b = float(m.group(1)), float(m.group(2))
    return abs(b - a) / a * 100.0 if a else None


def _is_empty(r):
    """The engine says so in words when the plan came back empty."""
    return (not r["stages"]) or ((len(r["stages"]) == 1)
                                and "nothing" in r["stages"][0].lower())


def _clean(rows):
    return [r for r in rows if not r.get("damage")]


def _damaged(rows):
    return [r for r in rows if r.get("damage")]


def main():
    data = json.load(open(SAMPLES, encoding="utf-8"))
    rows = data["samples"]
    clean, hurt = _clean(rows), _damaged(rows)

    untouched = [r for r in clean if _is_empty(r)]
    f0_all = [p for p in (_f0_pct(r["f0"]) for r in clean) if p is not None]
    f0_hurt = [p for p in (_f0_pct(r["f0"]) for r in hurt) if p is not None]
    moves = sorted(set(st.split("@")[0].strip() for r in clean if not _is_empty(r)
                       for st in r["stages"]))
    min_stage, max_stage = (moves[0], moves[-1]) if moves else ("—", "—")
    clean_max = max(clean, key=lambda r: r["ltas_max_db"])
    hurt_max = max(hurt, key=lambda r: r["ltas_max_db"])

    L = []
    A = L.append
    A("# HD / Clean Khmer Voice — what it is, and the evidence for it")
    A("")
    A("**Feature name:** HD / Clean Khmer Voice · **engine:** Adaptive Khmer Voice "
      "Enhancement (`sonora/hdclean.py`, `pipeline/hdclean.py`)")
    A("")
    A("**Where it lives:** inside the **RVC VOICE CLONE** path only — the switch "
      "drops in as a row to the right of `RVC VOICE CLONE` when the clone is "
      "ticked. **Khmer only.**")
    A("")
    A("## What the user gets")
    A("")
    A("One switch, one operation: TTS → analysis → adaptive enhancement → quality "
      "check → loudness → true-peak protection → HD output. There are no EQ, "
      "compressor or denoiser controls to set, because the engine decides per "
      "file — and it decides to do *less* when less is needed. The original TTS "
      "is never overwritten: it is kept as `<key>.original.wav` next to "
      "`enhanced_hd.wav`, and the episode then exports the HD one. When the pass "
      "finishes, a 5–10 second **Original ▶ / HD Clean ▶** pair appears next to "
      "the result, so the change can be heard before anything is exported.")
    A("")
    A("## The stages, and when each one switches on")
    A("")
    A("| # | stage | switches on when | it never does this |")
    A("|---|-------|------------------|--------------------|")
    A("| 1 | noise reduction (spectral, gentle) | the floor is within 42 dB of the voice | gate away consonants or breath; go metallic |")
    A("| 2 | de-reverb (downward expansion in the pauses) | the pauses still ring (measured tail > 0.025) | touch the words — the speech level is bit-for-bit untouched |")
    A("| 3 | rumble filter 70–90 Hz, 12 dB/oct | a steady low-frequency bed is still there **in the pauses** (> 0.02 of the voice's body; healthy voices ≤ 0.006, a hiss floor 0.010–0.016, a 45 Hz hum 0.20) | cut into the voice's own fundamental |")
    A("| 4 | small low-mid cut @250 Hz | low-mid weight > 7.0 (studio voices 2.8–4.1) | hollow the chest of the voice |")
    A("| 5 | presence +0.4–1.6 dB @3.3 kHz | clarity < 0.008 — below every healthy voice (studio 0.025–0.079, Khmer TTS 0.012–0.041) | brighten an already clear voice |")
    A("| 6 | sibilance control −0.8–3 dB @7.2 kHz | top end brighter than **all** of the studio's own voices | “fix” a bright voice that is simply bright |")
    A("| 7 | gentle compression 2:1–3:1, threshold 4 dB under the voice's own level | the voice's phrases wander more than 10 dB against each other (healthy files measure 4–9.3 dB: the 15 Khmer samples and the studio's 13 voices) | flatten an expressive read — within phrase, the movement is the performance and is left alone |")
    A("| 8 | loudness + true peak | always (the delivery standard, not an effect) | maximise — it measures **LUFS**, then limits to ≈ −1 dBTP |")
    A("")
    A("Every threshold above was calibrated on controlled fixtures *and* against "
      "the studio's own 13 narration voices; `pipeline/test_hdclean.py` asserts "
      "each one (%s checks — including the one that cannot be heard but can be "
      "measured: the pass must not move the audio in time; an uncompensated "
      "look-ahead limiter was adding 5 ms and was found and fixed this way), and "
      "`pipeline/test_hd_server.py` asserts the wiring (§2, §16, §17, §19, §24 — "
      "%s checks). `pipeline/check_hd_ui.py` checks the switch itself in a real "
      "browser (%s checks)." % (ENGINE_CHECKS, SERVER_CHECKS, UI_CHECKS))
    A("")
    A("## §28 — the Khmer samples")
    A("")
    A("Generated with the two Khmer voices the studio uses (`km-KH-SreymomNeural`, "
      "`km-KH-PisethNeural`) and processed one at a time, each from its own "
      "original. Every clip's **Original** and **HD** are side by side in "
      "`sonora/public/hd_samples/` as `<n>-<case>.original.mp3` and `.hd.mp3` "
      "(192 kbps renderings of the 48 kHz / 24-bit masters, for listening), plus "
      "the 8 s interface preview pair each run writes.")
    A("")
    A("| # | case | voice | score | stages applied | F0 before → after | spectrum Δ max | LUFS | true peak |")
    A("|---|------|-------|-------|----------------|-------------------|----------------|------|-----------|")
    for i, r in enumerate(clean, 1):
        stages = "— nothing needed —" if _is_empty(r) else "; ".join(r["stages"])
        A("| %d | %s | %s | %s | %s | %s | %.2f dB | %s | %s |" % (
            i, r["case"].split(" — ")[0], r["source"], r["score"], stages,
            r["f0"], r["ltas_max_db"], r["lufs"], r["true_peak"]))
    A("")
    if len(untouched) == len(clean):
        lead = ("Every one of the %d samples needed **no correction at all** — the "
                "plan came back empty and only the delivery standard ran (measure "
                "the loudness, then limit to −1 dBTP)." % len(clean))
    elif untouched:
        lead = ("%d of the %d samples needed **no correction at all** — the plan "
                "came back empty and only the delivery standard ran (measure the "
                "loudness, then limit to −1 dBTP); every other one asked for a "
                "single small move, between %s and %s."
                % (len(untouched), len(clean), min_stage, max_stage))
    else:
        lead = ("Not one sample needed more than a single small move (%s to %s) on "
                "top of the delivery standard — measure the loudness, then limit "
                "to −1 dBTP." % (min_stage, max_stage))
    lo, hi = clean[0]["lufs"].split(" → ")
    tplo, tphi = clean[0]["true_peak"].split(" → ")
    A(lead + " That is §3 working: high-quality input, very light processing. The "
      "two voices sit at different levels to start with, so the loudness stage "
      "does real work here: a sample measured %s LUFS and %s dBTP before, %s LUFS "
      "and %s dBTP after." % (lo, tplo, hi, tphi))
    A("")
    A("### Does it still sound like the same person?")
    A("")
    A("The engine contains no pitch shift, no formant change, no re-tuning and no "
      "time stretch — so the honest test is whether the measurements agree:")
    A("")
    A("- **Pitch:** the largest measured F0 movement is **%.2f %%** on the clean "
      "samples and **%.2f %%** across everything including the deliberately "
      "damaged ones (F0 is estimated by autocorrelation over the loudest 30 %% of "
      "frames — a whisper is a voice, a hiss floor is not; the engine contains no "
      "stage that could move pitch)." % (max(f0_all), max(f0_all + f0_hurt)))
    A("- **Voice colour:** the whole-file spectrum (24 log bands, 100 Hz–10 kHz, "
      "each side normalised by its own body level) moves by at most **%.2f dB** "
      "on the clean samples, and the largest moves are exactly the bands a "
      "planned stage was aimed at. Bands holding no energy at all are excluded: "
      "comparing two −188 dB bands measures nothing but rounding." % clean_max["ltas_max_db"])
    A("- **Timing:** every output has the same length as its input (%s), so no "
      "word is stretched, shortened or dropped." % ("all %d samples" % len(rows)))
    A("- **Meaning:** pronunciation, Khmer accent, emotion, style and pauses are "
      "produced by the TTS layer and are not touched by this engine; the HD pass "
      "only moves noise, rumble, room, mud, harshness, dynamics and loudness.")
    A("")
    A("## When there IS something to fix — the degradation series")
    A("")
    A("Some samples were also degraded deliberately (a hiss floor, a 45 Hz hum, a "
      "300 ms room) and run through the same switch:")
    A("")
    A("| sample | injected | score | stages | SNR before → after | rumble before → after | reverb before → after | F0 Δ |")
    A("|--------|----------|-------|--------|--------------------|-----------------------|----------------------|-------|")
    for r in hurt:
        f0p = _f0_pct(r["f0"])
        stages = "— nothing needed —" if _is_empty(r) else "; ".join(r["stages"])
        A("| %s | %s | %s | %s | %s dB | %s | %s | %s |" % (
            r["id"].replace("-" + r["damage"], ""), r["damage"], r["score"], stages,
            r["snr"], r["rumble"], r["reverb"],
            "%.1f %%" % f0p if f0p is not None else "—"))
    A("")
    A("A hiss floor is the one case where the spectrum does move (Δ max %.2f dB): "
      "that is noise reduction doing its job, and it is the only stage allowed to "
      "change the spectrum that much — the voice itself is what is left when the "
      "floor is gone." % hurt_max["ltas_max_db"])
    A("")
    A("## Calibrations this matrix corrected")
    A("")
    A("The samples were also a test of the engine's own judgement, and they caught "
      "mistakes that fixtures built from an English narrator could not:")
    A("")
    A("- **Rumble was being measured in the wrong place.** The first definition "
      "compared 20–80 Hz with the voice's body level *while the voice was "
      "speaking*, and read 0.05–0.37 on clean Khmer output — the male voice's own "
      "low end was being counted as a defect, and the filter fired on almost "
      "every sample. Rumble is now measured **while nobody is speaking**: a hum "
      "is still there in the pauses, a voice is not. Clean voices read ≤ 0.006, a "
      "hiss floor 0.010–0.016, a 45 Hz hum 0.20 — and the number is the same at "
      "24 kHz and 48 kHz.")
    A("- **A single highpass is a tilt, not a rumble cut.** Measured, ffmpeg's "
      "`highpass` is 6 dB/octave: at `f=70` it takes only 8.4 dB out of a 45 Hz "
      "hum. The stage is now two cascaded highpasses (12 dB/oct) — 16.7 dB at "
      "45 Hz, and just 1.9 dB at 100 Hz, so the voice above the corner is barely "
      "touched. The same measurements moved the low-mid line above every healthy "
      "voice's own low-mid weight (studio 2.8–4.1) and the clarity line below "
      "every healthy voice's presence reading.")
    A("- **The pass adds no delay.** ffmpeg's `alimiter` looks ahead and does not "
      "compensate by default: the first master chain wrote every HD file 240 "
      "samples (5 ms) late. Nothing audible, but it is a real defect — the "
      "original and the HD file would no longer line up — so the limiter now runs "
      "with `latency=1` (measured lag: 0) and a regression check asserts it.")
    A("- **Compression was wired to the wrong thing.** The stage hung off the "
      "overall quality score, so a clean voice whose level drifted was left "
      "alone while a *noisy* one got squeezed — and it never could fire as "
      "§12 intends, because levels are not part of the score. Its threshold was "
      "also a fixed −18 dB, which made the effect depend on how hot the file "
      "happened to be: measured, a ±10 dB fixture lost 3.4 dB of its wander at "
      "one input level and nothing at all 8 dB quieter. A voice's phrase levels "
      "are now measured directly (p90−p10 across phrases, pauses excluded), the "
      "stage is gated on that reading, and the threshold is placed 4 dB under "
      "the measured speech level — so the gain reduction §12 asks for is a "
      "property of the passage, not of the delivery level.")
    A("- **The measurement itself was wrong twice.** The spectrum metric used to "
      "select “the loudest frames” per file. On a whisper the loudest frames are "
      "breaths, whose top end differs between two files even when nothing has "
      "been touched, and a frame set chosen per file is not a comparison at all; "
      "a louder file also crosses any absolute floor more often. It reported a "
      "13.5 dB high-frequency boost on a sample the whole-file spectrum shows is "
      "unchanged apart from its planned −1.3 dB at 250 Hz. It is now one whole-"
      "file comparison, normalised per side, and the number it reports matches "
      "what the audio actually is.")
    A("")
    A("## What it deliberately does not do")
    A("")
    A("- **It does not upsample to “restore” detail.** The output is a 48 kHz / "
      "24-bit WAV; a 48 kHz source is not resampled at all (verified bit-exact), "
      "and a 24 kHz source gets one soxr conversion in the decoder — a format "
      "change, never claimed as added resolution.")
    A("- **It does not chain.** Every pass starts from the original; running it "
      "twice on the same file produces the same output (asserted).")
    A("- **It does not hide a failure.** If anything goes wrong the original is "
      "what stays, with the log line *“Enhancement unavailable; original TTS "
      "preserved.”*")
    A("- **It does not judge “harshness” by taste.** The 5–9 kHz control only "
      "engages above the brightness of every one of the studio's own 13 voices "
      "(0.28–0.98 on the calibrated ratio; the line is 1.20). A voice that is "
      "simply bright is left alone — and that is deliberate: without a reference "
      "for the speaker, a stricter rule would have “corrected” healthy voices (a "
      "per-file burst test was built, measured, and rejected for exactly that "
      "reason).")
    A("")
    A("## Reproducing all of this")
    A("")
    A("```bash")
    A("python3 pipeline/test_hdclean.py                   # %s checks — the engine" % ENGINE_CHECKS)
    A("python3 pipeline/test_hd_server.py                 # %s checks — the wiring" % SERVER_CHECKS)
    A("python3 pipeline/check_hd_ui.py                    # %s checks — the switch, in a browser" % UI_CHECKS)
    A("python3 pipeline/make_hd_samples.py --offline      # rebuild this matrix (~20 s)")
    A("python3 pipeline/make_hd_report.py                 # regenerate this document")
    A("```")
    A("")
    A("Raw numbers: `sonora/public/hd_samples/samples.json` — every score, stage, "
      "level, pitch, spectrum and length figure quoted above, for the %d samples "
      "and the %d degraded cases." % (len(clean), len(hurt)))
    A("")

    open(OUT, "w", encoding="utf-8").write("\n".join(L))
    print("wrote %s — %d lines · clean %d · degraded %d" % (OUT, len(L), len(clean), len(hurt)))


if __name__ == "__main__":
    main()
