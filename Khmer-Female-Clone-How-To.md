# How to train a FEMALE clone

A clone's gender, age and character all come from **the recordings you train on** — nothing in
Sonora or RVC can turn a male model female. So there is only one way to get a female clone:
**train a model on a female speaker's voice.** This is the whole path.

---

## 0 · What you need first

| | |
|---|---|
| Recordings of **one** female speaker | 30–60 min of her talking (RVC's own guidance is 10–50 min; below 5 min rarely works) |
| Her OK | you are about to clone a person's voice — get her permission, then keep it to whatever she agreed to |
| One microphone, one room, one distance | mixing sessions across two rooms or two mics makes the model drift |
| No music, no echo, no second voice | RVC copies reverb and background noise just as faithfully as it copies her |

**Two ways to get the recordings — pick one:**

* **A · She records now.** `START.bat → 13 → option 2` writes a **numbered Khmer reading script**
  (one sentence per line, breath marks, time estimate, stops at 40 min). She reads it aloud and
  records. That *is* your dataset material.
* **B · You already have her audio** — voice notes, interviews, old recordings. It only needs to be
  single-speaker, no music, no heavy echo. Dull, hissy files are fine: `START.bat → 13 → option 1`
  has a denoise option and a quality report.

> **Never mix two different women** in one dataset, and don't include your own voice in it. A mixed
> dataset gives you a voice that is a blend of everyone in it.

---

## 1 · Build the dataset — `START.bat → 13 → option 1`

Put all her recordings in one folder, then answer the three questions:

```
  Folder with my recordings (drag the folder here, then Enter): D:\her recordings
  Where should the training dataset go? (Enter = D:\khmer-dataset): D:\female-dataset
  Noise reduction? (y = yes, Enter = no): y        <- use y if you hear hiss/fan/room
```

It prints a verdict and writes `DATASET-REPORT.txt` + `RVC-TRAIN-SETTINGS.txt` into
`D:\female-dataset`.

| Verdict | Meaning |
|---|---|
| **GOOD** (≥ 30 min) | train it — this is the professional range |
| **WORKABLE** (10–30 min) | fine to start; more recordings still helps |
| **THIN** / **TOO LITTLE** | add more of her audio first |

---

## 2 · Train — RVC-WebUI → **Train** tab

Everything here is the same as the male clone, **except the experiment name**:

| Box | Set it to |
|---|---|
| Enter the experiment name | **`sonara_female`** — a new name. Never reuse `Sonaro-kh`; that would overwrite the model you already have |
| Target sample rate | **40k** (stay consistent — if you use 48k, use 48k everywhere) |
| Whether the model has pitch guidance | **true** |
| Version | **v2** |
| Number of CPU processes | **4** (not 11 — 11 stalls the whole PC) |
| Step 2a: training folder | `D:\female-dataset`, speaker ID **0** → **Process data** |
| Step 2b | GPU **0**, pitch extraction **rmvpe** → **Feature extraction** |
| Save frequency | **10** |
| Total training epochs | **200** (a low count is what makes a clone sound muffled / "close but not her") |
| Batch size per GPU | **3** (RTX 3060 Laptop 6 GB; use 2 if you get CUDA out of memory) |
| Save only the latest .pth | **No** — keep the history, pick the best-sounding epoch |
| Cache all training set to GPU memory | **No** |
| Save a small model to the 'weights' folder at each save point | **Yes** ← without this you only get `G_`/`D_` checkpoints |
| Load pre-trained G / D | `assets\pretrained_v2\f0G40k.pth` / `f0D40k.pth` |
| GPU index(es) | **0** → **Train model** |

Watch the first 10 epochs to estimate the total (typically **1–3 hours** on the 3060 Laptop).

**Test while it trains:** every 10 epochs a new small model lands in `assets\weights\`. Open
**Model Inference** in a second tab, refresh the voice list, pick the newest, and listen. Jot down
which epoch sounds most like her — often 120–180, not 200.

---

## 3 · The index (the step people skip)

RVC-WebUI → Train → **Train feature index** → then copy the result:

```
logs\sonara_female\added_IVF*.index   →   assets\indices\
```

The index is the retrieval memory of her recordings; it is what stops the base voice's accent from
leaking through. Sonora finds it automatically when its name contains the model name.

---

## 4 · Test it inside RVC-WebUI first — **Model Inference** tab

| Box | Value |
|---|---|
| Inferencing voice | **Refresh voice list** → `sonara_female_...s.pth` |
| Transpose | **0** |
| Pitch extraction | **rmvpe** |
| Resample in post-processing | **0** |
| Volume envelope | 0.25 |
| Protect voiceless consonants | **0.33** |
| Search feature ratio | **0.75** |
| Feature index path | auto-matched — check it is her `.index` |
| | drop a Khmer clip → **Convert** |

Her voice should come out of **her** recordings. If it comes out male, you converted with the wrong
model selected — check the *Inferencing voice* dropdown.

---

## 5 · Put it into Sonora

| Field | What to put there |
|---|---|
| **MODEL (.PTH)** | `assets/weights/sonara_female_...e_...s.pth` |
| **INDEX** | leave **blank** (Sonora matches it by name) |
| **BASE VOICE** | **Sreymom** — a female base matches her pitch; the base voice only supplies pronunciation |
| **PITCH** | **0** to start. If she sounds deeper/lighter than she really is, try ±1…±3. Never ±12 unless you want the octave effect |
| **CONVERT** | *Khmer lines only* |
| | press **⟳ Test clone ▶** |

**Check the pitch line under the panel.** With a female model it should read something like:

```
base voice 231 Hz (female range) → clone ~190–250 Hz (female range).
```

If it says *"clone ≈114 Hz (male range) … about an octave lower"*, the wrong model is loaded (or the
index belongs to the other model) — that line is diagnostic, send it to me if it looks impossible.

---

## 6 · Using both voices

You keep both models side by side; nothing is overwritten:

```
assets\weights\Sonaro-kh.pth              your voice (male)      -> MODEL field when you narrate
assets\weights\sonara_female_...s.pth     her voice (female)     -> MODEL field when she narrates
```

Switch the **MODEL** field between them, press **⟳ Test clone ▶**, and continue. If you want them
alternating in one episode, produce the chapter twice — once per model — and cut them together; the
studio converts one voice per job.

---

## Troubleshooting (grown-up version)

| Symptom | Cause | Fix |
|---|---|---|
| Sounds like the **female base voice**, not her | index missing, or crossed genders in your head — check the pitch line | copy her `.index` to `assets\indices\`; raise index rate to 0.8 |
| Comes out **male** | wrong MODEL loaded (still `Sonaro-kh.pth`) | put the female `.pth` in the MODEL field |
| **Muffled** / behind a door | too few epochs, or noisy recordings | train to 200+; re-run `menu 13` with `y` (denoise) |
| **Warbly / metallic** | too many epochs or clipped audio | use an earlier checkpoint (epoch 100/150) |
| **Breathy clicks** between words | protect too low | protect **0.5** |
| Single words swallowed | carrier pronunciation, not the clone | note the sentence and I fix the Khmer text pass |

**Time budget:** recording 1–2 h (or reuse her existing audio) · dataset 5 min · training 1–3 h ·
index 1 min. All free, no Colab, no subscription.
