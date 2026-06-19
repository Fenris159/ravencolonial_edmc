# Ravencolonial EDMC

## Welcome

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app update checks and manual installs stay in sync.

**Install this version:** download **`RavenColonial_EDMC-v1.8.0.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC's plugins directory, and restart EDMC. The running plugin reports **v1.8.0** in settings and to EDMC's plugin browser.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** -> **[1.8.0] - 2026-06-19**.

---

### Highlights in **v1.8.0**

- **Build tracker popout** - Use **Enable Popout** to open the build tracker in a separate EDMC window instead of the in-game overlay. It shows the same selected build, **Track All**, ship cargo, carrier tracking, assignment hints, trip footer, and Fleet Carrier jump countdown.
- **Cleaner tracker mode switch** - When the popout is active, **Enable Overlay** is replaced by **Popout Tracker** and **Always On** is hidden. Refresh, search, build selection, Track All, and carrier tracking stay available.
- **Theme-aware Oxanium rendering** - The popout follows the EDMC theme and uses the bundled Oxanium font where Tk can register it, so it remains readable without EDMCModernOverlay.
- **Localized popout controls** - The new popout labels are translated across the shipped locale files.

---

### Highlights from **v1.7.9** (still included)

- **Auto-update integrity check** - The updater rejects incomplete release packages before they can replace the live plugin, preventing the broken restart path that triggered the hotfix.
- **Manual install prompt** - When auto-update fails, the plugin points commanders to the manual installation steps in `docs/MANUAL_UPDATE_INSTRUCTIONS.md`.

---

### Highlights from **v1.7.8** (still included)

- **Fleet Carrier jump countdown** - Schedule a carrier jump and the tracker footer shows a live departure countdown as the **last row**, with BGS-Tally-style sub-lines for jump initiation, pad lockdown, and pads locked. Cancelling a jump shows a 60-second cooldown; the tracker updates every second while a timer is active.
- **Collapsible plugin panel** - Use the chevron on the **Ravencolonial** header to collapse the main-tab body to one row when you need more EDMC space; top and bottom dividers stay visible while collapsed.
- **Overlay refresh failure handling** - A failed build-project search no longer leaves the dropdown stuck on `Build projects error`. Empty search still shows the existing popup, but the combobox stays on `Please Refresh` instead of changing to an error state.
- **Build-project fallback display** - When a normal tracker refresh fails but the system context is known, the dropdown can fall back to `No Build Projects` instead of interrupting the UI with a blocking error path.
- **Non-modal status line** - Tracker refresh failures now log and update the local state without forcing a modal status interruption in the main UI flow.

---

### Highlights from **v1.7.5 - v1.7.6** (still included)

- **Track All tracker mode** - The build-project picker offers **Track All** as the first active option. It aggregates remaining commodities across every active build project in the refreshed list.
- **Aggregate carrier tracking** - In Track All, linked carriers from all tracked projects are combined and deduplicated. You can still view **All** carriers or select one callsign.
- **Event-driven refresh** - Local construction depot journal updates keep the docked project live. After construction-depot or fleet-carrier activity, the next undock refreshes all Track All project details so other commanders' background changes are folded in without polling.
- **Dropdown hotfix** - **Select Build Project** stays at the top, **Track All** appears directly below it, and larger themed dropdown lists remain visible.

---

### Notes

Track All does not continuously poll Ravencolonial. Use refresh when you want an immediate network update, or let the event-driven refresh run after the next qualifying construction-depot or fleet-carrier undock.

EDMCModernOverlay is still required for the in-game HUD. The new popout tracker is an EDMC-native alternative when you want the same tracker table in a separate themed window.

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

Thanks to everyone who reports issues and helps improve the plugin. **v1.8.0** adds a popout build tracker for commanders who want the overlay table outside Elite or cannot use the external overlay stack.

If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version, whether you are using EDMCModernOverlay or Popout Tracker, and what you were doing in-game when it happened.
