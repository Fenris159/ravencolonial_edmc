# Ravencolonial EDMC v1.8.0

## Welcome

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app update checks and manual installs stay in sync.

**Install this version:** download **`RavenColonial_EDMC-v1.8.0.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC's plugins directory, and restart EDMC. The running plugin reports **v1.8.0** in settings and to EDMC's plugin browser.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** -> **[1.8.0] - 2026-06-19**.

---

## What's New in v1.8.0

- **Popout Tracker** - Opens the build tracker in a separate EDMC window instead of the in-game overlay. It uses the same selected build, **Track All**, ship cargo, carrier tracking, assignments, footer lines, and Fleet Carrier jump countdown data as the HUD.
- **Mutually exclusive tracker modes** - **Enable Overlay** and **Popout Tracker** are separate choices. When Popout Tracker is active, **Enable Overlay** is hidden and **Always On** is removed. When Enable Overlay is active, Popout Tracker is hidden.
- **EDMC-dark popout window** - The popout keeps a dark custom window style no matter which EDMC theme is active. It uses the bundled **Oxanium** font where Tk can load it, dynamically resizes to fit changing contents, remembers its last position, and appears on the taskbar where supported.
- **Discord-friendly copy** - The popout title bar includes a copy button that places a fixed-width Discord code block on the clipboard. The copied table omits the **Ship** column, the **trips in this ship** footer row, and FC jump-timer rows, while keeping FC deficit text when carrier data is available.
- **Improved popout readability** - The popout numeric header uses `Need/Ship/FC` spacing and recomputes layout to avoid overlapping Oxanium text.
- **Default-theme dropdown fix** - Custom tracker dropdowns now keep the normal white entry background in EDMC's default theme, including disabled placeholder states such as `Please Refresh` and `Select carrier`.
- **Localized popout controls** - The new **Popout Tracker** label is translated across the shipped locale files.

---

## Relevant Existing Tracker Behavior

These are not new in v1.8.0, but they matter because Popout Tracker uses the same tracker engine as the in-game HUD:

- **Track All** aggregates remaining commodities across every active build project in the refreshed list.
- **Carrier tracking** can show **All** linked carriers or one selected callsign, including FC surplus/deficit values.
- **Event-driven updates** keep local construction depot and Fleet Carrier activity reflected without continuous background polling. Use refresh when you want an immediate network update.
- **Fleet Carrier jump countdown** can appear as the last tracker footer row in the HUD or popout when a jump is scheduled.

EDMCModernOverlay is still required only for the in-game HUD. **Popout Tracker** is the EDMC-native alternative when you want the same tracker table outside Elite or cannot use the external overlay stack.

---

## Thank You

Thanks to everyone who reports issues and helps improve the plugin. If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version, whether you are using EDMCModernOverlay or Popout Tracker, and what you were doing in-game when it happened.
