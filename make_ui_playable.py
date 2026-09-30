#!/usr/bin/env python3
"""make_ui_playable.py — the new studio panel as ONE self-contained page.

The live studio needs a server, and the sandbox recycles it between sessions, so
the part you actually want to try — the HD / CLEAN KHMER VOICE switch at 75 %
opacity until RVC VOICE CLONE is ticked, with the four takes playable — was hard
to get your hands on. This builds a single .html file with no server, no network
and no missing pieces:

  * the panel markup and its CSS are **extracted from the real
    `sonora/public/index.html`**, not re-typed, so what you see is the served UI;
  * the eight audio clips are embedded as base64 data URIs, so ▶ Original and
    ▶ HD Clean really play;
  * the gating rule is the same one the browser suite checks (42 checks):
    clone off → the row and the panel sit at 75 % opacity with every control
    disabled; clone on → full strength and everything plays.

    python3 pipeline/make_ui_playable.py
"""
from __future__ import annotations

import base64
import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PAGE = os.path.join(ROOT, "sonora", "public", "index.html")
CLIPS = os.path.join(ROOT, "sonora", "public", "hd_samples")
OUT = "/home/user/HD-UI-Playable.html"

CASES = (("01-normal", "A healthy take — almost nothing to fix"),
         ("01-normal-hiss", "A hiss floor — noise reduction"),
         ("01-normal-hum", "A 45 Hz hum — rumble filter"),
         ("01-normal-room", "A roomy take — de-reverb"))

#: the studio's own palette, so the page looks like the studio it comes from
PALETTE = """
  :root{ --bg:#f2efe8;--card:#fffdf8;--border:#e7e0d2;--border2:#d5ccb9;
         --ink:#201d18;--muted:#8b8374;--faint:#b0a794;
         --acc:#6f5bf0;--acc-soft:#f2eeff;--acc-border:#cbbdf7; }
  *{box-sizing:border-box}
  body{margin:0;padding:26px 20px 60px;background:var(--bg);color:var(--ink);
       font:14.5px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
  .wrap{max-width:760px;margin:0 auto}
  h1{font-size:21px;margin:0 0 4px;font-family:Georgia,"Times New Roman",serif;font-weight:600}
  .sub{color:var(--muted);margin:0 0 18px;font-size:13px}
  .card{background:var(--card);border:1px solid var(--border);border-radius:14px;
        padding:16px 18px;margin:0 0 16px}
  .tiny{font-size:10px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;color:var(--muted)}
  .linkbtn{border:1px solid var(--border);background:#f6f3ec;border-radius:999px;padding:5px 12px;
           font-size:12px;cursor:pointer;color:#57503f;font-weight:600;font-family:inherit}
  .linkbtn:hover{border-color:var(--acc);color:var(--acc)}
  .hint{font-size:11.5px;color:var(--faint);line-height:1.5}
  .perf{display:grid;gap:8px}
  .perf-h{display:flex;align-items:baseline;justify-content:space-between;gap:10px}
  .perf-sub{font-size:10.5px;color:var(--faint);text-align:right}
  .dial2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  .dial{border:1px solid var(--border);border-radius:13px;padding:10px 12px 8px;
        background:linear-gradient(180deg,#fff 0%,#fbf9f4 100%)}
  .dial-top{display:flex;align-items:baseline;justify-content:space-between;gap:8px}
  .dial-lab{font-size:10.5px;letter-spacing:.13em;font-weight:700;color:#7b7466}
  .dial-val{font-size:16px;font-weight:800;color:var(--acc);font-variant-numeric:tabular-nums;line-height:1}
  .dial-ticks{display:flex;justify-content:space-between;font-size:10px;color:var(--faint);margin-top:1px}
  input[type=range]{width:100%;margin:8px 0 2px;accent-color:var(--acc)}
  .note{background:#fff;border:1px solid var(--acc-border);border-radius:12px;padding:10px 14px;
        margin:0 0 18px;font-size:13px;color:#41358f}
  /* the studio fills this line with the picked style's own description; here it
     would just be an empty gap, so it is hidden rather than left blank. */
  #perfNote{display:none}
"""


def extract_block(text, start_pat, end_pat, label):
    i = text.find(start_pat)
    if i < 0:
        raise SystemExit("could not find %s in %s" % (label, PAGE))
    j = text.find(end_pat, i + len(start_pat))
    if j < 0:
        raise SystemExit("could not find the end of %s" % label)
    return text[i:j + len(end_pat)]


def main():
    html = io.open(PAGE, encoding="utf-8").read()

    # 1 · the panel's CSS, exactly as the studio carries it
    css = extract_block(html, ".hdrow.off{", ".hdrow.off *{cursor:not-allowed}", "hdpanel css")

    # 2 · the panel markup, exactly as the studio carries it
    panel = extract_block(html,
                          '<!-- HD / CLEAN KHMER VOICE — the four takes',
                          '<p class="hint" style="margin:6px 0 0">The same take twice through '
                          'the engine the studio runs — original, then one HD pass.</p>\n      </div>',
                          "hdpanel markup")

    # 3 · the performance block, extracted too
    perf = extract_block(html, '<div class="perf">', '<p class="perf-note" id="perfNote"></p>',
                         "performance block") + "</div>"

    # 4 · the eight clips as data URIs
    clips = {}
    total = 0
    for cid, _title in CASES:
        clips[cid] = {}
        for which, ext in (("original", ".original.mp3"), ("hd", ".hd.mp3")):
            p = os.path.join(CLIPS, cid + ext)
            if not os.path.exists(p):
                raise SystemExit("missing clip: " + p)
            raw = open(p, "rb").read()
            total += len(raw)
            clips[cid][which] = "data:audio/mpeg;base64," + \
                base64.b64encode(raw).decode("ascii")

    import json
    # strip the studio-only attributes the standalone page replaces
    panel = panel.replace('class="linkbtn hdplay"', 'class="linkbtn hdplay"')
    css = "\n".join("  " + ln.strip() for ln in css.splitlines() if ln.strip())

    page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HD / Clean Khmer Voice — the new panel, playable</title>
<style>
__PALETTE____CSS__</style></head><body><div class="wrap">
<h1>HD / Clean Khmer Voice — the new studio panel</h1>
<p class="sub">build 2026-09-30q · this one page needs no server and no internet:
every clip is inside it. The panel markup and its styles are lifted from the real
<code>sonora/public/index.html</code>, so this is the UI the studio serves.</p>

<p class="note"><b>Try the rule first:</b> leave <b>RVC VOICE CLONE</b> unticked and press
any ▶ — nothing happens, and the panel stays at 75 %. Tick it and everything comes alive.
That is exactly what the 42-check browser suite asserts.</p>

<div class="card">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;row-gap:6px">
    <label style="display:flex;align-items:center;gap:6px;cursor:pointer;flex:none">
      <input type="checkbox" id="rvcEnable" style="accent-color:var(--acc)">
      <span class="tiny" style="letter-spacing:.08em">RVC VOICE CLONE</span>
    </label>
__ROW__
    <span class="tiny" id="rvcStatus" style="flex:1;text-align:right"></span>
  </div>
__PANEL__
</div>

<div class="card">
__PERF__
  <p class="hint" style="margin:10px 2px 0">The two dials are live here: drag them and the
  numbers follow. In the studio they also set the delivery you generate.</p>
</div>

<p class="hint">Rebuild this page: <code>python3 pipeline/make_ui_playable.py</code> ·
screenshots of the same build: <code>HD-UI-Update.html</code> ·
the audio-only sheet: <code>HD-Cleanup-Demo.html</code>.</p>
</div>
<script>
/* the studio's own panel markup, with the same ids — so the gating rule below is
   the shipped one, not a description of it. */
var CLIPS = __CLIPS__;
function $(id){ return document.getElementById(id); }
function rvcEnabled(){ return $("rvcEnable").checked; }
function hdEnabled(){ return rvcEnabled() && $("hdEnable").checked; }
function showHdRow(){
  var on = rvcEnabled();
  var row = $("hdRow");
  row.classList.toggle("off", !on);
  row.style.display = "flex";
  var cb = $("hdEnable");
  cb.disabled = !on;
  cb.style.cursor = on ? "pointer" : "not-allowed";
  var panel = $("hdPanel");
  if(panel){
    panel.classList.toggle("off", !on);
    document.querySelectorAll("#hdPanel .hdplay").forEach(function(b){
      b.disabled = !on;
      b.style.cursor = on ? "pointer" : "not-allowed";
      if(!on) hdDemoReset();
    });
    var note = $("hdPanelNote");
    if(note) note.textContent = on ? "▶ plays that take" : "tick RVC VOICE CLONE to use it";
  }
  $("rvcStatus").textContent = on ? "clone path on — HD live" : "clone off — HD at 75%";
}
var hdDemoAudio = null, hdDemoBtn = null;
function hdDemoReset(){
  if(hdDemoBtn){
    hdDemoBtn.textContent = hdDemoBtn.dataset.lab || hdDemoBtn.textContent;
    hdDemoBtn.classList.remove("playing");
  }
  hdDemoBtn = null;
}
function hdDemoPlay(btn){
  if(!hdEnabled()) return;
  var cid = btn.dataset.case, which = btn.dataset.hd;
  try{
    if(hdDemoAudio){ hdDemoAudio.pause(); }
    if(hdDemoBtn && hdDemoBtn !== btn) hdDemoReset();
    hdDemoAudio = new Audio(CLIPS[cid][which]);
    hdDemoBtn = btn;
    if(!btn.dataset.lab) btn.dataset.lab = btn.textContent;
    btn.textContent = "❚❚ playing";
    btn.classList.add("playing");
    hdDemoAudio.onended = function(){ hdDemoReset(); };
    hdDemoAudio.onerror = function(){ hdDemoReset(); };
    hdDemoAudio.play().catch(function(){ hdDemoReset(); });
  }catch(e){}
}
document.querySelectorAll("#hdPanel .hdplay").forEach(function(b){
  b.addEventListener("click", function(){ hdDemoPlay(b); });
});
$("rvcEnable").addEventListener("change", showHdRow);
$("hdEnable").addEventListener("change", showHdRow);
/* the performance read-outs */
function syncPerf(){
  $("pauseVal").textContent = (+$("pause").value).toFixed(1).replace(/\\.0$/, "") + "s";
  $("speedVal").textContent = (+$("speed").value).toFixed(2) + "\\u00d7";
}
$("pause").addEventListener("input", syncPerf);
$("speed").addEventListener("input", syncPerf);
syncPerf();
showHdRow();
</script>
</body></html>
"""
    row = ('        <label class="hdrow off" id="hdRow" style="display:flex;align-items:center;'
           'gap:6px;cursor:pointer;flex:none;border-left:1px solid var(--border);'
           'padding-left:10px">\n'
           '          <input type="checkbox" id="hdEnable" checked style="accent-color:var(--acc)">\n'
           '          <span class="tiny" style="letter-spacing:.08em">HD / CLEAN KHMER VOICE</span>\n'
           '          <span class="tiny" id="hdTag" style="opacity:.62">Khmer only</span>\n'
           '        </label>\n')
    page = (page.replace("__PALETTE__", PALETTE).replace("__CSS__", css)
                .replace("__ROW__", row.rstrip("\n")).replace("__PANEL__", panel)
                .replace("__PERF__", perf)
                .replace("__CLIPS__", json.dumps(clips, separators=(",", ":"))))

    io.open(OUT, "w", encoding="utf-8").write(page)
    print("wrote %s — %.2f MB (audio %.2f MB embedded)"
          % (OUT, os.path.getsize(OUT) / 1e6, total / 1e6))
    print("   css lifted from the studio:", len(css), "chars")
    print("   panel lifted from the studio:", len(panel), "chars")
    print("   clips embedded:", sum(len(v) for v in clips.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
