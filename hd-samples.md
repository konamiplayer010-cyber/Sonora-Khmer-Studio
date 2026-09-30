# HD / Clean Khmer Voice — the §28 sample matrix

Generated 2026-09-30 12:57 by `pipeline/make_hd_samples.py`. Every clip is in `sonora/public/hd_samples/` as `<n>-<case>.original.mp3` and `.hd.mp3` — the same take with and without the HD pass, nothing else changed. Scores are the engine's own 0–100 (§5); stages are what the adaptive plan actually switched on.

## §28 — the Khmer samples

| # | case | voice | score | stages applied | F0 before → after | spectrum Δ (max / rms) | length kept | LUFS | true peak |
|---|------|-------|-------|----------------|-------------------|------------------------|-------------|------|-----------|
| 01 | normal — balanced sentence | SreymomNeural @ +0% | 99 → 100 | low-mid -0.4 dB @250 Hz | 226.4 → 226.4 Hz | 0.22 / 0.14 dB | yes | -20.7 → -15.98 | -6.7 → -1.9 |
| 02 | one long sentence | SreymomNeural @ +0% | 100 → 100 | nothing needed | 228.6 → 228.6 Hz | 0.07 / 0.03 dB | yes | -21.32 → -16.24 | -6.2 → -1.2 |
| 03 | short sentences | SreymomNeural @ +0% | 98 → 98 | presence +0.4 dB @3.3 kHz | 250.0 → 250.0 Hz | 0.4 / 0.14 dB | yes | -20.07 → -15.99 | -5.7 → -1.6 |
| 04 | fast delivery | SreymomNeural @ +25% | 100 → 100 | nothing needed | 226.4 → 226.4 Hz | 0.0 / 0.0 dB | yes | -21.77 → -16.0 | -6.8 → -1.0 |
| 05 | slow delivery | SreymomNeural @ -25% | 100 → 100 | nothing needed | 230.2 → 229.7 Hz | 0.29 / 0.11 dB | yes | -21.42 → -16.44 | -5.5 → -1.0 |
| 06 | emotional | SreymomNeural @ -10% | 100 → 99 | nothing needed | 230.8 → 231.9 Hz | 0.11 / 0.05 dB | yes | -21.81 → -16.21 | -6.7 → -1.0 |
| 07 | calm / soft | SreymomNeural @ -15% | 100 → 100 | nothing needed | 224.3 → 224.3 Hz | 0.05 / 0.02 dB | yes | -20.71 → -16.0 | -5.6 → -1.0 |
| 08 | numbers and digits | SreymomNeural @ +0% | 100 → 100 | nothing needed | 222.2 → 222.2 Hz | 0.25 / 0.13 dB | yes | -20.63 → -16.38 | -4.4 → -1.0 |
| 09 | Khmer names | PisethNeural @ +0% | 97 → 98 | low-mid -0.6 dB @250 Hz | 131.5 → 131.5 Hz | 0.48 / 0.31 dB | yes | -22.79 → -16.36 | -6.5 → -1.0 |
| 10 | questions / exclamations / dots | PisethNeural @ +0% | 100 → 100 | nothing needed | 137.1 → 136.9 Hz | 0.25 / 0.15 dB | yes | -22.18 → -16.02 | -6.2 → -1.0 |
| 11 | pauses between phrases | PisethNeural @ -5% | 100 → 100 | nothing needed | 145.9 → 145.9 Hz | 0.58 / 0.3 dB | yes | -22.27 → -16.41 | -5.6 → -1.0 |
| 12 | storytelling register | PisethNeural @ -5% | 100 → 100 | nothing needed | 139.5 → 139.5 Hz | 0.5 / 0.23 dB | yes | -22.98 → -16.06 | -5.7 → -1.0 |
| 13 | news / formal | PisethNeural @ +10% | 100 → 100 | nothing needed | 138.3 → 138.3 Hz | 0.29 / 0.11 dB | yes | -23.1 → -16.35 | -6.3 → -1.0 |
| 14 | explainer / instructional | PisethNeural @ +0% | 100 → 100 | nothing needed | 135.2 → 135.2 Hz | 0.2 / 0.09 dB | yes | -21.97 → -16.54 | -4.7 → -1.0 |
| 15 | a quiet, breathy moment | PisethNeural @ -20% | 90 → 90 | low-mid -1.3 dB @250 Hz | 159.5 → 159.5 Hz | 0.63 / 0.5 dB | yes | -20.86 → -16.0 | -6.6 → -1.1 |

**Identity, measured:** pitch and spectral shape are the two things a "does it still sound like the same person" test can actually put a number on, and the engine contains no stage that could move either — so these are checks, not claims. Across the 15 clean samples the largest F0 movement is 0.48 %, and the whole-file spectrum (24 log bands, 100 Hz–10 kHz, each side normalised by its own body level) moves at most 0.63 dB, with a 0.50 dB rms deviation — and the largest moves are exactly the bands a planned stage was aimed at. Every output is sample-for-sample the same length as its input, and the same audio in the same place: the pass adds no delay (measured by cross-correlation, not assumed — an uncompensated look-ahead limiter was found this way and fixed).

**What the pass did:** 11 of the 15 clean samples came back with an EMPTY plan — nothing to correct, so only the delivery standard ran (measure the loudness, normalise to −16 LUFS, limit the true peak to ≈ −1 dBTP). That is §3 working: high-quality input gets very light processing, and the tool does less when less is needed.

## The same samples, with a defect injected

Hiss (a real noise floor), a 45 Hz hum (a real mains artifact) and a small room (a real early-reflection tail) were added to four of the samples and the same switch was run again — this is the side where the tool has something to do.

| # | case | score | stages applied | SNR dB | noise floor dB | sibilance | rumble | clarity | reverb | F0 | spectrum Δ max | length kept |
|---|------|-------|----------------|--------|----------------|-----------|--------|---------|--------|----|----------------|-------------|
| 01 | hiss | 77 → 79 | noise reduction; low-mid -0.4 dB @250 Hz | 15 → 22 | -34 → -36 | 0.31 → 0.11 | 0.012 → 0.005 | 0.0403 → 0.026 | — → 0.077 | 226.4 → 227.5 Hz | 6.16 dB | yes |
| 01 | hum | 91 → 98 | rumble filter 70 Hz; low-mid -0.4 dB @250 Hz | 60 → 74 | -33 → -45 | 0.02 → 0.02 | 0.21 → 0.031 | 0.0311 → 0.0317 | — → 0.031 | 226.4 → 226.4 Hz | 1.25 dB | yes |
| 01 | room | 94 → 100 | de-reverb; low-mid -0.3 dB @250 Hz | 98 → 102 | -124 → -128 | 0.02 → 0.02 | 0.001 → 0.0 | 0.0321 → 0.0316 | 0.042 → 0.014 | 226.4 → 225.4 Hz | 2.52 dB | yes |
| 04 | hiss | 78 → 79 | noise reduction | 14 → 21 | -34 → -35 | 0.45 → 0.2 | 0.013 → 0.006 | 0.0224 → 0.0123 | — → 0.078 | 226.4 → 228.6 Hz | 6.21 dB | yes |
| 06 | clip | 85 → 99 | clipping / hard limiting found (0.26% of samples pinned at the ceiling, crest 12.7 dB) — no boost, extra headroom; low-mid -0.4 dB @250 Hz | 107 → 103 | -140 → -142 | 0.02 → 0.02 | 0.0 → 0.0 | 0.0271 → 0.0277 | 0.009 → 0.009 | 230.8 → 230.8 Hz | 0.24 dB | yes |
| 11 | room | 93 → 100 | de-reverb | 98 → 104 | -159 → -161 | 0.02 → 0.02 | 0.0 → 0.0 | 0.0122 → 0.0117 | 0.049 → 0.025 | 147.2 → 147.2 Hz | 2.16 dB | yes |

Notes on reading the table:

- **SNR / noise floor go UP where a defect was removed** (hiss) and **down where the room was** — a room adds energy in the pauses, so removing it lowers the measured "floor". Both are the metric doing its job, in opposite directions.
- **rumble** is measured in the pauses only (a hum is there when nobody speaks; a voice is not): healthy voices sit at ≤ 0.006, the 45 Hz hum at 0.21–0.25, and after the 70 Hz rumble filter the hummed samples fall back to 0.03–0.05.
- **sibilance** is the 5–9 kHz / 2–5 kHz balance. The studio's own thirteen voices measure 0.28–0.98, so the de-esser only engages above 1.20 — a bright voice that is simply bright is left alone.
- **clarity** is 2–4 kHz / 500 Hz–2 kHz; it is only lifted when it is below 0.008, i.e. below every healthy voice in either language set (0.012–0.079).
- **"nothing needed"** means exactly that: the plan was empty and no EQ, gate, compressor or de-esser touched the audio. What remains is the loudness normalisation — which is why the LUFS column moves on every row (the TTS came in around −20 to −24 LUFS; the deliverable standard is −16).

## What is NOT in this table

Pronunciation, consonants, vowels, naturalness, emotion and breath cannot be measured from a table — they are judged by ear. That is why every row above exists twice on disk, original and HD, from the same synthesis run: play them side by side. The engine never re-synthesises and never touches timing, so any difference you hear is the one the measurements describe.

```
engine + thresholds   HD-Cleanup-Khmer.md
raw numbers           sonora/public/hd_samples/samples.json
engine checks         python3 pipeline/test_hdclean.py      (139 checks)
rebuild this matrix   python3 pipeline/make_hd_samples.py
```
