# Changelog

All notable changes to the Ravencolonial EDMC plugin are documented in this file.

Release titles and dates are aligned with [GitHub Releases](https://github.com/Fenris159/ravencolonial_edmc/releases) when published there (using each release’s publish date in UTC, `YYYY-MM-DD`). Older entries may reference releases from the upstream fork history.

## [Unreleased]

- Nothing yet.

## [1.8.2] - 2026-08-26

Stable release of the 1.8.2 tracker reliability work from **1.8.2-rc.1** through **1.8.2-rc.3**, plus a Create Project construction-type parity fix.

### Added

- **Reset and show Popout Tracker** - Plugin settings include a recovery button that activates popout mode, centers the tracker on the EDMC display, restores it from minimized/hidden state, and brings it to the foreground.
- **Dodec Starport in Create Project** - Construction Type now includes **Tier 3: Dodec Starport** with models **Dodec**, **Quint truss**, and **Dec truss** (`dodec`, `quint_truss`, `dec_truss`), matching SrvSurvey `colonization-costs2.json` layouts so Dodec plan sites can be selected when creating a project.

### Fixed

- **Off-screen Popout Tracker recovery** - Saved tracker positions are validated against every connected monitor's usable work area. Positions stranded by monitor removal, resolution/DPI changes, or window rearrangement are centered on the display containing EDMC.
- **Minimized position persistence** - Minimized and unreachable off-screen sentinel coordinates are no longer saved during shutdown, while valid positions on secondary monitors remain intact.
- **Taskbar visibility fallback** - If Windows taskbar promotion fails after temporarily hiding the tracker, the window is immediately restored instead of remaining withdrawn.
- **Build tracker project switching** - The newest project or Track All selection supersedes an older in-flight fetch, so rapid combobox changes cannot leave the popout empty or showing a stale project's demand list.
- **Selected-project demand source** - Overlay and popout demand rows always come from the selected project's cache. A docked construction depot updates only its matching build id and no longer overrides a different selection.
- **Scoped depot cache writes** - Journal snapshots, successful depot PATCH responses, and completion events update the matching by-build-id entry; the selected single-project cache changes only when that build is selected, while Track All is rebuilt from the by-id cache.
- **Track All in popout-only mode** - Track All builds its aggregate in the shared project-cache layer instead of requiring a Modern Overlay renderer, so the popout receives the combined needs even when the in-game overlay is unavailable or inactive.

### Changed

- **Depot cache implementation** - Shared cache-update logic is implemented directly in the normal journal, completion, and API PATCH paths; the temporary runtime method replacement is no longer needed.

### Tests

- Full local suite: **225 passed, 1 skipped**. Regression coverage includes off-screen window recovery, absolute negative monitor coordinates, minimized-state persistence, rapid project switching, project-to-Track-All switching, popout-only aggregation, selected-cache isolation, matching depot updates, completion filtering, and cache-driven demand rendering.

## [1.8.2-rc.3] - 2026-07-31

### Fixed

- **Off-screen Popout Tracker recovery** - Saved tracker positions are validated against every connected monitor's usable work area. Positions stranded by monitor removal, resolution/DPI changes, or window rearrangement are centered on the display containing EDMC.
- **Minimized position persistence** - Minimized and unreachable off-screen sentinel coordinates are no longer saved during shutdown, while valid positions on secondary monitors remain intact.
- **Taskbar visibility fallback** - If Windows taskbar promotion fails after temporarily hiding the tracker, the window is immediately restored instead of remaining withdrawn.

### Added

- **Reset and show Popout Tracker** - Plugin settings now include a recovery button that activates popout mode, centers the tracker on the EDMC display, restores it from minimized/hidden state, and brings it to the foreground.

### Tests

- Added regression coverage for absolute negative monitor coordinates, connected-monitor title-bar visibility, EDMC-monitor centering, off-screen sentinel recovery, minimized-state persistence, and settings recovery wiring.

## [1.8.2-rc.2] - 2026-07-27

### Fixed

- **Track All in popout-only mode** - Track All now builds its aggregate in the shared project-cache layer instead of requiring a Modern Overlay renderer, so the popout receives the combined needs even when the in-game overlay is unavailable or inactive.

### Tests

- Added regression coverage proving Track All stores summed needs with only the Popout Tracker renderer present.

## [1.8.2-rc.1] - 2026-07-27

### Fixed

- **Build tracker project switching** - The newest project or Track All selection now supersedes an older in-flight fetch, so rapid combobox changes cannot leave the popout empty or showing a stale project's demand list.
- **Selected-project demand source** - Overlay and popout demand rows always come from the selected project's cache. A docked construction depot updates only its matching build id and no longer overrides a different selection.
- **Scoped depot cache writes** - Journal snapshots, successful depot PATCH responses, and completion events update the matching by-build-id entry; the selected single-project cache changes only when that build is selected, while Track All is rebuilt from the by-id cache.

### Changed

- **Depot cache implementation** - Shared cache-update logic is implemented directly in the normal journal, completion, and API PATCH paths; the temporary runtime method replacement is no longer needed.

### Tests

- Added regression coverage for out-of-order project and Track All fetch completion, selected-cache isolation, matching depot updates, completion filtering, and cache-driven demand rendering.

## [1.8.1] - 2026-06-28

### Fixed

- **Squadron Carrier cargo transfers** - Linked Squadron Carriers now use the same marketId-based `CargoTransfer` cargo delta rules as regular linked Fleet Carriers. Main-ship `tocarrier` transfers apply a positive FC cargo delta, main-ship `toship` transfers apply a negative FC cargo delta, and SRV transfer directions remain sign-correct for the linked carrier.
- **Removed Squadron-only Cargo resync fallback** - The old Squadron Carrier `Cargo` snapshot diff fallback and skip-next-Cargo bookkeeping were removed so direct `CargoTransfer`, `MarketBuy`, and `MarketSell` updates cannot be double-counted by a later inferred cargo diff.

### Changed

- **Fleet Carrier cargo diagnostics** - `CargoTransfer` handling now logs the current docked marketId, update eligibility, direction, SRV context, branch decision, and final signed cargo diff sent to RavenColonial.
- **Carrier cargo documentation** - Release and tracker documentation describe linked carrier cargo updates as a uniform marketId-based path using `PATCH /api/fc/{marketId}/cargo`.

### Tests

- Added regression coverage proving regular linked Fleet Carriers and Squadron linked Fleet Carriers produce the same signed cargo deltas for main-ship `tocarrier` and `toship` transfers.

## [1.8.1-rc.4] - 2026-06-23

### Added

- **Edit Carrier Manifest window** - The main tab now has a theme-aware Fleet Carrier manifest button with the **Edit Carrier Manifest** tooltip. The window lists linked carriers by callsign, edits the selected carrier's cached commodity totals, removes rows, adds commodities from a filtered scrollable commodity list, and keeps **Save** disabled until the normalized manifest changes.
- **Manual full-manifest save** - Saving the editor sends the selected carrier's full commodity totals through `POST /api/fc/{marketId}/cargo`, updates the local Fleet Carrier cache from the server response, and nudges the overlay cache when the edited carrier is selected.
- **Current ship cargo diagnostics** - Commander ship cargo publishing now logs normalized movement deltas, snapshot totals, and the `POST /api/cmdr/currentShip` payload summary so in-flight tracking can be verified from EDMC logs.

### Changed

- **Fleet Carrier dock baseline source** - Dock/startup baseline handling no longer depends on Elite writing a complete local Fleet Carrier `Market.json` cargo manifest. The cache is seeded from RavenColonial server snapshots or accepted CAPI snapshots, then maintained by journal trade/transfer deltas.
- **Startup while already docked** - Plugin startup now initializes Fleet Carrier dock context from EDMC state. If the player starts EDMC while already docked at an eligible carrier, the same baseline workflow runs as a normal `Docked` journal event.
- **Empty-cache dock handling** - If an eligible carrier has no usable cached manifest at dock time, the plugin fetches `GET /api/fc/{marketId}`, queues FC cargo deltas while the baseline is pending, and replays them after the baseline completes.
- **CAPI freshness policy** - CAPI Fleet Carrier cargo snapshots are still rejected while docked and require a parseable timestamp, but they no longer compare against RavenColonial `lastRefresh`; accepted undocked snapshots compare against the local cache timestamp when applicable and skip when the normalized manifest already matches.

### Tests

- Added regression coverage for startup-while-docked baseline initialization, server-baseline pending delta replay, failed-baseline delta release, and the Fleet Carrier manifest editor helper behavior.

## [1.8.1-rc.3] - 2026-06-22

### Changed

- **Fleet Carrier dock manifest priority** - Linked Fleet Carrier docks now always attempt one local `Market.json` manifest comparison for that dock visit, regardless of whether the existing cache came from RavenColonial, CAPI, or journal deltas. If the local manifest differs, the plugin queues a full FC cargo replacement before applying later cargo deltas.
- **Baseline-pending delta queue** - FC cargo deltas from `MarketBuy`, `MarketSell`, `CargoTransfer`, and squadron cargo resync are now buffered while the dock manifest baseline is pending. Once the manifest comparison finishes, queued deltas replay after the baseline so delayed `Market.json` writes do not cause skipped or out-of-order cargo patches.
- **Server FC timestamp alignment** - FC records from `GET /api/cmdr/{cmdr}/fc/all` and `GET /api/fc/{marketId}` now use the server's `lastRefresh` timestamp as the primary cargo freshness marker, with `cargoUpdatedAt` and `cargoSnapshotTimestamp` kept as fallbacks.

### Fixed

- **CAPI cargo freshness** - Fleet Carrier CAPI snapshots now pass Frontier's payload `timestamp` into the freshness check, normalize timestamp formats before comparison, reject snapshots while the player is docked, and only POST a full manifest when the undocked CAPI snapshot is newer than both server `lastRefresh` and the local cache timestamp and the cargo differs from cache.
- **Local manifest timestamps** - Dock `Market.json` manifest timestamps are preserved in the local FC cache when a dock baseline replaces cargo, instead of replacing them with the plugin's current clock time.

### Tests

- Added regression coverage for dock manifest timestamp preservation, trusted-cache dock comparisons, delayed dock-baseline delta replay, CAPI freshness against `lastRefresh`, timestamp normalization, docked CAPI rejection, matching-manifest CAPI skips, and empty-cache CAPI seeding.
- Full test suite passed locally with `189 passed, 1 skipped`.

## [1.8.1-rc.2] - 2026-06-21

### Added

- **EDMC version compatibility advisory** - Startup checks EDMC `appversion` against a tested minimum (`6.1.2`) and optional known-incompatible versions. Below-minimum and blocking cases surface through the existing main-thread status/error paths without changing supported hook behavior.

### Changed

- **Safer auto-update staging** - Auto-update keeps the custom updater, verifies the GitHub SHA-256 digest when release metadata provides one, validates the extracted and staged plugin tree, stages the update in a disabled folder while EDMC is running, and promotes the staged folder during EDMC shutdown after plugin resources are released.
- **Windows-aware update promotion** - Folder renames now use short retry/backoff handling for transient Windows file locks, leave the live plugin untouched when staging or shutdown backup rename fails, and restore the backup folder if shutdown promotion fails after the live folder was moved.
- **Supported Python metadata** - Local dev and packaging metadata now target `requires-python >=3.11,<3.14` instead of pinning to `>=3.13.9,<3.14`, matching the supported EDMC-compatible range.
- **Cross-platform journal fallback** - Market/journal fallback scanning now checks Windows, macOS, and Linux journal locations, sorts candidates by modification time, and ignores unreadable files while looking for recent market data.
- **HTTP request consistency** - API and UI worker HTTP calls now use the plugin retry/timeout helpers consistently, reducing hangs and one-off request behavior differences.
- **Developer checks reproducibility** - Flake8 and pytest are declared in `requirements-dev.txt`, the README documents the exact local lint command, and CI now enforces lint plus unit tests.
- **Logging setup cleanup** - Module fallback logger setup now uses a shared helper while preserving the existing EDMC-safe logger propagation choices.
- **Typed exception handling** - Hot paths now use shared groups in `exc_utils.py` instead of broad `except Exception` catches, with intentional survival/propagate boundaries documented in `load.py` worker and startup code. Logging context is preserved or improved on API, journal, FC, overlay, update, and UI paths.
- **Complexity baseline removed** - All 15 modules previously exempted from Flake8 `C901` now pass `max-complexity = 15`. Refactors include journal event dispatch and prefs section builders in `load.py`, UI async coordinators under `ui/`, overlay compose/draw helpers, `ParsedVersion` parsing in `version_check.py`, and FC handler predicate splits in `fleet_carrier_handler.py`. Per-file `C901` ignores were removed from `.flake8`.
- **Shutdown-aware UI scheduling** - Central `schedule_after()` on the plugin instance; high-traffic worker and cross-thread UI callbacks (manager, overlay row, popout, FC jump timer) schedule through it with shutdown and destroyed-widget guards.
- **Post-refactor cleanup** - Shared `http_session.new_http_session()` for UI workers (EDMC `timeout_session` with `requests` fallback in tests), deduplicated site parsing helpers, removed private cross-imports, cleared W503 style warnings, expanded worker typing via `ui/plugin_protocol.py`, and fixed overlay bridge Protocol stubs for flake8.

### Fixed

- **EDMC main-thread UI safety** - Worker-thread error paths now schedule plugin status/error updates back onto Tk's main thread instead of calling EDMC UI helpers directly from background workers.
- **Supported commander source** - Commander identity no longer depends on unsupported `monitor.cmdr`; it is captured from the supported journal `cmdr` hook and supported CAPI data fields.
- **Supported CAPI cache inputs** - The CAPI disk cache now accepts supported EDMC hook payloads only: `cmdr_data`, `cmdr_data_legacy`, and `capi_fleetcarrier`.
- **Squadron carrier tracking cleanup** - Removed the redundant unsupported `/squadron` Companion-session fetch/cache path. Squadron Fleet Carrier tracking remains journal-driven through the same linked `marketId` and `squadronBank` flow used for normal carrier cargo updates.
- **Auto-update status text** - Fixed garbled update status text in the staged-update failure path.
- **Issue-log diagnostics** - If the dedicated RavenColonial issue log cannot be initialized, plugin startup now warns through the EDMC main log and troubleshooting docs point users to that fallback.
- **Dead Market-file FC fallback** - Removed the disabled Fleet Carrier `Market.*.json` reconciliation path. Carrier cargo tracking remains driven by journal trade/transfer events, squadron cargo resync, and CAPI snapshots.
- **API client log strings** - Replaced mojibake in `api/client.py` docstrings and log messages with ASCII so project rename/completion logs display correctly on Windows.
- **EDMC theme walker on Canvas widgets** - Added `ThemeSafeCanvas` to ignore unsupported options (`foreground`, `font`, and similar) when EDMC applies themes. Main-tab collapse/separator canvases and Popout Tracker canvases use it so startup and theme changes no longer log `TclError: unknown option` in EDMC debug output.

### Tests

- Full test suite passed locally with `170 passed, 1 skipped`.
- `**ThemeSafeCanvas`** - Unit test confirms unsupported EDMC theme options are dropped without breaking supported canvas configuration.

## [1.8.0] - 2026-06-19

### Added

- **Build tracker popout** - The main tab now offers **Popout Tracker** as the separate-window alternative to **Enable Overlay**. Popout mode opens an EDMC-dark secondary window that renders the same selected build, **Track All**, ship cargo, optional FC column, assignment hints, row bands, column dividers, trip footer, and Fleet Carrier jump countdown as the in-game HUD.
- **Shared tracker controls** - **Enable Overlay** and **Popout Tracker** are mutually exclusive choices. When **Popout Tracker** is active, the in-game **Enable Overlay** checkbox is hidden, **Always On** is removed, and the same refresh, search, build-project, Track All, and carrier-tracking controls remain available for configuring the tracker.
- **Oxanium popout text** - The popout uses the plugin's bundled Oxanium font through Tk where available, matching the build tracker typography without requiring EDMCModernOverlay.
- **Discord-friendly tracker copy** - The popout title bar includes a copy button that places a fixed-width Discord code block on the clipboard. The copied table omits the Ship column, the "trips in this ship" line, and FC jump-timer lines, while keeping the FC deficit line when carrier data is available.
- **Localized popout labels** - **Popout Tracker** was added to every shipped locale file.

### Changed

- **Overlay dependency scope** - EDMCModernOverlay is still required for the in-game HUD, but the popout tracker can be used as an EDMC-native window when the external overlay stack is not wanted or not available.
- **Popout window behavior** - The popout now uses an EDMC-dark custom title bar with close and copy controls, appears on the taskbar where the platform supports it, remembers its last position across toggles and EDMC restarts, and resizes itself when tracker content changes.
- **Tracker table readability** - The popout column header now presents the numeric columns as `Need/Ship/FC` and the window recomputes spacing so Oxanium text does not overlap as rows or footer content change.
- **Default-theme combobox styling** - Custom tracker dropdowns keep the normal white entry background in EDMC's default theme, including disabled placeholder states such as `Please Refresh` and `Select carrier`.

## [1.7.9] - 2026-06-18

### Fixed

- **Auto-update package integrity** - The updater now checks the extracted release tree before and after install so an incomplete zip cannot replace the live plugin and break the next EDMC restart.
- **Manual recovery prompt** - Auto-update failures now tell the user to try the manual installation steps in `docs/MANUAL_UPDATE_INSTRUCTIONS.md` after checking the logs.

## [1.7.8] - 2026-06-17

### Added

- **Fleet Carrier jump countdown in overlay** - When you schedule a carrier jump, the build overlay footer shows a live departure countdown as the **last row** (BGS-Tally-compatible timing). Sub-lines appear for jump initiation (under 10 minutes), landing-pad lockdown (under 3m20s), and pads locked. `CarrierJumpCancelled` starts a 60-second cooldown row; completed jumps use the standard post-departure cooldown. The overlay refreshes every second while a jump timer is active. When carrier tracking selects one callsign, that carrier's jump is preferred for display.
- **Collapsible main plugin panel** - A chevron on the **Ravencolonial** header collapses the plugin body to a single header row (expanded = down, collapsed = left) with an animated toggle, leaving more room on the EDMC main tab.

### Changed

- **Overlay refresh failure handling** - Empty-search failures still show the popup, but the build-project dropdown no longer switches itself to `Build projects error`. It stays on `Please Refresh` so the UI does not look broken after a bad search.
- **Plugin header typography** - The Ravencolonial header font scale is reduced by 25% for a tighter fit beside EDMC's main-tab layout.
- **Collapsed panel chrome** - Top and bottom separator lines stay visible when the plugin panel is collapsed.

### Fixed

- **Non-modal overlay failure path** - Normal overlay refresh failures no longer force a blocking status interruption in the UI. When the current system is known, the dropdown can fall back to `No Build Projects` instead of showing a transient error state.
- **Jump footer on empty overlay states** - The FC jump countdown still renders as the last footer row when the commodity table is complete or has no remaining rows.

## [1.7.7] - 2026-06-17

### Added

- **Active-project Fleet Carrier update eligibility** - Startup now reads `GET /api/cmdr/{cmdr}/active` and adds every active project `linkedFC[].marketId` to the same FC cargo PATCH eligibility set used for profile-linked carriers. Duplicate market IDs are collapsed, so a carrier linked in both the commander profile and a project still produces only one cargo update path.
- **Persistent owner capacity cache** - Fleet Carrier owner free-space snapshots are stored in `fc_owner_capacity_cache.json` inside the plugin folder. The overlay only shows the capacity footer for a selected carrier when a matching cached `freeSpace`/`marketId` pairing exists.
- **Targeted v2 site repair documentation** - The inferred API reference now documents `PATCH /api/v2/system/{nameOrNum}/sites/{siteId}` for small plan-site repairs such as `marketId` and `name`.

### Changed

- **Overlay Fleet Carrier cache flow** - Carrier cargo shown in the overlay is no longer refreshed from Ravencolonial during normal overlay redraws. Manual/context-allowed refreshes establish the server baseline, then journal deltas update the local manifest and selected overlay rows live.
- **Manual FC manifest refresh** - Carrier tracking now has a refresh button beside the carrier dropdown. It reloads `GET /api/fc/{marketId}` for one selected carrier, or every linked carrier when All is selected, then disables itself with a live 60-second countdown.
- **Track All carrier handling** - Track All uses the same cached FC manifests as single-project tracking and mirrors journal deltas for any currently tracked linked carrier, avoiding stale aggregate rows without polling.
- **Plan-site dropdown scope** - Plan-site candidates loaded from the in-system refresh are scoped to the current system and clear on system changes, while overlay build rows remain separately tracked until refreshed or completed.
- **API reference anchors** - Same-file endpoint links were simplified to Markdown heading anchors so editor navigation works without raw endpoint HTML anchors.

### Fixed

- **FC cargo cache replacement** - Full carrier cargo snapshots now replace the local manifest instead of leaving commodities that disappeared from the server response.
- **CAPI/server freshness guard** - CAPI cargo snapshots cannot overwrite a non-empty Ravencolonial server baseline unless freshness can be verified.
- **Display-only FC PATCH guard** - Project/display carrier records can be shown in the overlay without becoming cargo PATCH eligible unless they come from the commander profile or active-project `linkedFC` list.
- **Missing FC manifest display** - Selecting a project-linked carrier with no local cargo manifest now performs one guarded `GET /api/fc/{marketId}` seed attempt; if no manifest can be loaded, the FC column shows `sync` instead of treating missing stock as zero.

## [1.7.6] - 2026-06-14

### Fixed

- **Track All dropdown order hotfix** - **Select Build Project** remains the first placeholder row, **Track All** is now the first selectable row below it, and individual build projects follow.
- **Combobox popup height hotfix** - Removed the fixed popup height cap from the custom themed combobox so all build-project rows are visible without hidden, unscrollable items.

## [1.7.5] - 2026-06-14

### Added

- **Overlay Track All mode** - The build-project picker now offers **Track All** as the first active option. It aggregates remaining commodities across every active build project in the refreshed project list and renders the combined total in the HUD.
- **Aggregate carrier tracking** - In **Track All**, linked fleet carriers from all tracked projects are combined and deduplicated by `marketId`. The carrier picker still supports **All** carriers or a single carrier callsign.
- **Track All project cache** - The overlay keeps a per-build project cache for aggregate mode, then rebuilds the combined HUD from that cache as individual project data changes.

### Changed

- **Event-driven Track All refresh** - Local `ColonisationConstructionDepot` updates continue to update the currently docked project immediately, while full Track All project-detail refreshes are deferred until undock after cons…5963 tokens truncated…ct**` before `**POST .../complete**`.
- **Fewer redundant project GETs** — `**check_existing_project`**, `**CargoDepot**` status path, and `**ColonisationContribution**` use `**get_project(..., use_location_cache=True)**` where appropriate.
- **CAPI on-disk snapshot retention** — `**capi_cache.py`** keeps the **3** newest timestamped `**snapshot_<kind>_*.json`** files per supported EDMC CAPI hook kind (`cmdr_data`, `cmdr_data_legacy`, `fleetcarrier`; v1.6.2 documented **40**). `**capi_cache.write()`** accepts optional `**source_host**` / `**request_cmdr**` for envelope `**meta**`.

### Fixed

- **False “project exists”** — dicts without `**buildId`** no longer imply an active project for the create button / `**get_project()**` consumers.
- **Duplicate link/create after completion** — mitigated when `**/api/system/...`** still says “no active project” but the plan site has moved past `**plan**`: sites preflight blocks `**PUT /api/project**`.
- **Undocked status text** — main-tab status uses the journal `**Undocked`** event’s `**StationName**` (with EDMC’s `**station**` argument as fallback). EDMC clears `**monitor.state['StationName']**` before `**journal_entry**`, so the third argument is `**None**` on undock; the previous logic showed **“Undocked from None”**.
- **Link Build Site double-click** — while a link worker is running, the main action button is disabled and a second click is ignored, avoiding overlapping `**GET`/`PUT`** sequences that could race before the server reflects the first `**PUT`**.

### Documentation

- `**docs/ACTION_MAP_API_FLOWS.md**` — journal/API map aligned with normalized `**/api/system/...**`, `**404**` completion hints, Link Build Site flow (`**/sites**` preflight, `**architectName**` on `**PUT**`).
- `**README.md**` — Features table and **Plan sites and Link Build Site** usage (architect refresh, link payload, plain-language safety checks before linking); pointer to `**ACTION_MAP_API_FLOWS.md`** for technical detail.

### Notes

- Publish `**v1.6.3**` on GitHub with a `**RavenColonial_EDMC-v1.6.3.zip**` release asset so in-app auto-update can resolve the build. For a **rerelease** of the same tag, replace the zip on the existing `**v1.6.3`** release (or delete and recreate the release) so the asset name stays `**RavenColonial_EDMC-v1.6.3.zip**` for auto-update matching.

## [1.6.2] - 2026-05-03

### Added

- **Plugin issue log** — rotating file `**logs/RavenColonial_EDMC.log`** under the plugin install directory (same handler attached to main, `**.api`**, `**.fc`**, and other plugin module loggers so API and FC traffic appear even with `**propagate=False**`). Initialized in `**plugin_start3**`; closed on `**plugin_stop**`. See README troubleshooting for paths to attach on GitHub issues.
- **CAPI snapshot cache** — on each EDMC refresh, `**cmdr_data`**, `**cmdr_data_legacy**`, and `**capi_fleetcarrier**` enqueue a deep-copied payload; a background thread writes `**latest_<kind>.json**` and timestamped `**snapshot_<kind>_*.json**` under `**<plugin_dir>/capi_cache/**` (envelope includes `meta`: kind, UTC time, `is_beta`, `source_host`, `request_cmdr`). Prunes to the 40 newest snapshots per kind. `**plugin_stop**` drains the writer thread before unload. `**.gitignore**` includes `**capi_cache/**` so dumps stay local.

### Changed

- **Fleet Carrier journal logic (SrvSurvey parity)** — detect squadron fleet carriers via journal `**StationServices`** containing `**squadronBank**`; `**CargoTransfer**` uses main-ship vs SRV branching like SrvSurvey and skips branch-A deltas on squadron FCs; `**MarketBuy`/`MarketSell**` set a one-shot skip for the follow-up `**Cargo**` resync; forced `**Cargo**` (no full inventory in the event) can apply an inverted commander-hold diff to `**/api/fc/{marketId}/cargo**` when docked on a linked squadron FC after a full `**Cargo**` baseline. `**Location**` / `**Undocked**` refresh FC dock context and services.
- **License** — project relicensed under **MIT**; added root `**LICENSE`** file, `**pyproject.toml**` `license` metadata, and `**README**` badge + wording (EDMC remains under its own upstream license).
- **README** — reorganized badges (CI / security / release / license; community; runtime & downloads).

### Fixed

- **Update UI theming** — main-window update banner and controls use `**ttk`** (and EDMC `**HyperlinkLabel**` for the project link when available) so colors match EDMC light/dark and custom themes instead of classic `**tk**` defaults. **Create Project** dialog: `**tk.Text`** Notes field takes `**TEntry`/`TLabel`** colors from `**ttk.Style`**, Toplevel `**bg**` matches `**TFrame**`; column weights for resize. `**plugin_app**` fallback uses `**ttk.Frame**`. Settings tab: GitHub URL uses `**HyperlinkLabel**` instead of hard-coded blue.

### Notes

- Publish `**v1.6.2**` on GitHub with a `**RavenColonial_EDMC-v1.6.2.zip**` release asset so in-app auto-update can resolve the build. For a **rerelease** of the same tag, replace the zip on the existing `**v1.6.2`** release (or delete and recreate the release) so the asset name stays `**RavenColonial_EDMC-v1.6.2.zip**` for auto-update matching.

## [1.6.1] - 2026-05-01

### Added

- **Commander ship snapshot** — `POST /api/cmdr/currentShip` (SrvSurvey-compatible body: commander, ship name/type, `maxCargo`, normalized `cargo` map), authenticated with `**rcc-key`** only. Driven from journal `**Cargo**`, `**Loadout**` (main ship), and `**SetUserShipName**`, with EDMC `**state**` for `CargoCapacity` / ship identity; deduplicated queue to the background API worker.
- **Stealth: commander ship cargo** — config `**ravencolonial_stealth_ship_cargo`**: when enabled, skips publishing the commander ship snapshot (independent of Fleet Carrier stealth).
- **Stealth: all construction delivery reporting** — config `**ravencolonial_stealth_construction_reporting`**: when enabled, skips `**ColonisationConstructionDepot**`, `**ColonisationContribution**`, and `**CargoDepot**` journal paths that update Ravencolonial (Create Project from the dialog is unchanged).
- **Plugin UI localization** — all user-facing strings go through EDMC `**l10n`** (`**i18n.py**` + `**tr**` / `**trf**`). `**L10n/en.template**` defines English keys; `**L10n/*.strings**` cover the same locale set as core EDMC except the parody `**uwu**` locale (machine-translated for most languages; `**sr-Latn**`* use a Latin-script placeholder with a header note). Maintainer regen: `**scripts/generate_plugin_l10n.py*`* (`deep-translator`; `**--resume**`, `**--only**`).
- **Show API Key** — Ravencolonial settings tab checkbox (default off) toggles the API key field between masked and visible entry.
- `**scripts/clean_build_artifacts.py`** — remove `**dist/**`, `**__pycache__/**`, egg metadata, and setuptools outputs under `**build/**` while **preserving `build/release/`** (release zips). Optional `**--include-stray-root-zips**` only affects legacy zips in the repo root.

### Removed

- **Dock-to-dock CSV logger** (`**d2d_logger.py`**) — local `**~/Documents/d2dTimes.csv**` timing log removed; no API or website impact.

### Changed

- **Fleet Carrier stealth** — `**ravencolonial_stealth_mode`** now applies **only** to Fleet Carrier commodity/CAPI sync (no longer gates colonization depot/contribution journal handling).
- **Settings UI** — three separate checkboxes and help strings for FC stealth, ship-cargo stealth, and construction-reporting stealth; grid layout adjusted for the extra row.
- **Documentation** — README rewritten for current features, repo (**Fenris159/ravencolonial_edmc**), releases link, configuration, and troubleshooting; [docs/MANUAL_UPDATE_INSTRUCTIONS.md](docs/MANUAL_UPDATE_INSTRUCTIONS.md) generalized as a fallback when auto-update fails; [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md) updated for current release practice; [docs/AUTO_UPDATE_FEATURE.md](docs/AUTO_UPDATE_FEATURE.md) aligned with this repo; legacy per-beta release notes stub removed in favor of the changelog and GitHub releases.
- **Documentation layout** — all supplementary Markdown (manual update, auto-update, release checklist, logging guide, API reference) moved under `**docs/`** with [docs/README.md](docs/README.md) as the index; `**make_release.py**` bundles the `**docs/**` tree into the release zip so manual installs include the same docs as the repo.
- **README** — documents `**L10n/`** behavior (follows EDMC display language), machine-translation caveats, and the `**generate_plugin_l10n.py**` workflow.
- `**make_release.py**` — always resolves the repo from the script path (not the process cwd); writes `**build/release/RavenColonial_EDMC-v{version}.zip**`; documents the output layout in README / maintainer docs.
- **Create Project error text** — EDMC log path hint is **OS-specific** (Windows / macOS / Linux) via `**{log_path}`** in `**L10n/***` and `**edmc_log_path_hint()**` in `**plugin_config/settings.py**`, replacing a Windows-only `**%TEMP%**` string.
- **Markdownlint** — `**.markdownlint.json`** and `**.markdownlint-cli2.jsonc**` relax noisy rules for tables/changelog and ignore vendored trees when linting broad globs.

### Fixed

- **Auto-update ZIP install** — validate archive member paths before `**extractall`** to block path traversal (**Zip Slip**) from a malicious zip.
- `**get_market_data()`** (`**load.py**`) — open market JSON with `**encoding="utf-8"**` for consistent decoding across platforms.

### Notes

- Publish `**v1.6.1**` on GitHub with a `**RavenColonial_EDMC-v1.6.1.zip**` release asset so in-app auto-update can resolve the build.

## [1.6.0] - 2026-05-01

### Added

- Package `**__init__.py**` at the plugin root so EDMC can load `load` as a subpackage and relative imports resolve reliably.
- Module-level `**VERSION**` (mirrors `plugin_version`) for EDMC `plug.get_version()` / Plugin Browser.
- `**_notify_plugin_status_main_thread()**` in `load.py` so background threads can refresh status without calling `**plug.show_error**` for non-errors (avoids the “error” sound and status misuse).
- `**normalize_commodity_key**` / `**_normalize_cargo_map**` in `api/client.py` (and use from journal, FC handler, CAPI FC path, and create dialog) so `**Cargo**` payloads match Ravencolonial’s lowercase commodity keys.
- `**_elite_journal_dir()**`, journal timestamp helpers, `**refresh_construction_depot_from_journal()**`, and a per-line copy of EDMC’s `**state**` in `**_last_edmc_state**` for resolving system address and depot snapshots when the journal is slightly behind UI actions.

### Changed

- **Maintainers / repository**: Primary development, issues, and GitHub **Releases** (including auto-update checks) are now **[Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Earlier releases and code history remain attributable to upstream contributors (notably toemaus313 / CMDR Dirk Pitt13 and the original EDMC-RavenColonial lineage).
- **Auto-update source**: `version_check` uses a single `**GITHUB_REPO`** constant (`Fenris159/ravencolonial_edmc`); `load.py` prefs GitHub link and “latest” version check use the same value.
- **HTTP / EDMC alignment**: API client, GitHub version checks, and update downloads use EDMC `**timeout_session.new_session()`**; `**PluginConfig.get_user_agent()**` prefixes EDMC’s `**config.user_agent**` with a Ravencolonial plugin suffix (per PLUGINS.md).
- **Imports**: switched to **relative imports** across the plugin (`load.py`, subpackages, `create_project_dialog` / `version_check` where applicable) to avoid clashing with other plugins’ top-level module names.
- **Settings persistence**: `**prefs_changed`** now persists the same fields as “Save Settings” when the user dismisses EDMC Settings with OK, matching PLUGINS.md (widgets were previously easy to lose if OK was pressed without the in-tab Save).
- **Configurable API base URL**: `**ravencolonial_api_url`** is read with supported `**config.get_str()**` (removed invalid `**appname_config**` usage that always fell back to the default base URL).
- **Update UX**: startup and manual auto-update **success** paths use logging + main-thread status updates instead of `**plug.show_error`**; failures still use `**plug.show_error**`.
- **Release zip layout** (`make_release.py`): artifact folder / prefix `**RavenColonial_EDMC`** and filename `**RavenColonial_EDMC-v{version}.zip**`; **all root `*.py`** except `make_release.py` are bundled automatically so runtime modules cannot be omitted from the zip by mistake.
- **Ravencolonial HTTP client** (`api/client.py`): FC cargo uses `**rcc-key` only** (matches [SrvSurvey](https://github.com/njthomson/SrvSurvey)); **lowercase** `/api/system`, `/api/cmdr`, `/api/fc` paths; `**buildId`** path segments **URL-encoded** on contribute and project supply POSTs; `**create_project`** uses **debug/info** logging for normal traffic (errors only on HTTP failure / exceptions); duplicate `**logger.error`** pairs on several failure paths consolidated.
- **Version compare**: removed duplicate `**compare_versions`** from `load.py`; prefs “check for updates” uses `**version_check.compare_versions(..., logger)**` so behavior matches auto-update (including prerelease vs stable when versions tie).
- `**get_system_sites**`: optional `**name_or_num**` (system name or id64); when omitted, still resolves `**current_system_address**` via journal/state. `**get_system_bodies**` / `**get_system_architect**` and v2 `**nameOrNum**` URLs use the same escaped segment rules as SrvSurvey.
- `**get_system_address_from_journal**`: prefers EDMC `**state`’s** `SystemAddress`; journal fallback scans recent files for the **latest** `**Docked`** or `**Location**` with `**Docked: true**` by **timestamp** (not only the first reversed hit in one file).
- **Create Project flow**: before `**PUT /api/project`**, calls `**refresh_construction_depot_from_journal()**` (latest `**ColonisationConstructionDepot**`, preferring `**MarketID**` when known); **blocks** create if depot snapshot or **required commodity** list would be empty, with clear “wait / re-dock” errors instead of sending an empty commodity map.
- **Main-window create button**: disabled label `**Waiting for Dock`**; enabled-to-create label `**🚧Create Build Project**` (existing-project branch unchanged: **Open Build Page**).

### Removed

- Unused `**plugin_app_prefs_cmdr`** entry point (not invoked by current EDMC `plug.py`).
- **TESTING bypass** in `ui/manager.py` that could force-enable the Create Project button.
- `**rcc-cmdr`** header on FC `**/api/fc/.../cargo**` requests (server contract matches SrvSurvey: `**rcc-key**` only).
- Unused `**models**` imports from `**load.py**` (project still uses plain dicts from the API).

### Fixed

- **Update notification banner**: `UIManager` resolves `**CURRENT_VERSION`** via `**from ..version_check import CURRENT_VERSION**` so it works when the plugin is loaded as a package.
- **Accidental duplicate** `get_system_address_from_journal` method on `**RavencolonialPlugin`** (second definition overwrote the first; removed the dead copy and invalid `**exc_info=e**` logging).

### Documentation

- This changelog’s **1.5.x and earlier** sections were reconciled with historical **GitHub release titles/dates**; README / support / auto-update docs updated for the **Fenris159** fork and **RavenColonial_EDMC** zip naming.

### Notes

- For that release line, publish a `**RavenColonial_EDMC-v1.6.0.zip`** asset on GitHub so auto-update can resolve the build (see newer release notes for the current artifact name).

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

- **Localization (l10n)**: framework and English template (`L10n/en.template`).
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
