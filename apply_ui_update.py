#!/usr/bin/env python3
"""apply_ui_update.py — the build-2026-09-30q UI change, as a re-runnable patch.

The sandbox (and a fresh extract of an older archive) can hand back an older
`sonora/public/index.html`. Rather than hand-editing the page again, the whole
change lives here and is re-applied in one command:

    python3 pipeline/apply_ui_update.py            # patch ./sonora/public/index.html

It is idempotent: if the page already carries the change it says so and stops.
Every step asserts its anchor first, so it can never half-apply silently — if a
string moved, it fails loudly instead of writing a broken page.

What it does (build 2026-09-30q):

  1. PERFORMANCE: one header row, and DRAMATIC PAUSES + NARRATION SPEED side by
     side underneath (the space saving), same controls and read-outs.
  2. HD / CLEAN KHMER VOICE: always on the page, at 75% opacity with the box
     disabled until RVC VOICE CLONE is ticked; full strength and usable once it
     is. It never disappears.
  3. The four takes — healthy / hiss / 45 Hz hum / roomy — are playable inside
     the studio with ▶ Original and ▶ HD Clean, from the same clips
     HD-Cleanup-Demo.html plays. Dimmed and dead while the clone is off.
  4. ⟳ Test clone ▶ moves up next to 🔍 Find RVC folder, and the long paragraph
     about the clone folds into a one-click summary (nothing deleted).
"""
from __future__ import annotations

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PAGE = os.path.join(ROOT, "sonora", "public", "index.html")

MARK = 'id="hdPanel"'          # the change is present when this is
NEED = ('id="hdRow"', '13 styles')   # …and only applies to this page


def fail(msg):
    print("!! " + msg)
    sys.exit(1)


def sub(text, old, new, label):
    if old not in text:
        fail("anchor not found: %s" % label)
    return text.replace(old, new, 1)


def main():
    if not os.path.exists(PAGE):
        fail("no page at %s" % PAGE)
    html = io.open(PAGE, encoding="utf-8").read()

    if MARK in html:
        print("already applied — the page carries the HD panel (%d bytes)" % len(html))
        return 0
    for n in NEED:
        if n not in html:
            fail("this page is not the expected one (%r missing) — refusing to patch %s"
                 % (n, PAGE))

    n_before = len(html)

    # ---------- 1 · PERFORMANCE: two dials side by side ----------
    html = sub(html,
               '<span class="perf-sub">plain voice — these two dials are the whole delivery</span>',
               '<span class="perf-sub">both dials apply to every style — the style keeps its own '
               'pace and pauses</span>', "perf sub-line")
    html = sub(html, '<div class="dial" id="dialPause">',
               '<div class="dial2">\n        <div class="dial" id="dialPause">', "dial2 open")
    html = sub(html,
               '          <div class="dial-ticks"><span>slow</span><span>storytelling</span>'
               '<span>fast</span></div>\n        </div>\n        <p class="perf-note" id="perfNote">',
               '          <div class="dial-ticks"><span>slow</span><span>storytelling</span>'
               '<span>fast</span></div>\n        </div>\n        </div>\n'
               '        <p class="perf-note" id="perfNote">', "dial2 close")
    html = sub(html, ".perf{display:grid;gap:9px}",
               ".perf{display:grid;gap:8px}\n"
               ".dial2{display:grid;grid-template-columns:1fr 1fr;gap:10px}\n"
               "@media(max-width:900px){.dial2{grid-template-columns:1fr}}", "perf css")

    # ---------- 2 · the HD row: visible, dimmed, disabled ----------
    html = sub(html,
               '<label class="hdrow hidden" id="hdRow" style="display:none;align-items:center;'
               'gap:6px;cursor:pointer;flex:none;border-left:1px solid var(--border);'
               'padding-left:10px">',
               '<label class="hdrow off" id="hdRow" style="display:flex;align-items:center;'
               'gap:6px;cursor:pointer;flex:none;border-left:1px solid var(--border);'
               'padding-left:10px">', "hd row")

    # ---------- 3 · ⟳ Test clone ▶ next to 🔍 Find RVC folder ----------
    html = sub(html,
               '            <button class="linkbtn" id="rvcScan" type="button">🔍 Find RVC '
               'folder</button>\n            <span class="tiny" id="rvcScanStatus"></span>\n',
               '            <button class="linkbtn" id="rvcScan" type="button">🔍 Find RVC '
               'folder</button>\n            <button class="linkbtn" id="rvcTest" type="button">'
               '⟳ Test clone ▶</button>\n            <span class="tiny" id="rvcScanStatus">'
               '</span>\n', "scan row")
    html = sub(html,
               '          <div style="margin-top:8px;display:flex;gap:10px;align-items:center">\n'
               '            <button class="linkbtn" id="rvcTest" type="button">⟳ Test clone ▶'
               '</button>\n          </div>\n', "", "old test-clone block")

    # ---------- 4 · less text: one line, the rest one click away ----------
    html = re.sub(
        r'          <p class="hint" style="margin-top:8px">Loads your Sonaro-kh.*?</p>\n',
        '          <p class="hint" style="margin-top:6px">Loads your Sonaro-kh model once, then '
        're-voices each line. GPU (CUDA) makes it ~10× faster. <b>⟳ Test clone ▶</b> reports '
        'the measured pitch of the base voice and of the clone.</p>\n'
        '          <details style="margin-top:4px"><summary class="tiny" style="cursor:pointer">'
        'how the clone and the base voice work</summary>\n'
        '            <p class="hint" style="margin-top:6px"><b>The clone replaces the host\'s '
        'voice:</b> the base voice only supplies Khmer pronunciation and timing — the voice you '
        'hear is the model, so a male model comes out male whatever the base voice is. For a '
        'female clone, train on a female speaker (menu 13 → RVC-WebUI Train). Crossing genders '
        'on purpose: PITCH ±12 (one octave) — female base → male model −12, male base → female '
        'model +12.</p>\n          </details>\n',
        html, count=1, flags=re.S)
    if "how the clone and the base voice work" not in html:
        fail("anchor not found: hint paragraph")

    # ---------- 5 · the four-case panel, directly under the clone row ----------
    panel = """      <!-- HD / CLEAN KHMER VOICE — the four takes the tool exists for, playable
           here. Same clips as HD-Cleanup-Demo.html. Dimmed and unusable until
           RVC VOICE CLONE is ticked; see showHdRow(). -->
      <div class="hdpanel off" id="hdPanel">
        <div class="hdpanel-h">
          <span class="tiny">HD / CLEAN KHMER VOICE — THE FOUR TAKES</span>
          <span class="tiny" id="hdPanelNote" style="opacity:.75">tick RVC VOICE CLONE to use it</span>
        </div>
        <div class="hdcase" data-case="01-normal">
          <span class="hdcase-t" title="A healthy take — almost nothing to fix">A healthy take — almost nothing to fix</span>
          <button class="linkbtn hdplay" type="button" data-case="01-normal" data-hd="original">▶ Original</button>
          <button class="linkbtn hdplay" type="button" data-case="01-normal" data-hd="hd">▶ HD Clean</button>
        </div>
        <div class="hdcase" data-case="01-normal-hiss">
          <span class="hdcase-t" title="A hiss floor — noise reduction">A hiss floor — noise reduction</span>
          <button class="linkbtn hdplay" type="button" data-case="01-normal-hiss" data-hd="original">▶ Original</button>
          <button class="linkbtn hdplay" type="button" data-case="01-normal-hiss" data-hd="hd">▶ HD Clean</button>
        </div>
        <div class="hdcase" data-case="01-normal-hum">
          <span class="hdcase-t" title="A 45 Hz hum — rumble filter">A 45 Hz hum — rumble filter</span>
          <button class="linkbtn hdplay" type="button" data-case="01-normal-hum" data-hd="original">▶ Original</button>
          <button class="linkbtn hdplay" type="button" data-case="01-normal-hum" data-hd="hd">▶ HD Clean</button>
        </div>
        <div class="hdcase" data-case="01-normal-room">
          <span class="hdcase-t" title="A roomy take — de-reverb">A roomy take — de-reverb</span>
          <button class="linkbtn hdplay" type="button" data-case="01-normal-room" data-hd="original">▶ Original</button>
          <button class="linkbtn hdplay" type="button" data-case="01-normal-room" data-hd="hd">▶ HD Clean</button>
        </div>
        <p class="hint" style="margin:6px 0 0">The same take twice through the engine the studio runs — original, then one HD pass.</p>
      </div>

"""
    html = sub(html, '        <div id="rvcPanel" class="hidden" style="margin-top:8px">',
               panel + '        <div id="rvcPanel" class="hidden" style="margin-top:8px">',
               "rvcPanel (panel goes above it)")

    # ---------- 6 · css ----------
    html = sub(html, ".linkbtn:hover{border-color:var(--acc);color:var(--acc)}",
               ".linkbtn:hover{border-color:var(--acc);color:var(--acc)}\n"
               ".hdrow.off{opacity:.75}\n"
               ".hdpanel{margin-top:12px;border-top:1px solid rgba(127,127,127,.18);padding-top:10px}\n"
               ".hdpanel.off{opacity:.75}\n"
               ".hdpanel-h{display:flex;align-items:baseline;justify-content:space-between;gap:8px;margin-bottom:4px}\n"
               ".hdcase{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:6px;align-items:center;padding:4px 0;border-top:1px solid rgba(127,127,127,.10)}\n"
               ".hdcase-t{font-size:11px;color:#5c5546;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n"
               ".hdplay{font-size:11px;padding:4px 10px}\n"
               ".hdplay.playing{border-color:var(--acc);color:var(--acc);background:var(--acc-soft)}\n"
               ".hdpanel.off .linkbtn{cursor:not-allowed;border-color:var(--border);color:#a9a29a}\n"
               ".hdrow.off *{cursor:not-allowed}", "linkbtn css")

    # ---------- 7 · js: the gating rule ----------
    html = sub(html,
               'function showHdRow(){\n  const row = $("hdRow");\n'
               '  row.classList.toggle("hidden", !rvcEnabled());\n'
               '  row.style.display = rvcEnabled() ? "flex" : "none";\n}',
               '''function showHdRow(){
  // The switch is ALWAYS on the page — it is a real feature of the studio, not a
  // secret — but it only works inside the clone path. Without RVC VOICE CLONE it
  // sits at 75% opacity with its box disabled, and the four-case demo panel
  // below it is dimmed the same way; ticking the clone makes both live.
  const on = rvcEnabled();
  const row = $("hdRow");
  row.classList.toggle("off", !on);
  row.style.display = "flex";
  const cb = $("hdEnable");
  cb.disabled = !on;
  cb.style.cursor = on ? "pointer" : "not-allowed";
  const panel = $("hdPanel");
  if(panel){
    panel.classList.toggle("off", !on);
    document.querySelectorAll("#hdPanel .hdplay").forEach(b => {
      b.disabled = !on;
      b.style.cursor = on ? "pointer" : "not-allowed";
      if(!on) hdDemoReset();
    });
    const note = $("hdPanelNote");
    if(note) note.textContent = on
      ? "▶ plays that take"
      : "tick RVC VOICE CLONE to use it";
  }
}''', "showHdRow")

    # ---------- 8 · js: the demo player ----------
    html = sub(html,
               'if($("hdPlayA")) $("hdPlayA").onclick = () => playHd("original");',
               '''/* ---------- the four HD cases (public/hd_samples/<case>.<original|hd>.mp3) ----------
   The same clips HD-Cleanup-Demo.html plays, so what you hear here is what you
   tested there. Only usable while the clone path is on (hdEnabled()). */
let hdDemoAudio = null, hdDemoBtn = null;
function hdDemoReset(){
  if(hdDemoBtn){
    hdDemoBtn.textContent = hdDemoBtn.dataset.lab || hdDemoBtn.textContent;
    hdDemoBtn.classList.remove("playing");
  }
  hdDemoBtn = null;
}
function hdDemoPlay(btn){
  if(!hdEnabled()) return;
  const cid = btn.dataset.case, which = btn.dataset.hd;
  const url = "hd_samples/" + cid + (which === "hd" ? ".hd.mp3" : ".original.mp3");
  try{
    if(hdDemoAudio){ hdDemoAudio.pause(); }
    if(hdDemoBtn && hdDemoBtn !== btn) hdDemoReset();
    hdDemoAudio = new Audio(url + "?t=" + Date.now());
    hdDemoBtn = btn;
    if(!btn.dataset.lab) btn.dataset.lab = btn.textContent;
    btn.textContent = "❚❚ playing";
    btn.classList.add("playing");
    hdDemoAudio.onended = () => hdDemoReset();
    hdDemoAudio.onerror = () => hdDemoReset();
    hdDemoAudio.play().catch(() => hdDemoReset());
  }catch(e){}
}
document.querySelectorAll("#hdPanel .hdplay").forEach(b => { b.onclick = () => hdDemoPlay(b); });
if($("hdPlayA")) $("hdPlayA").onclick = () => playHd("original");''', "hd demo player")

    io.open(PAGE, "w", encoding="utf-8").write(html)
    print("applied — %s grew by %d bytes (now %d)" % (PAGE, len(html) - n_before, len(html)))
    for label, needle in (("hd panel", 'id="hdPanel"'), ("two dials", 'class="dial2"'),
                          ("row off state", 'class="hdrow off"'),
                          ("test-clone moved", 'id="rvcTest" type="button">⟳ Test clone ▶</button>\n            <span class="tiny" id="rvcScanStatus">'),
                          ("demo player", "hdDemoPlay"), ("folded paragraph", "how the clone and the base voice work")):
        print("   %-18s %s" % (label, "ok" if needle in html else "MISSING"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
