# Ravencolonial EDMC

## Welcome

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app “check for updates” and manual installs stay in sync.

**Install this version:** download **`RavenColonial_EDMC-v1.7.2.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC’s plugins directory, and restart EDMC (paths for Windows, Linux, and macOS are in the repo **README**). The running plugin reports **v1.7.2** in settings and to EDMC’s plugin browser.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** → **[1.7.2] - 2026-05-31**.

---

### What’s new in **v1.7.2** (hotfix)

**If you are on v1.7.1 and completed sites still lack Market Info, upgrade and re-dock at the finished outpost.**

- **MarketID repair actually works** — Re-dock at the **finished** station (not the construction depot). Matching now uses **normalized station name only**—v1.7.1 also required body alignment, which failed when finished `43…` stations, depot `396…` docks, and duplicate site names on the same body did not line up. Exactly one eligible `/sites` row gets your journal `MarketID`; skip rules, retries, and prefix gates are in **[CHANGELOG.md](CHANGELOG.md)** → **[1.7.2]**.
- **Construction complete reminder** — When a project finishes, the status line tells you to **re-dock at the finished location** so the repair can run. Translated for all supported EDMC languages.

---

### Highlights from **v1.7.1** (still included)

- **Cerulean Gold overlay theme**, themed combobox fixes, overlay UI polish, **Oxanium** header font on Windows, plugin-tab startup and Linux dialog fixes, initial (since-fixed) legacy MarketID repair — see **[CHANGELOG.md](CHANGELOG.md)**.

---

### Highlights from **v1.7.0** (still included)

- **Build tracker overlay** — On-screen HUD for a selected colonization **build** (Need, Ship cargo, optional FC column, trip estimates) via **[EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay)** (install separately; see **[docs/OVERLAY.md](docs/OVERLAY.md)**).
- **Main-tab overlay controls** — **Enable Overlay**, **Always On**, **Select Build Project**, ↻ refresh, and optional **Enable Carrier Tracking**.
- **HUD polish** — Six color themes (default **Elite Orange**), commodity categories, row shading, column dividers, trip footer; fulfilled commodities hidden; zero ship cargo shows blank.

---

### Highlights from **v1.6.8** and earlier (still included)

- **Commander ship cargo after station buys**, **depot sync retries**, **Link Build Site** improvements, plan sites, FC tracking, stealth toggles, auto-update, localization — See **[CHANGELOG.md](CHANGELOG.md)** for the full history.

---

### Thank you

Thanks to everyone who reports issues and helps improve the plugin. **v1.7.2** is an urgent hotfix: legacy MarketID backfill now works at finished stations, and completion messaging tells you to re-dock so the fix can run.

If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version, whether EDMCModernOverlay is installed, and what you were doing in-game when it happened.
