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
    icons: dict[str, str] = {}
    for path in glob.glob(os.path.join(icons_dir, "**", "*.png"), recursive=True):
        name = os.path.splitext(os.path.basename(path))[0]
        icons[name] = path
    return icons


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
