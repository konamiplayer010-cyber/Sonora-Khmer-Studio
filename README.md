# Khmer History Production Pipeline (Sonaro-Kh RVC)

Reliable, resumable, non-destructive production of long Khmer history
narration in your Sonaro-Kh voice:

```
Khmer script → normalize → chunk (1–4 sentences) → TTS WAV → Sonaro RVC WAV
             → chapter WAV → final WAV
             → CLEAN & CLEAR: denoise → 48 kHz → loudness master → clean master
             (+ JSON processing log + reports)
```

## Quick start

1. Put your script in **`input/history_kh.txt`** (UTF-8).
   Chapters start at a line like `Chapter 1`, `CH. 2`, `CHAPTER 10: ...`
   or Khmer `ជំរើទ 5`. No headers → the whole file is one chapter.
2. Check **`config.json`** — your RVC root, model and index are already
   filled in (verified from your installation). Change `tts_voice` only if
   you want a different carrier voice.
3. Double-click **`run_all.bat`**.

Re-run `run_all.bat` any time — every chunk that already passed validation
is **skipped**, so it resumes instead of restarting.

## "Why doesn't my voice clone work?" — read this first

RVC training leaves a folder like this inside RVC-WebUI:

```
logs/Sonaro-kh/          <- the TRAINING workspace (this is what you listed)
    0_gt_wavs/           preprocessing audio        - not a model
    1_16k_wavs/          preprocessing audio        - not a model
    2a_f0/  2b-f0nsf/    pitch data                 - not a model
    3_feature768/        training features (v2)     - not a model
    eval/                sample audio from training - not a model
    G_233333.pth         TRAINING CHECKPOINT (big)  - NOT usable for inference
    D_233333.pth         TRAINING CHECKPOINT (big)  - NOT usable for inference
    added_..._v2.index   feature index              - USABLE (this is the good one)
    trained_..._v2.index feature index              - usable too
```

Inference (Sonora, RVC-WebUI, this pipeline) needs the **small model** — a
single ~55–120 MB file that is *extracted* from a training checkpoint:

```
assets/weights/Sonaro-kh.pth      (2.3+ layout)
weights/Sonaro-kh.pth             (2.0–2.2 layout)
```

If that file does not exist, or you pointed MODEL at a `G_*.pth`, the clone
cannot work. Fix it once, in RVC-WebUI:

1. Open RVC-WebUI → the **ckpt-processing** tab (the one that also has
   "model fusion"; in some builds it is `ckpt処理` / "Model processing").
2. Point it at your **newest** training checkpoint, e.g.
   `logs/Sonaro-kh/G_233333.pth`.
3. Model name `Sonaro-kh`, version `v2`, sample rate `40k` (your folder
   `3_feature768` means v2).
4. Click **Extract small model**.
5. Save as `assets/weights/Sonaro-kh.pth`.
6. Check it: double-click **`check_model.bat`** (below), then run
   `run_all.bat`.

Not sure which tab it is? Send a screenshot of the RVC-WebUI tabs and we
will point at it exactly — no guessing.

### `check_model.py` / `check_model.bat`

Double-click **`check_model.bat`** any time. It lists every `.pth` under
your RVC folder and tells you which are usable voice models and which are
training checkpoints, with the fix printed for anything unusable.

```
[USABLE]              assets/weights/Sonaro-kh.pth
                      74.2 MB - true RVC voice model (small model)
[NOT A VOICE MODEL]   logs/Sonaro-kh/G_233333.pth
                      421.7 MB - raw training checkpoint - extract the small model
```

## The five stages (each runs standalone)

| Script | What it does | With which python |
|---|---|---|
| `00_preflight.py [--full]` | checks RVC root / index / model / inference API / TTS / folders / Clean & Clear engine; `--full` also does one real TTS→RVC test conversion | system |
| `01_normalize_khmer.py` | normalizes (numbers/%/currency → spoken Khmer, word spacing, punctuation), splits chapters + chunks, writes chunk files + change report | system |
| `02_generate_tts.py` | one validated WAV per chunk (skip valid, retry failed ≤2×) | system |
| `03_rvc_convert.py` | loads the model **once**, converts every chunk with ONE fixed settings set | **RVC python** (auto-detected) |
| `04_merge_audio.py` | assembles chapters (all chunks must be valid), final WAV in numeric order, writes `final/report.txt` | system |
| `05_clean_master.py` | **Clean & Clear** — denoise, de-ess, tonal tidy-up, 48 kHz, loudness master → `master/…_CLEAN.wav` + `master/report.txt` | system (model backends: RVC python) |
| `hdclean.py` | **HD / Clean Khmer Voice** (engine of the studio switch, Khmer + clone only) — analyse, correct only what is wrong, 48 kHz / 24-bit master at −16 LUFS / ≈ −1 dBTP, original kept. `make_hd_samples.py` builds the Khmer before/after matrix, `test_hdclean.py` runs its 105 checks. | system |

## Where things land

```
input/       your original script (never modified)
normalized/  chapter_XX.txt + chapter_XX_chunk_NNNN.txt + changes_report.txt
tts/         chapter_XX/chunk_NNNN.wav        (base voice)
rvc_output/  chapter_XX/chunk_NNNN.wav        (Sonaro-Kh)
final/       chapter_XX.wav + History_Narration_SONARO_KH.wav + report.txt
master/      chapter_XX.wav (clean) + History_Narration_SONARO_KH_CLEAN.wav
             + report.txt + listen.html   ← THE DELIVERABLE for listening
final/       also gets listen.html (raw chapters with ▶ buttons)
logs/        processing_log.json  (resume state — do not edit by hand)
```

Note: chapter *header lines* (`Chapter 1: ...`) label the chapter but are
not spoken. If you want the title read aloud, write it as the first line of
the chapter body.

## HD / Clean Khmer Voice

One switch in the studio (inside the RVC clone path, Khmer only): the clone is
analysed, corrected only where the measurement asks for it, then mastered to
48 kHz / 24-bit at −16 LUFS and ≈ −1 dBTP — with the original kept beside it.
The engine is `hdclean.py`; `python3 hdclean.py in.wav out.wav --report r.json`
runs it from a shell. Thresholds, the Khmer sample matrix and the measurements:
`HD-Cleanup-Khmer.md` in the package root.

## Clean & Clear (stage 05) — how to get the best out of it

The chain that makes output sound commercial:

```
RVC WAV → denoise → de-ess + tonal tidy-up → gentle compression
        → 48 kHz → two-pass loudness master (-16 LUFS, -1 dB true peak)
```

Two engines (config `clean_master.tier`):

| Engine | What it does | Install |
|---|---|---|
| **model** (best) | neural denoise, and with `clearvoice` **true 48 kHz super-resolution** (invents the missing high frequencies — this is the "clean & clear like Kiri" part) | in the RVC env: `<RVC folder>\venv\Scripts\pip install clearvoice` (or `pip install deepfilternet` for a light denoise) |
| **ffmpeg** (always works) | spectral denoise, de-ess, EQ, 48 kHz resample, loudness master | nothing — ships with RVC-WebUI / this tool |

`tier: auto` uses the model engine when it is installed and silently falls
back to ffmpeg (the report always says which one actually ran; "48 kHz SR:
… (resampled)" means no invented frequencies, "(true super-resolution)"
means the neural upsampler ran).

Settings live in `config.json` → `clean_master` (`enabled`, `target_lufs`,
`true_peak_db`, `sample_rate`, `de_ess_db`, `export_mp3`, …).
Set `"enabled": false` to skip stage 05 entirely, or `export_mp3: true` to
also emit a delivery MP3 (only ever at this final step).

If the RVC python has no ffmpeg, or `clearvoice` is not installed there yet,
nothing breaks — the model engine is simply reported as unavailable and the
ffmpeg engine does the job.

## The rules it enforces (from your production spec)

- **No guessing** — missing model/index/RVC python → `[MISSING]` report and
  STOP. The index is used exactly as configured; no replacement is created.
- **One verified RVC configuration** for the whole project (the settings
  that produced your `Sonaro-kh_test.wav`); never changed between chunks.
- **Never overwrite** a successful file — valid outputs are kept; candidates
  are written to `.part` files, validated, then moved into place.
- **Validated, not assumed** — a chunk counts only when the WAV exists,
  opens, has duration, and is not silent; the final file is checked the same
  way before "PRODUCTION COMPLETE".
- **Retry policy** — 2 automatic retries per failed operation, then that
  chunk is marked `failed` in the log; the rest of the project continues.
- **Traceable** — `logs/processing_log.json` records stage status, attempt
  counts and errors for every chunk; `final/report.txt` is the final report.

## If something fails

The console shows the exact chunk, stage and error. Typical causes:

- **TTS failures** — network to Microsoft (edge-tts). Re-run stage 02.
- **RVC load failure** — run 03 with the RVC python (`run_all.bat` does this
  automatically; if it doesn't find the venv, set `rvc_python` in config).
- **Chunk failed at RVC** — usually a transient GPU error; just re-run
  `run_all.bat` — only the failed chunk is re-converted.
- **CLEAN & CLEAR failed** — the exact reason is printed and logged (e.g.
  ffmpeg missing, or `tier: model` with no model backend installed). Other
  chapters are kept; re-run `run_all.bat` and only the failed chapter is
  re-mastered, then the clean master is rebuilt automatically.

## Safety

Nothing in this folder ever modifies your RVC installation, your model, your
index, or your original script. To start a *different project*: replace
`input/history_kh.txt`, set a new `final_name`, and move the previous
`final/` + `logs/` + `tts/` + `rvc_output/` folders aside (they are kept).

NARRATION STYLE (optional)
==========================

`narration_style` in config.json decides HOW the audiobook is performed.
It ships set to **audiobook** (the long-form listening style). Empty = plain read
(one TTS call per chunk, fastest). Set a style and stage 2 gives
every sentence its own performance: pace, pitch, loudness, pause length,
emphasis and breathing — from the specification in narration.py.

    natural | storytelling | novel | documentary | trailer | audiobook |
    news | explainer | thriller | meditation | inner_monologue |
    sad_romantic | cinematic

Choose it without editing JSON:  START.bat -> 10  (or python set_style.py)
Hear what they sound like:       START.bat -> 9   (or play demo\narration-styles.mp3)

Every chunk's log entry then records the style, e.g.

    "style": "Documentary | 2/2 sentences | intensity 38-43 | 1 breath(s)"

Cost: a styled run makes one TTS call per sentence instead of per chunk, so
stage 2 takes longer (roughly 2-4x on the same script). A plain read stays
available at any time by clearing the setting.

Check the engine itself:  python test_narration.py      (50 checks, no internet)
See a plan for your own text:
    python narration.py --plan "your sentence here" --style thriller
    python narration.py                                  (all styles, one table)
