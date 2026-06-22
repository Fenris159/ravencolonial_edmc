# Ravencolonial EDMC v1.8.1-rc.3 Pre-release

## Pre-release / Active Development Build

This release is intended for active validation from the `development` branch before it is promoted to the normal stable release path. GitHub should show this build as a **Pre-release**. In-app update checks should only offer it to users who enable **Include pre-release versions** in the RavenColonial EDMC settings.

Use this build when you are comfortable testing release-candidate behavior and reporting issues. Stable users should stay on the latest non-prerelease GitHub Release unless they are intentionally helping test.

## Welcome

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app update checks and manual installs stay in sync.

**Install this pre-release:** download **`RavenColonial_EDMC-v1.8.1-rc.3.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC's plugins directory, and restart EDMC. The running plugin reports **v1.8.1-rc.3** in settings and to EDMC's plugin browser.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** -> **[1.8.1-rc.3] - 2026-06-22**.

---

## What's New in v1.8.1-rc.3 Pre-release

- **Fleet Carrier dock manifest priority** - When you dock at a linked carrier, the plugin compares the newest local `Market.json` manifest first. If it differs from the cache, the plugin sends a full carrier cargo replacement before applying later deltas.
- **Queued dock-time deltas** - Cargo moved while the dock baseline is still waiting on `Market.json` is buffered and replayed after the baseline comparison, so delayed journal writes do not cause skipped or out-of-order FC cargo patches.
- **CAPI freshness tightened** - Fleet Carrier CAPI cargo snapshots are ignored while docked. When undocked, CAPI must have a parseable timestamp, be newer than the server `lastRefresh` and local cache timestamp, and differ from the cache before it can send a full cargo replacement.
- **Server timestamp alignment** - Linked carrier reads now use RavenColonial's `lastRefresh` field from `/api/cmdr/{cmdr}/fc/all` and `/api/fc/{marketId}` as the primary server freshness timestamp.
- **Timestamp normalization** - CAPI, server, and local cache timestamps are normalized before comparison, covering `Z`, offset ISO strings, naive ISO strings, and numeric epoch values.
- **Local manifest timestamps** - When a dock manifest replaces the cache, its journal timestamp is preserved as the local cargo timestamp.

---

## Testing

The full local test suite passed for this pre-release candidate with **189 passed, 1 skipped**.

---

## Thank You

Thanks to everyone who reports issues and helps improve the plugin. If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version, update path, whether you are using EDMCModernOverlay or Popout Tracker, and what you were doing in-game when it happened.
