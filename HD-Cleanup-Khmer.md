# HD / Clean Khmer Voice — what it is, and the evidence for it

**Feature name:** HD / Clean Khmer Voice · **engine:** Adaptive Khmer Voice Enhancement (`sonora/hdclean.py`, `pipeline/hdclean.py`)

**Where it lives:** inside the **RVC VOICE CLONE** path only — the switch drops in as a row to the right of `RVC VOICE CLONE` when the clone is ticked. **Khmer only.**

## What the user gets

One switch, one operation: TTS → analysis → adaptive enhancement → quality check → loudness → true-peak protection → HD output. There are no EQ, compressor or denoiser controls to set, because the engine decides per file — and it decides to do *less* when less is needed. The original TTS is never overwritten: it is kept as `<key>.original.wav` next to `enhanced_hd.wav`, and the episode then exports the HD one. When the pass finishes, a 5–10 second **Original ▶ / HD Clean ▶** pair appears next to the result, so the change can be heard before anything is exported.

## The stages, and when each one switches on

| # | stage | switches on when | it never does this |
|---|-------|------------------|--------------------|
| 1 | noise reduction (spectral, gentle) | the floor is within 42 dB of the voice | gate away consonants or breath; go metallic |
| 2 | de-reverb (downward expansion in the pauses) | the pauses still ring (measured tail > 0.025) | touch the words — the speech level is bit-for-bit untouched |
| 3 | rumble filter 70–90 Hz, 12 dB/oct | a steady low-frequency bed is still there **in the pauses** (> 0.02 of the voice's body; healthy voices ≤ 0.006, a hiss floor 0.010–0.016, a 45 Hz hum 0.20) | cut into the voice's own fundamental |
| 4 | small low-mid cut @250 Hz | low-mid weight > 7.0 (studio voices 2.8–4.1) | hollow the chest of the voice |
| 5 | presence +0.4–1.6 dB @3.3 kHz | clarity < 0.008 — below every healthy voice (studio 0.025–0.079, Khmer TTS 0.012–0.041) | brighten an already clear voice |
| 6 | sibilance control −0.8–3 dB @7.2 kHz | top end brighter than **all** of the studio's own voices | “fix” a bright voice that is simply bright |
| 7 | gentle compression 2:1–3:1, threshold 4 dB under the voice's own level | the voice's phrases wander more than 10 dB against each other (healthy files measure 4–9.3 dB: the 15 Khmer samples and the studio's 13 voices) | flatten an expressive read — within phrase, the movement is the performance and is left alone |
| 8 | loudness + true peak | always (the delivery standard, not an effect) | maximise — it measures **LUFS**, then limits to ≈ −1 dBTP |
| 9 | **damaged input guard** — not a stage, a veto | the file arrives already clipped: > 0.02 % of samples pinned flat, or a crest factor under 13.5 dB (clean Khmer samples 15.0–16.1, the studio's 13 voices 16.4–17.6; a ×2.0 gain 12.5, ×3.2 9.5, a tanh overload 9.6) | boost presence, compress, or push the ceiling back up. The stage list is cut to the safe ones, the true-peak target drops to **−1.5 dBTP**, and the score keeps a penalty of `min(12, (13.5 − crest) × 3)` — the file is delivered quieter, not louder; nothing can be un-clipped |

Every threshold above was calibrated on controlled fixtures *and* against the studio's own 13 narration voices; `pipeline/test_hdclean.py` asserts each one (139 checks — including the one that cannot be heard but can be measured: the pass must not move the audio in time; an uncompensated look-ahead limiter was adding 5 ms and was found and fixed this way), and `pipeline/test_hd_server.py` asserts the wiring (§2, §16, §17, §19, §24 — 14 checks). `pipeline/check_hd_ui.py` checks the switch and its four-case demo panel in a real browser (42 checks).

## §28 — the Khmer samples

Generated with the two Khmer voices the studio uses (`km-KH-SreymomNeural`, `km-KH-PisethNeural`) and processed one at a time, each from its own original. Every clip's **Original** and **HD** are side by side in `sonora/public/hd_samples/` as `<n>-<case>.original.mp3` and `.hd.mp3` (192 kbps renderings of the 48 kHz / 24-bit masters, for listening), plus the 8 s interface preview pair each run writes.

| # | case | voice | score | stages applied | F0 before → after | spectrum Δ max | LUFS | true peak |
|---|------|-------|-------|----------------|-------------------|----------------|------|-----------|
| 1 | normal | SreymomNeural @ +0% | 99 → 100 | low-mid -0.4 dB @250 Hz | 226.4 → 226.4 Hz | 0.22 dB | -20.7 → -15.98 | -6.7 → -1.9 |
| 2 | one long sentence | SreymomNeural @ +0% | 100 → 100 | — nothing needed — | 228.6 → 228.6 Hz | 0.07 dB | -21.32 → -16.24 | -6.2 → -1.2 |
| 3 | short sentences | SreymomNeural @ +0% | 98 → 98 | presence +0.4 dB @3.3 kHz | 250.0 → 250.0 Hz | 0.40 dB | -20.07 → -15.99 | -5.7 → -1.6 |
| 4 | fast delivery | SreymomNeural @ +25% | 100 → 100 | — nothing needed — | 226.4 → 226.4 Hz | 0.00 dB | -21.77 → -16.0 | -6.8 → -1.0 |
| 5 | slow delivery | SreymomNeural @ -25% | 100 → 100 | — nothing needed — | 230.2 → 229.7 Hz | 0.29 dB | -21.42 → -16.44 | -5.5 → -1.0 |
| 6 | emotional | SreymomNeural @ -10% | 100 → 99 | — nothing needed — | 230.8 → 231.9 Hz | 0.11 dB | -21.81 → -16.21 | -6.7 → -1.0 |
| 7 | calm / soft | SreymomNeural @ -15% | 100 → 100 | — nothing needed — | 224.3 → 224.3 Hz | 0.05 dB | -20.71 → -16.0 | -5.6 → -1.0 |
| 8 | numbers and digits | SreymomNeural @ +0% | 100 → 100 | — nothing needed — | 222.2 → 222.2 Hz | 0.25 dB | -20.63 → -16.38 | -4.4 → -1.0 |
| 9 | Khmer names | PisethNeural @ +0% | 97 → 98 | low-mid -0.6 dB @250 Hz | 131.5 → 131.5 Hz | 0.48 dB | -22.79 → -16.36 | -6.5 → -1.0 |
| 10 | questions / exclamations / dots | PisethNeural @ +0% | 100 → 100 | — nothing needed — | 137.1 → 136.9 Hz | 0.25 dB | -22.18 → -16.02 | -6.2 → -1.0 |
| 11 | pauses between phrases | PisethNeural @ -5% | 100 → 100 | — nothing needed — | 145.9 → 145.9 Hz | 0.58 dB | -22.27 → -16.41 | -5.6 → -1.0 |
| 12 | storytelling register | PisethNeural @ -5% | 100 → 100 | — nothing needed — | 139.5 → 139.5 Hz | 0.50 dB | -22.98 → -16.06 | -5.7 → -1.0 |
| 13 | news / formal | PisethNeural @ +10% | 100 → 100 | — nothing needed — | 138.3 → 138.3 Hz | 0.29 dB | -23.1 → -16.35 | -6.3 → -1.0 |
| 14 | explainer / instructional | PisethNeural @ +0% | 100 → 100 | — nothing needed — | 135.2 → 135.2 Hz | 0.20 dB | -21.97 → -16.54 | -4.7 → -1.0 |
| 15 | a quiet, breathy moment | PisethNeural @ -20% | 90 → 90 | low-mid -1.3 dB @250 Hz | 159.5 → 159.5 Hz | 0.63 dB | -20.86 → -16.0 | -6.6 → -1.1 |

11 of the 15 samples needed **no correction at all** — the plan came back empty and only the delivery standard ran (measure the loudness, then limit to −1 dBTP); every other one asked for a single small move, between low-mid -0.4 dB and presence +0.4 dB. That is §3 working: high-quality input, very light processing. The two voices sit at different levels to start with, so the loudness stage does real work here: a sample measured -20.7 LUFS and -6.7 dBTP before, -15.98 LUFS and -1.9 dBTP after.

### Does it still sound like the same person?

The engine contains no pitch shift, no formant change, no re-tuning and no time stretch — so the honest test is whether the measurements agree:

- **Pitch:** the largest measured F0 movement is **0.48 %** on the clean samples and **0.97 %** across everything including the deliberately damaged ones (F0 is estimated by autocorrelation over the loudest 30 % of frames — a whisper is a voice, a hiss floor is not; the engine contains no stage that could move pitch).
- **Voice colour:** the whole-file spectrum (24 log bands, 100 Hz–10 kHz, each side normalised by its own body level) moves by at most **0.63 dB** on the clean samples, and the largest moves are exactly the bands a planned stage was aimed at. Bands holding no energy at all are excluded: comparing two −188 dB bands measures nothing but rounding.
- **Timing:** every output has the same length as its input (all 20 samples), so no word is stretched, shortened or dropped.
- **Meaning:** pronunciation, Khmer accent, emotion, style and pauses are produced by the TTS layer and are not touched by this engine; the HD pass only moves noise, rumble, room, mud, harshness, dynamics and loudness.

## When there IS something to fix — the degradation series

Some samples were also degraded deliberately (a hiss floor, a 45 Hz hum, a 300 ms room) and run through the same switch:

| sample | injected | score | stages | SNR before → after | rumble before → after | reverb before → after | F0 Δ |
|--------|----------|-------|--------|--------------------|-----------------------|----------------------|-------|
| 01-normal | hiss | 77 → 79 | noise reduction; low-mid -0.4 dB @250 Hz | 15 → 22 dB | 0.012 → 0.005 | — → 0.077 | 0.5 % |
| 01-normal | hum | 91 → 98 | rumble filter 70 Hz; low-mid -0.4 dB @250 Hz | 60 → 74 dB | 0.21 → 0.031 | — → 0.031 | 0.0 % |
| 01-normal | room | 94 → 100 | de-reverb; low-mid -0.3 dB @250 Hz | 98 → 102 dB | 0.001 → 0.0 | 0.042 → 0.014 | 0.4 % |
| 04-fast | hiss | 78 → 79 | noise reduction | 14 → 21 dB | 0.013 → 0.006 | — → 0.078 | 1.0 % |
| 11-pauses | room | 93 → 100 | de-reverb | 98 → 104 dB | 0.0 → 0.0 | 0.049 → 0.025 | 0.0 % |

A hiss floor is the one case where the spectrum does move (Δ max 6.21 dB): that is noise reduction doing its job, and it is the only stage allowed to change the spectrum that much — the voice itself is what is left when the floor is gone.

## Calibrations this matrix corrected

The samples were also a test of the engine's own judgement, and they caught mistakes that fixtures built from an English narrator could not:

- **Rumble was being measured in the wrong place.** The first definition compared 20–80 Hz with the voice's body level *while the voice was speaking*, and read 0.05–0.37 on clean Khmer output — the male voice's own low end was being counted as a defect, and the filter fired on almost every sample. Rumble is now measured **while nobody is speaking**: a hum is still there in the pauses, a voice is not. Clean voices read ≤ 0.006, a hiss floor 0.010–0.016, a 45 Hz hum 0.20 — and the number is the same at 24 kHz and 48 kHz.
- **A single highpass is a tilt, not a rumble cut.** Measured, ffmpeg's `highpass` is 6 dB/octave: at `f=70` it takes only 8.4 dB out of a 45 Hz hum. The stage is now two cascaded highpasses (12 dB/oct) — 16.7 dB at 45 Hz, and just 1.9 dB at 100 Hz, so the voice above the corner is barely touched. The same measurements moved the low-mid line above every healthy voice's own low-mid weight (studio 2.8–4.1) and the clarity line below every healthy voice's presence reading.
- **The pass adds no delay.** ffmpeg's `alimiter` looks ahead and does not compensate by default: the first master chain wrote every HD file 240 samples (5 ms) late. Nothing audible, but it is a real defect — the original and the HD file would no longer line up — so the limiter now runs with `latency=1` (measured lag: 0) and a regression check asserts it.
- **Compression was wired to the wrong thing.** The stage hung off the overall quality score, so a clean voice whose level drifted was left alone while a *noisy* one got squeezed — and it never could fire as §12 intends, because levels are not part of the score. Its threshold was also a fixed −18 dB, which made the effect depend on how hot the file happened to be: measured, a ±10 dB fixture lost 3.4 dB of its wander at one input level and nothing at all 8 dB quieter. A voice's phrase levels are now measured directly (p90−p10 across phrases, pauses excluded), the stage is gated on that reading, and the threshold is placed 4 dB under the measured speech level — so the gain reduction §12 asks for is a property of the passage, not of the delivery level.
- **The measurement itself was wrong twice.** The spectrum metric used to select “the loudest frames” per file. On a whisper the loudest frames are breaths, whose top end differs between two files even when nothing has been touched, and a frame set chosen per file is not a comparison at all; a louder file also crosses any absolute floor more often. It reported a 13.5 dB high-frequency boost on a sample the whole-file spectrum shows is unchanged apart from its planned −1.3 dB at 250 Hz. It is now one whole-file comparison, normalised per side, and the number it reports matches what the audio actually is.

- **Clipping was measured with the wrong test — three times.** `|x| > 0.999` misses any file that was normalised *after* it clipped; “within 0.5 % of the peak” false-fires on smooth low-frequency peaks (a muffled fixture read 0.084 % with nothing clipped at all); what is actually clipping is a **pinned run** — three or more samples in a row flat to within 1e-4 at ≥ 0.90 of full scale. That detector is what ships. Even then, a 24 kHz → 48 kHz resample smooths the pins away, so a file that is hard-limited rather than clipped is caught by the other half of §18: **crest factor** (peak minus speech level), which no amount of resampling can restore.
- **The damage reading now changes the plan, not just the log.** §5 clipping and §18 distortion were being measured and then ignored: a clipped file was still getting its presence boost and its compressor, i.e. the pipeline made the loudest thing louder. Damaged input now vetoes both stages and lowers the ceiling to −1.5 dBTP (§26 failure-averse), and the score carries the penalty — so “what the engine says” and “what the engine does” are the same list.

## What it deliberately does not do

- **It does not upsample to “restore” detail.** The output is a 48 kHz / 24-bit WAV; a 48 kHz source is not resampled at all (verified bit-exact), and a 24 kHz source gets one soxr conversion in the decoder — a format change, never claimed as added resolution.
- **It does not chain.** Every pass starts from the original; running it twice on the same file produces the same output (asserted).
- **It does not hide a failure.** If anything goes wrong the original is what stays, with the log line *“Enhancement unavailable; original TTS preserved.”*
- **It does not judge “harshness” by taste.** The 5–9 kHz control only engages above the brightness of every one of the studio's own 13 voices (0.28–0.98 on the calibrated ratio; the line is 1.20). A voice that is simply bright is left alone — and that is deliberate: without a reference for the speaker, a stricter rule would have “corrected” healthy voices (a per-file burst test was built, measured, and rejected for exactly that reason).

## Reproducing all of this

```bash
python3 pipeline/test_hdclean.py                   # 139 checks — the engine
python3 pipeline/test_hd_server.py                 # 14 checks — the wiring
python3 pipeline/check_hd_ui.py                    # 42 checks — the switch + the demo panel
python3 pipeline/make_hd_samples.py --offline      # rebuild this matrix (~20 s)
python3 pipeline/make_hd_report.py                 # regenerate this document
```

Raw numbers: `sonora/public/hd_samples/samples.json` — every score, stage, level, pitch, spectrum and length figure quoted above, for the 15 samples and the 5 degraded cases.
