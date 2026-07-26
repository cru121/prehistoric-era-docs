#!/usr/bin/env python3
"""
Prehistoric Era — documentation site generator.

Reads the mod's own source of truth (Data/*.sql, Text/*.xml, Icons/) and emits a
self-contained static website under `web/`. No Claude, no internet, no
dependencies beyond the Python standard library.

    python tools/docgen/generate.py

Re-run it whenever the mod changes; the site regenerates from scratch.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse  # noqa: E402

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _resolve_mod_dir():
    """The mod's source files (read-only input). Priority: --mod arg, then
    PR_MOD_DIR env var, then a PrehistoricEra folder next to this repo."""
    for i, a in enumerate(sys.argv):
        if a == "--mod" and i + 1 < len(sys.argv):
            return os.path.abspath(sys.argv[i + 1])
        if a.startswith("--mod="):
            return os.path.abspath(a.split("=", 1)[1])
    if os.environ.get("PR_MOD_DIR"):
        return os.path.abspath(os.environ["PR_MOD_DIR"])
    return os.path.abspath(os.path.join(SCRIPT_DIR, "..", "PrehistoricEra"))


ROOT = _resolve_mod_dir()                 # mod source (input) — NOT part of this repo
OUT = os.path.join(SCRIPT_DIR, "docs")    # generated site (committed; served by GitHub Pages)
NOINDEX = True                            # True = ask search engines not to index (quiet link-sharing).
                                          # Flip to False when you want the site publicly discoverable.
MOD_AUTHOR = "AKXTM"
MOD_URL = "https://steamcommunity.com/workshop/filedetails/?id=3739196160"


def _read_mod_version():
    try:
        txt = open(os.path.join(ROOT, "PrehistoricEra.modinfo"), encoding="utf-8-sig").read()
        m = re.search(r'<Mod\b[^>]*\bversion="([^"]+)"', txt)
        if m:
            return m.group(1)
    except OSError:
        pass
    return "?"


MOD_VERSION = _read_mod_version()

# --------------------------------------------------------------------------
# Text markup  ->  HTML
# --------------------------------------------------------------------------

# Game yield/stat icons -> (emoji, human label). Rendered as a titled chip.
ICON_MAP = {
    "Food": ("🌾", "Food"),
    "Production": ("🔨", "Production"),
    "Gold": ("💰", "Gold"),
    "Science": ("🧪", "Science"),
    "Culture": ("🎭", "Culture"),
    "Faith": ("✨", "Faith"),
    "Housing": ("🏠", "Housing"),
    "Amenities": ("😊", "Amenities"),
    "Amenity": ("😊", "Amenity"),
    "GreatWork": ("🖼️", "Great Work"),
    "GreatWork_Artifact": ("🏺", "Artifact"),
    "GreatWorkArtifact": ("🏺", "Artifact"),
    "TechBoosted": ("💡", "Eureka"),
    "CivicBoosted": ("💡", "Inspiration"),
    "Tech": ("🔬", "Technology"),
    "Civic": ("📜", "Civic"),
    "Strength": ("⚔️", "Strength"),
    "Movement": ("👣", "Movement"),
    "Ranged": ("🏹", "Ranged"),
    "Range": ("🎯", "Range"),
    "Citizen": ("👤", "Citizen"),
    "Capital": ("⭐", "Capital"),
    "Districts": ("🏛️", "District"),
    "District": ("🏛️", "District"),
    "GreatPerson": ("🌟", "Great Person"),
    "GreatGeneral": ("🎖️", "Great General"),
    "Envoy": ("🤝", "Envoy"),
    "GoldenAge": ("🌅", "Golden Age"),
    "Bullet": ("•", ""),
    "PromotionGeneric": ("🎖️", "Promotion"),
    "Charges": ("🛠️", "Build Charges"),
}


def _icon_chip(name: str) -> str:
    if name in ICON_MAP:
        emoji, label = ICON_MAP[name]
        if not label:
            return emoji
        return f'<span class="chip" title="{html.escape(label)}">{emoji}</span>'
    # Resource icons are always followed by the resource's name in the prose,
    # so the icon token itself is redundant — drop it.
    if name.startswith("RESOURCE_"):
        return ""
    pretty = name.replace("_", " ")
    return f'<span class="chip chip-unknown" title="{html.escape(pretty)}">{html.escape(pretty)}</span>'


_ICON_RE = re.compile(r"\[ICON_([A-Za-z0-9_]+)\]")
_COLOR_RE = re.compile(r"\[COLOR[^\]]*\]|\[ENDCOLOR\]", re.IGNORECASE)
_OTHER_TAG_RE = re.compile(r"\[/?[A-Za-z][^\]]*\]")
_TOKEN_RE = re.compile(r"\{(LOC_[A-Za-z0-9_]+)\}")


def _prettify_key(key: str) -> str:
    base = re.sub(r"^LOC_", "", key)
    base = re.sub(r"_(NAME|DESCRIPTION|ABBREVIATION)$", "", base)
    base = re.sub(r"^(TECH|CIVIC|UNIT|BUILDING|IMPROVEMENT|DISTRICT|RESOURCE|FEATURE|TERRAIN)_", "", base)
    return base.replace("_", " ").title()


def resolve_tokens(text: str, loc: dict[str, str]) -> str:
    """Civ text interpolates `{LOC_*}` tokens. Resolve from the string table,
    or fall back to a prettified form of the key (for base-game keys the mod
    does not ship)."""
    def sub(m):
        key = m.group(1)
        return loc.get(key) or _prettify_key(key)
    # resolve up to a couple of nesting levels
    for _ in range(3):
        new = _TOKEN_RE.sub(sub, text)
        if new == text:
            break
        text = new
    return text


def render_text(loc_key_or_text: str | None, loc: dict[str, str]) -> str:
    """Resolve a LOC key (or pass through literal text) and convert the game's
    inline markup to HTML paragraphs."""
    if not loc_key_or_text:
        return ""
    text = loc.get(loc_key_or_text, loc_key_or_text)
    text = resolve_tokens(text, loc)
    text = html.escape(text)
    text = text.replace("[NEWLINE]", "\n")
    text = _ICON_RE.sub(lambda m: _icon_chip(m.group(1)), text)
    text = _COLOR_RE.sub("", text)
    text = _OTHER_TAG_RE.sub("", text)
    paras = [p.strip() for p in text.split("\n")]
    paras = [p for p in paras if p]
    return "".join(f"<p>{p}</p>" for p in paras)


def render_inline(loc_key_or_text: str | None, loc: dict[str, str]) -> str:
    """Like render_text but single-line (no <p> wrapping)."""
    if not loc_key_or_text:
        return ""
    text = resolve_tokens(loc.get(loc_key_or_text, loc_key_or_text), loc)
    text = html.escape(text)
    text = _ICON_RE.sub(lambda m: _icon_chip(m.group(1)), text)
    text = _COLOR_RE.sub("", text)
    text = _OTHER_TAG_RE.sub("", text)
    return text.replace("[NEWLINE]", " ").strip()


def name_of(loc_key: str | None, loc: dict[str, str]) -> str:
    if not loc_key:
        return ""
    return html.escape(loc.get(loc_key, loc_key))


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------

class Model:
    def __init__(self):
        self.tables = parse.load_sql(os.path.join(ROOT, "Data"))
        self.loc = parse.load_text(os.path.join(ROOT, "Text"))
        self.icons = parse.load_icons(os.path.join(ROOT, "Icons"))
        # Canonical (standard-game) tree edges — NOT the nomadic/compat re-wiring.
        self.canon = parse.load_sql_files([
            os.path.join(ROOT, "Data", "Technologies.sql"),
            os.path.join(ROOT, "Data", "Civics.sql"),
        ])
        # Base-game units/buildings/improvements the mod re-gates onto a
        # prehistoric prereq (e.g. Settler -> Fire). These are UPDATEs, so they
        # don't appear as INSERT rows. Read only the standard-game files.
        self._build_regated([
            os.path.join(ROOT, "Data", "Units.sql"),
            os.path.join(ROOT, "Data", "Buildings.sql"),
            os.path.join(ROOT, "Data", "Improvements.sql"),
        ])
        # Optional hand-maintained supplement: base-game successor policy ->
        # unlocking civic (not present in the mod's own data).
        self.base_policies = {}
        bp = os.path.join(os.path.dirname(__file__), "base_policies.json")
        if os.path.exists(bp):
            with open(bp, encoding="utf-8") as fh:
                self.base_policies = {k: v for k, v in json.load(fh).items()
                                      if not k.startswith("_")}

    _REGATE_TABLES = {
        "Units": ("UnitType", "unit"),
        "Buildings": ("BuildingType", "building"),
        "Improvements": ("ImprovementType", "improvement"),
    }

    def _build_regated(self, paths):
        self.regated = {}  # (prereq_col, prereq_value) -> [(kind, type_key)]
        seen = set()
        for upd in parse.load_updates(paths):
            meta = self._REGATE_TABLES.get(upd["table"])
            if not meta:
                continue
            tcol, kind = meta
            tkey = upd["where"].get(tcol)
            if not tkey or "_PR_" in tkey:  # skip new PR content (handled via INSERT)
                continue
            for col in ("PrereqTech", "PrereqCivic"):
                val = upd["set"].get(col)
                if val and "_PR_" in val:
                    dedup = (col, val, kind, tkey)
                    if dedup in seen:
                        continue
                    seen.add(dedup)
                    self.regated.setdefault((col, val), []).append((kind, tkey))

    def rows(self, table):
        return self.tables.get(table, [])

    def canon_rows(self, table):
        return self.canon.get(table, [])

    def boost_requirement(self, type_col, type_key):
        """The Eureka/Inspiration TRIGGER (what you must do to earn it), not the
        flavor line. Read from the canonical Technologies.sql / Civics.sql only —
        the 6T-compat and Nomadic files add variant triggers that don't apply to
        a standard game."""
        for b in self.canon_rows("Boosts"):
            if b.get(type_col) == type_key and b.get("TriggerDescription"):
                return b["TriggerDescription"]
        return None

    def yields_for(self, table, key_col, key):
        out = []
        for r in self.rows(table):
            if r.get(key_col) == key:
                amt = r.get("YieldChange")
                yt = (r.get("YieldType") or "").replace("YIELD_", "").title()
                if amt is not None and yt:
                    out.append((yt, amt))
        return out

    def icon_web(self, type_key):
        """Return the web/ relative icon path for a type, or None."""
        cand = type_key if type_key.startswith("ICON_") else f"ICON_{type_key}"
        for k in (cand, type_key):
            if k in self.icons:
                return f"assets/icons/{os.path.basename(self.icons[k])}"
        return None


def fmt_yields(pairs):
    """Format list of (Yield, amount) as chips using ICON_MAP."""
    parts = []
    for yt, amt in pairs:
        emoji = ICON_MAP.get(yt, ("", yt))[0] or ""
        try:
            n = float(amt)
            amt_s = str(int(n)) if n == int(n) else str(n)
            sign = "+" if n >= 0 else ""
        except (TypeError, ValueError):
            amt_s, sign = str(amt), ""
        parts.append(
            f'<span class="yield">{sign}{amt_s} {emoji}'
            f'<span class="ylabel">{html.escape(yt)}</span></span>'
        )
    return " ".join(parts)


# --------------------------------------------------------------------------
# Tree layout (tech + civics)
# --------------------------------------------------------------------------

def compute_columns(nodes, edges):
    """col(node) = 1 + max(col(same-set prereq)); roots => col 1."""
    preds = {n: [] for n in nodes}
    for src, dst in edges:
        if src in nodes and dst in nodes:
            preds[dst].append(src)
    col = {}

    def resolve(n, stack):
        if n in col:
            return col[n]
        if n in stack:  # cycle guard
            return 1
        stack.add(n)
        col[n] = 1 if not preds[n] else 1 + max(resolve(p, stack) for p in preds[n])
        stack.discard(n)
        return col[n]

    for n in nodes:
        resolve(n, set())
    return col


def place_rows(nodes, col, rowpref):
    """Assign each node a unique (col,row) cell, honoring UITreeRow preference
    and nudging to the nearest free row on collision (mirrors the engine)."""
    used = set()
    placed = {}
    for n in sorted(nodes, key=lambda x: (col[x], rowpref.get(x, 0))):
        c, pref = col[n], rowpref.get(n, 0)
        r, d = pref, 0
        while (c, r) in used:
            d += 1
            r = pref + (d if d % 2 else -d)
        used.add((c, r))
        placed[n] = (c, r)
    return placed


def render_tree_svg(nodes, edges, placed, labels, icons, gate_edges, gate_labels):
    COL_W, ROW_H = 220, 96
    NODE_W, NODE_H = 168, 60
    PAD_X, PAD_Y = 40, 60

    cols = [c for c, _ in placed.values()]
    rows = [r for _, r in placed.values()]
    min_r, max_r = min(rows), max(rows)
    max_c = max(cols)
    width = PAD_X * 2 + (max_c - 1) * COL_W + NODE_W + 150
    height = PAD_Y * 2 + (max_r - min_r) * ROW_H + NODE_H

    def xy(n):
        c, r = placed[n]
        return PAD_X + (c - 1) * COL_W, PAD_Y + (r - min_r) * ROW_H

    svg = [f'<svg class="tree" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" role="img">']

    for src, dst in edges:
        if src not in placed or dst not in placed:
            continue
        x1, y1 = xy(src)
        x2, y2 = xy(dst)
        sx, sy = x1 + NODE_W, y1 + NODE_H / 2
        ex, ey = x2, y2 + NODE_H / 2
        mx = (sx + ex) / 2
        svg.append(f'<path class="edge" d="M {sx} {sy} C {mx} {sy}, {mx} {ey}, {ex} {ey}" />')

    gate_by_src = {}
    for src, dst in gate_edges:
        gate_by_src.setdefault(src, []).append(dst)
    for src, dsts in gate_by_src.items():
        if src not in placed:
            continue
        x1, y1 = xy(src)
        sx, sy = x1 + NODE_W, y1 + NODE_H / 2
        for i, dst in enumerate(dsts):
            ty = sy + (i - (len(dsts) - 1) / 2) * 16
            svg.append(f'<line class="gate" x1="{sx}" y1="{sy}" x2="{sx + 22}" y2="{ty}" />')
            svg.append(f'<text class="gate-label" x="{sx + 26}" y="{ty + 4}">→ {html.escape(gate_labels.get(dst, dst))}</text>')

    for n in nodes:
        if n not in placed:
            continue
        x, y = xy(n)
        icon = icons.get(n)
        svg.append(f'<g class="node" transform="translate({x},{y})">')
        svg.append(f'<rect width="{NODE_W}" height="{NODE_H}" rx="8" />')
        tx = 10
        if icon:
            svg.append(f'<image href="{icon}" x="8" y="8" width="44" height="44" />')
            tx = 60
        svg.append(f'<text class="node-title" x="{tx}" y="26">{html.escape(labels.get(n, n))}</text>')
        meta = labels.get(n + "::meta", "")
        if meta:
            svg.append(f'<text class="node-meta" x="{tx}" y="45">{html.escape(meta)}</text>')
        svg.append("</g>")

    svg.append("</svg>")
    return "\n".join(svg)


# --------------------------------------------------------------------------
# HTML scaffolding
# --------------------------------------------------------------------------

NAV = [
    ("index.html", "Overview"),
    ("tech-tree.html", "Technologies"),
    ("civics.html", "Civics"),
    ("policies.html", "Policies"),
    ("pantheons.html", "Pantheons"),
    ("units.html", "Units"),
    ("buildings.html", "Buildings"),
    ("wonders.html", "Wonders"),
    ("improvements.html", "Improvements"),
    ("myths.html", "Myths"),
    ("governments.html", "Governments"),
    ("governor.html", "Governor"),
    ("society.html", "Society"),
]


def page(title, active, body):
    nav = "".join(
        f'<a href="{href}" class="{"active" if href == active else ""}">{label}</a>'
        for href, label in NAV
    )
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{'<meta name="robots" content="noindex, nofollow">' if NOINDEX else ''}
<title>{html.escape(title)} — Prehistoric Era</title>
<link rel="stylesheet" href="assets/style.css">
</head>
<body>
<header class="site-header">
  <div class="brand"><a href="index.html">🔥 Prehistoric Era</a><span class="ver">v{MOD_VERSION}</span></div>
  <nav>{nav}</nav>
</header>
<main>
{body}
</main>
<footer class="site-footer">
  <span>Mod <a href="{MOD_URL}" target="_blank" rel="noopener">Prehistoric Era</a> © {MOD_AUTHOR}. Unofficial fan-made reference, not affiliated with the author.</span>
  <span>Generated {stamp} from the mod's data files.</span>
</footer>
</body>
</html>"""


def card_grid(cards):
    return f'<div class="grid">{"".join(cards)}</div>'


# --------------------------------------------------------------------------
# Reverse lookups: what a tech / civic unlocks
# --------------------------------------------------------------------------

def unlocks_for(m, prereq_col, prereq_key):
    """Returns (kind, type_key, namekey, regated). New PR content comes from
    INSERT rows; re-gated base-game content comes from the mod's UPDATEs."""
    out = []
    for tbl, tcol, ncol, kind in [
        ("Units", "UnitType", "Name", "unit"),
        ("Buildings", "BuildingType", "Name", "building"),
        ("Improvements", "ImprovementType", "Name", "improvement"),
    ]:
        for r in m.rows(tbl):
            t = r.get(tcol) or ""
            if r.get(prereq_col) == prereq_key and "_PR_" in t:
                out.append((kind, t, r.get(ncol), False))
    # Civics also unlock policy cards (Policies.PrereqCivic).
    if prereq_col == "PrereqCivic":
        for r in m.rows("Policies"):
            t = r.get("PolicyType") or ""
            if r.get("PrereqCivic") == prereq_key and "_PR_" in t:
                out.append(("policy", t, r.get("Name"), False))
    for kind, type_key in m.regated.get((prereq_col, prereq_key), []):
        out.append((kind, type_key, None, True))
    return out


def unlock_chips(m, unlocks):
    if not unlocks:
        return ""
    items = []
    for kind, type_key, namekey, regated in unlocks:
        label = (m.loc.get(namekey) if namekey else None) or nice_type(m, type_key)
        icon = m.icon_web(type_key)
        img = f'<img src="{icon}" alt="">' if icon else ""
        cls = f"ul ul-{kind}" + (" ul-regated" if regated else "")
        title = ' title="Base-game content, re-gated to this prerequisite by the mod"' if regated else ""
        tag = '<span class="ul-base">base</span>' if regated else ""
        inner = f"{img}{html.escape(label)}{tag}"
        if kind == "policy":
            items.append(f'<a class="{cls}" href="policies.html#{type_key}"{title}>{inner}</a>')
        else:
            items.append(f'<span class="{cls}"{title}>{inner}</span>')
    return f'<div class="unlocks"><span class="ul-head">Unlocks</span>{"".join(items)}</div>'


def nice_type(m, type_key):
    """Best-effort readable name for any type key (looks up LOC_<TYPE>_NAME)."""
    guess = f"LOC_{type_key}_NAME"
    if guess in m.loc:
        return m.loc[guess]
    base = re.sub(r"^(TECH|CIVIC|UNIT|BUILDING|IMPROVEMENT|POLICY|DISTRICT|RESOURCE)_", "", type_key)
    return base.replace("_", " ").title()


def prereq_label(m, r):
    bits = []
    if r.get("PrereqTech"):
        bits.append(f'🔬 {nice_type(m, r["PrereqTech"])}')
    if r.get("PrereqCivic"):
        bits.append(f'🎭 {nice_type(m, r["PrereqCivic"])}')
    return " · ".join(bits) if bits else "—"


def effects_block(m, type_key):
    """The hand-authored gameplay benefits a tech/civic grants (harvest unlocks,
    new buildable terrain, adjacency and Palace yields). These live in the
    type's Description text, which the mod writes by hand because the engine
    does not auto-describe modifier/harvest/adjacency gates on the node."""
    key = f"LOC_{type_key}_DESCRIPTION"
    if key not in m.loc or not m.loc[key].strip():
        return ""
    return f'<div class="effects"><span class="eff-head">Effects</span>{render_text(key, m.loc)}</div>'


def boost_block(m, type_col, type_key, label):
    req = m.boost_requirement(type_col, type_key)
    if not req:
        return ""
    return f'<div class="eureka"><span class="eu-tag">💡 {label}</span> {render_inline(req, m.loc)}</div>'


def icon_img(m, type_key, glyph="⬦"):
    icon = m.icon_web(type_key)
    if icon:
        return f'<img class="ico" src="{icon}" alt="">'
    return f'<div class="ico ico-blank">{glyph}</div>'


def entity_card(m, type_key, namekey, desckey, sub, yields="", quote="", glyph="⬦"):
    img = icon_img(m, type_key, glyph)
    y = f'<div class="yields">{yields}</div>' if yields else ""
    q = f"<blockquote>{render_inline(quote, m.loc)}</blockquote>" if quote else ""
    return f"""<div class="card" id="{type_key}">
  <div class="card-head">{img}<div><h3>{name_of(namekey, m.loc)}</h3><div class="sub">{sub}</div></div></div>
  {y}
  <div class="desc">{render_text(desckey, m.loc)}</div>
  {q}
</div>"""


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

def build_tech_page(m):
    techs = m.rows("Technologies")
    nodes = {r["TechnologyType"] for r in techs}
    rowpref = {r["TechnologyType"]: int(r.get("UITreeRow") or 0) for r in techs}
    edges = [(e["PrereqTech"], e["Technology"]) for e in m.canon_rows("TechnologyPrereqs")]
    intra = [(a, b) for a, b in edges if a in nodes and b in nodes]
    gates = [(a, b) for a, b in edges if a in nodes and b not in nodes]

    col = compute_columns(nodes, intra)
    placed = place_rows(nodes, col, rowpref)

    labels, icons = {}, {}
    for r in techs:
        tt = r["TechnologyType"]
        labels[tt] = m.loc.get(r["Name"], r["Name"])
        labels[tt + "::meta"] = f"{r.get('Cost')} science"
        icons[tt] = m.icon_web(tt)

    gate_labels = {b: nice_type(m, b) for _, b in gates}
    svg = render_tree_svg(nodes, intra, placed, labels, icons, gates, gate_labels)

    order = sorted(techs, key=lambda r: (col[r["TechnologyType"]], placed[r["TechnologyType"]][1]))
    cards = []
    for r in order:
        tt = r["TechnologyType"]
        img = icon_img(m, tt, "🔬")
        cards.append(f"""<div class="card" id="{tt}">
  <div class="card-head">{img}<div><h3>{name_of(r['Name'], m.loc)}</h3>
  <div class="sub">Cost {r.get('Cost')} 🧪 · Prehistoric Era</div></div></div>
  {effects_block(m, tt)}
  {boost_block(m, 'TechnologyType', tt, 'Eureka')}
  {unlock_chips(m, unlocks_for(m, 'PrereqTech', tt))}
</div>""")

    body = f"""<h1>Technology Tree</h1>
<p class="lead">The Prehistoric era adds <strong>{len(techs)}</strong> new technologies, from Flintknapping to Agriculture. Columns follow prerequisite depth (as in-game). Dashed arrows on the right show where each branch gates into the Ancient era.</p>
<p class="note">ℹ️ This shows the <strong>standard game</strong>. In the <em>Wandering Start</em> game mode the technology tree is re-tuned — different prerequisites, layout, costs, and Eurekas.</p>
<div class="tree-wrap">{svg}</div>
<h2>Details</h2>
{card_grid(cards)}"""
    return page("Technologies", "tech-tree.html", body)


def build_civics_page(m):
    civics = m.rows("Civics")
    nodes = {r["CivicType"] for r in civics}
    rowpref = {r["CivicType"]: int(r.get("UITreeRow") or 0) for r in civics}
    edges = [(e["PrereqCivic"], e["Civic"]) for e in m.canon_rows("CivicPrereqs")]
    intra = [(a, b) for a, b in edges if a in nodes and b in nodes]
    gates = [(a, b) for a, b in edges if a in nodes and b not in nodes]

    col = compute_columns(nodes, intra)
    placed = place_rows(nodes, col, rowpref)

    labels, icons = {}, {}
    for r in civics:
        ct = r["CivicType"]
        labels[ct] = m.loc.get(r["Name"], r["Name"])
        labels[ct + "::meta"] = f"{r.get('Cost')} culture"
        icons[ct] = m.icon_web(ct)
    gate_labels = {b: nice_type(m, b) for _, b in gates}
    svg = render_tree_svg(nodes, intra, placed, labels, icons, gates, gate_labels)

    order = sorted(civics, key=lambda r: (col[r["CivicType"]], placed[r["CivicType"]][1]))
    cards = []
    for r in order:
        ct = r["CivicType"]
        img = icon_img(m, ct, "📜")
        cards.append(f"""<div class="card" id="{ct}">
  <div class="card-head">{img}<div><h3>{name_of(r['Name'], m.loc)}</h3>
  <div class="sub">Cost {r.get('Cost')} 🎭 · Prehistoric Era</div></div></div>
  {effects_block(m, ct)}
  {boost_block(m, 'CivicType', ct, 'Inspiration')}
  {unlock_chips(m, unlocks_for(m, 'PrereqCivic', ct))}
</div>""")

    body = f"""<h1>Civics Tree</h1>
<p class="lead">The governance spine (Band → Tribe → Chiefdom → Customary Law) plus culture and faith lanes: <strong>{len(civics)}</strong> new civics that converge into the Ancient era's Code of Laws and Mysticism.</p>
<div class="tree-wrap">{svg}</div>
<h2>Details</h2>
{card_grid(cards)}"""
    return page("Civics", "civics.html", body)


def build_units_page(m):
    units = [r for r in m.rows("Units") if "_PR_" in (r.get("UnitType") or "")]
    players = [r for r in units if "BARBARIAN" not in r["UnitType"]]
    barbs = [r for r in units if "BARBARIAN" in r["UnitType"]]

    def card(r):
        ut = r["UnitType"]
        sub = f"Cost {r.get('Cost')} · {prereq_label(m, r)}"
        stats = []
        if r.get("Combat"):
            stats.append(("Strength", r["Combat"]))
        if r.get("RangedCombat"):
            stats.append(("Ranged", r["RangedCombat"]))
        if r.get("BaseMoves"):
            stats.append(("Movement", r["BaseMoves"]))
        if r.get("BuildCharges"):
            stats.append(("Charges", r["BuildCharges"]))
        return entity_card(m, ut, r.get("Name"), r.get("Description"), sub, fmt_yields(stats))

    # Base-game units the mod re-gates / edits (UPDATE statements, standard-game file).
    CHANGE_LABEL = {
        "PrereqTech": "Now requires",
        "PrereqCivic": "Now requires civic",
        "MandatoryObsoleteTech": "Becomes obsolete at",
        "ObsoleteTech": "Obsolete with",
        "Cost": "Cost",
    }
    mod_units = {}  # type_key -> {col: val}
    for upd in parse.load_updates([os.path.join(ROOT, "Data", "Units.sql")]):
        if upd["table"] != "Units":
            continue
        ut = upd["where"].get("UnitType")
        targets = ut if isinstance(ut, list) else ([ut] if ut else [])
        for t in targets:
            if not t or "_PR_" in t:
                continue
            mod_units.setdefault(t, {}).update(upd["set"])

    def mod_card(type_key, changes):
        rows = []
        for col, val in changes.items():
            if val is None:
                continue
            label = CHANGE_LABEL.get(col, col)
            shown = nice_type(m, val) if isinstance(val, str) and val.startswith(("TECH_", "CIVIC_")) else str(val)
            rows.append(f'<div class="mod-row"><span class="mod-k">{html.escape(label)}</span> {html.escape(shown)}</div>')
        return f"""<div class="card" id="{type_key}">
  <div class="card-head">{icon_img(m, type_key, "🗿")}<div><h3>{html.escape(nice_type(m, type_key))}</h3>
  <div class="sub">Base-game unit · re-gated by the mod</div></div></div>
  {''.join(rows)}
</div>"""

    mod_section = ""
    if mod_units:
        cards = [mod_card(t, mod_units[t]) for t in sorted(mod_units)]
        mod_section = f"""<h2>Modified base-game units</h2>
<p class="lead">Existing Civilization VI units the mod re-gates so the tech tree lines up with the new era — the Settler, Warrior, Slinger and Scout move into the Prehistoric era, while the Builder is pushed later so the Tribesperson covers the stone age.</p>
{card_grid(cards)}"""

    body = f"""<h1>Units</h1>
<p class="lead">{len(players)} player units for the stone age, plus {len(barbs)} prehistoric barbarian and naval units.</p>
<h2>Player units</h2>
{card_grid([card(r) for r in players])}
<h2>Barbarian &amp; naval units</h2>
{card_grid([card(r) for r in barbs])}
{mod_section}"""
    return page("Units", "units.html", body)


def build_buildings_page(m):
    blds = [r for r in m.rows("Buildings")
            if "_PR_" in (r.get("BuildingType") or "") and not r.get("IsWonder")]

    def card(r):
        bt = r["BuildingType"]
        sub = f"Cost {r.get('Cost')} · {prereq_label(m, r)}"
        yields = fmt_yields(m.yields_for("Building_YieldChanges", "BuildingType", bt))
        return entity_card(m, bt, r.get("Name"), r.get("Description"), sub, yields)

    body = f"""<h1>Buildings</h1>
<p class="lead">{len(blds)} new buildings for the early economy — the communal Hearth, the record-keeping Tablet House, and early craft workshops.</p>
{card_grid([card(r) for r in blds])}"""
    return page("Buildings", "buildings.html", body)


def build_wonders_page(m):
    wonders = [r for r in m.rows("Buildings")
               if "_PR_" in (r.get("BuildingType") or "") and r.get("IsWonder")]

    def card(r):
        bt = r["BuildingType"]
        sub = f"Wonder · Cost {r.get('Cost')} · {prereq_label(m, r)}"
        yields = fmt_yields(m.yields_for("Building_YieldChanges", "BuildingType", bt))
        qkey = f"LOC_{bt}_QUOTE"
        quote = qkey if qkey in m.loc else ""
        return entity_card(m, bt, r.get("Name"), r.get("Description"), sub, yields, quote)

    body = f"""<h1>Wonders</h1>
<p class="lead">{len(wonders)} prehistoric world wonders — Göbekli Tepe, Nabta Playa, Poverty Point, Çatalhöyük and the Tower of Jericho.</p>
{card_grid([card(r) for r in wonders])}"""
    return page("Wonders", "wonders.html", body)


def build_improvements_page(m):
    imps = [r for r in m.rows("Improvements") if "_PR_" in (r.get("ImprovementType") or "")]

    def card(r):
        it = r["ImprovementType"]
        sub = prereq_label(m, r)
        yields = fmt_yields(m.yields_for("Improvement_YieldChanges", "ImprovementType", it))
        return entity_card(m, it, r.get("Name"), r.get("Description"), sub, yields)

    body = f"""<h1>Tile Improvements</h1>
<p class="lead">{len(imps)} improvements built during the stone age — foraging camps, pit houses, palisades, cairns and ritual sites.</p>
{card_grid([card(r) for r in imps])}"""
    return page("Improvements", "improvements.html", body)


def build_pantheons_page(m):
    pans = [b for b in m.rows("Beliefs")
            if b.get("BeliefClassType") == "BELIEF_CLASS_PANTHEON" and "_PR_" in (b.get("BeliefType") or "")]
    cards = []
    for b in pans:
        bt = b["BeliefType"]
        cards.append(f"""<div class="card" id="{bt}">
  <div class="card-head">{icon_img(m, bt, "🛐")}<div><h3>{name_of(b.get('Name'), m.loc)}</h3><div class="sub">Pantheon</div></div></div>
  <div class="desc">{render_text(b.get('Description'), m.loc)}</div>
</div>""")
    body = f"""<h1>Pantheons</h1>
<p class="lead">{len(pans)} new pantheon beliefs themed for the stone age. As in the base game, you found a Pantheon with your first accumulated ✨ Faith and choose one belief — these join the base-game pantheons in the pool, giving early, terrain- and ritual-focused options that fit the Prehistoric era.</p>
{card_grid(cards)}"""
    return page("Pantheons", "pantheons.html", body)


def load_myth_ids():
    """Ordered list of the 25 origin-myth ids from the Lua catalog
    (Scripts/OriginMyth.lua OM_CATALOG)."""
    path = os.path.join(ROOT, "Scripts", "OriginMyth.lua")
    if not os.path.exists(path):
        return []
    txt = open(path, encoding="utf-8-sig").read()
    m = re.search(r"OM_CATALOG\s*=\s*\{(.*?)\n\};", txt, re.DOTALL)
    block = m.group(1) if m else txt
    return re.findall(r'id\s*=\s*"([A-Z_]+)"', block)


def build_myths_page(m):
    ids = load_myth_ids()
    cards = []
    for mid in ids:
        name = m.loc.get(f"LOC_MYTH_PR_{mid}_NAME", mid.title())
        eff_key = f"LOC_MYTH_PR_{mid}_EFFECT"
        flavor_key = f"LOC_MYTH_PR_{mid}_FLAVOR"
        cond = m.loc.get(f"LOC_PR_MYTH_JNY_COND_{mid}")
        icon = m.icon_web(f"MYTH_PR_{mid}")
        img = f'<img class="ico" src="{icon}" alt="">' if icon else '<div class="ico ico-blank">🌀</div>'
        effect = f'<div class="effects"><span class="eff-head">Effect</span>{render_text(eff_key, m.loc)}</div>' if eff_key in m.loc else ""
        journey = f'<div class="journey"><span class="eff-head">The journey toward it</span>{html.escape(cond)}</div>' if cond else ""
        flavor = f"<blockquote>{render_inline(flavor_key, m.loc)}</blockquote>" if flavor_key in m.loc else ""
        cards.append(f"""<div class="card myth" id="MYTH_PR_{mid}">
  <div class="card-head">{img}<div><h3>{html.escape(name)}</h3><div class="sub">Origin Myth</div></div></div>
  {effect}
  {journey}
  {flavor}
</div>""")

    intro = render_text("LOC_PR_MYTH_POPUP_BODY", m.loc)
    body = f"""<h1>Origin Myths</h1>
<p class="lead">A <strong>Wandering Start</strong> feature. When your roaming band founds its first city, the elders tell the story of how your people came to be — and you choose one of <strong>{len(ids)}</strong> origin myths, each granting a permanent bonus. Which myths are offered is shaped by the journey your band actually walked (the "journey" line on each card below is what earns it).</p>
<div class="era-desc">{intro}</div>
<div class="grid" style="margin-top:20px">{"".join(cards)}</div>"""
    return page("Origin Myths", "myths.html", body)


SLOT_INFO = {
    "SLOT_MILITARY": ("Military", "slot-military", "⚔️"),
    "SLOT_ECONOMIC": ("Economic", "slot-economic", "💰"),
    "SLOT_DIPLOMATIC": ("Diplomatic", "slot-diplomatic", "🕊️"),
    "SLOT_WILDCARD": ("Wildcard", "slot-wildcard", "⭐"),
    "SLOT_GREAT_PERSON": ("Great Person", "slot-great", "🌟"),
}


def build_policies_page(m):
    pols = [r for r in m.rows("Policies") if "_PR_" in (r.get("PolicyType") or "")]
    obsolete = {o["PolicyType"]: o.get("ObsoletePolicy")
                for o in m.rows("ObsoletePolicies") if o.get("PolicyType")}
    # PrereqCivic of every policy the mod itself defines (covers PR -> PR chains).
    pol_civic = {r["PolicyType"]: r.get("PrereqCivic")
                 for r in m.rows("Policies") if r.get("PolicyType")}

    def successor_civic(succ):
        """Readable civic that unlocks a successor policy: from mod data when the
        successor is a mod policy, else from the base_policies.json supplement."""
        if succ in pol_civic and pol_civic[succ]:
            return nice_type(m, pol_civic[succ]), None
        info = m.base_policies.get(succ)
        if info:
            return info.get("civic"), info.get("era")
        return None, None

    # order the unlocking civics the way the civics tree does (col, then row)
    civics = m.rows("Civics")
    cnodes = {r["CivicType"] for r in civics}
    cedges = [(e["PrereqCivic"], e["Civic"]) for e in m.canon_rows("CivicPrereqs")]
    ccol = compute_columns(cnodes, [(a, b) for a, b in cedges if a in cnodes and b in cnodes])
    crow = {r["CivicType"]: int(r.get("UITreeRow") or 0) for r in civics}
    civic_order = sorted(cnodes, key=lambda c: (ccol.get(c, 99), crow.get(c, 0)))
    rank = {c: i for i, c in enumerate(civic_order)}

    groups = {}
    for p in pols:
        groups.setdefault(p.get("PrereqCivic"), []).append(p)

    def policy_card(p):
        pt = p["PolicyType"]
        slot = SLOT_INFO.get(p.get("GovernmentSlotType"), ("Policy", "slot-wildcard", "•"))
        badge = f'<span class="slot {slot[1]}">{slot[2]} {slot[0]}</span>'
        succ = obsolete.get(pt)
        if succ:
            civic, era = successor_civic(succ)
            by = civic or nice_type(m, succ)
            succ_name = nice_type(m, succ)
            era_s = f", {era} era" if era else ""
            tip = f"Superseded by {succ_name} ({by}{era_s})"
            exp = f'<div class="expires" title="{html.escape(tip)}">⏳ Obsoleted by <b>{html.escape(by)}</b>.</div>'
        else:
            exp = '<div class="expires perm">♾️ No successor — remains available.</div>'
        return f"""<div class="card" id="{pt}">
  <div class="card-head" style="justify-content:space-between"><h3>{name_of(p.get('Name'), m.loc)}</h3>{badge}</div>
  <div class="desc">{render_text(p.get('Description'), m.loc)}</div>
  {exp}
</div>"""

    sections = []
    for civic in sorted(groups, key=lambda c: rank.get(c, 99)):
        cname = nice_type(m, civic) if civic else "Other"
        cards = "".join(policy_card(p) for p in groups[civic])
        sections.append(
            f'<section class="pol-group"><h2>{html.escape(cname)} '
            f'<span class="civic-tag">— {len(groups[civic])} '
            f'{"card" if len(groups[civic]) == 1 else "cards"}</span></h2>{card_grid([cards])}</section>'
        )

    body = f"""<h1>Policy Cards</h1>
<p class="lead">{len(pols)} prehistoric policy cards, grouped by the civic that unlocks them. Each is an early, weaker ancestor of a later base-game card and is <strong>superseded</strong> — automatically retired — once its successor becomes available.</p>
{"".join(sections)}"""
    return page("Policies", "policies.html", body)


def html_table(headers, rows):
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tbl-wrap"><table class="tbl"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def split_unlock(raw):
    """Secret-society title descriptions begin with the unlock condition, e.g.
    'Unlocked in the Medieval Era. <effect>'. Split it out for a tidy table."""
    if raw and raw.strip().startswith("Unlocked"):
        parts = raw.split(". ", 1)
        unlock = parts[0].strip().rstrip(".")
        unlock = re.sub(r"^Unlocked\s+", "", unlock)
        unlock = unlock[:1].upper() + unlock[1:] if unlock else unlock
        return unlock, (parts[1] if len(parts) > 1 else "")
    return None, raw


def governor_promotions(m, gov_type):
    in_set = {r["GovernorPromotion"] for r in m.rows("GovernorPromotionSets")
              if r.get("GovernorType") == gov_type}
    proms = [p for p in m.rows("GovernorPromotions") if p.get("GovernorPromotionType") in in_set]
    prereqs = {}
    for r in m.rows("GovernorPromotionPrereqs"):
        pt = r.get("GovernorPromotionType")
        if pt in in_set:
            prereqs.setdefault(pt, []).append(r.get("PrereqGovernorPromotion"))
    proms.sort(key=lambda p: (int(p.get("Level") or 0), m.loc.get(p.get("Name"), "")))
    return proms, prereqs


def build_governor_page(m):
    gt = "GOVERNOR_PR_SHAMAN"
    gov = next((g for g in m.rows("Governors") if g.get("GovernorType") == gt), None)
    proms, prereqs = governor_promotions(m, gt)
    pname = {p["GovernorPromotionType"]: m.loc.get(p.get("Name"), p.get("Name")) for p in proms}
    rows = []
    for p in proms:
        pt = p["GovernorPromotionType"]
        req = "First title" if p.get("BaseAbility") == "1" or not prereqs.get(pt) else \
            " or ".join(html.escape(pname.get(x, x)) for x in prereqs[pt])
        rows.append([
            f'<span class="tbl-title">{name_of(p.get("Name"), m.loc)}</span>',
            f'Tier {p.get("Level")}',
            req,
            render_text(p.get("Description"), m.loc),
        ])
    icon = m.icon_web("GovernorNormal_Shaman")
    img = f'<img class="ico" src="{icon}" alt="">' if icon else '<div class="ico ico-blank">🧙</div>'
    title = name_of(gov.get("Title"), m.loc) if gov and gov.get("Title", "").startswith("LOC") else ""
    desc = render_text(f"LOC_{gt}_DESCRIPTION", m.loc) if f"LOC_{gt}_DESCRIPTION" in m.loc else ""
    body = f"""<h1>Governor — the Shaman</h1>
<p class="lead">A unique Prehistoric Governor. Establish and promote the Shaman to shape a city with hunt-magic, healing, and ritual.</p>
<div class="card" style="max-width:640px">
  <div class="card-head">{img}<div><h3>{name_of(gov.get('Name'), m.loc) if gov else 'Shaman'}</h3><div class="sub">{title}</div></div></div>
  {desc}
</div>
<h2>Titles (promotions)</h2>
{html_table(['Title', 'Tier', 'Requires', 'Effect'], rows)}"""
    return page("Governor", "governor.html", body)


def build_society_page(m):
    s = next((x for x in m.rows("SecretSocieties") if "_PR_" in (x.get("SecretSocietyType") or "")), None)
    if not s:
        return page("Secret Society", "society.html", "<h1>Secret Society</h1><p>None found.</p>")
    gt = s.get("GovernorType")
    proms, prereqs = governor_promotions(m, gt)
    rows = []
    for p in proms:
        unlock, effect = split_unlock(m.loc.get(p.get("Description"), ""))
        rows.append([
            f'<span class="tbl-title">{name_of(p.get("Name"), m.loc)}</span>',
            html.escape(unlock) if unlock else f'Tier {p.get("Level")}',
            render_text(effect, m.loc),
        ])
    chance = s.get("DiscoverAtGoodyHutBaseChance")
    discover = f"Discovered at Tribal Villages ({chance}% chance)" if chance and chance != "0" else "Discovered while exploring"
    icon = m.icon_web("Society_FireStone")
    img = f'<img class="ico" src="{icon}" alt="">' if icon else '<div class="ico ico-blank">🔥</div>'
    body = f"""<h1>Secret Society — Fire &amp; Stone</h1>
<p class="lead">A Prehistoric-exclusive Secret Society. Requires the <strong>Secret Societies</strong> game mode.</p>
<div class="card" style="max-width:720px">
  <div class="card-head">{img}<div><h3>{name_of(s.get('Name'), m.loc)}</h3><div class="sub">{discover}</div></div></div>
  <div class="desc">{render_text(s.get('Description'), m.loc)}</div>
  {f'<blockquote>{render_inline(s.get("MembershipText"), m.loc)}</blockquote>' if s.get('MembershipText') else ''}
</div>
<h2>Titles</h2>
<p class="lead">As you earn Governor Titles and advance through the eras, you unlock these tiers — each granting new powers (the Athanor building, Emberwright unit, and the Star-Quickening project).</p>
{html_table(['Title', 'Unlocked by', 'Effect'], rows)}"""
    return page("Secret Society", "society.html", body)


def build_governments_page(m):
    govs = [g for g in m.rows("Governments") if "_PR_" in (g.get("GovernmentType") or "")]
    slots = {}
    for r in m.rows("Government_SlotCounts"):
        slots.setdefault(r["GovernmentType"], []).append((r.get("GovernmentSlotType"), int(r.get("NumSlots") or 0)))
    cards = []
    for g in govs:
        gt = g["GovernmentType"]
        badges = ""
        for st, n in slots.get(gt, []):
            info = SLOT_INFO.get(st, ("Policy", "slot-wildcard", "•"))
            badges += f'<span class="slot {info[1]}">{info[2]} {n}× {info[0]}</span> '
        icon = m.icon_web(gt)
        img = f'<img class="ico" src="{icon}" alt="">' if icon else '<div class="ico ico-blank">🏛️</div>'
        inh = render_inline(g.get("InherentBonusDesc"), m.loc)
        acc = render_inline(g.get("AccumulatedBonusShortDesc"), m.loc)
        avail = ("Available from the start — the Prehistoric era's starting government"
                 if gt.endswith("_FORAGER")
                 else "Available from the start (Tier-0 alternative)")
        cards.append(f"""<div class="card" id="{gt}">
  <div class="card-head">{img}<div><h3>{name_of(g.get('Name'), m.loc)}</h3><div class="sub">Tier 0 Government</div></div></div>
  <div class="gov-slots">{badges}</div>
  <div class="mod-row"><span class="mod-k">Availability</span> {avail}</div>
  <div class="mod-row"><span class="mod-k">Bonus</span> {inh}</div>
  <div class="mod-row"><span class="mod-k">Legacy bonus</span> {acc}</div>
</div>""")
    body = f"""<h1>Governments</h1>
<p class="lead">{len(govs)} Prehistoric Tier-0 governments — the earliest forms of organization, each with its own policy slots and bonus.</p>
<p class="note">ℹ️ Unlike policy cards, these have <strong>no civic prerequisite</strong>. <strong>Sharing Community</strong> is the era's <strong>starting government</strong> (it replaces the base Chiefdom), and both are available from the outset. To lock in a government's <em>Legacy bonus</em> you build its Tier-0 <a href="buildings.html">Government Plaza building</a> (Council House, Muster Square, Tribute Warehouse) in the Government District — which the base-game <em>State Workforce</em> civic unlocks.</p>
{card_grid(cards)}"""
    return page("Governments", "governments.html", body)


def build_index(m):
    counts = {
        "Technologies": len(m.rows("Technologies")),
        "Civics": len(m.rows("Civics")),
        "Policies": len([r for r in m.rows("Policies") if "_PR_" in (r.get("PolicyType") or "")]),
        "Pantheons": len([b for b in m.rows("Beliefs") if b.get("BeliefClassType") == "BELIEF_CLASS_PANTHEON" and "_PR_" in (b.get("BeliefType") or "")]),
        "Units": len([r for r in m.rows("Units") if "_PR_" in (r.get("UnitType") or "")]),
        "Buildings": len([r for r in m.rows("Buildings") if "_PR_" in (r.get("BuildingType") or "") and not r.get("IsWonder")]),
        "Wonders": len([r for r in m.rows("Buildings") if "_PR_" in (r.get("BuildingType") or "") and r.get("IsWonder")]),
        "Improvements": len([r for r in m.rows("Improvements") if "_PR_" in (r.get("ImprovementType") or "")]),
        "Myths": len(load_myth_ids()),
        "Governments": len([g for g in m.rows("Governments") if "_PR_" in (g.get("GovernmentType") or "")]),
        "Governor": len([g for g in m.rows("Governors") if g.get("GovernorType") == "GOVERNOR_PR_SHAMAN"]),
        "Society": len([x for x in m.rows("SecretSocieties") if "_PR_" in (x.get("SecretSocietyType") or "")]),
    }
    era_desc = render_text("LOC_ERA_PREHISTORIC_DESCRIPTION", m.loc)
    cards = []
    for href, label in NAV[1:]:
        n = counts.get(label, "")
        cards.append(f'<a class="nav-card" href="{href}"><span class="nc-count">{n}</span><span class="nc-label">{label}</span></a>')

    body = f"""<section class="hero">
  <h1>Prehistoric Era</h1>
  <p class="tagline">A new starting era for Civilization VI — begin in the Stone Age, before the Ancient era.</p>
  <div class="era-desc">{era_desc}</div>
</section>
<section class="credit" role="note">
  <h2>Credit &amp; disclaimer</h2>
  <p><strong>Prehistoric Era</strong> is created by <strong>{html.escape(MOD_AUTHOR)}</strong>. Every technology,
  civic, unit, building, wonder, improvement and policy documented on this site — along with all of the mod's
  design and artwork — is entirely their work. Sincere thanks to {html.escape(MOD_AUTHOR)} for making it.</p>
  <p>Please support the mod on the Steam Workshop:
  <a href="{MOD_URL}" target="_blank" rel="noopener">Prehistoric Era by {html.escape(MOD_AUTHOR)} ↗</a></p>
  <p class="unaffiliated">This is an <strong>unofficial, fan-made reference</strong>. It is not affiliated with,
  endorsed by, or maintained by {html.escape(MOD_AUTHOR)}. It is generated automatically from the mod's data files
  purely as a convenience for players.</p>
</section>
<section class="nav-cards">{"".join(cards)}</section>
<section class="about">
  <h2>About this reference</h2>
  <p>This site is generated directly from the mod's own data files (<code>Data/*.sql</code>, <code>Text/*.xml</code>, <code>Icons/</code>), so it always matches the installed mod version shown in the header. To refresh it after a mod update, re-run the generator: <code>python tools/docgen/generate.py</code>. See <code>tools/docgen/README.md</code> for details.</p>
</section>"""
    return page("Overview", "index.html", body)


# --------------------------------------------------------------------------
# CSS
# --------------------------------------------------------------------------

CSS = """
:root{
  --bg:#15120e; --bg2:#1e1a14; --panel:#26211a; --panel2:#2e2820;
  --ink:#efe6d6; --muted:#b3a992; --line:#3a3226; --accent:#d98a3d; --accent2:#e0b862;
  --edge:#6b5b3e; --chip:#3a3226;
}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--ink);
  font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;}
a{color:var(--accent2);text-decoration:none}
a:hover{text-decoration:underline}
main{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
h1{font-size:2rem;margin:.2em 0 .3em}
h2{margin:1.6em 0 .6em;border-bottom:1px solid var(--line);padding-bottom:.25em;color:var(--accent2)}
h3{margin:0;font-size:1.08rem}
.lead{color:var(--muted);max-width:74ch;margin:0 0 1.4em}
code{background:var(--panel);padding:.1em .4em;border-radius:4px;font-size:.9em}

.site-header{position:sticky;top:0;z-index:10;display:flex;align-items:center;gap:24px;
  padding:12px 20px;background:linear-gradient(#1e1a14,#15120e);border-bottom:1px solid var(--line);
  box-shadow:0 2px 12px #0006}
.brand a{font-weight:700;color:var(--ink);font-size:1.15rem}
.brand .ver{margin-left:8px;font-size:.7rem;color:var(--muted);border:1px solid var(--line);
  padding:1px 6px;border-radius:10px;vertical-align:middle}
.site-header nav{display:flex;gap:4px;flex-wrap:wrap}
.site-header nav a{padding:6px 12px;border-radius:6px;color:var(--muted);font-size:.92rem}
.site-header nav a:hover{background:var(--panel);text-decoration:none;color:var(--ink)}
.site-header nav a.active{background:var(--accent);color:#1a140c;font-weight:600}

.site-footer{max-width:1180px;margin:0 auto;padding:24px 20px;color:var(--muted);
  font-size:.82rem;border-top:1px solid var(--line);display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}

.hero{text-align:center;padding:40px 10px 10px}
.hero h1{font-size:2.8rem;margin:0}
.tagline{color:var(--accent2);font-size:1.15rem;margin:.3em 0 1.4em}
.era-desc{max-width:66ch;margin:0 auto;color:var(--muted);text-align:left;
  background:var(--panel);border:1px solid var(--line);border-left:3px solid var(--accent);
  padding:14px 20px;border-radius:8px}
.era-desc p{margin:.4em 0}
.credit{margin:26px 0 6px;background:linear-gradient(180deg,#2a2015,#211b13);
  border:1px solid var(--accent);border-radius:12px;padding:18px 22px;box-shadow:0 2px 16px #0005}
.credit h2{margin:0 0 .4em;border:0;padding:0;color:var(--accent);font-size:1.15rem}
.credit p{margin:.5em 0;color:var(--ink)}
.credit a{font-weight:600}
.credit .unaffiliated{color:var(--muted);font-size:.9rem;border-top:1px solid var(--line);padding-top:.7em;margin-top:.7em}
.nav-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin:34px 0}
.nav-card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:22px;
  text-align:center;transition:transform .1s,border-color .1s}
.nav-card:hover{transform:translateY(-3px);border-color:var(--accent);text-decoration:none}
.nc-count{display:block;font-size:2.2rem;font-weight:700;color:var(--accent2)}
.nc-label{color:var(--ink)}
.about{color:var(--muted);max-width:74ch}

.tree-wrap{overflow-x:auto;background:var(--bg2);border:1px solid var(--line);border-radius:10px;padding:8px}
svg.tree{min-width:760px;height:auto}
svg.tree .edge{fill:none;stroke:var(--edge);stroke-width:2}
svg.tree .gate{stroke:var(--accent);stroke-width:1.5;stroke-dasharray:3 3}
svg.tree .gate-label{fill:var(--muted);font-size:11px;font-style:italic}
svg.tree .node rect{fill:var(--panel2);stroke:var(--line);stroke-width:1.5}
svg.tree .node:hover rect{stroke:var(--accent)}
svg.tree .node-title{fill:var(--ink);font-size:14px;font-weight:600}
svg.tree .node-meta{fill:var(--muted);font-size:11px}

.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px;margin-top:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px;scroll-margin-top:70px}
.card-head{display:flex;gap:12px;align-items:center;margin-bottom:8px}
.card .ico{width:52px;height:52px;border-radius:8px;background:var(--bg2);object-fit:contain;flex:0 0 auto}
.card .ico-blank{display:flex;align-items:center;justify-content:center;font-size:1.5rem;border:1px solid var(--line)}
.card .sub{color:var(--muted);font-size:.82rem;margin-top:2px}
.desc{color:#ddd2bd;font-size:.94rem}
.desc p{margin:.45em 0}
blockquote{border-left:3px solid var(--accent);margin:.6em 0 0;padding:.2em 0 .2em 12px;
  color:var(--muted);font-style:italic;font-size:.9rem}
.effects{margin:.5em 0}
.eff-head{display:block;font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:2px}
.effects p{margin:.25em 0;font-size:.92rem;color:#ddd2bd}
.eureka{background:var(--bg2);border-left:3px solid var(--accent2);border-radius:6px;
  padding:6px 10px;margin:.5em 0;font-size:.9rem;color:#e7d9bd}
.eu-tag{color:var(--accent2);font-weight:600;white-space:nowrap}

.yields{display:flex;flex-wrap:wrap;gap:6px;margin:.4em 0}
.yield{background:var(--chip);border-radius:6px;padding:3px 8px;font-size:.85rem;font-weight:600}
.yield .ylabel{color:var(--muted);font-weight:400;margin-left:3px;font-size:.8em}
.chip{cursor:help}
.chip-unknown{background:var(--chip);border-radius:4px;padding:0 5px;font-size:.78rem;color:var(--muted)}

.unlocks{margin-top:.5em;display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.ul-head{font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted)}
.ul{display:inline-flex;align-items:center;gap:4px;background:var(--bg2);border:1px solid var(--line);
  border-radius:14px;padding:2px 9px 2px 3px;font-size:.82rem}
.ul img{width:20px;height:20px;border-radius:50%}
.ul-unit{border-color:#5a7a9a}
.ul-building{border-color:#9a7a5a}
.ul-improvement{border-color:#6a9a6a}
.ul-policy{border-color:#9a7ac0;color:var(--ink)}
a.ul-policy:hover{background:var(--panel);text-decoration:none;border-color:var(--accent)}
.ul-regated{border-style:dashed}
.ul-base{margin-left:5px;font-size:.62rem;text-transform:uppercase;letter-spacing:.04em;
  color:var(--muted);border:1px solid var(--line);border-radius:6px;padding:0 4px}

/* policies */
.pol-group{margin-top:1.6em}
.pol-group > h2{margin-bottom:.2em}
.pol-group .civic-tag{font-size:.85rem;color:var(--muted);font-weight:400}
.slot{display:inline-block;font-size:.72rem;font-weight:700;text-transform:uppercase;
  letter-spacing:.04em;padding:2px 8px;border-radius:12px;color:#1a140c}
.slot-military{background:#c9636a}
.slot-economic{background:#d9a441}
.slot-diplomatic{background:#5aa06e}
.slot-wildcard{background:#9a7ac0}
.slot-great{background:#c08a5a}
.journey{margin:.5em 0;font-size:.9rem;color:#ddd2bd}
.journey .eff-head{color:var(--accent2)}
.card.myth blockquote{margin-top:.7em}
.note{max-width:74ch;background:var(--bg2);border-left:3px solid var(--accent2);
  border-radius:6px;padding:8px 14px;color:var(--muted);font-size:.9rem;margin:0 0 1.2em}
.tbl-wrap{overflow-x:auto;margin-top:14px}
table.tbl{border-collapse:collapse;width:100%;min-width:640px;background:var(--panel);
  border:1px solid var(--line);border-radius:10px;overflow:hidden}
table.tbl th{text-align:left;padding:10px 14px;background:var(--panel2);color:var(--accent2);
  font-size:.8rem;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--line)}
table.tbl td{padding:10px 14px;border-bottom:1px solid var(--line);vertical-align:top;font-size:.92rem;color:#ddd2bd}
table.tbl tr:last-child td{border-bottom:0}
table.tbl td p{margin:.2em 0}
.tbl-title{color:var(--accent);font-weight:600;white-space:nowrap}
.gov-slots{margin:.5em 0;display:flex;flex-wrap:wrap;gap:6px}
.mod-row{font-size:.9rem;margin:.2em 0;color:#ddd2bd}
.mod-k{color:var(--muted);font-size:.8rem;text-transform:uppercase;letter-spacing:.03em;margin-right:4px}
.expires{margin-top:.5em;font-size:.85rem;color:var(--muted)}
.expires b{color:#e0b0a0;font-weight:600}
.expires.perm b{color:var(--accent2)}
"""


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def copy_icons(m):
    dst = os.path.join(OUT, "assets", "icons")
    os.makedirs(dst, exist_ok=True)
    seen = set()
    for _, path in m.icons.items():
        base = os.path.basename(path)
        if base in seen:
            continue
        seen.add(base)
        shutil.copy2(path, os.path.join(dst, base))
    return len(seen)


def write(name, content):
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as fh:
        fh.write(content)


def main():
    print("Prehistoric Era — documentation generator")
    print(f"  mod source : {ROOT}")
    print(f"  output     : {OUT}")
    if not os.path.isdir(os.path.join(ROOT, "Data")):
        sys.exit(
            f"\nERROR: could not find the mod's Data/ folder under:\n  {ROOT}\n"
            "Point the generator at your local Prehistoric Era install, e.g.:\n"
            '  python generate.py --mod "C:/path/to/PrehistoricEra"\n'
            "or set the PR_MOD_DIR environment variable."
        )
    m = Model()
    os.makedirs(os.path.join(OUT, "assets"), exist_ok=True)
    n_icons = copy_icons(m)
    write(os.path.join("assets", "style.css"), CSS)

    pages = {
        "index.html": build_index(m),
        "tech-tree.html": build_tech_page(m),
        "civics.html": build_civics_page(m),
        "policies.html": build_policies_page(m),
        "pantheons.html": build_pantheons_page(m),
        "units.html": build_units_page(m),
        "buildings.html": build_buildings_page(m),
        "wonders.html": build_wonders_page(m),
        "improvements.html": build_improvements_page(m),
        "myths.html": build_myths_page(m),
        "governments.html": build_governments_page(m),
        "governor.html": build_governor_page(m),
        "society.html": build_society_page(m),
    }
    for name, content in pages.items():
        write(name, content)
        print(f"  wrote {name}")
    print(f"  copied {n_icons} icons")
    print(f"Done -> {OUT}")


if __name__ == "__main__":
    main()
