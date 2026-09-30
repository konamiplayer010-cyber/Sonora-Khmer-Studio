#!/usr/bin/env python3
"""khmer_text.py — the Khmer language frontend (TTS text preparation).

This is the LANGUAGE layer: it turns written Khmer into speech-ready Khmer.
It does not speak and it does not choose a voice — the prosody/emotion layer
(narration.py) and the TTS engines come after it.

    RAW KHMER
      -> unicode / whitespace cleaning
      -> abbreviation expansion          (គ.ស. -> គ្រិស្តសករាជ)
      -> number classification + reading (year / ordinal / currency / % /
                                          decimal / phone / date / time)
      -> repetition ៗ expansion          (បន្តិចម្ដងៗ -> បន្តិចម្ដង បន្តិចម្ដង)
      -> symbol / punctuation interpretation (។ ៕ ៖ ... are NOT spoken)
      -> word boundary + phrase grouping
      -> pronunciation lexicon (user corrections win over everything)
      -> SPEECH TEXT (+ pause plan, notes, confidence)

Two representations are always kept apart:

    SOURCE  — the author's text, never destroyed
    SPEECH  — what the voice is asked to say

Design rules taken from the reference specification:
  * a space is a WORD boundary, not a breath
  * never break a Khmer orthographic unit (base + subscript + vowel + sign)
  * numbers are read by MEANING, not by digits
  * ៗ is an instruction, never a sound
  * unknown abbreviations are never invented — they are reported
  * every user correction becomes a reusable rule (lexicon)

CLI:
    python khmer_text.py --in script.txt --out speech.txt [--debug]
                         [--json report.json] [--lexicon lexicon.json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
from functools import lru_cache
import sys
import unicodedata

# ---------------------------------------------------------------- constants --

KH_LETTER = "\u1780-\u17d3"          # consonants, vowels, signs (NOT digits/punct)
REPEAT_SIGN = "\u17d7"                # ៗ KHMER SIGN LEK TOO — repetition
_MARK = "\u0001"                     # guards a spoken form from segmentation


def _prot(word: str) -> str:
    """Mark a generated spoken form as ONE unit (never split by the segmenter).

    Inner marks are removed first: nesting them would end the outer guard at
    the first inner mark and let the segmenter back in.
    """
    return _MARK + str(word).replace(_MARK, "") + _MARK
KH_BLOCK = "\u1780-\u17ff"
KH_DIGITS = "០១២៣៤៥៦៧៨៩"
_DIGIT_MAP = {k: str(i) for i, k in enumerate(KH_DIGITS)}

ZERO_WIDTH = "\u200b"                 # ZWSP = invisible segmentation hint
KEEP_INVISIBLE = "\u200c\u200d"       # ZWNJ / ZWJ can be meaningful — keep them

#: One word per line: written form -> spoken form (confidence is always HIGH
#: for this table — these are the documented historical abbreviations).
ABBREVIATIONS = {
    "គ.ស.": "គ្រិស្តសករាជ",
    "គ.ស": "គ្រិស្តសករាជ",
    "ព.ស.": "ពុទ្ធសករាជ",
    "ព.ស": "ពុទ្ធសករាជ",
    "ម.ស.": "មហាសករាជ",
    "ម.ស": "មហាសករាជ",
    "ច.ស.": "ចុល្លសករាជ",
    "ច.ស": "ចុល្លសករាជ",
    "ស.វ.": "សតវត្ស",
    "ស.វ": "សតវត្ស",
    "គ.ក.": "គីឡូក្រាម",
    "គ.ក": "គីឡូក្រាម",
    "គ.ម.": "គីឡូម៉ែត្រ",
    "គ.ម": "គីឡូម៉ែត្រ",
    "ស.ម.": "សង់ទីម៉ែត្រ",
    "ស.ម": "សង់ទីម៉ែត្រ",
    "ល.រ.": "លេខរៀង",
    "ល.រ": "លេខរៀង",
    "ទ.ី.": "ទី",
    "ព.ធ.": "ព្រះធម៌",
    "ព.ធ": "ព្រះធម៌",
}

#: Era / year markers: a number near one of these is a YEAR (cardinal reading,
#: never digit-by-digit).
YEAR_MARKERS = ("គ្រិស្តសករាជ", "ពុទ្ធសករាជ", "មហាសករាជ", "ចុល្លសករាជ",
                "គ.ស", "ព.ស", "ម.ស", "ច.ស", "ឆ្នាំ", "សករាជ")

#: number + unit is ONE semantic group: the space between them disappears so
#: no breath can fall inside it (spec: "៥ ឆ្នាំ -> ប្រាំឆ្នាំ").
UNITS_GLUE = (
    "ឆ្នាំ", "ខែ", "ថ្ងៃ", "ម៉ោង", "នាទី", "វិនាទី", "នាក់", "ដង", "លើក",
    "គ្រឿង", "ក្រុម", "គ្រួសារ", "ភាគរយ", "រៀល", "ដុល្លារ", "បាត", "យន់",
    "គីឡូក្រាម", "គីឡូម៉ែត្រ", "ម៉ែត្រ", "សង់ទីម៉ែត្រ", "លាន", "ពាន់",
    "រយ", "សែន", "ម៉ឺន", "គ.ម", "គ.ក", "ក្រាម", "លីត្រ", "តោន",
)

#: words that begin a new phrase (narrative signposts)
PHRASE_STARTERS = (
    "បន្ទាប់មក", "ក្រោយមក", "ថ្ងៃក្រោយមក", "កាលនោះ", "នៅពេលនោះ",
    "រហូតដល់", "ដូចនេះ", "ដូច្នេះ", "ដូចនេះហើយ", "ផ្ទុយទៅវិញ",
    "ប៉ុន្តែ", "តែ", "ដោយសារតែ", "ដោយសារ", "ចុងក្រោយនេះ", "ហើយ",
    "បន្ទាប់", "ក្នុងពេលនោះ", "ទោះបីជា", "ទោះជាយ៉ាងណា", "សរុបមក",
)

#: royal / religious titles — never separated from what follows
PROTECTED_TITLES = (
    "ព្រះបាទ", "ព្រះមហាក្សត្រ", "ព្រះអង្គ", "ព្រះនាង", "ព្រះរាជបុត្រ",
    "ព្រះរាជវង្ស", "ព្រះរាជសម្បត្តិ", "ព្រះរាជបល្ល័ង្ក", "ព្រះអគ្គមហេសី",
    "ព្រះរាជា", "ស្តេច", "ព្រះសង្ឃ", "ព្រះគ្រូ", "ព្រះពុទ្ធ",
)

#: proper names (Angkor / modern) and state names that must stay in one piece;
#: a segmenter is free to guess, a narration engine is not. Add more through
#: the lexicon: every user rule is protected automatically.
PROTECTED_NAMES = (
    "ជ័យវរ្ម័ន", "ជយវម៌្ម", "សូរ្យវរ្ម័ន", "ឧទយាទិត្យវរ្ម័ន", "ហរិហរាល័យ",
    "ឥន្ទ្រវរ្ម័ន", "យសោវរ្ម័ន", "ព្រហ្មញ្ញ", "អង្គរវត្ត", "អង្គរធំ", "បាយ័ន",
    "ភ្នំពេញ", "សៀមរាប", "បាត់ដំបង", "កំពង់ចាម", "ក្រុងតាខ្មៅ",
    "មេគង្គ", "ទន្លេសាប", "គ្រិស្តសករាជ", "ពុទ្ធសករាជ", "មហាសករាជ",
    "ចុល្លសករាជ", "សតវត្ស", "អាណាចក្រ", "ចក្រភព", "សាសនា",
)

#: known reduplicative bases. `ៗ` repeats the longest of these that ends where
#: the sign sits (so បន្តិចម្ដងៗ repeats បន្តិចម្ដង, not ម្ដង).
REPEAT_BASES = (
    # words that really take ៗ in prose (អ្វីៗ, ព្រឹកៗ, ល្ងាចៗ, ថ្ងៃៗ, ដងៗ …)
    "អ្វី", "ព្រឹក", "ល្ងាច", "ថ្ងៃ", "យប់", "ដង", "ច្រើន", "តិច", "ខ្លះ",
    "គ្នា", "ផ្សេង", "ម្នាក់", "កន្លែង", "ពេល", "សប្តាហ៍", "ខែ", "ឆ្នាំ",
    "បន្តិចម្ដង", "មួយចាន", "ដោយឡែក", "សន្សឹម", "ក្មេង", "ខ្លះ", "ម្តង",
    "ផ្សេង", "ដូច", "យូរ", "តិច", "ច្រើន", "ថ្ងៃ", "ខែ", "ឆ្នាំ", "ដង",
    "នាក់", "គ្រឿង", "ពួក", "ក្រុម", "លើក", "ដប់", "រយ", "ពាន់", "លាន",
    "ធំ", "តូច", "ខ្ពស់", "ទាប", "ជិត", "ឆ្ងាយ", "លឿន", "យឺត", "ស្អាត",
    "ល្អ", "អាក្រក់", "ថ្លៃ", "ចាស់", "ថ្មី", "ស្រួល", "លំបាក", "ខ្លាំង",
)

#: Khmer months (for the date engine)
MONTHS = ("មករា", "កុម្ភៈ", "មីនា", "មេសា", "ឧសភា", "មិថុនា", "កក្កដា",
          "សីហា", "កញ្ញា", "តុលា", "វិច្ឆិកា", "ធ្នូ")

_ONES = {"0": "សូន្យ", "1": "មួយ", "2": "ពីរ", "3": "បី", "4": "បួន",
         "5": "ប្រាំ", "6": "ប្រាំមួយ", "7": "ប្រាំពីរ", "8": "ប្រាំបី",
         "9": "ប្រាំបួន"}
_TENS = {"1": "ដប់", "2": "ម្ភៃ", "3": "សាមសិប", "4": "សែសិប", "5": "ហាសិប",
         "6": "ហុកសិប", "7": "ចិតសិប", "8": "ប៉ែតសិប", "9": "កៅសិប"}

# ------------------------------------------------------------ number engine --


def kh_number(n: int) -> str:
    """An integer as natural spoken Khmer.

        8      -> ប្រាំបី          20  -> ម្ភៃ
        100    -> មួយរយ           1000 -> មួយពាន់
        1327   -> មួយពាន់បីរយម្ភៃប្រាំពីរ
        2569   -> ពីរពាន់ប្រាំរយហុកសិបប្រាំបួន
    """
    try:
        n = int(n)
    except Exception:
        return str(n)
    if n < 0:
        return "ដក " + kh_number(-n)
    if n == 0:
        return _ONES["0"]
    if n >= 10 ** 6:
        head, rest = divmod(n, 10 ** 6)
        return kh_number(head) + "លាន" + (kh_number(rest) if rest else "")
    return _kh_under_million(n)


def _kh_under_million(n: int) -> str:
    if n < 1000:
        return _kh_under_thousand(n)
    parts = []
    for scale, word in ((100000, "សែន"), (10000, "ម៉ឺន"), (1000, "ពាន់")):
        q, n = divmod(n, scale)
        if q:
            parts.append(_kh_under_thousand(q) + word)
    if n:
        parts.append(_kh_under_thousand(n))
    return "".join(parts)


def _kh_under_thousand(n: int) -> str:
    out = []
    hundreds, rest = divmod(n, 100)
    if hundreds:
        out.append(_ONES[str(hundreds)] + "រយ")
    if rest >= 10:
        out.append(_TENS[str(rest // 10)])
        if rest % 10:
            out.append(_ONES[str(rest % 10)])
    elif rest:
        out.append(_ONES[str(rest)])
    return "".join(out) or _ONES["0"]


def kh_digit_by_digit(digits: str) -> str:
    """Phone numbers / codes: digits are spoken one by one."""
    return " ".join(_ONES.get(d, "") for d in digits if d.isdigit())


def kh_decimal(whole: str, frac: str) -> str:
    """1.5 -> មួយ ចុច ប្រាំ    2.25 -> ពីរ ចុច ម្ភៃប្រាំ"""
    return "%s ចុច %s" % (kh_number(whole), kh_number(frac))


#: Khmer ordinals use their own first/second forms.
_ORDINAL_SPECIAL = {"1": "ទីមួយ", "2": "ទីពីរ"}


def kh_ordinal(n) -> str:
    key = str(n)
    if key in _ORDINAL_SPECIAL:
        return _ORDINAL_SPECIAL[key]
    return "ទី" + kh_number(key)


# --------------------------------------------------------------- cleaning ----

_FORMAT_LINE = re.compile(r"^\s*(?:[-=*_#~]{3,}|#{1,6}\s*.*|```.*)\s*$")


def clean_unicode(text: str) -> tuple[str, dict]:
    """NFC + invisible formatting cleanup. Never deletes a Khmer character.

    * ZWSP (U+200B) is a segmentation hint: dropped inside a cluster, turned
      into a word space between words.
    * NBSP / thin spaces / tabs become plain spaces.
    * control characters and BOM disappear; ZWNJ/ZWJ stay (they can carry
      meaning in Khmer).
    * markdown / symbol noise that is never spoken (---, ***, ##, backticks,
      **bold**) is removed.
    * smart quotes become plain quotes: quotation marks are not spoken, but
      their grouping still matters for dialogue.
    """
    stats = {"zwsp": 0, "nbsp": 0, "format_lines": 0, "control": 0, "markdown": 0}
    t = unicodedata.normalize("NFC", text or "")
    stats["zwsp"] = t.count(ZERO_WIDTH)
    t = re.sub(r"(?<=[\u17b4-\u17d3])%s|%s(?=[\u17b4-\u17d3])"
               % (ZERO_WIDTH, ZERO_WIDTH), "", t)
    t = t.replace(ZERO_WIDTH, " ")
    before = t
    t = (t.replace("\u00a0", " ").replace("\u2007", " ").replace("\u202f", " ")
          .replace("\u2009", " ").replace("\u200a", " ").replace("\t", " "))
    stats["nbsp"] = sum(before.count(c) for c in "\u00a0\u2007\u202f\u2009\u200a\t")
    keep = "".join(c for c in t if unicodedata.category(c) != "Cf"
                   or c in KEEP_INVISIBLE)
    stats["control"] = len(t) - len(keep)
    t = keep.replace("\ufeff", "")

    for a, b in (("\u201c", '"'), ("\u201d", '"'), ("\u201e", '"'),
                 ("\u201f", '"'), ("\u00ab", '"'), ("\u00bb", '"'),
                 ("\u2018", "'"), ("\u2019", "'"), ("\u2032", "'")):
        t = t.replace(a, b)

    out_lines = []
    for line in t.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if _FORMAT_LINE.match(line) and not re.search(r"[%s]" % KH_BLOCK, line):
            stats["format_lines"] += 1
            out_lines.append("")
            continue
        line, n1 = re.subn(r"^\s*#{1,6}\s*", "", line)                 # ## heading
        line, n2 = re.subn(r"\s*#{1,6}\s*$", "", line)                 # trailing #
        line, n3 = re.subn(r"(\*\*|__)(.+?)\1", r"\2", line)           # **bold**
        line, n4 = re.subn(r"`([^`]*)`", r"\1", line)                  # `code`
        line, n5 = re.subn(r"^\s*[\u2022\u25cf\u25aa\u2013\u2014\-\*]\s+",
                           "", line)                                   # bullets
        # a numbered list marker ("1. ", "១. ", "12) ") is never read aloud
        line, n6 = re.subn(r"^\s*(?:\d{1,3}|[\u17e0-\u17e9]{1,3})[.)]\s+", "", line)
        stats["markdown"] += n1 + n2 + n3 + n4 + n5 + n6
        out_lines.append(line)
    t = "\n".join(out_lines)
    t = re.sub(r"[ ]{2,}", " ", t)
    # a dash is punctuation, not a word: "5–7" is a range, "ខ្ញុំ—" is a break
    t = re.sub(r"(?<=\d)\s*[\u2013\u2014\u2015]\s*(?=\d)", " ដល់ ", t)
    t = re.sub(r"\s*[\u2013\u2014\u2015]\s*", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip(), stats


def khmer_digits_to_ascii(text: str) -> str:
    return "".join(_DIGIT_MAP.get(c, c) for c in text)


# ----------------------------------------------------------- abbreviations ---

#: an abbreviation is Khmer single letters joined by dots (2-5 parts), with the
#: trailing dot optional, and NOT glued to Khmer letters on either side.
_ABBREV_RE = re.compile(
    r"(?<![.\u17d4-\u17d9])([\u1780-\u17a2](?:\.[\u1780-\u17a2]){1,4}\.?)"
    r"(?![\u1780-\u17a2])")


def expand_abbreviations(text: str, lexicon: dict | None = None) -> tuple[str, dict]:
    """គ.ស. -> គ្រិស្តសករាជ. User entries (lexicon) win over the built-ins.
    Unknown abbreviations are REPORTED, never invented."""
    found, unknown = {}, []
    table = dict(ABBREVIATIONS)
    for k, v in ((lexicon or {}).get("abbreviations") or {}).items():
        table[k] = v

    def repl(m):
        raw = m.group(1)
        bare = raw.rstrip(".").replace(" ", "")
        tail = text[m.end():m.end() + 1]
        for cand in (raw, raw.replace(" ", ""), bare, bare + "."):
            if cand in table:
                found[cand] = found.get(cand, 0) + 1
                # "គ.ស១៣២៧" -> expand AND keep the number a separate word
                return table[cand] + (" " if tail.isdigit() else "")
        if bare not in unknown:
            unknown.append(bare)
        return bare         # preserved on purpose — a human must decide

    t = _ABBREV_RE.sub(repl, text)
    return t, {"abbreviations": found, "unknown_abbreviations": unknown}


# ------------------------------------------------------------- repetition ---


def _clusters(word: str) -> list[str]:
    """Split a Khmer run into orthographic clusters (base + subscript +
    vowels + signs). Never used to insert a pause — only to reason about ៗ."""
    out, cur = [], ""
    for ch in word:
        if "\u1780" <= ch <= "\u17a2" or "\u17a3" <= ch <= "\u17b3":
            if cur:
                out.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def _repeat_base(run: str, lexicon: dict | None) -> tuple[str, str]:
    """What does ៗ repeat? Returns (base, confidence)."""
    bases = list((lexicon or {}).get("repetition_bases") or [])
    for known in sorted(bases + list(REPEAT_BASES), key=len, reverse=True):
        if run.endswith(known):
            return known, "HIGH"
    # the whole run repeats: "ព្រឹកៗ" -> "ព្រឹក ព្រឹក". Guessing a shorter base
    # by slicing inside a cluster is what once turned "អ្វីៗ" into "អ្វី វី";
    # a whole-word repeat is always a real word, a guessed cut often is not.
    # It is reported as low confidence so a human can correct it in the lexicon.
    return run, "LOW"


def expand_repetition(text: str, lexicon: dict | None = None) -> tuple[str, dict]:
    """បន្តិចម្ដងៗ -> បន្តិចម្ដង បន្តិចម្ដង.

    The repeated unit is decided lexically (never "the last character"), the
    sign itself is never spoken, and a second repetition is only ever added
    where the sign exists.
    """
    hits, low = [], []
    sign = REPEAT_SIGN

    def repl(m):
        run, tail = m.group(1), m.group(2)
        base, conf = _repeat_base(run, lexicon)
        hits.append({"run": run, "base": base, "confidence": conf})
        if conf == "LOW":
            low.append({"run": run, "base": base})
        prefix = run[:len(run) - len(base)]
        #  Xៗ  ->  X X          (a space between the two, as the spec shows)
        # a tail glued to the sign ("ខ្លះៗដោយឡែក") belongs to the second copy.
        # Both copies are single spoken forms: the segmenter must not split them.
        return _prot(prefix + base) + " " + _prot(base + tail)

    t = re.sub(r"([%s\u17b4-\u17d3]+)\s*%s([%s\u17b4-\u17d3]*)"
               % (KH_LETTER, sign, KH_LETTER), repl, text)
    t = t.replace(sign, "")        # any orphan sign is dropped, never spoken
    return t, {"repetitions": hits, "low_confidence_repetitions": low}


# ------------------------------------------------------- numbers + symbols ---

_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_TIME_RE = re.compile(r"(?<![\d])(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?(?![%s\d])" % KH_LETTER)
_DATE_DMY = re.compile(r"(?<!\d)(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})(?!\d)")
_DATE_YMD = re.compile(r"(?<!\d)(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})(?!\d)")
_MONEY_DOLLAR = re.compile(r"\$\s*(%s)" % _NUM)
_MONEY_RIEL = re.compile(r"(%s)\s*(?:\u17db|រៀល)" % _NUM)
_PERCENT = re.compile(r"(%s)\s*%%" % _NUM)
_ORDINAL = re.compile(r"ទី\s*(%s)(?![%s])" % (_NUM, KH_LETTER))
_PHONE = re.compile(r"(?<![\d%s])(0\d{7,9})(?![\d%s])" % (KH_LETTER, KH_LETTER))
_PHONE_GROUPED = re.compile(r"(?<![\d%s])(\d{3})[ \-](\d{3})[ \-](\d{3})(?![\d%s])"
                            % (KH_LETTER, KH_LETTER))
_UNIT = re.compile(r"(?<![%s\d])(%s)\s*((?:%s))(?![\u17b4-\u17d3])"
                   % (KH_LETTER, _NUM, "|".join(re.escape(u) for u in UNITS_GLUE)))
_DECIMAL = re.compile(r"(?<![\d.])(\d+)\.(\d+)(?![\d])")
_INTEGER = re.compile(r"(?<![\d.,])(\d{1,15})(?![\d.,])")


def _looks_like_year(text: str, start: int) -> bool:
    """A number right after an era/ឆ្នាំ marker (or +-18 chars back) is a YEAR."""
    back = text[max(0, start - 20):start]
    return any(m in back for m in YEAR_MARKERS)


def verbalize(text: str, lexicon: dict | None = None) -> tuple[str, dict]:
    """Every number is read by MEANING, not by digits."""
    stats = {"time": 0, "date": 0, "currency": 0, "percent": 0, "ordinal": 0,
             "year": 0, "phone": 0, "decimal": 0, "number": 0}
    extra = ((lexicon or {}).get("numbers") or {})
    t = khmer_digits_to_ascii(text)

    def sub(pattern, fn, key, src=t):
        nonlocal t

        def wrapped(m):
            try:
                return fn(m)
            except Exception:
                return m.group(0)
        t2, n = pattern.subn(wrapped, t)
        if n:
            stats[key] = stats.get(key, 0) + n
        t = t2

    # user-pinned readings win: "1327@year" style entries are applied last,
    # as exact-token replacements, so they can never fight the rules below
    def do_time(m):
        h, mi, ap = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower()
        s = "%s ម៉ោង %s នាទី" % (kh_number(h), kh_number(mi))
        if ap == "am":
            s += " ព្រឹក"
        elif ap == "pm":
            s += " ល្ងាច"
        return _prot(s)
    sub(_TIME_RE, do_time, "time")

    def do_date(m):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= mo <= 12):
            return m.group(0)
        return _prot("ថ្ងៃទី %s ខែ %s ឆ្នាំ %s"
                     % (kh_number(d), MONTHS[mo - 1], kh_number(y)))
    sub(_DATE_DMY, do_date, "date")

    def do_ymd(m):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= mo <= 12):
            return m.group(0)
        return _prot("ថ្ងៃទី %s ខែ %s ឆ្នាំ %s"
                     % (kh_number(d), MONTHS[mo - 1], kh_number(y)))
    sub(_DATE_YMD, do_ymd, "date")

    sub(_MONEY_DOLLAR, lambda m: " " + _prot(kh_number(_clean_num(m.group(1))) + "ដុល្លារ"), "currency")
    sub(_MONEY_RIEL, lambda m: " " + _prot(kh_number(_clean_num(m.group(1))) + "រៀល"), "currency")
    sub(_PERCENT, lambda m: " " + _prot(kh_number(_clean_num(m.group(1))) + "ភាគរយ"), "percent")
    sub(_ORDINAL, lambda m: _prot(kh_ordinal(_clean_num(m.group(1)))), "ordinal")
    sub(_PHONE_GROUPED,
        lambda m: " " + _prot(kh_digit_by_digit(m.group(1) + m.group(2) + m.group(3))) + " ",
        "phone")

    def do_phone(m):
        stats["_phone_pending"] = True
        return " " + _prot(kh_digit_by_digit(m.group(1))) + " "
    sub(_PHONE, do_phone, "phone")

    def do_unit(m):
        n = _clean_num(m.group(1))
        return _prot(kh_number(n) + m.group(2))
    sub(_UNIT, do_unit, "unit")

    def do_decimal(m):
        return (_prot(kh_number(_clean_num(m.group(1)))) + " ចុច "
                + _prot(kh_number(_clean_num(m.group(2)))))
    sub(_DECIMAL, do_decimal, "decimal")

    def do_int(m):
        start = m.start(1)
        n = _clean_num(m.group(1))
        if _looks_like_year(t, start) and len(str(n)) == 4:
            stats["year"] += 1
        return _prot(kh_number(n))
    sub(_INTEGER, do_int, "number")

    for written, spoken in extra.items():
        if written in t:
            t = t.replace(written, spoken)
    stats.pop("_phone_pending", None)
    if stats.get("number"):
        pass
    t = re.sub(r"[ ]{2,}", " ", t).strip()
    return t, stats


def _clean_num(s: str) -> int:
    s = (s or "").replace(",", "")
    return int(float(s))


# ------------------------------------------------------------ punctuation ----

#: Khmer punctuation -> speech instructions (never spoken words).
PUNCT_MAP = {
    "\u17d4": ".",     # ។  full sentence stop      -> full pause
    "\u17d5": ".",     # ៕  end of section/text     -> longer pause
    "\u17d6": ",",     # ៖  colon / explanation     -> short explanatory pause
    "\u17d9": ".",     # ៙  khan
    "\u17da": ".",     # ៚  koomuut
}

_PAUSE_LEVEL = {"\u17d4": 4, "\u17d5": 5, "\u17d6": 2, ".": 4, "!": 4, "?": 4,
                ",": 1, "\u2026": 3, "...": 3, "\n": 3}


def interpret_punctuation(text: str) -> tuple[str, dict]:
    """Symbols become instructions. None of them is ever pronounced."""
    marks = []
    t = text
    from_sign = set()
    for kh, plain in PUNCT_MAP.items():
        if kh in t:
            for m in re.finditer(re.escape(kh), t):
                marks.append({"at": m.start(), "sign": kh, "as": plain,
                              "pause_level": _PAUSE_LEVEL[kh]})
                from_sign.add(m.start())
            t = t.replace(kh, plain)      # 1 char -> 1 char, positions hold
    for m in re.finditer(r"[.!?,]|\u2026|\.\.\.", t):
        if m.start() in from_sign:
            continue                      # already planned from the Khmer sign
        marks.append({"at": m.start(), "sign": m.group(0),
                      "as": m.group(0), "pause_level": _PAUSE_LEVEL.get(m.group(0), 1)})
    t = t.replace("\u2026", "...")
    marks.sort(key=lambda d: d["at"])
    return t, {"punctuation": marks}


# ------------------------------------------------------------- phrasing -----

def protect_terms(text: str, terms) -> str:
    """Wrap a spoken form so the segmenter keeps it whole.

    An expansion is ONE pronunciation unit: “គ្រិស្តសករាជ” or a form the user
    taught must never be split back into pieces by the word segmenter.
    """
    terms = sorted({t for t in terms if t and len(t) > 1}, key=len, reverse=True)
    parts = re.split(r"(\u0001[^\u0001]*\u0001)", text)
    for i, part in enumerate(parts):
        if part.startswith(_MARK) and part.endswith(_MARK):
            continue                      # already one unit — leave it alone
        for term in terms:
            if term in part:
                part = part.replace(term, _MARK + term + _MARK)
        parts[i] = part
    return "".join(parts)


def unprotect(text: str) -> str:
    return text.replace(_MARK, "")


_KH_RUN = "[\u1780-\u17ff](?![.][\u1780-\u17a2])"
_TOKEN_RE = re.compile(
    r"(?P<prot>\u0001[^\u0001]*\u0001)"
    r"|(?P<abbr>[\u1780-\u17a2](?:\.[\u1780-\u17a2]){1,4}\.?)"
    r"|(?P<khmer>[\u1780-\u17d3]+)"
    r"|(?P<latin>[A-Za-z0-9]+(?:[\u2019'&-][A-Za-z0-9]+)*)"
    r"|(?P<punct>[.!?,;:\u2026%]+)"
    r"|(?P<other>[^\s])")

#: punctuation clings to the word before it — a stop is never preceded by a space
_ATTACH_LEFT = set(".,!?;:%\u2026)]}\"'")
_ATTACH_RIGHT = set("([{\u201c\u2018\"")


def tokenize(text: str) -> list[str]:
    """Word tokens for phrase grouping.

    Khmer runs are segmented with khmercut when it is installed; without it a
    run stays ONE token, because a guessed break inside a word is worse than no
    break at all. Abbreviations (គ.ស.) and punctuation keep their own tokens so
    the joiner can attach them correctly.
    """
    toks = []
    for m in _TOKEN_RE.finditer(text):
        kind, val = m.lastgroup, m.group(0)
        if kind == "khmer":
            toks.extend(_segment_run(val))
        else:
            toks.append(val)   # incl. protected terms: one indivisible token
    return toks


@lru_cache(maxsize=1)
def number_words() -> frozenset:
    """Every word the number engine can produce (used to keep numbers whole)."""
    words = set()
    for i in range(0, 111):
        words.update(kh_number(i).split())
    for big in (1000, 1200, 10123, 250000, 1327, 2023, 1000000, 2500000):
        words.update(kh_number(big).split())
    words.update(kh_digit_by_digit("0123456789").split())
    # the engine writes a number as ONE word, so the pieces never appear in the
    # generated set above — they are added by hand
    words.update({"ចុច", "ទី", "ទីមួយ", "ទីពីរ", "ម៉ោង", "នាទី", "ថ្ងៃទី",
                  "រយ", "ពាន់", "ម៉ឺន", "សែន", "លាន", "សិប"})
    words.discard("")
    return frozenset(words)


def _segment_run(run: str) -> list[str]:
    """A Khmer run -> word tokens.

    khmercut when it is installed, else the run stays ONE token (a guessed
    break inside a word is worse than no break). A run that is nothing but
    spoken number words — “មួយពាន់បីរយម្ភៃប្រាំពីរ”, “ទីប្រាំពីរ” — is kept
    whole, so preparing an already-prepared line changes nothing.
    """
    words = []
    try:
        import khmercut
        words = [w for w in khmercut.tokenize(run) if w.strip()]
    except Exception:
        return [run]
    if not words:
        return [run]
    core = words[1:] if words[0] in ("ទី", "ទីប្រាំ", "ទីប្រាំពីរ") else words
    nw = number_words()
    if core and all(w in nw for w in core):
        return [run]
    return words


def join_tokens(tokens) -> str:
    """Tokens -> text. Punctuation attaches left, quotes hug their content."""
    parts = []
    for tok in tokens:
        if not tok:
            continue
        if parts and tok[0] in _ATTACH_LEFT:
            parts[-1] += tok
        elif parts and parts[-1] and parts[-1][-1] in _ATTACH_RIGHT:
            parts[-1] += tok
        else:
            parts.append(tok)
    return " ".join(parts)


def phrase_group(text: str, max_words: int = 8, max_chars: int = 44) -> tuple[str, dict]:
    """Group words into natural phrases.

    ONE space = word boundary, TWO spaces = phrase boundary, blank line =
    paragraph boundary. A word boundary is NOT a breath: the pauses come from
    the punctuation plan, never from the spaces.
    """
    lines_out, phrases = [], []
    for raw_line in text.split("\n"):
        if raw_line.strip() == "":
            lines_out.append("")
            continue
        toks = tokenize(raw_line)
        cur = []
        for tok in toks:
            if tok in PHRASE_STARTERS and cur:
                phrases.append(cur)
                cur = []
            cur.append(tok)
            words = sum(1 for x in cur if x and x[0] not in _ATTACH_LEFT)
            chars = sum(len(x) for x in cur)
            if words >= max_words or chars >= max_chars:
                phrases.append(cur)
                cur = []
        if cur:
            phrases.append(cur)
        lines_out.append(("\u0000", len(toks)))

    joined = [join_tokens(ph) for ph in phrases]
    # a phrase may never *start* with punctuation ("បាយ័ន" + "." = "បាយ័ន.")
    merged: list[str] = []
    for g in joined:
        if merged and g and g[0] in _ATTACH_LEFT:
            merged[-1] = merged[-1] + g
        else:
            merged.append(g)
    joined = merged
    phrased_lines, cursor = [], 0
    for item in lines_out:
        if item == "":
            phrased_lines.append("")
            continue
        need = item[1]
        buf, used = [], 0
        while cursor < len(joined) and used < need:
            g = joined[cursor]
            buf.append(g)
            used += len(tokenize(g))
            cursor += 1
        phrased_lines.append("  ".join(buf))
    phrased = re.sub(r"\n{3,}", "\n\n", "\n".join(phrased_lines).strip())
    word_count = sum(1 for x in re.split(r"\s+", phrased)
                     if x and x[0] not in _ATTACH_LEFT)
    return phrased, {"phrases": joined, "phrase_count": len(joined),
                     "words": word_count}


# --------------------------------------------------------------- lexicon -----

LEXICON_NAME = "khmer_lexicon.json"


def default_lexicon_path(*bases) -> str:
    for b in bases:
        if b and os.path.isdir(b):
            return os.path.join(b, LEXICON_NAME)
    return LEXICON_NAME


def load_lexicon(path: str | None = None) -> dict:
    """The user's own rules. Loaded empty when the file does not exist yet."""
    lex = {"abbreviations": {}, "words": {}, "numbers": {}, "repetition_bases": []}
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k in lex:
                    if isinstance(data.get(k), type(lex[k])):
                        lex[k] = data[k]
        except Exception:
            pass
    return lex


def save_lexicon(lex: dict, path: str) -> bool:
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(lex, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def learn(term: str, spoken: str, kind: str = "word", path: str | None = None) -> dict:
    """A user correction becomes a reusable rule (highest priority).

    kind: word | abbreviation | number | repetition
    """
    lex = load_lexicon(path)
    term, spoken = (term or "").strip(), (spoken or "").strip()
    if not term or not spoken:
        return lex
    if kind == "abbreviation":
        lex["abbreviations"][term] = spoken
    elif kind == "number":
        lex["numbers"][term] = spoken
    elif kind == "repetition":
        if term not in lex["repetition_bases"]:
            lex["repetition_bases"].append(term)
    else:
        lex["words"][term] = spoken
    if path:
        save_lexicon(lex, path)
    return lex


def apply_words(text: str, lexicon: dict | None) -> tuple[str, int]:
    """User word corrections: exact-text replacement, longest term first."""
    words = ((lexicon or {}).get("words") or {})
    n = 0
    for written in sorted(words, key=len, reverse=True):
        if written and written in text:
            n += text.count(written)
            text = text.replace(written, words[written])
    return text, n


def prepare(text: str, lexicon: dict | None = None, phrase: bool = True) -> dict:
    """The whole frontend: SOURCE -> SPEECH.

    Returns a dict with both forms, the stats, the notes, the pause plan and
    the confidence list. Nothing here speaks; nothing here destroys SOURCE.
    """
    source = text or ""
    notes: list[str] = []
    t, clean_stats = clean_unicode(source)
    t, abbr = expand_abbreviations(t, lexicon)
    t, num_stats = verbalize(t, lexicon)
    t, rep = expand_repetition(t, lexicon)
    t, words_hits = apply_words(t, lexicon)
    t, punct = interpret_punctuation(t)
    if not phrase:
        t = re.sub(r"\s+", " ", t)
        return {"source": source, "speech": t.strip(), "phrased": t.strip(),
                "stats": {**clean_stats, **num_stats, **{"word_fixes": words_hits}},
                "notes": notes, "pause_plan": punct["punctuation"],
                "repetitions": rep["repetitions"],
                "unknown_abbreviations": abbr["unknown_abbreviations"],
                "low_confidence": rep["low_confidence_repetitions"]}

    # expansions and user-taught forms are protected from re-segmentation
    protect = [w for w in PROTECTED_TITLES + PROTECTED_NAMES if w in t]
    protect += [v for v in ABBREVIATIONS.values() if v in t]
    protect += [k for k in ((lexicon or {}).get("words") or {}) if k in t]
    protect += [v for v in ((lexicon or {}).get("words") or {}).values() if v in t]
    protect += [v for v in ((lexicon or {}).get("abbreviations") or {}).values()
                if v in t]
    t = protect_terms(t, protect)
    phrased, ph = phrase_group(t)
    phrased = unprotect(phrased)
    speech = unprotect(re.sub(r"\s+", " ", phrased).strip())

    if abbr["unknown_abbreviations"]:
        notes.append("abbreviation not in the dictionary, left unchanged "
                     "(add it to the lexicon): "
                     + ", ".join(abbr["unknown_abbreviations"]))
    for low in rep["low_confidence_repetitions"]:
        notes.append("ៗ after “%s” was expanded as “%s” — low confidence, please "
                     "confirm" % (low["run"], low["base"]))
    if words_hits:
        notes.append("%d user correction(s) applied from the lexicon" % words_hits)

    return {
        "source": source,
        "speech": speech,
        "phrased": phrased,
        "stats": {**clean_stats, **num_stats, "words": ph["words"],
                  "phrases": ph["phrase_count"], "word_fixes": words_hits,
                  "abbreviations": abbr["abbreviations"],
                  "repetitions": len(rep["repetitions"])},
        "notes": notes,
        "pause_plan": punct["punctuation"],
        "repetitions": rep["repetitions"],
        "unknown_abbreviations": abbr["unknown_abbreviations"],
        "low_confidence": rep["low_confidence_repetitions"],
    }


def normalize(text: str, lexicon: dict | None = None) -> tuple[str, dict]:
    """One-shot convenience used by the studio and the batch pipeline."""
    res = prepare(text, lexicon=lexicon)
    return res["speech"], res["stats"]


# ------------------------------------------------------------------- CLI ------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Khmer TTS text frontend")
    ap.add_argument("--in", dest="src", help="input text file (UTF-8)")
    ap.add_argument("--out", dest="dst", help="output speech file")
    ap.add_argument("--text", help="text passed directly instead of --in")
    ap.add_argument("--json", dest="report", help="write the full report JSON")
    ap.add_argument("--lexicon", help="path to khmer_lexicon.json")
    ap.add_argument("--learn", nargs=2, metavar=("TERM", "SPOKEN"),
                    help="store a correction")
    ap.add_argument("--learn-kind", default="word",
                    choices=["word", "abbreviation", "number", "repetition"])
    ap.add_argument("--debug", action="store_true",
                    help="print SOURCE / SPEECH / notes")
    args = ap.parse_args(argv)

    lex_path = args.lexicon or default_lexicon_path(os.path.dirname(__file__))
    if args.learn:
        learn(args.learn[0], args.learn[1], args.learn_kind, lex_path)
        print("saved:", args.learn[0], "->", args.learn[1])

    text = args.text
    if text is None and args.src:
        with open(args.src, "r", encoding="utf-8") as f:
            text = f.read()
    if text is None:
        text = sys.stdin.read()
    res = prepare(text, lexicon=load_lexicon(lex_path))

    if args.dst:
        with open(args.dst, "w", encoding="utf-8") as f:
            f.write(res["phrased"] + "\n")
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in res.items() if k != "source"},
                      f, ensure_ascii=False, indent=2)
    if args.debug or not args.dst:
        print("SOURCE:\n" + res["source"][:1500])
        print("\nSPEECH:\n" + res["speech"][:1500])
        print("\nSTATS:", json.dumps(res["stats"], ensure_ascii=False))
        for n in res["notes"]:
            print("NOTE:", n)
        print("PAUSES:", json.dumps(res["pause_plan"][:12], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
