#!/usr/bin/env python3
"""install_khmer_tts.py — add more Khmer voices/engines to this package.

What each engine gives you (see khmer_tts.py for the full table):

  edge-tts   Microsoft Neural km-KH Sreymom / Piseth   ~0 MB   internet
             the default: excellent quality, no download
  gTTS       Google voice (emergency fallback)         ~0 MB   internet
  mmsft      MMS Khmer fine-tuned (community voice)    ~600 MB  offline
             tighter pacing than stock MMS; this is also the slot where a
             voice YOU trained with the Colab kit runs (KHMER_MMSFT_MODEL)
  mms        Meta MMS-TTS Khmer, offline, robotic      ~600 MB  offline
  voxcpm     VoxCPM2, 48 kHz, can clone your voice     ~5 GB    offline
             the best free Khmer TTS available today (Apache-2.0),
             needs an NVIDIA GPU with ~8 GB VRAM

Usage:
    double-click install_khmer_tts.bat          (recommended)
    python install_khmer_tts.py                 light engines only
    python install_khmer_tts.py --offline       + MMS (works with no internet)
    python install_khmer_tts.py --voxcpm        + VoxCPM2 (GPU, ~5 GB)
    python install_khmer_tts.py --check         show what is installed
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import khmer_tts as KT
except Exception as e:                                  # pragma: no cover
    print("[FAIL] khmer_tts.py is missing next to this script:", e)
    sys.exit(1)


def run(py, args, label):
    print(f"\n--- {label} ---")
    print("   " + " ".join(str(a) for a in args))
    try:
        r = subprocess.run([py] + [str(a) for a in args])
        return r.returncode == 0
    except Exception as e:
        print(f"   [FAIL] {type(e).__name__}: {e}")
        return False


def gpu_report():
    """(has_gpu, vram_gb, note) — best effort, no crash if torch is absent."""
    try:
        import torch
    except Exception:
        return False, 0.0, "torch not installed in this python"
    try:
        if not torch.cuda.is_available():
            return False, 0.0, "no CUDA GPU visible to torch"
        name = torch.cuda.get_device_name(0)
        props = torch.cuda.get_device_properties(0)
        gb = props.total_memory / (1024 ** 3)
        return True, gb, f"{name}, {gb:.1f} GB VRAM"
    except Exception as e:
        return False, 0.0, f"{type(e).__name__}: {e}"


def _run_json(py, code, label):
    """Run a small python -c snippet that prints one JSON object."""
    try:
        r = subprocess.run([py, "-c", code], capture_output=True, text=True,
                           timeout=1800)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    if r.returncode != 0:
        return None, (r.stderr or r.stdout or "").strip()[-300:]
    for line in reversed(r.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line), ""
            except Exception:
                continue
    return None, "no json from helper"


def model_cache_state(py):
    """{model_id: True/False} — which offline voices are already downloaded."""
    here = str(Path(__file__).resolve().parent)
    code = (
        "import json,sys\n"
        "sys.path.insert(0, %r)\n"
        "out={}\n"
        "try:\n"
        "    import khmer_tts as KT\n"
        "    from huggingface_hub import try_to_load_from_cache as T\n"
        "    for mid in (KT.MMSFT_MODEL, KT.MMS_MODEL):\n"
        "        out[mid]=bool(T(mid,'model.safetensors'))\n"
        "except Exception:\n"
        "    pass\n"
        "print(json.dumps(out))\n" % here
    )
    data, err = _run_json(py, code, "cache check")
    return data or {}, err


def prefetch(py):
    """Download the offline Khmer voices now, so a later run works with NO
    internet. Non-fatal: a failure here only means the first offline run will
    download them instead."""
    here = str(Path(__file__).resolve().parent)
    code = (
        "import sys\n"
        "sys.path.insert(0, %r)\n"
        "import khmer_tts as KT\n"
        "for mid in (KT.MMSFT_MODEL, KT.MMS_MODEL):\n"
        "    print('   fetching', mid, flush=True)\n"
        "    KT._vits_model(mid)\n"
        "print('offline voices ready')\n" % here
    )
    print("\n--- downloading the two offline Khmer voices (~145 MB each, once) ---")
    try:
        r = subprocess.run([py, "-c", code], timeout=3600)
        return r.returncode == 0
    except Exception as e:
        print(f"   [WARN] {type(e).__name__}: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", default=sys.executable,
                    help="which python to install into (default: this one)")
    ap.add_argument("--offline", action="store_true",
                    help="also install the offline engine (transformers + torch)")
    ap.add_argument("--voxcpm", action="store_true",
                    help="also install VoxCPM2 (GPU, ~5 GB of weights)")
    ap.add_argument("--check", action="store_true", help="just show the status")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    py = a.python

    print("=" * 66)
    print("Khmer TTS engines — what this package can speak with")
    print("=" * 66)
    print(f"python: {py}")

    has_gpu, vram, note = gpu_report()
    print(f"GPU   : {note}")

    if a.check:
        print()
        for row in KT.status():
            print(f"  {'OK ' if row['installed'] else '-- '} {row['engine']:7s} "
                  f"{row['label']:44s} {row['licence'].split('—')[0].strip()}")
        print("\nfallback order:", " -> ".join(KT.AUTO_ORDER))
        state, err = model_cache_state(py)
        if state:
            print("\noffline voices (work with no internet):")
            for mid, have in state.items():
                print(f"  [{'downloaded' if have else 'not yet '}] {mid}")
        elif err:
            print(f"\n(offline voice check skipped: {err.splitlines()[-1][:90]})")
        if has_gpu and vram >= 7.5:
            print(f"\nThis machine has {vram:.1f} GB VRAM - VoxCPM2 (the best "
                  f"free Khmer voice) will run:  --voxcpm")
        elif has_gpu:
            print(f"\n{vram:.1f} GB VRAM is below VoxCPM2's ~8 GB - "
                  f"edge-tts stays the best option here.")
        return 0

    plan = [
        ("edge-tts", ["-m", "pip", "install", "edge-tts"],
         "Microsoft neural Khmer voices (primary)"),
        ("gTTS", ["-m", "pip", "install", "gTTS"],
         "Google voice (emergency fallback)"),
    ]
    if a.offline:
        plan.append(("transformers+torch",
                     ["-m", "pip", "install", "transformers", "torch"],
                     "the two offline Khmer voices (no internet needed)"))
    if a.voxcpm:
        if not (has_gpu and vram >= 7.5):
            print("\n[NOTE] VoxCPM2 wants ~8 GB VRAM; this machine reports "
                  f"{vram:.1f} GB. Installing anyway would be slow on CPU - "
                  "skipping it. Re-run with --voxcpm if you are sure.")
        else:
            plan.append(("voxcpm", ["-m", "pip", "install", "voxcpm"],
                         "VoxCPM2 — 48 kHz Khmer + voice cloning "
                         "(first use downloads ~5 GB of weights)"))

    print("\nplan:")
    for i, (name, args, why) in enumerate(plan, 1):
        have = KT.engine_ready({"edge-tts": "edge", "gTTS": "gtts",
                                "transformers+torch": "mms",
                                "voxcpm": "voxcpm"}.get(name, name))
        print(f"  {i}. {name:20s} {'already installed' if have else 'to install'}"
              f"   — {why}")
    if a.dry_run:
        print("\n[dry-run] nothing installed.")
        return 0

    ok_all = True
    for name, args, why in plan:
        if not run(py, args, f"installing {name} ({why})"):
            ok_all = False

    if a.offline and ok_all:
        if KT.engine_ready("mmsft") or KT.engine_ready("mms"):
            state, _ = model_cache_state(py)
            missing = [m for m, have in state.items() if not have]
            if missing or not state:
                prefetch(py)
            else:
                print("\nboth offline Khmer voices are already downloaded — "
                      "good, the package now speaks Khmer with no internet.")

    print("\n--- verifying ---")
    for row in KT.status():
        mark = "OK  " if row["installed"] else "MISS"
        print(f"  [{mark}] {row['engine']:7s} {row['label']}")
    usable = KT.available_engines()
    print("\nusable now:", " -> ".join(usable) if usable else "(none)")
    if usable:
        print("\nThe pipeline picks them automatically (tts_engine = \"auto\").")
        print("Test it:  python khmer_tts.py --say \"សួស្តី\" --out test.wav")
    if a.voxcpm and any(r["engine"] == "voxcpm" and r["installed"]
                        for r in KT.status()):
        print("\nVoxCPM2 tip: in Sonora, set the RVC carrier voice to a Khmer")
        print("voice as usual; to hear VoxCPM2 alone (or clone your own voice")
        print("from a reference wav), use:  python khmer_tts.py --engine voxcpm")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
