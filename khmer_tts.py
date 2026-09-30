#!/usr/bin/env python3
"""khmer_tts.py — Khmer text-to-speech engines, with automatic fallback.

Why this module exists
----------------------
The batch pipeline and Sonora both need Khmer speech. Until now they used one
route (Microsoft edge-tts). When that route is unavailable — no internet, a
Microsoft hiccup, a blocked region — the whole job failed.

This module knows every free Khmer TTS route that works from Cambodia and
picks the best one that is actually usable on this machine:

  engine    what it is                                   offline  licence
  --------  -------------------------------------------  -------  --------------
  voxcpm    VoxCPM2 — 48 kHz, can clone your voice        yes     Apache-2.0
            (best quality; needs ~8 GB VRAM + install)
  edge      Microsoft Neural km-KH Sreymom / Piseth       no      MS terms
            (excellent quality, zero install — default)
  mmsft     MMS Khmer fine-tuned by the community         yes     CC-BY-NC
            (tighter pacing, a second Khmer narrator; also the slot for
             the voice YOU train with the Colab kit — see khmer-colab/)
  mms       Meta MMS-TTS Khmer (VITS, 36M params)         yes     CC-BY-NC
            (robotic and slow, but faithful — offline fallback)
  gtts      Google Translate voice                        no      unofficial
            (emergency only: flat, but understandable)

Fallback order (config: tts_engine = "auto"):
    edge -> mmsft -> mms -> voxcpm -> gtts
    (the first engine that works wins; anything offline comes before the
     low-quality emergency voice)

To use a voice you trained yourself, point the fine-tuned slot at it:
    set KHMER_MMSFT_MODEL=your-hf-name/khmer-voice     (engine "mmsft")
or the stock slot:
    set KHMER_MMS_MODEL=your-hf-name/khmer-voice       (engine "mms")

Every call returns which engine actually produced the audio, so a long
production run can be audited afterwards.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

# ----------------------------------------------------------------- recipes --

# km-KH neural voices from Microsoft (via edge-tts). Free, no key.
EDGE_VOICES = {
    "km-KH-SreymomNeural": "Sreymom (female) — warm Cambodian narrator",
    "km-KH-PisethNeural": "Piseth (male) — clear Cambodian host",
}

ENGINES = {
    "voxcpm": {
        "label": "VoxCPM2 — 48 kHz neural + voice cloning",
        "offline": True,
        "quality": 5,
        "python_pkg": "voxcpm",
        "install": "pip install voxcpm   (needs ~8 GB VRAM; Apache-2.0)",
        "licence": "Apache-2.0 (commercial use allowed)",
        "voices": ["default"],
    },
    "edge": {
        "label": "Microsoft Neural (edge-tts)",
        "offline": False,
        "quality": 4,
        "python_pkg": "edge_tts",
        "install": "pip install edge-tts   (no key needed)",
        "licence": "Microsoft terms — free for personal use",
        "voices": sorted(EDGE_VOICES),
    },
    "mmsft": {
        "label": "MMS Khmer fine-tuned — community voice (local VITS)",
        "offline": True,
        "quality": 3,
        "python_pkg": "transformers",
        "install": "pip install transformers torch   (model ~145 MB, CC-BY-NC)",
        "licence": "CC-BY-NC-4.0 — personal / non-commercial only",
        "voices": ["default"],
    },
    "mms": {
        "label": "Meta MMS-TTS Khmer (local VITS)",
        "offline": True,
        "quality": 2,
        "python_pkg": "transformers",
        "install": "pip install transformers torch   (model ~145 MB, CC-BY-NC)",
        "licence": "CC-BY-NC-4.0 — personal / non-commercial only",
        "voices": ["default"],
    },
    "gtts": {
        "label": "Google Translate voice (emergency)",
        "offline": False,
        "quality": 1,
        "python_pkg": "gtts",
        "install": "pip install gTTS",
        "licence": "unofficial Google endpoint — avoid for published work",
        "voices": ["default"],
    },
}

# default chain for tts_engine="auto"
AUTO_ORDER = ["edge", "mmsft", "mms", "voxcpm", "gtts"]

# swap this for a model you trained with the free-Colab kit (see khmer-colab/):
#   KHMER_MMS_MODEL=yourname/khmer-voice   (environment variable, or edit here)
MMS_MODEL = os.environ.get("KHMER_MMS_MODEL", "facebook/mms-tts-khm")
# Community fine-tune of the same model (KrorngAI/mms-tts-khm-finetuned):
# same architecture, a different narrator with noticeably tighter pacing.
# Point KHMER_MMSFT_MODEL at your own trained voice to use that instead.
MMSFT_MODEL = os.environ.get("KHMER_MMSFT_MODEL",
                             "KrorngAI/mms-tts-khm-finetuned")
VOXCPM_MODEL = "openbmb/VoxCPM2"


def find_ffmpeg(hint=""):
    """System ffmpeg -> the one bundled with imageio-ffmpeg -> bare name."""
    if hint and (os.path.sep in hint or shutil.which(hint)):
        return hint
    got = shutil.which("ffmpeg")
    if got:
        return got
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return hint or "ffmpeg"


def _has_module(name):
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def engine_ready(engine):
    """Is this engine installed on this machine? (checks, never downloads)"""
    pkg = ENGINES[engine]["python_pkg"]
    return _has_module(pkg)


def available_engines(online=True):
    """Engines usable right now, best quality first."""
    out = []
    for e in sorted(ENGINES, key=lambda k: -ENGINES[k]["quality"]):
        if not engine_ready(e):
            continue
        if not online and not ENGINES[e]["offline"]:
            continue
        out.append(e)
    return out


def status():
    """Human-readable table for preflight / the Sonora UI."""
    rows = []
    for e in sorted(ENGINES, key=lambda k: -ENGINES[k]["quality"]):
        ok = engine_ready(e)
        rows.append({
            "engine": e,
            "label": ENGINES[e]["label"],
            "installed": ok,
            "offline": ENGINES[e]["offline"],
            "quality": ENGINES[e]["quality"],
            "install": ENGINES[e]["install"],
            "licence": ENGINES[e]["licence"],
        })
    return rows


# ------------------------------------------------------------- synthesise --

def _run(cmd, timeout=900):
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    return r.returncode, (r.stdout or b"").decode("utf-8", "ignore"), \
        (r.stderr or b"").decode("utf-8", "ignore")


def _to_wav(src, dst, ffmpeg, rate=24000):
    """Convert whatever an engine produced into mono 16-bit PCM wav."""
    # "-f wav" is explicit on purpose: callers may write to *.part temp files
    # and ffmpeg cannot guess the container from that extension
    code, _, err = _run([ffmpeg, "-v", "error", "-y", "-i", src,
                         "-ar", str(rate), "-ac", "1", "-c:a", "pcm_s16le",
                         "-f", "wav", dst], timeout=300)
    if code != 0 or not os.path.exists(dst):
        raise RuntimeError("ffmpeg could not convert engine output: " + err[-200:])


def synth_edge(text, dst, voice="km-KH-SreymomNeural", rate="+0%", pitch="+0Hz",
               ffmpeg="ffmpeg"):
    """Microsoft neural voice via edge-tts.

    edge-tts only produces MP3, and every stage here works in WAV, so the
    audio is converted (unless the caller explicitly asked for .mp3).
    """
    import edge_tts

    mp3 = dst if dst.lower().endswith(".mp3") else dst + ".edge.mp3"
    try:
        async def go():
            comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
            await comm.save(mp3)
        asyncio.run(go())
        if not os.path.exists(mp3) or os.path.getsize(mp3) < 1000:
            raise RuntimeError("edge-tts returned no audio "
                               "(voice unavailable or blocked)")
        if mp3 != dst:
            _to_wav(mp3, dst, ffmpeg)
    finally:
        if mp3 != dst:
            try:
                os.remove(mp3)
            except OSError:
                pass
    return {"engine": "edge", "voice": voice, "path": dst}


def synth_gtts(text, dst, ffmpeg="ffmpeg", **kw):
    """Google Translate endpoint — flat but always understandable."""
    from gtts import gTTS
    tmp = dst + ".mp3"
    gTTS(text=text, lang="km").save(tmp)
    _to_wav(tmp, dst, ffmpeg)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return {"engine": "gtts", "voice": "km", "path": dst}


_MMS_CACHE = {}


def _vits_model(model_id):
    """Load and cache one VITS model (Hub id or a local folder)."""
    from transformers import VitsModel, AutoTokenizer
    slot = _MMS_CACHE.get(model_id)
    if slot is None:
        slot = {"tok": AutoTokenizer.from_pretrained(model_id),
                "model": VitsModel.from_pretrained(model_id)}
        try:
            slot["model"].eval()
        except Exception:
            pass
        _MMS_CACHE[model_id] = slot
    return slot["tok"], slot["model"]


def _vits_say(engine, model_id, voice_name, text, dst):
    """Shared VITS inference for the two offline Khmer models."""
    import numpy as np
    import scipy.io.wavfile as wav
    import torch
    tok, model = _vits_model(model_id)
    inputs = tok(text, return_tensors="pt")
    with torch.no_grad():
        out = model(**inputs).waveform
    audio = out.squeeze().cpu().numpy()
    sr = int(getattr(model.config, "sampling_rate", 16000))
    peak = float(np.max(np.abs(audio))) or 1.0
    pcm = (audio / peak * 0.95 * 32767).astype(np.int16)
    wav.write(dst, sr, pcm)
    return {"engine": engine, "voice": voice_name, "path": dst}


def synth_mms(text, dst, ffmpeg="ffmpeg", **kw):
    """Meta MMS-TTS Khmer (VITS) — offline, slow but faithful."""
    return _vits_say("mms", MMS_MODEL, "mms-khm", text, dst)


def synth_mmsft(text, dst, ffmpeg="ffmpeg", **kw):
    """MMS Khmer fine-tuned (community checkpoint, or YOUR trained voice).

    Same architecture as the stock MMS model, but a different narrator:
    measured on identical text it reads a 7.8 s sentence in 5.5 s, i.e. it
    drags far less. Set KHMER_MMSFT_MODEL to use your own Colab-trained
    model here.
    """
    return _vits_say("mmsft", MMSFT_MODEL, MMSFT_MODEL, text, dst)


_VOX_CACHE = {}


def synth_voxcpm(text, dst, ffmpeg="ffmpeg", reference_wav="", **kw):
    """VoxCPM2 — 48 kHz Khmer, optional voice cloning from a reference wav."""
    import soundfile as sf
    from voxcpm import VoxCPM
    if "model" not in _VOX_CACHE:
        _VOX_CACHE["model"] = VoxCPM.from_pretrained(VOXCPM_MODEL,
                                                     load_denoiser=False)
    model = _VOX_CACHE["model"]
    args = {"text": text, "cfg_value": 2.0, "inference_timesteps": 10,
            "normalize": True}
    if reference_wav and os.path.isfile(reference_wav):
        args["reference_wav_path"] = reference_wav
    wav = model.generate(**args)
    sr = int(getattr(getattr(model, "tts_model", None), "sample_rate", 48000)
             or 48000)
    sf.write(dst, wav, sr)
    return {"engine": "voxcpm", "voice": "clone" if reference_wav else "default",
            "path": dst}


_SYNTH = {"edge": synth_edge, "gtts": synth_gtts, "mms": synth_mms,
          "mmsft": synth_mmsft, "voxcpm": synth_voxcpm}


def synth(text, dst, engine="auto", voice="", ffmpeg="ffmpeg",
          rate="+0%", pitch="+0Hz", reference_wav="", log=print):
    """Synthesize one line. Tries the preferred engine, then the fallbacks.

    Returns a dict: {ok, engine, voice, path, seconds, error, tried[]}
    """
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty text", "tried": []}

    ffmpeg = find_ffmpeg(ffmpeg)
    if engine == "auto":
        order = list(AUTO_ORDER)
    else:
        order = [engine] + [e for e in AUTO_ORDER if e != engine]

    tried, last_err = [], ""
    for e in order:
        if not engine_ready(e):
            tried.append((e, "not installed"))
            continue
        fn = _SYNTH[e]
        t0 = time.time()
        try:
            kw = {"ffmpeg": ffmpeg}
            if e == "edge":
                kw.update({"voice": voice or "km-KH-SreymomNeural",
                           "rate": rate, "pitch": pitch})
            elif e == "voxcpm":
                kw.update({"reference_wav": reference_wav})
            info = fn(text, dst, **kw)
            size = os.path.getsize(dst) if os.path.exists(dst) else 0
            if size < 1000:
                raise RuntimeError("engine produced no audio (%d bytes)" % size)
            return {"ok": True, "engine": e, "voice": info.get("voice", ""),
                    "path": dst, "seconds": round(time.time() - t0, 2),
                    "bytes": size, "error": "", "tried": tried}
        except Exception as ex:
            last_err = f"{type(ex).__name__}: {ex}"
            tried.append((e, last_err.split(":")[0]))
            log(f"[tts] {e} failed: {last_err[:160]}")
            continue
    return {"ok": False, "engine": "", "voice": "", "path": "",
            "seconds": 0, "bytes": 0, "error": last_err,
            "tried": tried,
            "hint": "install a fallback: pip install edge-tts gTTS "
                    "(offline: transformers torch)"}


def probe(ffmpeg="ffmpeg", log=print):
    """Preflight helper: what can this machine actually do right now?"""
    info = {"engines": status(), "usable": [], "preferred": ""}
    for e in AUTO_ORDER:
        if not engine_ready(e):
            continue
        ok = True
        if e == "edge":
            ok = _quick_edge_check(log)
        if e in ("mms", "mmsft"):
            ok = _has_module("torch") and _has_module("transformers")
        if ok:
            info["usable"].append(e)
    if info["usable"]:
        info["preferred"] = info["usable"][0]
    return info


def _quick_edge_check(log=print):
    try:
        import edge_tts
        voices = asyncio.run(edge_tts.list_voices())
        return any(v.get("ShortName", "").startswith("km-KH") for v in voices)
    except Exception as ex:
        log(f"[tts] edge-tts reachability check failed: {type(ex).__name__}")
        return _has_module("edge_tts")     # installed but offline? still try later


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Khmer TTS engines")
    ap.add_argument("--status", action="store_true", help="show engine table")
    ap.add_argument("--say", default="", help="synthesize this text")
    ap.add_argument("--out", default="khmer_tts_out.wav")
    ap.add_argument("--engine", default="auto")
    ap.add_argument("--voice", default="")
    a = ap.parse_args()
    if a.say:
        ff = find_ffmpeg()
        r = synth(a.say, a.out, engine=a.engine, voice=a.voice, ffmpeg=ff)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        sys.exit(0 if r["ok"] else 1)
    print(f"{'engine':8s} {'installed':10s} {'offline':8s} quality  licence")
    for row in status():
        print(f"{row['engine']:8s} {str(row['installed']):10s} "
              f"{str(row['offline']):8s} {row['quality']:^7d}  {row['licence']}")
    print("\nfallback order (auto):", " -> ".join(AUTO_ORDER))
