# Ravencolonial EDMC Plugin

[![CI](https://github.com/Fenris159/ravencolonial_edmc/actions/workflows/ci.yml/badge.svg)](https://github.com/Fenris159/ravencolonial_edmc/actions/workflows/ci.yml) [![Bandit](https://github.com/Fenris159/ravencolonial_edmc/actions/workflows/bandit.yml/badge.svg)](https://github.com/Fenris159/ravencolonial_edmc/actions/workflows/bandit.yml) [![GitHub release](https://img.shields.io/github/v/release/Fenris159/ravencolonial_edmc?style=flat&logo=github&label=release)](https://github.com/Fenris159/ravencolonial_edmc/releases/latest) [![License: MIT](https://img.shields.io/github/license/Fenris159/ravencolonial_edmc?style=flat&logo=github&label=license)](https://github.com/Fenris159/ravencolonial_edmc/blob/main/LICENSE)

[![GitHub stars](https://img.shields.io/github/stars/Fenris159/ravencolonial_edmc?style=flat&logo=github&label=stars)](https://github.com/Fenris159/ravencolonial_edmc/stargazers) [![GitHub issues](https://img.shields.io/github/issues/Fenris159/ravencolonial_edmc?style=flat&logo=github&label=issues)](https://github.com/Fenris159/ravencolonial_edmc/issues) [![Discord](https://img.shields.io/discord/1055035389791969352?style=flat&logo=discord&logoColor=white&label=Discord&color=5865F2)](https://discord.gg/BdSqrvkkBx)

[![Python](https://img.shields.io/badge/Python-3.13.9%20–%203.13.x-3776AB?logo=python&logoColor=white)](https://github.com/Fenris159/ravencolonial_edmc/blob/main/pyproject.toml) [![GitHub all releases](https://img.shields.io/github/downloads/Fenris159/ravencolonial_edmc/total?style=flat&logo=github&label=downloads&cacheSeconds=600)](https://github.com/Fenris159/ravencolonial_edmc/releases) [![Built for EDMC 6.1.2](https://img.shields.io/badge/Built%20for%20EDMC-6.1.2-181717?logo=github&logoColor=white)](https://github.com/EDCD/EDMarketConnector/releases/tag/Release%2F6.1.2)

An [Elite Dangerous Market Connector (EDMC)](https://github.com/EDCD/EDMarketConnector) plugin that tracks colonization activity and Fleet Carrier stock, and syncs with **[Ravencolonial](https://ravencolonial.com)**—similar goals to **[SrvSurvey](https://github.com/njthomson/SrvSurvey)** while running inside EDMC.

**Source, issues, and releases:** [github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)  
**Download the latest build:** [GitHub Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)  
**More documentation:** [docs/README.md](docs/README.md) (manual install, auto-update, release checklist, API reference, logging notes)

---

## Features

| Area                      | What the plugin does                                                                                                                                                                                        |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Colonization projects** | Reads `ColonisationConstructionDepot` / `ColonisationContribution` (and `CargoDepot` deliveries) to update project need and attributed contributions on Ravencolonial.                                      |
| **Create Project**        | In-game dialog (when docked at a construction ship) to submit a new project with build type, name, architect, bodies, pre-planned sites, notes, and optional Discord link—aligned with Ravencolonial’s API. |
| **Plan sites / Link Build Site** | If you’re the system architect, **Refresh** (↻) loads plan sites from Ravencolonial into the dropdown. **Link Build Site** connects the site you pick to where you’re docked and sends your commander as architect. Refresh problems open a small themed error window (with **Copy Error Msg**); the dropdown stays a short label so EDMC does not stretch. Extra checks before **Create** / **Link** and when resolving the dock slot reduce duplicate projects when server answers are messy. |
| **Fleet Carriers**        | Journal + CAPI paths update **linked** carrier cargo on Ravencolonial (`rcc-key` auth, same pattern as SrvSurvey)—**personal** fleet carriers and **squadron** fleet carriers (detected via journal `StationServices` / `squadronBank`, with SrvSurvey-style cargo handling when docked on a linked squadron FC). **Requires your Ravencolonial API key** in plugin settings. |
| **Commander ship**        | Optional `**POST /api/cmdr/currentShip`**-style sync: ship identity, max cargo, and hold contents from journal `Cargo` / `Loadout` / `SetUserShipName` (via EDMC `state`). **Requires API key.**            |
| **Privacy**               | Three independent **stealth** toggles (FC only, commander ship cargo only, construction journal reporting only).                                                                                            |
| **Updates**               | Optional GitHub release check, notification banner, and auto-install (see [docs/AUTO_UPDATE_FEATURE.md](docs/AUTO_UPDATE_FEATURE.md)).                                                                      |
| **Languages**             | When you run EDMC in another language (for example French or German), this plugin’s buttons and messages try to match. If a few words stay in English, restart EDMC after changing the language. |

---

## What this plugin does (journal-driven)

- Subscribes to EDMC’s `**journal_entry`** feed (same ordering and `**state**` as the core app—no separate journal tailing for normal operation).
- When you dock at a colonization construction ship, it can **refresh depot data** from the journal, **update project supply** totals, and **record contributions** to the active build.
- **Fleet Carrier** buy/sell/transfer and CAPI snapshots update Ravencolonial for carriers **linked to your commander** on the site (personal or squadron hulls); squadron carriers are recognized from the journal so cargo deltas apply correctly when you are on the carrier. **Requires an API key** for uploads.
- **Ship snapshot** updates Ravencolonial when your hold or loadout changes (unless ship-cargo stealth is on).

---

## Requirements

- **EDMC** 6.1.2 or newer ([releases](https://github.com/EDCD/EDMarketConnector/releases)).
- **Python** bundled with EDMC (currently **3.13.x**). For local dev/CI this repo targets `**requires-python >=3.13.9,<3.14`** in `[pyproject.toml](pyproject.toml)`; see also `[.python-version](.python-version)`.
- **Ravencolonial account** if you use an API key, create projects, or sync FC / ship data.

---

## Installation

1. Download `**RavenColonial_EDMC-v*.zip`** from the **[latest GitHub release](https://github.com/Fenris159/ravencolonial_edmc/releases)** (use the plugin asset, not a source archive, unless the release notes say otherwise).
2. Extract so you have a single folder named `**RavenColonial_EDMC`** containing `load.py` and the rest of the plugin.
3. Copy that folder into your EDMC **plugins** directory:

    - **Windows:** `%LOCALAPPDATA%\EDMarketConnector\plugins\`
    - **Linux:** `~/.local/share/EDMarketConnector/plugins/`
    - **macOS:** `~/Library/Application Support/EDMarketConnector/plugins/`

4. Restart EDMC. Enable the plugin under **File → Settings → Plugins** if needed.

**If in-app auto-update fails** (network, permissions, or GitHub), use **[docs/MANUAL_UPDATE_INSTRUCTIONS.md](docs/MANUAL_UPDATE_INSTRUCTIONS.md)** for a clean manual replace of the plugin folder.

Maintainers can build the same zip with **`make_release.py`** from anywhere (it writes **`build/release/RavenColonial_EDMC-v{version}.zip`** next to the repo; the zip contains a top-level **`RavenColonial_EDMC/`** folder), or use **GitHub Actions → Build release**: leave **Publish GitHub release** off to download only the artifact, or turn it on to create tag **`v*`** and a Release from **`load.py`** `plugin_version`; alternatively push tag **`v*`** that matches **`load.py`** to publish the same way.

To drop local **`__pycache__`**, **`dist/`**, egg-info metadata, and setuptools outputs under **`build/`** (such as **`build/lib/`**) without touching release artifacts, run **`python scripts/clean_build_artifacts.py`**. That script **always keeps `build/release/`** (including shipped zips). Optional **`--include-stray-root-zips`** only removes legacy **`RavenColonial_EDMC-v*.zip`** files sitting in the **repo root**, not under **`build/release/`**.

---

## Configuration (File → Settings → Ravencolonial tab)

### API key (`ravencolonial_api_key`)

- Get it from **Ravencolonial → account / user settings** (same key SrvSurvey uses as `rcc-key` for authenticated writes).
- **Required** for: Fleet Carrier cargo updates (personal or linked **squadron** carriers), commander **current ship** hold sync, and any server-side features that expect your account context.
- **Project creation** and many read/update flows still need the game + journal context; some calls work without a key depending on server policy—set the key for the full experience.

### Optional API base URL (`ravencolonial_api_url`)

- Advanced: override the default Ravencolonial API host (see `PluginConfig.DEFAULT_API_BASE` in `[plugin_config/settings.py](plugin_config/settings.py)`).

### Privacy — three stealth toggles

| Setting                                          | Config key                                     | When enabled                                                                                                                                                                                                                            |
| ------------------------------------------------ | ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Stealth: Fleet Carrier data**                  | `ravencolonial_stealth_mode`                   | No FC commodity journal handlers and no CAPI FC cargo uploads to Ravencolonial.                                                                                                                                                         |
| **Stealth: commander ship cargo**                | `ravencolonial_stealth_ship_cargo`             | No `**POST /api/cmdr/currentShip`** (hold / loadout snapshot).                                                                                                                                                                          |
| **Stealth: all construction delivery reporting** | `ravencolonial_stealth_construction_reporting` | No processing of `**ColonisationConstructionDepot`**, `**ColonisationContribution**`, or `**CargoDepot**` for Ravencolonial API updates from the journal. *(Create Project from the dialog is unchanged—it is a deliberate UI action.)* |

Click **Save Settings** (or OK on the main Settings dialog—prefs are persisted on dismiss).

### Update settings

- **Check for updates on startup** — queries [GitHub Releases](https://github.com/Fenris159/ravencolonial_edmc/releases) for a newer tag.
- **Automatically install updates** — downloads and swaps the plugin folder (EDMC restart required).
- **Include pre-release versions** — treat beta/rc tags as candidates when comparing versions.

Details: [docs/AUTO_UPDATE_FEATURE.md](docs/AUTO_UPDATE_FEATURE.md).

---

## Usage

1. Run **EDMC** while playing (or before launching the game).
2. **Dock** at colonization construction sites and deliver cargo as usual; watch the plugin status line for confirmations.
3. Open **[ravencolonial.com](https://ravencolonial.com)** for project progress and FC/ship data the server exposes.

### Create Project

When docked at a **construction site**, use **Create Build Project** (or open project link when a build already exists—labels depend on state):

1. Choose **build type** (full tiered list in the dialog).
2. **Project name**, **architect**, optional **pre-planned site**, **body**, **notes**, **Discord** link as needed.
3. **Create** submits **`PUT /api/project`** with journal-backed depot data when available. On success the main tab switches to **Open Build Page** when the server reports the new project at your dock.

### Plan sites and Link Build Site

When docked at a colonization construction ship, the plugin shows **Select Plan Site** above the main button row:

1. Tap **Refresh** (↻). Ravencolonial must recognize **you** as the architect for this system. If not, the row shows **Not Architect** and you can’t pick plan sites here. If refresh fails (network, HTTP error, or no commander context yet), a **themed popup** explains what went wrong; use **Copy Error Msg** to paste details into a bug report. The dropdown itself keeps a **short** status label so the window layout stays stable.
2. Choose a plan site from the list, or **Create New** to open the full project dialog instead.
3. **Link Build Site** tells Ravencolonial to connect the site you picked to **this dock** and station, using your commander name as architect. EDMC needs to know who you are (normal **LoadGame** / journal flow); if your name isn’t loaded yet, linking waits until it is.

#### Safety checks before Create / Link

These steps reduce accidental **duplicate** projects when the website and game state don’t quite line up:

- The plugin asks Ravencolonial whether a build **already exists** for this dock. It only trusts a clear “yes, here’s the project” answer (including common **`buildId`** spellings and wrapped JSON shapes). Vague “nothing active” messages are treated as **no** active link—not as proof the slot is free to reuse if something is still registered on the server.
- **Immediately before** opening **Create Build Project** or starting **Link Build Site**, it **re-checks** that dock slot on the network so a build that appeared while you were still docked is detected and the flow switches to **Open Build Page** instead.
- Right before sending the link, it **looks up your plan site again** on Ravencolonial. If that site is no longer in the planning stage (construction has started or finished), linking stops and you’ll see a message instead of creating a second project.

Technical details (which journal events call which URLs): **[docs/ACTION_MAP_API_FLOWS.md](docs/ACTION_MAP_API_FLOWS.md)**.

### Fleet Carriers

Link each carrier you care about (personal or **squadron** fleet carrier) on Ravencolonial under your commander profile so the server returns it in `/fc/all`. With an **API key** set, the plugin mirrors FC trades/transfers and optional CAPI cargo refresh; journal logic treats squadron carriers like SrvSurvey so transfers and resync behave correctly when `StationServices` includes **squadronBank**.

### Commander ship snapshot

With an **API key**, cargo and capacity updates (after `**Loadout`** provides capacity) are sent so Ravencolonial can show your current ship loadout context alongside colonization tools.

---

## Troubleshooting

- **RavenColonial-only log (bug reports):** the plugin writes a dedicated rotating log next to its install: **`plugins/<RavenColonial_EDMC folder>/logs/RavenColonial_EDMC.log`** (for example on Windows `%LOCALAPPDATA%\EDMarketConnector\plugins\RavenColonial_EDMC\logs\RavenColonial_EDMC.log`). It includes main plugin messages plus **API** and **fleet carrier** module lines (not mixed into EDMC’s global log). Attach the latest file when opening a GitHub issue (redact your API key if you pasted it into chat).
- **Plugin errors:** EDMC main log — on Windows typically `%TEMP%\EDMarketConnector\EDMarketConnector.log`; on Linux/macOS typically under `~/.local/share/EDMarketConnector/` or `~/Library/Application Support/EDMarketConnector/` (see EDMC docs if your install differs).
- **API / auth:** confirm API key and that stealth toggles match what you intend to upload.
- **Manual install:** [docs/MANUAL_UPDATE_INSTRUCTIONS.md](docs/MANUAL_UPDATE_INSTRUCTIONS.md).

---

## Credits

- **SrvSurvey** — reference colonization client by [grinning2001 / njthomson](https://github.com/njthomson/SrvSurvey).
- **Ravencolonial** — platform by [grinning2001](https://ravencolonial.com).
- **EDMC** — [EDCD](https://github.com/EDCD/EDMarketConnector).
- **This plugin** — maintained by **[Fenris159](https://github.com/Fenris159)**; builds on earlier community work (CMDR Dirk Pitt13 / toemaus313 and related forks).

---

## License

This project is licensed under the **[MIT License](LICENSE)**.

**EDMC** itself is distributed under **its own** terms (see the [EDMarketConnector](https://github.com/EDCD/EDMarketConnector) repository). This plugin’s MIT license applies to **this repository’s** code only.

---

## Support

- **Issues:** [github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)
- **EDMC plugins:** [EDMC Wiki — Plugins](https://github.com/EDCD/EDMarketConnector/wiki/Plugins)
- **Ravencolonial:** [ravencolonial.com](https://ravencolonial.com)

---

## Version history

See **[CHANGELOG.md](CHANGELOG.md)** for the full record.

| Version   | Summary                                                                                                        |
| --------- | -------------------------------------------------------------------------------------------------------------- |
| **1.6.5-dev** | **Development** (`development` / optional **`v1.6.5-dev`** tag): plan-site **themed error dialog** + short combobox labels; **click-time** re-**GET** before Create/Link; **negative freeze** + positive-only location cache for fewer bursty **`GET /api/system/...`** calls; **Open Build Page** / **`buildId`** via **`resolve_build_id`**; main tab refresh after successful **Create Project**; docked create-button logic split into resolve/apply; no client **`/sites`** merge for dock project lookup (changelog **Unreleased**). |
| **1.6.4** | Auto-update on Windows: release CAPI cache + issue log before folder replace (`WinError 32`); update banner **`v`** display; shorter error dialog text; status line wrap; **Select Plan Site** themed combobox (see changelog). |
| **1.6.3** | Link Build Site: **`architectName`** on **`PUT`**, **`/sites`** preflight, **`404`** completion hints; normalized **`/api/system/...`**; short-lived project GET cache; depot supply dedup; undock status shows station name; docs (see changelog). |
| **1.6.2** | CAPI snapshot cache (`capi_cache/`) for analysis; squadron fleet carrier journal tracking (SrvSurvey-style), MIT license, README refresh (see changelog). |
| **1.6.1** | Commander ship `currentShip` sync; three-way stealth (FC / ship cargo / construction reporting); UI in many languages (follows EDMC’s language); docs refresh. |
| **1.6.0** | Maintainer/repo handoff to **Fenris159/ravencolonial_edmc**, packaging and HTTP alignment, auto-update UX.     |

Older releases remain listed in the changelog.
