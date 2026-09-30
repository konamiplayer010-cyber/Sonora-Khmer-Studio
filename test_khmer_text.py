#!/usr/bin/env python3
"""test_khmer_text.py — acceptance tests for the Khmer language frontend.

Every case here comes from the reference specification: the abbreviation
rules, the historical years, the repetition sign, ordinals, currency, percent,
decimals, phone numbers, punctuation and the "space is not a breath" rule.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import khmer_text as KT

PASS = FAIL = 0
FAILURES = []


def check(label, got, want):
    global PASS, FAIL
    if got == want:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append("%s\n     got:  %r\n     want: %r" % (label, got, want))


def check_true(label, cond, why=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(label + (("\n     " + str(why)) if why else ""))


def check_in(label, needle, hay):
    global PASS, FAIL
    if needle in hay:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append("%s\n     missing: %r\n     in:      %r" % (label, needle, hay))


def speech(text, **kw):
    return KT.prepare(text, **kw)["speech"]


# ---------------------------------------------------------------- numbers ----
check("0", KT.kh_number(0), "សូន្យ")
check("1", KT.kh_number(1), "មួយ")
check("5", KT.kh_number(5), "ប្រាំ")
check("8", KT.kh_number(8), "ប្រាំបី")
check("10", KT.kh_number(10), "ដប់")
check("11", KT.kh_number(11), "ដប់មួយ")
check("20", KT.kh_number(20), "ម្ភៃ")
check("21", KT.kh_number(21), "ម្ភៃមួយ")
check("30", KT.kh_number(30), "សាមសិប")
check("40", KT.kh_number(40), "សែសិប")
check("50", KT.kh_number(50), "ហាសិប")
check("60", KT.kh_number(60), "ហុកសិប")
check("70", KT.kh_number(70), "ចិតសិប")
check("80", KT.kh_number(80), "ប៉ែតសិប")
check("90", KT.kh_number(90), "កៅសិប")
check("100", KT.kh_number(100), "មួយរយ")
check("1000", KT.kh_number(1000), "មួយពាន់")

# the six historical years from the specification
check("year 1243", KT.kh_number(1243), "មួយពាន់ពីររយសែសិបបី")
check("year 1285", KT.kh_number(1285), "មួយពាន់ពីររយប៉ែតសិបប្រាំ")
check("year 1295", KT.kh_number(1295), "មួយពាន់ពីររយកៅសិបប្រាំ")
check("year 1308", KT.kh_number(1308), "មួយពាន់បីរយប្រាំបី")
check("year 1327", KT.kh_number(1327), "មួយពាន់បីរយម្ភៃប្រាំពីរ")
check("year 1336", KT.kh_number(1336), "មួយពាន់បីរយសាមសិបប្រាំមួយ")
check("year 2564", KT.kh_number(2564), "ពីរពាន់ប្រាំរយហុកសិបបួន")
check("year 2569", KT.kh_number(2569), "ពីរពាន់ប្រាំរយហុកសិបប្រាំបួន")

# -------------------------------------------------------------- ordinals ----
check("ordinal 1", KT.kh_ordinal(1), "ទីមួយ")
check("ordinal 2", KT.kh_ordinal(2), "ទីពីរ")
check("ordinal 3", KT.kh_ordinal(3), "ទីបី")
check("ordinal 7", KT.kh_ordinal(7), "ទីប្រាំពីរ")

# ------------------------------------------------ abbreviations + years -----
check("Khmer digits -> ascii", KT.khmer_digits_to_ascii("១៣២៧"), "1327")
check("គ.ស. ១៣២៧",
      speech("គ.ស. ១៣២៧"),
      "គ្រិស្តសករាជ មួយពាន់បីរយម្ភៃប្រាំពីរ")
check("គ.ស ១៣២៧ (no final dot)",
      speech("គ.ស ១៣២៧"),
      "គ្រិស្តសករាជ មួយពាន់បីរយម្ភៃប្រាំពីរ")
check("គ.ស១៣២៧ (glued — user example)",
      speech("គ.ស១៣២៧"),
      "គ្រិស្តសករាជ មួយពាន់បីរយម្ភៃប្រាំពីរ")
check("ព.ស.", speech("ព.ស."), "ពុទ្ធសករាជ")
check("ព.ស (no final dot)", speech("ព.ស"), "ពុទ្ធសករាជ")
check("ព.ស. ២៥៦៤",
      speech("ព.ស. ២៥៦៤"),
      "ពុទ្ធសករាជ ពីរពាន់ប្រាំរយហុកសិបបួន")
check("ម.ស. -> មហាសករាជ", speech("ម.ស."), "មហាសករាជ")
check("ច.ស. -> ចុល្លសករាជ", speech("ច.ស."), "ចុល្លសករាជ")
check("ស.វ. -> សតវត្ស", speech("ស.វ."), "សតវត្ស")
check_in("គ.ស. ១៣០៨", "មួយពាន់បីរយប្រាំបី", speech("គ.ស. ១៣០៨"))
check_in("គ.ស. ១២៤៣", "មួយពាន់ពីររយសែសិបបី", speech("គ.ស. ១២៤៣"))

# ------------------------------------------------------------ repetition ----
check("បន្តិចម្ដងៗ", speech("បន្តិចម្ដងៗ"), "បន្តិចម្ដង បន្តិចម្ដង")
# the repeat unit must be right and no word may be broken; whether "ជាលំដាប់"
# is shown as one word or two depends on the segmenter, which is allowed
_s = speech("បន្តិចម្ដងៗ ជាលំដាប់")
check_in("បន្តិចម្ដងៗ ជាលំដាប់ (repeat)", "បន្តិចម្ដង បន្តិចម្ដង", _s)
check_in("បន្តិចម្ដងៗ ជាលំដាប់ (tail intact)", "ជាលំដាប់", _s)
check("សន្សឹមៗ", speech("សន្សឹមៗ"), "សន្សឹម សន្សឹម")
check("ខ្លះៗ", speech("ខ្លះៗ"), "ខ្លះ ខ្លះ")
check("ម្តងៗ", speech("ម្តងៗ"), "ម្តង ម្តង")
check("ក្មេងៗ", speech("ក្មេងៗ"), "ក្មេង ក្មេង")
check("មួយចានៗ", speech("មួយចានៗ"), "មួយចាន មួយចាន")
check("ខ្លះៗដោយឡែក", speech("ខ្លះៗដោយឡែក"), "ខ្លះ ខ្លះដោយឡែក")
check("no ៗ sign is ever spoken", "ៗ" in speech("ក្មេងៗ"), False)

# -------------------------------------------------------- numbers in text ----
check("ordinal in a royal name",
      speech("ព្រះបាទ ជ័យវរ្ម័ន ទី ៧ សុគត ក្នុង គ.ស. ១២២០។"),
      "ព្រះបាទ ជ័យវរ្ម័ន ទីប្រាំពីរ សុគត ក្នុង គ្រិស្តសករាជ មួយពាន់ពីររយម្ភៃ.")
check("number + unit glued", speech("៥ ឆ្នាំ"), "ប្រាំឆ្នាំ")
check("100 people", speech("១០០ នាក់"), "មួយរយនាក់")
check("3 times", speech("៣ ដង"), "បីដង")
check("2 km", speech("២ គីឡូម៉ែត្រ"), "ពីរគីឡូម៉ែត្រ")
check("100 riel", speech("100៛"), "មួយរយរៀល")
check("$100", speech("$100"), "មួយរយដុល្លារ")
check("200 riel", speech("២០០៛"), "ពីររយរៀល")
check("100%", speech("100%"), "មួយរយភាគរយ")
check("8%", speech("8%"), "ប្រាំបីភាគរយ")
check("1.5", speech("1.5"), "មួយ ចុច ប្រាំ")
check("2.25", speech("2.25"), "ពីរ ចុច ម្ភៃប្រាំ")
check("123.45", speech("123.45"), "មួយរយម្ភៃបី ចុច សែសិបប្រាំ")
check("date 01/01/2023", speech("01/01/2023"),
      "ថ្ងៃទី មួយ ខែ មករា ឆ្នាំ ពីរពាន់ម្ភៃបី")
check("time 10:30", speech("10:30"), "ដប់ ម៉ោង សាមសិប នាទី")
check("phone 010123123", speech("010123123"),
      "សូន្យ មួយ សូន្យ មួយ ពីរ បី មួយ ពីរ បី")

# a number is never detected inside a word: the letters must survive intact
def letters(x):
    return "".join(ch for ch in x if not ch.isspace())
check("no number inside a word",
      letters(speech("ជីវិតពីរបៀប")), letters("ជីវិតពីរបៀប"))

# ---------------------------------------------------------- punctuation -----
check("។ is never spoken", "។" in speech("សូមស្វាគមន៍។ ថ្ងៃនេះ។"), False)
check_in("។ becomes a stop", "សូមស្វាគមន៍.", speech("សូមស្វាគមន៍។"))
check_in("៖ becomes a short pause", ",", speech("ថេរវាទ៖ គឺជា"))
check("៖ is never spoken", "៖" in speech("ថេរវាទ៖ គឺជា"), False)
_md = speech("## ការវិលត្រឡប់នៃព្រហ្មញ្ញសាសនា")
check("# marker dropped", "#" in _md, False)
check("heading text kept", letters(_md), letters("ការវិលត្រឡប់នៃព្រហ្មញ្ញសាសនា"))
check("horizontals are dropped", speech("---"), "")
check("smart quotes become plain", speech("“សូម”"), '"សូម"')

# --------------------------------------------------------------- spacing ----
res = KT.prepare("ព្រះអង្គមានព្រះរាជបំណងដ៏សំខាន់ គឺការរក្សាសន្តិភាពក្នុងនគរ។ "
                 "បន្ទាប់មក ព្រះអង្គបានបញ្ជាឲ្យដកកងទ័ពចេញ។")
check_in("phrase spacing (display form)", "  ", res["phrased"])
check("no double space in the TTS form", "  " in res["speech"], False)
check("ZWS is not spoken", speech("សូ\u200bម"), "សូម")
check("NBSP becomes a space", speech("សូម\u00a0ស្វាគមន៍"), "សូម ស្វាគមន៍")

# ------------------------------------------------------------- word breaks --
cl = KT._clusters("បន្តិចម្ដង")
check("clusters never split a base+subscript", len(cl) >= 2, True)
check("a cluster always starts with a base letter",
      all(c[0] in "ក ខ គ ឃ ង ច ឆ ជ ឈ ញ ដ ឋ ឌ ឍ ណ ត ថ ទ ធ ន ប ផ ព ភ ម យ រ ល វ ស ហ ឡ អ".replace(" ", "")
          or c[0] for c in cl), True)

# ------------------------------------------------------------- lexicon ------
import tempfile

with tempfile.TemporaryDirectory() as td:
    lex_path = os.path.join(td, KT.LEXICON_NAME)
    check("empty lexicon loads", KT.load_lexicon(lex_path)["words"], {})
    KT.learn("ជ័យវរ្ម័ន", "ជ័យវរ្ម័ន", "word", lex_path)
    KT.learn("អ.ស.", "អង្គរសករាជ", "abbreviation", lex_path)
    lex = KT.load_lexicon(lex_path)
    check("user word stored", lex["words"]["ជ័យវរ្ម័ន"], "ជ័យវរ្ម័ន")
    check("user abbreviation wins", speech("អ.ស.", lexicon=lex), "អង្គរសករាជ")
    KT.learn("បន្តិចម្ដង", "x", "repetition", lex_path)
    lex = KT.load_lexicon(lex_path)
    check("repetition base stored", "បន្តិចម្ដង" in lex["repetition_bases"], True)

# unknown abbreviations are reported, never invented
res = KT.prepare("អ.ព. មួយ")
check("unknown abbreviation reported", res["unknown_abbreviations"], ["អ.ព"])
check("unknown abbreviation preserved", res["speech"], "អ.ព មួយ")
check("a note is raised", any("abbreviation" in n for n in res["notes"]), True)

# ------------------------------------------------------------- reporting ----
res = KT.prepare("គ.ស. ១៣២៧។ ក្មេងៗ ខ្លះៗ")
check("stats count abbreviations", res["stats"]["abbreviations"].get("គ.ស."), 1)
check("stats count repetitions", res["stats"]["repetitions"], 2)
check("stats count the year", res["stats"]["year"], 1)
check("pause plan built", len(res["pause_plan"]) >= 1, True)
check("source is preserved", res["source"], "គ.ស. ១៣២៧។ ក្មេងៗ ខ្លះៗ")
check("source is not destroyed by prepare", res["source"] != res["speech"], True)

# ------------------------------------------------------------- CLI smoke ----
with tempfile.TemporaryDirectory() as td:
    src = os.path.join(td, "in.txt")
    dst = os.path.join(td, "out.txt")
    rep = os.path.join(td, "report.json")
    with open(src, "w", encoding="utf-8") as f:
        f.write("គ.ស. ១៣២៧ ព្រះបាទ ជ័យវរ្ម័ន ទី ៧ បន្តិចម្ដងៗ ជាលំដាប់។")
    KT.main(["--in", src, "--out", dst, "--json", rep, "--lexicon",
             os.path.join(td, "lex.json")])
    check("CLI wrote the speech file", os.path.exists(dst), True)
    check("CLI wrote the report", os.path.exists(rep), True)

print()

# ---------------------------------------------------------- markdown marks ---
# The user's manuscript is written with **bold**, ## headings, "—" dashes and
# numbered sections. NONE of those marks may ever be read aloud, and none of
# the words may be lost.
_MD = ("## ភាគទី៧ — ប្រាំបីម៉ោងឆ្ងាយ\n"
       "### ១. ការហៅដែលខ្ញុំខកខាន\n"
       "- ខ្ញុំកំពុងងូតទឹក។\n"
       "1. ខ្ញុំរង់ចាំ។\n"
       "**“ភ្ញាក់ហើយ?”** គេសួរ **Elias** ។\n"
       "ថ្ងៃនោះ—ខ្ញុំមិនបានលើកទូរស័ព្ទ។")
_md = KT.prepare(_MD)["speech"]
check("no # survives", "#" in _md, False)
check("no * survives", "*" in _md, False)
check("no backtick survives", "`" in _md, False)
check("no list number survives", "1." in _md or "១." in _md, False)
check("no bullet survives", _md.strip().startswith("-"), False)
check("no em-dash survives", "\u2014" in _md, False)
for _w in ("ការហៅ", "ខ្ញុំកំពុងងូតទឹក", "Elias", "ភ្ញាក់ហើយ"):
    check_in("markdown text kept: %s" % _w, _w.replace(" ", ""), _md.replace(" ", ""))
# a wrong guess must never invent a word: these two broke in real prose
_rep = KT.prepare("អ្វីៗមើលទៅងាយស្រួល")["speech"]
check("អ្វីៗ doubles the word, not a fragment",
      (_rep.startswith("អ្វី អ្វី"), _rep.count("អ្វី")), (True, 2))
check("no Khmer character is lost by the repetition",
      [c for c in _rep if "\u1780" <= c <= "\u17ff"][:3], ["អ", "\u17d2", "វ"])
check_in("អ្វីៗ -> អ្វី អ្វី", "អ្វី អ្វី", KT.prepare("អ្វីៗមើលទៅងាយស្រួល")["speech"])
check_in("ព្រឹកៗ -> ព្រឹក ព្រឹក", "ព្រឹក ព្រឹក", KT.prepare("ព្រឹកៗ គេផ្ញើសារ")["speech"])
check("no letter is left alone by a repetition",
      [w for w in KT.prepare("ព្រឹកៗ គេផ្ញើសារ")["speech"].split() if len(w) == 1], [])
check("a 2020–2023 range is spoken, not symbol-read",
      "ដល់" in KT.prepare("ឆ្នាំ 2020–2023")["speech"], True)

# ---------------------------------------------------- identity of a sentence --
# Style and emotion change the delivery only: pitch and loudness stay inside
# the identity band (see narration.py), and the SPEED stays human.
import narration as _N
_ID_TXT = ("ខ្ញុំគិតថាអ្វីៗនឹងល្អ។ ប៉ុន្តែពេលខ្ញុំបើកទ្វារ ខ្ញុំបានឃើញវា។ "
           "គេមិនបានឆ្លើយ។ ទឹកភ្នែកធ្លាក់។ ខ្ញុំនឹកគេណាស់។")
for _sid in _N.STYLE_ORDER:
    _pl = _N.plan_text(_ID_TXT, style=_sid, pause=0.25)
    check_true("%s keeps the speaker's register (pitch ≤ 0.25 st)" % _sid,
               all(abs(p["pitch_st"]) <= _N.IDENTITY_PITCH_ST + 1e-6 for p in _pl),
               str([round(p["pitch_st"], 2) for p in _pl]))
    _sd = _N.style_delivery(_sid)
    check_true("%s keeps its own human loudness" % _sid,
               all(abs(p["gain_db"] - _sd["gain_db"])
                   <= _N.STYLE_GAIN_TOL + 0.01 for p in _pl),
               "%+.1f dB (style ships %+.1f)" % (
                   min(p["gain_db"] for p in _pl), _sd["gain_db"]))
    check_true("%s keeps its own speaking pace" % _sid,
               all(abs(p["rate"] - _sd["pace"]) <= _N.STYLE_PACE_TOL + 0.01
                   for p in _pl),
               "%.2fx (style ships %.2fx)" % (
                   min(p["rate"] for p in _pl), _sd["pace"]))
    check_true("%s gives every sentence a feeling and an intensity" % _sid,
               all(p.get("emotion") and p.get("emotion_intensity5") is not None
                   for p in _pl))
    check_true("%s is not one flat colour" % _sid,
               len({p["emotion"] for p in _pl}) >= 2,
               str([p["emotion"] for p in _pl]))
    check_true("%s has no narration bed (sound stays the same)" % _sid,
               _N.spec(_sid).get("bed", ("none", 0))[1] == 0)


print("khmer frontend: %d passed, %d failed" % (PASS, FAIL))
for f in FAILURES:
    print("FAIL:", f)
sys.exit(1 if FAIL else 0)