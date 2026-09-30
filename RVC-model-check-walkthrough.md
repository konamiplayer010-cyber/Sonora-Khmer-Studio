# Menu 3 — "Check my RVC model", screen by screen

**What this is for:** before any batch run, prove which `.pth` file is your voice clone.
Your package is not allowed to guess it, and it will not touch your index file. This
walkthrough shows exactly what appears on screen and what to do at each step.

**Two rules this tool follows (your production spec):**

1. **The `.pth` is discovered, never guessed.** Menu 3 reads every candidate and tells
   you what each file really is (a voice model or a training checkpoint).
2. **The index is never modified, renamed or replaced.** Menu 3 only *reads*.
   Preflight checks the exact path from `config.json` and **stops** if it is missing.

Nothing in menu 3 writes to your RVC folder.

---

## Step 1 — start it

Double-click **`START.bat`** → press **`3`** → Enter. It takes a few seconds and
prints a report. Nothing is written to your RVC folder.

---

## Step 1b — read the first three lines

```
python : C:\...\python.exe                  <- which python ran the check
check  : full content check (torch 2.4.0)    <- it can look INSIDE the .pth files
config : E:\...\assets\weights\Sonaro-kh.pth   <- what your config uses
```

If it says **"name and size only"**, that python has no torch, so it can only report
names and sizes (`[?]` instead of `[USABLE]`). Run **menu 6** (Find my RVC python) once,
then menu 3 again, to get the stronger check.

The menu-3 launcher hunts for your RVC python itself, in this order: the `rvc_python`
line in `pipeline/config.json` → `venv` / `.venv` under your RVC folder → the scan in
menu 6 (it checks that a candidate really has torch before reporting it).

## Step 2 — the possible outcomes

### Outcome A — everything is right ✅

```
==================================================================
RVC model check
==================================================================

[USABLE] E:\Audio Books\History\TH\RVC20260718Nvidia\RVC20260718Nvidia\assets\weights\Sonaro-kh.pth
            84.3 MB — true RVC voice model (small model). extra keys: config, f0, version

------------------------------------------------------------------
USE ONE OF THESE (set it as the model):
   E:\...\assets\weights\Sonaro-kh.pth

In AI_Agent/config.json the equivalent relative form is:
   "model_file": "assets/weights/Sonaro-kh.pth"
```

**What it means:** that file is a real extracted voice model (small model) — exactly what
RVC inference needs. The last line shows the value your config already uses. **Nothing to
change.** Go to Step 4.

*(On your PC the size will be somewhere around 55–120 MB. The example above is from a
test fixture, which is why the number is small.)*

---

### Outcome B — only training checkpoints exist ⚠️

```
[NOT A VOICE MODEL] E:\...\logs\Sonaro-kh\D_233333.pth
            0.0 MB — training checkpoint (state_dict wrapper) — extract the small model
[NOT A VOICE MODEL] E:\...\logs\Sonaro-kh\G_233333.pth
            0.0 MB — raw training checkpoint (generator weights) — extract the small model

------------------------------------------------------------------
NO USABLE VOICE MODEL FOUND.

What you have is the training workspace. G_*.pth / D_*.pth are
training checkpoints — inference cannot use them directly.

Fix (2 minutes, inside RVC-WebUI):
  1. Open your RVC-WebUI.
  2. Go to the checkpoint/ckpt-processing tab (it also holds
     'model fusion'; in some builds it is called ckpt处理 /
     'Model processing').
  3. Set the checkpoint path to your newest training checkpoint,
     e.g. logs/Sonaro-kh/G_233333.pth
  4. Set model name: Sonaro-kh     version: v2     sample rate: 40k
  5. Run 'Extract small model'.
  6. Save it as  assets/weights/Sonaro-kh.pth
  7. Run this script again — it should say [USABLE], then press
     Test clone in Sonora (or run run_all.bat).
```

**What it means:** the folder holds the *training* files, not the small model inference
uses. Follow the 7 steps inside RVC-WebUI. **If you are unsure which tab or button is
which, take a screenshot of the RVC-WebUI tabs and send it to me — I will point at it
exactly. I will not guess at button names.**

---

### Outcome C — several voice models found ✅ (this is normal)

Real installs hold several voices (other projects, older versions). The report now
**puts the one your config uses first** and says so:

```
python : C:\...\python.exe
check  : full content check (torch 2.4.0)

config : E:\...\assets\weights\Sonaro-kh.pth

[USABLE] E:\...\assets\weights\Sonaro-kh.pth
            54.9 MB — true RVC voice model (small model). extra keys: config, f0, version, sr, info

[NOT A VOICE MODEL] 32 training checkpoint(s) (G_*.pth / D_*.pth) — 19.6 GB.
            Inference never uses them; they matter only if you extract another
            small model (newest: G_2295.pth). Nothing to do for a normal run.

------------------------------------------------------------------
YOUR CONFIG ALREADY POINTS AT THIS ONE — nothing to change:
   E:\...\assets\weights\Sonaro-kh.pth
   "model_file": "assets/weights/Sonaro-kh.pth"

4 other voice model(s) are installed too (not used):
   guanguanV1.pth
   keruanV1.pth
   kikiV1.pth
   youzhanv2-xi.pth
```

Training checkpoints are summarised as one line instead of dozens, so the screen
stays readable.

### Outcome C-old — if the config's model is missing ⚠️

```
[USABLE] E:\...\assets\weights\Sonaro-kh.pth
            84.3 MB — true RVC voice model (small model). extra keys: config, f0, version
[USABLE] E:\...\assets\weights\Sonaro-kh_v2.pth
            61.1 MB — true RVC voice model (small model). extra keys: config, version

------------------------------------------------------------------
USE ONE OF THESE (set it as the model):
   E:\...\assets\weights\Sonaro-kh.pth
   E:\...\assets\weights\Sonaro-kh_v2.pth
```

**What it means:** both are real voice models. The tool lists them but will not choose
for you. Your `config.json` currently expects **`assets/weights/Sonaro-kh.pth`** — if one
of the listed files has that exact name, that is the one. If neither does, **send me the
list** and I will set the correct name in the config (never the other way round: the
file is never renamed).

---

## Step 3 — if the file name does not match the config

If your config expects `Sonaro-kh.pth` but the real file is named differently, preflight
reports it like this:

```
[FAIL]   C. RVC model: configured model not found:
         E:\...\assets\weights\Sonaro-kh.pth
       tip: run  python check_model.py  to see every .pth in your
       RVC folder and which one is the real voice model.
```

That is the tool refusing to guess — exactly as intended. Run menu 3, read the real name,
and either tell me or edit one line in `pipeline/config.json`:

```json
"model_file": "assets/weights/<the-name-check-model-showed>.pth"
```

---

## Step 4 — the index (never touched)

Preflight verifies the exact index path from your config:

```
[OK]   B. RVC index: E:\...\assets\indices\Sonaro-kh_added_IVF248_Flat_nprobe_1_Sonaro-kh_v2.index
```

If that file is missing, the tool **stops and refuses to continue**:

```
  item:         RVC index (.index)
  required:     exact path from your RVC-WebUI Feature index path field
  index file not found: E:\...\Sonaro-kh_added_IVF248_Flat_nprobe_1_Sonaro-kh_v2.index
  Expected location: <rvc_root>\assets\indices\...
  Required information: the exact .index path from your RVC-WebUI
  (Feature index path field). Not creating a replacement.
```

**Read that last line again: "Not creating a replacement."** Your index is never
regenerated, renamed or substituted. If it is missing, send me the message and we find
it — nothing gets rebuilt automatically.

---

## Step 5 — confirm the whole picture (30 seconds)

Menu 3 answers "which `.pth`". Preflight answers "is everything else ready too". Run it
any time:

```
cd pipeline
python 00_preflight.py
```

A ready machine looks like:

```
[OK]   A. RVC root: E:\Audio Books\History\TH\RVC20260718Nvidia\RVC20260718Nvidia
[OK]   B. RVC index: E:\...\Sonaro-kh_added_IVF248_Flat_nprobe_1_Sonaro-kh_v2.index
[OK]   C. RVC model: E:\...\assets\weights\Sonaro-kh.pth  (84 MB)
[OK]   D2. RVC python: <your RVC venv python>
[OK]   E. Khmer TTS engines: edge -> mmsft -> mms -> gtts   voice: km-KH-SreymomNeural
[OK]   F. Narration style: Audiobook — one TTS call per sentence (intensity 15-55, pace 0.95-1.06x)
PRE-FLIGHT: PASSED — configuration is valid. Ready to process.
```

Any `[FAIL]` line prints the exact item, expected path and what is required. Copy those
lines to me and I will read them with you.

---

## What each file in your RVC folder actually is

| file / folder | what it is | usable by the pipeline? |
|---|---|---|
| `assets/weights/*.pth` (55–120 MB) | **extracted small model** — your voice | ✅ this is the one |
| `weights/*.pth` | same thing in older RVC layouts | ✅ |
| `logs/<name>/G_*.pth`, `D_*.pth` | **training checkpoints** (generator / discriminator) | ❌ extract the small model first |
| `logs/<name>/0_gt_wavs`, `1_16k_wavs`, `2a_f0`, `3_feature768` | preprocessing / training data | ❌ not models |
| `assets/indices/*.index` | feature index used during conversion | ✅ read-only, exact path from config |
| `*_test.wav` (e.g. `Sonaro-kh_test.wav`) | your quality reference recording | ⚪ reference only — never fed to RVC as a model |

---

## What to send me

Copy the **whole window** (select the text in the console → right-click → Mark/Copy) or
just take a photo of the screen. Either is fine. What I need is:

- the first line (**which python it used**),
- every `[USABLE]` / `[NOT A VOICE MODEL]` / `[FAIL]` line,
- and, if it stopped on the index, that `Required information:` line.

## After this is green — the one-small-test rule

Per your production spec, we do **not** start a full book straight away. The next step is
one small test: a short text (one paragraph) through stages 00 → 03, so you can *listen*
to the converted output and confirm the clone sounds right before any batch work. That
test is also what proves the pitch/index-rate/protect settings (rmvpe, 0, 0.75, 0.33) —
they are fixed in the config, and the test is where we confirm them on your machine.

**Run it now: menu 11 (TEST THE CLONE).** It runs one paragraph through the real
pipeline — 00 preflight, 01 text, 02 voice, 03 **your clone**, 04 merge — inside
`pipeline/clone_test/`, so your book, its chunks and its log are never touched (chunk
names such as `chapter_01/chunk_0001` are what the tool uses to decide "already done";
a separate folder means a test can never be mistaken for book audio).

It prints the exact file to listen to, and what to listen for:

* does it sound like your voice, at speech tempo (not slowed down)?
* any crackle, buzz, metallic edge or robotic wobble?
* are Khmer numbers/dates read as words rather than symbol by symbol?

Green light → run the book: **menu 2**. Not right → send me the whole window; nothing
was lost, nothing was overwritten.

### Two pythons, and why the test now shows both

Your machine has two Python installations doing two different jobs:

| job | python | why |
|---|---|---|
| text (01) and voice (02) | the pipeline python (`Python314`) | it has edge-tts and the Khmer text tools |
| **the clone (03), and the test conversion inside preflight** | `...\RVC20260718Nvidia\runtime\python.exe` | RVC, torch and `soundfile` live *only* in RVC's own environment |

The earlier `G FAILED … No module named 'soundfile'` happened because the *pipeline*
python tried to import RVC — the wrong way round, and not a problem with your model,
your index or your settings. Preflight now splits the test into two lines and runs each
half with the right python:

```
[OK]   G1. test sentence (TTS): ...\clone_test\logs\preflight_test_tts.wav
       [rvc-engine] python=...\runtime\python.exe  torch=...  cuda=...
       [rvc-engine] using RVC API: infer.vc.modules
       [rvc-engine] model loaded via get_vc('Sonaro-kh.pth')
       [rvc-engine] OK 4.0s 40000 Hz f0=rmvpe -> ...\logs\preflight_test.wav
[OK]   G2. clone conversion (RVC): ...\clone_test\logs\preflight_test.wav  (4.0s, 40000 Hz)
```

Both `[OK]` lines are the goal. `D2. RVC python` also says
**"(the RVC stages run with this one, not with the python you started)"** — that is the
line that tells you the right environment was found.

If **G2** fails, the report prints which python it used and what that python is missing.
What the message means:

| G2 says | what it means | what to do |
|---|---|---|
| `it is missing 'common'` | that python does not add the script's own folder to its list of import places — common with RVC "integrated pack" runtimes | fixed in this build (the engine and stage 03 now add it themselves); if you still see it, you are running an older copy |
| `RVC's python is missing the package 'x'` | that python can start RVC, but RVC needs package `x` for the conversion and it is not installed there | run **menu 12** (Fix the RVC python) — it installs exactly that package, into that python, and re-checks. Then menu 11 again. |
| `it is missing 'soundfile'` or `'torch'` | that python cannot import RVC's own libraries — wrong python, or an incomplete RVC environment | run **menu 6**, put the python it names into `rvc_python` in `pipeline\config.json`, run menu 11 again |
| `RVC's own configuration could not be read inside …` | `rvc_root` is not the RVC-WebUI folder (no `RVC.py`, `infer/`, `configs/config.json`) | compare with items A and D1 in the same report |
| `cannot import RVC's VC class` | `rvc_root` is not the RVC-WebUI folder (the one holding `RVC.py` and `infer/`) | compare with items A and D1 in the same report |

The same protection covers **stage 03 of a real book run** (menu 2): it is launched with the
RVC python too, and it now finds the pipeline's files by itself.

### One more thing that is not about your files

RVC is written to run *from inside its own folder* — it reads `configs/config.json`,
`i18n/` and `assets/` relative to the working directory. The pipeline runs from
`pipeline\`, so the clone stage now steps into the RVC folder for every part that touches
RVC (and steps back out). Before this, a perfectly good RVC install could refuse to load
while sitting in another folder — that is why some failures looked like "cannot import
RVC's VC class" even though nothing was wrong with your setup.

Every failure now also writes the RVC python's own words to
`pipeline\clone_test\logs\preflight_rvc_error.txt` (or `logs\` during a book run), so you
can send one small file instead of the whole window.
