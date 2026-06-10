# Ravencolonial EDMC

## Welcome

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app check for updates and manual installs stay in sync.

**Install this version:** download **`RavenColonial_EDMC-v1.7.4.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC's plugins directory, and restart EDMC. The running plugin reports **v1.7.4** in settings and to EDMC's plugin browser.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** -> **[1.7.4] - 2026-06-10**.

---

### What's new in **v1.7.4**

- **Persistent site repair cache** - The rolling last-50 site repair cache now survives plugin reloads in `site_market_id_repair_visits.json`.
- **Successful repairs only** - The cache records `(MarketID, normalized station name)` only after a successful site repair PATCH. Failed/no-match checks can be retried later without restarting EDMC or waiting for the rolling cache to evict them.

---

### Highlights from **v1.7.3** (still included)

- **Targeted site repair update** - Re-docking at a finished station still uses the conservative v1.7.2 matching rules, but the write uses `PATCH /api/v2/system/{nameOrNum}/sites/{siteId}` instead of the older bulk `/sites` PUT.
- **MarketID-only payload** - Name-matched MarketID repairs send only the journal `MarketID` as `marketId`.
- **Name repair fallback** - When a site already has the correct journal `MarketID` but a generic or stale Ravencolonial name, the same repair flow can patch only the site `name`. Duplicate `marketId` rows are skipped.
- **ID64 system routing** - The repair uses the journal `SystemAddress` ID64 for the system route whenever it patches the matched Ravencolonial site row.

---

### Highlights from **v1.7.2** (still included)

- **MarketID repair at finished stations** - Re-dock at the finished station, not the construction depot. Matching uses normalized station name only and skips duplicate names as a safety guard.
- **Construction complete reminder** - When a project finishes, the status line tells you to re-dock at the finished location so Market Info can be updated.

---

### Highlights from **v1.7.1** (still included)

- **Cerulean Gold overlay theme**, themed combobox fixes, overlay UI polish, **Oxanium** header font on Windows, plugin-tab startup and Linux dialog fixes, and the initial legacy MarketID repair path.

---

### Highlights from **v1.7.0** (still included)

- **Build tracker overlay** - On-screen HUD for a selected colonization build via **[EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay)**.
- **Main-tab overlay controls** - Enable Overlay, Always On, Select Build Project, refresh, and optional Enable Carrier Tracking.
- **HUD polish** - Six color themes, commodity categories, row shading, column dividers, trip footer, fulfilled commodities hidden, and zero ship cargo shown blank.

---

### Thank you

Thanks to everyone who reports issues and helps improve the plugin. **v1.7.4** keeps the targeted finished-station repair flow and makes its recent-repair cache persistent without blocking retries after failed matches.

If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version, whether EDMCModernOverlay is installed, and what you were doing in-game when it happened.
