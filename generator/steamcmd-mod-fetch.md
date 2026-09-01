# Automating the Prehistoric Era mod fetch (SteamCMD notes)

Goal: replace the manual "download the mod + drop a new `vNN\` folder into
`PrehistoricEra\`" step. Investigated 2026-09-01.

## Key facts
- Mod: **Prehistoric Era** by AKXTM, for **Sid Meier's Civilization VI**.
- Steam AppID: **289070**
- Workshop item (published file) ID: **3739196160**
  - https://steamcommunity.com/workshop/filedetails/?id=3739196160
- Version is machine-readable: `PrehistoricEra.modinfo` carries `version="NN"`
  (`<Mod id="..." version="27">`). The Workshop download is always *latest*, so
  detect the version from the modinfo rather than requesting a specific one.
- The Workshop download layout already matches what `generate.py` expects:
  `Data/ Text/ Icons/ Scripts/ PrehistoricEra.modinfo`.

## Anonymous SteamCMD: DOES NOT WORK (tested, confirmed)
Command tried:
```
steamcmd +login anonymous +workshop_download_item 289070 3739196160 +quit
```
Result:
```
Connecting anonymously to Steam Public...OK
Downloading item 3739196160 ...
Detected workshop change (latest from server): new manifest 3152219082730127232
No workshop depot defined, skipping non-legacy item 3739196160
Download item 3739196160 result : Failure
```
Anonymous login connects and can even read the item's latest **manifest**, but
Steam refuses the actual file bytes because the anonymous account holds no
**license** for Civ VI (289070). This is the standard gate on paid titles — no
flag works around it. The `content/289070/` folder is created but stays empty.

## What actually works — needs an account that OWNS Civ VI

### Option A (recommended): run the fetch on the Civ PC
That machine already owns the game, so there is zero auth friction.
1. Subscribe to the mod once in the Steam client. Steam auto-downloads/updates it to:
   `<Steam>\steamapps\workshop\content\289070\3739196160\`
2. A small script reads `version=` from that folder's `PrehistoricEra.modinfo`
   and copies the folder to `PrehistoricEra\vNN\` (into a synced/shared location).
Updates then land automatically whenever Steam runs. No SteamCMD, no login prompt.

### Option B: SteamCMD with your Steam account (on any machine)
```
steamcmd +login <your_steam_user> +workshop_download_item 289070 3739196160 +quit
```
- First run is interactive: enter your password + Steam Guard code **yourself**
  (do not let the assistant type credentials).
- SteamCMD caches the session token afterward, so later runs are unattended —
  until the token expires (typically weeks), then re-login once.
- Downloads to `steamcmd\steamapps\workshop\content\289070\3739196160\`.

## After fetching (either option) — the docs update workflow
1. Copy the downloaded mod folder to `PrehistoricEra\vNN\` (NN from the modinfo).
2. `cd prehistoric-era-docs && python generate.py` (auto-selects highest vNN).
3. Review the diff, then `git add -A && git commit && git push`.
4. Keep latest + previous version folders; delete older ones (~130-170 MB each).
