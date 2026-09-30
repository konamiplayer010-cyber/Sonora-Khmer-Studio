"""rvc_engine.py — in-process RVC conversion (verified dual-generation API).

This is the same loading/conversion logic that Sonora's rvc_worker.py uses,
verified against the real RVC-WebUI source (2.3+ layout `infer.vc.modules`
and classic 2.0-2.2 layout `infer.modules.vc.modules`).

Run with the python that has torch + the RVC packages (normally the RVC
venv). Nothing here is a guessed CLI — it imports RVC's own VC class.
"""
import asyncio
import contextlib
import os
import sys
import tempfile

import numpy as np

# This file is launched as a script by the preflight check and by stage 03, with
# the python that owns RVC. Some RVC installs ship an EMBEDDED python (a
# `runtime` folder with a python._pth file) which does not put the script's own
# folder on sys.path — `import common` then fails with "No module named
# 'common'" even though common.py sits right next to this file. Add it here so
# the engine works with every python, extracted or embedded.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def log(msg):
    print(f"[rvc-engine] {msg}", flush=True)


@contextlib.contextmanager
def _in_dir(path):
    """Work from `path` for a while.

    RVC's own launcher starts it with the RVC folder as the working directory —
    `configs/config.json`, `i18n/`, `assets/` and friends are opened relative to
    it. The pipeline runs from the pipeline folder, so step into the RVC folder
    for every part that touches RVC, then step back out.
    """
    try:
        old = os.getcwd()
    except OSError:
        old = None
    try:
        os.chdir(path)
    except Exception:
        yield
        return
    try:
        yield
    finally:
        if old:
            try:
                os.chdir(old)
            except Exception:
                pass


def _setup_env(rvc_root):
    os.environ.setdefault("weight_root", os.path.join(rvc_root, "assets", "weights"))
    os.environ.setdefault("index_root", os.path.join(rvc_root, "logs"))
    os.environ.setdefault("outside_index_root", os.path.join(rvc_root, "assets", "indices"))
    os.environ.setdefault("rmvpe_root", os.path.join(rvc_root, "assets", "rmvpe"))
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")


def _make_config():
    """RVC's Config() parses sys.argv — guard it (same trick RVC's own CLI uses)."""
    saved = sys.argv[:]
    sys.argv = [sys.argv[0]]
    try:
        from configs.config import Config
        return Config()
    finally:
        sys.argv = saved


def _resolve_fields(rvc_root, model_path, index_path):
    """MODEL/INDEX from config may be a file, a bare name or a FOLDER.

    Batch runs must never hand RVC a folder (it concatenates paths and dies
    with a PermissionError). Returns (model_path, index_path, notes).
    """
    notes = []
    try:
        from sonora_paths import resolve_model_field, resolve_index_field
    except Exception:
        return model_path, index_path, notes
    mp, n1 = resolve_model_field(rvc_root, model_path,
                                 prefer=["Sonaro-kh.pth",
                                         os.path.basename(model_path or "")])
    if n1:
        notes.append("MODEL: " + n1)
    ip, n2 = "", ""
    if index_path:
        ip, n2 = resolve_index_field(rvc_root, index_path,
                                     prefer=[os.path.basename(mp or model_path or "")])
        if n2:
            notes.append("INDEX: " + n2)
    return (mp or model_path), (ip or index_path), notes


def load_vc(rvc_root, model_path, index_path=None):
    """Load RVC's VC class + the model. Returns (vc, api_module, device)."""
    rvc_root = os.path.abspath(rvc_root)
    if rvc_root not in sys.path:
        sys.path.insert(0, rvc_root)
    if os.path.isdir(os.path.join(rvc_root, "assets")) is False \
            and os.path.isdir(os.path.join(rvc_root, "weights")) is False:
        pass                        # layout is checked elsewhere; never fatal here
    model_path, index_path, _notes = _resolve_fields(rvc_root, model_path, index_path)
    for _n in _notes:
        log(_n)
    if os.path.isdir(model_path):
        raise RuntimeError(
            "the model in config.json (model_file) is a FOLDER: " + model_path
            + " — put the .pth file name in it, e.g. "
              "\"model_file\": \"assets/weights/Sonaro-kh.pth\"")
    _setup_env(rvc_root)

    import torch
    log(f"python={sys.executable} torch={torch.__version__} "
        f"cuda={torch.cuda.is_available()} cwd={os.getcwd()}")

    # everything that touches RVC happens INSIDE the RVC folder (see _in_dir)
    with _in_dir(rvc_root):
        try:
            from i18n.i18n import I18nAuto
            I18nAuto()
        except Exception:
            pass

        try:
            config = _make_config()
        except Exception as e:
            raise RuntimeError(
                "RVC's own configuration could not be read inside " + rvc_root
                + " — " + str(e)[:200]
                + "  (rvc_root must be the RVC-WebUI folder: it holds RVC.py, "
                  "infer/ and configs/config.json)")
        device = str(getattr(config, "device", "")) or "cpu"

        errs, vc, api = [], None, None
        for mod in ("infer.vc.modules", "infer.modules.vc.modules"):
            try:
                mod_obj = __import__(mod, fromlist=["VC"])
            except Exception as e:
                errs.append(f"{mod} [import]: {str(e)[:200]}")
                log(f"{mod} -> import failed: {str(e)[:160]}")
                continue
            try:
                vc = mod_obj.VC(config)
            except Exception as e:
                errs.append(f"{mod} [start VC]: {str(e)[:200]}")
                log(f"{mod} -> imported, but starting it failed: {str(e)[:160]}")
                continue
            api = mod
            log("using RVC API: " + mod)
            break
        if vc is None:
            raise RuntimeError(
                "cannot load RVC's VC class from " + rvc_root + " — "
                + " | ".join(errs)[:600]
                + "  (rvc_root must be the RVC-WebUI folder holding RVC.py and "
                  "infer/; its python needs RVC's own packages)")

        base = os.path.basename(model_path)
        names = [base, base[:-4] + ".pth" if base.lower().endswith(".pth") else base]
        last_err = ""
        for nm in dict.fromkeys(names + [model_path]):
            try:
                vc.get_vc(nm)
                log("model loaded via get_vc('" + nm + "')")
                break
            except Exception as e:
                last_err = str(e)[:250]
        else:
            raise RuntimeError("RVC get_vc failed for " + base + " — " + last_err)

        if index_path and not os.path.exists(index_path):
            raise FileNotFoundError("index file not found: " + index_path)
    return vc, api, device


def _vc_single(vc, api, in_path, settings, index_path):
    """One conversion. Returns (sr, int16 numpy mono). Raises on failure."""
    pitch = int(settings.get("pitch", 0))
    index_rate = float(settings.get("index_rate", 0.75))
    protect = float(settings.get("protect", 0.33))
    resample = int(settings.get("resample_sr", 0) or 0)
    rms = float(settings.get("rms_mix_rate", 1.0))
    f0 = settings.get("f0_method", "rmvpe")
    idx = index_path or ""
    modern = api == "infer.vc.modules"

    def call(method):
        if modern:
            return vc.vc_single(0, in_path, pitch, method, idx, index_rate,
                                resample, rms, protect)
        return vc.vc_single(0, in_path, pitch, None, method, idx, None,
                            index_rate, 3, resample, rms, protect)

    last = None
    for method in [f0] + (["pm"] if f0 == "rmvpe" else []):
        try:
            status, result = call(method)
            if isinstance(result, tuple) and result and result[0] is not None:
                sr, audio = result
                if isinstance(status, str) and ("Traceback" in status or "Error" in status):
                    raise RuntimeError(status[:300])
                return int(sr), _to_int16(audio), method
            raise RuntimeError((status if isinstance(status, str) else str(status))[:300])
        except Exception as e:
            last = e
            if method != f0:
                break
            log(f"f0 method '{f0}' failed ({str(e)[:120]}) — retrying with 'pm'")
    raise RuntimeError("RVC conversion failed: " + str(last)[:300])


def _to_int16(audio):
    audio = np.asarray(audio)
    if audio.ndim > 1:
        audio = audio[0] if audio.shape[-1] <= 2 else audio.mean(axis=-1)
    if np.issubdtype(audio.dtype, np.floating):
        audio = np.clip(audio, -1.0, 1.0) * 32767.0
    return audio.astype(np.int16)


def convert_wav(rvc_root, model_path, index_path, in_wav, out_wav, settings):
    """Convert one WAV (any sample rate, mono/stereo) through the loaded model.
    out_wav is written only after success."""
    from common import write_wav, validate_wav
    sr_in, data = _read_any_wav(in_wav)
    with tempfile.TemporaryDirectory() as td:
        tmp_in = os.path.join(td, "in.wav")
        write_wav(tmp_in, data, sr_in)
        sr, audio, method = _call_with_loaded(rvc_root, model_path, index_path,
                                              tmp_in, settings)
    import pathlib
    pathlib.Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
    write_wav(out_wav, audio, sr)
    ok, info, probs = validate_wav(out_wav)
    if not ok:
        raise RuntimeError("output failed validation: " + "; ".join(probs))
    info["f0_used"] = method
    return info


# a loaded VC is kept in-process by the caller; these wrappers let a caller
# either load per-call (simple) or keep it loaded (fast batches).
_LOADED = {}


def get_loaded(rvc_root, model_path, index_path):
    key = (os.path.abspath(rvc_root), os.path.abspath(model_path))
    if key not in _LOADED:
        vc, api, device = load_vc(rvc_root, model_path, index_path)
        _LOADED[key] = (vc, api, device, index_path, os.path.abspath(rvc_root))
    return _LOADED[key]


def _call_with_loaded(rvc_root, model_path, index_path, in_wav, settings):
    vc, api2, device, idx, root2 = get_loaded(rvc_root, model_path, index_path)
    with _in_dir(root2):
        return _vc_single(vc, api2, in_wav, settings, idx or index_path or "")


def _read_any_wav(path):
    import wave
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        width = w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if width == 2:
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return sr, data


# ------------------------------------------------------------- test mode --

TEST_TEXT = "\u179f\u1788\u17d2\u1798\u17b6\u17c7\u1780\u17d2\u178e \u1793\u17c7\u179b\u17c1\u17cd\u1780\u17c1\u17c3\u179c\u17c1\u17c2\u17d2\u1785\u1793\u17c7\u1780\u17bb\u1794\u17c3\u17a0\u1796\u17c1\u17c7\u179b\u17c7\u1791\u17c7\u17d2\u1794\u1790\u17d2\u1785\u1797\u17d2"


async def _edge_once(text, voice, rate):
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=rate)
    buf = b""
    async for msg in comm.stream():
        if msg.get("type") == "audio":
            buf += msg["data"]
    if not buf:
        raise RuntimeError("edge-tts returned no audio")
    return buf


def make_test_tts(cfg, out_wav=None):
    """Spec section 8, half 1: one small Khmer sentence -> TTS WAV (no RVC).

    This half only needs the ordinary voice packages, so the normal pipeline
    python can do it. The RVC half is separate on purpose: it needs the python
    that owns RVC (see main_cli below)."""
    import common as C
    tts_wav = out_wav or str(C.LOG_DIR / "preflight_test_tts.wav")
    log("test sentence -> Khmer TTS (" + cfg.get("tts_voice", "") + ")")
    mp3 = asyncio.run(_edge_once(TEST_TEXT, cfg.get("tts_voice", "km-KH-SreymomNeural"),
                                 cfg.get("tts_rate", "+0%")))
    C.LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(C.LOG_DIR / "preflight_test.mp3", "wb") as f:
        f.write(mp3)
    C.mp3_to_wav(cfg, str(C.LOG_DIR / "preflight_test.mp3"), tts_wav)
    ok, info, probs = C.validate_wav(tts_wav)
    if not ok:
        raise RuntimeError("TTS test audio invalid: " + "; ".join(probs))
    log(f"TTS ok ({info['duration']}s) -> RVC conversion")
    return tts_wav


def run_test(cfg, index_path, model_path, out_wav=None):
    """Spec section 8: BOTH halves in this interpreter (TTS -> RVC -> WAV).
    Returns the output wav path. Correct only when this interpreter has both
    the voice packages and RVC — 00_preflight.py --full decides that and uses
    main_cli (a subprocess) when the RVC python is a different interpreter."""
    import common as C
    out_wav = out_wav or str(C.LOG_DIR / "preflight_test.wav")
    tts_wav = make_test_tts(cfg)
    info2 = convert_wav(cfg.get("rvc_root"), model_path, index_path,
                        tts_wav, out_wav, cfg.get("rvc", {}))
    log(f"RVC ok ({info2['duration']}s, {info2.get('sr')} Hz)")
    return out_wav


# settings used when a caller does not pass --settings-json (the fixed
# configuration from the production spec: rmvpe / 0 / 0.75 / 0.33)
KNOWN_SETTINGS = {
    "pitch": 0,
    "f0_method": "rmvpe",
    "index_rate": 0.75,
    "resample_sr": 0,
    "rms_mix_rate": 1.0,
    "protect": 0.33,
}


def main_cli(argv=None):
    """Run the RVC half with the python that OWNS RVC.

        <rvc python> rvc_engine.py --rvc-root R --model M.pth \
                     --in in.wav --out out.wav [--index I.index] \
                     [--settings-json '{"pitch": 0, ...}']

    Why a command line: RVC lives in its own environment (a venv or the
    WebUI's runtime folder). The pipeline's ordinary python has neither torch
    nor soundfile nor the RVC packages, so importing RVC there fails no matter
    how correct the paths are — the work has to happen in the RVC interpreter.

    Exit code 0 = out.wav written and validated. Anything else prints the
    reason and exits non-zero, so the caller reports it and stops.
    """
    import argparse
    import json as _json

    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("--rvc-root", required=True,
                    help="the folder containing RVC.py / infer/")
    ap.add_argument("--model", required=True, help="the .pth voice model (full path)")
    ap.add_argument("--index", default="", help="the .index (optional)")
    ap.add_argument("--in", dest="in_wav", required=True, help="input wav")
    ap.add_argument("--out", dest="out_wav", required=True, help="output wav")
    ap.add_argument("--settings-json", default="",
                    help='config.json "rvc" settings as JSON (optional)')
    a = ap.parse_args(argv)

    settings = dict(KNOWN_SETTINGS)
    if a.settings_json.strip():
        try:
            settings.update(_json.loads(a.settings_json) or {})
        except Exception as e:
            log(f"unreadable --settings-json ({e}) — using the standard settings")
    info = convert_wav(a.rvc_root, a.model, (a.index or None), a.in_wav,
                       a.out_wav, settings)
    log(f"OK {info.get('duration')}s {info.get('sr')} Hz "
        f"f0={info.get('f0_used')} -> {a.out_wav}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main_cli())
    except SystemExit:
        raise
    except Exception as e:
        print("[rvc-engine] FAILED: " + str(e)[:400], file=sys.stderr, flush=True)
        sys.exit(2)
