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
| `generate.py` | The generator: reads the mod's data files and writes the site. |
| `parse.py` | SQL / XML / icon extraction (standard library only). |
| `base_policies.json` | The one hand-maintained file: base-game policy → unlocking civic (wiki-verified). |
| `docs/` | **The generated website** — this is what GitHub Pages serves. |

The mod's own source files (`Data/`, `Text/`, `Icons/`, `Scripts/`) are **not**
included here — that would be redistributing the whole mod. The generator reads
them from your local copy of the mod when you rebuild.

## Rebuilding after a mod update

You need a local copy of the mod's files. Then:

```bash
# if a folder named PrehistoricEra sits next to this repo, just:
python generate.py

# otherwise point it at your install:
python generate.py --mod "C:/path/to/PrehistoricEra"
```

This regenerates everything under `docs/`. Commit and push, and the live site
updates:

```bash
git add docs
git commit -m "Rebuild docs for mod vNN"
git push
```

Requires only Python 3 (no third-party packages).

## Notes

- **`noindex`** — `NOINDEX = True` near the top of `generate.py` adds a
  `noindex` tag to every page, so the site is reachable by link but stays out of
  search results. Flip it to `False` to make it publicly discoverable, then
  rebuild.
- **The version badge** in the header is read automatically from the mod's
  `PrehistoricEra.modinfo`.
