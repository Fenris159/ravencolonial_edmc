# Changelog

All notable changes to the Ravencolonial EDMC plugin are documented in this file.

Release titles and dates are aligned with [GitHub Releases](https://github.com/Fenris159/ravencolonial_edmc/releases) when published there (using each release’s publish date in UTC, `YYYY-MM-DD`). Older entries may reference releases from the upstream fork history.

## [Unreleased]

### Changed

- **License** — project relicensed under **MIT**; added root **`LICENSE`** file, **`pyproject.toml`** `license` metadata, and **`README`** badge + wording (EDMC remains under its own upstream license).
- **README** — reorganized badges (CI / security / release / license; community; runtime & downloads).

## [1.6.1] - 2026-05-01

### Added

- **Commander ship snapshot** — `POST /api/cmdr/currentShip` (SrvSurvey-compatible body: commander, ship name/type, `maxCargo`, normalized `cargo` map), authenticated with **`rcc-key`** only. Driven from journal **`Cargo`**, **`Loadout`** (main ship), and **`SetUserShipName`**, with EDMC **`state`** for `CargoCapacity` / ship identity; deduplicated queue to the background API worker.
- **Stealth: commander ship cargo** — config **`ravencolonial_stealth_ship_cargo`**: when enabled, skips publishing the commander ship snapshot (independent of Fleet Carrier stealth).
- **Stealth: all construction delivery reporting** — config **`ravencolonial_stealth_construction_reporting`**: when enabled, skips **`ColonisationConstructionDepot`**, **`ColonisationContribution`**, and **`CargoDepot`** journal paths that update Ravencolonial (Create Project from the dialog is unchanged).
- **Plugin UI localization** — all user-facing strings go through EDMC **`l10n`** (`**i18n.py**` + **`tr` / `trf`**). **`L10n/en.template`** defines English keys; **`L10n/*.strings`** cover the same locale set as core EDMC (machine-translated for most languages; **`uwu`** mirrors English; **`sr-Latn`*** use a Latin-script placeholder with a header note). Maintainer regen: **`scripts/generate_plugin_l10n.py`** (`deep-translator`; **`--resume`**, **`--only`**).
- **Show API Key** — Ravencolonial settings tab checkbox (default off) toggles the API key field between masked and visible entry.
- **`scripts/clean_build_artifacts.py`** — remove **`dist/`**, **`__pycache__/`**, egg metadata, and setuptools outputs under **`build/`** while **preserving `build/release/`** (release zips). Optional **`--include-stray-root-zips`** only affects legacy zips in the repo root.

### Removed

- **Dock-to-dock CSV logger** (`**d2d_logger.py**`) — local `**~/Documents/d2dTimes.csv**` timing log removed; no API or website impact.

### Changed

- **Fleet Carrier stealth** — **`ravencolonial_stealth_mode`** now applies **only** to Fleet Carrier commodity/CAPI sync (no longer gates colonization depot/contribution journal handling).
- **Settings UI** — three separate checkboxes and help strings for FC stealth, ship-cargo stealth, and construction-reporting stealth; grid layout adjusted for the extra row.
- **Documentation** — README rewritten for current features, repo (**Fenris159/ravencolonial_edmc**), releases link, configuration, and troubleshooting; [docs/MANUAL_UPDATE_INSTRUCTIONS.md](docs/MANUAL_UPDATE_INSTRUCTIONS.md) generalized as a fallback when auto-update fails; [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) updated for current release practice; [docs/AUTO_UPDATE_FEATURE.md](docs/AUTO_UPDATE_FEATURE.md) aligned with this repo; legacy per-beta release notes stub removed in favor of the changelog and GitHub releases.
- **Documentation layout** — all supplementary Markdown (manual update, auto-update, release checklist, logging guide, API reference) moved under **`docs/`** with [docs/README.md](docs/README.md) as the index; **`make_release.py`** bundles the **`docs/`** tree into the release zip so manual installs include the same docs as the repo.
- **README** — documents **`L10n/`** behavior (follows EDMC display language), machine-translation caveats, and the **`generate_plugin_l10n.py`** workflow.
- **`make_release.py`** — always resolves the repo from the script path (not the process cwd); writes **`build/release/RavenColonial_EDMC-v{version}.zip`**; documents the output layout in README / maintainer docs.
- **Create Project error text** — EDMC log path hint is **OS-specific** (Windows / macOS / Linux) via **`{log_path}`** in **`L10n/*`** and **`edmc_log_path_hint()`** in **`plugin_config/settings.py`**, replacing a Windows-only **`%TEMP%`** string.
- **Markdownlint** — **`.markdownlint.json`** and **`.markdownlint-cli2.jsonc`** relax noisy rules for tables/changelog and ignore vendored trees when linting broad globs.

### Fixed

- **Auto-update ZIP install** — validate archive member paths before **`extractall`** to block path traversal (**Zip Slip**) from a malicious zip.
- **`get_market_data()`** (`**load.py**`) — open market JSON with **`encoding="utf-8"`** for consistent decoding across platforms.

### Notes

- Publish **`v1.6.1`** on GitHub with a **`RavenColonial_EDMC-v1.6.1.zip`** release asset so in-app auto-update can resolve the build.

## [1.6.0] - 2026-05-01

### Added

- Package **`__init__.py`** at the plugin root so EDMC can load `load` as a subpackage and relative imports resolve reliably.
- Module-level **`VERSION`** (mirrors `plugin_version`) for EDMC `plug.get_version()` / Plugin Browser.
- **`_notify_plugin_status_main_thread()`** in `load.py` so background threads can refresh status without calling **`plug.show_error`** for non-errors (avoids the “error” sound and status misuse).
- **`normalize_commodity_key`** / **`_normalize_cargo_map`** in `api/client.py` (and use from journal, FC handler, CAPI FC path, and create dialog) so **`Cargo`** payloads match Ravencolonial’s lowercase commodity keys.
- **`_elite_journal_dir()`**, journal timestamp helpers, **`refresh_construction_depot_from_journal()`**, and a per-line copy of EDMC’s **`state`** in **`_last_edmc_state`** for resolving system address and depot snapshots when the journal is slightly behind UI actions.

### Changed

- **Maintainers / repository**: Primary development, issues, and GitHub **Releases** (including auto-update checks) are now **[Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Earlier releases and code history remain attributable to upstream contributors (notably toemaus313 / CMDR Dirk Pitt13 and the original EDMC-RavenColonial lineage).
- **Auto-update source**: `version_check` uses a single **`GITHUB_REPO`** constant (`Fenris159/ravencolonial_edmc`); `load.py` prefs GitHub link and “latest” version check use the same value.
- **HTTP / EDMC alignment**: API client, GitHub version checks, and update downloads use EDMC **`timeout_session.new_session()`**; **`PluginConfig.get_user_agent()`** prefixes EDMC’s **`config.user_agent`** with a Ravencolonial plugin suffix (per PLUGINS.md).
- **Imports**: switched to **relative imports** across the plugin (`load.py`, subpackages, `create_project_dialog` / `version_check` where applicable) to avoid clashing with other plugins’ top-level module names.
- **Settings persistence**: **`prefs_changed`** now persists the same fields as “Save Settings” when the user dismisses EDMC Settings with OK, matching PLUGINS.md (widgets were previously easy to lose if OK was pressed without the in-tab Save).
- **Configurable API base URL**: **`ravencolonial_api_url`** is read with supported **`config.get_str()`** (removed invalid **`appname_config`** usage that always fell back to the default base URL).
- **Update UX**: startup and manual auto-update **success** paths use logging + main-thread status updates instead of **`plug.show_error`**; failures still use **`plug.show_error`**.
- **Release zip layout** (`make_release.py`): artifact folder / prefix **`RavenColonial_EDMC`** and filename **`RavenColonial_EDMC-v{version}.zip`**; **all root `*.py`** except `make_release.py` are bundled automatically so runtime modules cannot be omitted from the zip by mistake.
- **Ravencolonial HTTP client** (`api/client.py`): FC cargo uses **`rcc-key` only** (matches [SrvSurvey](https://github.com/njthomson/SrvSurvey)); **lowercase** `/api/system`, `/api/cmdr`, `/api/fc` paths; **`buildId`** path segments **URL-encoded** on contribute and project supply POSTs; **`create_project`** uses **debug/info** logging for normal traffic (errors only on HTTP failure / exceptions); duplicate **`logger.error`** pairs on several failure paths consolidated.
- **Version compare**: removed duplicate **`compare_versions`** from `load.py`; prefs “check for updates” uses **`version_check.compare_versions(..., logger)`** so behavior matches auto-update (including prerelease vs stable when versions tie).
- **`get_system_sites`**: optional **`name_or_num`** (system name or id64); when omitted, still resolves **`current_system_address`** via journal/state. **`get_system_bodies`** / **`get_system_architect`** and v2 **`nameOrNum`** URLs use the same escaped segment rules as SrvSurvey.
- **`get_system_address_from_journal`**: prefers EDMC **`state`’s** `SystemAddress`; journal fallback scans recent files for the **latest** **`Docked`** or **`Location`** with **`Docked: true`** by **timestamp** (not only the first reversed hit in one file).
- **Create Project flow**: before **`PUT /api/project`**, calls **`refresh_construction_depot_from_journal()`** (latest **`ColonisationConstructionDepot`**, preferring **`MarketID`** when known); **blocks** create if depot snapshot or **required commodity** list would be empty, with clear “wait / re-dock” errors instead of sending an empty commodity map.
- **Main-window create button**: disabled label **`Waiting for Dock`**; enabled-to-create label **`🚧Create Build Project`** (existing-project branch unchanged: **Open Build Page**).

### Removed

- Unused **`plugin_app_prefs_cmdr`** entry point (not invoked by current EDMC `plug.py`).
- **TESTING bypass** in `ui/manager.py` that could force-enable the Create Project button.
- **`rcc-cmdr`** header on FC **`/api/fc/.../cargo`** requests (server contract matches SrvSurvey: **`rcc-key`** only).
- Unused **`models`** imports from **`load.py`** (project still uses plain dicts from the API).

### Fixed

- **Update notification banner**: `UIManager` resolves **`CURRENT_VERSION`** via **`from ..version_check import CURRENT_VERSION`** so it works when the plugin is loaded as a package.
- **Accidental duplicate** `get_system_address_from_journal` method on **`RavencolonialPlugin`** (second definition overwrote the first; removed the dead copy and invalid **`exc_info=e`** logging).

### Documentation

- This changelog’s **1.5.x and earlier** sections were reconciled with historical **GitHub release titles/dates**; README / support / auto-update docs updated for the **Fenris159** fork and **RavenColonial_EDMC** zip naming.

### Notes

- For that release line, publish a **`RavenColonial_EDMC-v1.6.0.zip`** asset on GitHub so auto-update can resolve the build (see newer **1.6.1** notes for the current artifact name).

## [1.5.8] - 2025-11-07

### Added

- Dock-to-dock time logging for construction / carrier workflows (release: *Added dock to dock time log*).

## [1.5.7] - 2025-11-06

### Fixed

- Fleet Carrier quantity handling and related UI layout (release: *FC quantity bug fix, UI arrangement*).

## [1.5.6] - 2025-11-05

### Changed

- Auto-update verification, formatting, and construction-completion behavior (release: *Autoupdate test, formatting and completion enhancements*).

## [1.5.5] - 2025-11-05

### Added

- Plugin auto-update support (release: *Auto-update implementation*).

### Changed

- Filter completed / in-build sites out of the system site list; cleaner station names in the create-project flow; primary-port checkbox removed from the dialog (same train as `1.5.5-beta1`, shipped as stable).

## [1.5.5-beta1] - 2025-11-05

Pre-release tag `1.5.5-beta1` on GitHub.

### Changed

- Beta pass on project creation and pre-planned site list (release: *(beta) fine tuning project creation and pre-planned list*).

## [1.5.3] - 2025-11-02

### Fixed

- Construction completion handling (release: *Fix for completion*).

### Added

- Plugin version display and GitHub link on the settings page (from release notes on GitHub).

## [1.5.2] - 2025-11-02

### Fixed

- System body list not populating when pre-planned site filtering was applied incorrectly (release: *Fix for bodies not populating*).

## [1.5.1] - 2025-11-01

### Added

- Fleet Carrier commodity tracking (transfers, buy/sell); requires a Ravencolonial API key in plugin settings.
- Optional sync of FC stock from Frontier CAPI when fleet-carrier CAPI is enabled in EDMC.
- **Stealth mode**: setting to stop sending Fleet Carrier commodity updates to Ravencolonial (release: *Add Fleetcarrier support*).

## [1.4.1] - 2025-11-01

### Fixed

- Create Project body menu when the main star uses `bodyNum` 0 instead of 1 (release: *fix for missing main star when num=0*).

## [1.4.0] - 2025-10-31

### Changed

- Project creation and completion fixes (release: *Fixes to project creation and completion*).
- Refactored layout: dedicated API client, UI manager, journal handler, models, and centralized plugin config (monolithic `load.py` split into modules).

## [1.3.0] - 2025-10-30

First published GitHub asset `Ravencolonial-EDMC-v1.3.0.zip` (release *Initial Release* / `Latest` tag).

### Added

- **Localization (l10n)**: framework and English template (`L10n/en.template`); UI refreshes when EDMC language changes.
- **Async errors in the EDMC status bar** via `plug.show_error()` for API failures.
- **Thread lifecycle**: API worker thread is stopped and joined on plugin shutdown (per EDMC guidance).

### Changed

- Prefer typed config accessors (`config.get_str()`, etc.) over legacy `config.get()` where applicable.
- User-facing strings wired for translation.

### Removed

- Earlier experimental “no settings” flow superseded by configurable API key and related options in later 1.5.x releases.

### Fixed

- Worker thread teardown uses a bounded `join()` so EDMC can exit cleanly.

---

## Earlier milestones (pre-GitHub versioning)

The following versions were documented during early development before per-tag GitHub releases existed; they are kept for history and do not map 1:1 to a single release asset.

## [1.2.0] - 2025-10-29 (development)

### Added

- Construction-ship-only “Create Project” gating (SrvSurvey-style behavior).
- Pre-planned site selection when the system has existing planned sites.
- Full build-type list (28 types) grouped by tier.

### Changed

- Build-type menu structure aligned with SrvSurvey; dialog size 550×650; removed unused Faction field from the form.

### Fixed

- Project deep links use `https://ravencolonial.com/#build={buildId}`.

## [1.1.0] - 2025-10-29 (development)

### Added

- Create Project dialog and main-window control; journal enrichment (`StarPos`, `BodyID`, `Body`, `StationType`, `StationFaction`, dock state).
- Browser opens to the new project after successful creation.

### Changed

- Status row layout; clearer disabled/enabled button labels.

### Technical

- API: `get_system_sites()`, `create_project()`; URL encoding for commander names in API paths.

## [1.0.0] - 2025-10-29 (development)

### Added

- Initial colonization cargo tracking, Ravencolonial API integration, background API queue, and basic EDMC UI status.
