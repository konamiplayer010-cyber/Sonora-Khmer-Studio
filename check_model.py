#!/usr/bin/env python3
"""check_model.py — "which .pth is my voice clone?"

RVC training produces a folder that looks like this (inside RVC-WebUI):

    logs/Sonaro-kh/
        0_gt_wavs/ 1_16k_wavs/     preprocessing artifacts — not models
        2a_f0/ 2b-f0nsf/           pitch data — not models
        3_feature768/              training features — not models
        G_233333.pth               TRAINING CHECKPOINT (big)  <-- NOT a voice model
        D_233333.pth               TRAINING CHECKPOINT (big)  <-- NOT a voice model
        eval/                      sample audio from training
        added_..._v2.index         feature index (inference — good)
        trained_..._v2.index       feature index (inference — ok)

The file RVC inference needs is the SMALL MODEL (~55-120 MB) that you create
from a training checkpoint with RVC-WebUI's ckpt-processing tab
("extract small model" / "模型提取"). It normally lives in:

    assets/weights/Sonaro-kh.pth          (2.3+ layout)
    weights/Sonaro-kh.pth                 (2.0-2.2 layout)

This script looks at every .pth under your RVC folder and says which ones
are usable, which are training checkpoints, and what to do.

Usage (run with the python that has torch = your RVC python):
    python check_model.py
    python check_model.py --rvc-root "E:\\...\\RVC20260718Nvidia"
    python check_model.py --file "E:\\...\\assets\\weights\\Sonaro-kh.pth"

Exit code 0 = at least one usable voice model found.
"""
import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

CHECKPOINT_HINTS = ("train", "checkpoint")
SMALL_MODEL_MIN = 5 * 1024 * 1024           # < 5 MB is suspicious
CHECKPOINT_MIN = 150 * 1024 * 1024          # > 150 MB is a training checkpoint


def looks_like_checkpoint_name(name):
    base = os.path.basename(name)
    return base[:2].upper() in ("G_", "D_") or \
        any(h in base.lower() for h in CHECKPOINT_HINTS)


def inspect_with_torch(path):
    """(verdict, detail). Uses torch when available."""
    try:
        import torch
    except ImportError:
        return None, "no torch in this python"
    try:
        ckpt = torch.load(str(path), map_location="cpu")
    except Exception as e:
        return "broken", f"cannot load: {type(e).__name__}: {e}"
    if not isinstance(ckpt, dict):
        return "unknown", f"contents: {type(ckpt).__name__}"
    keys = list(ckpt.keys())
    low = [str(k).lower() for k in keys]
    if "weight" in low:
        extra = [k for k in ("config", "f0", "version", "sr", "info")
                 if str(k).lower() in low]
        return "model", ("true RVC voice model (small model). "
                         f"extra keys: {', '.join(str(k) for k in extra) or '—'}")
    if "model" in low and len(keys) <= 6:
        return "checkpoint", ("training checkpoint (state_dict wrapper) — "
                              "extract the small model")
    if any(str(k).startswith(("enc_p", "dec", "emb_", "flow", "dp")) for k in keys):
        return "checkpoint", ("raw training checkpoint (generator weights) — "
                              "extract the small model")
    if "optimizer" in low or "iteration" in low or "epoch" in low:
        return "checkpoint", "training checkpoint (optimizer/iteration data)"
    return "unknown", f"top-level keys: {', '.join(str(k) for k in keys[:8])}"


def verdict_for(path):
    size = path.stat().st_size
    mb = size / 1048576.0
    verdict, detail = inspect_with_torch(path)
    if verdict is None:
        # no torch: name/size heuristics only
        if looks_like_checkpoint_name(path.name) or size >= CHECKPOINT_MIN:
            verdict = "checkpoint"
            detail = "name/size look like a training checkpoint (torch not " \
                     "available for a content check)"
        elif size >= SMALL_MODEL_MIN:
            verdict = "maybe"
            detail = "size fits an extracted voice model (torch not available " \
                     "for a content check)"
        else:
            verdict = "unknown"
            detail = f"only {mb:.1f} MB — too small for a voice model"
    elif verdict == "model" and size < SMALL_MODEL_MIN:
        detail += f"  (but only {mb:.1f} MB — probably truncated)"
    return verdict, detail, mb


def _read_train_log(path):
    """What did that training run ACTUALLY use? (SR, epochs, version)."""
    info = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(200_000)
            f.seek(0, 2)
            size = f.tell()
            if size > 400_000:
                f.seek(max(0, size - 200_000))
                tail = f.read()
            else:
                tail = head
    except Exception:
        return info
    txt = head + "\n" + tail
    for key, pat in (("sr", r"-sr\s+(\d+)"), ("te", r"-te\s+(\d+)"),
                     ("version", r"-v\s+(v\d)"), ("f0", r"-f0\s+(\d)"),
                     ("exp", r"(?:^|\s)-e\s+([^\s]+)")):
        m = re.findall(pat, txt)
        if m:
            info[key] = m[-1]
    done = [int(x) for x in re.findall(r"epoch\s*[:=]?\s*(\d+)", txt, re.I)]
    if done:
        info["epoch_seen"] = max(done)
    info["completed"] = ("all processes have been completed" in txt.lower()
                         or "training complete" in txt.lower())
    return info


def training_report(root):
    """Read logs/<experiment>/ and say exactly what to do with the result."""
    rootp = Path(root)
    logdir = rootp / "logs"
    if not logdir.is_dir():
        return
    exps = [d for d in sorted(logdir.iterdir())
            if d.is_dir() and d.name.lower() != "mute"]
    if not exps:
        return False

    weights = rootp / "assets" / "weights"
    if not weights.is_dir():
        weights = rootp / "weights"
    index_dirs = [rootp / "assets" / "indices", logdir]
    print()
    print("=" * 66)
    print("TRAINING RUNS FOUND (logs/)")
    print("=" * 66)
    for d in exps:
        ck = sorted(d.glob("G_*.pth"), key=lambda p: p.stat().st_mtime)
        if not ck:
            continue
        newest = ck[-1]
        log = d / "train.log"
        info = _read_train_log(log) if log.exists() else {}
        idx = sorted(d.glob("*.index"), key=lambda p: p.stat().st_mtime)
        small = []
        if weights.is_dir():
            small = [p for p in weights.glob("*.pth")
                     if d.name.lower() in p.name.lower()]
        sr = info.get("sr", "")
        sr_lab = ("48k" if sr.startswith("48") else
                  "40k" if sr.startswith("40") else
                  "32k" if sr.startswith("32") else (sr or "?"))
        print()
        print(f"  experiment : {d.name}")
        print(f"  trained at : {sr_lab}   version {info.get('version', '?')}   "
              f"pitch guidance {info.get('f0', '?')}")
        if info.get("te"):
            print(f"  epochs set : {info['te']}"
                  + (f"   (progress seen: epoch {info['epoch_seen']})"
                     if info.get("epoch_seen") else ""))
        print(f"  newest checkpoint : {newest.name} "
              f"({newest.stat().st_size / 1048576.0:.0f} MB)")
        if small:
            print(f"  small model in weights/ : {', '.join(p.name for p in small)}")
        else:
            print("  small model in weights/ : NONE — extract it (see below)")
        if idx:
            newest_idx = idx[-1]
            print(f"  index : {newest_idx.name}")
            copied = (rootp / "assets" / "indices" / newest_idx.name).exists() \
                or (rootp / "indices" / newest_idx.name).exists()
            if copied:
                print("          already copied to assets/indices — good")
            else:
                print("          COPY IT to assets/indices/  "
                      "(Sonora finds it automatically from there)")
        print("  what to do:")
        if small:
            print("    -> this run already produced a model you can TEST:")
            print(f"       RVC-WebUI -> Model Inference -> Refresh voice list -> "
                  f"pick {small[-1].name}")
            print("       Transpose 0, rmvpe, resample 0, protect 0.33, "
                  "index rate 0.75 -> Convert")
            print("       (or straight into Sonora: RVC VOICE CLONE -> MODEL = "
                  "that file, INDEX blank, PITCH 0)")
            print("    -> to extract a DIFFERENT checkpoint (e.g. epoch 150), "
                  "use ckpt-processing:")
        if sr_lab in ("40k", "48k"):
            print("    RVC-WebUI -> ckpt-processing -> Model extraction:")
            print(f"      Path to Model : {newest}")
            print(f"      Save name     : {d.name}")
            print(f"      Target sample rate : {sr_lab}   "
                  "(must match this run — the radio buttons are 32k/40k/48k)")
            print(f"      pitch guidance: 1     version: {info.get('version', 'v2')}")
            print("      -> Extract   (then it appears in assets/weights/)")
        low_epochs = info.get("te") and int(info["te"]) < 60
        if low_epochs:
            print(f"    NOTE: this run used only {info['te']} epochs — that is the "
                  "rough/muffled zone.")
            print("          Test it now, but expect to retrain with "
                  "total_epoch = 200 before it sounds like you.")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rvc-root", default="")
    ap.add_argument("--file", default="")
    ap.add_argument("--python", default="", help="(unused — informational)")
    a = ap.parse_args()

    root = a.rvc_root
    if not root and not a.file:
        cfg = C.load_config()
        root = cfg.get("rvc_root") or ""
    if a.file:
        files = [Path(a.file)]
    else:
        if not root or not os.path.isdir(root):
            print("[MISSING] RVC folder not found: " + (root or "(empty)"))
            sys.exit(1)
        rootp = Path(root)
        files = []
        for sub in ("assets/weights", "weights", "logs"):
            p = rootp / sub
            if p.is_dir():
                if sub == "logs":
                    files += sorted(p.glob("*/*.pth"))
                else:
                    files += sorted(p.glob("*.pth"))

    print("=" * 66)
    print("RVC model check")
    print("=" * 66)
    try:
        import torch as _t
        strength = f"full content check (torch {_t.__version__})"
    except Exception:
        strength = ("name and size only — this python has no torch; run with the "
                    "RVC python for a content check")
    print(f"python : {sys.executable}")
    print(f"check  : {strength}")
    cfg_now = C.load_config()
    configured = str(cfg_now.get("model_file") or "")
    if configured and not os.path.isabs(configured):
        configured = os.path.join(str(cfg_now.get("rvc_root") or ""), configured)
    print(f"config : {configured or '(model_file not set)'}")
    if not files:
        print("\nNo .pth file found at all.")
        print("  Looked in: assets/weights/, weights/, logs/*/")
        print("  If your training just finished, the small model has not been")
        print("  extracted yet — see the instructions below.")
    usable, checkpoints, broken = [], [], []
    print()
    for f in files:
        try:
            verdict, detail, mb = verdict_for(f)
        except Exception as e:
            verdict, detail, mb = "error", str(e), 0
        if verdict in ("model", "maybe"):
            usable.append((f, detail, mb))
        elif verdict == "checkpoint":
            checkpoints.append((f, mb))
            continue                       # summarised below, not spammed
        else:
            broken.append((f, detail, mb))
            continue
        tag = "[USABLE] " if verdict == "model" else "[?]      "
        print(f"{tag}{f}")
        print(f"            {mb:.1f} MB — {detail}")

    for f, detail, mb in broken:
        print(f"[?]      {f}")
        print(f"            {mb:.1f} MB — {detail}")

    if checkpoints:
        gb = sum(mb for _f, mb in checkpoints) / 1024.0
        newest = max(checkpoints, key=lambda x: x[1] * 0 + os.path.getmtime(x[0])
                     if os.path.exists(x[0]) else 0)
        print()
        print(f"[NOT A VOICE MODEL] {len(checkpoints)} training checkpoint(s) "
              f"(G_*.pth / D_*.pth) — {gb:.1f} GB. Inference never uses them;")
        print(f"            they matter only if you extract another small model")
        print(f"            (newest: {newest[0].name}). Nothing to do for a "
              f"normal run.")

    print()
    print("-" * 66)
    if usable:
        # the model the config already points at comes first and is called out
        cfg = C.load_config()
        want = str(cfg.get("model_file") or "")
        want_abs = want if os.path.isabs(want) else os.path.join(
            str(cfg.get("rvc_root") or ""), want)
        match = next((u for u in usable
                      if os.path.normcase(os.path.normpath(str(u[0]))) ==
                      os.path.normcase(os.path.normpath(want_abs))), None)
        if match:
            print("YOUR CONFIG ALREADY POINTS AT THIS ONE — nothing to change:")
            print("   " + str(match[0]))
            print(f'   "model_file": "{want}"')
            others = [u for u in usable if u is not match]
            if others:
                print(f"\n{len(others)} other voice model(s) are installed too "
                      f"(not used):")
                for f, _d, _mb in others:
                    print("   " + f.name)
                print("   If a converted chunk ever comes out as the wrong "
                      "person, check model_file first.")
        else:
            print(f"NOT FOUND: the model your config expects —")
            print(f'   "model_file": "{want}"')
            print("\nCandidates that DO exist:")
            for f, _d, _mb in usable:
                print("   " + str(f))
            print("\nPick the right one and set it in pipeline/config.json - the "
                  "file itself must not be renamed.")
        try:
            rel = usable[0][0].relative_to(Path(cfg.get("rvc_root") or ""))
            if not match:
                print(f'\n(relative form, if that is the one you want: '
                      f'"model_file": "{rel.as_posix()}")')
        except Exception:
            pass
        if root and os.path.isdir(root):
            training_report(root)
    else:
        detailed = (training_report(root)
                    if (root and os.path.isdir(root)) else False)
        print("NO USABLE VOICE MODEL FOUND.")
        print()
        if not detailed:
            print("What you have is the training workspace. G_*.pth / D_*.pth are")
            print("training checkpoints — inference cannot use them directly.")
            print()
            print("Fix (2 minutes, inside RVC-WebUI):")
            print("  1. Open your RVC-WebUI.")
            print("  2. Go to the checkpoint/ckpt-processing tab (it also holds")
            print("     'model fusion'; in some builds it is called ckpt处理 /")
            print("     'Model processing').")
            print("  3. Set the checkpoint path to your newest training checkpoint,")
            print("     e.g. logs/Sonaro-kh/G_233333.pth")
            print("  4. Set model name: Sonaro-kh     version: v2     sample rate: 40k")
            print("     (match what you trained with — the folder 3_feature768 means v2)")
            print("  5. Run 'Extract small model'.")
            print("  6. Save it as  assets/weights/Sonaro-kh.pth")
            print("  7. Run this script again — it should say [USABLE], then press")
            print("     Test clone in Sonora (or run run_all.bat).")
            print()
            print("If you are not sure which tab it is, send me a screenshot of the")
            print("RVC-WebUI tabs and I will point at it exactly.")
        sys.exit(1)



if __name__ == "__main__":
    main()
