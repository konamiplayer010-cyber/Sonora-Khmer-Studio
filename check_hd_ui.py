#!/usr/bin/env python3
"""check_hd_ui.py — the browser check for the HD / Clean Khmer Voice switch.

`test_hd_server.py` proves the engine side (a real Khmer master goes through the
pass, the original is kept, the previews are served). This one proves the part
only a browser can show:

  1. the row is ON THE PAGE at all times, but at 75% opacity with its box
     disabled while RVC VOICE CLONE is off — visible, not usable;
  2. ticking the clone makes it live, and it sits at the right of the clone box;
  3. the four-case panel (the clips HD-Cleanup-Demo.html plays) is dimmed and
     dead until the clone is on, and plays the right URL once it is;
  4. a finished HD run fills the result line and puts up ▶ Original / ▶ HD Clean;
  5. a failed run shows the exact fallback sentence and no buttons;
  6. “⟳ Test clone ▶” sits directly after “🔍 Find RVC folder”;
  7. PERFORMANCE is one header row with the two dials side by side;
  8. the page still fits, at four sizes, with nothing cut off at the right edge.

Screenshots land in ui-fit/. Run:  python3 pipeline/check_hd_ui.py
"""

from __future__ import annotations

import os
import sys

URL = os.environ.get("SONORA_URL", "http://127.0.0.1:8000/")
SIZES = ((1366, 768), (1600, 900), (1920, 1080), (2557, 1239))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "ui-fit")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("ok  " if ok else "FAIL", name, ("   " + detail) if detail else ""),
          flush=True)


#: exactly what the server puts into HD_STATE (see _hd_cleanup_clone)
HD_STATE = {
    "ok": True,
    "score_before": 77, "score_after": 83,
    "stages": ["noise reduction", "rumble filter 70 Hz"],
    "original": "job-abc123.original.wav",
    "hd": "enhanced_hd.wav",
    "previews": {"original": "/hd-preview/job-abc123/job-abc123.original.mp3",
                 "hd": "/hd-preview/job-abc123/job-abc123.hd.mp3"},
    "sr": 48000, "bits": 24, "lufs": -16.0, "true_peak_db": -1.0,
    "time": "2026-09-30 12:00:00",
}

#: the four cases the panel must offer, in order
CASES = (("01-normal", "A healthy take — almost nothing to fix"),
         ("01-normal-hiss", "A hiss floor — noise reduction"),
         ("01-normal-hum", "A 45 Hz hum — rumble filter"),
         ("01-normal-room", "A roomy take — de-reverb"))


def main():
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    asked = []

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1920, "height": 1080})
        pg.on("request", lambda r: asked.append(r.url) if "/hd-preview/" in r.url else None)
        # a preview that will not exist on the server: answer it locally so the
        # click can be verified without inventing a job
        pg.route("**/hd-preview/**", lambda route: route.fulfill(
            status=200, content_type="audio/mpeg", body=b"\xff\xfb\x90\x00" * 64))
        pg.goto(URL, wait_until="load")
        pg.wait_for_timeout(400)

        if not pg.query_selector("#hdRow"):
            print("FAIL #hdRow is not in the page — the studio being served is not this build")
            return 1

        # 1 · on the page, dimmed, unusable — while the clone is off
        check("the HD row is on the page while RVC VOICE CLONE is off",
              pg.is_visible("#hdRow"))
        op = pg.evaluate("() => getComputedStyle($('hdRow')).opacity")
        check("…shown at 75% opacity, not hidden", abs(float(op) - 0.75) < 0.02, "opacity " + op)
        check("…and its box is disabled (unusable)",
              pg.evaluate("() => $('hdEnable').disabled === true"))
        txt = pg.inner_text("#hdRow")
        check("it is named “HD / CLEAN KHMER VOICE”", "HD / CLEAN KHMER VOICE" in txt.upper(),
              txt.strip())
        check("and it says “Khmer only”", "KHMER ONLY" in txt.upper())
        check("hdEnabled() is false while the clone is off",
              pg.evaluate("() => hdEnabled()") is False)

        # ·· the four-case panel in the same state
        check("the four-case panel is on the page too", pg.is_visible("#hdPanel"))
        pop = pg.evaluate("() => getComputedStyle($('hdPanel')).opacity")
        check("…also at 75% opacity", abs(float(pop) - 0.75) < 0.02, "opacity " + pop)
        titles = [t.strip() for t in pg.eval_on_selector_all(
            "#hdPanel .hdcase-t", "els => els.map(e => e.textContent)")]
        check("it lists the four takes, in order",
              titles == [t for _, t in CASES], str(titles))
        nplay = pg.evaluate("() => document.querySelectorAll('#hdPanel .hdplay').length")
        check("each take has ▶ Original and ▶ HD Clean", nplay == 8, "%d button(s)" % nplay)
        check("…and every one of them is disabled until the clone is on",
              pg.evaluate("() => [...document.querySelectorAll('#hdPanel .hdplay')]"
                          ".every(b => b.disabled === true)"))
        asked.clear()
        pg.evaluate("() => document.querySelector('#hdPanel .hdplay').click()")
        pg.wait_for_timeout(250)
        check("a dead button really does nothing (no audio is fetched)",
              not [u for u in asked if "/hd_samples/" in u], str(asked[:2]))
        pg.screenshot(path=os.path.join(SHOTS, "ui-hd-0-clone-off.png"))

        # 2 · ticking the clone makes both live
        pg.check("#rvcEnable")
        pg.wait_for_timeout(300)
        row = pg.query_selector("#hdRow")
        chk = pg.query_selector("#rvcEnable")
        rb, cb = row.bounding_box(), chk.bounding_box()
        same_line = abs((rb["y"] + rb["height"] / 2) - (cb["y"] + cb["height"] / 2)) < 10
        op = pg.evaluate("() => getComputedStyle($('hdRow')).opacity")
        check("ticking RVC VOICE CLONE brings the row to full strength",
              abs(float(op) - 1.0) < 0.02, "opacity " + op)
        check("…and enables its box",
              pg.evaluate("() => $('hdEnable').disabled === false"))
        check("the row sits at the RIGHT of the clone checkbox",
              rb["x"] > cb["x"] + cb["width"] - 2 and same_line,
              "row x=%.0f vs checkbox x=%.0f (same line: %s)" % (rb["x"], cb["x"], same_line))
        check("the HD switch is on by default", pg.is_checked("#hdEnable"))
        check("hdEnabled() is true now", pg.evaluate("() => hdEnabled()") is True)
        ppo = pg.evaluate("() => getComputedStyle($('hdPanel')).opacity")
        check("the four-case panel goes live too",
              abs(float(ppo) - 1.0) < 0.02
              and pg.evaluate("() => [...document.querySelectorAll('#hdPanel .hdplay')]"
                              ".every(b => b.disabled === false)"), "opacity " + ppo)
        pg.screenshot(path=os.path.join(SHOTS, "ui-hd-1-row-on.png"))

        # ·· and the clips really play
        pg.evaluate("""() => { window.__hdDemo = [];
          const A = window.Audio;
          window.Audio = function (u) { window.__hdDemo.push(String(u)); return new A(u); }; }""")
        pg.click("#hdPanel .hdcase[data-case='01-normal-hum'] .hdplay[data-hd='hd']")
        pg.wait_for_timeout(300)
        played = pg.evaluate("() => window.__hdDemo || []")
        check("▶ HD Clean on the hum take asks for that HD clip",
              any("hd_samples/01-normal-hum.hd.mp3" in u for u in played), str(played)[:110])
        check("…with a cache-buster (a fresh take is never a stale one)",
              bool(played) and all("?t=" in u for u in played))
        pg.click("#hdPanel .hdcase[data-case='01-normal-hiss'] .hdplay[data-hd='original']")
        pg.wait_for_timeout(300)
        played = pg.evaluate("() => window.__hdDemo || []")
        check("▶ Original on the hiss take asks for the original clip",
              any("hd_samples/01-normal-hiss.original.mp3" in u for u in played), str(played)[:110])
        pg.screenshot(path=os.path.join(SHOTS, "ui-hd-2-cases.png"))

        # the checkbox it belongs to is the clone box, not the “Clean & Clear” one
        pg.uncheck("#rvcEnable")
        pg.wait_for_timeout(200)
        check("ticking the clone off dims it again (does not remove it)",
              pg.is_visible("#hdRow")
              and abs(float(pg.evaluate("() => getComputedStyle($('hdRow')).opacity")) - 0.75) < 0.02)
        pg.check("#rvcEnable")
        pg.wait_for_timeout(200)

        # 4/5 · a finished run, and the two preview buttons
        pg.evaluate("(s) => { $('rvcPanel').style.display = 'block'; showHdResult(s); }", HD_STATE)
        pg.wait_for_timeout(200)
        note = pg.inner_text("#hdNote")
        check("the result line reports the score and the stages",
              "77 → 83" in note and "noise reduction" in note.lower(), note[:90])
        check("it names the kept original and the HD master",
              HD_STATE["original"].lower() in note.lower() and "enhanced_hd.wav" in note.lower(),
              note[-60:])
        check("▶ Original and ▶ HD Clean are both up",
              pg.is_visible("#hdPlayA") and pg.is_visible("#hdPlayB"))
        pg.screenshot(path=os.path.join(SHOTS, "ui-hd-3-result.png"))

        # watch what the buttons hand to the audio element
        pg.evaluate("""() => { window.__hdAsked = [];
          const A = window.Audio;
          window.Audio = function (u) { window.__hdAsked.push(String(u)); return new A(u); }; }""")
        pg.click("#hdPlayB")
        pg.wait_for_timeout(250)
        pg.click("#hdPlayA")
        pg.wait_for_timeout(250)
        play = pg.evaluate("() => window.__hdAsked || []")
        base = [u.split("?")[0] for u in play]
        check("▶ HD Clean asks for the HD preview URL",
              HD_STATE["previews"]["hd"] in base, str(base))
        check("▶ Original asks for the original preview URL",
              HD_STATE["previews"]["original"] in base)
        check("both previews are cache-busted (a fresh take is never a stale one)",
              bool(base) and all("?t=" in u for u in play), str(play)[:90])

        # 6 · the fail-safe wording, exactly
        pg.evaluate("""() => showHdResult({ok:false, error:'ffmpeg: broken',
          note:'Enhancement unavailable; original TTS preserved.'})""")
        pg.wait_for_timeout(150)
        fail_note = pg.inner_text("#hdNote")
        check("a failed run shows the exact fallback sentence",
              "Enhancement unavailable; original TTS preserved." in fail_note
              and not pg.is_visible("#hdPlayA"), fail_note[:90])
        pg.screenshot(path=os.path.join(SHOTS, "ui-hd-4-failed.png"))

        # 7 · the two buttons, side by side, in the order asked for
        sb = pg.eval_on_selector("#rvcScan", "e => { const r = e.getBoundingClientRect();"
                                             " return {x:r.x, y:r.y, w:r.width, h:r.height}; }")
        tb = pg.eval_on_selector("#rvcTest", "e => { const r = e.getBoundingClientRect();"
                                             " return {x:r.x, y:r.y, w:r.width, h:r.height}; }")
        check("⟳ Test clone ▶ sits directly after 🔍 Find RVC folder",
              tb["x"] > sb["x"] + sb["w"] - 2 and abs((tb["y"] + tb["h"] / 2)
                                                      - (sb["y"] + sb["h"] / 2)) < 8,
              "scan x=%.0f w=%.0f · test x=%.0f" % (sb["x"], sb["w"], tb["x"]))
        check("the long clone paragraph is behind a summary, not in the way",
              pg.evaluate("() => { const d = [...document.querySelectorAll('details')]"
                          ".some(e => e.textContent.includes('how the clone and the base voice work'));"
                          " const shown = document.body.innerText.includes"
                          "('Crossing genders on purpose'); return d && !shown; }"))
        pg.screenshot(path=os.path.join(SHOTS, "ui-hd-5-buttons.png"))

        # 8 · PERFORMANCE: one header row, two dials side by side
        db = pg.eval_on_selector("#dialPause", "e => { const r = e.getBoundingClientRect();"
                                               " return {x:r.x, y:r.y, w:r.width, h:r.height}; }")
        sb2 = pg.eval_on_selector("#dialSpeed", "e => { const r = e.getBoundingClientRect();"
                                                " return {x:r.x, y:r.y, w:r.width, h:r.height}; }")
        check("PERFORMANCE keeps its one header row above the dials",
              pg.evaluate("() => document.querySelector('.perf-h').getBoundingClientRect().bottom"
                          " <= document.querySelector('.dial2').getBoundingClientRect().top + 1"))
        check("the two dials sit SIDE BY SIDE (this is the space saving)",
              sb2["x"] > db["x"] + db["w"] - 2 and abs(db["y"] - sb2["y"]) < 6,
              "pause x=%.0f w=%.0f · speed x=%.0f · y %.0f/%.0f"
              % (db["x"], db["w"], sb2["x"], db["y"], sb2["y"]))
        got = pg.evaluate("""() => { const a = document.querySelector('#dialPause input'); const b =
          document.querySelector('#dialSpeed input'); const n = v => Number(v.toFixed(2));
          const before = [n(+a.value), n(+b.value)];
          a.value = 0.6; a.dispatchEvent(new Event('input', {bubbles:true}));
          b.value = 1.2; b.dispatchEvent(new Event('input', {bubbles:true}));
          const out = [n(+$('pause').value), n(+$('speed').value),
                       $('pauseVal').textContent, $('speedVal').textContent];
          a.value = before[0]; a.dispatchEvent(new Event('input', {bubbles:true}));
          b.value = before[1]; b.dispatchEvent(new Event('input', {bubbles:true}));
          return out; }""")
        check("both dials still drive their values and read-outs",
              got[0] == 0.6 and got[1] == 1.2, str(got))
        pg.screenshot(path=os.path.join(SHOTS, "ui-fit-performance.png"))

        # 9 · the page still fits at four sizes
        for w, h in SIZES:
            pg.set_viewport_size({"width": w, "height": h})
            pg.wait_for_timeout(350)
            fit = pg.evaluate("""() => {
              const r = $('hdRow').getBoundingClientRect();
              const d = $('hdPanel').getBoundingClientRect();
              return {overflow: document.documentElement.scrollWidth - window.innerWidth,
                      right: Math.round(r.right), win: window.innerWidth,
                      w: Math.round(r.width), h: Math.round(r.height),
                      panelRight: Math.round(d.right), panelW: Math.round(d.width)};
            }""")
            check("%dx%d: the page fits and the whole HD row is on screen" % (w, h),
                  fit["overflow"] <= 1 and fit["right"] <= fit["win"] + 1 and fit["w"] > 120,
                  "row %.0fx%.0f at x→%d · page overflow %d px" % (fit["w"], fit["h"], fit["right"],
                                                                   fit["overflow"]))
            check("%dx%d: the four-case panel fits too" % (w, h),
                  fit["panelRight"] <= fit["win"] + 1 and fit["panelW"] > 150,
                  "panel %d px wide, right edge %d" % (fit["panelW"], fit["panelRight"]))
            pg.screenshot(path=os.path.join(SHOTS, "ui-hd-%dx%d.png" % (w, h)))
        b.close()

    print("\n%s\nHD UI: %d passed, %d failed" % ("=" * 74, len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
