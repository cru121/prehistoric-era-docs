#!/usr/bin/env python3
"""
Prehistoric Era — mod backup snapshot.

Copies a *lean* snapshot of the live mod (Data/ Text/ Scripts/ + the .modinfo,
but NOT Icons/Art/UI — those are ~160 MB and irrelevant to diffs) into
`backup/vNN/`, where NN is read from the mod's PrehistoricEra.modinfo.

The archive's only job is to give the next mod update something to diff against
("what changed since vNN"), so it deliberately skips the heavy art assets.

    python generator/backup_mod.py                 # snapshot the live Steam mod
    python generator/backup_mod.py --mod "C:/path/to/mod"

Source resolution mirrors generate.py: --mod arg, then PR_MOD_DIR env var, then
the live Steam Workshop copy. (There is no backup->backup fallback here.)
"""

from __future__ import annotations

import os
import re
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_ROOT = os.path.join(SCRIPT_DIR, "..", "backup")

# Same live-mod location as generate.py (see its header for the id meanings).
STEAM_WORKSHOP_MOD = os.path.join(
    r"C:\Program Files (x86)\Steam\steamapps\workshop\content",
    "289070", "3739196160",
)

# What travels into the archive. Everything else (Icons/ Art/ UI/ Config/,
# stray files like lala.zip) is left behind on purpose.
KEEP_DIRS = ["Data", "Text", "Scripts"]
KEEP_FILES = ["PrehistoricEra.modinfo"]


def resolve_source():
    """The live mod to snapshot: --mod arg, then PR_MOD_DIR, then Steam Workshop."""
    src = None
    for i, a in enumerate(sys.argv):
        if a == "--mod" and i + 1 < len(sys.argv):
            src = sys.argv[i + 1]
        elif a.startswith("--mod="):
            src = a.split("=", 1)[1]
    if src is None:
        src = os.environ.get("PR_MOD_DIR")
    if src is None and os.path.isdir(os.path.join(STEAM_WORKSHOP_MOD, "Data")):
        src = STEAM_WORKSHOP_MOD
    return os.path.abspath(src) if src else None


def read_version(src):
    """Read version="NN" from the mod's .modinfo, or None."""
    try:
        txt = open(os.path.join(src, "PrehistoricEra.modinfo"),
                   encoding="utf-8-sig").read()
    except OSError:
        return None
    m = re.search(r'version="(\d+)"', txt)
    return m.group(1) if m else None


def main():
    src = resolve_source()
    if not src or not os.path.isdir(os.path.join(src, "Data")):
        sys.exit(
            "ERROR: could not find the live mod's Data/ folder.\n"
            f"  looked at: {src or STEAM_WORKSHOP_MOD}\n"
            'Pass one explicitly:  python generator/backup_mod.py --mod "C:/path/to/mod"'
        )

    ver = read_version(src)
    if not ver:
        sys.exit(f"ERROR: could not read version= from {src}\\PrehistoricEra.modinfo")

    dest = os.path.abspath(os.path.join(BACKUP_ROOT, f"v{ver}"))
    print(f"Prehistoric Era — backup snapshot")
    print(f"  source : {src}")
    print(f"  dest   : {dest}")

    if os.path.isdir(dest):
        shutil.rmtree(dest)  # overwrite idempotently
    os.makedirs(dest, exist_ok=True)

    for d in KEEP_DIRS:
        s = os.path.join(src, d)
        if os.path.isdir(s):
            shutil.copytree(s, os.path.join(dest, d))
            print(f"  copied {d}/")
    for f in KEEP_FILES:
        s = os.path.join(src, f)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(dest, f))
            print(f"  copied {f}")

    # Report the archive footprint.
    total = sum(
        os.path.getsize(os.path.join(r, fn))
        for r, _, fns in os.walk(dest) for fn in fns
    )
    print(f"Done -> {dest}  ({total / 1_048_576:.1f} MB)")

    others = sorted(
        d for d in os.listdir(BACKUP_ROOT)
        if re.match(r"^v\d+$", d) and d != f"v{ver}"
    ) if os.path.isdir(BACKUP_ROOT) else []
    if others:
        print(f"  (other archives kept: {', '.join(others)})")


if __name__ == "__main__":
    main()
