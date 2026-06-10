# Changelog

All notable changes to the Ravencolonial EDMC plugin are documented in this file.

Release titles and dates are aligned with [GitHub Releases](https://github.com/Fenris159/ravencolonial_edmc/releases) when published there (using each release’s publish date in UTC, `YYYY-MM-DD`). Older entries may reference releases from the upstream fork history.

## [Unreleased]

- Nothing yet.

## [1.7.4] - 2026-06-10

### Changed

- **Site repair recent-visit cache** - The rolling last-50 repair cache is now persisted across plugin reloads in `site_market_id_repair_visits.json`.
- **Repair cache writes** - `(MarketID, normalized station name)` entries are now recorded only after a successful site repair PATCH, so failed/no-match attempts can be retried later in the same session or after server-side data changes.

## [1.7.3] - 2026-06-06

### Changed

- **Targeted site repair endpoint** — Legacy completed-site repair now updates the matched `/sites` row through targeted `PATCH /api/v2/system/{nameOrNum}/sites/{siteId}` instead of bulk `PUT /api/v2/system/{nameOrNum}/sites`. The repair uses the journal `SystemAddress` ID64 for `nameOrNum`.
- **MarketID repair payload** — Name-matched MarketID repairs send only `{ "marketId": ... }`; they do not update the site name.
- **Site name repair fallback** — If the name-matched MarketID repair path does not apply, the same already-fetched `/sites` rows are checked for exactly one row whose `marketId` already equals the dock journal `MarketID`. When that row is complete/statusless and its normalized name differs from the journal station name, the worker patches only `{ "name": ... }`. Duplicate `marketId` rows skip the rename to avoid changing the wrong site.
- **Site repair recent-visit cache** — Recent repair checks are now remembered by `(MarketID, normalized station name)` instead of `MarketID` alone, so a later in-game station rename can still trigger the name repair path without adding extra `/sites` reads for unchanged docks.

## [1.7.2] - 2026-05-31

### Notes

- Hotfix **`v1.7.2`**: publish **`RavenColonial_EDMC-v1.7.2.zip`** on GitHub so in-app auto-update can resolve the build. **Upgrade from v1.7.1** if legacy completed sites still show missing Market Info after construction finishes.

### Changed

- **Construction complete status** — After a successful project completion, the main-tab notification now asks commanders to re-dock at the finished location to update Market Info. All plugin locale strings include the longer message.

### Fixed

- **Legacy completed site MarketID repair (hotfix)** — v1.7.1 added backfill on re-dock, but matching on journal `BodyID`/`bodyNum` plus station name rarely succeeded at **finished** outposts. This release fixes the repair path so re-docking at the completed station can reliably `PUT` the journal `MarketID` onto eligible `/api/v2/system/{SystemAddress}/sites` rows (Ravencolonial API key required; **`Docked`** and docked **`Location`** only—not `ColonisationConstructionDepot`).
- **MarketID repair matching (name-only)** — Matching now uses **normalized station name only**. Body alignment failed because finished outposts use different MarketID prefixes than construction depots (`43…` vs `396…`), several completed sites can share the same `bodyNum`, and depot journal names (`Orbital Construction Site: …`) never equal the finished station name. `normalize_dock_station_name()` strips construction-site prefixes and localization tokens before compare. Repair proceeds only when **exactly one** `/sites` row shares that normalized name; if two or more rows share the name (even when only one is eligible), the update is skipped as a safety guard. Rows with a **wrong** stored `marketId` (e.g. depot `396…` on a finished outpost) are updated to the dock journal ID when it differs; rows that already match the journal ID are left alone.
- **MarketID repair eligibility** — Journal `MarketID` must fall under player colonization prefixes **`395`**, **`396`**, **`397`**, **`42`**, or **`43`**. Target rows must be **`complete`** or statusless and still missing `marketId`; active **`plan`** / **`build`** rows are never touched. Skipped dock contexts: fleet carriers, megaships, `SpaceConstructionDepot`, orbital/planetary construction depot names, colonisation ships, and any dock outside those MarketID prefixes.
- **MarketID repair worker** — Async worker performs **one** live `/sites` match pass on success; retries the GET up to **3** times with **1.5s × attempt** backoff **only when the `/sites` request fails** (timeout/latency), then `PUT`s the dock `MarketID`. Remembers the last **50** checked dock MarketIDs and dedupes inflight `(SystemAddress, normalized name, MarketID)` work so repeat docking does not hammer `/sites`. Successful **construction complete** at the depot also records that depot `MarketID` (already sent during build/link) so re-docks there skip repair.

## [1.7.1] - 2026-05-30

### Notes

- Publish **`v1.7.1`** on GitHub with a **`RavenColonial_EDMC-v1.7.1.zip`** release asset so in-app auto-update can resolve the build.

### Added

- **Cerulean Gold overlay theme** — Sixth preset (cerulean **blue** build/footer, **white** system line, pale blue commodity labels, **gold** value columns) for a cockpit-style HUD on dark backgrounds.
- **Overlay localization templates** — Dedicated **`L10n/en.overlay.template`** for HUD labels/trip wording/categories and generated **`L10n/en.commodities.template`** for 255 FDev commodity display names; generation/refresh scripts merge these into plugin locale files.
- **Localized overlay commodity names** — Latin/Cyrillic locale files include overlay HUD strings plus commodity/category names. Where available, commodity/category names come from EDDI's Elite Dangerous game-string resources; gaps fall back to machine translation. Japanese, Korean, and Simplified Chinese intentionally keep the English HUD fallback for now.

### Changed

- **Plan-site wording** — User-facing English text and translated locale strings now use **location** instead of **site** for plan/location selection labels and messages, while keeping existing `tr()` lookup keys stable for compatibility.

### Fixed

- **Legacy completed site MarketID repair** — On dock/location journal context, completed or statusless `/api/v2/system/{SystemAddress}/sites` rows missing `marketId` are matched by normalized station name plus `BodyID`/`bodyNum`; exactly one match is updated with the journal `MarketID` via authenticated `PUT /api/v2/system/.../sites`. The repair waits through short server-latency retries and records the last 50 checked dock `MarketID`s to avoid repeated `/sites` calls on repeat docking. *(Matching and eligibility were corrected in **[1.7.2]**—re-dock at the **finished** station after upgrading.)*
- **Plugin language switching** — After changing EDMC's language and closing Settings with **OK**, plugin-owned labels, checkboxes, combobox placeholders, buttons, and the update banner repaint from the newly loaded plugin translations without restarting EDMC.
- **Linux modal dialogs** — Themed error/alert dialogs defer ``grab_set`` until after the toplevel is visible (avoids a stray grab that can make all EDMC mouse input appear dead on X11/Wayland).
- **Themed combobox (all EDMC themes)** — Popup list colors are taken from the closed entry (with contrast enforcement) and never call ``theme.update`` on the ``Listbox``. After ``theme.update`` on the entry, light/default themes that set the same fg/bg get a readable black foreground; combobox entry/button are excluded from subtree ``theme.update`` so styling is applied once via ``apply_theme_styling``. Root ``<Button-1>`` dismiss bindings are always cleared when the popup closes; popup height is derived from item count (fixes zero-height lists on Linux). Fixes v1.7.0 behaviour where plan-site options only appeared under dark theme.
- **Plan locations refresh logging** — Successful ↻ refresh logs plan/build row counts to the RavenColonial issue log for easier diagnosis of empty **Select Plan Location** lists.
- **Main-tab settings (⚙) button** — Opens EDMC **File → Settings** on the Ravencolonial plugin tab again (``postprefs`` is not on the Tk root in EDMC 6.x; dialog discovery uses the settings notebook, not the window title).
- **Overlay row layout** — **Select Build Project** combobox and ↻ refresh sit on their own row between the overlay toggles and carrier tracking row (aligned with **Select Plan Location**).
- **Plugin tab crash on startup** — Renamed overlay ``build_picker_row`` frame attribute so it no longer shadows ``build_row()`` (EDMC logged ``TypeError: 'NoneType' object is not callable`` and disabled the plugin tab).
- **Overlay row checkboxes** — ~2× indicators via themed ``PhotoImage`` pairs (``indicatoron=0``; no font/ttk padding). ``tk`` + ``ttk.Label`` captions match EDMC dark theme. All three match; gated sub-options gray the caption only. Overlay defaults off; last on/off choices persist via config.
- **Theme switching** — Plugin-owned ``tk`` controls, custom comboboxes, separators, header font, and overlay checkbox images repaint after Tk/ttk ``<<ThemeChanged>>``; generated checkbox images resolve EDMC/Tk symbolic colors through ``winfo_rgb`` so default/light themes on Linux do not inherit invalid or dark-only colors.
- **RavenColonialWeb header font** — **Oxanium** for the main-tab title via Windows private font registration; Tcl/Tk in EDMC does not support ``Font(file=…)`` (logged ``bad option "-file"``), so the bundled variable font is registered with GDI then selected by family name.

## [1.7.0] - 2026-05-28

### Notes

- Publish **`v1.7.0`** on GitHub with a **`RavenColonial_EDMC-v1.7.0.zip`** release asset so in-app auto-update can resolve the build.
- **Requires [EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay)** for the in-game build tracker HUD (install separately; borderless or windowed Elite). See **[docs/OVERLAY.md](docs/OVERLAY.md)**.

### Added

- **Oxanium HUD font:** Bundled Oxanium variable font (OFL); auto-install into EDMC Modern Overlay with per-layer font weights (200–800).

- **Build tracker overlay** — Optional on-screen commodity table for a selected **build** project (Need, Ship, optional FC surplus/deficit, assignment hints, trip footer) via EDMCModernOverlay, similar in spirit to SrvSurvey’s build overlay.
- **Main-tab overlay row** — **Enable Overlay**, **Always On** (HUD while undocked), **Select Build Project** (`status == build`), dedicated **↻** refresh for overlay sites, and optional **Enable Carrier Tracking** with **All** or a linked callsign.
- **Overlay themes** — Five HUD color presets in settings (default **Elite Orange**); multi-layer text (build/system/commodity/values/footer).
- **HUD readability** — Semi-transparent plugin-group panel, alternating row bands on commodity data rows, vertical rules between **Need | Ship | FC's** (commodity rows only).
- **Market categories** — Commodities grouped under Elite market categories (EDCD FDevIDs template).
- **Trip estimates** — Footer shows total remaining units and **trips in this ship** (`CargoCapacity` from journal); optional FC deficit line when carrier tracking is on.
- **Clutter reduction** — Ship cargo **zero** shows as blank; fulfilled commodities (**zero need**) are hidden; live depot remaining is authoritative when docked so completed rows do not reappear from stale project data.
- **Overlay dependency guard** — Enabling the overlay without EDMCModernOverlay shows a themed alert pointing to plugin settings and the Modern Overlay link.
- **Settings** — **Overlay Theme** picker; **EDMC Modern Overlay** dependency section with GitHub link at the bottom of the Ravencolonial settings tab.
- **UI polish** — Gear button on the status row opens plugin settings; RavenColonialWeb header above main controls; styled canvas separators above and below the plugin panel.
- **Documentation** — **[docs/OVERLAY.md](docs/OVERLAY.md)**; unit tests for overlay formatting, themes, trips, FC cargo, availability, row stripes, column dividers, and `load.py` wiring.

### Fixed

- **`load.py` overlay wiring** — Restored `BuildProjectOverlay` initialization, `refresh_build_overlay()`, project fetch hook, and plugin-stop clear after an accidental removal during the settings refactor (overlay would not have updated in-game without this).

## [1.6.8] - 2026-05-27

### Notes

- Publish **`v1.6.8`** on GitHub with a **`RavenColonial_EDMC-v1.6.8.zip`** release asset so in-app auto-update can resolve the build.

### Fixed

- **Commander ship cargo after station trade** — **`MarketBuy`** / **`MarketSell`** at regular stations update the hold sent to **`POST /api/cmdr/currentShip`**. Sparse **`Cargo`** journal lines (**`Count`** only) no longer replace the hold with an empty map when EDMC’s cargo state has not caught up yet (e.g. a single full-hold **`steel`** purchase).
- **Depot sync after API timeout** — **`ColonisationConstructionDepot`** remaining need is remembered and duplicate-PATCH signatures are set **only after a successful PATCH**; transient read timeouts on GET/PATCH retry safely, while **`POST …/contribute`** does not retry read timeouts (avoids double-counted delivery history).

## [1.6.7] - 2026-05-24

### Notes

- Publish **`v1.6.7`** on GitHub with a **`RavenColonial_EDMC-v1.6.7.zip`** release asset so in-app auto-update can resolve the build.

### Added

- **`station_names.py`** — Shared **`normalize_dock_station_name()`** for dock **`buildName`** (localization tokens and construction-site prefixes); used by **Link Build Site**, **Create Project**, and construction completion rename.
- **Depot payload helpers** — **`build_depot_project_fields()`**, **`build_depot_patch_payload()`**, and **`prepare_put_project_body()`** unify create, link, and journal depot sync.
- **Plan-site body helpers** — **`plan_site_body_num()`**, **`body_name_for_num()`**, and **`plan_site_put_body_fields()`** for **`bodyNum`** / **`bodyName`** on link **PUT**.
- **Phantom commodity cleanup** — **`phantom_commodity_zero_patch_map()`** and **`maybe_clear_phantom_commodities()`** zero Ravencolonial template slots at **`‑1`** when a project response is already in hand.

### Changed

- **Depot need sync** — Ongoing **`ColonisationConstructionDepot`** updates **PATCH** `/api/project/{buildId}` with the full depot snapshot (authoritative remaining need). Legacy **POST** `/api/project/{buildId}` supply updates removed; **POST** `/supply/{cmdr}` remains unused (subtract semantics). **`ColonisationContribution`** still uses **POST …/contribute** (history only).
- **API documentation** — **`docs/RavenColonial_API_Reference.md`** and **`docs/ACTION_MAP_API_FLOWS.md`** document PATCH depot vs contribute vs supply; **`README.md`** colonization section aligned.

### Fixed

- **Link Build Site commodities** — Linking a plan site now sends the same **`commodities`**, **`maxNeed`**, and **`colonisationConstructionDepot`** payload as scratch **Create Project** (from the dock **`ColonisationConstructionDepot`** journal line). Follow-up depot sync uses **PATCH** (not **POST**) when remaining need differs from what **PUT** already sent; a fresh dock skips that redundant call.
- **Link Build Site naming** — **`buildName`** on link uses the normalized dock station name (not the Ravencolonial plan codename).
- **Link Build Site body** — **`PUT /api/project`** now includes **`bodyNum`** and **`bodyName`** from the selected plan row (`/sites`) plus **`GET /api/v2/system/.../bodies`** lookup (same source as the create dialog).
- **Plan-site dropdown after link** — Linked **`plan`** rows drop out of **Select Plan Site** immediately without a manual ↻ refresh.
- **Phantom commodity rows (`?`)** — Outbound need maps clamp to **`≥ 0`**; negative keys in an existing project response are **PATCH**ed to **`0`** without an extra hunt **GET**.

## [1.6.6] - 2026-05-24

### Notes

- Publish **`v1.6.6`** on GitHub with a **`RavenColonial_EDMC-v1.6.6.zip`** release asset so in-app auto-update can resolve the build.

### Fixed

- **Plan-site architect gate** — **`GET /api/v2/system/.../architect`** sometimes returns a double-encoded JSON string (e.g. **`"Fenris Nihilus"`** with literal quote characters). **`parse_system_architect_response`** unwraps those quotes so system architects match correctly and the **Select Plan Site** dropdown shows **all** **`plan`** rows plus **Create New** instead of orbital-only filtering. Plan-site refresh also prefers **`cmdr_name`** then **`cmdr_snapshot`** for the commander comparison (same order as Link Build Site).

## [1.6.5] - 2026-05-13

### Notes

- Publish **`v1.6.5`** on GitHub with a **`RavenColonial_EDMC-v1.6.5.zip`** release asset so in-app auto-update can resolve the build.

### Added

- **`ui/themed_report_dialog.py`** — Themed modal (EDMC **`theme`** background + **`apply_theme_to_widget_subtree`**, GalaxyGPS-style **`tk`** controls) for plan-site refresh problems: short summary, scrollable detail, **OK**, and **Copy Error Msg** (clipboard includes title, summary, and detail for bug reports).

### Changed

- **Plan sites errors vs combobox** — Long HTTP / exception text is no longer placed inside the **Select Plan Site** control (which stretched the EDMC window). Failures open the themed dialog; the combobox shows a short label such as **`Plan sites error`** (or **Not Architect** when the architect gate fails).
- **`check_existing_project(..., force=False|True)`** — After one “no **`buildId`**” outcome for a dock slot, further probes skip **`GET /api/system/...`** until **`invalidate_project_location_cache()`** or **`force=True`** (used immediately before **Create Build Project** and **Link Build Site**) so depot/UI refresh does not hammer the API.
- **`get_project(..., use_location_cache=True)`** — Caches successful payloads only (never caches **`None`**) so a project that appears right after “no project” is not hidden for the positive-cache TTL.
- **Main-tab create / link** — **`resolve_build_id`** for **`buildId`** / **`BuildId`** / **`build_id`**; **Open Build Page** binds the resolved id to the click handler. Docked button state is computed in **`_resolve_docked_create_button_plan`** then applied in **`_apply_docked_create_button_plan`**.
- **`GET /api/system/...` normalization** — **`active_project_from_system_location_json`** unwraps common wrapper keys and alternate id spellings via **`resolve_build_id`** (see **`api/client.py`**).
- **Create Project dialog** — On successful **`create_project`**, sets **`current_build_id`** from the response and calls **`update_create_button()`** so the main tab can switch to **Open Build Page** without waiting for the next journal event.
- **Project-at-dock lookup** — Removed the client-side **`GET /api/v2/system/.../sites`** merge into the location project result; the backend is treated as authoritative for **`GET /api/system/{id64}/{marketId}`**.

### Fixed

- **Main tab after successful Create Project** — **`update_create_button()`** runs when the create dialog succeeds so **Open Build Page** appears without waiting for unrelated journal ticks.

## [1.6.4] - 2026-05-11

### Fixed

- **Auto-update on Windows (`WinError 32`)** — Before replacing the plugin folder, **`run_autoupdate()`** now calls **`capi_cache.stop()`** and **`plugin_file_log.stop_issue_log()`** so **`capi_cache/`** JSON and **`logs/RavenColonial_EDMC.log`** are not locked during **`shutil.move`** (same handles that **`plugin_stop`** releases on unload).
- **“Update available” banner** — Remote **`tag_name`** already includes a leading **`v`**; the banner template also prefixed **`v`**, which showed **`vv1.6.x`**. Display strings strip one leading **`v`** before formatting.
- **Manual auto-update error dialog** — Long exception text (paths, tracebacks) passed to **`plug.show_error`** could widen the EDMC window; user-facing detail is shortened while the full error remains in the log.

### Changed

- **Main-tab status line** — **`ttk.Label`** uses **`wraplength`** (and horizontal fill) so status messages wrap instead of stretching the layout.
- **Select Plan Site** — Replaced **`ttk.Combobox`** with a **`ThemedCombobox`** (**`ui/themed_combobox.py`**, same pattern as GalaxyGPS Fleet Carrier): **`tk.Entry`** + dropdown **`Listbox`** so EDMC light/dark themes paint correctly on Windows (no bright **`ttk`** field). Collapsed width is sized to the visible label; the open list uses measured width for long site lines.
- **Plan-site theme pass** — **`apply_theme_styling()`** follows GalaxyGPS (manual prelude → **`theme.update(frame, entry, button)`**); **`disabled`** placeholder states (short messages such as “please refresh” / error hints) set **`disabledbackground`** / **`disabledforeground`** from the entry colors EDMC applies so the field matches the Fleet Carrier row in default and dark themes.

### Notes

- Publish **`v1.6.4`** on GitHub with a **`RavenColonial_EDMC-v1.6.4.zip`** release asset so in-app auto-update can resolve the build.

## [1.6.3] - 2026-05-06

### Added

- **Link Build Site** — `PUT /api/project` includes **`architectName`** from the EDMC commander (`cmdr_name`, **`cmdr_snapshot`** fallback). Link does not start if the commander name is not known yet.
- **Duplicate-build safeguards (Link Build Site)** — live **`GET /api/v2/system/{id64}/sites`** before **`PUT`**; if the selected **`systemSiteId`** is no longer **`plan`**, linking stops with a clear message.
- **Completion hints on `404`** — **`completed_project_hint_from_system_location_json()`** in **`api/client.py`** detects completion-style payloads on **`GET /api/system/{id64}/{marketId}`** (e.g. **`complete: true`**, or **`status`** / **`buildStatus`** indicating complete/finished) when the server returns **`404`** with a JSON object; Link Build Site treats that as “already completed” and does not **`PUT`**.
- **Project lookup cache** — **`RavencolonialPlugin`** caches **`GET /api/system/...`** briefly (**4s TTL**) for UI and journal paths that only need a stable snapshot; **`invalidate_project_location_cache()`** on undock, after **`create_project`**, and after a successful link.

### Changed

- **`GET /api/system/{id64}/{marketId}`** — **`active_project_from_system_location_json()`** normalizes responses: “no active project” strings / ProblemDetails-style bodies are **not** treated as projects unless **`buildId`** is present (including some HTTP **200** cases).
- **`RavencolonialAPIClient.get_project()`** — parses **`404`** bodies; may return a completion-hint dict instead of always **`None`** on **`404`**.
- **Link Build Site worker** — non-**404** **`GET /api/system/...`** errors report **`http_error`** (no blind **`PUT`**); **`404`/`200`** bodies use the same parsers as **`get_project()`**.
- **Main-tab create button** — **Open Build Page** only when the resolved project dict includes **`buildId`**.
- **Construction depot supply** — skips enqueueing **`POST /api/project/{buildId}`** when the supply payload matches the last queued update (same normalized JSON). Depot resolution uses **`get_project(..., use_location_cache=False)`**; **`construction_completion`** also uses an uncached **`get_project`** before **`POST .../complete`**.
- **Fewer redundant project GETs** — **`check_existing_project`**, **`CargoDepot`** status path, and **`ColonisationContribution`** use **`get_project(..., use_location_cache=True)`** where appropriate.
- **CAPI on-disk snapshot retention** — **`capi_cache.py`** keeps the **3** newest timestamped **`snapshot_<kind>_*.json`** files per kind (v1.6.2 documented **40**; this release intentionally tightens disk use). **`squadron`** Companion payloads may be written like the other kinds; **`capi_cache.write()`** accepts optional **`source_host`** / **`request_cmdr`** for envelope **`meta`**.

### Fixed

- **False “project exists”** — dicts without **`buildId`** no longer imply an active project for the create button / **`get_project()`** consumers.
- **Duplicate link/create after completion** — mitigated when **`/api/system/...`** still says “no active project” but the plan site has moved past **`plan`**: sites preflight blocks **`PUT /api/project`**.
- **Undocked status text** — main-tab status uses the journal **`Undocked`** event’s **`StationName`** (with EDMC’s **`station`** argument as fallback). EDMC clears **`monitor.state['StationName']`** before **`journal_entry`**, so the third argument is **`None`** on undock; the previous logic showed **“Undocked from None”**.
- **Link Build Site double-click** — while a link worker is running, the main action button is disabled and a second click is ignored, avoiding overlapping `**GET`/`PUT`** sequences that could race before the server reflects the first **`PUT`**.

### Documentation

- **`docs/ACTION_MAP_API_FLOWS.md`** — journal/API map aligned with normalized **`/api/system/...`**, **`404`** completion hints, Link Build Site flow (**`/sites`** preflight, **`architectName`** on **`PUT`**).
- **`README.md`** — Features table and **Plan sites and Link Build Site** usage (architect refresh, link payload, plain-language safety checks before linking); pointer to **`ACTION_MAP_API_FLOWS.md`** for technical detail.

### Notes

- Publish **`v1.6.3`** on GitHub with a **`RavenColonial_EDMC-v1.6.3.zip`** release asset so in-app auto-update can resolve the build. For a **rerelease** of the same tag, replace the zip on the existing **`v1.6.3`** release (or delete and recreate the release) so the asset name stays **`RavenColonial_EDMC-v1.6.3.zip`** for auto-update matching.

## [1.6.2] - 2026-05-03

### Added

- **Plugin issue log** — rotating file **`logs/RavenColonial_EDMC.log`** under the plugin install directory (same handler attached to main, `**.api`**, `**.fc`**, and other plugin module loggers so API and FC traffic appear even with **`propagate=False`**). Initialized in **`plugin_start3`**; closed on **`plugin_stop`**. See README troubleshooting for paths to attach on GitHub issues.
- **CAPI snapshot cache** — on each EDMC refresh, **`cmdr_data`**, **`cmdr_data_legacy`**, and **`capi_fleetcarrier`** enqueue a deep-copied payload; a background thread writes **`latest_<kind>.json`** and timestamped **`snapshot_<kind>_*.json`** under **`<plugin_dir>/capi_cache/`** (envelope includes `meta`: kind, UTC time, `is_beta`, `source_host`, `request_cmdr`). Prunes to the 40 newest snapshots per kind. **`plugin_stop`** drains the writer thread before unload. `**.gitignore**` includes **`capi_cache/`** so dumps stay local.

### Changed

- **Fleet Carrier journal logic (SrvSurvey parity)** — detect squadron fleet carriers via journal **`StationServices`** containing **`squadronBank`**; **`CargoTransfer`** uses main-ship vs SRV branching like SrvSurvey and skips branch-A deltas on squadron FCs; `**MarketBuy`/`MarketSell**` set a one-shot skip for the follow-up **`Cargo`** resync; forced **`Cargo`** (no full inventory in the event) can apply an inverted commander-hold diff to **`/api/fc/{marketId}/cargo`** when docked on a linked squadron FC after a full **`Cargo`** baseline. **`Location`** / **`Undocked`** refresh FC dock context and services.
- **License** — project relicensed under **MIT**; added root **`LICENSE`** file, **`pyproject.toml`** `license` metadata, and **`README`** badge + wording (EDMC remains under its own upstream license).
- **README** — reorganized badges (CI / security / release / license; community; runtime & downloads).

### Fixed

- **Update UI theming** — main-window update banner and controls use **`ttk`** (and EDMC **`HyperlinkLabel`** for the project link when available) so colors match EDMC light/dark and custom themes instead of classic **`tk`** defaults. **Create Project** dialog: **`tk.Text`** Notes field takes `**TEntry`/`TLabel`** colors from **`ttk.Style`**, Toplevel **`bg`** matches **`TFrame`**; column weights for resize. **`plugin_app`** fallback uses **`ttk.Frame`**. Settings tab: GitHub URL uses **`HyperlinkLabel`** instead of hard-coded blue.

### Notes

- Publish **`v1.6.2`** on GitHub with a **`RavenColonial_EDMC-v1.6.2.zip`** release asset so in-app auto-update can resolve the build. For a **rerelease** of the same tag, replace the zip on the existing **`v1.6.2`** release (or delete and recreate the release) so the asset name stays **`RavenColonial_EDMC-v1.6.2.zip`** for auto-update matching.

## [1.6.1] - 2026-05-01

### Added

- **Commander ship snapshot** — `POST /api/cmdr/currentShip` (SrvSurvey-compatible body: commander, ship name/type, `maxCargo`, normalized `cargo` map), authenticated with **`rcc-key`** only. Driven from journal **`Cargo`**, **`Loadout`** (main ship), and **`SetUserShipName`**, with EDMC **`state`** for `CargoCapacity` / ship identity; deduplicated queue to the background API worker.
- **Stealth: commander ship cargo** — config **`ravencolonial_stealth_ship_cargo`**: when enabled, skips publishing the commander ship snapshot (independent of Fleet Carrier stealth).
- **Stealth: all construction delivery reporting** — config **`ravencolonial_stealth_construction_reporting`**: when enabled, skips **`ColonisationConstructionDepot`**, **`ColonisationContribution`**, and **`CargoDepot`** journal paths that update Ravencolonial (Create Project from the dialog is unchanged).
- **Plugin UI localization** — all user-facing strings go through EDMC **`l10n`** (**`i18n.py`** + **`tr`** / **`trf`**). **`L10n/en.template`** defines English keys; **`L10n/*.strings`** cover the same locale set as core EDMC except the parody **`uwu`** locale (machine-translated for most languages; **`sr-Latn`*** use a Latin-script placeholder with a header note). Maintainer regen: **`scripts/generate_plugin_l10n.py`** (`deep-translator`; **`--resume`**, **`--only`**).
- **Show API Key** — Ravencolonial settings tab checkbox (default off) toggles the API key field between masked and visible entry.
- **`scripts/clean_build_artifacts.py`** — remove **`dist/`**, **`__pycache__/`**, egg metadata, and setuptools outputs under **`build/`** while **preserving `build/release/`** (release zips). Optional **`--include-stray-root-zips`** only affects legacy zips in the repo root.

### Removed

- **Dock-to-dock CSV logger** (**`d2d_logger.py`**) — local **`~/Documents/d2dTimes.csv`** timing log removed; no API or website impact.

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
- **`get_market_data()`** (**`load.py`**) — open market JSON with **`encoding="utf-8"`** for consistent decoding across platforms.

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
- **Ravencolonial HTTP client** (`api/client.py`): FC cargo uses `**rcc-key` only** (matches [SrvSurvey](https://github.com/njthomson/SrvSurvey)); **lowercase** `/api/system`, `/api/cmdr`, `/api/fc` paths; **`buildId`** path segments **URL-encoded** on contribute and project supply POSTs; **`create_project`** uses **debug/info** logging for normal traffic (errors only on HTTP failure / exceptions); duplicate **`logger.error`** pairs on several failure paths consolidated.
- **Version compare**: removed duplicate **`compare_versions`** from `load.py`; prefs “check for updates” uses **`version_check.compare_versions(..., logger)`** so behavior matches auto-update (including prerelease vs stable when versions tie).
- **`get_system_sites`**: optional **`name_or_num`** (system name or id64); when omitted, still resolves **`current_system_address`** via journal/state. **`get_system_bodies`** / **`get_system_architect`** and v2 **`nameOrNum`** URLs use the same escaped segment rules as SrvSurvey.
- **`get_system_address_from_journal`**: prefers EDMC `**state`’s** `SystemAddress`; journal fallback scans recent files for the **latest** **`Docked`** or **`Location`** with **`Docked: true`** by **timestamp** (not only the first reversed hit in one file).
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

- For that release line, publish a **`RavenColonial_EDMC-v1.6.0.zip`** asset on GitHub so auto-update can resolve the build (see newer release notes for the current artifact name).

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
