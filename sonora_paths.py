#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""sonora_paths.py — resolve the MODEL (.pth) and INDEX (.index) fields.

WHY THIS EXISTS
    A user can reasonably type ANY of these into Sonora's MODEL field:

        assets/weights/Sonaro-kh.pth            correct, relative
        assets\\weights\\Sonaro-kh.pth           same, backslashes
        Sonaro-kh.pth                           bare file name
        Sonaro-kh                               name without extension
        D:\\RVC\\assets\\weights\\Sonaro-kh.pth   absolute
        assets/weights                          THE FOLDER
        D:\\RVC\\assets\\weights                  the folder, absolute
        weights                                 the folder, bare

    RVC's own loader only understands a file inside its weights root. Handing
    it a folder makes it concatenate paths and fail with nonsense like
    "[Errno 22] Invalid argument: 'D:/RVC/assets/D:/RVC/assets/weights'" and
    "(PermissionError)" — which tells the user nothing.

    So: every path coming from a field or a config goes through here first.
    Folders are resolved to the actual file inside them, bare names are looked
    up in the usual places, and when we had to interpret the value we say so
    out loud (returned `note`), never silently.

    Pure stdlib. Used by sonora/rvc_worker.py, sonora/server.py and
    pipeline/rvc_engine.py — keep the copies identical.
"""
import os
import re

KEEP = (".pth", ".pt", ".ckpt")


def _clean(p):
    """Strip quotes/whitespace, fix mixed separators, un-glue a doubled path."""
    if not p:
        return ""
    s = str(p).strip().strip('"').strip("'").strip()
    if not s:
        return ""
    # someone pasted "assets/D:\\RVC\\assets\\weights" (our own old bug, or a
    # copy-paste of two paths): keep the last real absolute path in the string
    hits = [m.start() for m in re.finditer(r"[A-Za-z]:[\\/]", s)]
    if len(hits) > 1:
        s = s[hits[-1]:]
    elif len(hits) == 1 and hits[0] > 0:
        s = s[hits[0]:]
    # (a POSIX-doubled value is handled by adding suffix candidates below —
    #  never by guessing here, that used to swallow "assets/weights/x.pth")
    s = s.replace("\\", os.sep).replace("/", os.sep)
    return os.path.normpath(s)


def _is_abs(s):
    return bool(s) and (os.path.isabs(s) or re.match(r"^[A-Za-z]:[\\/]", s) is not None)


def _files_in(folder, exts):
    try:
        return sorted(f for f in os.listdir(folder)
                      if f.lower().endswith(exts)
                      and os.path.isfile(os.path.join(folder, f)))
    except Exception:
        return []


def _best_in_folder(folder, exts, prefer=()):
    """Pick the file a user almost certainly meant inside `folder`."""
    files = _files_in(folder, exts)
    if not files:
        return ""
    low = {f.lower(): f for f in files}
    for want in prefer:
        if not want:
            continue
        w = os.path.basename(str(want)).lower()
        if w in low:
            return low[w]
        stem = os.path.splitext(w)[0]
        for f in files:                       # partial match on the stem
            if stem and stem in f.lower():
                return f
    if len(files) == 1:
        return files[0]
    try:                                      # newest wins
        return max(files, key=lambda f: os.path.getmtime(os.path.join(folder, f)))
    except Exception:
        return files[0]


def resolve_field(base_dir, value, kind="model", prefer=()):
    """Resolve a MODEL / INDEX field value.

    Returns (abs_path, note). abs_path is "" when nothing usable was found.
    `note` is a plain sentence describing any interpretation we had to make
    ("" when the value was already a clean, existing file).
    """
    exts = KEEP if kind == "model" else (".index",)
    raw = _clean(value)
    if not raw:
        return "", ""
    base = os.path.abspath(base_dir) if base_dir else ""

    # 1) exact hits, in the order a user would expect
    cands = []
    if _is_abs(raw):
        cands.append(raw)
    else:
        cands.append(os.path.join(base, raw) if base else raw)
        for sub in (("assets", "weights"), ("weights",), ("assets", "indices"),
                    ("indices",), ("logs",), ()):
            if base:
                cands.append(os.path.join(base, *sub, raw))
        cands.append(raw)                     # cwd-relative, last resort

    # any separator inside a glued value may be the start of the real path
    for i, ch in enumerate(raw):
        if i > 0 and ch == os.sep:
            cands.append(raw[i:])

    for c in cands:
        try:
            if os.path.isfile(c) and c.lower().endswith(exts):
                return os.path.abspath(c), ""
            if os.path.isfile(c):
                # a file with an unexpected extension — still the best answer
                return os.path.abspath(c), ("the %s field has no %s extension — "
                                            "using it as-is"
                                            % (kind, "/".join(exts)))
        except Exception:
            continue

    # 1b) the name without its extension ("Sonaro-kh" / "added_IVF248"): sweep
    for c in list(cands):
        for ext in exts:
            try:
                if os.path.isfile(c + ext):
                    return os.path.abspath(c + ext), (
                        "the %s field had no extension — using %s"
                        % (kind, os.path.basename(c) + ext))
            except Exception:
                continue
    # 1c) a partial name ("Sonaro" / "added_IVF"): the unique file that contains it
    for root in ([os.path.join(base, "assets", "weights"), os.path.join(base, "weights")]
                 if kind == "model" else
                 [os.path.join(base, "assets", "indices"), os.path.join(base, "logs")]):
        if not root or not os.path.isdir(root):
            continue
        hits = []
        for dp, dn, fn in os.walk(root):
            for f in fn:
                if f.lower().endswith(exts) and raw.lower() in f.lower():
                    hits.append(os.path.join(dp, f))
        if len(hits) == 1:
            return os.path.abspath(hits[0]), (
                "matched %s to %s" % (raw, os.path.relpath(hits[0], base)))
        if len(hits) > 1:
            hits.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
            return os.path.abspath(hits[-1]), (
                "%s matches %d files — using the newest, %s"
                % (raw, len(hits), os.path.basename(hits[-1])))

    # 2) the value names a FOLDER: pick the file inside it
    aliases = {"weights": (("assets", "weights"), ("weights",)),
               "assets/weights": (("assets", "weights"),),
               "assets\\weights": (("assets", "weights"),),
               "indices": (("assets", "indices"), ("indices",)),
               "assets/indices": (("assets", "indices"),)}
    key = raw.replace(os.sep, "/").strip("/").lower()
    if base and key in aliases:
        for parts in aliases[key]:
            cands.insert(0, os.path.join(base, *parts))
    for c in cands:
        try:
            if os.path.isdir(c):
                pick = _best_in_folder(c, exts, prefer)
                rel = os.path.relpath(c, base).replace(os.sep, "/") if base else c
                if pick:
                    return os.path.abspath(os.path.join(c, pick)), (
                        "the %s field pointed at the folder %s — I used %s inside it"
                        % (kind, rel, pick))
                have = _files_in(c, (".pth", ".pt", ".ckpt", ".index"))
                return "", ("the %s field is the folder %s, and it holds no %s file%s"
                            % (kind, rel, "/".join(exts),
                               (" (it has: " + ", ".join(have[:6]) + ")") if have else ""))
        except Exception:
            continue

    # 3) give the user the list of what actually exists
    near = []
    for sub in (("assets", "weights"), ("weights",), ("assets", "indices"),
                ("indices",)):
        d = os.path.join(base, *sub) if base else ""
        if d and os.path.isdir(d):
            for f in _files_in(d, exts):
                near.append(sub[-1] + "/" + f)
        if len(near) >= 8:
            break
    extra = (" — available: " + ", ".join(near[:8])) if near else ""
    if kind == "index":
        extra += ("  (tip: leave the INDEX field blank and Sonora picks the "
                  "best match automatically)")
    return "", ("%s file not found: %s%s" % (kind, raw, extra))


def resolve_model_field(base_dir, value, prefer=()):
    return resolve_field(base_dir, value, "model", prefer)


def resolve_index_field(base_dir, value, prefer=()):
    return resolve_field(base_dir, value, "index", prefer)
