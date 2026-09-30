#!/usr/bin/env python3
"""find_rvc_python.py -- locate the python interpreter that runs RVC-WebUI.

Why this exists
---------------
RVC installations hide their interpreter in many different places:

    <rvc>\\venv\\Scripts\\python.exe        classic venv
    <rvc>\\.venv\\Scripts\\python.exe       newer venv
    <rvc>\\env\\Scripts\\python.exe         conda-ish env
    <rvc>\\python\\python.exe              official "embeddable" python
    <rvc>\\runtime\\python.exe             integrated one-click packs
    <rvc>\\py311\\python.exe               packs shipping their own build
    <rvc>\\system\\python.exe
    <rvc>\\python.exe                      portable layout

The first version of the Clean & Clear installer only looked at the RVC
folder ROOT and the venv paths -- so on an integrated pack (RVC20260718Nvidia
style) it found only the pythons installed system-wide, none of which has
torch, and it gave up with "none of those pythons has torch".

This module also WALKS the RVC folder, and READS the launcher .bat/.cmd/.ps1
files, which name the interpreter directly. Nothing is installed, started or
modified here -- it only looks.

Used by: install_clean_engine.py, the batch pipeline (common.py), and
Sonora (server.py), so all three always agree on the same interpreter.

CLI
---
    python find_rvc_python.py                 list candidates + best pick
    python find_rvc_python.py --root "E:\\..."  scan a specific RVC folder
    python find_rvc_python.py --json          machine-readable output
"""
import argparse
import json
import os
import re
import subprocess
import sys

# folders that never contain the RVC interpreter (and can be huge)
SKIP_DIRS = {
    "logs", "log", "output", "outputs", "out", "temp", "tmp", "cache",
    "__pycache__", ".git", ".cache", ".idea", ".vs", "node_modules",
    "models", "model", "weights", "assets", "indices", "audio", "audios",
    "dataset", "datasets", "data", "input", "inputs", "results", "sample",
    "samples", "recordings", "record", "backup", "backups", "docs",
    "site-packages", "dist-packages", "tcl", "idlelib", "test", "tests",
}
MAX_DEPTH = 4            # how deep under the RVC root we walk
MAX_WALK_HITS = 60       # hard cap on python files collected by walking
TORCH_TIMEOUT = 90       # torch can be slow to import the first time

_TORCH_CACHE = {}        # path(lower) -> True/False
_SCAN_CACHE = {}         # root(lower) -> [paths]


def _is_python_name(name):
    n = name.lower()
    if n in ("python", "python3", "pythonw"):
        return True
    return bool(re.fullmatch(r"python(w)?3?(\d+(\.\d+)?)?\.exe", n))


def has_torch(python, timeout=TORCH_TIMEOUT):
    """True when this interpreter can `import torch`. Cached per path."""
    key = str(python).lower()
    if key in _TORCH_CACHE:
        return _TORCH_CACHE[key]
    ok = False
    try:
        r = subprocess.run([python, "-c", "import torch"], capture_output=True,
                           timeout=timeout)
        ok = r.returncode == 0
    except Exception:
        ok = False
    _TORCH_CACHE[key] = ok
    return ok


def torch_version(python, timeout=TORCH_TIMEOUT):
    try:
        r = subprocess.run(
            [python, "-c", "import torch;print(torch.__version__)"],
            capture_output=True, timeout=timeout)
        if r.returncode == 0:
            return (r.stdout or b"").decode("utf-8", "ignore").strip()
    except Exception:
        pass
    return ""


def _walk_pythons(root, limit=MAX_WALK_HITS):
    """Every python interpreter-looking file under root, shallow first."""
    found, seen = [], set()

    def add(p):
        k = str(p).lower()
        if k not in seen and len(found) < limit:
            seen.add(k)
            found.append(str(p))

    root = os.path.abspath(root)
    # 1) the well-known layouts first (most likely, and cheap to check)
    for rel in ("venv/Scripts/python.exe", "venv/bin/python",
                ".venv/Scripts/python.exe", ".venv/bin/python",
                "env/Scripts/python.exe", "env/bin/python",
                "python/python.exe", "python_embedded/python.exe",
                "runtime/python.exe", "system/python.exe",
                "python.exe", "python3.exe"):
        p = os.path.join(root, rel.replace("/", os.sep))
        if os.path.isfile(p):
            add(p)
    # 2) then anything else that looks like an interpreter, bounded
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dp, dn, fn in os.walk(root):
        depth = dp.rstrip(os.sep).count(os.sep) - base_depth
        dn[:] = [d for d in dn if d.lower() not in SKIP_DIRS]
        if depth >= MAX_DEPTH:
            dn[:] = []
        for f in fn:
            if _is_python_name(f):
                full = os.path.join(dp, f)
                if os.path.isfile(full):
                    add(full)
    return found


def _from_launchers(root, limit=16):
    """Read .bat/.cmd/.ps1/.sh launchers -- they name the interpreter."""
    out, seen = [], set()
    root = os.path.abspath(root)
    pats = (".bat", ".cmd", ".ps1", ".sh")
    base_depth = root.rstrip(os.sep).count(os.sep)
    try:
        files = [f for f in sorted(os.listdir(root))
                 if f.lower().endswith(pats)]
    except OSError:
        files = []
    # also one level down (some packs keep the launcher in a subfolder)
    try:
        for d in sorted(os.listdir(root)):
            sub = os.path.join(root, d)
            if os.path.isdir(sub) and d.lower() not in SKIP_DIRS:
                if sub.rstrip(os.sep).count(os.sep) - base_depth >= 2:
                    continue
                files += [os.path.join(d, f) for f in sorted(os.listdir(sub))
                          if f.lower().endswith(pats)]
    except OSError:
        pass
    for name in files[:40]:
        path = name if os.path.isabs(name) else os.path.join(root, name)
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                txt = fh.read()
        except OSError:
            continue
        for m in re.finditer(r'([^\s"\'=;,()]*python(?:w)?[0-9.]*\.exe)',
                             txt, re.I):
            tok = m.group(1).strip()
            cands = []
            if re.match(r"^[A-Za-z]:[\\/]", tok):
                cands.append(tok)
            else:
                tok2 = tok.lstrip(".\\/")
                cands.append(os.path.join(root, tok2.replace("/", os.sep)))
                cands.append(os.path.join(os.path.dirname(path),
                                          tok2.replace("/", os.sep)))
            for c in cands:
                k = str(c).lower()
                if k not in seen and os.path.isfile(c):
                    seen.add(k)
                    out.append(os.path.abspath(c))
                    if len(out) >= limit:
                        return out
    return out


def installed_pythons(limit=10):
    """Pythons registered with the Windows `py` launcher (best effort)."""
    out = []
    try:
        r = subprocess.run(["py", "-0p"], capture_output=True, timeout=10)
        txt = (r.stdout or b"").decode("utf-8", "ignore")
        for m in re.finditer(r'([A-Za-z]:\\[^\r\n]*?python(?:w)?\.exe)', txt):
            p = m.group(1).strip().strip('"')
            if os.path.isfile(p) and p.lower() not in [q.lower() for q in out]:
                out.append(p)
    except Exception:
        pass
    return out[:limit]


def candidates(rvc_root="", explicit="", include_self=True):
    """Ordered candidate interpreters, most-likely first. No deduping loss.

    rvc_root  - the RVC installation folder (config rvc_root)
    explicit  - config rvc_python / the "RVC PYTHON" field, checked first
    """
    out, seen = [], set()

    def add(p):
        if not p:
            return
        p = str(p).strip().strip('"')
        if not p:
            return
        k = p.lower()
        if k in seen:
            return
        if os.path.isabs(p):
            if not os.path.isfile(p):
                return
        seen.add(k)
        out.append(p)

    add(explicit)
    root = (rvc_root or "").strip().strip('"')
    if root and os.path.isdir(root):
        key = os.path.abspath(root).lower()
        if key not in _SCAN_CACHE:
            _SCAN_CACHE[key] = _from_launchers(root) + _walk_pythons(root)
        for p in _SCAN_CACHE[key]:
            add(p)
    for p in installed_pythons():
        add(p)
    if include_self:
        add(sys.executable)
    return out


def find(rvc_root="", explicit="", include_self=True, log=print):
    """Return (python, [(path, has_torch), ...]). python is None if no torch."""
    cands = candidates(rvc_root, explicit, include_self)
    results = []
    for p in cands:
        results.append((p, has_torch(p)))
    best = next((p for p, ok in results if ok), None)
    return best, results


def main():
    ap = argparse.ArgumentParser(description="find the RVC python (the one "
                                             "that has torch)")
    ap.add_argument("--root", default="", help="RVC installation folder")
    ap.add_argument("--python", default="", help="candidate to check first")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    root = a.root
    if not root:
        # try the config next to this script / one folder up
        for probe in (os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "config.json"),):
            try:
                with open(probe, "r", encoding="utf-8") as fh:
                    root = (json.load(fh).get("rvc_root") or "").strip()
                if root:
                    break
            except Exception:
                pass

    best, results = find(root, a.python)
    if a.json:
        print(json.dumps({"best": best,
                          "candidates": [{"path": p, "torch": ok}
                                         for p, ok in results]}, indent=2))
        return 0 if best else 1

    note = ""
    if root and not os.path.isdir(root):
        note = "   <-- not found on this PC, check the path"
    print("RVC folder :", (root or "(not set in config.json)") + note)
    print("candidates : %d" % len(results))
    for p, ok in results:
        print(f"  - {p}   [{'torch OK' if ok else 'no torch'}]")
    if best:
        tv = torch_version(best)
        print("\nUSE THIS PYTHON:\n  " + best + (f"   (torch {tv})" if tv else ""))
        return 0
    print("\n[FAIL] no python with torch found.")
    print("Send this list if you need help -- it shows what was looked at.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
