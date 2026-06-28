# Ravencolonial EDMC v1.8.1

## Welcome

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app update checks and manual installs stay in sync.

**Install this release:** download **`RavenColonial_EDMC-v1.8.1.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC's plugins directory, and restart EDMC. The running plugin reports **v1.8.1** in settings and to EDMC's plugin browser.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** -> **[1.8.1] - 2026-06-28**.

---

## What's New in v1.8.1

- **Squadron Carrier cargo transfers** - Squadron Carriers linked to active RavenColonial projects now use the same marketId-based `CargoTransfer` handling as regular linked Fleet Carriers. A main-ship transfer to carrier increases Raven carrier cargo; a transfer from carrier decreases it.
- **No Squadron-only Cargo resync fallback** - The old inferred Cargo snapshot diff path was removed so direct `CargoTransfer`, `MarketBuy`, and `MarketSell` carrier updates cannot be applied a second time later.
- **MarketId-based carrier cargo path** - Linked carrier cargo changes use `PATCH /api/fc/{marketId}/cargo` with signed deltas. There is no separate endpoint for Squadron Carriers.
- **Fleet Carrier manifest editor** - The main tab includes a theme-aware editor for linked carrier cached commodity totals, with guarded full-manifest saves through `POST /api/fc/{marketId}/cargo`.
- **Dock/startup cargo baselines** - Startup-while-docked and dock-time carrier cache handling use RavenColonial server or accepted CAPI snapshots as baselines, then maintain cargo through journal deltas.
- **Better diagnostics** - Debug logs include current ship cargo movement summaries and detailed `CargoTransfer` carrier update decisions.

---

## Testing

The full local test suite passed for this release with **213 passed, 1 skipped**. The full repository flake8 check passed with **0** errors.

---

## Thank You

Thanks to everyone who reports issues and helps improve the plugin. If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version, update path, whether you are using EDMCModernOverlay or Popout Tracker, and what you were doing in-game when it happened.
