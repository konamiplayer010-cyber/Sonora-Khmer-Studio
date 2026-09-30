# The whisper is removed — builds 2026-09-30n and 2026-09-30o

## Update — build 2026-09-30o: the sound that was hiding in the pauses

You reported it again after build n: in English, not over the whole file, but
heard again and again — **about 10–15 times in a five-minute read**, in the gaps
between the sentences. That matched a second, quieter source that build n did
not touch, and it is gone now.

**What it was.** The renderer synthesised a soft **inhale** and wrote it into
every few sentence gaps: filtered white noise, shaped with a sine envelope —
"a breath", in the words of the code. Each style asked for one between 16 % and
50 % of its pauses, never closer than 2–4 sentences. Measured on a real English
pair of sentences: **0.22–0.42 s long, ~35 dB under the voice (peak −47 dBFS,
−53 dBFS RMS in the gap on a −16 LUFS master)**. In a five-minute read that is
exactly 10–15 events — the count you reported — and a filtered-noise breath is
not a voice, so what arrives in the pause reads as a whisper.

**Why the earlier checks missed it.** It is short (under half a second), so the
passage rule in the checker — a whisper *passage* is ≥ 0.8 s — never looked at
it; and it is not airy (it is low-mid noise), so the air test would not have
flagged it either. It is heard, not measured by a whisper metric. The checker now
has a **pause audit** for it (§ below).

**What changed.**

| route | before | now |
|---|---|---|
| the studio renderer | wrote `_breath_samples()` into the gap | the gap is exact digital silence |
| the batch renderer (`narration.render_styled`) | same, via `_breath_np()` | same — silence |
| the planner | marked a breath on chance, on strong/emotional lines, on the "breaking" line and in several deliveries | never marks one; `plan()` ends with a guarantee that every item leaves with `breath: False` |
| the delivery layer | `apply_to_plan_item(..., breath=True)` could set the flag | cannot set it any more |
| the synthesisers themselves | produced noise | **return digital silence**, so no stale caller can put the sound back |

**What did NOT change.** The pauses. Each style keeps its own pace, its own
pause lengths, its own softness and its own emphasis — Meditation is still slow
with long gaps, news is still brisk. The intimate delivery is still slower, softer
and closer. Only the noise inside the gaps is gone.

**The shipped clips were rebuilt to match:** the 13 Narration Style demo clips
(`sonora/public/style_demos/`), the one clip that still carried a breath
(`cinematic.mp3`) among them, and the English pack
(`all-13-narration-styles.mp3`) reassembled from them. All 13 now report *pauses
are silent*.

### The pause audit in `pipeline/check_whisper.py`

For every file the checker now also measures the pauses themselves: a sentence
gap is a run ≥ 0.4 s that sits 30 dB below the voice, measured as a true frame
RMS in dBFS, trimmed at both ends so the decay of the last word is never counted.
Anything above **−70 dBFS** inside such a gap is reported with its time and level.

```
pause-with-breath.mp3
  **   1 pause(s) carry noise (a breath-like sound between the sentences):
       0:03.22 for 1.78 s at -53.0 dBFS

pause-now-silent.mp3
  OK   pauses are silent (no noise between the sentences)
```

Calibration, for reference: digital silence measures −120 dBFS or lower, mp3 room
floor about −85 dBFS, the voice engine's own faint mouth noise −63…−59 dBFS, and
the removed breath **−53 dBFS**. The loudest quiet event in the 13 demo clips is
now below −70 dBFS in every one of them.

**What you reported**

> The whisper voice/sound still have in all voice as in Khmer and English
> Language. That whisper is so bad. While the normal voice is reading then
> sometime the whisper hear/come to loud replace the normal voice. So, in this
> step I want you remove all whisper voices from original voice.

You were right, and the cause was exactly what it sounded like.

## What was happening

A "whisper moment" was never a quieter reading. `whisper.py` **built a different
sound**: it measured the shape of the line, then re-synthesised it as a breath
carrying the words (harmonic comb removed, chest weight gone, air above 2.5 kHz
lifted). Wherever that landed mid-narration, the speaker you were listening to
stopped being the speaker you were listening to — and the master chain then
normalised the level, so the airy take arrived **as loud as the sentence it
replaced**. Measured on a real Khmer line:

| take | air (2.5–9 kHz vs the words) | level |
|---|---|---|
| the old whispered take | **−3.52 dB** | −23.8 dBFS |
| the voice reading it | −18.94 dB | −22.0 dBFS |

**15.4 dB airier** than the voice — a different instrument, not a soft one. Hear
the two side by side in **`Whisper-Removed.html`**.

Three routes could whisper a line, and all three are closed:

| route | before | now |
|---|---|---|
| the style spec | cinematic whispered ~1 line in 3, thriller ~3 in 10 | every style's whisper block is `None` |
| the delivery layer | the “Whisper / Intimate” move carried a whisper depth of 0.55, and any intimacy cue in the text (ខ្សឹប, secret, *leaned close*…) selected it | the move still exists as a soft, close, hesitant delivery — **no whisper in it**; nothing marks a line for whispering |
| the renderers | the studio and the batch renderer called the synthesiser on each marked line | neither calls it any more — the line goes to the master untouched |

The engine entry points are inert as well, so nothing can re-enable it by
accident: `depth_for()` returns **0.0** for every style and every item, and
`whisperize()` returns its input **bit-identical**.

The studio UI stopped advertising it too: the style card no longer prints
“a whispered line stays a moment…”, and the frontend test now fails if that
promise, a whisper chip, or the old “14 styles / 56 feelings” wording ever comes
back (the page file is the one most likely to be replaced by an older copy).

## What stays

- The **performance** that was doing the real work: an intimate passage is still
  slower, softer, closer and better spaced (the “Whisper / Intimate” slot is
  still there as a delivery — pause 1.45 s, breath 0.70).
- The voice itself: pitch locked at **0.0 st** in all 13 styles, no formant or
  timbre change anywhere, as it always was.
- Every other feeling, pause and speed rule you asked for.

## How it is checked now

`pipeline/test_whisper.py` was rewritten — it used to prove the whisper worked,
it now proves it is **gone** (24 checks):

- `depth_for()` is 0.0 for every style, and for a fully flagged item;
- `whisperize()` returns the line **bit-identical** at every depth and seed;
- **no planned line in any of the 13 styles is flagged** — 143 lines over four
  texts, including Khmer and English intimacy cues: **0 whispered**;
- `whisper_depth()` is 0.0 across every style × delivery, and no delivery move
  carries a whisper depth;
- no rendered path calls the synthesiser any more (studio + batch);
- the two engine copies are still the same file.

The other suites that assumed a whisper existed were updated to assert its
absence (narration 105, feeling layer 61, Khmer expressive 81), and the
expressive engine's own policy now caps air for **every** style instead of
naming seven that were allowed near-whisper.


## Check your own file — `pipeline/check_whisper.py`

If you still hear a whisper, this turns it into a time stamp. Point it at any
file ("every voice, Khmer and English" — so try the exact export that had it):

```bash
python3 pipeline/check_whisper.py your-episode.wav
```

It prints, for each file, whether a whisper-like passage was found and where:

```
old-whispered.mp3
  3.79 s · voice air -4.72 dB · pitch periodicity 0.23 · 263 breath frame(s)
  **   the WHOLE FILE reads as whispered (air -4.7 dB, pitch periodicity 0.23)

whisper-in-a-normal-read.mp3
  12.08 s · voice air -14.71 dB · pitch periodicity 0.68 · 92 breath frame(s)
  **   #1 0:04.13 - 0:07.93 (3.80 s): air +11.8 dB over the voice, level -14.4 dB, periodicity 0.23
       note: 0:00.41 for 0.34 s is airy (air +9.6 dB, pitch 0.36) — a consonant, not a passage
```

**How it decides.** A whisper has a measurable signature: it is *airy* (2.5–9 kHz
far above the file's own voice), *pitchless* (no autocorrelation period in the
70–400 Hz voice range) and *audible* (above the file's own noise floor —
anchored to the floor, not to the loud voice, because a whispered line measured
14.8 dB below the voice and the first version of this rule walked right past it).
A passage is reported only when it lasts at least **0.8 s** with a mean
periodicity of **0.28** or less, so a hissing consonant is listed as a note
instead of an accusation: a clean take's "s" reads 0.33–0.35 s / 0.35–0.37,
while the whispered line reads 2.9–3.8 s / 0.23–0.24.

Calibrated on real audio, not on taste: **a whispered take reads air −4.7 dB /
periodicity 0.23; every real voice reads −18 to −21 dB / 0.66–0.74** — the 13
style demos, the combined 4-minute pack, and the Khmer sample clips. All 17 are
reported clean. The checker is also part of the test suite (6 checks), together
with a fixture built from your description: a normal read with the whispered take
dropped into the middle, which it locates at 4.13–7.93 s.

If it prints **nothing**, the file has no whisper in it and what you are hearing
is something else (a breath in a pause, the clone's own noise, or a
transcription of a whispered word) — send me the file and I will measure that
instead.

## Files

- `sonora/whisper.py` = `pipeline/whisper.py` — the entry points are inert; the
  old synthesiser is kept, unreferenced, as `_whisperize_removed()` so the A/B
  above can still be produced honestly.
- `sonora/public/whisper_ab/` — the clips from the page: the plain source line,
  the old whispered take of it, the same line read normally, and the whisper
  dropped inside a normal read, and (build o) the same two sentences with the old
  pause breath, with the silence that replaces it, and the breath alone at +30 dB.
  All seven play on the page itself.
- `Whisper-Removed.html` — built by `pipeline/make_whisper_page.py`.
- Build label: the removal shipped in **`2026-09-30o`** (that is the stamp
  above, and it is still what this page describes). Later builds keep it —
  the current one is **`2026-09-30p`** (HD cleanup and damaged input), shown
  top-right of the page next to "Engine online". If the header says `n` or
  earlier, the old files are on your PC — press Ctrl+F5 after installing.
