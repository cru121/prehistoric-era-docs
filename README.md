# Prehistoric Era — documentation site

An **unofficial, fan-made** reference for the Civilization VI mod
**[Prehistoric Era](https://steamcommunity.com/workshop/filedetails/?id=3739196160)** by **AKXTM**:
its technology tree, civics tree, policies, pantheons, origin myths, units,
buildings, wonders and tile improvements.

All mod content, design and artwork belong to AKXTM. This repository is not
affiliated with or endorsed by the author — it only holds a small generator and
the web pages it produces. Please subscribe to and support the mod on the
[Steam Workshop](https://steamcommunity.com/workshop/filedetails/?id=3739196160).

## Live site

Served by GitHub Pages from the [`docs/`](docs/) folder:

> **https://cru121.github.io/prehistoric-era-docs/**

## What's in here

| Path | What it is |
| --- | --- |
| `generator/generate.py` | The generator: reads the mod's data files and writes the site. |
| `generator/parse.py` | SQL / XML / icon extraction (standard library only). |
| `generator/backup_mod.py` | Snapshots the live mod into `backup/vNN/` (lean: no icons/art). |
| `generator/base_policies.json` | The one hand-maintained file: base-game policy → unlocking civic (wiki-verified). |
| `docs/` | **The generated website** — this is what GitHub Pages serves (from repo-root `/docs`). |
| `backup/` | Local, git-ignored archive of past mod versions — diff baselines only. |
| `update.bat` | Convenience: rebuild the docs, then snapshot the mod, in one go. |

The mod's own source files (`Data/`, `Text/`, `Icons/`, `Scripts/`) are **not**
committed — that would redistribute the whole mod. The generator reads them from
your local copy of the mod when you rebuild, and `backup/` is git-ignored for the
same reason.

## Rebuilding after a mod update

On a machine that owns Civ VI and is subscribed to the mod, everything is
automatic — the generator reads the **live Steam Workshop copy** directly:

```
…\steamapps\workshop\content\289070\3739196160\
```

So after Steam updates the mod, just run both steps (or double-click `update.bat`):

```bash
python generator/generate.py     # rebuild docs/ from the live mod
python generator/backup_mod.py   # snapshot the mod into backup/vNN/
```

The generator resolves its source in this order: `--mod "path"` → `PR_MOD_DIR`
env var → the live Steam Workshop copy → else the newest `backup/vNN/`. That last
fallback means it still works on a machine *without* the game — it builds from the
most recent local backup.

`backup_mod.py` copies only `Data/ Text/ Scripts/ PrehistoricEra.modinfo` (~10 MB,
no icons/art) into `backup/vNN/`. Its job is to leave a diff baseline so the *next*
mod update can be compared against the current one ("what changed since vNN") — the
generator itself only ever reads one version.

Then commit and push; the live site updates (GitHub Pages serves repo-root `/docs`):

```bash
git add docs && git commit -m "Rebuild docs for mod vNN" && git push
```

Requires only Python 3 (no third-party packages).

> Backups are tiny, so keeping several is fine; prune old `backup/vNN/` folders
> whenever you like. `backup/` is git-ignored and never leaves your machine.

## Notes

- **`noindex`** — the `NOINDEX` flag near the top of `generator/generate.py`
  (currently `False`, i.e. publicly discoverable) controls a `noindex` tag on
  every page. Set it to `True` to keep the site reachable by link but out of
  search results, then rebuild.
- **The version badge** in the header is read automatically from the mod's
  `PrehistoricEra.modinfo`.
- **Icons** are extracted at build time from the mod's own `.dds` art — both the
  loose single-icon files and the grid **texture atlases** (`Icons/*.xml` →
  `IconTextureAtlases` + `IconDefinitions`). The generator un-packs each atlas
  cell to a small PNG under `docs/assets/icons/`, using only the Python standard
  library (`zlib`/`struct`) — no image dependencies. Only icons the pages actually
  reference are emitted. Base-game icons the mod reuses (whose atlases aren't
  shipped with it) fall back to an emoji glyph.
