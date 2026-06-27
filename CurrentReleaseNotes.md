# Ravencolonial EDMC v1.8.1-rc.5 Pre-release

## Pre-release / Active Development Build

This release is intended for active validation from the `development` branch before it is promoted to the normal stable release path. GitHub should show this build as a **Pre-release**. In-app update checks should only offer it to users who enable **Include pre-release versions** in the RavenColonial EDMC settings.

Use this build when you are comfortable testing release-candidate behavior and reporting issues. Stable users should stay on the latest non-prerelease GitHub Release unless they are intentionally helping test.

## Welcome

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app update checks and manual installs stay in sync.

**Install this pre-release:** download **`RavenColonial_EDMC-v1.8.1-rc.5.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC's plugins directory, and restart EDMC. The running plugin reports **v1.8.1-rc.5** in settings and to EDMC's plugin browser.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** -> **[1.8.1-rc.5] - 2026-06-27**.

---

## What's New in v1.8.1-rc.5 Pre-release

- **Squadron Carrier cargo transfers** - Squadron Carriers linked to active RavenColonial projects now use the same marketId-based `CargoTransfer` handling as regular linked Fleet Carriers. A main-ship transfer to carrier increases Raven carrier cargo; a transfer from carrier decreases it.
- **No Squadron-only Cargo resync fallback** - The old inferred Cargo snapshot diff path was removed so direct `CargoTransfer`, `MarketBuy`, and `MarketSell` carrier updates cannot be applied a second time later.
- **MarketId-based carrier cargo path** - Linked carrier cargo changes continue to use `PATCH /api/fc/{marketId}/cargo` with signed deltas. There is no separate endpoint for Squadron Carriers.
- **Better CargoTransfer diagnostics** - Debug logs now show the docked marketId, update eligibility, transfer direction, SRV context, branch decision, and final cargo diff used for the RavenColonial carrier update.

---

## Testing

The full local test suite passed for this pre-release candidate with **213 passed, 1 skipped**.

---

## Thank You

Thanks to everyone who reports issues and helps improve the plugin. If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version, update path, whether you are using EDMCModernOverlay or Popout Tracker, and what you were doing in-game when it happened.
