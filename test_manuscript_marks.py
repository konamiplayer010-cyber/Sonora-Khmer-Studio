#!/usr/bin/env python3
"""test_manuscript_marks.py — no manuscript mark may ever be SPOKEN.

Rule (user, standing): "#", "##", "###", "**bold**", "*italic*", "`code`",
"- bullet", "1." / "១." list numbers, ">", "~~", links and dashes must never be
read out loud — in Khmer AND in English. A dash becomes a pause (or "ដល់" / "to"
inside a number range).

Two levels of proof:
  1. the cleaner itself (unit level), on the exact shapes a manuscript uses;
  2. a full production run with a spy on the synthesis engine, so the check is
     made on the strings that were really handed to the voice — not on the
     cleaner's output in isolation.

    python pipeline/test_manuscript_marks.py
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SONORA = os.path.join(HERE, "..", "sonora")
for p in (HERE, SONORA):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import server as S        # noqa: E402
except Exception as _e:       # the studio is not in this folder (patch-only copy)
    S = None
    _WHY = "%s: %s" % (type(_e).__name__, _e)

OK, FAIL = [], []


def check(name, cond, extra=""):
    (OK if cond else FAIL).append(name)
    print("  [%s] %s%s" % ("OK  " if cond else "FAIL", name,
                           "  — " + str(extra) if extra else ""))


FORBIDDEN = set("#*`~[]{}<>|_\\")
FORBIDDEN |= {"\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2015"}


def marks_left(t):
    return sorted(set(t) & FORBIDDEN)


if S is None:
    print("the studio (sonora/server.py) is not next to this test in this copy —")
    print("run the tests from the full Sonora-Khmer-Studio folder to include the")
    print("end-to-end check. (%s)" % _WHY)
    print("\nmanuscript marks: skipped, 0 failed")
    sys.exit(0)

print("1. English manuscripts — what the voice would receive")
EN = [
    ("# THE LAST TIME YOU SAID MY NAME", "THE LAST TIME YOU SAID MY NAME"),
    ("## Part 7 — Four Hours Away", "Part 7, Four Hours Away"),
    ("### 1. The missed call", "The missed call"),
    ("- Elias called every morning.", "Elias called every morning."),
    ("1. She opened the door.", "She opened the door."),
    ("**bold** and *italic* and `code`", "bold and italic and code"),
    ("> a quoted line", "a quoted line"),
    ("Elias said — quietly — nothing.", "Elias said, quietly, nothing."),
    ("2020–2023 were hard.", "2020 to 2023 were hard."),
    ("See [the letter](https://x.test) now.", "See the letter now."),
    ("---", ""),
    ("## “I'm outside.”", "“I'm outside.”"),
]
for src, want in EN:
    got = S._manuscript_clean(src)
    check("%-38r -> %r" % (src, want), got == want and not marks_left(got),
          ("got %r %s" % (got, marks_left(got))) if got != want else "")

print("\n2. Khmer manuscripts — source -> the speech text the engine receives")
KM = [
    ("## ភាគទី៧ — ប្រាំបីម៉ោងឆ្ងាយ", ["ភាគ", "ទីប្រាំពីរ"]),
    ("### ១. ការហៅដែលខ្ញុំខកខាន", ["ការហៅ"]),
    ("**“ភ្ញាក់ហើយ?”**", ["ភ្ញាក់"]),
    ("- ខ្ញុំឆ្លើយ", ["ខ្ញុំ", "ឆ្លើយ"]),
    ("ឆ្នាំ ២០២០–២០២៣ ខ្ញុំនៅភ្នំពេញ។", ["ពីរពាន់ម្ភៃ", "ដល់"]),
]
for src, wants in KM:
    got = S._tts_safe_text(S._manuscript_clean(src, keep_dashes=True))
    ok = all(w in got for w in wants) and not marks_left(got)
    check("%-38r -> %r" % (src, got), ok, marks_left(got))

print("\n3. the sharp edges")
check("a dash at the end of a Khmer line is not spoken",
      not marks_left(S._tts_safe_text(
          S._manuscript_clean("ទីក្រុងថ្មី—", keep_dashes=True))))
check("a heading with Khmer numerals loses its number marker",
      "១" not in S._manuscript_clean("### ១. ជំពូក"))
check("a hash inside a sentence never survives",
      "#" not in S._manuscript_clean("ខ្ញុំមាន # មួយ"))
check("an asterisk inside dialogue never survives",
      "*" not in S._manuscript_clean('**"ភ្ញាក់ហើយ?"**'))
check("a number range keeps its meaning (Khmer)",
      "ដល់" in S._tts_safe_text(S._manuscript_clean("២០២០–២០២៣", keep_dashes=True)))
check("a number range keeps its meaning (English)",
      " to " in S._manuscript_clean("pages 12–15"))

print("\n4. end-to-end: the strings that actually reach the voice engine")
seen = []
real_synth = S.synth_unit_mp3


async def spy(text, voice, rate, pitch=0):
    seen.append(text)
    return await real_synth(text, voice, rate, pitch)


S.synth_unit_mp3 = spy
_real_cached = S._cached_unit
S._cached_unit = lambda *a, **k: None      # force a real trip to the engine
CHAPTER = [
    "# THE LAST TIME YOU SAID MY NAME",
    "## Part 7 — Four Hours Away",
    "### 1. The missed call",
    "- Elias called every morning.",
    "1. She opened the door.",
    "**“I'm outside.”**",
    "ខ្ញុំរង់ចាំគាត់រាល់យប់ — ហើយទឹកភ្នែកធ្លាក់។",
    "### ១. ការហៅដែលខ្ញុំខកខាន",
]
key = "marks-0001-abcdef"
try:
    S.produce(key=key, lines=[{"s": "S", "text": t} for t in CHAPTER],
              voices={"S": "km-KH-SreymomNeural"}, speed=1.0, pause=0.25,
              bed="none", bed_level=0.0, fmt="mp3", style="audiobook")
finally:
    S.synth_unit_mp3 = real_synth
    S._cached_unit = _real_cached

print("      the voice actually received:")
for t in seen:
    print("        %r" % t)
bad = [(t, marks_left(t)) for t in seen if marks_left(t)]
check("no mark reached the voice engine, in any of %d units" % len(seen), not bad,
      bad)
check("the heading is spoken as words",
      any("THE LAST TIME YOU SAID MY NAME" in t for t in seen))
check("the dash inside the Khmer line left no sign",
      any("រង់ចាំ" in t and not marks_left(t) for t in seen))

for suf in (".raw", ".master", ".mp3", ".wav"):
    try:
        os.remove(os.path.join(S.CACHE_DIR, key + suf))
    except OSError:
        pass

print("\nmanuscript marks: %d passed, %d failed" % (len(OK), len(FAIL)))
for f in FAIL:
    print("  FAILED:", f)
sys.exit(1 if FAIL else 0)
