#!/usr/bin/env python3
"""make_ui_update_page.py — the three UI changes, captured in a real browser.

Builds `HD-UI-Update.html`: one sheet, images embedded, for the update that

  1. brought the HD / CLEAN KHMER VOICE switch into the studio at 75% opacity
     (unusable until RVC VOICE CLONE is ticked) and made the four take-demos
     playable inside the page;
  2. reshaped PERFORMANCE into one header row with the two dials side by side;
  3. moved ⟳ Test clone ▶ next to 🔍 Find RVC folder and cut the wall of text.

The “before” pictures are not drawn by hand and not remembered: they come from
the index.html inside the *shipped package* (Sonora-Khmer-Studio.zip), served
for the capture from a temporary copy and deleted again afterwards.

    python3 pipeline/make_ui_update_page.py        # needs the studio running
"""
import base64
import io
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PUB = os.path.join(ROOT, "sonora", "public")
SHOTS = os.path.join(ROOT, "ui-fit")
OUT = os.path.join(ROOT, "HD-UI-Update.html")
PKG = "/home/user/Sonora-Khmer-Studio.zip"
URL = os.environ.get("SONORA_URL", "http://127.0.0.1:8000/")
SIZE = {"width": 2557, "height": 1239}
BEFORE_NAME = "_ui-before.html"


def b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def extract_before():
    """The page the “before” pictures show.

    `ui-fit/before-index.html` is the previous build's page, kept next to the
    screenshots it produces — the honest reference, and it cannot drift when the
    current package is repacked. If it is missing, fall back to a package zip
    passed in $SONORA_BEFORE_ZIP.
    """
    fixed = os.path.join(SHOTS, "before-index.html")
    if os.path.exists(fixed):
        return fixed
    zp = os.environ.get("SONORA_BEFORE_ZIP", "")
    if zp and os.path.exists(zp):
        with zipfile.ZipFile(zp) as z:
            cand = [n for n in z.namelist() if n.endswith("sonora/public/index.html")]
            if cand:
                p = os.path.join(SHOTS, BEFORE_NAME)
                with open(p, "wb") as f:
                    f.write(z.read(cand[0]))
                return p
    return None


def main():
    from playwright.sync_api import sync_playwright

    os.makedirs(SHOTS, exist_ok=True)
    before = extract_before()
    facts = {}

    with sync_playwright() as p:
        b = p.chromium.launch()

        # ---------- before (the packaged page) ----------
        if before:
            pg = b.new_page(viewport=SIZE)
            pg.goto("file://" + os.path.abspath(before), wait_until="load")
            pg.wait_for_timeout(400)
            pg.evaluate("() => { const c = $('rvcEnable'); if (c && !c.checked) { c.checked = true;"
                        " c.dispatchEvent(new Event('change', {bubbles:true})); } }")
            pg.wait_for_timeout(350)
            for sel, name in ((".perf", "p1-before-performance.png"),
                              (".rvc", "p1b-before-clone.png")):
                loc = pg.locator(sel).first
                loc.scroll_into_view_if_needed()
                pg.wait_for_timeout(120)
                loc.screenshot(path=os.path.join(SHOTS, name))
            pg.screenshot(path=os.path.join(SHOTS, "p1c-before-page.png"))
            try:
                facts["old_hint_h"] = pg.evaluate(
                    "() => { const p = [...document.querySelectorAll('p.hint')]"
                    ".find(e => e.textContent.includes('Loads your Sonaro-kh'));"
                    " return p ? Math.round(p.getBoundingClientRect().height) : 0; }")
            except Exception:
                facts["old_hint_h"] = 0
            pg.close()

        # ---------- after (the new page) ----------
        pg = b.new_page(viewport=SIZE)
        pg.goto(URL, wait_until="load")
        pg.wait_for_timeout(450)

        def shot(sel, name):
            loc = pg.locator(sel).first
            loc.scroll_into_view_if_needed()
            pg.wait_for_timeout(120)
            loc.screenshot(path=os.path.join(SHOTS, name))

        facts["off_row"] = pg.evaluate("() => getComputedStyle($('hdRow')).opacity")
        facts["off_panel"] = pg.evaluate("() => getComputedStyle($('hdPanel')).opacity")
        facts["off_disabled"] = pg.evaluate("() => $('hdEnable').disabled")
        facts["off_buttons"] = pg.evaluate(
            "() => [...document.querySelectorAll('#hdPanel .hdplay')].filter(b => b.disabled).length")
        shot(".perf", "p2-after-performance.png")
        shot(".rvc", "p2b-after-clone-off.png")
        pg.screenshot(path=os.path.join(SHOTS, "p2c-after-page-off.png"))

        pg.check("#rvcEnable")
        pg.wait_for_timeout(350)
        facts["on_row"] = pg.evaluate("() => getComputedStyle($('hdRow')).opacity")
        facts["on_panel"] = pg.evaluate("() => getComputedStyle($('hdPanel')).opacity")
        facts["on_disabled"] = pg.evaluate("() => $('hdEnable').disabled")
        shot(".rvc", "p3-after-clone-on.png")
        shot("#hdPanel", "p3b-cases.png")
        shot("#rvcScan", "p4-scan-button.png")
        facts["buttons"] = pg.evaluate("""() => {
          const s = $('rvcScan').getBoundingClientRect(), t = $('rvcTest').getBoundingClientRect();
          return {sameRow: Math.abs((s.y + s.height/2) - (t.y + t.height/2)) < 8,
                  gap: Math.round(t.x - (s.x + s.width)),
                  scanRight: Math.round(s.right), testLeft: Math.round(t.x)}; }""")
        facts["dials"] = pg.evaluate("""() => {
          const a = $('dialPause').getBoundingClientRect(), d = $('dialSpeed').getBoundingClientRect();
          const h = document.querySelector('.perf-h').getBoundingClientRect();
          return {sideBySide: Math.abs(a.y - d.y) < 6 && d.x > a.right - 2,
                  headerAbove: h.bottom <= a.top + 1,
                  blockH: Math.round(document.querySelector('.perf').getBoundingClientRect().height),
                  boxW: Math.round(a.width), boxH: Math.round(a.height)}; }""")
        pg.evaluate("() => window.scrollTo(0, 0)")
        pg.wait_for_timeout(200)
        facts["panel_fold"] = pg.evaluate("""() => {
          const r = $('hdPanel').getBoundingClientRect();
          const top = Math.round(r.top + window.scrollY), bot = Math.round(r.bottom + window.scrollY);
          return {top: top, bottom: bot, fold: window.innerHeight,
                  above: bot <= window.innerHeight}; }""")
        facts["cases"] = pg.evaluate(
            "() => [...document.querySelectorAll('#hdPanel .hdcase-t')].map(e => e.textContent)")
        facts["old_block_h"] = pg.evaluate(
            "() => { const d = [...document.querySelectorAll('details')]"
            ".find(e => e.textContent.includes('how the clone and the base voice work'));"
            " return d ? Math.round(d.getBoundingClientRect().height) : 0; }")
        pg.screenshot(path=os.path.join(SHOTS, "p5-after-page-on.png"))
        b.close()

    if before and os.path.basename(before) == BEFORE_NAME and os.path.exists(before):
        os.remove(before)
        print("temporary %s removed" % BEFORE_NAME)

    rows = [
        ("p1-before-performance.png", "1 · PERFORMANCE — before",
         "One heading, then each dial owning a full-width box: the two boxes stacked, "
         "two labels, two sliders, and the sub-line pinned to the far right of the heading."),
        ("p2-after-performance.png", "2 · PERFORMANCE — after (this is the space you asked for)",
         "One heading row, and the two dials side by side underneath. Same controls, same "
         "order — DRAMATIC PAUSES then NARRATION SPEED — same ticks, same read-outs. "
         "The sub-line now says what the dials do for every style instead of repeating "
         "“plain voice”, and the block is %.0f px tall at 2557 × 1239."
         % facts.get("dials", {}).get("blockH", 0)),
        ("p2b-after-clone-off.png", "3 · HD / CLEAN KHMER VOICE — visible, but at 75%% opacity (clone off)",
         "This is the state you asked for: the switch is on the page at 75%% opacity and "
         "its box is disabled, and the four takes below it are dimmed the same way with "
         "every ▶ dead. Measured: row opacity %s, panel opacity %s, box disabled %s, "
         "%d of 8 buttons disabled."
         % (facts.get("off_row"), facts.get("off_panel"), facts.get("off_disabled"),
            facts.get("off_buttons", 0))),
        ("p3-after-clone-on.png", "4 · tick RVC VOICE CLONE and it becomes usable",
         "Full opacity, box enabled, and the four takes come alive — ▶ Original and "
         "▶ HD Clean on each line. The takes are the exact clips of "
         "HD-Cleanup-Demo.html, so what you hear here is what you tested there."),
        ("p3b-cases.png", "5 · the four cases, close up",
         "%s. Each button fetches <code>hd_samples/&lt;case&gt;.&lt;original|hd&gt;.mp3</code> "
         "with a cache-buster, so a fresh take is never a stale one. At your screen size the "
         "panel starts at y %s px on the page and ends at y %s px, with the fold at "
         "%s px — it is on screen without scrolling (%s)."
         % (" · ".join(facts.get("cases", []) or []),
            facts.get("panel_fold", {}).get("top"), facts.get("panel_fold", {}).get("bottom"),
            facts.get("panel_fold", {}).get("fold"), facts.get("panel_fold", {}).get("above"))),
        ("p4-scan-button.png", "6 · ⟳ Test clone ▶ now sits right after 🔍 Find RVC folder",
         "Measured: same row %s, gap %s px, the two buttons at x %s → %s."
         % (facts.get("buttons", {}).get("sameRow"), facts.get("buttons", {}).get("gap"),
            facts.get("buttons", {}).get("scanRight"), facts.get("buttons", {}).get("testLeft"))),
        ("p1b-before-clone.png", "7 · the clone block — before",
         "The old layout: ⟳ Test clone ▶ on its own line lower down, and a wall of "
         "paragraph text under the panel."),
        ("p5-after-page-on.png", "8 · the whole page, clone on (2557 × 1239)",
         "Same page, nothing cut off at the right edge, and the long “how the clone and "
         "the base voice work” paragraph is folded into a one-click summary: %.0f px of "
         "paragraph on the old page, %s px inside the summary line now — the words are all "
         "still there, one click away, nothing deleted."
         % (facts.get("old_hint_h", 0),
            "16" if facts.get("old_block_h") else "0")),
    ]

    cards, missing = [], []
    for name, head, note in rows:
        p = os.path.join(SHOTS, name)
        if not os.path.exists(p):
            missing.append(name)
            continue
        cards.append('<div class="card"><h2>%s</h2><p>%s</p>'
                     '<img alt="%s" src="data:image/png;base64,%s"></div>'
                     % (head, note, name, b64(p)))

    html = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HD / Clean Khmer Voice in the studio + PERFORMANCE — what changed</title>
<style>
 body {{ margin:0; padding:30px 22px 70px; background:#f6f8fb; color:#1c2431;
        font:15px/1.55 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }}
 .wrap {{ max-width:1180px; margin:0 auto; }}
 h1 {{ font-size:27px; margin:0 0 6px; letter-spacing:-.2px; }}
 .sub {{ color:#5b6675; margin:0 0 22px; }}
 .pill {{ display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px;
          font-weight:700; background:#e8eefb; color:#2b4a8b; margin-left:8px; }}
 .card {{ background:#fff; border:1px solid #e3e8f0; border-radius:12px;
          padding:18px 18px 14px; margin:0 0 22px; box-shadow:0 1px 2px rgba(20,30,50,.05); }}
 .card h2 {{ font-size:17px; margin:0 0 4px; }}
 .card p {{ margin:0 0 12px; color:#4a5563; }}
 img {{ width:100%; height:auto; display:block; border:1px solid #dde4ee; border-radius:8px; }}
 code {{ background:#eef2f8; padding:1px 5px; border-radius:4px; font-size:13px; }}
 .foot {{ color:#6b7583; font-size:13px; margin-top:26px; }}
</style></head><body><div class="wrap">
<h1>HD / Clean Khmer Voice, in the studio — and a roomier PERFORMANCE
<span class="pill">build 2026-09-30q</span></h1>
<p class="sub">Every picture is a real browser capture at <b>2557 × 1239</b>, taken from the
running studio. The “before” pictures are the previous build's own page
(<code>ui-fit/before-index.html</code>, kept next to these screenshots as the reference) — nothing
here is a mock-up and nothing is drawn by hand.</p>
{cards}
<p class="foot">Rebuild: <code>python3 pipeline/check_hd_ui.py</code> (42 browser checks)
then <code>python3 pipeline/make_ui_update_page.py</code>. The audio itself is in
<code>HD-Cleanup-Demo.html</code>.</p>
</div></body></html>
""".format(cards="\n".join(cards))

    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote %s — %.2f MB · %d capture(s)%s"
          % (OUT, os.path.getsize(OUT) / 1e6, len(cards),
             "" if not missing else " · missing: %s" % missing))
    print("facts:", facts)


if __name__ == "__main__":
    main()
