#!/usr/bin/env python3
"""make_hd_ui_page.py — one page showing the HD Cleanup tool in the studio.

Takes the screenshots `pipeline/check_hd_ui.py` writes into `ui-fit/` and puts
them in one sheet, images embedded, so the tool can be reviewed without running
the studio. Nothing here is drawn by hand: every picture is a real browser
capture of the page the server serves.

    python3 pipeline/make_hd_ui_page.py
"""
import base64
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SHOTS = os.path.join(ROOT, "ui-fit")
OUT = os.path.join(ROOT, "HD-Cleanup-UI.html")

#: (file, heading, what to look at)
ROWS = [
    ("ui-hd-1-row-on.png",
     "1 · the tool appears when the clone is ticked",
     "RVC VOICE CLONE ticked → “HD / CLEAN KHMER VOICE · KHMER ONLY” comes up "
     "next to it, switched on by default. It is not there while the clone is off, "
     "and it belongs to no other path."),
    ("ui-hd-2557x1239.png",
     "2 · the same row at your screen size (2557 × 1239)",
     "On a wide screen it sits on the same line as the clone switch, to its right, "
     "separated by a hairline. Page overflow 0 px — nothing is cut off."),
    ("ui-hd-2-cases.png",
     "3 · the four takes, playable in the studio",
     "Two words of English in the whole control: the name and “Khmer only”. "
     "There is no EQ, no compressor and no noise-reduction dial anywhere."),
    ("ui-hd-3-result.png",
     "4 · after a run",
     "The result line reports what the engine actually did — score before → after, "
     "the stages it switched on, 48 kHz / 24-bit — and names both files: the kept "
     "original and the HD master. Then ▶ Original and ▶ HD Clean."),
    ("ui-hd-4-failed.png",
     "5 · when the enhancement cannot run",
     "The original audio stays, nothing is replaced, and the line says exactly: "
     "“Enhancement unavailable; original TTS preserved.”"),
]


def b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def main():
    cards, missing = [], []
    for name, head, note in ROWS:
        p = os.path.join(SHOTS, name)
        if not os.path.exists(p):
            missing.append(name)
            continue
        cards.append(
            '<div class="card"><h2>%s</h2><p>%s</p>'
            '<img alt="%s" src="data:image/png;base64,%s"></div>'
            % (head, note, name, b64(p)))
    html = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HD / Clean Khmer Voice — the tool in the studio</title>
<style>
 body {{ margin:0; padding:30px 22px 70px; background:#f6f8fb; color:#1c2431;
        font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }}
 .wrap {{ max-width:1180px; margin:0 auto; }}
 h1 {{ font-size:26px; margin:0 0 6px; }}
 .sub {{ color:#5b6675; margin:0 0 26px; }}
 .badge {{ display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px;
           font-weight:700; background:#e8eefb; color:#2b4a8b; margin-left:8px; }}
 .card {{ background:#fff; border:1px solid #e3e8f0; border-radius:12px;
          padding:18px 18px 14px; margin:0 0 22px; box-shadow:0 1px 2px rgba(20,30,50,.05); }}
 .card h2 {{ font-size:17px; margin:0 0 4px; }}
 .card p {{ margin:0 0 12px; color:#4a5563; }}
 img {{ width:100%; height:auto; display:block; border:1px solid #dde4ee; border-radius:8px; }}
 .foot {{ color:#6b7583; font-size:13px; margin-top:26px; }}
 code {{ background:#eef2f8; padding:1px 5px; border-radius:4px; font-size:13px; }}
</style></head><body><div class="wrap">
<h1>HD / Clean Khmer Voice<span class="badge">RVC VOICE CLONE · Khmer only</span></h1>
<p class="sub">Engine: <b>Adaptive Khmer Voice Enhancement</b>. Every picture below is a
real browser capture of the studio page this build serves — nothing is a mock-up.</p>
{cards}
<p class="foot">Rebuild these yourself: <code>python3 pipeline/check_hd_ui.py</code>
(writes into <code>ui-fit/</code>, 42 checks) then
<code>python3 pipeline/make_hd_ui_page.py</code>.<br>
The audio side is in <code>HD-Cleanup-Demo.html</code>; the full specification
mapping is in <code>HD-Spec-Coverage.md</code>.</p>
</div></body></html>
""".format(cards="\n".join(cards))
    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote %s — %.2f MB · %d screenshot(s)%s"
          % (OUT, os.path.getsize(OUT) / 1e6, len(cards),
             "" if not missing else " · missing: %s" % missing))


if __name__ == "__main__":
    main()
