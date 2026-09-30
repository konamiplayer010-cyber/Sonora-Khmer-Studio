"""make_whisper_page.py — the whisper removal, with the two takes side by side.

Builds `Whisper-Removed.html`: one self-contained page (no external files, no
network — the audio is embedded) that plays

    the take the OLD engine shipped   (whisper stage applied to the line)
    the take the NEW engine ships     (the line, exactly as the voice said it)

for the same Khmer sentence, and prints what changed. The old take is produced
by `whisper._whisperize_removed()`, which is the old synthesiser kept in the
module for exactly this purpose: the honest A/B needs the old sound, and it can
no longer be reached by accident.

    python3 pipeline/make_whisper_page.py
"""
from __future__ import annotations

import base64
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AB = os.path.join(ROOT, "sonora", "public", "whisper_ab")
OUT = os.path.join(ROOT, "Whisper-Removed.html")

#: measured by make_whisper_page's probe (see Whisper-Removed.md for how)
MEASURED = {
    "old_air": -3.52, "new_air": -18.94,        # 2.5–9 kHz vs 300 Hz–2.5 kHz
    "old_level": -23.8, "new_level": -22.0,     # dBFS
    "seconds": 3.79,
}


def _b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def main():
    old = _b64(os.path.join(AB, "old-whispered.mp3"))
    new = _b64(os.path.join(AB, "new-voice.mp3"))
    inside = os.path.join(AB, "whisper-in-a-normal-read.mp3")
    inside_b64 = _b64(inside) if os.path.exists(inside) else None
    source = os.path.join(AB, "source-line.mp3")
    source_b64 = _b64(source) if os.path.exists(source) else None
    breath = os.path.join(AB, "pause-with-breath.mp3")
    breath_b64 = _b64(breath) if os.path.exists(breath) else None
    silent = os.path.join(AB, "pause-now-silent.mp3")
    silent_b64 = _b64(silent) if os.path.exists(silent) else None
    breath_only = os.path.join(AB, "breath-only-x30.mp3")
    breath_only_b64 = _b64(breath_only) if os.path.exists(breath_only) else None
    m = MEASURED
    html = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Whisper removed — hear the difference (build 2026-09-30o)</title>
<style>
 body {{ margin:0; padding:28px 20px 60px; background:#f6f8fb; color:#1c2431;
        font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif; }}
 .wrap {{ max-width:900px; margin:0 auto; }}
 h1 {{ font-size:26px; margin:0 0 6px; }}
 .sub {{ color:#5b6a80; margin:0 0 22px; }}
 .pill {{ display:inline-block; background:#e9e6ff; color:#3b2fa8; border-radius:999px;
          padding:2px 10px; font-size:12.5px; font-weight:600; margin-right:6px; }}
 .box {{ background:#fff; border:1px solid #dde3ec; border-radius:14px; padding:18px 20px;
         margin:0 0 16px; }}
 .box h2 {{ font-size:17px; margin:0 0 10px; }}
 .row {{ display:flex; align-items:center; gap:10px; margin:8px 0; }}
 .tag {{ flex:0 0 190px; font-size:13px; font-weight:700; text-transform:uppercase;
         letter-spacing:.03em; }}
 .tag.old {{ color:#a4442c; }} .tag.new {{ color:#1d7a4d; }} .tag.mid {{ color:#8a6a1f; }}
 audio {{ width:100%; height:34px; }}
 table {{ width:100%; border-collapse:collapse; font-size:14px; margin-top:6px; }}
 td, th {{ text-align:left; padding:6px 8px; border-bottom:1px solid #dde3ec; }}
 th {{ color:#5b6a80; font-weight:600; }}
 code {{ background:#eef1f6; padding:1px 5px; border-radius:5px; font-size:13.5px; }}
 .foot {{ color:#5b6a80; font-size:13px; margin-top:20px; }}
</style></head>
<body><div class="wrap">

<h1>The whisper is gone</h1>
<p class="sub"><span class="pill">build 2026-09-30n</span>
<span class="pill">applies to every voice</span><span class="pill">Khmer &amp; English</span><br>
Same Khmer sentence, same voice, same take. It is read first as plain speech,
then the way the old engine shipped it when the words earned a whisper, and last
the way it ships now.</p>

<div class="box">
  <h2>Hear it</h2>
  {{source_row}}
  <div class="row"><span class="tag old">Old — whispered line</span>
    <audio controls preload="none" src="data:audio/mpeg;base64,{old}"></audio></div>
  <div class="row"><span class="tag new">New — the voice reads it</span>
    <audio controls preload="none" src="data:audio/mpeg;base64,{new}"></audio></div>
  {{inside_row}}
  <table>
    <tr><th>measured</th><th>old take</th><th>new take</th></tr>
    <tr><td>air, 2.5–9 kHz vs the words (300 Hz–2.5 kHz)</td>
        <td><b>{old_air:+.2f} dB</b></td><td>{new_air:+.2f} dB</td></tr>
    <tr><td>level</td><td>{old_level:.1f} dBFS</td><td>{new_level:.1f} dBFS</td></tr>
  </table>
  <p style="margin:10px 0 0">The old take is <b>{air_delta:.1f} dB airier</b> than the voice —
  a breath carrying the words, which is a different sound, not a quieter reading.
  That is why, mid-sentence, it sounded like the voice had been replaced; and once
  the master chain normalised the level it arrived as loud as the line it replaced.</p>
</div>

<div class="box">
  <h2>What you described — a whisper arriving inside a normal read</h2>
  <p style="margin:0 0 8px">A healthy read on both sides, and the old whispered
  take dropped into the middle of it. This is the sound you reported hearing
  while the voice was simply reading — and it is the case the checker is built to
  find. On this file it reports one passage, <b>0:04.13–0:07.93</b> (3.80 s),
  air +11.8 dB over the voice, pitch 0.23.</p>
  {{inside_player}}
  <p style="margin:8px 0 0">Run it on any file you have:
  <code>python3 pipeline/check_whisper.py yourfile.wav</code></p>
</div>

<div class="box">
  <h2>build 2026-09-30o — the sound that was hiding between the sentences</h2>
  <p style="margin:0 0 8px">You reported the whisper again in English: not over the
  whole file, but heard again and again — about <b>10–15 times in a five-minute
  read</b>, in the gaps between the sentences. That was not the whispered line of
  build n; it was the last non-speech sound the generator made. The renderer
  synthesised a soft <b>inhale</b> — filtered noise, shaped like a breath — and
  wrote it into every few sentence gaps. It is quiet (about 35 dB under the
  voice, 0.22–0.42 s long), which is exactly why it survived: loud enough to be
  heard in a pause, easy to miss on a measurement that looks for a loud whisper.
  Two sentences, the same take, one press apart — first with the old breath in
  the gap, then with the silence that replaces it.</p>
  {{breath_row}}
  <p style="margin:10px 0 8px">If it is hard to hear at normal level, this is the
  same breath on its own, amplified +30 dB and with the voice muted — so you can
  recognise the sound if it ever comes back:</p>
  {{breath_only_player}}
  <p style="margin:8px 0 0">The checker now audits the pauses too. On the old
  take it reports <b>0:03.22 for 1.78 s at −53.0 dBFS</b>; on the new one it says
  the pauses are silent. Run it on your own file:
  <code>python3 pipeline/check_whisper.py yourfile.wav</code></p>
</div>

<div class="box">
  <h2>What changed in the build</h2>
  <table>
    <tr><th>where</th><th>before</th><th>now</th></tr>
    <tr><td>the engine (<code>whisper.py</code>)</td>
        <td>synthesised a near-whisper from the line</td>
        <td><code>whisperize()</code> returns the line <b>bit-identical</b>; <code>depth_for()</code> is 0.0 for every style</td></tr>
    <tr><td>the planner</td>
        <td>cinematic ~1 line in 3, thriller ~3 in 10, plus any intimacy cue in the text</td>
        <td>no line is ever flagged — checked over all 13 styles × 4 texts (143 lines, 0 flagged)</td></tr>
    <tr><td>the delivery layer</td>
        <td>“Whisper / Intimate” carried a whisper depth of 0.55</td>
        <td>the slot still exists as a soft, close, hesitant delivery — with no whisper in it</td></tr>
    <tr><td>the studio and the batch renderer</td>
        <td>whisperised each marked line as it rendered</td>
        <td>never call the synthesiser any more; the line goes to the master untouched</td></tr>
    <tr><td>the pause itself <i>(2026-09-30o)</i></td>
        <td>a synthesised breath was written into every few sentence gaps — filtered noise, ~35 dB under the voice, 10–15 times per five minutes</td>
        <td>every pause is exact digital silence; both breath synthesisers return zeros, and no style, feeling or delivery can mark a line for one. The pauses, pace and softness stay</td></tr>
  </table>
  <p style="margin:10px 0 0">What <b>stays</b>: an intimate passage is still slower,
  softer, closer and better spaced — performed by the same voice, from the first
  line to the last. Pitch is still locked at 0.0 st in all 13 styles.</p>
</div>

<p class="foot">Full write-up, including the user report and the test results:
<code>Whisper-Removed.md</code>. The switch this belongs to (HD / Clean Khmer Voice)
is unchanged: <code>HD-Spec-Coverage.md</code>.</p>

</div></body></html>
""".format(old=old, new=new, **m,
           air_delta=abs(m["new_air"] - m["old_air"]))
    html = html.replace(
        "{source_row}",
        ("""<div class="row"><span class="tag mid">Source — the plain line</span>
    <audio controls preload="none" src="data:audio/mpeg;base64,%s"></audio></div>"""
         % source_b64) if source_b64 else "")
    html = html.replace(
        "{inside_row}",
        ("""<div class="row"><span class="tag mid">Whisper inside a read</span>
    <audio controls preload="none" src="data:audio/mpeg;base64,%s"></audio></div>"""
         % inside_b64) if inside_b64 else "")
    html = html.replace(
        "{breath_row}",
        ("""<div class="row"><span class="tag old">Old — breath in the gap</span>
    <audio controls preload="none" src="data:audio/mpeg;base64,%s"></audio></div>
  <div class="row"><span class="tag new">Now — the gap is silence</span>
    <audio controls preload="none" src="data:audio/mpeg;base64,%s"></audio></div>"""
         % (breath_b64, silent_b64)) if breath_b64 and silent_b64 else "")
    html = html.replace(
        "{breath_only_player}",
        ("""<audio controls preload="none" src="data:audio/mpeg;base64,%s"></audio>"""
         % breath_only_b64) if breath_only_b64 else "")
    html = html.replace(
        "{inside_player}",
        ("""<audio controls preload="none" src="data:audio/mpeg;base64,%s"></audio>"""
         % inside_b64) if inside_b64 else "")
    open(OUT, "w", encoding="utf-8").write(html)
    print("wrote %s — %.1f MB" % (OUT, os.path.getsize(OUT) / 1e6))


if __name__ == "__main__":
    main()
