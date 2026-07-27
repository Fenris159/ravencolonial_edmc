# Changelog

All notable changes to the Ravencolonial EDMC plugin are documented in this file.

Release titles and dates are aligned with [GitHub Releases](https://github.com/Fenris159/ravencolonial_edmc/releases) when published there (using each release’s publish date in UTC, `YYYY-MM-DD`). Older entries may reference releases from the upstream fork history.

## [Unreleased]

- Nothing yet.

## [1.8.2-rc.1] - 2026-07-27

### Fixed

- **Build tracker demand list after project switch** — Selecting a different build project updates the overlay/popout commodity demand list from that project's cache, not the previously selected (or currently docked) project's remaining need. An EDMC restart is no longer required to clear a stale demand list.
- **Docked depot no longer drives display selection** — Live `ColonisationConstructionDepot` journal remaining-need is applied only as a **cache write** for the project that matches the depot market / build id. The HUD always reads the **selected** project from cache; docked state only controls overlay visibility (Always On / show while docked).

### Changed

- **Cache-driven tracker mental model** — Overlay and popout paint `overlay_project_cache` (or Track All aggregate from `overlay_project_cache_by_build_id`) for the current selection. Journal and successful depot PATCH responses update the matching build id entry via `apply_depot_update_to_cache` / scoped depot PATCH helper (`depot_overlay_sync`).
- **Construction complete** — Completion marks the matching cached project complete through the same scoped cache helper instead of relying on a live journal display override.

### Tests

- Regression coverage expects cache-only demand lists; live-journal display override expectations removed.

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

See git history prior to this entry for full 1.8.1-rc.x and older notes. Historical detail remains in repository history; this file was truncated in the RC bump commit only for the duplicate long tail already published with 1.8.1 — **restoring full history below**.
