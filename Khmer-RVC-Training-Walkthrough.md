# Train your own Khmer voice for RVC — step by step

**For: your machine** (Windows · NVIDIA RTX 3060 Laptop · RVC-WebUI open on the Train tab)
**Companion to: menu 13** (`pipeline\prep_voice_dataset.py`)

---

## 0. First, the honest part — what "as good as Kiri AI" means here

Kiri AI was a **Khmer text-to-speech engine**. It learned Khmer from thousands of hours
of Khmer audio, then spoke any text you gave it. Nothing you can train at home on one
GPU will match a system like that, and no RVC setting will turn RVC into it. Anyone who
promises otherwise is guessing.

So here is what we do match, and how:

| What the ear calls "Kiri quality" | Where it comes from in your setup | Status |
|---|---|---|
| Khmer pronunciation, word splitting, numbers, dates | the **carrier** TTS voice (`km-KH-SreymomNeural`) + Sonora's Khmer normaliser | already done |
| A **specific timbre** — *your* voice, not a stock voice | **RVC**, trained on your recordings | this walkthrough |
| Studio-clean, no hiss, no rumble, even level | **Clean & Clear** + the mastering chain | already done |
| A voice that sounds *performed*, not read | the 14 narration styles + feeling layer | already done |

**RVC copies a voice's timbre and keeps the carrier's pronunciation.** That is why we
build *"your voice, speaking like Sreymom"* — and it is the reason a good dataset is the
whole ballgame: RVC can only copy what it hears, and it copies the room and the
microphone just as faithfully as it copies you.

**Two rules that decide the result:**

1. **One speaker, one microphone, one distance, one room.** Two sessions from two rooms
   produce a model that drifts between two sounds.
2. **30–60 minutes of quiet speech beats 5 hours of noisy speech.** RVC's own guidance is
   10–50 min; below 5 minutes it rarely works at all.

---

## 1. What you need before you start

| Item | Detail |
|---|---|
| Recordings | 30–60 min of **you speaking Khmer**, mono or stereo, any format (wav/mp3/m4a) |
| Microphone | USB mic or a phone held ~15–20 cm away, **always the same** |
| Room | soft room (curtains, bed, clothes), **no music, no TV, no fan, no echo** |
| Content | read anything Khmer: a book chapter, news, your own scripts. Vary the emotion a little — flat monotone reading gives a flat model |
| Time | 1–2 h of recording + 1–3 h of training (the GPU is busy, you are not) |
| Disk | a few GB free on the drive where RVC-WebUI lives |

> **Do not** use a recording that has music under it, a phone call, reverb/echo, or two
> people. RVC will learn all of it. If your only source already has hiss, menu 13's
> `--denoise` option cleans it — that is exactly what it is for.

---

## 2. Step 1 — prepare the dataset (menu 13)

> **Nothing recorded yet?** `START.bat → 13 → option 2` turns any Khmer text file you
> already have (your book, news, notes) into a **reading script**: one sentence per
> line, numbered, breath marks every 10 sentences, running-time estimate, and it stops
> at 40 minutes of speech by default. Read that aloud and record it — that *is* your
> dataset material. Then come back to option 1.

1. Put all your recordings in **one folder**, e.g. `D:\my khmer recordings`.
2. Run **`START.bat` → 13 → option 1** (or double-click `pipeline\prep_voice_dataset.bat`).
3. It asks for three things:

```
  Folder with my recordings (drag the folder here, then Enter): D:\my khmer recordings
  Where should the training dataset go? (Enter = D:\khmer-dataset): D:\khmer-dataset
  Noise reduction? (y = yes, Enter = no):
```

What it does to every file: mono · 40 000 Hz · high-pass 70 Hz (kills rumble) ·
optional spectral denoise · long silences trimmed · peak-limited to −1 dBFS ·
saved as `km_0001.wav`, `km_0002.wav`, … It **never touches your originals**.

It prints a verdict, and writes two files into the dataset folder:

* `DATASET-REPORT.txt` — clips, minutes, and per-clip peak / RMS / silence / noise floor
* `RVC-TRAIN-SETTINGS.txt` — **every value to type on the Train tab** (step 3 below)

| Verdict | Meaning |
|---|---|
| **GOOD** (≥ 30 min) | professional range — train it |
| **WORKABLE** (10–30 min) | RVC's own recommended band; more recording still helps |
| **THIN** (5–10 min) | it will work, expect the carrier's accent to leak through |
| **TOO LITTLE** (< 5 min) | record more first |

---

## 3. Step 2 — open RVC-WebUI → **Train** tab and fill these boxes

Your screenshot already shows most of this — here is the same screen with the values that
matter, and the ones you must change (marked **CHANGE**).

### Step 1 row (top)

| Box | Set it to | Why |
|---|---|---|
| Enter the experiment name | `sonaro_kh2` | a new name — **never reuse `Sonaro-kh`**, you must not overwrite your working model |
| Target sample rate | **40k** | the standard for speech and what the pretrained pair expects |
| Whether the model has pitch guidance | **true** | you are cloning speech with pitch — needed |
| Version | **v2** | better detail than v1; matches your existing model |
| Number of CPU processes | **4** *(currently 11)* | **CHANGE** — 11 saturates the CPU and makes the whole PC stutter during processing |

### Step 2a — process the audio

| Box | Set it to |
|---|---|
| Enter the path of the training folder | `D:\khmer-dataset` (the folder menu 13 produced — it contains the `km_*.wav` files **and** the two report files) |
| Please specify the speaker/singer ID | `0` |
| | press **Process data** |

You will see `step 1: processing data` … and the folder `logs\sonaro_kh2\` appears with
`0_gt_wavs\`, `1_16k_wavs\`. Wait for **Successfully** (a few minutes for 30–60 min of audio).

### Step 2b — features

| Box | Set it to |
|---|---|
| Enter the GPU index(es) | `0` |
| Select the pitch extraction algorithm | **rmvpe** *(leave it — it is already selected)* |
| | press **Feature extraction** |

`step 2a: extracting pitch` … `step 2b: extracting features` … **Successfully**.
This is the slow part on a laptop GPU (10–30 min for a full dataset). Do not close the window.

### Step 3 — the model (this is where quality is decided)

| Box | Set it to | Why |
|---|---|---|
| Save frequency (save_every_epoch) | **10** | checkpoint every 10 epochs so you can hear the progress |
| Total training epochs (total_epoch) | **200** *(currently 20)* | **CHANGE** — 20 epochs gives a muffled, "not quite you" model. 150–200 on clean data is where it becomes convincing; 250+ only if the voice still sounds thin |
| Batch size per GPU | **3** *(already)* | correct for 6 GB. If you see **CUDA out of memory**, use **2** |
| Save only the latest .pth file | **No** *(currently Yes)* | **CHANGE** — you want the history: epochs 50 / 100 / 150 / 200 so you can pick the best-sounding one |
| Cache all training set to GPU memory | **No** *(already)* | 6 GB cannot hold a full dataset |
| Save a small model to the 'weights' folder at each save point | **Yes** *(currently No)* | **CHANGE** — this writes usable `Sonaro_kh2_...e_...s.pth` files you can test in Sonora, instead of raw `G_` / `D_` training checkpoints |
| Load pre-trained base model G path | `assets\pretrained_v2\f0G40k.pth` *(already)* | the "already knows how to talk" starting point |
| Load pre-trained base model D path | `assets\pretrained_v2\f0D40k.pth` *(already)* | |
| Enter the GPU index(es) | `0` | |
| | press **Train model** | |

**What you will see:** the console starts printing `[epoch 1/200]` lines with loss numbers.
Watch the **first 10 epochs** and multiply — that is your honest total time (expect roughly
1–3 hours for 200 epochs on a 3060 Laptop with 30–60 min of audio).

**Sound check while it runs:** every 10 epochs a new small model appears in
`assets\weights\`. Leave training running, open the **Model Inference** tab in a second
browser tab (see step 5), test the newest one, and note which epoch sounds best. If epoch
80 already sounds perfect and 200 sounds metallic, **you keep the epoch-80 file** — that
is why we saved the history.

### Step 4 — the index (do not skip this)

| | |
|---|---|
| press | **Train feature index** |
| result | `logs\sonaro_kh2\added_IVF*.index` |
| then | copy that `.index` into **`assets\indices\`** next to your other index files |

The index is the retrieval memory of your recordings. It is what removes the
"carrier accent leaks through" problem. Without it the clone sounds more like the base
voice than like you. Sonora finds it automatically when the name contains the model name.

> **If you skipped "Save a small model = Yes"**: open the **ckpt-processing** tab, use
> **Model extraction** → *Path to Model* = `E:\codes\py39\logs\sonaro_kh2\G_xxxx.pth`,
> *Save name* = `Sonaro_kh2`, *Target sample rate* **40k**, *pitch guidance* **1**,
> *version* **v2** → **Extract**. That converts a training checkpoint into a usable model.

---

## 4. Step 3 — test inside RVC-WebUI first

Open **Model Inference** (your first screenshot):

1. **Inferencing voice** — press **Refresh voice list**, pick your new
   `Sonaro_kh2_...s.pth`.
2. **Transpose** = `0` *(Khmer is not a tonal language; only change this if the clone sits
   clearly higher or lower than your real voice — then try ±1, ±2)*
3. **Select the pitch extraction algorithm** = `rmvpe`
4. **Resample the output audio in post-processing** = `0`
5. **Adjust the volume envelope scaling** = leave at `0.25` (Sonora handles loudness itself)
6. **Protect voiceless consonants …** = `0.33` — Khmer has many final consonants; this is
   the setting that stops them turning into clicks
7. **Search feature ratio** = `0.75` (range 0.6 safer ↔ 0.8 closer to you)
8. **Feature index path** — auto-matched when you pick a model; check it points at your
   new `.index`. If it does not, paste the full path.
9. Drop a **Khmer** wav (10–20 s) → **Convert**.

If it sounds like you, gate passed. Now put it in Sonora.

---

## 5. Step 4 — put the new model into Sonora

Those boxes you pasted, filled in:

| Field in the RVC VOICE CLONE panel | What to put there |
|---|---|
| **RVC FOLDER (RVC-WebUI)** | your RVC folder — the one that contains `infer\`. Press **🔍 Find RVC folder** and click the result; if it is already `E:\Audio Books\...\RVC20260718Nvidia` leave it |
| **RVC PYTHON (optional — blank = auto-detect)** | **leave blank.** The studio finds the python that RVC-WebUI itself uses. If a test says "no torch" / "No module named", run `START.bat → 12` once — that installs what RVC is missing into that python |
| **MODEL (.PTH)** | `assets/weights/Sonaro_kh2_...e_...s.pth` — the small model you kept. (Your current working model stays `assets/weights/Sonaro-kh.pth`; the new one is a *second* model, nothing is replaced) |
| **INDEX (.INDEX — blank = auto-detect)** | **leave blank.** The studio searches `assets/indices/` and `logs/`, prefers a name matching your model, and prefers `added_` indexes |
| **PITCH** | **0**. Only if the clone sounds notably deeper or thinner than you do: try `+1`…`+3` (deeper clone) or `-1`…`-3` |
| **INDEX RATE** | `0.75` to start. `0.6` = safer and faster, `0.8` = closer to your timbre |
| **BASE VOICE** | your Khmer carrier, `km-KH-SreymomNeural` |
| **CONVERT** | *Khmer lines only* |
| then | **⟳ Test clone ▶** — you hear the sentence in your cloned voice |

---

## 6. Step 5 — judge it honestly (A/B)

Listen to **Test clone** against the same sentence in the plain carrier voice. Score it:

| Symptom | Cause | Fix |
|---|---|---|
| Sounds like the **carrier**, not you | index missing, or too few epochs | copy the `.index` into `assets\indices\`; raise index rate to 0.8; train to 200+ epochs |
| **Muffled**, like behind a door | too few epochs, or noisy recordings | more epochs; re-run menu 13 with `y` (denoise) |
| **Warbly, watery, metallic** | too many epochs, or clipping in the recordings | use an earlier checkpoint (epoch 100/150); check `DATASET-REPORT.txt` for clipped files |
| **Breathing / clicking** between words | protect too low, or crackly source | protect `0.5`, re-record the noisy parts |
| Clone sounds **higher/lower** than you | pitch mismatch | PITCH ±1…±3 (one step at a time) |
| Some words swallowed | carrier pronunciation, not the clone | that is a normaliser/text issue — report the sentence and we fix the Khmer text pass |
| Good alone, bad in a whole book | model works, engine flags do not | turn on Clean & Clear in the batch tool (menu 4 → install, then tick it) |

**Good enough is a judgement call, not a number:** when a Khmer paragraph sounds like
**you reading it calmly**, and you stop noticing the audio and start hearing the words.

---

## 7. Optional — squeezing the last quality out

* **More data, same microphone.** 30 → 60 minutes is usually a bigger jump than 200 → 400 epochs.
* **Re-record the noisy parts.** Replace the file in the source folder and run menu 13 again — the dataset is rebuilt from scratch, the old one is not reused.
* **Epoch sweep.** Keep every checkpoint; the best-sounding one is often 120–180, not the last.
* **Model fusion** (ckpt-processing): blending your 150- and 200-epoch models at weight 0.5 sometimes softens the last roughness. Copy both to `assets\weights\` first, *Weight for Model A* = 0.5, then test.
* **v1 vs v2**: stay on v2. v1 is a fallback for older tools only.
* **48k**: only if you also download the 48k pretrained pair; for speech, 40k is the norm and what your existing model uses.

---

## 8. One-page cheat sheet

```
RECORD     30–60 min, your voice, Khmer, one mic, one quiet room
PREPARE    START.bat -> 13        -> D:\khmer-dataset (+ report + settings card)
TRAIN      RVC-WebUI -> Train
             sonaro_kh2 · 40k · true · v2 · CPU 4
             Process data     (folder = D:\khmer-dataset, ID 0)
             Feature extraction (rmvpe, GPU 0)
             save_every 10 · total_epoch 200 · batch 3 · latest=No · cache=No
             save small model = YES · f0G40k/f0D40k · GPU 0
             Train model
INDEX      Train feature index  ->  copy .index into assets\indices\
CHECK      Model Inference tab: Refresh voice list, Transpose 0, rmvpe,
           resample 0, protect 0.33, index rate 0.75, Convert
SONORA     RVC VOICE CLONE -> MODEL = new .pth · INDEX = blank · PITCH 0
           Test clone ▶  ->  then A/B  ->  then Generate your book
```

**Two things never to do:** never rename/replace the working index
`Sonaro-kh_added_IVF248_Flat_nprobe_1_Sonaro-kh_v2.index`, and never overwrite
`assets\weights\Sonaro-kh.pth`. Train under a new experiment name — that is exactly why
this walkthrough uses `sonaro_kh2`.
