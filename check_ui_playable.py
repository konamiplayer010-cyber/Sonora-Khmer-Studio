#!/usr/bin/env python3
"""check_ui_playable.py — does the self-contained page really work?

The playable page is a single file with the clips inside it. This opens it in a
real browser from the filesystem (no server) and asserts the rule the studio
enforces: dimmed + dead with the clone off, live with it on, and every ▶ hands
the right embedded clip to the audio element.

    python3 pipeline/check_ui_playable.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PAGE = os.environ.get("PLAYABLE", "/home/user/HD-UI-Playable.html")
SHOTS = os.path.join(ROOT, "ui-fit")
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("ok  " if ok else "FAIL", name, ("   " + detail) if detail else ""),
          flush=True)


def main():
    from playwright.sync_api import sync_playwright

    if not os.path.exists(PAGE):
        print("FAIL no page at %s — run pipeline/make_ui_playable.py" % PAGE)
        return 1
    os.makedirs(SHOTS, exist_ok=True)

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 900, "height": 1200})
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto("file://" + PAGE, wait_until="load")
        pg.wait_for_timeout(400)

        check("no javascript error on load", not errs, str(errs[:1]))

        # --- clone off ---
        op = pg.evaluate("() => getComputedStyle($('hdRow')).opacity")
        check("clone off: the row sits at 75% opacity", abs(float(op) - 0.75) < 0.02, op)
        check("clone off: the box is disabled", pg.evaluate("() => $('hdEnable').disabled === true"))
        pop = pg.evaluate("() => getComputedStyle($('hdPanel')).opacity")
        check("clone off: the panel is at 75% too", abs(float(pop) - 0.75) < 0.02, pop)
        check("clone off: every ▶ is disabled",
              pg.evaluate("() => [...document.querySelectorAll('#hdPanel .hdplay')]"
                          ".every(b => b.disabled === true)"))
        asked = pg.evaluate("""() => { window.__asked = [];
          const A = window.Audio;
          window.Audio = function (u) { window.__asked.push(String(u).slice(0, 30)); return new A(u); };
          return true; }""")
        pg.evaluate("() => document.querySelector('#hdPanel .hdplay').click()")
        pg.wait_for_timeout(250)
        check("clone off: pressing ▶ plays nothing",
              not pg.evaluate("() => window.__asked || []"),
              str(pg.evaluate("() => window.__asked || []"))[:40])
        pg.screenshot(path=os.path.join(SHOTS, "play-clone-off.png"))

        # --- clone on ---
        pg.check("#rvcEnable")
        pg.wait_for_timeout(300)
        op = pg.evaluate("() => getComputedStyle($('hdRow')).opacity")
        check("clone on: the row goes to full strength", abs(float(op) - 1.0) < 0.02, op)
        check("clone on: the box is enabled", pg.evaluate("() => $('hdEnable').disabled === false"))
        check("clone on: every ▶ is live",
              pg.evaluate("() => [...document.querySelectorAll('#hdPanel .hdplay')]"
                          ".every(b => b.disabled === false)"))
        pg.evaluate("""() => { window.__played = [];
          const A = window.Audio;
          window.Audio = function (u) { window.__played.push(String(u)); return new A(u); }; }""")
        pg.click("#hdPanel .hdcase[data-case='01-normal-hum'] .hdplay[data-hd='hd']")
        pg.wait_for_timeout(300)
        played = pg.evaluate("() => window.__played || []")
        check("▶ HD Clean plays an embedded clip (a data: URI, no network)",
              bool(played) and played[0].startswith("data:audio/mpeg;base64,"),
              (played[0][:40] + "…") if played else "nothing")
        check("…and it is really audio, not an empty string",
              len(played[0]) > 20000 if played else False,
              "%d chars" % (len(played[0]) if played else 0))
        pg.click("#hdPanel .hdcase[data-case='01-normal-hiss'] .hdplay[data-hd='original']")
        pg.wait_for_timeout(300)
        played = pg.evaluate("() => window.__played || []")
        check("a second take plays its own clip (both buttons work)",
              len(played) == 2 and played[1] != played[0])
        pg.screenshot(path=os.path.join(SHOTS, "play-clone-on.png"))

        # --- the four cases are all there, and the dials work ---
        titles = pg.eval_on_selector_all("#hdPanel .hdcase-t", "e => e.map(x => x.textContent.trim())")
        want = ["A healthy take — almost nothing to fix", "A hiss floor — noise reduction",
                "A 45 Hz hum — rumble filter", "A roomy take — de-reverb"]
        check("the four takes are listed, in order", titles == want, str(titles))
        check("eight buttons in total",
              pg.evaluate("() => document.querySelectorAll('#hdPanel .hdplay').length") == 8)
        got = pg.evaluate("""() => { $('pause').value = 0.6;
          $('pause').dispatchEvent(new Event('input')); $('speed').value = 1.2;
          $('speed').dispatchEvent(new Event('input'));
          return [$('pauseVal').textContent, $('speedVal').textContent]; }""")
        check("the two dials still read out", got == ["0.6s", "1.20×"], str(got))
        side = pg.evaluate("""() => { const a = document.querySelector('.dial').getBoundingClientRect();
          const d = document.querySelectorAll('.dial')[1].getBoundingClientRect();
          return d.x > a.right - 2 && Math.abs(a.y - d.y) < 6; }""")
        check("PERFORMANCE is side by side here too", side is True)
        b.close()

    print("\n%s\nplayable page: %d passed, %d failed" % ("=" * 74, len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
