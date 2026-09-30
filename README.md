# 🎙️ Sonora — Notebook to Podcast

A NotebookLM-style **text → HD voice** studio. Paste any text (notes, document,
book chapter, history, article) and leave with a show — either as a **solo
narration** or a **two-host podcast** — that you can save to your PC.

## Voices
Powered by the same **HD neural voices used by Microsoft Edge "Read Aloud"**
(322 voices, 60+ languages). The studio ships with 14 hand-picked host voices
(Ava, Andrew, Jenny, Guy, Aria, Davis, Jane, Jason, Sonia, Ryan, Natasha,
William, plus Cambodian **Sreymom** (female) and **Piseth** (male)) — each with
a **▶ Try** button. **Browse all voices** opens a **popup over the studio**
(with its own scroll, no page scrolling) where you can search all **322
voices** by name, language, or gender, play any of them, and pick one for Host
A or Host B. No sign-in or key required.

### Reliable generation (three engines)
The voice endpoint occasionally rejects a session ("No audio received", HTTP
403). Every sentence is synthesized through a chain of three independent
engines:

1. `edge-tts` — up to 5 tries with exponential backoff (bails immediately on
   a definitive 403/410 refusal)
2. `tts_fallback.py` — our own WebSocket client (independent DRM token & MUID)
3. Google `gTTS` — a fully different provider (last resort; the finished
   banner tells you if it was needed)

If the whole job still fails (service down for everyone), the server
**retries the job automatically** (20s, then 60s) before reporting an error.
A single line that every engine rejects is **sanitized and re-tried, then
skipped with a short pause** instead of killing the whole job.

### RVC voice clone — your own voice (optional)

If you have trained an RVC voice model (e.g. **Sonaro-kh** in RVC-WebUI),
Sonora can re-voice episodes in *your* voice. Tick **RVC VOICE CLONE** in
the voice card, fill in the paths, press **⟳ Test clone ▶**, then pick
**⭐ Sonara-kh** as a host.

**What you need**

- [RVC-WebUI](https://github.com/RVC-Project/Repository) installed with a
  working Python environment (its `venv`), ideally with a CUDA GPU
- Your trained model, by default expected at
  `RVC-WebUI\assets\weights\Sonaro-kh.pth` (2.3+ builds) or
  `RVC-WebUI\weights\Sonaro-kh.pth` (2.0–2.2 builds)

**Finding your RVC folder**

The **RVC FOLDER** is the root of RVC-WebUI — the folder that contains
`RVC.py`, `infer/` and `assets/` (or `weights/`). Not the folder you unzipped
it into: if your zip extracted `RVC20260718Nvidia\RVC20260718Nvidia`, the
*inner* folder is the RVC folder. Easiest way to see it: open the RVC WebUI
in a browser and copy the address bar — `…/RVC.py`'s folder is the answer.
Or press **🔍 Find RVC folder**: it scans your C:–F: drives (a few seconds to
a minute) and lists every RVC-WebUI it finds with its `.pth` models — click
one and the FOLDER / MODEL / INDEX fields fill themselves.

**Training checkpoints are not voice models.** RVC training writes big
`G_*.pth` / `D_*.pth` files into `logs/<name>/` — inference cannot use
them. You need the **extracted small model** (`assets/weights/<name>.pth`,
~55–120 MB). The 🔍 **Find RVC folder** scan now flags checkpoints it finds
and tells you what to do; Test clone also explains this precisely if you
point MODEL at one. To extract: RVC-WebUI → ckpt-processing tab (it also
holds "model fusion") → pick the newest `G_*.pth` → **extract small
model** → save as `assets/weights/Sonaro-kh.pth`.

**INDEX** can stay **blank** — the worker auto-detects it
(`assets/indices/…` or `logs/…/added_…_v2.index`, the newest matching file).

**RVC PYTHON (only if Test clone says "No module named 'torch'")**

The worker must run on the python that has RVC + torch — the one your
RVC-WebUI runs on. Sonora finds it automatically (a `venv` inside the RVC
folder, a bundled `python.exe`, or any installed python that has torch).
If it still fails, find the right python and paste its full path into the
**RVC PYTHON** field:

1. Open a terminal **inside the RVC folder** and run
   `python -c "import torch; print(torch.__version__)"` — if it prints a
   version, that python is the one; use `where python` (Windows) for its path.
2. Otherwise open the .bat / shortcut you use to start the RVC-WebUI and read
   which `python.exe` it calls.
3. Or look at the window that opens when the WebUI starts — the header or
   first lines show the interpreter path.

**Clean & Clear (optional, on by default)**

Tick **CLEAN & CLEAR** in the output panel and every episode is mastered
before delivery:

```
your mix → denoise → de-ess + tonal tidy-up → gentle level
         → 48 kHz → broadcast loudness master (-16 LUFS, -1 dB true peak)
```

That is the chain commercial voices go through — it is what makes the
difference between "AI TTS" and "studio production". Two engines:

- **ffmpeg chain** (always available): spectral denoise, de-ess, EQ,
  48 kHz, two-pass loudness master.
- **clearvoice** (best, optional): MossFormer2 neural denoise **plus true
  48 kHz super-resolution** — it reconstructs the high frequencies the
  carrier voice never had.

**Don't want to touch a terminal?** Press **⤓ get engine** next to the
CLEAN & CLEAR checkbox. Sonora finds the python that runs your RVC-WebUI,
installs the engine there (progress shows under the checkbox), verifies it,
and switches to it automatically. Nothing is removed, and if the install
fails your episodes still generate normally on the ffmpeg chain.

If the install fails with **"metadata-generation-failed"** and messages about
`numpy`, `meson` and `Running `cl /?` gave WinError 2`: that is pip trying to
**compile numpy 1.x from source** (clearvoice's metadata pins `numpy<2.0`,
your env has numpy 2.x, and Windows has no C compiler). The button already
avoids this by installing with `--no-deps` — clearvoice works fine on numpy 2.
Never "fix" it by downgrading numpy; that is what breaks torch/RVC.

Prefer to do it by hand? Use the same python your RVC-WebUI runs, e.g.
`"<RVC folder>\venv\Scripts\python.exe" -m pip install clearvoice` — or
just run the `install_clean_engine.bat` that ships with the AI_Agent
pipeline, which finds the right python for you.

Sonora reports which engine ran under the checkbox (and in the job status).
If the clean pass hits a problem, the episode is still delivered normally
and the status line says Clean & Clear was skipped — never a dead job.
Your choice is remembered between sessions.

**How it works**

Sonora starts a small worker (`rvc_worker.py`) *inside your RVC
environment*; the worker loads the model **once** and stays resident, so
only the first job pays the ~1-minute model-load. Each line is then:
base TTS voice (the **base voice** you pick — Sreymom is the default) →
RVC conversion → your voice → mixed into the episode. The conversion runs
on 127.0.0.1 only. **Pitch** (semitones) and **index rate** are tunable:
lower index rate = faster + less accent similarity; raise it if the result
doesn't sound like you enough. **Convert** scope: *Khmer lines only*
(recommended — the model was trained on Khmer) or *all lines*.

**Reliability**

- If the worker is down, Sonora **retries the job automatically** (restarting
  the worker) instead of shipping a different voice; converted lines are
  cached, so a resumed job re-converts nothing.
- With a GPU (CUDA + half precision) conversion is roughly 10× faster than
  CPU. The *Test clone* button reports the device it loaded on.

## Run it
**Windows (easiest):** unzip, double-click `start.bat` — it fixes a missing
pip (Python 3.14 quirk) via `ensurepip`, installs everything, and opens the
studio in your browser at http://localhost:8000.

**Manual / any OS:**
```bash
pip install edge-tts imageio-ffmpeg numpy gtts
python3 server.py
# open http://localhost:8000
```
If you get `No module named pip`, run `python -m ensurepip --upgrade` once
first (then re-run the install).

## Features

### HD / Clean Khmer Voice (RVC clone, Khmer only)

Tick **RVC VOICE CLONE** and one more switch drops in at its right: **HD /
CLEAN KHMER VOICE**. One operation, no audio-engineer controls: analyse →
correct only what is actually wrong → check → loudness → true-peak protection →
48 kHz / 24-bit master. Your clone audio is kept next to it
(`<key>.original.wav`), and **Original ▶ / HD Clean ▶** play the before/after
pair. Measurements, thresholds and the Khmer sample matrix: `HD-Cleanup-Khmer.md`.

- **Solo narration** — pick one of **13** narration styles:
  Natural read · Documentary · Movie trailer · Audiobook · News anchor ·
  Explainer · Thriller · Meditation · Narrative Storytelling · Novel Narration ·
  Inner Monologue · Sad Romantic · Emotional Cinematic Storytelling.
  Every card has a ▶ that
  plays that style **describing itself**, and picking a card sets that style's
  dramatic-pause preset — your voice, your speed and your tone stay exactly as
  you set them.
- **Two-host podcast** — pick Host A + Host B, then the conversation comes from:
  - **⚡ Auto dialogue** — hosts alternate through your Notes with natural
    transitions (English, Thai **and Khmer/Cambodian**, auto-detected from
    your text). No key needed.
  - **✨ Smart conversation** — a real back-and-forth written by your LLM
    (any OpenAI-compatible endpoint). Your key stays in your browser.
  - **✍️ Your script** — write `A: …` / `B: …` lines yourself.
- **Studio bed — two sources:**
  - **My music** — *your own audio files* as the bed: upload 1–2h MP3/WAV/
    M4A/OGG/FLAC tracks, **▶ preview** them, and control **music speed
    (0.5–2×)** and **volume**. The track **loops automatically to fit the
    whole episode** (with a 1s crossfade at each wrap, a soft fade-in and
    a 3s fade-out). Tracks are stored next to the server and survive
    restarts.
  - **None.**
  In the queue, every document can use a *different* song (and its own
  speed/volume) — just like the per-document voice.
- **13 narration styles, each doing its own thing.** Every style layers a
  distinct *rhythm* on top of your speed/pause sliders, not just a preset:
  a **rate ramp** across the whole episode (trailer builds slow→punchy,
  thriller tightens, meditation slows into stillness) and
  **punctuation-aware dramatic pauses** (exclamations land harder with an
  extra beat, paragraphs take a real breath, plain dots stay short). Behind
  them sits the **feeling layer** — 52 emotional deliveries (4 per style) that
  change delivery only, never the voice. A whisper is only ever a brief MOMENT
  inside a line (the specification's WHISPER RULE): no style whispers a whole
  narration.
- **Multi-document queue** — add several documents (paste + *＋ Add to
  queue*, or drop/choose *multiple files at once*), and they run **one by
  one in the exact order you added them**. While a document is producing,
  its row shows **where it is in line** (`RUNNING 1/10`), a **live progress
  bar**, and **document word progress** (`715 / 785 words`) right on the row;
  the queue list scrolls inside itself, so the page never grows. Each item
  carries its **own settings**: click the chips on any queue row — the
  picker opens as a **popup over the studio** (it grows to fit its options
  and scrolls inside itself when long; close it with ✓ Done, ✕, Esc, or a
  click outside):
  - **🎙 voice** — the full 322-voice picker (search by name/language/
    *male*/*female*, ▶ preview): e.g. a male voice for one file, a female
    voice for another.
  - **🎚 narration style** — pick any of the 8 styles for that document
    (speed + pauses + bed update to match).
  - **🎵 bed** — the style bed, one of your uploaded music tracks (with its
    own speed + volume), or none.
  Press **🚀 Start queue**, choose the folder to save into, and every
  finished file **saves itself there automatically** (named after its
  title). If your browser can't pick a folder, files fall back to your
  Downloads folder. A job that fails is marked and the queue keeps going.
- **Save to your PC** — **MP3** (96 kbps) or **WAV** (true HD: 24-bit,
  48 kHz, stereo — ~2304 kbps). After generating, **Save file…** triggers a
  straight save to your Downloads folder (or your chosen folder); switching
  MP3↔WAV after the fact converts instantly from cache. (This is the fix for
  the old browser-only build that "couldn't write to E:\ or Desktop" — files
  are now produced on the server and downloaded.)
- Live progress: the banner streams the studio pipeline stage
  (`voice 12/48`, `mixing studio bed…`, `encoding WAV…`) **with percentage
  and word count** (`voice 64/70 · 91% · 7,150 / 7,850 words`).
- Everything is peak-normalized and mixed on a 24 kHz master, then delivered
  at the format's final level (HD WAV = 48 kHz / 24-bit / stereo), so voices
  and beds land at a consistent, broadcast-friendly level.

## Notes
- Text and API key are used only for this session; the key is never stored on
  the server.
- Effectively unlimited length: up to ~8,000,000 characters / 12,000
  narration units per episode (books are fine as a single episode).
- Generated audio is cached 6 hours (individual voice units 24 h), so
  re-plays, format conversions and re-runs of the same text are instant.
- **Khmer (ខ្មែរ)** is prepared before TTS so it sounds professional:
  text is Unicode-NFC-normalized, Khmer digits and numbers are spelled out
  in words (years, phone numbers, decimals), `%` becomes ភាគរយ, `$` becomes
  ដុល្លារ and ៛ / “riel” becomes រៀល, khmercut word segmentation gives the
  voice natural breaks, and sentences split on the Khmer full stop ។.
  If a provider ever returns a truncated clip under rate pressure, the
  server detects it and retries with the next engine instead of speaking a
  fragment. Best Khmer voices: Sreymom (female) / Piseth (male).

## Files
- `server.py` — studio backend (HD TTS, sentence-level pauses, procedural
  studio beds, mixing, encoding, podcast scripting, job status, HD Cleanup)
- `hdclean.py` — the HD / Clean Khmer Voice engine (Adaptive Khmer Voice
  Enhancement); `pipeline/hdclean.py` is the same file for the batch side
- `public/index.html` — the whole Sonora UI (single file, no external assets)
- `public/hd_samples/` — the Khmer before/after sample matrix (see
  `HD-Cleanup-Khmer.md` in the package root)

NARRATION STYLES
================

The studio's style picker carries the **13** styles of the performance
specification (Natural read, Narrative Storytelling, Novel Narration,
Documentary, Movie trailer, Audiobook, News anchor, Explainer, Thriller,
Meditation, Inner Monologue, Sad Romantic, Emotional Cinematic Storytelling).

Selecting one changes the performance, not the label: every sentence gets an
emotion and one of that style's **four emotional deliveries** (52 in all),
intensity, pause length, emphasis and - where the style allows it - a soft
breath. Paragraph endings get a cadence. The engine enforces contrast, so no
style reads every sentence at one level and quiet sentences are guaranteed.
The style itself is fixed and the voice never changes: the feeling layer moves
pauses, emphasis, rhythm and breath only - pitch 0.0 st, loudness 0.0 dB - and
each style has its own pace and its own softness from the `STYLE_DELIVERY`
table, which is what makes the cards sound different from one another
(Emotional Cinematic Storytelling, for instance, reads like a storyteller:
0.99x at 0.0 dB, unhurried and phrase by phrase). A whisper is always a brief
moment inside a line, never a whole narration.

Watch the decisions while it works:

    set SONORA_DEBUG_PERFORMANCE=1
    python server.py

and the console prints the per-sentence plan ("emotion  I= 69 rate=1.06
pitch=-2.2st gain=+0.9dB pause=0.49s breath  ...").

Engine notes: Microsoft edge-tts honours rate + pitch natively (full plan).
The offline VITS voices get pace via time-stretch, plus loudness, pauses and
breaths; a large pitch shift uses a formant shift. Google gTTS gets pace,
loudness, pauses and breaths.

Styles can also be set by name in the API ("style": "Novel Narration") -
spelling variants are accepted.

## The delivery: plain voice, two dials

There is no style menu any more. The studio speaks with the voice you picked,
unmodified — no pitch shift, no loudness change, no pace change — and the whole
delivery is two dials you own:

* **DRAMATIC PAUSES** — how long the silence is after each sentence.
* **NARRATION SPEED** — the speaking rate, applied exactly as you set it.

Markup in your manuscript (`#`, `##`, `**bold**`, bullets, list numbers, links,
dashes) is never spoken: it becomes words and pauses before the voice sees it.
A range like `2020–2023` still reads as a range ("to" / "ដល់").

