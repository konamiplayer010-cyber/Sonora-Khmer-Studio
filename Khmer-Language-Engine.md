# Khmer Language Engine — what this update adds

This update turns the Khmer side of Sonora from *"one big prompt that asks the
model to be careful"* into a real frontend: four layers, each with its own code
file, its own tests and its own rules. The TTS model is now the **last** layer
and it never has to guess anything.

```
SOURCE TEXT
   │
   │  1  KHMER LANGUAGE .............. khmer_text.py
   │        NFC, invisible characters, markdown, quotes
   │        abbreviation/pronunciation dictionary
   │        numbers read by MEANING (year / ordinal / money / % / decimal / phone / date / time)
   │        ៗ  expansion,  ។ ៕ ៖ ,  pause levels, word & phrase spacing
   │        the user's own rules (khmer_lexicon.json) — they outrank everything
   │
   │  2  PRONUNCIATION ............... khmer_text.py + lexicon
   │        គ.ស.  → គ្រិស្តសករាជ          ៨% → ប្រាំបីភាគរយ
   │        010123123 → digits one by one   1.5 → មួយ ចុច ប្រាំ
   │        unknown abbreviations are REPORTED, never invented
   │
   │  3  PROSODY / EMOTION .......... khmer_expressive.py
   │        52 emotions × 13 style profiles
   │        pitch · energy · rate/duration · pause · rhythm · emphasis · voice quality
   │        emotion changes INSIDE a sentence, emotional arc per piece
   │        restraint guards: no flat narration, no constant drama,
   │        no whisper everywhere, no constant breath, no singing
   │
   ▼
  4  TTS ENGINE  (edge / gTTS / local mms · then Sonaro-kh RVC · then Clean & Clear)
```

SOURCE text is never destroyed — both forms are kept (SOURCE vs SPEECH).

---

## 1. The language layer — `pipeline/khmer_text.py`

### Abbreviations (pronunciation dictionary)

| written | spoken | notes |
|---|---|---|
| `គ.ស.` / `គ.ស` | គ្រិស្តសករាជ | also glued: `គ.ស១៣២៧` → `គ្រិស្តសករាជ មួយពាន់បីរយម្ភៃប្រាំពីរ` |
| `ព.ស.` | ពុទ្ធសករាជ | |
| `ម.ស.` | មហាសករាជ | |
| `ច.ស.` | ចុល្លសករាជ | |
| `ស.វ.` | សតវត្ស | |
| `គ.ក` `គ.ម` `ស.ម` `ល.រ` `ទ.ី` `ព.ធ` | គីឡូក្រាម / គីឡូម៉ែត្រ / សង់ទីម៉ែត្រ / លេខរៀង / ទី / ព្រះធម៌ | with **and** without the trailing dot |

An abbreviation that is **not** in the dictionary is left alone and reported
(`unknown_abbreviations` in the API, `ASK BEFORE RECORDING` in the batch
report). Nothing is ever invented.

### Numbers are read by MEANING

| written | spoken | rule |
|---|---|---|
| `១៣២៧` after `គ.ស.` | មួយពាន់បីរយម្ភៃប្រាំពីរ | year — never digit-by-digit |
| `ទី ៧` | ទីប្រាំពីរ | ordinal (ទី) |
| `100៛` | មួយរយរៀល | riel |
| `$100` | មួយរយដុល្លារ | dollar |
| `8%` | ប្រាំបីភាគរយ | percent |
| `1.5` | មួយ ចុច ប្រាំ | decimal |
| `01/01/2023` | ថ្ងៃទី មួយ ខែ មករា ឆ្នាំ ពីរពាន់ម្ភៃបី | date |
| `10:30` | ដប់ ម៉ោង សាមសិប នាទី | time |
| `010123123` | digits one by one | phone |
| `២ គីឡូម៉ែត្រ` | ពីរគីឡូម៉ែត្រ | number + unit glue |

A digit inside a word is never a number. Every spoken form is marked as **one
pronunciation unit**, so the word segmenter can never break
`មួយពាន់បីរយម្ភៃប្រាំពីរ` into pieces again — preparing an already-prepared
line changes nothing (idempotent).

### `ៗ` — the repetition sign

`បន្តិចម្ដងៗ` → `បន្តិចម្ដង បន្តិចម្ដង`
`ខ្លះៗដោយឡែក` → `ខ្លះ ខ្លះដោយឡែក`
`មួយចានៗ` → `មួយចាន មួយចាន`

The repeated unit is decided lexically (longest known base), never "the last
character". The sign itself is **never spoken**, a second repetition is only
ever added where the sign exists, and a base that is not in the known list is
expanded but flagged `low_confidence` for confirmation.

### Punctuation = pause instructions

`។` full pause (level 4) · `៕` end of section (5) · `៖` short explanatory pause (2) ·
`,` micro pause (1) · `…` (3). No symbol is ever pronounced. The pause plan is
returned as data (`pause_plan`) so the prosody layer — not the TTS model —
decides the silence.

### Spacing

**one space = word boundary** (not a breath) · **two spaces = phrase boundary** ·
**blank line = paragraph**. Phrasing is rebuilt on those rules, and punctuation
is never left floating in front of a space.

---

## 2. The performance layer — `pipeline/khmer_expressive.py`

* **52 emotions** in 7 families (calm, tender, solemn, mystery, bright,
  informative, driven, sad, fear, anger, awe) — each one a full channel vector:
  pitch, pitch span, rate, energy, pause multiplier, breath, tension, drive.
* **13 style profiles** — bound to the shipped style names. The emotion gives
  the colour; the style sets the limits it may move inside (its own intensity
  band, pace band, volume band, pitch band).
* **Emotion changes inside a sentence.** A contrast word (`ប៉ុន្តែ តែ ផ្ទុយទៅវិញ
  ដូច្នេះ ស្រាប់តែ …`) starts a new clause with its own emotion; a quoted line is
  performed as **dialogue**, not as narration.
* **Emotional arc** for the whole piece: opening → build → turn → **climax**
  (chosen, never simply the last sentence) → release.
* **Restraint guards (they are enforced in code, not asked for in a prompt):**
  * never flat — a minimum intensity spread inside the band,
  * no constant drama — high-intensity units capped (25 %, 34 % for cinematic/trailer/thriller),
  * whisper only in the styles allowed to whisper, and never everywhere,
  * breath never on three sentences in a row,
  * no singing, no mumble — pitch ±4 st, rate 0.75–1.30,
  * emotion variety — one colour for a whole piece is rejected.

Every unit of the plan carries: `emotion, intensity, pitch_st, pitch_span, rate,
energy_db, rhythm, pauses{before,after,clause,level}, quality{breath,tension,projection},
emphasis[], clauses[], phase`.

---

## 3. The learning loop (user corrections become rules)

A correction is never a per-sentence patch: it is stored as a reusable rule in
`pipeline/khmer_lexicon.json` and it **outranks every built-in table**.

```bash
# from a terminal, next to the studio
python pipeline/khmer_text.py --learn "អ.ព" "អង្គពិសេស" --learn-kind abbreviation
python pipeline/khmer_text.py --learn "ជ័យវរ្ម័ន" "ជ័យៈវរ្ម័ន"       # kind defaults to word
python pipeline/khmer_text.py --text "អ.ព បានមកដល់។" --json          # see the plan + notes
```

Rule kinds: `word` (exact text → spoken form), `abbreviation`, `number`,
`repetition`. Every rule is protected from re-segmentation, and the studio
clears its text cache the moment a rule is learned.

---

## 4. API (the live studio, port 8000)

| method | path | what it does |
|---|---|---|
| POST | `/api/khmer/prepare` | `{text}` → `speech`, `phrased`, `stats`, `notes`, `pause_plan`, `unknown_abbreviations`, `low_confidence` |
| POST | `/api/khmer/perform` | `{text, style, intensity?, speed?, pause?}` → the full performance plan **plus** `sheet` (readable) and `summary` |
| POST | `/api/khmer/learn` | `{term, spoken, kind}` → stores a reusable rule, returns the new lexicon counts |
| GET | `/api/khmer/lexicon` | the stored rules + where the file lives |
| GET | `/api/khmer/emotions` | the 52 emotions by family and the default emotion of every style |

The studio's own text path (`_tts_safe_text`) now runs layers 1+2 for every
Khmer line, so jobs, the helper checks and the reader all see the same SPEECH
text. The batch pipeline (`01_normalize_khmer.py`) calls the same frontend and
writes its findings into `normalized/changes_report.txt`, including the
`ASK BEFORE RECORDING` list.

---

## 5. Tests — run them yourself

```bash
cd pipeline
python test_khmer_text.py        # 97 checks: numbers, abbreviations, ៗ, spacing, lexicon, CLI
python test_khmer_expressive.py  # 73 checks: emotions, styles, inside-sentence change, arc, guards
python test_narration.py         # 86 checks: the 13 narration styles (unchanged, still green)
```

All three suites pass (256 checks).

---

## 6. Files in this update

| file | what changed |
|---|---|
| `pipeline/khmer_text.py` | **new** — the Khmer language + pronunciation layer (normalizer, dictionary, number engine, `ៗ`, pause levels, phrasing, lexicon, CLI) |
| `pipeline/khmer_expressive.py` | **new** — the prosody/emotion performance layer (52 emotions, 13 profiles, arcs, guards, CLI) |
| `pipeline/test_khmer_text.py` | **new** — 97 acceptance checks |
| `pipeline/test_khmer_expressive.py` | **new** — 73 acceptance checks |
| `pipeline/khmer_lexicon.json` | **new** — your correction rules (starts empty: nothing invented) |
| `pipeline/common.py` | `normalize_khmer_frontend()` + the frontend loader; the old rules stay as fallback |
| `pipeline/01_normalize_khmer.py` | uses the frontend, reports unknown abbreviations / low-confidence `ៗ` |
| `sonora/server.py` | text path runs the frontend; **the frontend now runs BEFORE the sentence splitter** (so `គ.ស. ១៣២៧` can no longer be torn into `គ.` + `ស.` + a bare number); a failed unit is retried on its own with backoff before a burst is blamed; 5 new API endpoints; build `2026-09-29a` |

Nothing was removed: the previous simple rule set is still the fallback if the
new module is ever missing, and the 14 narration styles, the clone chain and
Clean & Clear are untouched.
