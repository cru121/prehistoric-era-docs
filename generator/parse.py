"""
Data extraction for the Prehistoric Era documentation generator.

Parses the mod's own source of truth with no external dependencies:
  * Data/*.sql   -> every `INSERT INTO <Table> (cols) VALUES (...)` row
  * Text/*.xml   -> LOC_* -> English (en_US) string table
  * Icons/src/*  -> ICON_<TYPE> -> png path

The SQL is not executed; we extract INSERT rows with a small tokenizer that is
aware of `--` line comments (including the mod's Korean comments) and single
quoted string literals with `''` escaping. This keeps the generator robust even
without the base game's table schema.
"""

from __future__ import annotations

import os
import re
import glob
import struct
import zlib
import xml.etree.ElementTree as ET
from collections import defaultdict


# --------------------------------------------------------------------------
# SQL parsing
# --------------------------------------------------------------------------

def strip_sql_comments(sql: str) -> str:
    """Remove `-- ...` line comments and `/* */` blocks, respecting string
    literals so an apostrophe inside a comment or a `--` inside a string does
    not confuse us."""
    out = []
    i, n = 0, len(sql)
    in_str = False
    while i < n:
        c = sql[i]
        if in_str:
            out.append(c)
            if c == "'":
                # doubled '' is an escaped quote, stays in the string
                if i + 1 < n and sql[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        # not in a string
        if c == "'":
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            # line comment -> skip to end of line
            j = sql.find("\n", i)
            if j == -1:
                break
            i = j
            continue
        if c == "/" and i + 1 < n and sql[i + 1] == "*":
            j = sql.find("*/", i + 2)
            i = (j + 2) if j != -1 else n
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _split_top_level(s: str, sep: str = ",") -> list[str]:
    """Split on `sep` at paren-depth 0, ignoring separators inside strings."""
    parts, buf = [], []
    depth = 0
    in_str = False
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if in_str:
            buf.append(c)
            if c == "'":
                if i + 1 < n and s[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if c == "'":
            in_str = True
            buf.append(c)
        elif c == "(":
            depth += 1
            buf.append(c)
        elif c == ")":
            depth -= 1
            buf.append(c)
        elif c == sep and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    if buf:
        parts.append("".join(buf))
    return parts


def _parse_value(tok: str):
    tok = tok.strip()
    if tok == "" :
        return None
    if tok.upper() == "NULL":
        return None
    if tok[0] == "'" and tok[-1] == "'":
        return tok[1:-1].replace("''", "'")
    # bareword / number / true / false
    return tok


def _split_tuples(values_blob: str) -> list[str]:
    """Given the text after VALUES, return each top-level `( ... )` group."""
    tuples = []
    depth = 0
    in_str = False
    start = None
    i, n = 0, len(values_blob)
    while i < n:
        c = values_blob[i]
        if in_str:
            if c == "'":
                if i + 1 < n and values_blob[i + 1] == "'":
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if c == "'":
            in_str = True
        elif c == "(":
            if depth == 0:
                start = i + 1
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0 and start is not None:
                tuples.append(values_blob[start:i])
                start = None
        i += 1
    return tuples


_INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*?)\)\s*VALUES\s*(.*?);",
    re.IGNORECASE | re.DOTALL,
)


def parse_sql_file(path: str, tables: dict[str, list[dict]]):
    with open(path, "r", encoding="utf-8-sig") as fh:
        raw = fh.read()
    clean = strip_sql_comments(raw)
    for m in _INSERT_RE.finditer(clean):
        table = m.group(1)
        cols = [c.strip() for c in _split_top_level(m.group(2))]
        for tup in _split_tuples(m.group(3)):
            vals = [_parse_value(v) for v in _split_top_level(tup)]
            if len(vals) != len(cols):
                # tolerate mismatch rather than crash the whole build
                continue
            tables[table].append(dict(zip(cols, vals)))


def load_sql(data_dir: str) -> dict[str, list[dict]]:
    tables: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(glob.glob(os.path.join(data_dir, "*.sql"))):
        try:
            parse_sql_file(path, tables)
        except Exception as exc:  # noqa: BLE001 - keep going, report at end
            print(f"  ! failed to parse {os.path.basename(path)}: {exc}")
    return tables


_UPDATE_RE = re.compile(
    r"UPDATE\s+([A-Za-z_][A-Za-z0-9_]*)\s+SET\s+(.*?)\s+WHERE\s+(.*?);",
    re.IGNORECASE | re.DOTALL,
)


def parse_updates_file(path: str, out: list[dict]):
    """Extract `UPDATE <table> SET a=x, b=y WHERE c='z'` statements as
    {table, set:{col:val}, where:{col:val}}. Used to catch base-game rows the
    mod re-gates (e.g. the Settler's PrereqTech), which are edits, not inserts."""
    with open(path, "r", encoding="utf-8-sig") as fh:
        clean = strip_sql_comments(fh.read())
    for m in _UPDATE_RE.finditer(clean):
        table = m.group(1)
        set_d = {}
        for assign in _split_top_level(m.group(2)):
            if "=" in assign:
                k, v = assign.split("=", 1)
                set_d[k.strip()] = _parse_value(v)
        where_d = {}
        for cond in re.split(r"\s+AND\s+", m.group(3), flags=re.IGNORECASE):
            in_m = re.match(r"\s*([A-Za-z_][\w]*)\s+IN\s*\((.*)\)\s*$", cond, re.IGNORECASE | re.DOTALL)
            if in_m:
                vals = [_parse_value(v) for v in _split_top_level(in_m.group(2))]
                where_d[in_m.group(1).strip()] = vals
            elif "=" in cond:
                k, v = cond.split("=", 1)
                where_d[k.strip()] = _parse_value(v)
        out.append({"table": table, "set": set_d, "where": where_d})


def load_updates(paths: list[str]) -> list[dict]:
    out: list[dict] = []
    for path in paths:
        parse_updates_file(path, out)
    return out


def load_sql_files(paths: list[str]) -> dict[str, list[dict]]:
    """Parse only the given files. Used for the tech/civics trees, whose
    canonical prerequisite edges live in Technologies.sql / Civics.sql — the
    compatibility and Nomadic-Start variants re-wire the tree and must not be
    merged into the standard-game layout."""
    tables: dict[str, list[dict]] = defaultdict(list)
    for path in paths:
        parse_sql_file(path, tables)
    return tables


# --------------------------------------------------------------------------
# Localized text
# --------------------------------------------------------------------------

def load_text(text_dir: str, language: str = "en_US") -> dict[str, str]:
    loc: dict[str, str] = {}
    for path in sorted(glob.glob(os.path.join(text_dir, "*.xml"))):
        try:
            tree = ET.parse(path)
        except ET.ParseError as exc:
            print(f"  ! failed to parse {os.path.basename(path)}: {exc}")
            continue
        for node in tree.iter():
            tag = node.tag
            if tag not in ("Replace", "Row", "Update"):
                continue
            if node.get("Language") != language:
                continue
            key = node.get("Tag")
            text = node.get("Text")
            if text is None:
                # <Row><Tag>..</Tag><Text>..</Text></Row> form
                text = node.findtext("Text")
                key = key or node.findtext("Tag")
            if key and text is not None:
                loc[key] = text
    return loc


# --------------------------------------------------------------------------
# Icons
# --------------------------------------------------------------------------

def load_icons(icons_dir: str) -> dict[str, str]:
    """Legacy: loose PNG files keyed by basename (for mods that ship per-icon PNGs).
    Superseded by plan_icons(), which also un-packs the DDS texture atlases the mod
    switched to at ~v25. Kept for reference / backward compatibility."""
    icons: dict[str, str] = {}
    for path in glob.glob(os.path.join(icons_dir, "**", "*.png"), recursive=True):
        name = os.path.splitext(os.path.basename(path))[0]
        icons[name] = path
    return icons


# --- DDS decoding + PNG writing (uncompressed 32bpp only; stdlib only) --------
# The mod's atlases and loose icons are uncompressed A8R8G8B8 (.dds). Compressed
# (FourCC / DXT / DX10) files are skipped — the mod ships exactly one (PR_SNOW),
# which the docs don't use.

def _mask_shift(mask: int) -> int:
    shift = 0
    while mask and not (mask >> shift) & 1:
        shift += 1
    return shift


def read_dds_rgba(path: str):
    """Decode an uncompressed 32bpp DDS to (w, h, rgba_bytes). Return None for
    compressed or non-32bpp files. Channel order is taken from the header masks,
    so it works whether the file is BGRA (the usual Civ layout) or RGBA."""
    with open(path, "rb") as fh:
        blob = fh.read()
    if blob[:4] != b"DDS " or len(blob) < 128:
        return None
    h, w = struct.unpack("<II", blob[12:20])
    pf_flags = struct.unpack("<I", blob[80:84])[0]
    if pf_flags & 0x4:                       # DDPF_FOURCC -> compressed
        return None
    bitcount = struct.unpack("<I", blob[88:92])[0]
    if bitcount != 32:
        return None
    rmask, gmask, bmask, amask = struct.unpack("<IIII", blob[92:108])
    px = blob[128:128 + w * h * 4]
    if len(px) < w * h * 4:
        return None
    rs, gs, bs, as_ = (_mask_shift(rmask), _mask_shift(gmask),
                       _mask_shift(bmask), _mask_shift(amask))
    out = bytearray(w * h * 4)
    for i in range(w * h):
        v = int.from_bytes(px[i * 4:i * 4 + 4], "little")
        out[i * 4]     = (v & rmask) >> rs
        out[i * 4 + 1] = (v & gmask) >> gs
        out[i * 4 + 2] = (v & bmask) >> bs
        out[i * 4 + 3] = ((v & amask) >> as_) if amask else 255
    return w, h, bytes(out)


def write_png(path: str, w: int, h: int, rgba: bytes, crop=None) -> None:
    """Write RGBA bytes to a PNG (zlib only). crop=(x, y, size) writes just that
    square cell out of a larger source image (used to lift a cell from an atlas)."""
    if crop:
        x, y, s = crop
        raw = b"".join(b"\x00" + rgba[((y + j) * w + x) * 4:((y + j) * w + x + s) * 4]
                       for j in range(s))
        ow = oh = s
    else:
        raw = b"".join(b"\x00" + rgba[j * w * 4:(j + 1) * w * 4] for j in range(h))
        ow, oh = w, h

    def chunk(typ, data):
        body = typ + data
        return struct.pack(">I", len(data)) + body + \
            struct.pack(">I", zlib.crc32(body) & 0xffffffff)

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", struct.pack(">IIBBBBB", ow, oh, 8, 6, 0, 0, 0)))
        fh.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        fh.write(chunk(b"IEND", b""))


def _pick_atlas_size(rows, want=64):
    """Pick the smallest atlas size >= want (crisp at the site's 52px), else the
    largest available — keeps output PNGs small without decoding the 256px sheets."""
    rows = sorted(rows, key=lambda r: r["size"])
    for r in rows:
        if r["size"] >= want:
            return r
    return rows[-1]


def plan_icons(icons_dir: str) -> dict:
    """Return {icon_key: job} describing how to produce every icon PNG. A job is:
        ("atlas", dds_path, x, y, size)   -- one grid cell of a texture atlas
        ("loose", src_path, 0, 0, None)   -- a whole single-icon .dds/.png file

    Reads the mod's Icons/*.xml (IconTextureAtlases + IconDefinitions), and any
    loose per-icon files. Base-game atlases (whose .dds is not shipped in the mod)
    and fogged "_FOW" variants are skipped."""
    jobs: dict = {}
    atlas_files: set = set()
    atlases: dict = defaultdict(list)        # atlas name -> [{size, per_row, path}]
    defs: list = []                          # (icon_name, atlas_name, index)

    for xp in glob.glob(os.path.join(icons_dir, "**", "*.xml"), recursive=True):
        try:
            root = ET.parse(xp).getroot()
        except ET.ParseError:
            continue
        for row in root.iter("Row"):
            a = row.attrib
            name = a.get("Name", "")
            if "IconsPerRow" in a and name.startswith("ICON_ATLAS"):
                fn = a.get("Filename", "")
                atlas_files.add(os.path.normcase(fn))
                path = os.path.join(icons_dir, fn)
                if os.path.exists(path):
                    atlases[name].append({"size": int(a["IconSize"]),
                                          "per_row": int(a["IconsPerRow"]),
                                          "path": path})
            elif name.startswith("ICON_") and "Atlas" in a and "Index" in a:
                defs.append((name, a["Atlas"], int(a["Index"])))

    for name, atlas, index in defs:
        rows = atlases.get(atlas)
        if not rows or "_FOW" in atlas:      # base-game atlas or fogged variant
            continue
        row = _pick_atlas_size(rows)
        size = row["size"]
        col, r = index % row["per_row"], index // row["per_row"]
        jobs[name] = ("atlas", row["path"], col * size, r * size, size)

    # Loose per-icon files (not atlas sheets): converted whole.
    loose = (glob.glob(os.path.join(icons_dir, "**", "*.dds"), recursive=True) +
             glob.glob(os.path.join(icons_dir, "**", "*.png"), recursive=True))
    for path in loose:
        fn = os.path.basename(path)
        if os.path.normcase(fn) in atlas_files:
            continue
        jobs.setdefault(os.path.splitext(fn)[0], ("loose", path, 0, 0, None))
    return jobs


if __name__ == "__main__":
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    tables = load_sql(os.path.join(root, "Data"))
    loc = load_text(os.path.join(root, "Text"))
    icons = load_icons(os.path.join(root, "Icons"))
    print(f"tables parsed: {len(tables)}")
    for t in sorted(tables):
        print(f"  {t:32} {len(tables[t])} rows")
    print(f"loc keys: {len(loc)}")
    print(f"icons: {len(icons)}")
