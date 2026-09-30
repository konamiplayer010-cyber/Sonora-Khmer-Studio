# Sonora Khmer Studio — one package, two tools

## Build 2026-09-30q — the HD switch is a real, testable feature of the studio

The tool used to be hidden until you ticked RVC VOICE CLONE, and the only way to
hear what it does was a separate page. In this build:

- **HD / CLEAN KHMER VOICE is always on the page**, next to RVC VOICE CLONE, but
  at **75 % opacity with its box disabled** until the clone is ticked — visible
  and obviously part of the studio, plainly not usable yet. Tick the clone and it
  goes to full strength, on by default (§2: one switch, still no EQ, no
  compressor, no noise-reduction dial anywhere).
- **The four takes are playable inside the studio.** “A healthy take — almost
  nothing to fix”, “A hiss floor — noise reduction”, “A 45 Hz hum — rumble
  filter”, “A roomy take — de-reverb”, each with **▶ Original** and **▶ HD Clean**.
  They are the exact clips `HD-Cleanup-Demo.html` plays
  (`hd_samples/<case>.original.mp3` / `.hd.mp3`). Dimmed and dead while the clone
  is off; a dead button fetches nothing.
- **PERFORMANCE is one header row with the two dials side by side** — same
  controls, same order, same ticks, same read-outs; 167 px tall at 2557 × 1239
  instead of two stacked full-width boxes.
- **Less text:** ⟳ Test clone ▶ now sits directly after 🔍 Find RVC folder, and the
  long “how the clone and the base voice work” paragraph is folded into a
  one-click summary (117 px of text, not one word deleted).

`HD-UI-Update.html` shows all of it as real browser captures at 2557 × 1239, next
to the previous build for comparison. The browser suite grew with it —
`pipeline/check_hd_ui.py` is now **42 checks**.

## Build 2026-09-30p — HD cleanup no longer boosts damaged audio

The HD / Clean Khmer Voice engine **measured** clipping and distortion, logged
them, and then boosted and compressed the file anyway — the one thing you must
never do to audio that is already pinned at the ceiling. Fixed in this build:

- **Clipping is detected properly.** A pinned run — three or more samples in a row
  flat to within 1e-4 at ≥ 0.90 of full scale — is clipping. A file normalised
  *after* it clipped used to slip past `|x| > 0.999`, and a "within 0.5 % of the
  peak" test fired on healthy low-frequency peaks instead. Line: **0.02 %** of
  samples.
- **Hard limiting is caught by crest factor** — the distance between the peak and
  the body of the voice, which no amount of resampling can restore. Line:
  **13.5 dB** (the studio's 13 voices measure 16.4–17.6 dB, the Khmer samples
  15.0–16.1; a ×2.0 gain 12.5, ×3.2 9.5, a tanh overload 9.6).
- **And the reading now changes the plan, not just the log.** Damaged input gets
  **no presence boost and no compressor**, and a **−1.5 dBTP** ceiling instead of
  −1 dBTP (§26, failure-averse); the score carries the penalty
  `min(12, (13.5 − crest) × 3)`.

See `hd-samples.md` row `06 | clip` and `HD-Cleanup-Khmer.md` stage 9.

## Build 2026-09-30o — no whisper, and no breath noise in the pauses

The last non-speech sound the generator made was a synthesised breath — filtered
noise, about 35 dB under the voice — written into every few sentence gaps. In a
five-minute read it fired 10-15 times, which is the "whisper between the
sentences" that was still audible after build n. The breath audio is gone: every
pause is now exact digital silence, both synthesisers return silence, and no
style, feeling or delivery can mark a line for one. The pauses themselves are
untouched — each style keeps its own pace, pause lengths, softness and emphasis,
so Meditation is still slow with long gaps and news is still brisk. The 13 panel
demo clips and the English pack were rebuilt with the same engine. See
`Whisper-Removed.md` (the build-o instructions now live in `START-HERE-build-p.txt`).

## Build 2026-09-30n — the whisper is removed

The whisper stage is gone from every voice, Khmer and English. A whispered line
was synthesised as a different sound (a breath carrying the words, measured
15.4 dB airier than the voice), so mid-read it stopped being the voice that was
speaking — and the loudness chain then brought it up to the level of the
sentence it replaced. Nothing whispers now: no style, no delivery, no text cue,
and the engine entry point returns your audio bit-identical. An intimate passage
is still slower, softer and closer — read by the same voice. See
`Whisper-Removed.md` and `Whisper-Removed.html`.


Everything for making Khmer audiobook narration in **your own voice**
(the Sonaro-Kh RVC model), cleaned and mastered, in one folder.

Double-click **`START.bat`** and pick a number from the menu.

```
  sonora\        the live studio   — type, press Generate, listen, clone
  pipeline\      the batch factory — whole script in, finished audiobook out
  khmer-colab\   train your own Khmer voice on free Google Colab
  checkpoints\   neural weights (downloaded once, shared by BOTH tools)
```

---

## Which one do I use?

| | You want to… | Use |
|---|---|---|
| **Sonora Studio** | try a voice, paste a paragraph, hear it right away, work line by line | menu **1** |
| **Batch Pipeline** | turn a whole chapter or book into finished audio and walk away | menu **2** |

They are the same voice, the same Clean & Clear engine, the same settings —
one is interactive, the other runs unattended.

---

## First run — do these three things

**1. Check your voice model (menu 3).**
RVC training leaves a big `G_*.pth` *checkpoint*; inference needs the small
*extracted* model:

```
RVC-WebUI → ckpt-processing tab → point at the newest logs\Sonaro-kh\G_*.pth
          → name: Sonaro-kh   version: v2   sample rate: 40k
          → Extract small model → save as  assets\weights\Sonaro-kh.pth
```

Menu 3 (`check_model.bat`) tells you whether a given `.pth` is the real
inference model or just a training checkpoint — run it after extracting.

**The delivery (in the studio)** — the NARRATION STYLE panel sits above the two
dials: fourteen cards, each with a ▶ that plays that style explaining itself.
Picking a card sets that style's pauses (and nothing else), your voice is spoken
unmodified, and DRAMATIC PAUSES / NARRATION SPEED stay yours to move. Every
voice row still has a ▶ button so you can hear that voice before you use it.

**1a. Test the clone (menu 11)** — one paragraph through the real pipeline
(preflight → text → voice → **your RVC clone**), in its own folder so your book is
never touched. Listen to the result before you batch anything. Full walkthrough:
`RVC-model-check-walkthrough.md`.

**1b. Fix the RVC python (menu 12)** — only if the clone test says
`No module named ...`. RVC runs in its *own* python; this finds exactly what that
python is missing and installs only that, with your OK. Your models, index and
settings are never touched.

**1c. Check your RVC model (menu 3)** — a full screen-by-screen walkthrough ships
with the package: `RVC-model-check-walkthrough.md` (which `.pth` is your clone, what
each file in the RVC folder is, and exactly what the tool prints if something is wrong).

**1d. Train a new clone from your own recordings (menu 13)** — prepare the dataset
first: menu 13 turns a folder of recordings into training-ready 40 kHz WAVs, prints a
quality verdict (GOOD / WORKABLE / THIN / TOO LITTLE), and writes
`RVC-TRAIN-SETTINGS.txt` — every value to type on the RVC-WebUI **Train** tab. The full
step-by-step (screenshots' worth of detail, the exact boxes, the index step, and how to
put the finished model into the studio) is in **`Khmer-RVC-Training-Walkthrough.md`**.

**2. Add Khmer voices (menu 7)** — optional. Menu 7 installs extra engines so the
studio never runs out of ways to speak Khmer (see the engine table above).

**2b. Install the neural cleanup engine (menu 4)** — optional but recommended.
It prints every step (pip → pypi check → install → dependency resolve →
import → weights). If something fails, the failing step is shown and the
full log is kept at `pipeline\.clean_install.log`. The ffmpeg cleaner works
without it, so nothing is ever blocked.

**3. Put your script in `pipeline\input\history_kh.txt`** (UTF-8), then menu 2.

`pipeline\config.json` already points at your RVC installation
(`E:\Audio Books\History\TH\RVC20260718Nvidia\RVC20260718Nvidia`) with your
exact index file. You normally never have to touch it.

---

## Narration styles — the performance, not just a label (studio)

Fourteen styles, each with its own delivery specification (tone, emotional band,
pace, pitch movement, loudness, pauses, breathing, emphasis, ending cadence) and

| style | what it does |
|---|---|
| **Natural read** | relaxed, conversational, believable |
| **Narrative Storytelling** | warm storyteller; emotion builds through the piece |
| **Novel Narration** | literary, controlled, cinematic but restrained |
| **Documentary** | calm, authoritative; numbers/dates land with weight |
| **Movie trailer** | low, powerful, big pauses, slow→intense escalation |
| **Audiobook** | long-form comfort, subtle character colouring |
| **News anchor** | crisp, neutral, brisk; almost no emotional colouring |
| **Explainer** | friendly teaching voice; slows on new ideas |
| **Thriller** | hushed, tense, low register, long silences before reveals |
| **Meditation** | very slow, spacious, long breathing gaps |
| **Inner Monologue** | private thoughts, close and reflective |
| **Sad Romantic** | restrained longing, gentle downward endings |
| **Emotional Cinematic Storytelling** | scene-building with wide dynamics — the sentence builds into its emphasis beat, is closer there and eases away at the end (`express.py`, build k) |

**The default is Audiobook** (chosen for long-form history narration): comfortable
pace, subtle character colouring, gentle paragraph endings, unobtrusive breathing.
Change it any time — studio cards, or `START.bat → 10`, or `"narration_style"` in
`pipeline/config.json` (empty string = plain read, fastest).

**What actually changes** — the engine reads each sentence and decides emotion,
intensity (0–100), pause length, stress, breath, phrase rhythm and ending
cadence, inside the style's own pace and softness. Contrast is enforced: quiet sentences are guaranteed, and short punchy
lines or revelatory moments get more weight. A pause before the phrase that
carries a sentence is part of the performance, not a fixed silence.

**Every style performs its own way.** A style is not a label: it has its own
pace, its own softness and its own pause length, and the engine performs it
that way in the studio and in a batch run (meditation 0.84× at −1.2 dB with long
gaps, news 1.07× and brisk, a trailer 0.90× and +0.7 dB, cinematic 0.99× at 0.0 dB
whisper). What never changes is the **speaker** — pitch stays at 0.0 st in all
13 styles and all 52 feelings, so it is always the same voice.

**The feeling layer** — the style is the permanent framework; the feeling is
variable. Every sentence is performed with one of its own style's four emotional
deliveries (56 in total), chosen from the text: a Documentary line that feels sad
is still documentary, a whisper inside a cinematic story stays a brief moment,

Two example plans (`python narration.py --plan "…" --style thriller`):

    thriller   1. gravity      I= 44 rate=0.94 pitch=-1.4st gain=-0.7dB pause=0.41s
               2. tension      I= 69 rate=1.06 pitch=-2.2st gain=+0.9dB pause=0.49s breath
               3. revelation   I= 66 rate=1.05 pitch=-2.1st gain=+0.7dB pause=0.48s
    meditation 1. gravity      I= 11 rate=0.80 pitch=-1.2st gain=-1.2dB pause=0.56s
               2. revelation   I= 14 rate=0.82 pitch=-1.1st gain=-0.9dB pause=0.57s

Same words, completely different performances. Every style is audio-verified.

**Hear it:** `pipeline/demo/narration-styles.mp3` — one Khmer passage in
**all 13 styles**, back to back, each segment announced by its name in Khmer
(4:46; `narration-styles.txt` is the index and lists each style's pace, softness
and pause length; rebuild with `python build_style_demo.py`). The English panel
clips — every style performing *and* describing itself — are packed together as
`all-13-narration-styles.mp3` at the top of the ZIP (3:50), and each card's ▶ in
the studio plays its own clip.

---

## Khmer voices — what the studio can speak with (menu 7)

The package knows several free Khmer engines and **automatically uses the best one
that works**, so a run never dies because one provider is down:

| engine | what it is | offline | licence |
|---|---|---|---|
| **edge** | Microsoft Neural `km-KH` Sreymom / Piseth — the default | no | Microsoft terms |
| **voxcpm** | VoxCPM2 — 48 kHz, can clone your voice (needs ~8 GB VRAM) | yes | Apache-2.0 |
| **mmsft** | MMS Khmer **fine-tuned** — a second Khmer narrator, tighter pacing (this is also the slot for a voice *you* train — see `khmer-colab/`) | yes | CC-BY-NC (non-commercial) |
| **mms** | Meta MMS-TTS Khmer — slow but faithful | yes | CC-BY-NC (non-commercial) |
| **gtts** | Google voice — emergency fallback | no | unofficial |

Tried in this order by default: `edge → mmsft → mms → voxcpm → gtts` — the first one
that works wins, so a Microsoft outage or no internet no longer stops a book.

`tts_engine` in `pipeline/config.json` is `"auto"` (default) or forces one engine
(any name from the table). `narration_style` (also in the pipeline config) applies
the same 14 performance styles to a batch run — empty means a plain read per chunk
(fastest); set e.g. `"narration_style": "documentary"` and every sentence is
performed. The stage-2 output then reports, per chunk, the style, how many
sentences were performed and the intensity range. Every chunk records which engine spoke it — including the
exact voice — in `logs/processing_log.json`.

**Two offline Khmer voices, one command:** `install_khmer_tts.bat` (menu 7) → option 2
installs them and downloads both models, so the package can read a whole book with
the internet switched off.

**Hear the difference:** `pipeline/demo/khmer-voice-a-standard.mp3` (stock Meta MMS)
vs `pipeline/demo/khmer-voice-b-finetuned.mp3` (fine-tuned) — the same two sentences
through both. Measured on these files: the stock voice needs **10.8 s** of speech with
a median pitch of **134 Hz**; the fine-tune **8.6 s** at **200 Hz**. A different
narrator, and it draws the reading out less. Listening takes 20 seconds — that is the
fastest way to decide which voice a book wants.

**Khmer text is spoken properly now**, not read as raw symbols:

| written | spoken |
|---|---|
| `$1,200` | មួយពាន់ពីររយ ដុល្លារ (one thousand two hundred dollars) |
| `2,500,000 រៀល` | ពីរលានប្រាំសែន រៀល |
| `3:30` | ម៉ោងបី សាមសិបនាទី |
| `ថ្ងៃទី 5` | ថ្ងៃទីប្រាំ |
| `1990-1995` | ពីមួយពាន់ប្រាំបួនរយកៅសិប ដល់ មួយពាន់ប្រាំបួនរយកៅសិបប្រាំ |
| `012 345 678` | digit by digit (phone numbers) |

---

## Train a NEW RVC clone from your own voice (menu 13)

RVC copies the *timbre* of a voice it has heard. Everything the ear calls quality comes
from the recordings, not from the settings:

* **menu 13** (`pipeline\prep_voice_dataset.py`) — mono, 40 kHz, rumble removed, long
  silences trimmed, peak-limited, optional light denoise; measures the result and writes
  `DATASET-REPORT.txt` + `RVC-TRAIN-SETTINGS.txt` next to the finished dataset.
  Menu 13 has three doors: **1** prepare recordings into a dataset, **2** make a
  numbered Khmer reading script from any text file (`make_reading_script.py` — one
  sentence per line, breath marks, running time estimate, stops at your target length,
  so you have something to record from), **3** re-check an existing dataset folder.
* **`Khmer-RVC-Training-Walkthrough.md`** — the whole path: record 30–60 min → prepare →
  Train tab (40k · v2 · rmvpe · 200 epochs · batch 3 · *save small model = Yes*) →
  *Train feature index* → copy the `.index` into `assets\indices\` → test in
  RVC-WebUI's Model Inference tab → then into the studio's RVC VOICE CLONE panel
  (MODEL = the new `.pth`, INDEX = blank, PITCH = 0).
* **`Khmer-Female-Clone-How-To.md`** — the same path for a **female** clone: a clone's
  gender comes only from the recordings, so this one uses a female speaker's audio, a
  new experiment name (`sonara_female`, nothing is overwritten) and the pitch check that
  proves which model is loaded.

Nothing here overwrites `Sonaro-kh.pth` or your existing index — a new model is trained
under a new experiment name (`sonaro_kh2`).

---

## Train your own Khmer voice — free (menu 8)

`khmer-colab/` holds a complete kit for fine-tuning a Khmer TTS model on your own
recordings, on the **free Google Colab T4**:

* `Khmer_Voice_Colab.ipynb` — the notebook (upload to Colab, run top to bottom)
* `prepare_khmer_dataset.py` — runs on your PC: turns a folder of clips + Khmer text
  into a checked, 16 kHz dataset (catches silent/too-short/non-Khmer clips for you)
* `README.md` — the walkthrough, honest about what to expect

The finished model can be used in the studio as the **offline engine** — your voice,
no internet, no subscription. See `khmer-colab/README.md` step 3.

---

## What the pipeline does (menu 2)

```
Khmer script → normalize → chunk → TTS → Sonaro-Kh RVC → chapter + final WAV
             → CLEAN & CLEAR: denoise → 48 kHz → -16 LUFS master
```

- **Resumable** — re-running skips every chunk that already validated.
- **Non-destructive** — never overwrites or deletes successful audio or logs.
- **Honest** — a stage only reports success if the output file exists and validates.

Stages: `00_preflight` → `01_normalize_khmer` → `02_generate_tts` →
`03_rvc_convert` → `04_merge_audio` → `05_clean_master`.

---

## Clean & Clear

Two tiers, and you always get the better one available:

- **ffmpeg tier** — denoise, EQ, de-ess, 48 kHz, loudness to −16 LUFS /
  −1 dB peak. Always available.
- **neural tier** — MossFormer2 neural denoise (+ super-resolution where the
  machine has the RAM), then the same master chain. Needs menu 4.

Settings live in `pipeline\config.json` → `clean_master`
(`target_lufs` −16, `true_peak_db` −1, `sample_rate` 48000, `super_res` true).

**Hear the difference:** menu 5 — `clean-and-clear-demo-v2.mp3` plays the same
Khmer line raw, ffmpeg-cleaned and neural-cleaned, all loudness-matched, so
you hear clarity rather than volume.

---

## HD / Clean Khmer Voice — for the RVC clone, in Khmer

A second switch, and it only appears where it belongs: tick **RVC VOICE CLONE**
and an **HD / CLEAN KHMER VOICE** box drops in at the right of it (Khmer only).

It is one operation, not a rack of controls — TTS → analysis → adaptive
enhancement → quality check → loudness → true-peak protection → HD output — and
it does **less when less is needed**: fifteen real Khmer samples came back with
twelve needing no correction at all, and three asking for one small move each
(a 0.4 dB clarity lift, a 0.8 and a 1.3 dB low-mid trim).

- 48 kHz / 24-bit master, measured to −16 LUFS and ≈ −1 dBTP, kept next to the
  original: your clone audio is never overwritten (`<key>.original.wav`).
- **Original ▶ / HD Clean ▶** buttons appear with the result, so the change can
  be heard before anything is exported.
- If anything goes wrong the original is what stays, and the log says
  *“Enhancement unavailable; original TTS preserved.”*

The full measurements — what each stage does, when it switches on, and the
Khmer sample matrix with pitch, spectrum, length and level checks — are in
**`HD-Cleanup-Khmer.md`**; the clips are in `sonora\public\hd_samples\`.

---

## Notes

- Both tools read and write **WAV** internally; MP3 only at delivery.
- The weights in `checkpoints\` are downloaded **once** and shared by both
  tools. If you move the folder, they are fetched again (or copy the folder too).
- No Kiri, no cloud accounts, no API keys anywhere in this package.
