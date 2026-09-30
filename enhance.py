#!/usr/bin/env python3
"""enhance.py — "Clean & Clear" mastering engine.

One shared engine, used by the AI_Agent pipeline (stage 05) and by Sonora.
Takes any speech WAV/MP3 and produces a broadcast-clean master:

    denoise -> tonal tidy-up -> de-ess -> gentle level -> 48 kHz -> loudness master

Two backends, in order of quality:

  model  (best)  clearvoice  MossFormer2_SE_48K (+ MossFormer2_SR_48K super-res)
                 deepfilternet  (denoise only, very fast)
                 — these need a torch environment; the RVC venv already has
                   torch, so install them THERE:
                       pip install clearvoice          (best, adds true 48k SR)
                       pip install deepfilternet       (light denoise only)

  ffmpeg         always available (bundled with RVC-WebUI / imageio-ffmpeg).
                 Denoise is spectral (afftdn), 48 kHz is a resample — no
                 invented high frequencies. Still a big "clear + polished" win.

CLI:
    python enhance.py --in in.wav --out out.wav [--json report.json]
                      [--tier auto|ffmpeg|model] [--ffmpeg PATH] [--quiet]
                      [--lufs -16] [--peak -1.0] [--sr 48000]
                      [--no-denoise] [--no-eq] [--deess 2.5]

Report JSON is always written when --json is given, including which stages
really ran — never claim a stage that did not run.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave

# ---------------------------------------------------------------- ffmpeg ----

def find_ffmpeg(explicit=None):
    if explicit and os.path.exists(explicit):
        return explicit
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    for p in (r"C:\ffmpeg\bin\ffmpeg.exe",
              os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe")):
        if os.path.exists(p):
            return p
    return None


def _run(cmd, timeout=1800):
    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if r.returncode != 0:
        tail = (r.stderr or b"").decode("utf-8", "ignore")[-800:]
        raise RuntimeError(f"ffmpeg failed ({r.returncode}): {tail}")
    return r


def probe_audio(ffmpeg, path):
    """Return {sr, channels, duration, codec} using ffmpeg -i (no ffprobe
    dependency — RVC installs always ship ffmpeg.exe, not always ffprobe)."""
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)],
                       capture_output=True)
    txt = (r.stderr or b"").decode("utf-8", "ignore")
    info = {"sr": 0, "channels": 0, "duration": 0.0, "codec": ""}
    m = re.search(r"Audio:\s*([a-zA-Z0-9_]+)", txt)
    if m:
        info["codec"] = m.group(1)
    m = re.search(r"(\d+)\s*Hz", txt)
    if m:
        info["sr"] = int(m.group(1))
    m = re.search(r"(mono|stereo)", txt)
    if m:
        info["channels"] = 1 if m.group(1) == "mono" else 2
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", txt)
    if m:
        info["duration"] = (int(m.group(1)) * 3600 + int(m.group(2)) * 60
                            + float(m.group(3)))
    return info


def measure_loudness(ffmpeg, path, target_i=-16.0, target_tp=-1.0, lra=9.0):
    """One print_format=json loudnorm scan (the standard first pass)."""
    cmd = [ffmpeg, "-hide_banner", "-nostats", "-i", str(path),
           "-af", f"loudnorm=I={target_i}:TP={target_tp}:LRA={lra}:"
                  f"print_format=json", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True)
    txt = (r.stderr or b"").decode("utf-8", "ignore")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", txt, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return {k: float(v) for k, v in d.items() if k.startswith("input_")
                and v not in ("", "-inf")}
    except Exception:
        return None


# ----------------------------------------------------------- model tiers ----

def model_backends():
    """Which torch-based denoisers are importable in THIS python.
    Cheap check: find_spec (no heavy imports, no model downloads)."""
    have = []
    try:
        import importlib.util
        if importlib.util.find_spec("clearvoice") is not None:
            have.append("clearvoice")
        if importlib.util.find_spec("df") is not None:      # DeepFilterNet
            have.append("deepfilternet")
    except Exception:
        pass
    return have



# ------------------------------------------------- ClearVoice weights -----
# ClearVoice downloads its checkpoints relative to the CURRENT WORKING
# DIRECTORY and (observed on clearvoice 0.1.2) it does not fetch the
# super-resolution weights at all. So we fetch them ourselves, into
# <base>/checkpoints/<model>/, and run ClearVoice from <base>.

CV_REPOS = {
    "MossFormer2_SE_48K": ("alibabasglab/MossFormer2_SE_48K",
                           "last_best_checkpoint.pt"),
    "MossFormer2_SR_48K": ("alibabasglab/MossFormer2_SR_48K",
                           "last_best_checkpoint_m.pt"),
}


def cv_weights_dir(base, model):
    return os.path.join(base, "checkpoints", model)


def cv_weights_ready(base, model):
    repo, fname = CV_REPOS[model]
    return os.path.exists(os.path.join(cv_weights_dir(base, model), fname))


def fetch_cv_weights(base, model, log=None, timeout=1800):
    """Download a missing ClearVoice checkpoint. Returns True when present."""
    import urllib.request
    repo, fname = CV_REPOS[model]
    dest_dir = cv_weights_dir(base, model)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, fname)
    if os.path.exists(dest):
        return True
    url = f"https://huggingface.co/{repo}/resolve/main/{fname}"
    tmp = dest + ".part"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "sonora"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            last_pct = -10
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if total:
                    pct = int(got * 100 / total)
                    if pct >= last_pct + 10:
                        last_pct = pct
                        if log is not None:
                            log.append(f"downloading {model} weights… {pct}%")
        os.replace(tmp, dest)
        if log is not None:
            log.append(f"{model} weights ready ({got // 1048576} MB)")
        return True
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        if log is not None:
            log.append(f"could not download {model} weights "
                       f"({type(e).__name__}: {e})")
        return False


def ensure_cv_models(base, super_res, log=None):
    """Make sure the weights for SE (and SR when wanted) exist locally."""
    ok_se = (cv_weights_ready(base, "MossFormer2_SE_48K")
             or fetch_cv_weights(base, "MossFormer2_SE_48K", log))
    ok_sr = True
    if super_res:
        ok_sr = (cv_weights_ready(base, "MossFormer2_SR_48K")
                 or fetch_cv_weights(base, "MossFormer2_SR_48K", log))
    return ok_se, ok_sr


def _run_clearvoice(src, dst, cfg, log):
    """MossFormer2: 48 kHz enhance (+ optional super-resolution).

    Runs with the CWD set to cfg['cv_base'] because ClearVoice resolves its
    `checkpoints/` folder relative to the working directory. If the SR model
    is missing or cannot run (e.g. not enough RAM), we keep the SE result and
    say so — never a failed job.
    """
    from clearvoice import ClearVoice
    import numpy as np
    import soundfile as sf

    base = cfg.get("cv_base") or os.getcwd()
    os.makedirs(os.path.join(base, "checkpoints"), exist_ok=True)
    ok_se, ok_sr = ensure_cv_models(base, cfg.get("super_res"), log)
    if not ok_se:
        raise RuntimeError("ClearVoice SE weights unavailable (no internet?)")

    prev_cwd = os.getcwd()
    try:
        os.chdir(base)
        work = os.path.abspath(str(src))
        cv = ClearVoice(task="speech_enhancement",
                        model_names=["MossFormer2_SE_48K"])
        out = np.asarray(cv(input_path=work, online_write=False)).squeeze()
        data = out.astype("float32")
        rate = 48000
        log.append("denoise: MossFormer2_SE_48K (48 kHz)")

        if cfg.get("super_res") and ok_sr:
            se_path = os.path.join(tempfile.gettempdir(), "_cv_se_in.wav")
            sr_path = os.path.join(tempfile.gettempdir(), "_cv_sr_out.wav")
            sf.write(se_path, data, rate)
            ok_sr_run, why = _run_sr_subprocess(base, se_path, sr_path)
            if ok_sr_run:
                try:
                    import soundfile as _sf2
                    sr_data, _ = _sf2.read(sr_path, dtype="float32")
                    data = sr_data.squeeze().astype("float32")
                    cfg["sr_done"] = True
                    log.append("super-res: MossFormer2_SR_48K — high "
                               "frequencies reconstructed")
                except Exception as e:
                    log.append(f"super-res output unreadable "
                               f"({type(e).__name__}) — enhancer output kept")
                finally:
                    for p in (se_path, sr_path):
                        try:
                            os.remove(p)
                        except OSError:
                            pass
            else:
                log.append(f"super-res skipped ({why}) — enhancer output kept "
                           f"(no invented high frequencies)")
    finally:
        os.chdir(prev_cwd)

    sf.write(dst, data, min(cfg["sr"], 48000))
    return True


def _run_deepfilternet(src, dst, cfg, log):
    """DeepFilterNet — fast, light denoise (48 kHz native)."""
    from df.enhance import init_df, enhance, save_audio
    from df.io import load_audio
    model, state, _ = init_df()
    audio, _ = load_audio(str(src), sr=state.sr())
    audio = enhance(model, state, audio)
    save_audio(str(dst), audio, state.sr())
    log.append(f"denoise: DeepFilterNet ({state.sr()} Hz)")
    return True


def model_polish(src, dst, cfg, log):
    """Try model backends in quality order. Returns (backend, reasons)."""
    reasons = []
    for name in ("clearvoice", "deepfilternet"):
        if name not in model_backends():
            reasons.append(f"{name} is not installed in this python")
            continue
        try:
            if name == "clearvoice":
                _run_clearvoice(src, dst, cfg, log)
            else:
                _run_deepfilternet(src, dst, cfg, log)
            return name, reasons
        except Exception as e:
            msg = f"{name} failed: {type(e).__name__}: {e}"
            log.append(msg + " — trying next")
            reasons.append(msg)
    return "", reasons



# ---------------------------------------------- dependency auto-resolver ---
# clearvoice pulls a long tail of small packages, and which ones are missing
# depends on what the user's RVC environment already has. Instead of guessing
# a fixed list, we ask the TARGET python to import the package and install
# exactly the module it reports missing — repeat until it imports.
# modules the neural engine touches at runtime (probed before/after install)
PROBE_MODULES = ["torch", "torchaudio", "yamlargparse", "pydub", "einops",
                 "rotary_embedding_torch", "torchinfo", "huggingface_hub",
                 "soundfile", "joblib", "packaging", "tqdm", "scipy", "gdown",
                 "sklearn", "cv2", "scenedetect", "librosa", "numpy",
                 "httpx2", "httpcore2", "truststore", "httpx", "httpcore"]

MODULE_TO_PKG = {
    "cv2": "opencv-python-headless",
    "httpx2": "httpx2",
    "httpcore2": "httpcore2",
    "sklearn": "scikit-learn",
    "yaml": "pyyaml",
    "df": "deepfilternet",
    "PIL": "pillow",
    "pkg_resources": "setuptools",
    "yaml": "pyyaml",
}


def _torchaudio_pin(python):
    """torchaudio must match the installed torch version, otherwise it fails
    to load (or drags in a different CUDA build). Returns 'torchaudio==X.Y.Z'."""
    try:
        r = subprocess.run(
            [python, "-c", "import torch;print(torch.__version__)"],
            capture_output=True, timeout=120)
        if r.returncode == 0:
            v = (r.stdout or b"").decode().strip().split("+")[0]
            parts = v.split(".")
            if len(parts) >= 2:
                return "torchaudio==" + ".".join(parts[:3])
    except Exception:
        pass
    return ""


def resolve_dependencies(python=None, package="clearvoice", rounds=8, log=None):
    """Import-driven dependency resolution for `package` in `python`.

    `import clearvoice` alone is not enough — it imports its real dependencies
    lazily, when a model is built. So we probe the whole module set the engine
    touches at runtime, and install exactly what is reported missing.
    Returns (ok, steps). Uses --no-deps only, so numpy and torch can never be
    touched, and a missing torchaudio is pinned to the installed torch version.
    """
    import subprocess as _sp
    python = python or sys.executable
    probes = [package] + [m for m in PROBE_MODULES if m != package]
    steps = []

    def note(msg):
        steps.append(msg)
        if log is not None:
            log.append(msg)

    for _ in range(rounds):
        missing = []          # (module that failed, module pip must install)
        for mod in probes:
            try:
                r = _sp.run([python, "-c", "import " + mod],
                            capture_output=True, timeout=900)
            except Exception as e:
                note("probe " + mod + " errored: " + type(e).__name__)
                return False, steps
            if r.returncode == 0:
                continue
            out = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "ignore")
            m = re.search(r"No module named '([^']+)'", out)
            if not m:
                last = [l.strip() for l in out.strip().splitlines() if l.strip()]
                note("probe " + mod + " failed hard: " +
                     (last[-1][:160] if last else "unknown"))
                return False, steps
            reported = m.group(1).split(".")[0]
            if reported == "torch":
                note("that python has no torch — it is not the RVC environment")
                return False, steps
            missing.append(reported)

        if not missing:
            note("all " + str(len(probes)) + " modules import: OK")
            return True, steps

        for mod in dict.fromkeys(missing):
            if mod == "torchaudio":
                target = _torchaudio_pin(python)
                if not target:
                    note("torchaudio missing and torch version unknown")
                    return False, steps
            else:
                target = MODULE_TO_PKG.get(mod, mod)
            try:
                r2 = _sp.run([python, "-m", "pip", "install", "--no-deps", target],
                             capture_output=True, timeout=3600)
            except Exception as e:
                note("pip " + target + " failed: " + type(e).__name__)
                return False, steps
            tail = [l.strip() for l in
                    ((r2.stdout or b"") + (r2.stderr or b"")).decode(
                        "utf-8", "ignore").splitlines() if l.strip()]
            note("installed " + target + " (exit " + str(r2.returncode) + ")"
                 + ((" | " + tail[-1][:150]) if tail and r2.returncode else ""))
            if r2.returncode != 0:
                return False, steps
    note("still incomplete after " + str(rounds) + " rounds")
    return False, steps



# ------------------------------------------------------------ ffmpeg chain --

def build_filter_chain(cfg):
    """The 'polish' chain. Gentle on purpose: over-denoising synthetic speech
    adds artifacts, and RVC output is already fairly clean."""
    f = []
    if cfg["denoise"] and not cfg["model_denoised"]:
        # spectral denoise, conservative: 8 dB reduction, noise floor -45 dB
        f.append("afftdn=nr=8:nf=-45:tn=1")
    f.append("highpass=f=70")                      # rumble / DC
    if cfg["eq"]:
        f.append("equalizer=f=250:t=q:w=1.0:g=-1.5")     # mud
        f.append("equalizer=f=3500:t=q:w=1.5:g=1.2")     # presence/definition
        f.append(f"equalizer=f=7500:t=q:w=2.0:g=-{cfg['deess']}")  # sibilance
    f.append("acompressor=threshold=-18dB:ratio=2.2:attack=10:release=180:"
             "makeup=1.0")
    f.append(f"aresample={cfg['sr']}:resampler=soxr:precision=28")
    return ",".join(f)


def process(in_path, out_path, cfg, log, ffmpeg):
    """Full chain. Writes a 16-bit WAV at cfg['sr']."""
    tmpdir = tempfile.mkdtemp(prefix="clean_")
    try:
        stage = str(in_path)
        backend = ""
        if cfg["tier"] in ("auto", "model"):
            model_out = os.path.join(tmpdir, "model.wav")
            backend, reasons = model_polish(stage, model_out, cfg, log)
            if backend:
                stage = model_out
                cfg["model_denoised"] = True
            elif cfg["tier"] == "model":
                detail = "; ".join(reasons) or "no model backend available"
                raise RuntimeError(
                    "neural engine requested but could not run — " + detail
                    + "   (fix: install it, or set clean_master.tier to "
                      "\"auto\" / \"ffmpeg\" to use the built-in chain)")

        # 1) polish chain -> 48k wav (no loudness yet)
        chain_wav = os.path.join(tmpdir, "chain.wav")
        chain = build_filter_chain(cfg)
        _run([ffmpeg, "-hide_banner", "-nostats", "-y", "-i", stage,
              "-af", chain, "-ac", "1", "-c:a", "pcm_s16le", chain_wav])
        log.append("polish: " + chain)

        # 2) measure, 3) master (two-pass loudnorm, linear, plus limiter)
        meas = measure_loudness(ffmpeg, chain_wav, cfg["lufs"], cfg["peak"],
                                cfg["lra"])
        lim = min(0.99, 10 ** (cfg["peak"] / 20.0))   # e.g. -1 dB -> 0.891
        if meas:
            ln = (f"loudnorm=I={cfg['lufs']}:TP={cfg['peak']}:LRA={cfg['lra']}"
                  f":measured_I={meas.get('input_i', cfg['lufs'])}"
                  f":measured_TP={meas.get('input_tp', cfg['peak'])}"
                  f":measured_LRA={meas.get('input_lra', cfg['lra'])}"
                  f":measured_thresh={meas.get('input_thresh', -40)}"
                  f":offset={meas.get('target_offset', 0)}:linear=true")
            log.append("master: two-pass loudnorm "
                       f"(measured {meas.get('input_i', '?')} LUFS -> "
                       f"{cfg['lufs']} LUFS)")
        else:
            ln = (f"loudnorm=I={cfg['lufs']}:TP={cfg['peak']}:LRA={cfg['lra']}")
            log.append("master: one-pass loudnorm (measure failed)")
        master = (f"{ln},alimiter=limit={lim:.3f}:level=0")
        _run([ffmpeg, "-hide_banner", "-nostats", "-y", "-i", chain_wav,
              "-af", master, "-ac", "1", "-ar", str(cfg["sr"]),
              "-c:a", "pcm_s16le", out_path])
        log.append("master: limiter")
        return backend
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)



_SR_SNIPPET = """
import sys
from clearvoice import ClearVoice
import numpy as np, soundfile as sf
src, dst = sys.argv[1], sys.argv[2]
cv = ClearVoice(task="speech_super_resolution", model_names=["MossFormer2_SR_48K"])
out = np.asarray(cv(input_path=src, online_write=False)).squeeze()
sf.write(dst, out.astype("float32"), 48000)
print("SR_OK")
"""


def _run_sr_subprocess(base, src_wav, dst_wav, timeout=1800):
    """Run the (memory-hungry) SR model in its own process so an OOM kill or
    a crash degrades gracefully instead of taking the whole job down.
    Returns (ok, reason)."""
    try:
        r = subprocess.run([sys.executable, "-c", _SR_SNIPPET, src_wav, dst_wav],
                           cwd=base, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    if r.returncode != 0 or not os.path.exists(dst_wav):
        tail = (r.stderr or b"").decode("utf-8", "ignore").strip().splitlines()
        msg = tail[-1][:140] if tail else f"exit code {r.returncode}"
        if r.returncode in (137, -9):
            msg = "not enough memory for the super-resolution model"
        return False, msg
    return True, ""



def wav_stats(path):
    try:
        with wave.open(str(path), "rb") as w:
            sr = w.getframerate()
            n = w.getnframes()
            return {"sr": sr, "duration": round(n / sr, 3),
                    "channels": w.getnchannels(), "sampwidth": w.getsampwidth()}
    except Exception:
        return {"sr": 0, "duration": 0.0}


# ---------------------------------------------------------------- public ----

def enhance_file(in_path, out_path, tier="auto", ffmpeg=None, lufs=-16.0,
                 peak=-1.0, sr=48000, lra=9.0, denoise=True, eq=True,
                 deess=2.5, super_res=True, base=None):
    """Used by both tools. Returns a report dict (never raises on soft
    problems — the caller decides). Raises only if nothing could be done."""
    log = []
    ff = find_ffmpeg(ffmpeg)
    if not ff:
        raise RuntimeError("ffmpeg not found — set it in config (ffmpeg.exe "
                           "ships inside your RVC-WebUI folder)")
    cfg = {"tier": tier, "sr": int(sr), "lufs": float(lufs),
           "peak": float(peak), "lra": float(lra), "denoise": bool(denoise),
           "eq": bool(eq), "deess": float(deess),
           "super_res": bool(super_res), "model_denoised": False,
           "sr_done": False, "cv_base": base or os.getcwd()}
    before = probe_audio(ff, in_path)
    in_loud = measure_loudness(ff, in_path, cfg["lufs"], cfg["peak"], cfg["lra"])
    backend = process(in_path, out_path, cfg, log, ff)
    after = probe_audio(ff, out_path)
    out_loud = measure_loudness(ff, out_path, cfg["lufs"], cfg["peak"], cfg["lra"])
    rep = {
        "ok": bool(after["duration"] > 0),
        "in": {"path": str(in_path), **before,
               "lufs": (in_loud or {}).get("input_i")},
        "out": {"path": str(out_path), **after,
                "lufs": (out_loud or {}).get("input_i"),
                "true_peak_db": (out_loud or {}).get("input_tp")},
        "backend": backend or "ffmpeg",
        "stages": log,
        "target": {"lufs": cfg["lufs"], "true_peak_db": cfg["peak"],
                   "sr": cfg["sr"]},
        "bandwidth_extension": bool(cfg.get("sr_done")),
    }
    return rep


def main():
    ap = argparse.ArgumentParser(description="Clean & Clear mastering")
    ap.add_argument("--in", dest="inp", default="")
    ap.add_argument("--out", dest="out", default="")
    ap.add_argument("--json", dest="json_out", default="")
    ap.add_argument("--tier", default="auto", choices=["auto", "ffmpeg", "model"])
    ap.add_argument("--ffmpeg", default="")
    ap.add_argument("--lufs", type=float, default=-16.0)
    ap.add_argument("--peak", type=float, default=-1.0)
    ap.add_argument("--sr", type=int, default=48000)
    ap.add_argument("--lra", type=float, default=9.0)
    ap.add_argument("--deess", type=float, default=2.5)
    ap.add_argument("--no-denoise", action="store_true")
    ap.add_argument("--no-eq", action="store_true")
    ap.add_argument("--no-super-res", action="store_true")
    ap.add_argument("--probe", action="store_true",
                    help="print available backends as JSON and exit")
    a = ap.parse_args()

    if not a.probe and (not a.inp or not a.out):
        ap.error("--in and --out are required (or use --probe)")

    if a.probe:
        print(json.dumps({"ffmpeg": find_ffmpeg(a.ffmpeg),
                          "model_backends": model_backends(),
                          "python": sys.executable}))
        return

    rep = enhance_file(a.inp, a.out, tier=a.tier, ffmpeg=a.ffmpeg,
                       lufs=a.lufs, peak=a.peak, sr=a.sr, lra=a.lra,
                       denoise=not a.no_denoise, eq=not a.no_eq,
                       deess=a.deess, super_res=not a.no_super_res)
    if a.json_out:
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1, ensure_ascii=False)
    print(json.dumps({k: rep[k] for k in
                      ("ok", "backend", "bandwidth_extension")},
                     ensure_ascii=False))
    if not rep["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
