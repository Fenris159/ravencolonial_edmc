# Ravencolonial EDMC

## Welcome

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app check for updates and manual installs stay in sync.

**Install this version:** download **`RavenColonial_EDMC-v1.7.6.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC's plugins directory, and restart EDMC. The running plugin reports **v1.7.6** in settings and to EDMC's plugin browser.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** -> **[1.7.6] - 2026-06-14**.

---

### Hotfix in **v1.7.6**

- **Track All dropdown order** - **Select Build Project** stays at the top as the placeholder, **Track All** now appears directly below it, and individual build projects follow.
- **Dropdown height** - The themed dropdown no longer caps its popup height at 200px, so larger build lists are visible instead of hiding entries without a scrollbar.

---

### Highlights from **v1.7.5** (still included)

- **Track All overlay mode** - The build-project picker now offers **Track All** as the first active option. It aggregates remaining commodities across every active build project in the refreshed list.
- **Aggregate carrier tracking** - In Track All, linked carriers from all tracked projects are combined and deduplicated. You can still view **All** carriers or select one callsign.
- **Event-driven refresh** - Local construction depot journal updates keep the docked project live. After construction-depot or fleet-carrier activity, the next undock refreshes all Track All project details so other commanders' background changes are folded in without polling.
- **Completed project handling** - Completed projects drop out of Track All totals while the remaining projects continue tracking.

---

### Notes

Track All does not continuously poll Ravencolonial. If another commander changes a different project while you are not at that depot, the overlay picks that up on manual refresh, plan-location refresh, or the event-driven Track All refresh after qualifying construction-depot/fleet-carrier undock.

---

### Highlights from **v1.7.4** (still included)

- **Persistent site repair cache** - The rolling last-50 site repair cache survives plugin reloads in `site_market_id_repair_visits.json`.
- **Successful repairs only** - The cache records `(MarketID, normalized station name)` only after a successful site repair PATCH.

---

### Highlights from **v1.7.3** (still included)

- **Targeted site repair update** - Re-docking at a finished station uses conservative matching rules, but writes through targeted `PATCH /api/v2/system/{nameOrNum}/sites/{siteId}` instead of the older bulk `/sites` PUT.
- **MarketID-only payload** - Name-matched MarketID repairs send only the journal `MarketID` as `marketId`.
- **Name repair fallback** - When a site already has the correct journal `MarketID` but a stale Ravencolonial name, the same repair flow can patch only the site `name`.

---

### Highlights from **v1.7.0 - v1.7.2** (still included)

- **Build tracker overlay** - On-screen HUD for colonization builds via **[EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay)**.
- **Finished-site Market Info repair** - Re-dock at the finished location after construction completes so Market Info can be updated.
- **Cerulean Gold overlay theme**, themed combobox fixes, overlay UI polish, Oxanium header font on Windows, plugin-tab startup and Linux dialog fixes.

---

### Thank you

Thanks to everyone who reports issues and helps improve the plugin. **v1.7.6** is a small hotfix for the Track All dropdown introduced with multi-project overlay tracking.

If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version, whether EDMCModernOverlay is installed, and what you were doing in-game when it happened.
