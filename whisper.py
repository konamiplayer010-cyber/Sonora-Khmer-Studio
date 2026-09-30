#!/usr/bin/env python3
"""whisper.py — the whisper stage (the brief whisper MOMENTS of a style).

Whisper is a DELIVERY effect, not a second voice.

WHAT MAKES IT SOUND WHISPERED
-----------------------------
A spoken sentence has a *buzz*: the vocal folds fire ~200 times a second, so
the spectrum is a comb — a stack of harmonics under the formants. A real
whisper has the same formants but **no comb**: the air passes the mouth
without the folds firing. So the ear hears "whisper" when

    1. the chest weight below ~250 Hz is gone          (no body in the voice)
    2. the harmonic comb is gone                       (no buzz — this is the
                                                        one that matters)
    3. the air band (2–6 kHz) carries the words        (breath, not hiss)
    4. the pauses stay *silent*                        (no noise floor)

Version 1 of this file did (1) and (3) but kept the comb and mixed a flat
hiss on top — which is exactly why it sounded like "a normal voice with
static". Version 2 (this file) synthesises a true breath-excited voice:

    * STFT (42 ms frames, 75 % overlap)
    * the magnitude is smoothed along frequency, which removes the harmonic
      comb but keeps the formant envelope — the words stay intelligible
    * the phase is replaced by a slowly drifting random walk, so what is left
      is noise-excited formants (breath), never a tone
    * a shaped spectral curve takes the chest out, lifts 2.5–5 kHz and
      *rolls the top off above 8 kHz* — the hiss of v1 lived up there
    * a small, envelope-followed breath layer is mixed under the words
    * the line is level-matched so the master chain, not this stage, decides
      the final loudness

Measured on the shipped build (see test_whisper.py): the voicing
(buzz) figure drops from ~0.37 to ~0.09 on English and from ~0.75 to ~0.11 on
Khmer, the chest weight below 250 Hz drops to ~0.003 of the energy, the air
above 2.5 kHz rises to ~0.25 (v1: 0.68 = hiss), and the quietest 5 % of the
line stays as silent as the source — the pauses are never filled with noise.

Voice identity is untouched: the pitch contour and the formants of the
speaker stay where they were; only the weight and the air change.

WHERE IT RUNS
-------------
Per sentence, inside the same loop that renders the performance plan:

    narration.render_styled()          (batch pipeline, per sentence)
    sonora/server.py produce loop      (studio, per line)

Both call `whisperize()` on the float array of that one line. Nothing is
applied to a whole finished episode (that would also whisper the music bed).

    from whisper import whisperize, depth_for
    out = whisperize(arr, rate=24000, depth=1.0)

    python whisper.py --demo            # /tmp/whisper_demo.wav + numbers
"""
from __future__ import annotations

import math

try:
    import numpy as np
except Exception:                                            # pragma: no cover
    np = None

# --------------------------------------------------------------------------- #
# depths                                                                      #
# --------------------------------------------------------------------------- #
#: a brief whisper moment inside another style (spec: "whisper briefly")
DEPTH_MOMENT = 0.55
#: the deepest the stage can go (no style uses it now — a whisper is a moment)
DEPTH_FULL = 1.00
#: names accepted by --depth on the command line
DEPTHS = {"moment": DEPTH_MOMENT, "soft": 0.7, "full": 0.85}

CHEST_HZ = 250.0            # everything below this is "body", not "breath"


# --------------------------------------------------------------------------- #
# tuning (all of it measured, none of it guessed)                              #
# --------------------------------------------------------------------------- #
#: the comb filter is ~ the pitch (200 Hz); smoothing over 350 Hz removes the
#: harmonics and keeps the formants, so the words survive
COMB_SMOOTH_HZ = 350.0
#: random-walk step for the phase, in radians per frame (small = smooth air,
#: large = watery / metallic)
PHASE_STEP = 0.55
#: how much of the original phase survives at full depth (0 = pure breath)
PHASE_KEEP = (0.22, 0.19)   # (base, minus per depth) -> 0.03 at depth 1.0
#: how much more breath a *dull* source gets. The Khmer carrier voice carries
#: how much of the real line stays under the breath: (base, per-depth)
VOICE_KEEP = (0.55, 0.42)   # -> 0.13 at depth 1.0 (the mouth, not the voice)
#: how loud the breath sits, as a fraction of the line's own peak:
#: (base, per-depth). v3 owns most of the level here — the breath IS the voice.
BREATH_AMOUNT = (0.25, 0.60)
#: how much of the breath floor a lighter moment (depth < 1) keeps: (base,
#: per-depth). A moment is a narrator leaning in, not a full whisper, so it
#: must measure less airy than a full whisper — this control does that.
BREATH_FLOOR_DEPTH = (0.55, 0.45)
#: how hard the breath's own level is forced to follow the words. 1.0 means
#: the breath's envelope IS the line's words band — clear, and silent where
#: the line is silent (this is the fix for the noise floor in the pauses that
#: a *blended* lock left behind); 0.0 = free-running noise.
WORDS_LOCK = 1.0
#: the words band the lock follows, and how much consonant bursts are added
#: on top of it (plosives and sibilants live outside the band)
WORDS_BAND = (300.0, 2500.0)
WORDS_BURST = 0.55
#: the lock's gain is clamped here, so a near-silent frame can never turn into
#: a noise spike, and the pauses stay silent
WORDS_LOCK_MAX = 6.0

#: what happens to the words: chest gone, words kept, presence lifted, top
#: rolled off (the v1 hiss lived above 8 kHz)
VOICE_CURVE = [(0.0, -45.0), (100.0, -34.0), (200.0, -20.0),
               (300.0, -8.0), (500.0, -2.0), (800.0, 0.0),
               (1500.0, 1.5), (2500.0, 4.5), (3500.0, 7.0),
               (5000.0, 4.0), (6500.0, 1.0), (8000.0, -3.0),
               (9000.0, -6.0), (12000.0, -14.0), (24000.0, -20.0)]
#: the breath floor: no rumble below 250 Hz, the words live in 300 Hz–6 kHz,
#: and everything above 9 kHz is rolled away — that top band is the "hiss"
#: that made the old whisper sound like static.
BREATH_CURVE = [(0.0, -70.0), (120.0, -40.0), (250.0, -14.0),
                (400.0, -3.0), (1200.0, 0.0), (3000.0, 0.0),
                (6000.0, -1.0), (9000.0, -6.0), (14000.0, -18.0),
                (24000.0, -30.0)]
#: the breath never relies on the source alone: a dull voice (the Khmer carrier
#: has very little energy above 2.5 kHz) would otherwise whisper without any
#: presence at all. The formant shape rides on top of this floor.
BREATH_FLOOR = [(0.0, -60.0), (200.0, -34.0), (400.0, -16.0),
                (1200.0, -8.0), (2500.0, -1.0), (5000.0, -2.0),
                (9000.0, -10.0), (24000.0, -26.0)]
BREATH_FLOOR_AMT = 0.11       # for a voice that already carries some air
BREATH_FLOOR_BOOST = 0.20     # …and this much more for a dull one (Khmer)
BREATH_FLOOR_REF = 0.05       # a source at/above this is "already airy"


def depth_for(style, item=None):
    """Always 0.0 — the whisper stage is REMOVED (build 2026-09-30n).

    The user's report: in every voice, Khmer and English, the reading would
    occasionally drop into a whisper that arrived louder than the sentence it
    replaced. A whispered line is generated as a different *sound* (a breath
    carrying the words), so wherever it lands it stops being the voice that was
    speaking — which is exactly what the identity rule forbids. The answer is
    not a gentler whisper, it is no whisper: the stage is gone.

    Kept as a function so every caller keeps working, and so nothing can
    quietly re-enable it: this returns 0.0 for every style and every item.
    """
    return 0.0


def _style_id(style):
    try:
        import narration as NAR
        return NAR.style_id(style)
    except Exception:
        return str(style or "").strip().lower().replace("-", "_")


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #
def _gain_db(f, curve):
    """Piecewise-linear dB curve -> linear gain, evaluated on a frequency axis."""
    xs = [p[0] for p in curve]
    ys = [p[1] for p in curve]
    g = np.zeros_like(f, dtype=np.float32)
    for i in range(len(xs) - 1):
        x0, x1 = xs[i], xs[i + 1]
        y0, y1 = ys[i], ys[i + 1]
        if x1 <= x0:
            continue
        m = (f >= x0) & (f <= x1)
        if not m.any():
            continue
        t = (f[m] - x0) / (x1 - x0)
        g[m] = y0 + (y1 - y0) * t
    g[f < xs[0]] = ys[0]
    g[f > xs[-1]] = ys[-1]
    return (10.0 ** (g / 20.0)).astype(np.float32)


def _frame_size(rate):
    """~42 ms of audio — long enough to see the comb, short enough to be exact."""
    n = int(round(float(rate) * 0.0427))
    n = max(256, 1 << int(math.floor(math.log2(max(2, n)))))
    return min(2048, n)


def _stft(x, n_fft, hop):
    """Framed FFT (Hann). Returns (spec, padded_length, frames)."""
    pad = n_fft
    y = np.concatenate([np.zeros(pad, np.float32), x.astype(np.float32),
                        np.zeros(pad + n_fft, np.float32)])
    frames = 1 + (y.size - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(frames)[:, None]
    return np.fft.rfft(y[idx] * _WIN(n_fft), axis=1).astype(np.complex64), y.size, frames


def _istft(spec, total, frames, n_fft, hop):
    """Overlap-add inverse (Hann, 75 % overlap) — exact reconstruction."""
    win = _WIN(n_fft)
    fr = np.fft.irfft(spec, n=n_fft, axis=1).astype(np.float32) * win
    out = np.zeros(total, np.float32)
    wsum = np.zeros(total, np.float32)
    w2 = win * win
    for i in range(frames):
        s = i * hop
        out[s:s + n_fft] += fr[i]
        wsum[s:s + n_fft] += w2
    y = out / np.maximum(wsum, 1e-8)
    return y[n_fft:n_fft + (total - 2 * n_fft)].astype(np.float32)


_WIN_CACHE = {}


def _WIN(n):
    if n not in _WIN_CACHE:
        _WIN_CACHE[n] = np.hanning(n).astype(np.float32)
    return _WIN_CACHE[n]


def _rand_walk_phase(shape, rng, step):
    """Smooth random phases: a random walk per bin, wrapped to ±pi."""
    bins, frames = shape
    inc = rng.normal(0.0, float(step), (bins, frames)).astype(np.float32)
    ph = np.cumsum(inc, axis=1, dtype=np.float32)
    return ((ph + np.pi) % (2.0 * np.pi) - np.pi).astype(np.float32)


def _comb_smooth(mag, k):
    """Moving average along frequency — removes the harmonic comb."""
    if k <= 1:
        return mag
    k = int(k) | 1
    kh = k // 2
    pad = np.pad(mag, ((0, 0), (kh, kh)), mode="edge")
    c = np.cumsum(pad, axis=1, dtype=np.float64)
    return ((c[:, 2 * kh:] - c[:, :-2 * kh]) / float(k)).astype(np.float32)


def _rms(x):
    if x.size == 0:
        return 0.0
    return float(math.sqrt(float(np.mean(np.square(x.astype(np.float64))))))


def _envelope(x):
    """|x| smoothed at ~30 ms — the syllable shape, for the breath layer."""
    a = np.abs(np.asarray(x, np.float32))
    k = max(1, int(len(a) / 100) or 1)
    if a.size >= k > 1:
        c = np.concatenate([[0.0], np.cumsum(a, dtype=np.float64)])
        env = ((c[k:] - c[:-k]) / float(k)).astype(np.float32)
        env = np.concatenate([np.full(a.size - env.size, env[0] if env.size else 0.0,
                                      np.float32), env])
    else:
        env = a
    hi = float(np.percentile(env, 95)) if env.size else 0.0
    if hi > 1e-9:
        env = env / hi
    return np.clip(env, 0.0, 1.5).astype(np.float32)


# --------------------------------------------------------------------------- #
# the stage                                                                   #
# --------------------------------------------------------------------------- #
def _formant_envelope(x, rate, n_fft=None, avg_sec=0.35):
    """The average spectral SHAPE of the line — the vocal tract, not the pitch.

    This is what a breath has to be filtered by: noise shaped by the formants
    of the utterance sounds like a whispered voice; noise shaped by nothing
    sounds like a hiss (that was v1), and a bare residual buzz sounds like a
    quiet voice (that was the first v2).
    """
    n_fft = n_fft or _frame_size(rate)
    hop = max(1, n_fft // 4)
    spec, total, frames = _stft(x, n_fft, hop)
    mag = np.abs(spec).astype(np.float32)
    # group frames into ~0.35 s blocks and average them, so the shape follows
    # the text (vowels, consonants) instead of the pitch
    per = max(1, int(round(avg_sec * rate / hop)))
    n_blocks = max(1, int(np.ceil(frames / float(per))))
    blocks = np.zeros((n_blocks, mag.shape[1]), dtype=np.float32)
    for b in range(n_blocks):
        seg = mag[b * per:(b + 1) * per]
        if seg.size:
            blocks[b] = seg.mean(axis=0)
    # smooth along frequency: the formants stay, the harmonics go
    k = int(round(COMB_SMOOTH_HZ * (n_fft / float(rate)))) | 1
    blocks = _comb_smooth(blocks, k)
    # a small floor so a silent block can never produce pure noise
    blocks /= (blocks.max(axis=1, keepdims=True) + 1e-9)
    # spread each block back over its frames (nearest block)
    idx = np.minimum(frames - 1, (np.arange(frames) // per))
    env_spec = blocks[idx]
    del spec, mag
    return env_spec


def _band_envelope(x, rate, lo=300.0, hi=2500.0, win_ms=12.0):
    """Per-sample envelope of one band — the *words* as a loudness curve."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1.0 / float(rate))
    spec[(f < lo) | (f > hi)] = 0.0
    band = np.abs(np.fft.irfft(spec, n=x.size)).astype(np.float32)
    k = max(1, int(rate * win_ms / 1000.0))
    if band.size >= k > 1:
        c = np.concatenate([[0.0], np.cumsum(band, dtype=np.float64)])
        env = ((c[k:] - c[:-k]) / float(k)).astype(np.float32)
        env = np.concatenate([np.full(band.size - env.size,
                                      env[0] if env.size else 0.0, np.float32), env])
    else:
        env = band
    peak = float(np.max(env)) if env.size else 0.0
    return env / peak if peak > 1e-9 else env


def floor_amount(rate, arr, amount=None, depth=1.0):
    """The breath floor for THIS voice.

    The Khmer carrier carries almost no energy above 2.5 kHz (measured 0.005
    of it; the English voice 0.034), and a whisper is partly recognised by
    that band. A dull voice therefore gets a little more of the floor band
    than an airy one — by a bounded factor, never by taste.
    """
    base = BREATH_FLOOR_AMT if amount is None else float(amount)
    d = max(0.0, min(1.0, float(depth)))
    base *= (BREATH_FLOOR_DEPTH[0] + BREATH_FLOOR_DEPTH[1] * d)
    if arr is None or len(arr) == 0:
        return base
    n = min(int(len(arr)), 1 << 18)
    if n < 512:
        return base
    x = np.asarray(arr, np.float32).reshape(-1)[:n]
    spec = np.abs(np.fft.rfft(x * np.hanning(n).astype(np.float32))) ** 2
    f = np.fft.rfftfreq(n, 1.0 / float(rate))
    tot = float(spec.sum()) or 1e-12
    src_hf = float(spec[f > 2500.0].sum() / tot)
    scarcity = 1.0 - min(1.0, src_hf / BREATH_FLOOR_REF)
    return base * (1.0 + BREATH_FLOOR_BOOST * max(0.0, scarcity))


def _hf(f, curve):
    return _gain_db(f, curve)[None, :]


def _oal(x, y, rate, n_fft, hop):
    """Overlap-add two frame sequences back to a signal (Hann, 75 % overlap)."""
    win = _WIN(n_fft)
    w2 = win * win
    n = x.shape[0]
    total = n_fft + (n - 1) * hop + n_fft
    out = np.zeros(total, np.float32)
    wsum = np.zeros(total, np.float32)
    for i in range(n):
        s = i * hop
        out[s:s + n_fft] += x[i]
        wsum[s:s + n_fft] += w2
    out = out / np.maximum(wsum, 1e-8)
    return out[n_fft:n_fft + (total - 2 * n_fft)]


def whisperize(arr, rate=24000, depth=DEPTH_FULL, seed=0):
    """Return the line UNCHANGED — the whisper stage is removed (2026-09-30n).

    Everything below this docstring is the old v3 whisper synthesis. It is kept
    because it is the record of how the effect worked and because `measure()`
    and the analysis helpers in this file are still used by the tests, but the
    entry point is now a pass-through: no caller can turn a spoken line into a
    whisper any more. See `Whisper-Removed.md`.
    """
    import numpy as _np
    x = _np.asarray(arr, dtype=_np.float32)
    return x.copy()


def _whisperize_removed(arr, rate=24000, depth=DEPTH_FULL, seed=0):
    """The old synthesis, kept for reference only — nothing calls this.

    v3 (build 2026-09-29k): the whisper is *built* from the line instead of
    being carved out of it.

        1. the line's own spectral shape is measured (vocal tract, pitchless);
        2. a random-phase noise floor is filtered by that shape, per ~0.35 s
           block, so the breath carries the vowel colours of the words and the
           line reads as *words* — clear, not a hiss;
        3. it is shaped in time by two envelopes: the syllable shape (so the
           breath lands where the words are) and the consonant bursts (so the
           s/t/k articulations survive — this is what keeps a whisper
           intelligible);
        4. a little of the real line stays mixed in, de-buzzed, so the
           listener still hears the speaker's mouth and not a noise cloud;
        5. the chest weight is removed, 2–6 kHz carries the words, the top is
           rolled off above 9 kHz, the pauses stay as silent as the source.

    Deterministic for a given (line, depth, seed).
    """
    if np is None:                                           # pragma: no cover
        return arr
    x = np.asarray(arr, dtype=np.float32).reshape(-1)
    if x.size == 0 or depth <= 0.0:
        return x
    depth = float(max(0.0, min(1.0, depth)))

    n_fft = _frame_size(rate)
    hop = max(1, n_fft // 4)
    frames = 1 + (x.size + 2 * n_fft - n_fft) // hop
    f = np.fft.rfftfreq(n_fft, 1.0 / float(rate)).astype(np.float32)

    # ---- envelopes in the time domain (syllables + consonants) -------------
    env = _envelope(x)                                   # ~30 ms, 0..1.5
    k = max(1, int(rate * 0.012))
    a = np.abs(x)
    if a.size >= k > 1:
        c = np.concatenate([[0.0], np.cumsum(a, dtype=np.float64)])
        fast = ((c[k:] - c[:-k]) / float(k)).astype(np.float32)
        fast = np.concatenate([np.full(a.size - fast.size,
                                       fast[0] if fast.size else 0.0, np.float32), fast])
    else:
        fast = a
    hi = float(np.percentile(fast, 97)) if fast.size else 0.0
    fast = fast / hi if hi > 1e-9 else fast
    burst = np.clip(fast - env, 0.0, 2.0)                # consonants stick out
    env = np.clip(env, 0.0, 1.5)

    # ---- the noise floor, shaped like the words ---------------------------
    rng = np.random.default_rng(int(seed) & 0x7FFFFFFF)
    noise = rng.normal(0.0, 1.0, x.size).astype(np.float32)
    nspec, ntotal, nframes = _stft(noise, n_fft, hop)
    nmag = np.abs(nspec).astype(np.float32)
    del nspec
    shape = _formant_envelope(x, rate, n_fft=n_fft)
    floor = _gain_db(f, BREATH_FLOOR) * floor_amount(rate, x, depth=depth)
    shape = np.maximum(shape, floor[None, :])
    nmag *= shape
    # one random phase per bin per frame: uncorrelated breath, no tone
    nph = rng.uniform(-np.pi, np.pi, nmag.shape).astype(np.float32)
    breath_s = _istft((nmag * np.exp(1j * nph)).astype(np.complex64), ntotal,
                      nframes, n_fft, hop)
    del nmag, nph, shape

    # ---- the line itself, de-buzzed (the mouth the listener knows) --------
    spec, total, sfr = _stft(x, n_fft, hop)
    mag = np.abs(spec).astype(np.float32)
    kk = int(round(COMB_SMOOTH_HZ * (n_fft / float(rate)))) | 1
    w_comb = min(1.0, 0.20 + 0.55 * depth)
    mag = (1.0 - w_comb) * mag + w_comb * _comb_smooth(mag, kk)
    keep = PHASE_KEEP[0] - PHASE_KEEP[1] * depth
    if keep < 0.999:
        phr = _rand_walk_phase(mag.shape, rng, PHASE_STEP)
        z = keep * np.exp(1j * np.angle(spec)) + (1.0 - keep) * np.exp(1j * phr)
        ph = np.angle(z).astype(np.float32)
    else:
        ph = np.angle(spec).astype(np.float32)
    g = _gain_db(f, VOICE_CURVE)
    g = 1.0 + (g - 1.0) * min(1.0, 0.35 + 0.65 * depth)
    voiced_s = _istft((mag * g[None, :]).astype(np.complex64) * np.exp(1j * ph),
                      total, sfr, n_fft, hop)
    del spec, mag, ph

    # ---- mix -------------------------------------------------------------
    # the noise already carries the speech shape; this only trims the low
    # rumble and the top hiss off it
    breath_s = _spectral_trim(breath_s, rate, f, n_fft, hop, BREATH_CURVE)

    n = min(voiced_s.size, breath_s.size, x.size, env.size)
    voiced_s, breath_s, env, burst = (voiced_s[:n], breath_s[:n], env[:n], burst[:n])
    if n < x.size:                       # keep the tail's length (timing!)
        pad = x.size - n
        voiced_s = np.concatenate([voiced_s, np.zeros(pad, np.float32)])
        breath_s = np.concatenate([breath_s, np.zeros(pad, np.float32)])
        env = np.concatenate([env, np.zeros(pad, np.float32)])
        burst = np.concatenate([burst, np.zeros(pad, np.float32)])

    # ---- the breath is LOCKED to the words -------------------------------
    # A filter alone leaves the noise's own loudness wanderings in charge, and
    # that is what reads as a hiss. Forcing the breath's envelope to be the
    # line's words-band envelope (plus a little consonant burst) is what makes
    # the whisper carry the actual words — clear, not airy noise.
    words = _band_envelope(x, rate, *WORDS_BAND)
    b_env = np.clip(words * 0.90 + burst * WORDS_BURST, 0.0, 1.35)
    ref = float(np.max(np.abs(breath_s))) if breath_s.size else 0.0
    if ref > 1e-9:
        breath_s = breath_s / ref
    if WORDS_LOCK > 0.0:
        own = _band_envelope(breath_s, rate, *WORDS_BAND) + 1e-4
        gain = np.clip(b_env / own, 0.0, WORDS_LOCK_MAX) ** WORDS_LOCK
        breath_s = breath_s * gain
    b_amt = (BREATH_AMOUNT[0] + BREATH_AMOUNT[1] * depth)     # × input peak
    peak_in = float(np.max(np.abs(x))) or 1.0
    y = (VOICE_KEEP[0] - VOICE_KEEP[1] * depth) * voiced_s \
        + b_amt * peak_in * breath_s

    # ---- level + safety --------------------------------------------------
    target = _rms(x) * (1.0 - 0.10 * depth)
    cur = _rms(y)
    if cur > 1e-6 and target > 1e-6:
        y = y * min(12.0, target / cur)
    peak = float(np.max(np.abs(y))) if y.size else 0.0
    if peak > 0.95:
        y = y * (0.95 / peak)
    return y.astype(np.float32)


def _spectral_trim(sig, rate, f, n_fft, hop, curve):
    """One band-shaping pass over an already-synthesised signal."""
    spec, total, frames = _stft(sig, n_fft, hop)
    g = _gain_db(f, curve)
    out = _istft((np.abs(spec).astype(np.float32) * g[None, :]).astype(np.complex64)
                 * np.exp(1j * np.angle(spec)), total, frames, n_fft, hop)
    return out[:sig.size]


def word_envelope(arr, rate=24000, lo=300.0, hi=2500.0, hop_ms=20.0):
    """The speaking-band envelope — the shape of the words, pitchless.

    Used to check the whisper still *follows the words*: a good whisper has an
    envelope and a spectrum that track the spoken line; a hiss does not. These
    two numbers are the honest "is it clear?" test that this box can run
    without an ear or an ASR model.
    """
    if np is None or arr is None or len(arr) == 0:
        return np.zeros(1, np.float32)
    x = np.asarray(arr, dtype=np.float32).reshape(-1)
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1.0 / float(rate))
    spec[(f < lo) | (f > hi)] = 0.0
    band = np.fft.irfft(spec, n=x.size).astype(np.float32)
    hop = max(1, int(rate * hop_ms / 1000.0))
    n = int(np.ceil(band.size / float(hop)))
    pad = n * hop - band.size
    if pad:
        band = np.concatenate([band, np.zeros(pad, np.float32)])
    return np.sqrt(np.mean(band.reshape(n, hop).astype(np.float64) ** 2,
                           axis=1)).astype(np.float32)


def clarity(whisper, reference, rate=24000):
    """How much of the *words* survived: two numbers in 0..1.

    `band`  correlation of the 300–2500 Hz envelope with the spoken line
            (are the words in the same places?)
    `shape` cosine similarity of the 300–6000 Hz average spectrum
            (do the words have the same colours?)

    A hiss scores near 0 on both; a filtered version of the voice scores high
    on `shape` but low on `band`. A real whisper scores well on both.
    """
    if np is None or whisper is None or reference is None:
        return {"band": 0.0, "shape": 0.0}
    w = np.asarray(whisper, dtype=np.float32).reshape(-1)
    r = np.asarray(reference, dtype=np.float32).reshape(-1)
    n = min(w.size, r.size)
    if n < 512:
        return {"band": 0.0, "shape": 0.0}
    ew = word_envelope(w[:n], rate)
    er = word_envelope(r[:n], rate)
    m = min(ew.size, er.size)
    ew, er = ew[:m], er[:m]
    keep = er > 0.05 * (float(er.max()) or 1e-9)
    band = 0.0
    if keep.sum() > 8:
        a, b = np.log(ew[keep] + 1e-6), np.log(er[keep] + 1e-6)
        a, b = a - a.mean(), b - b.mean()
        den = float(np.sqrt((a * a).sum() * (b * b).sum()))
        band = float((a * b).sum() / den) if den > 1e-12 else 0.0
    # spectral shape: 1/3-octave-ish bands, 300 Hz – 6 kHz
    edges = 300.0 * (2.0 ** (np.arange(0, 15) / 3.0))
    spec_w = np.abs(np.fft.rfft(w[:n] * np.hanning(n).astype(np.float32)))
    spec_r = np.abs(np.fft.rfft(r[:n] * np.hanning(n).astype(np.float32)))
    free = np.fft.rfftfreq(n, 1.0 / float(rate))
    bw, br = [], []
    for i in range(len(edges) - 1):
        sel = (free >= edges[i]) & (free < edges[i + 1])
        bw.append(float(spec_w[sel].sum())); br.append(float(spec_r[sel].sum()))
    bw, br = np.asarray(bw), np.asarray(br)
    den = float(np.linalg.norm(bw) * np.linalg.norm(br))
    shape = float(bw.dot(br) / den) if den > 1e-12 else 0.0
    return {"band": max(0.0, band), "shape": max(0.0, shape)}


def measure(arr, rate=24000):
    """Spectral fingerprint of a line — used by the tests and the logs.

    `low_ratio`  share of energy below 250 Hz      (chest weight — gone)
    `hf_ratio`   share of energy above 2.5 kHz     (air — present, not a hiss)
    `voicing`    periodicity in the 200–3000 Hz band (the *buzz*: ~0.37 spoken,
                 ~0.09 whispered — the single best "is it really a whisper" number)
    `silence`    the quietest 5 % of the line relative to its own loud part
                 (a noise floor would push this up — the pauses stay silent)
    """
    empty = {"low_ratio": 0.0, "hf_ratio": 0.0, "rms": 0.0, "peak": 0.0,
             "voicing": 0.0, "silence": 0.0}
    if np is None or arr is None or len(arr) == 0:
        return empty
    x = np.asarray(arr, dtype=np.float32).reshape(-1)
    n = min(x.size, 1 << 19)
    seg = x[:n] * np.hanning(n).astype(np.float32)
    spec = np.abs(np.fft.rfft(seg)) ** 2
    f = np.fft.rfftfreq(n, 1.0 / float(rate))
    tot = float(spec.sum()) or 1e-12

    # periodicity: the biggest autocorrelation peak in the pitch range
    m = max(256, x.size // 2)
    half = x[:m] * np.hanning(m).astype(np.float32)
    fb = np.fft.rfftfreq(m, 1.0 / float(rate))
    band = (fb > 200.0) & (fb < 3000.0)
    lo = np.fft.irfft(np.fft.rfft(half) * band, n=m)
    ac = np.correlate(lo, lo, "full")[len(lo) - 1:]
    ac = ac / (float(ac[0]) + 1e-12)
    l0, l1 = int(rate / 400.0), int(rate / 70.0)
    voicing = float(np.max(ac[l0:l1])) if l1 > l0 + 1 else 0.0

    a = np.abs(x)
    k = max(1, int(rate * 0.02))
    if a.size >= k > 1:
        c = np.concatenate([[0.0], np.cumsum(a, dtype=np.float64)])
        e = ((c[k:] - c[:-k]) / float(k)).astype(np.float32)
    else:
        e = a
    silence = float(np.percentile(e, 5)) / (float(np.percentile(e, 95)) + 1e-9) \
        if e.size else 0.0

    return {"low_ratio": float(spec[f < CHEST_HZ].sum() / tot),
            "hf_ratio": float(spec[f > 2500.0].sum() / tot),
            "rms": _rms(x), "peak": float(np.max(np.abs(x))) if x.size else 0.0,
            "voicing": voicing, "silence": silence}


def is_whisper(plan_item):
    """True for a plan item the engine marked as whispered."""
    try:
        return bool(plan_item.get("whisper"))
    except Exception:
        return False


def _demo():
    """python whisper.py --demo — a voiced test tone, whispered, with numbers."""
    import struct
    import os

    if np is None:
        print("numpy is required for the demo")
        return 1
    rate = 24000
    t = np.arange(int(rate * 1.5), dtype=np.float32) / rate
    # a voiced "aaah": 190 Hz with harmonics, amplitude-enveloped like speech
    sig = sum((1.0 / k) * np.sin(2 * np.pi * 190.0 * k * t) for k in (1, 2, 3, 4, 5))
    sig = (sig * (0.5 + 0.5 * np.sin(2 * np.pi * 3.0 * t))).astype(np.float32)
    sig *= 0.3
    wh = whisperize(sig, rate=rate, depth=DEPTH_FULL)
    a, b = measure(sig, rate), measure(wh, rate)
    print("voiced :", {k: round(v, 4) for k, v in a.items()})
    print("whisper:", {k: round(v, 4) for k, v in b.items()})
    print("         voicing %.3f -> %.3f  (the buzz goes)"
          % (a["voicing"], b["voicing"]))
    try:
        exe = None
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            exe = "ffmpeg"
        wav = "/tmp/whisper_demo.wav"
        pcm = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32000))
                       for v in np.concatenate([sig, wh]))
        with open(wav, "wb") as f:                       # 16-bit mono, 2 x 1.5 s
            f.write(b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt ")
            f.write(struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16))
            f.write(b"data" + struct.pack("<I", len(pcm)) + pcm)
        print("wrote  :", wav, "(first 1.5 s voiced, second 1.5 s whispered)")
    except Exception as e:                                    # pragma: no cover
        print("wav write skipped:", e)
    return 0


def main():
    import sys
    if "--demo" in sys.argv:
        return _demo()
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
