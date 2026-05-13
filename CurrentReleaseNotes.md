# Ravencolonial EDMC

## Welcome

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app “check for updates” and manual installs stay in sync.

**Install this version:** download **`RavenColonial_EDMC-v1.6.5.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC’s plugins directory, and restart EDMC (paths for Windows, Linux, and macOS are in the repo **README**). The running plugin reports **v1.6.5** in settings and to EDMC’s plugin browser.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** → **[1.6.5] - 2026-05-13**.

---

### What’s new in **v1.6.5**

- **Plan-site refresh UX** — Failures (network, HTTP, missing commander context) open a **themed** error dialog with **Copy Error Msg** for bug reports; the **Select Plan Site** field keeps a **short** label so the EDMC window does not stretch. After refresh, **system architects** still get the full **plan** list plus **Create New**; **other commanders** see **orbital** plan rows only (aligned with the site’s orbital set), **no Create New**, and **No Orbitals** when that filtered list is empty—so helpers at an orbital construction dock are not offered incompatible surface-only picks.
- **Dock / project detection** — **`resolve_build_id`** accepts common **`buildId`** spellings and wrapped **`GET /api/system/...`** JSON; **`check_existing_project`** throttles repeated “no build” probes; **`get_project`** positive-cache behavior avoids hiding a project that appears right after a miss; **Create / Link** re-check the dock slot before starting. **Create Project** success updates **Open Build Page** immediately. Dock lookup treats the location **`GET`** as authoritative (no client merge from **`/sites`**).

---

### Earlier **1.6.2–1.6.4** (still part of today’s plugin)

- **Auto-update on Windows** — Folder replace releases **CAPI cache** and the **issue log** first to avoid **`WinError 32`** on locked files; update banner shows a single **`v`** prefix; long auto-update errors no longer blow out dialog width; main-tab status **wraps** cleanly.
- **Plan site row UI** — **ThemedCombobox** (EDMC-themed list) for **Select Plan Site** on Windows; plan-row styling matches other themed rows.
- **Link Build Site & API hygiene** — **`architectName`** on **`PUT`**, live **`/sites`** preflight, **`404`** completion hints, normalized **`/api/system/...`**, short-lived project GET cache, depot supply dedup, undock status shows the station name.
- **Fleet Carriers & diagnostics** — Squadron FC journal path (**`squadronBank`**), SrvSurvey-style cargo handling when docked on a linked squadron FC; optional **`capi_cache/`** snapshots; **`logs/RavenColonial_EDMC.log`** for support; main tab, update banner, settings link, and Create Project **Notes** follow EDMC theme where applicable.
- **Commander ship, privacy, localization** — Optional ship/cargo sync to Ravencolonial; **three** stealth toggles (FC / ship cargo / construction reporting); UI strings follow EDMC language when keys exist; optional **show API key** in settings.

---

### Fixes and polish you might notice

- **Settings** persist when you close EDMC’s settings with **OK**, even if you did not press Save inside the Ravencolonial tab first.
- **Custom API base URL** is honored instead of silently falling back to the default.
- **Create Project** — Clearer errors when the journal is behind the game or required fields are missing.
- **Market / JSON** files opened with UTF-8 consistently.

---

### Project & license

- **Open source:** the project is offered under the **MIT License** (see **`LICENSE`** in the zip and on the repo).

---

### Thank you

Thanks to everyone who used and contributed to earlier versions of this plugin (including upstream authors and CMDRs who reported issues). This line of releases keeps colonization tracking, Fleet Carriers (personal and squadron when linked), commander ship context, and Ravencolonial in sync—while tightening plan-site refresh, dock/project detection, auto-update on Windows, and everyday UI behavior.

If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version and what you were doing in-game when it happened.
