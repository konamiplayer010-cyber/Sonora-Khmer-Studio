#!/usr/bin/env python3
"""test_style_demos.py — the 13 Narration Style cards and their ▶ clips.

What this guards (all three were real problems at some point):

  1. the studio page still renders 13 style cards, each with a ▶ button, and
     the panel sits ABOVE the PERFORMANCE dials with a divider between;
  2. every clip in sonora/public/style_demos/ exists, is 48 kHz / 192 kbps and
     lasts 8–26 seconds (a clip that is missing or 1 second long is useless);
  3. the demo voice is the one the user asked for: en-US-JennyNeural;
  4. THE CLIP IS THE STYLE, NOT THE LABEL (build 2026-09-29j): every clip is
     rendered through the studio's own engine (`narration.render_styled`), so
     each style performs at its own pace and its own softness — the clips must
     measure DIFFERENT from each other, and pitch must not move at all (the
     speaker never changes);
  5. build l: Bedtime is gone — the cards and the clips are 13, and every
     through whisper.py, and the shipped clip is measurably a whisper
     (unvoiced — the buzz is gone — chest weight gone, air present).

    python pipeline/test_style_demos.py
"""
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEMO_DIR = os.path.join(ROOT, "sonora", "public", "style_demos")
INDEX = os.path.join(ROOT, "sonora", "public", "index.html")
BUILDER = os.path.join(ROOT, "sonora", "style_demos.py")

OK, FAIL = [], []


def check(name, cond, extra=""):
    (OK if cond else FAIL).append(name)
    print("  [%s] %s%s" % ("OK  " if cond else "FAIL", name,
                           "  — " + str(extra) if extra else ""))


def _ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def info(path):
    """(seconds, sample_rate, kbps) or None when ffmpeg is unavailable."""
    exe = _ffmpeg()
    if not exe:
        return None
    r = subprocess.run([exe, "-hide_banner", "-i", path], capture_output=True, text=True)
    secs, rate, kbps = 0.0, 0, 0
    for line in r.stderr.split("\n"):
        line = line.strip()
        if line.startswith("Duration:"):
            t = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = t.split(":")
            secs = int(h) * 3600 + int(m) * 60 + float(s)
        elif "Audio:" in line and "Hz" in line:
            parts = line.replace(",", " ").split()
            for i, p in enumerate(parts):
                if p == "Hz" and i and parts[i - 1].isdigit():
                    rate = int(parts[i - 1])
                if p == "kb/s" and i and parts[i - 1].isdigit():
                    kbps = int(parts[i - 1])
    return secs, rate, kbps


print("1. the studio page: 13 cards, a ▶ each, above PERFORMANCE")
try:
    html = io.open(INDEX, encoding="utf-8").read()
except OSError as e:
    print("  cannot read %s (%s)" % (INDEX, e))
    sys.exit(1)

m = re.search(r"const STYLES = \[(.*?)\n\];", html, re.S)
check("the page carries a STYLES table again", bool(m))
ids = re.findall(r'\{id:"([a-z_]+)"', m.group(1)) if m else []
check("exactly 13 styles are defined", len(ids) == 13, ids)
check("Bedtime is gone (build l: the style and its voice were removed)",
      "bedtime" not in ids and 'id:"bedtime"' not in html
      and "bedtime" not in html.lower())
check("no card and no card text still promises a whisper (build n removed it)",
      "A whispered line stays" not in html and "s.whisper" not in html
      and "whisper chip" not in html)
check("the page counts 13 styles / 52 feelings, not the stale 14 / 56",
      "14 styles" not in html and "56 feelings" not in html,
      "found: %s" % ([t for t in ("14 styles", "56 feelings") if t in html] or "none"))
check("every card carries its own character line (what makes it different)",
      len(re.findall(r'trait:"', html)) == 13
      and 's.trait ? s.trait + " · " : ""' in html)
check("every card renders a ▶ button",
      'class="sttry"' in html and "playStyleDemo" in html)
check("the panel sits above PERFORMANCE with a divider",
      html.find('id="styles"') < html.find('id="dialPause"') and 'class="strule"' in html,
      "styles@%d dials@%d" % (html.find('id="styles"'), html.find('id="dialPause"')))
check("the heading is NARRATION STYLE", "NARRATION STYLE" in html)
check("the panel is drawn on load", "renderStyles();" in html)
check("the ▶ clips are served from style_demos/", 'style_demos/' in html)
check("the demo never touches the voice (no pitch/loudness in the card code)",
      "pitch" not in html.split("function playStyleDemo")[1][:400].lower())

print("\n2. the demo voice and the builder")
try:
    b = io.open(BUILDER, encoding="utf-8").read()
except OSError as e:
    b = ""
    print("  (cannot read %s: %s)" % (BUILDER, e))
check("the demo voice is en-US-JennyNeural (Jenny US · female)",
      'DEFAULT_VOICE = "en-US-JennyNeural"' in b)
check("the builder performs every clip with the studio engine",
      "NAR.render_styled(" in b and "import narration as NAR" in b
      and "PRESETS" in b and "WHISPER_DEMOS" in b and '"bedtime":' not in b)
check("the cinematic demo text describes the storyteller read",
      '"cinematic":' in b and "cinematic storytelling" in b.lower())
check("the builder asks for the service's best stream (24 kHz / 96 kbps)",
      "audio-24khz-96kbitrate-mono-mp3" in b)
check("the builder masters to 48 kHz / 192 kbps",
      "OUT_RATE = 48000" in b and "OUT_KBPS = 192" in b)
check("the builder normalises loudness (-16 LUFS)",
      "loudnorm=I=-16" in b)

print("\n3. the clips themselves")
missing = [s for s in ids if not os.path.exists(os.path.join(DEMO_DIR, s + ".mp3"))]
check("a clip exists for every style", not missing, missing)
extra = [f for f in os.listdir(DEMO_DIR) if f.endswith(".mp3")
         and f[:-4] not in ids] if os.path.isdir(DEMO_DIR) else []
check("no orphan clips in the folder", not extra, extra)

try:
    import numpy as np
except Exception:
    np = None
try:
    import imageio_ffmpeg  # noqa: F401
except Exception:
    pass

if _ffmpeg() and not missing:
    bad_dur, bad_fmt, durs = [], [], []
    for s in ids:
        got = info(os.path.join(DEMO_DIR, s + ".mp3"))
        secs, rate, kbps = got
        durs.append((s, secs))
        if not (8.0 <= secs <= 26.0):
            bad_dur.append((s, secs))
        if rate != 48000 or kbps < 160:
            bad_fmt.append((s, rate, kbps))
    check("every clip is 8–26 s (a spoken explanation, with real pauses)",
          not bad_dur, bad_dur)
    check("every clip is 48 kHz / ≥160 kbps", not bad_fmt, bad_fmt)
    # the Bedtime clip must be measurably a whisper, and an ordinary clip not
    if np is not None:
        def _band(path, rate=24000):
            r = subprocess.run([_ffmpeg(), "-v", "error", "-i", path, "-ac", "1",
                                "-ar", str(rate), "-f", "f32le", "pipe:1"],
                               capture_output=True)
            y = np.frombuffer(r.stdout, dtype=np.float32)
            n = min(len(y), 1 << 19)
            seg = y[:n] * np.hanning(n).astype(np.float32)
            sp = np.abs(np.fft.rfft(seg)) ** 2
            f = np.fft.rfftfreq(n, 1.0 / rate)
            tot = float(sp.sum()) or 1e-12
            return float(sp[f < 250.0].sum() / tot), float(sp[f > 2500.0].sum() / tot)
        try:
            lo_c, hf_c = _band(os.path.join(DEMO_DIR, "cinematic.mp3"))
            lo_a, hf_a = _band(os.path.join(DEMO_DIR, "audiobook.mp3"))
            check("the cinematic clip is a spoken read, not a whisper",
                  lo_c > 0.05 and hf_c < 0.25, "low %.4f, air %.3f" % (lo_c, hf_c))
            check("an ordinary narration clip is a spoken read too",
                  lo_a > 0.10 and hf_a < 0.12, "low %.4f, air %.3f" % (lo_a, hf_a))
            check("no shipped clip is a whole-piece whisper any more",
                  not os.path.exists(os.path.join(DEMO_DIR, "bedtime.mp3")))
        except Exception as _e:
            check("the clips could be measured", False, str(_e)[:80])

    shortest = min(durs, key=lambda x: x[1])
    longest = max(durs, key=lambda x: x[1])
    print("      %d clips, %.1f s – %.1f s (shortest %s, longest %s)"
          % (len(durs), shortest[1], longest[1], shortest[0], longest[0]))
else:
    print("  (ffmpeg not available in this copy — clip checks skipped)")

print("\n4. the all-13 Khmer demo (menu 9, one passage in every style)")
BUILDER2 = os.path.join(HERE, "build_style_demo.py")
DEMO_MP3 = os.path.join(HERE, "demo", "narration-styles.mp3")
DEMO_TXT = os.path.join(HERE, "demo", "narration-styles.txt")
PACK_MP3 = os.path.join(ROOT, "all-13-narration-styles.mp3")
PACK_TXT = os.path.join(ROOT, "all-13-narration-styles.txt")

try:
    bb = io.open(BUILDER2, encoding="utf-8").read()
except OSError:
    bb = ""
check("the Khmer demo builder exists and drives the real engine",
      "render_styled" in bb and "import narration as NAR" in bb
      and "--only" in bb)
_blk = re.search(r"^STYLES = \[(.*?)^\]", bb, re.S | re.M)
b_ids = re.findall(r'\("([a-z_]+)",', _blk.group(1)) if _blk else []
check("the builder carries all 13 styles, in panel order", b_ids == ids,
      b_ids if b_ids != ids else "")
check("the builder says each style performs its own way, same speaker",
      "its own way" in bb and "pitch stays at 0.0 st" in bb and "whisper.py" in bb)

d_info = info(DEMO_MP3)
check("the shipped Khmer demo exists", os.path.exists(DEMO_MP3))
if d_info:
    secs, rate, kbps = d_info
    check("the Khmer demo is one long file (all 13 segments)",
          200.0 <= secs <= 400.0 and rate == 48000 and kbps >= 160,
          "%.1f s, %d Hz, %d kbps" % (secs, rate, kbps))

rows = []
if os.path.exists(DEMO_TXT):
    for line in io.open(DEMO_TXT, encoding="utf-8"):
        mrow = re.match(r"^(\d+):(\d+\.\d+)\s+\S+\s+([a-z_]+)\s", line)
        if mrow:
            rows.append((int(mrow.group(1)) * 60 + float(mrow.group(2)),
                         mrow.group(3)))
check("the index lists all 13 segments", len(rows) == 13, len(rows))
check("the index names them in the panel order",
      [r[1] for r in rows] == ids, [r[1] for r in rows] if rows else "")

if d_info and rows and _ffmpeg():
    try:
        import numpy as np
        bed_t = dict((sid, t) for t, sid in rows)
        nxt = dict(zip([r[1] for r in rows],
                       [r[0] for r in rows[1:]] + [d_info[0]]))
        def seg_band(sid, head=1.5, tail=1.0):
            t0 = bed_t[sid] + head
            t1 = min(nxt[sid] - tail, t0 + 9.0)
            r = subprocess.run([_ffmpeg(), "-v", "error", "-ss", str(t0),
                                "-to", str(t1), "-i", DEMO_MP3, "-ac", "1",
                                "-ar", "24000", "-f", "f32le", "pipe:1"],
                               capture_output=True)
            y = np.frombuffer(r.stdout, dtype=np.float32)
            n = min(len(y), 1 << 19)
            seg = y[:n] * np.hanning(n).astype(np.float32)
            sp = np.abs(np.fft.rfft(seg)) ** 2
            f = np.fft.rfftfreq(n, 1.0 / 24000)
            tot = float(sp.sum()) or 1e-12
            return float(sp[f < 250.0].sum() / tot), float(sp[f > 2500.0].sum() / tot)
        lo_c, hf_c = seg_band("cinematic")
        lo_n, hf_n = seg_band("natural")
        check("the cinematic segment is a spoken storyteller read",
              lo_c > 0.03 and hf_c < 0.30, "low %.4f, air %.3f" % (lo_c, hf_c))
        check("the Natural-read segment is a plain read",
              lo_n > 0.05 and hf_n < 0.15, "low %.4f, air %.3f" % (lo_n, hf_n))
    except Exception as _e:
        check("the Khmer demo segments could be measured", False, str(_e)[:80])

if os.path.exists(PACK_MP3):
    p_info = info(PACK_MP3)
    ptxt = io.open(PACK_TXT, encoding="utf-8").read() if os.path.exists(PACK_TXT) else ""
    n_rows = len(re.findall(r"^\d+:\d+\.\d+\s", ptxt, re.M))
    check("the English pack exists (13 panel clips, in order)",
          bool(p_info) and 150.0 <= p_info[0] <= 260.0 and p_info[1] == 48000
          and p_info[2] >= 160 and n_rows == 13,
          "%s / %d rows" % (p_info, n_rows))
else:
    check("the English pack exists (13 panel clips, in order)", False,
          "all-13-narration-styles.mp3 missing from the package root")

print("\n5. each clip is its own performance (the 'they all sound the same' fix)")
PERF = os.path.join(DEMO_DIR, "performance.json")
try:
    perf = json.load(io.open(PERF, encoding="utf-8"))
except Exception as e:
    perf = []
    print("  (no performance.json: %s — run: cd sonora && python style_demos.py)" % e)
check("every shipped clip reports what it did (performance.json)",
      len(perf) == 13, "%d entries" % len(perf))
if len(perf) == 13:
    paces = {i["style"]: i["pace"] for i in perf}
    gains = {i["style"]: i["softness_db"] for i in perf}
    pauses = {i["style"]: i["pauses_s"] for i in perf}
    check("every style performed at its OWN pace (a wide spread, not one number)",
          max(paces.values()) - min(paces.values()) >= 0.15,
          "%.2fx (news) … %.2fx (meditation)"
          % (max(paces.values()), min(paces.values())))
    check("…and at its own softness",
          max(gains.values()) - min(gains.values()) >= 1.0,
          "%+.1f dB (trailer) … %+.1f dB (meditation)"
          % (max(gains.values()), min(gains.values())))
    check("…and with its own pauses (a fifth of a second … twelve seconds)",
          max(pauses.values()) / max(0.01, min(pauses.values())) >= 10,
          "%.2fs … %.2fs" % (min(pauses.values()), max(pauses.values())))
    check("the SPEAKER never changes: pitch 0.0 in all 13 clips",
          all(abs(i["pitch_st"]) < 1e-9 for i in perf),
          sorted({i["pitch_st"] for i in perf}))
    f0 = [i["f0_hz"] for i in perf if i["f0_hz"] > 0]
    check("the measured voice frequency agrees (same speaker, ±15%)",
          bool(f0) and (max(f0) - min(f0)) / max(f0) <= 0.15,
          "F0 %.0f–%.0f Hz across %d spoken clips" % (min(f0), max(f0), len(f0)))
    check("the slow styles really are the slow ones",
          min(paces, key=paces.get) == "meditation"
          and max(paces, key=paces.get) == "news",
          "slowest %s, fastest %s" % (min(paces, key=paces.get),
                                      max(paces, key=paces.get)))
    check("meditation is the softest clip of the 13 (Bedtime is gone)",
          min(gains, key=gains.get) == "meditation",
          "softest: %s" % min(gains, key=gains.get))
    check("every clip names a real feeling from its own style",
          all(i["deliveries"] for i in perf))

print("\nstyle demos: %d passed, %d failed" % (len(OK), len(FAIL)))
for f in FAIL:
    print("  FAILED:", f)
sys.exit(1 if FAIL else 0)
