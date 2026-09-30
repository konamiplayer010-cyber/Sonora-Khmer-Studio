# -*- coding: utf-8 -*-
"""expressive delivery — the *inside* of a sentence (build 2026-09-29k).

The delivery layer (`narration.STYLE_DELIVERY`) decides pace, softness and
pauses **between** sentences. That is not enough for the two styles the user
asked to rework: a real storyteller also shapes **inside** one sentence — the
line swells into its emphasis beat, the beat itself is a touch brighter and
closer, and the sentence eases away instead of stopping dead.

That is all this module does. It never touches the speaker: no pitch change,
no formant change, no timbre swap. It is a slow level arc plus a band-lifted
emphasis beat, applied on one sentence at a time, so:

* the words stay exactly as intelligible as the engine said them,
* nothing is time-stretched (no phase-vocoder wobble, no "chipmunk"),
* the result is still the same recognisable voice, only *performed*.

Enabled for the styles the user named (Emotional Cinematic Storytelling,
Bedtime). The rest of the table is written down but switched off, so enabling
one later is a one-line change and never a surprise.
"""

from __future__ import annotations

import numpy as np

#: presence band — the "storyteller closeness" band. Above the chest, below
#: the sibilance: lift it and the voice sounds nearer and clearer (HD), never
#: brighter and never hissy.
PRESENCE_BAND = (2200.0, 5200.0)

#: one entry per style. `None` = untouched (see the module docstring: only the
#: two styles the user named are switched on).
EXPRESS = {
    # --- switched ON (update #3) ------------------------------------------
    "cinematic": dict(
        on=True,
        swell_db=1.35,       # the line builds INTO its emphasis beat …
        beat_db=0.45,        # … which is the loudest moment of the sentence
        ease_db=-2.30,       # and then eases away (— "trailing off")
        presence_db=1.50,    # the beat itself is closer and clearer
        presence_floor_db=0.35,   # a constant sliver of that clarity, all line
        ease_s=0.42,
        alt_db=0.35,         # sentence-to-sentence variation (never a metronome)
        min_words=5),
    "bedtime": dict(
        on=True,
        swell_db=0.45,       # a whisper barely swells — it softens and fades
        beat_db=0.10,
        ease_db=-2.15,
        presence_db=0.0,     # no brightness in a whisper: that turns to hiss
        presence_floor_db=0.0,
        ease_s=0.60,
        alt_db=0.15,
        min_words=4),
    # --- written down, switched OFF (kept out of this update) -------------
    "storytelling": dict(swell_db=0.55, ease_db=-1.10, presence_db=0.70,
                         presence_floor_db=0.15, ease_s=0.34, alt_db=0.25,
                         min_words=5),
    "novel": dict(swell_db=0.40, ease_db=-1.00, presence_db=0.45,
                  presence_floor_db=0.10, ease_s=0.30, alt_db=0.20, min_words=5),
    "sad_romantic": dict(swell_db=0.50, ease_db=-1.70, presence_db=0.40,
                         presence_floor_db=0.10, ease_s=0.48, alt_db=0.20,
                         min_words=5),
    "inner_monologue": dict(swell_db=0.40, ease_db=-1.30, presence_db=0.35,
                            presence_floor_db=0.10, ease_s=0.40, alt_db=0.18,
                            min_words=4),
    "meditation": dict(swell_db=0.25, ease_db=-1.40, presence_db=0.0,
                       presence_floor_db=0.0, ease_s=0.60, alt_db=0.10,
                       min_words=4),
    "trailer": dict(swell_db=1.60, ease_db=-0.90, presence_db=1.30,
                    presence_floor_db=0.20, ease_s=0.30, alt_db=0.45, min_words=4),
}

#: Safety rails — the arc can never swing harder than this, whatever a caller
#: passes in. A "reworked voice" must never turn into a pumping effect.
SWELL_CAP_DB = 2.0
BEAT_CAP_DB = 1.0
EASE_CAP_DB = -3.0
FLOOR_CAP_DB = 1.0
BEAT_DB_CAP = 2.5
HOP_MS = 5.0
SMOOTH_MS = 90.0
BEAT_SIGMA_S = 0.28


def plan(style):
    """The expressive plan for one style, or ``None`` when it is untouched."""
    sid = _sid(style)
    p = EXPRESS.get(sid)
    if p is None:
        return None
    if not p.get("on"):                      # written down, but switched off
        return None
    out = dict(p)
    out["swell_db"] = min(SWELL_CAP_DB, max(0.0, out.get("swell_db", 0.0)))
    out["beat_db"] = min(BEAT_CAP_DB, max(0.0, out.get("beat_db", 0.0)))
    out["ease_db"] = max(EASE_CAP_DB, min(0.0, out.get("ease_db", 0.0)))
    out["presence_floor_db"] = min(FLOOR_CAP_DB,
                                   max(0.0, out.get("presence_floor_db", 0.0)))
    out["presence_db"] = min(BEAT_DB_CAP, max(0.0, out.get("presence_db", 0.0)))
    out["style"] = sid
    return out


def _sid(style):
    try:
        import narration as _N
        return _N.style_id(style)
    except Exception:
        return str(style or "").strip().lower().replace("-", "_").replace(" ", "_")


def _env(x, rate, hop_ms=HOP_MS):
    """Short-time RMS envelope (float32) + the hop in samples."""
    hop = max(1, int(rate * hop_ms / 1000.0))
    n = int(np.ceil(x.size / float(hop)))
    pad = n * hop - x.size
    if pad:
        x = np.concatenate([x, np.zeros(pad, np.float32)])
    fr = x.reshape(n, hop)
    return np.sqrt(np.mean(fr.astype(np.float64) ** 2, axis=1)).astype(np.float32), hop


def _smooth_db(db, rate, hop, win_ms=SMOOTH_MS):
    """Move-average a dB curve (hops) so every gain change is clickless."""
    w = max(1, int(win_ms / HOP_MS))
    if w > 1 and db.size > w:
        k = np.ones(w, np.float32) / float(w)
        db = np.convolve(db, k, mode="same")
    return db


def _arc(env, hop, rate, p, index, words):
    """The dB arc for one sentence: build → beat → ease away."""
    total = env.size
    if total < 3:
        return np.zeros(total, np.float32), None
    loud = float(env.max()) or 1e-9
    voiced = np.where(env > 0.08 * loud)[0]
    if voiced.size < 3:
        return np.zeros(total, np.float32), None
    a, b = int(voiced[0]), int(voiced[-1])

    # the emphasis beat: the loudest 250 ms inside the voiced span
    win = max(1, int(0.25 * rate / hop))
    best, beat = -1.0, a
    for i in range(a, max(a + 1, b - win)):
        seg = float(env[i:i + win].mean())
        if seg > best:
            best, beat = seg, i
    arc = np.zeros(total, np.float32)

    swell = p["swell_db"] * (1.0 if words >= p["min_words"] else 0.4)
    lift = p["beat_db"] * (1.0 if words >= p["min_words"] else 0.5)
    # 1) from the first word to the beat: the line builds to its loudest moment
    if beat > a:
        arc[a:beat] = np.linspace(-swell, lift, beat - a, dtype=np.float32)
    arc[beat] = lift
    # 2) from the beat to the last word: ease away
    ease = p["ease_db"] * (1.0 if words >= p["min_words"] else 0.5)
    if b > beat:
        arc[beat:b] = np.linspace(lift, ease, b - beat, dtype=np.float32)
    arc[b:] = ease
    # 3) the tail — the last 0.38–0.55 s of the take fades out, not stops
    tail = max(1, int(p["ease_s"] * rate / hop))
    if b > tail and ease < -0.2:
        seg = np.linspace(0.0, ease * 0.85, tail, dtype=np.float32)
        arc[b - tail:b] = np.minimum(arc[b - tail:b], seg)
    # 4) never the same twice: alternate sentences sit a hair apart
    alt = p["alt_db"] if index % 2 else -p["alt_db"] * 0.6
    arc = arc + np.float32(alt)
    return _smooth_db(arc, rate, hop), beat


def _presence(arr, rate, beat_s, floor_db, beat_db):
    """Lift the presence band by `floor_db` everywhere and `beat_db` on the beat."""
    if floor_db <= 0.0 and beat_db <= 0.0:
        return arr
    n_fft = 1024 if arr.size > 4096 else 512
    hop = n_fft // 4
    win = np.hanning(n_fft).astype(np.float32)
    total = n_fft + ((arr.size + n_fft - 1) // hop) * hop
    pad = np.concatenate([arr, np.zeros(total - arr.size, np.float32)])
    nfr = 1 + (total - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(nfr)[:, None]
    frames = pad[idx] * win[None, :]
    spec = np.fft.rfft(frames, axis=1)
    f = np.fft.rfftfreq(n_fft, 1.0 / float(rate))
    band = (f >= PRESENCE_BAND[0]) & (f <= PRESENCE_BAND[1])
    # the beat bump lives on the FRAME grid (one value per STFT frame)
    tf = (np.arange(nfr, dtype=np.float32) * hop + n_fft * 0.5) / float(rate)
    bump = np.exp(-((tf - float(beat_s)) / BEAT_SIGMA_S) ** 2).astype(np.float32)
    g_db = floor_db + beat_db * bump                       # (nfr,)
    g = 10.0 ** (g_db / 20.0)
    g = (1.0 + (g - 1.0)[:, None] * band[None, :].astype(np.float32))
    spec = spec * g
    out = np.fft.irfft(spec, n=n_fft, axis=1) * win[None, :]
    # overlap-add
    buf = np.zeros(total, np.float32)
    wsum = np.zeros(total, np.float32)
    for i in range(nfr):
        s = i * hop
        buf[s:s + n_fft] += out[i]
        wsum[s:s + n_fft] += win * win
    buf = buf / np.maximum(wsum, 1e-8)
    return buf[:arr.size]


def expressize(arr, rate=24000, style="cinematic", index=0, words=None,
               stats=None, log=None):
    """Perform one sentence the expressive way. Returns a float32 array.

    Same length, same speaker, same words — the line just leans into its
    emphasis beat, sounds a little closer there, and eases off at the end.
    A style with no expressive plan (or one that is switched off) gets its
    audio back completely untouched.
    """
    p = plan(style)
    if p is None:
        return arr
    x = np.asarray(arr, dtype=np.float32).reshape(-1)
    if x.size < int(0.25 * rate):            # too short to shape: leave it
        return x
    n_words = int(words) if words else _count_words(x, rate)
    env, hop = _env(x, rate)
    arc, beat = _arc(env, hop, rate, p, index, n_words)
    if beat is None:
        return x

    # ---- the level arc, on the sample grid -------------------------------
    t = np.arange(x.size, dtype=np.float32) / float(rate)
    ha = np.arange(arc.size, dtype=np.float32) * (hop / float(rate))
    gain_db = np.interp(t, ha, arc).astype(np.float32)
    y = x * (10.0 ** (gain_db / 20.0))

    # ---- the presence lift on the beat -----------------------------------
    if p["presence_db"] > 0.0 or p["presence_floor_db"] > 0.0:
        y = _presence(y, rate, beat * hop / float(rate),
                      p["presence_floor_db"], p["presence_db"])

    # ---- keep it clean ----------------------------------------------------
    peak = float(np.max(np.abs(y))) or 1.0
    if peak > 0.98:
        y = y * (0.98 / peak)
    y = np.nan_to_num(y, nan=0.0, posinf=0.98, neginf=-0.98).astype(np.float32)

    if stats is not None:
        stats.update({"style": p["style"], "swell_db": round(float(arc.max()), 3),
                      "ease_db": round(float(arc.min()), 3), "words": n_words,
                      "beat_s": round(beat * hop / float(rate), 2),
                      "presence_db": p["presence_db"],
                      "presence_floor_db": p["presence_floor_db"]})
        if log:
            log("[express] %s: %.2f dB build → beat @%.2fs → %.2f dB ease"
                % (p["style"], stats["swell_db"], stats["beat_s"], stats["ease_db"]))
    return y


def _count_words(x, rate):
    """Rough word count from the modulation of the envelope (no ASR needed)."""
    env, _ = _env(x, rate, hop_ms=10.0)
    if env.size < 4:
        return 0
    loud = float(env.max()) or 1e-9
    on = env > 0.22 * loud
    # a word ≈ one burst: count the rises
    rises = int(np.sum((~on[:-1]) & on[1:])) + (1 if on[0] else 0)
    return max(1, rises)


def table():
    """Text table of the expressive plans (used by the docs and the tests)."""
    rows = ["style              state   build    ease   presence  floor  beat-pauses"]
    for sid in sorted(EXPRESS):
        p = EXPRESS[sid]
        if not p.get("on"):
            rows.append(f"{sid:18s} off     —        —      —         —      —")
            continue
        rows.append("%-18s on      %+.2f dB  %+.2f dB  %+.2f dB   %+.2f dB  %d words min"
                    % (sid, min(SWELL_CAP_DB, p["swell_db"]),
                       max(EASE_CAP_DB, p["ease_db"]), p["presence_db"],
                       p["presence_floor_db"], p["min_words"]))
    return "\n".join(rows)


if __name__ == "__main__":
    print(table())
