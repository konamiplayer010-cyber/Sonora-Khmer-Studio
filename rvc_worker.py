#!/usr/bin/env python
r"""Sonora RVC clone worker.

Runs inside your RVC-WebUI Python environment (the one with torch + the RVC
repo). Loads your RVC model ONCE at startup using RVC's own VC class, then
serves local HTTP on 127.0.0.1 (never the network) so Sonora can re-voice
each synthesized line through your cloned voice:

    GET  /health   -> {"state": "loading"|"ready"|"error", "error": str,
                       "model": str, "device": str, "api": str, "log": str}
    POST /convert  -> JSON {"wav_b64": <input wav base64>, "pitch": int,
                           "index_rate": float, "protect": float,
                           "f0_method": str}
                      -> 200 JSON {"wav_b64": <converted wav base64>}

Sonora starts this automatically; you normally never run it by hand.

Usage (for debugging):
    python rvc_worker.py --rvc-dir C:\RVC-WebUI \
        --model weights\Sonaro-kh.pth \
        --index "logs\Sonaro-kh\added_IVF_Sonaro-kh_v2.index" --port 18950
"""
import argparse
import base64
import json
import os
import platform
import sys
import tempfile
import threading
import time
import traceback
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)          # embedded runtimes skip this on their own
try:
    from sonora_paths import resolve_model_field, resolve_index_field
except Exception:                     # never let a helper break the worker
    resolve_model_field = resolve_index_field = None

STATE = {"state": "loading", "error": "", "model": "", "device": "",
         "api": "", "started": time.time(), "notes": [], "identity": {},
         "half": False, "warmup_s": None, "rtf": None}
MODEL = {}
CONV_LOCK = threading.Lock()  # RVC inference is not thread-safe
LOG_TAIL = []


def log(msg):
    line = "[rvc-worker] " + str(msg)
    print(line, flush=True)
    LOG_TAIL.append(line)
    if len(LOG_TAIL) > 40:
        del LOG_TAIL[:len(LOG_TAIL) - 40]


def resolve(base_dir, p):
    return p if (not p or os.path.isabs(p)) else os.path.join(base_dir, p)


# ------------------------------------------------------------------ setup --

def setup_env(rvc_dir, model_path):
    os.chdir(rvc_dir)
    sys.path.insert(0, rvc_dir)
    os.environ["weight_root"] = os.path.dirname(model_path)
    os.environ.setdefault("index_root", os.path.join(rvc_dir, "logs"))
    os.environ.setdefault("outside_index_root",
                          os.path.join(rvc_dir, "assets", "indices"))
    os.environ.setdefault("rmvpe_root",
                          os.path.join(rvc_dir, "assets", "rmvpe"))
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")


def make_config():
    """RVC's Config() parses sys.argv — guard it (same trick RVC's own CLI uses)."""
    saved = sys.argv[:]
    sys.argv = [sys.argv[0]]
    try:
        from configs.config import Config
        return Config()
    finally:
        sys.argv = saved


def _auto_find_index(rvc_dir, model_name):
    """Find the index for model_name when the user left the field blank.

    Looks in assets/indices/ (2.3+) and logs/ (classic); prefers names that
    contain the model's base name, then "added" (test) indexes over
    "trained", then the most recent file.
    """
    base = os.path.splitext(model_name)[0].lower()
    pools = []
    for sub in (os.path.join(rvc_dir, "assets", "indices"),
                os.path.join(rvc_dir, "logs")):
        if not os.path.isdir(sub):
            continue
        for dp, dn, fn in os.walk(sub):
            for f in fn:
                if f.lower().endswith(".index"):
                    pools.append(os.path.join(dp, f))
    scored = [p for p in pools if base in os.path.basename(p).lower()]
    if not scored:
        return ""
    added = [p for p in scored if "added" in os.path.basename(p).lower()]
    pool = added or scored
    return max(pool, key=lambda p: os.path.getmtime(p))



def _diagnose_model_file(path):
    """Why a .pth is not usable as an RVC voice model. Returns a short,
    printable explanation ('' when we cannot tell)."""
    import os as _os
    base = _os.path.basename(path)
    mb = _os.path.getsize(path) / 1048576.0 if _os.path.exists(path) else 0
    if base[:2].upper() in ("G_", "D_"):
        return ("this is a TRAINING CHECKPOINT (" + base + "), not a voice "
                "model. In RVC-WebUI open the ckpt-processing tab (it also "
                "holds 'model fusion') and run 'extract small model' on the "
                "newest G_*.pth, saving it as assets/weights/Sonaro-kh.pth — "
                "then point MODEL at that file.")
    if mb >= 150:
        return (f"this file is {mb:.0f} MB — that size means a training "
                "checkpoint, not the small voice model. Extract the small "
                "model in RVC-WebUI's ckpt-processing tab.")
    try:
        import torch
        ckpt = torch.load(path, map_location="cpu")
        if isinstance(ckpt, dict):
            keys = [str(k) for k in ckpt.keys()]
            low = [k.lower() for k in keys]
            if "weight" not in low:
                if any(k.startswith(("enc_p", "dec", "emb_", "flow", "dp"))
                       for k in keys) or "optimizer" in low or "model" in low:
                    return ("this .pth holds training weights (keys: "
                            + ", ".join(keys[:5]) + " …), not the small voice "
                            "model. Extract the small model in RVC-WebUI's "
                            "ckpt-processing tab.")
                return ("this .pth has no 'weight' entry (keys: "
                        + ", ".join(keys[:6]) + ") — it is not an RVC voice "
                        "model.")
    except Exception as e:
        return f"could not read it as a model ({type(e).__name__})."
    return ""

def load_model(args):
    rvc_dir = os.path.abspath(args.rvc_dir)

    # The MODEL field is whatever the user typed: a file, a bare name, or the
    # FOLDER that holds it. Resolve it (and say so when we had to interpret).
    if resolve_model_field is not None:
        model_path, note = resolve_model_field(rvc_dir, args.model,
                                               prefer=["Sonaro-kh.pth",
                                                       STATE.get("model") or ""])
    else:
        model_path, note = resolve(rvc_dir, args.model), ""
    if note:
        log("MODEL: " + note)
        STATE["notes"].append("MODEL: " + note)
    if not model_path:
        raise FileNotFoundError(note or ("model file not found: " + str(args.model)))
    # a folder slipped through in some other field shape — never hand RVC one
    if os.path.isdir(model_path):
        raise FileNotFoundError(
            "the MODEL field is a folder (" + model_path + "). Put the .pth "
            "file in it (or just the folder name) — Sonora picks the file "
            "inside when it can.")
    log("MODEL field -> " + model_path)

    if resolve_index_field is not None:
        index_path, inote = resolve_index_field(
            rvc_dir, args.index, prefer=[os.path.basename(model_path)])
    else:
        index_path, inote = resolve(rvc_dir, args.index), ""
    if inote:
        log("INDEX: " + inote)
        STATE["notes"].append("INDEX: " + inote)
    if index_path and not os.path.exists(index_path):
        log("WARNING: index file not found: " + index_path +
            " — continuing without index (slightly less accurate)")
        index_path = ""
    if not index_path:
        index_path = _auto_find_index(rvc_dir, os.path.basename(model_path))
        if index_path:
            log("index not set — auto-selected: " +
                os.path.relpath(index_path, rvc_dir).replace("\\", "/"))

    try:
        import torch
    except ImportError:
        raise RuntimeError(
            "this python has no torch — it is NOT the RVC environment "
            f"(worker python: {sys.executable}). Set the RVC PYTHON field in "
            "Sonora's RVC section to the python.exe that runs your RVC-WebUI "
            "(usually <RVC folder>\\venv\\Scripts\\python.exe, or the python "
            "your WebUI shortcut calls).")
    log(f"python={sys.executable} ({platform.python_version()}) "
        f"torch={torch.__version__} cuda={torch.cuda.is_available()}")

    setup_env(rvc_dir, model_path)

    # modern RVC's CLI creates this before VC(config) — keep parity
    try:
        from i18n.i18n import I18nAuto
        I18nAuto()
    except Exception:
        pass

    config = make_config()
    STATE["device"] = str(getattr(config, "device", "")) or "cpu"

    # ---- fp16 (half precision): the biggest speed knob -------------------
    # RVC's WebUI runs fp16 on CUDA cards with compute capability >= 7 (the
    # same rule used here). fp16 roughly halves the time of the two heavy
    # stages (hubert features + the generator) and is inaudible — and if the
    # card dislikes it, the warm-up below switches back to fp32 by itself.
    want_half = None
    try:
        if STATE["device"].lower().startswith("cuda") and torch.cuda.is_available():
            cap = torch.cuda.get_device_capability(0)
            want_half = cap[0] >= 7
    except Exception:
        want_half = None
    if want_half is not None:
        try:
            had = getattr(config, "is_half", None)
            if had != want_half:
                config.is_half = want_half
                os.environ["is_half"] = "True" if want_half else "False"
                log(f"fp16: is_half {had} -> {want_half}")
        except Exception as e:
            log("fp16: could not set is_half (" + str(e)[:80] + ")")
    try:
        STATE["half"] = bool(getattr(config, "is_half", False))
    except Exception:
        STATE["half"] = False
    log("precision: " + ("fp16 (half)" if STATE["half"] else "fp32")
        + " on " + STATE["device"])

    # RVC moved its module layout across versions — try the known locations.
    errs = []
    vc = None
    for mod in ("infer.vc.modules", "infer.modules.vc.modules"):
        try:
            VC = __import__(mod, fromlist=["VC"]).VC
            vc = VC(config)
            log("using RVC API: " + mod)
            STATE["api"] = mod
            break
        except Exception as e:
            errs.append(f"{mod}: {str(e)[:150]}")
    if vc is None:
        raise RuntimeError(
            "cannot import RVC's VC class — is the RVC folder the root of "
            "RVC-WebUI, and is its Python environment complete? details: "
            + " | ".join(errs)[:300])

    base = os.path.basename(model_path)
    names = [base, base[:-4] if base.lower().endswith(".pth") else base + ".pth"]
    last_err = ""
    for nm in dict.fromkeys(names + [model_path]):
        try:
            vc.get_vc(nm)
            log("model loaded via get_vc('" + nm + "')")
            break
        except Exception as e:
            last_err = str(e)[:200]
    else:
        why = _diagnose_model_file(model_path)
        raise RuntimeError(
            "RVC could not load the model file " + model_path + " — " + last_err
            + (("\n   >> " + why) if why else
               "\n   >> check that the MODEL field names this file "
               "(assets/weights/" + base + "), and that it was trained for "
               "this RVC version (v2) and sample rate."))

    # ---- identity: what did we ACTUALLY load? -------------------------
    # Users keep asking "is this the female model?" — the answer is in the
    # file itself: RVC stores the training metadata in the checkpoint, and VC
    # keeps the sample rate + version in memory.
    ident = {"file": os.path.basename(model_path),
             "path": model_path,
             "index": os.path.basename(index_path) if index_path else ""}
    try:
        ident["size_mb"] = round(os.path.getsize(model_path) / 1048576.0, 1)
    except Exception:
        pass
    try:
        ident["sr"] = int(getattr(vc, "tgt_sr", 0)) or None
    except Exception:
        ident["sr"] = None
    try:
        ident["version"] = str(getattr(vc, "version", "") or "") or None
    except Exception:
        ident["version"] = None
    try:
        cpt = getattr(vc, "cpt", None)
        if isinstance(cpt, dict):
            info = cpt.get("info")
            if info:
                ident["info"] = str(info)[:300]
            for k in ("f0", "sr", "version"):
                if k in cpt and not ident.get(k):
                    ident[k] = cpt[k]
    except Exception:
        pass
    STATE["identity"] = ident
    log("model identity: " + json.dumps(ident, ensure_ascii=False)[:400])

    MODEL["vc"] = vc
    MODEL["index"] = index_path
    MODEL["torch"] = torch
    _warmup(vc)
    return STATE["device"]


# -------------------------------------------------------------- conversion --

def _write_wav(path, arr, sr):
    import numpy as np
    a = np.asarray(arr, dtype=np.float32)
    amax = float(np.max(np.abs(a))) if a.size else 0.0
    if amax > 1.0:
        a = a / amax
    i16 = (np.clip(a, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(i16.tobytes())


def _vc_single(vc, in_p, pitch, f0_method, index_rate, protect):
    """vc_single across RVC generations:
    modern: (sid, input, pitch, f0_method, index, index_rate, resample_sr, rms, protect)
    classic: (sid, input, f0_up_key, f0_file, f0_method, index, index2,
              index_rate, filter_radius, resample_sr, rms, protect)"""
    index = MODEL.get("index") or ""
    sid = 0
    # (name, args-before-method, args-after-method)
    templates = [
        ("modern", [sid, in_p, int(pitch)],
         [index, float(index_rate), 0, 1.0, float(protect)]),
        ("classic", [sid, in_p, int(pitch), None],
         [index, "", float(index_rate), 3, 0, 1.0, float(protect)]),
    ]
    # modern RVC only supports pm/rmvpe; classic also harvest/crepe
    methods = [f0_method]
    if f0_method not in ("pm", "rmvpe"):
        methods += ["rmvpe", "pm"]
    errs = []
    for method in methods:
        for name, pre, post in templates:
            try:
                out = vc.vc_single(*(pre + [method] + post))
            except TypeError as e:
                errs.append(f"{name}/{method}: {str(e)[:120]}")
                continue
            if isinstance(out, tuple) and len(out) == 2:
                status, res = out
            else:
                status, res = str(out), None
            if res is None or (isinstance(res, tuple)
                               and (res[0] is None or res[1] is None)):
                errs.append(f"{name}/{method}: {str(status)[:200]}")
                break  # signature OK — real failure, try next method
            return res, method, name
        # both arities raised TypeError for this method → wrong signature
        # everywhere, don't waste time on the next method
        if all(x.startswith(("modern", "classic")) and
               ("argument" in x or "positional" in x) for x in errs[-2:]):
            break
    raise RuntimeError("RVC conversion failed — " + " || ".join(errs[-3:]))


def _downgrade_fp32(vc):
    """A card that cannot do fp16 (rare, older GPUs): put the networks back in
    fp32 and carry on — slower, but it always works."""
    for attr in ("net_g", "hubert_model"):
        try:
            m = getattr(vc, attr, None)
            if m is not None and hasattr(m, "float"):
                m.float()
        except Exception:
            pass
    try:
        vc.is_half = False
    except Exception:
        pass
    STATE["half"] = False
    log("NOTE: fp16 failed during warm-up — this worker now runs fp32")


def _warmup(vc):
    """One throwaway conversion immediately after the model loads.

    CUDA builds its kernels and allocates its caches on the FIRST forward
    pass, and rmvpe/pitch nets load lazily too — so the first line of a real
    job used to cost 2-4x the rest. Paying that here (while the user is still
    looking at "starting model") makes every line of the job fast.
    """
    import numpy as np
    t0 = time.time()
    sr = 24000
    n = int(0.6 * sr)
    t = np.arange(n, dtype=np.float32) / float(sr)
    sig = (0.08 * np.sin(2.0 * np.pi * 220.0 * t)).astype(np.float32)
    with tempfile.TemporaryDirectory() as td:
        wp = os.path.join(td, "warm.wav")
        _write_wav(wp, sig, sr)
        try:
            _vc_single(vc, wp, 0, "rmvpe", 0.75, 0.33)
        except Exception as e:
            if STATE.get("half"):
                log("warm-up with fp16 failed (" + str(e)[:120] + ")")
                _downgrade_fp32(vc)
                _vc_single(vc, wp, 0, "rmvpe", 0.75, 0.33)
            else:
                raise
    STATE["warmup_s"] = round(time.time() - t0, 2)
    log(f"warm-up done in {STATE['warmup_s']}s — the first real line no "
        f"longer pays the start-up cost")


def convert_wav(wav_bytes, pitch, index_rate, protect, f0_method):
    with CONV_LOCK:
        with tempfile.TemporaryDirectory() as td:
            in_p = os.path.join(td, "in.wav")
            out_p = os.path.join(td, "out.wav")
            with open(in_p, "wb") as f:
                f.write(wav_bytes)
            t0 = time.time()
            (sr, audio), used_method, used_api = _vc_single(
                MODEL["vc"], in_p, pitch, f0_method, index_rate, protect)
            if used_method != f0_method:
                log(f"NOTE: {f0_method} unavailable — converted with "
                    f"{used_method}")
            _write_wav(out_p, audio, sr)
            with open(out_p, "rb") as f:
                out = f.read()
            dt = time.time() - t0
            in_s = max(0.001, (len(wav_bytes) - 44) / 2.0 / 24000.0)
            out_s = (len(audio) / float(sr)) if sr else in_s
            rtf = (out_s / dt) if dt > 0 else 0.0
            STATE["rtf"] = round(rtf, 2)
            log(f"converted {in_s:.1f}s of audio in {dt:.1f}s "
                f"({rtf:.1f}x realtime, {used_api}/{used_method}"
                + (", fp16" if STATE.get("half") else ", fp32") + ")")
            return out


# ------------------------------------------------------------------ HTTP ----

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, payload, binary=False):
        data = payload if binary else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type",
                         "application/octet-stream" if binary else "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?")[0] in ("/health", "/"):
            h = dict(STATE)
            h["log"] = "\n".join(LOG_TAIL[-12:])
            self._send(200, h)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.split("?")[0] != "/convert":
            self._send(404, {"error": "not found"})
            return
        if STATE["state"] != "ready":
            self._send(503, {"error": STATE["state"] +
                             (": " + STATE["error"] if STATE["error"] else "")})
            return
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
            wav = base64.b64decode(body.get("wav_b64", ""))
            if len(wav) < 1000:
                raise ValueError("empty input wav")
            out = convert_wav(wav, body.get("pitch", 0),
                              body.get("index_rate", 0.75),
                              body.get("protect", 0.33),
                              str(body.get("f0_method", "rmvpe")))
            self._send(200, {"wav_b64": base64.b64encode(out).decode()})
        except Exception as e:
            log("convert error: " + repr(e))
            self._send(500, {"error": str(e)[:400]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rvc-dir", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--index", default="")
    ap.add_argument("--port", type=int, default=18950)
    ap.add_argument("--f0-method", default="rmvpe",
                    choices=["rmvpe", "harvest", "crepe", "pm"])
    args = ap.parse_args()

    STATE["model"] = os.path.basename(args.model)
    try:
        load_model(args)
        STATE["state"] = "ready"
        log(f"READY: {STATE['model']} on {STATE['device']} — "
            f"{'fp16' if STATE.get('half') else 'fp32'}, "
            f"warm-up {STATE.get('warmup_s')}s, port {args.port}, "
            f"api={STATE['api']}")
    except Exception as e:
        STATE["state"] = "error"
        STATE["error"] = f"RVC model load failed: {e}"
        log(STATE["error"])
        log(traceback.format_exc()[-1500:])
        # serve /health even on error so Sonora can report the reason

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    log(f"serving on 127.0.0.1:{args.port} (state={STATE['state']})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
