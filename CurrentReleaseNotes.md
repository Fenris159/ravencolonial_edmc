# Ravencolonial EDMC v1.8.1-rc.4 Pre-release

## Pre-release / Active Development Build

This release is intended for active validation from the `development` branch before it is promoted to the normal stable release path. GitHub should show this build as a **Pre-release**. In-app update checks should only offer it to users who enable **Include pre-release versions** in the RavenColonial EDMC settings.

Use this build when you are comfortable testing release-candidate behavior and reporting issues. Stable users should stay on the latest non-prerelease GitHub Release unless they are intentionally helping test.

## Welcome

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app update checks and manual installs stay in sync.

**Install this pre-release:** download **`RavenColonial_EDMC-v1.8.1-rc.4.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC's plugins directory, and restart EDMC. The running plugin reports **v1.8.1-rc.4** in settings and to EDMC's plugin browser.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** -> **[1.8.1-rc.4] - 2026-06-23**.

---

## What's New in v1.8.1-rc.4 Pre-release

- **Edit Carrier Manifest** - A new theme-aware button opens a separate editor for linked Fleet Carriers. Pick a callsign, edit cached commodity totals, remove commodities, or add missing commodities from a filtered scrollable list. **Save** stays disabled until the manifest changes.
- **Manual full-manifest save** - Saving the editor sends a full cargo replacement to `POST /api/fc/{marketId}/cargo`, then refreshes the local cache from the server response so the overlay and later deltas use the same totals.
- **Startup while docked** - If EDMC starts while you are already docked at an eligible Fleet Carrier, the plugin initializes the same dock-baseline workflow it uses after a normal dock event.
- **Server/cache baselines** - Elite does not provide a complete local Fleet Carrier manifest through journal files. The plugin now treats RavenColonial server snapshots and accepted undocked CAPI snapshots as baseline sources, then maintains the cache through journal cargo deltas.
- **Queued dock-time deltas** - When a docked carrier has no usable cached manifest, cargo deltas wait while `GET /api/fc/{marketId}` loads the server baseline, then replay after the baseline completes.
- **Current ship cargo diagnostics** - Debug logs now include the cargo movement, timestamp, total, and `POST /api/cmdr/currentShip` payload summary used for in-flight cargo tracking.

---

## Testing

The full local test suite passed for this pre-release candidate with **193 passed, 1 skipped**.

---

## Thank You

Thanks to everyone who reports issues and helps improve the plugin. If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version, update path, whether you are using EDMCModernOverlay or Popout Tracker, and what you were doing in-game when it happened.
