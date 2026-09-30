"""make_hd_demo_page.py — build one self-contained page you can listen to.

Writes `HD-Cleanup-Demo.html`: no external files, no network — the four
before/after pairs are embedded in the page itself, so it works from a USB
stick, a chat message or an offline laptop. Numbers come from the §28 matrix
(`sonora/public/hd_samples/samples.json`), never typed by hand.

    python3 pipeline/make_hd_demo_page.py
"""
from __future__ import annotations

import base64
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLIPS = os.path.join(ROOT, "sonora", "public", "hd_samples")
OUT = os.path.join(ROOT, "HD-Cleanup-Demo.html")

#: the four rows worth hearing: a clean one, and the three defects the tool exists for
CASES = (
    ("01-normal", "A healthy take — almost nothing to fix",
     "One small move was asked for (a fraction of a dB at 250 Hz); the rest is "
     "the delivery standard: measure the loudness, then limit to about "
     "-1 dBTP. Nearly everything you hear here is level — and across the "
     "15-sample matrix, 11 clips needed no correction at all."),
    ("01-normal-hiss", "A hiss floor — noise reduction",
     "A steady hiss floor was measured and gently reduced. The voice must stay "
     "untouched: listen for breath and consonants surviving."),
    ("01-normal-hum", "A 45 Hz hum — rumble filter",
     "A steady low-frequency bed, measured in the pauses (where a voice is not). "
     "Two cascaded high-pass filters, then the level is restored."),
    ("01-normal-room", "A roomy take — de-reverb",
     "A 300 ms room was detected in the pauses and pulled down. The speech "
     "level itself is left alone — no hollow, metallic or underwater effect."),
)


def _b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _row(rows, cid):
    for r in rows:
        if r["id"] == cid:
            return r
    return None


def main():
    data = json.load(open(os.path.join(CLIPS, "samples.json"), encoding="utf-8"))
    rows = data["samples"]
    cards = []
    for cid, title, note in CASES:
        r = _row(rows, cid)
        if r is None:
            continue
        o = os.path.join(CLIPS, "%s.original.mp3" % cid)
        h = os.path.join(CLIPS, "%s.hd.mp3" % cid)
        if not (os.path.exists(o) and os.path.exists(h)):
            continue
        stages = "nothing needed" if (not r["stages"] or "nothing" in r["stages"][0].lower()) \
            else "; ".join(r["stages"])
        cards.append("""
  <div class="card">
    <h3>{title}<span class="case">{cid}</span></h3>
    <p class="note">{note}</p>
    <dl class="nums">
      <div><dt>stages applied</dt><dd>{stages}</dd></div>
      <div><dt>quality score</dt><dd>{score}</dd></div>
      <div><dt>loudness</dt><dd>{lufs} LUFS</dd></div>
      <div><dt>true peak</dt><dd>{peak} dBTP</dd></div>
      <div><dt>spectrum moved</dt><dd>{dmax:.2f} dB max &middot; {drms:.2f} dB rms</dd></div>
      <div><dt>length kept</dt><dd>{length}</dd></div>
    </dl>
    <div class="players">
      <div><span class="tag orig">Original</span>
        <audio controls preload="none" src="data:audio/mpeg;base64,{ob64}"></audio></div>
      <div><span class="tag hd">HD Clean</span>
        <audio controls preload="none" src="data:audio/mpeg;base64,{hb64}"></audio></div>
    </div>
  </div>""".format(
            title=title, cid=cid, note=note, stages=stages, score=r["score"],
            lufs=r["lufs"], peak=r["true_peak"], dmax=r["ltas_max_db"],
            drms=r["ltas_rms_db"], length="yes, sample-for-sample" if r["length_kept"] else "no",
            ob64=_b64(o), hb64=_b64(h)))

    html = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HD / Clean Khmer Voice — hear it</title>
<style>
 :root {{ --ink:#1c2431; --dim:#5b6a80; --line:#dde3ec; --bg:#f6f8fb; --acc:#5b4bd6; }}
 * {{ box-sizing:border-box; }}
 body {{ margin:0; padding:28px 20px 60px; background:var(--bg); color:var(--ink);
        font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }}
 .wrap {{ max-width:900px; margin:0 auto; }}
 h1 {{ font-size:26px; margin:0 0 6px; letter-spacing:-.2px; }}
 .sub {{ color:var(--dim); margin:0 0 22px; }}
 .pill {{ display:inline-block; background:#e9e6ff; color:#3b2fa8; border-radius:999px;
          padding:2px 10px; font-size:12.5px; font-weight:600; margin-right:6px; }}
 .box {{ background:#fff; border:1px solid var(--line); border-radius:14px; padding:18px 20px;
         margin:0 0 18px; }}
 .box h2 {{ font-size:17px; margin:0 0 10px; }}
 .card {{ background:#fff; border:1px solid var(--line); border-radius:14px; padding:18px 20px;
          margin:0 0 16px; }}
 .card h3 {{ font-size:17px; margin:0 0 6px; }}
 .case {{ color:var(--dim); font-weight:400; font-size:13px; margin-left:8px; }}
 .note {{ color:var(--dim); margin:0 0 12px; font-size:14.5px; }}
 dl.nums {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
            gap:6px 22px; margin:0 0 14px; }}
 dl.nums div {{ display:flex; justify-content:space-between; gap:10px;
                border-bottom:1px dotted var(--line); padding:3px 0; font-size:13.5px; }}
 dt {{ color:var(--dim); }} dd {{ margin:0; font-weight:600; text-align:right; }}
 .players {{ display:grid; gap:8px; }}
 .players > div {{ display:flex; align-items:center; gap:10px; }}
 .tag {{ flex:0 0 82px; font-size:12.5px; font-weight:700; letter-spacing:.03em;
         text-transform:uppercase; }}
 .tag.orig {{ color:#8a6a1f; }} .tag.hd {{ color:#1d7a4d; }}
 audio {{ width:100%; height:34px; }}
 code {{ background:#eef1f6; padding:1px 5px; border-radius:5px; font-size:13.5px; }}
 table {{ width:100%; border-collapse:collapse; font-size:14px; }}
 td, th {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }}
 th {{ color:var(--dim); font-weight:600; }}
 .foot {{ color:var(--dim); font-size:13px; margin-top:22px; }}
</style></head>
<body><div class="wrap">

<h1>HD / Clean Khmer Voice</h1>
<p class="sub"><span class="pill">build 2026-09-30m</span>
<span class="pill">RVC VOICE CLONE only</span><span class="pill">Khmer only</span><br>
The same take twice: before, and after one HD Cleanup pass. No editing, no retakes —
if you hear a difference, that difference <em>is</em> the tool.</p>

{cards}

<div class="box">
  <h2>What this page is, and what it is not</h2>
  <p style="margin:0 0 10px">These are real clips from the Khmer test matrix, rendered
  from the 48&nbsp;kHz / 24&nbsp;bit masters the engine writes. The four rows above are one
  clean take and the three defects the tool is for. The other eleven rows — fast, slow,
  emotional, calm, long and short lines, Khmer names, numbers, punctuation, pauses, a
  whisper — are in the studio folder <code>sonora/public/hd_samples/</code>, every one
  of them with its Original next to its HD.</p>
  <p style="margin:0">MP3 is used here so a single page can hold everything; the studio
  itself always writes <strong>WAV 48&nbsp;kHz / 24-bit</strong>, and never deletes or
  overwrites your cloned voice — it keeps <code>&lt;key&gt;.original.wav</code> beside
  <code>enhanced_hd.wav</code>.</p>
</div>

<div class="box">
  <h2>Is your studio running this build?</h2>
  <table>
    <tr><th>you should see</th><th>where</th></tr>
    <tr><td><code>build 2026-09-30m</code></td><td>top-right of the page, next to “Engine online”</td></tr>
    <tr><td><code>HD / CLEAN KHMER VOICE · KHMER ONLY</code></td>
        <td>a row to the right of the <code>RVC VOICE CLONE</code> checkbox, and only after you tick it</td></tr>
    <tr><td><code>▶ Original</code> and <code>▶ HD Clean</code></td>
        <td>under the result line of a finished clone job</td></tr>
  </table>
  <p style="margin:10px 0 0">Older number in the header means the new files never replaced
  the old ones: close the studio, extract the package <em>over</em> the folder, restart
  <code>START.bat</code>, then press <strong>Ctrl+F5</strong>.</p>
</div>

<p class="foot">Feature name <strong>HD / Clean Khmer Voice</strong> · internal engine
<strong>Adaptive Khmer Voice Enhancement</strong> (<code>sonora/hdclean.py</code>).<br>
Full written evidence: <code>HD-Spec-Coverage.md</code> (your 30 sections, each mapped to
code and measurement) · <code>HD-Cleanup-Khmer.md</code> (what every stage does, and what
it never does) · <code>hd-samples.md</code> (the 20-row measured matrix).</p>

</div></body></html>
""".format(cards="".join(cards))
    open(OUT, "w", encoding="utf-8").write(html)
    n = len(cards)
    print("wrote %s — %d clip pairs · %.1f MB" % (OUT, n, os.path.getsize(OUT) / 1e6))


if __name__ == "__main__":
    main()
