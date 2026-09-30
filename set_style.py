#!/usr/bin/env python3
"""set_style.py — choose the narration style for the batch pipeline (menu 10).

Writes `narration_style` into config.json. Empty means a plain read: one TTS
call per chunk, fastest, no per-sentence performance.

    python set_style.py            interactive (double-click friendly)
    python set_style.py --list     just show the styles
    python set_style.py --set news set it and exit
    python set_style.py --set ""   back to a plain read
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try:
    import narration as NAR
except Exception as e:                                   # pragma: no cover
    print("[FAIL] narration.py is missing next to this script:", e)
    sys.exit(1)

CFG = HERE / "config.json"


def load_cfg():
    try:
        with open(CFG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_style(style):
    cfg = load_cfg()
    cfg["narration_style"] = style or ""
    with open(CFG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    return cfg


def show_table(current):
    print("=" * 70)
    print("NARRATION STYLE — how the audiobook is performed")
    print("=" * 70)
    print(f"current: {current or '(plain read — fastest, no per-sentence performance)'}\n")
    for i, s in enumerate(NAR.style_list(), 1):
        mark = "*" if s["id"] == current else " "
        print(f"{mark} {i:2d}. {s['label']}")
        print(f"      {s['definition']}")
        print(f"      best for: {s['best_for']}")
        sp = NAR.STYLE_SPECS[s["id"]]
        print(f"      intensity {sp['intensity'][0]}-{sp['intensity'][1]} · "
              f"pace {sp['pace'][0]:.2f}-{sp['pace'][1]:.2f}x · "
              f"bed: {sp['bed'][0]} {sp['bed'][1]}%"
              + (f" · breathing: {sp['breath']['mode']}" if sp['breath']['mode'] != 'off' else ""))
    print(f"  {len(NAR.style_list()) + 1:2d}. plain read (no style — fastest)")
    print()


def main():
    ap = argparse.ArgumentParser(description="choose the batch narration style")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--set", default=None)
    a = ap.parse_args()

    current = (load_cfg().get("narration_style") or "").strip()
    if a.list:
        show_table(current)
        return 0

    if a.set is not None:
        style = a.set.strip()
        sid = NAR.style_id(style) if style and style.lower() not in ("off", "none", "plain", "") else ""
        save_style("" if not sid and not style else (sid if style else ""))
        print(f"narration_style -> {load_cfg().get('narration_style') or '(plain read)'}")
        return 0

    show_table(current)
    styles = NAR.style_list()
    try:
        pick = input(f"Choose 1-{len(styles) + 1} (Enter = keep current): ").strip()
    except EOFError:
        return 0
    if not pick:
        print("kept:", current or "(plain read)")
        return 0
    if not pick.isdigit() or not (1 <= int(pick) <= len(styles) + 1):
        print("not a number in range — nothing changed")
        return 1
    if int(pick) == len(styles) + 1:
        save_style("")
        print("\nnarration_style -> (plain read): one TTS call per chunk, fastest.")
    else:
        chosen = styles[int(pick) - 1]
        save_style(chosen["id"])
        print(f"\nnarration_style -> {chosen['label']}")
        print("Every sentence is now performed: pace, pitch, loudness, pauses,")
        print("emphasis and breathing follow the style.")
    print("\nNext batch run (menu 2) will use it. Stage 2 reports the style per chunk.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
