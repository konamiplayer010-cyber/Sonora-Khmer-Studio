# Spec coverage — “HD / Clean Khmer Voice” against the 30-section specification

**Feature:** HD / Clean Khmer Voice · **engine:** Adaptive Khmer Voice Enhancement
**Lives in:** the **RVC VOICE CLONE** path only · **Khmer only** (§1, §2)
**Code:** `pipeline/hdclean.py` = `sonora/hdclean.py` (one file, two copies) · wiring: `sonora/server.py` · switch: `sonora/public/index.html`

Every row below was checked against the code and, where a number appears, against
a measurement — not against an intention. The measurements live in
`sonora/public/hd_samples/samples.json` (20 rows), `hd-samples.md` (the matrix)
and `HD-Cleanup-Khmer.md` (the narrative report).

| § | what the spec asks | where it is | how it was checked |
|---|--------------------|-------------|--------------------|
| 1 | One workflow: TTS → analysis → adaptive enhancement → quality check → loudness → HD output; user sees ONE operation | `server.py::_hd_cleanup_clone` runs the whole thing once per job; the engine's `enhance_file()` is that pipeline in one call | studio-side suite `test_hd_server.py` (14 checks): the job produces a master + `enhanced_hd.wav` + previews with one status line |
| 2 | A simple `HD / Clean Khmer Voice` option; no EQ/comp/NR controls; off → plain TTS | `index.html` `#hdRow` + `#hdEnable`; a row to the right of `RVC VOICE CLONE`. It is always on the page, but at **75 % opacity with its box disabled** until the clone is ticked — visible, not usable; ticked, it goes to full strength, on by default, and the four-case demo panel under it comes alive | browser suite `check_hd_ui.py` (42 checks): opacity 0.75 and box disabled with the clone off, a dead ▶ fetches nothing, full opacity with the clone on, ▶ plays `hd_samples/<case>.<original|hd>.mp3`, positioned right of the clone box, no other controls, and the page fits at four sizes |
| 3 | Analyse first; only process what is needed; cleaner ≠ louder/brighter | `plan()` — every stage is gated by its own measurement and returns an **empty** plan on a clean file | **11 of the 15** clean Khmer samples ran no corrective stage at all; thresholds sit outside the healthy range of all 13 studio voices |
| 4 | Protect identity, pronunciation, accent, emotion, style, pauses | the engine has no pitch shift, no formant change, no time stretch; every pass reads the original | F0 moves ≤ **0.48 %**; whole-file spectrum ≤ **1.03 dB**; every output the same length as its input |
| 5 | Analyse level, LUFS, true peak, noise, rumble, HF noise, clipping, sibilance, reverb, SNR, silence, clarity; score 0–40 / 40–60 / 60–80 / 80–100 | `analyze()` measures all of it per 30 s chunk; `score()` turns it into the 0–100 number; `band_of()` names the band | matrix rows carry the score before → after (e.g. 99 → 100, 90 → 90); `test_hdclean.py` asserts the band names and that a clean file rates “good” (score ≥ 95) |
| 6 | Gentle NR only when noise is there; no metallic/underwater/robotic sound | stage switches on when SNR < 42 dB, strength follows how bad it is | hiss fixture: SNR 15 → 22 dB, artifacts “none”; a clean file never gets NR |
| 7 | 70–90 Hz high-pass for rumble, keeping vocal body | two cascaded filters (12 dB/oct); corner follows the voice | measured: 45 Hz hum −16.7 dB, 100 Hz only −1.9 dB; rumble fixture 0.21 → 0.03 |
| 8 | Small 150–350 Hz cut only when muddy | low-mid weight vs 350–1500 Hz, line 7.0 (studio voices 2.8–4.1) | `test_hdclean.py` asserts silent on clean fixtures, fires on the muffled one |
| 9 | Gentle 2–4 kHz presence only when unclear | 2–4 kHz vs 500 Hz–2 kHz, line 0.008 (healthy 0.012–0.079), lift +0.4–1.6 dB @3.3 kHz | muffled fixture gets ≥ presence; every healthy sample was left alone |
| 10 | 4–9 kHz de-ess / harshness control, never dull | 5–9 kHz vs 2–5 kHz, line **1.20** — above every studio voice (0.28–0.98 yields); shelf at 7.2 kHz, −0.8…−3 dB | a deliberately harsh fixture receives it; a shelf-lifted *healthy* voice does not (both asserted — the first attempt at this rule “corrected” good voices and was rejected) |
| 11 | De-reverb only when there is reverb | measured in the pauses (tail > 0.025) and only on a quiet recording (SNR > 45) | room fixtures 0.042 → 0.014; dry samples never touched |
| 12 | Gentle compression 2:1–3:1, ≈3–6 dB on loud sections when needed; never flat | gated on **measured** phrase-to-phrase wander > 10 dB (healthy files 4–9.3 dB); threshold 4 dB under the voice's own speech level | wandering fixture: wander 10.7 → 6.3 dB, gain reduction **3.5 dB**, ratio 2.1:1 — 3 checks assert exactly this |
| 13 | Loudness normalisation by measurement, not peak | two-pass `loudnorm` using the measured I / LRA / threshold | every sample lands −15.9…−16.6 LUFS |
| 14 | ≈ −1 dBTP true-peak safety, never a maximiser | `alimiter` at −1 dBTP after the loudness stage, with look-ahead latency compensated | true peak −1.75…−1.00 dBTP across the matrix; pass adds **0 samples** of delay (cross-correlated) |
| 15 | WAV 48 kHz / 24-bit; do not resample 48 k; upsampling ≠ restoration | `OUT_SR 48000`, `BITS 24`; the decoder skips resampling when the source is already 48 k | bit-exact path asserted; the only conversion is the decoder's single soxr step for a 24 k source — never described as added detail |
| 16 | Never overwrite the original; keep `original` + `enhanced_hd.wav` | `_hd_cleanup_clone` copies the master to `<key>.original.wav` first | `test_hd_server.py` asserts the original's md5 is unchanged and the HD file is a separate 48 k/24-bit master |
| 17 | Original ▶ / HD Clean ▶ preview, 5–10 s | `_write_previews()` writes both; the UI plays them | previews measured at **8.0 s**; browser suite asserts the two buttons request the two URLs |
| 18 | After processing, look for artifacts; if worse, reduce strength and regenerate **from the original** | `_artifact_check()` compares the result to the original; one retry at `REDO_CAP 0.4`, never more | suite forces a “worse” reading: exactly one retry, at the reduced cap (1.0 → 0.4), from the original, and never a third pass (4 checks) |
| 19 | Never chain enhancement passes; always start from the original TTS | every call decodes the source it is given; the studio never re-runs an output | two passes on the same file are byte-identical (asserted twice: engine + studio suites) |
| 20 | Whole-script audio first, then enhance the whole thing | the studio finishes the full clone, then runs HD on that file | `test_hd_server.py`: the HD stage receives the finished master, not per-sentence pieces |
| 21 | Long audio: internal 10–30 s chunks, seamless, one global loudness + one final limiter | `CHUNK_SECS 30` with `OVERLAP_SECS 0.75` context each side, writing only the middle; loudness and limiter run once, after assembly | seam and alignment tests: output sample-aligned with input (lag 0), no seam artefact on a >30 s file |
| 22 | Never change the emotional performance | content/emotion is the TTS layer's; the engine only touches noise, rumble, room, mud, harshness, dynamics, loudness | emotional/whisper rows keep their F0 (230.8 → 231.9 Hz) and their timing exactly |
| 23 | “HD” is not a loudness preset; do less when less is needed | global strength = (100 − score)/100, so a good file gets a very light hand; stage gates are absolute, not score-driven | healthy samples: empty plan, strength 0.00; damaged ones get only their own stage |
| 24 | Enhancement failure must return the original | the master is replaced only on success | suite fails the engine on purpose: the original stays, no HD file exists, and the log/UI show the exact sentence **“Enhancement unavailable; original TTS preserved.”** |
| 25 | The 15-step order | implemented in that order: preserve → analyse → noise → de-reverb → rumble → mud → clarity → harshness → compression → loudness → true peak → final analysis → export | the plan's `stages` list is printed in processing order in every log row |
| 26 | The IF/THEN rule table | `plan()` is an if/elif chain in that order, each branch appending its reason | each branch is asserted by one of the 110 engine checks |
| 27 | Priority: identity > pronunciation > emotion > intelligibility > clean > loudness > resolution | thresholds are placed so that identity is never traded for clarity; nothing in the engine can move pitch, timing or formants | identity measurements above; the harshest stage is a −3 dB shelf, the deepest EQ move −1.6 dB |
| 28 | ≥10–20 representative Khmer samples, Original vs HD, on 13 listed qualities | `pipeline/make_hd_samples.py` generates exactly that set | **15 clean rows** (normal / fast / slow / emotional / calm / long / short / names / numbers / punctuation / pauses / whisper, two voices) + **5 degraded**, all measured and stored |
| 29 | The 15 success criteria | each is a check in the two suites or a matrix column | see “the ✓ list” below |
| 30 | Product concept, feature and engine names | UI: **HD / Clean Khmer Voice**; engine docstring and reports: **Adaptive Khmer Voice Enhancement** | named in the panel, the report, the log line and both READMEs |

## The §29 ✓ list, with the number behind each one

| criterion | evidence |
|---|---|
| Background noise reduced | hiss fixtures SNR 14 → 21 / 15 → 22 dB |
| Speech easier to understand | unclear fixtures get the presence lift; clean voices are never touched |
| Voice sounds clean | 11 of 15 samples needed no correction; the other 4 got one move ≤ 1.3 dB |
| Voice remains natural / pronunciation intact | no synthesis, no re-tuning, no time stretch — output is the same take |
| Voice identity recognisable | pitch ≤ 0.48 % · spectrum ≤ 1.03 dB |
| Emotional delivery intact | F0 and length preserved on the emotional and whisper rows |
| Loudness consistent | every sample −15.9…−16.6 LUFS |
| No clipping | true peak −1.75…−1.00 dBTP, limiter after the loudness stage |
| No robotic artifacts | artifact check per pass; every matrix row “none” |
| No excessive EQ / compression / processing | largest EQ move −1.6 dB; compression only on measured wander, 3.5 dB GR |
| High-resolution output | 48 kHz / 24-bit PCM WAV, from the master |
| Original available as backup | `<key>.original.wav` beside `enhanced_hd.wav`, md5 asserted |

## How to run the evidence yourself

```bash
python3 pipeline/test_hdclean.py                # 139 checks — the engine
python3 pipeline/test_hd_server.py              #  14 checks — the wiring
python3 pipeline/check_hd_ui.py                 #  42 checks — the switch + the demo panel, in a browser
python3 pipeline/make_hd_samples.py --offline   # rebuild the §28 matrix (~22 s)
python3 pipeline/make_hd_report.py              # regenerate HD-Cleanup-Khmer.md
```
