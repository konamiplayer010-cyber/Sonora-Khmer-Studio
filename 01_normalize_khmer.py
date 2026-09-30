#!/usr/bin/env python3
"""01_normalize_khmer.py — read the original script (untouched), normalize
it for TTS, split into chapters, and write numbered chunk text files.

Outputs (spec sections 10, 11, 28):
    normalized/chapter_XX.txt                  full normalized chapter
    normalized/chapter_XX_chunk_NNNN.txt       1-4 sentences each
    normalized/changes_report.txt              what was changed, per chapter

The original input file is never modified.
"""
import sys

import common as C

KHMER_STOP = C.KHMER_STOP


def main():
    cfg = C.load_config()
    in_path = C.ROOT / (cfg.get("input_file") or "input/history_kh.txt")
    if not in_path.exists():
        print("[MISSING]\n  item:         input script\n"
              f"  expected:     {in_path}\n"
              "  required:     your Khmer history script (.txt, UTF-8)")
        sys.exit(1)
    original = in_path.read_text(encoding="utf-8").strip()
    if not original:
        print("[FAIL]   input script is empty")
        sys.exit(1)

    log = C.load_log()
    log["meta"]["input"] = str(in_path)
    log["meta"]["project"] = cfg.get("project")

    chapters = C.parse_chapters(original)
    ndir = C.sub_dir("normalized")
    report = ["normalization report", "=" * 40,
              f"input: {in_path.name}", ""]
    ask = []          # abbreviations a human must decide on
    total_chunks = 0

    for num, title, body in chapters:
        ch = C.chapter_id(num)
        norm, stats, fnotes, fextra = C.normalize_khmer_frontend(body)
        (ndir / f"{ch}.txt").write_text(norm + "\n", encoding="utf-8")

        sentences = C.split_sentences(norm)
        chunks = C.group_chunks(sentences)
        for i, c in enumerate(chunks, 1):
            p = C.chunk_text_path(num, i)
            p.write_text(c + "\n", encoding="utf-8")
        total_chunks += len(chunks)

        # register chunks in the log (fresh only — resume keeps old entries)
        for i in range(1, len(chunks) + 1):
            cid = C.chunk_id(num, i)
            log["chunks"].setdefault(cid, {})

        label = f"chapter {num}" + (f" — {title}" if title else "")
        report.append(f"{label}: {len(body)} chars -> {len(norm)} chars, "
                      f"{len(sentences)} sentences, {len(chunks)} chunks")
        rule_bits = [f"{k} x{v}" for k, v in stats.items()
                     if v and k != "segmented"]
        if stats.get("segmented"):
            rule_bits.append("word-segmented (khmercut)")
        report.append("    rules: " + (", ".join(rule_bits) or "none needed"))
        for n in fnotes:
            report.append("    ! " + n)
        for ab in fextra.get("unknown_abbreviations", []):
            report.append("    ! abbreviation not in the dictionary, left "
                          "unchanged: " + ab)
            ask.append(ab)
        for low in fextra.get("low_confidence", []):
            report.append("    ! low confidence ស: “%s” read as “%s” — confirm it"
                          % (low.get("run"), low.get("base")))
        report.append("")

    # drop log entries for chunk files that no longer exist (script changed)
    stale = [k for k in list(log["chunks"].keys())
             if not C.chunk_text_path(
                 int(k.split("/")[0].split("_")[1]),
                 int(k.split("/")[1].split("_")[1])).exists()]
    for k in stale:
        del log["chunks"][k]

    if ask:
        report += ["", "ASK BEFORE RECORDING (these were never guessed):",
                   "  " + ", ".join(sorted(set(ask))), ""]
    (ndir / "changes_report.txt").write_text("\n".join(report), encoding="utf-8")
    C.save_log(log)

    print(f"[OK]   chapters: {len(chapters)}")
    print(f"[OK]   chunks:   {total_chunks}")
    print(f"[OK]   normalized text -> {ndir}/")
    print(f"[OK]   change report -> {ndir / 'changes_report.txt'}")
    print("STAGE 1 COMPLETE (normalization + chunking)")


if __name__ == "__main__":
    main()
