# Ravencolonial EDMC

## Welcome

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app check for updates and manual installs stay in sync.

**Install this version:** download **`RavenColonial_EDMC-v1.7.7.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC's plugins directory, and restart EDMC. The running plugin reports **v1.7.7** in settings and to EDMC's plugin browser.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** -> **[1.7.7] - 2026-06-17**.

---

### Highlights in **v1.7.7**

- **Fleet Carrier cargo updates for active project carriers** - Fleet carriers linked to your active Ravencolonial projects are now included in the cargo-update eligibility list, along with carriers linked in your commander profile. Duplicate market IDs are collapsed, so the same carrier will not double-update.
- **Safer carrier cargo cache** - Ravencolonial server snapshots, CAPI snapshots, and journal cargo deltas now have clearer ownership. Full server snapshots replace the local manifest, CAPI cannot overwrite a newer non-empty server baseline without freshness evidence, and journal deltas keep the overlay view current. If a selected project-linked carrier has no local manifest yet, the overlay makes one guarded seed request and shows `sync` instead of a false negative deficit if cargo still cannot be loaded. A carrier refresh button can manually reload one selected carrier manifest, or all linked manifests when All is selected, with a live 60-second cooldown.
- **Track All overlay cache cleanup** - Track All and single-project carrier tracking now share the same local FC cargo manifests. Journal deltas update the matching tracked carrier rows without forcing background API refreshes during normal overlay redraws.
- **In-system plan-site refresh safety** - Plan-site candidates loaded by the non-search refresh are scoped to the current system and clear when you change systems, reducing the chance of linking a project row from another system.
- **Carrier capacity footer** - The selected-carrier capacity footer uses the local `fc_owner_capacity_cache.json` free-space cache only when a matching market ID exists, so missing capacity data simply hides that line.
- **API reference cleanup** - The API reference now documents the targeted v2 site repair PATCH route and uses cleaner same-file Markdown anchors for endpoint navigation.

---

### Highlights from **v1.7.5 - v1.7.6** (still included)

- **Track All overlay mode** - The build-project picker offers **Track All** as the first active option. It aggregates remaining commodities across every active build project in the refreshed list.
- **Aggregate carrier tracking** - In Track All, linked carriers from all tracked projects are combined and deduplicated. You can still view **All** carriers or select one callsign.
- **Event-driven refresh** - Local construction depot journal updates keep the docked project live. After construction-depot or fleet-carrier activity, the next undock refreshes all Track All project details so other commanders' background changes are folded in without polling.
- **Dropdown hotfix** - **Select Build Project** stays at the top, **Track All** appears directly below it, and larger themed dropdown lists remain visible.

---

### Notes

Track All does not continuously poll Ravencolonial. Use refresh when you want an immediate network update, or let the event-driven refresh run after the next qualifying construction-depot or fleet-carrier undock.

---

### Highlights from **v1.7.3 - v1.7.4** (still included)

- **Targeted site repair update** - Re-docking at a finished station uses conservative matching rules, but writes through targeted `PATCH /api/v2/system/{nameOrNum}/sites/{siteId}` instead of the older bulk `/sites` PUT.
- **Persistent site repair cache** - The rolling last-50 site repair cache survives plugin reloads in `site_market_id_repair_visits.json`.
- **MarketID/name repair payloads** - Name-matched MarketID repairs patch only `marketId`; unique marketId-matched stale-name rows can patch only `name`.

---

### Highlights from **v1.7.0 - v1.7.2** (still included)

- **Build tracker overlay** - On-screen HUD for colonization builds via **[EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay)**.
- **Finished-site Market Info repair** - Re-dock at the finished location after construction completes so Market Info can be updated.
- **Cerulean Gold overlay theme**, themed combobox fixes, overlay UI polish, Oxanium header font on Windows, plugin-tab startup and Linux dialog fixes.

---

### Thank you

Thanks to everyone who reports issues and helps improve the plugin. **v1.7.7** focuses on Fleet Carrier cargo safety, active-project carrier updates, and overlay cache correctness.

If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version, whether EDMCModernOverlay is installed, and what you were doing in-game when it happened.
