# Ravencolonial EDMC

## Welcome

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app “check for updates” and manual installs stay in sync.

**Install this version:** download **`RavenColonial_EDMC-v1.6.7.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC’s plugins directory, and restart EDMC (paths for Windows, Linux, and macOS are in the repo **README**). The running plugin reports **v1.6.7** in settings and to EDMC’s plugin browser.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** → **[1.6.7] - 2026-05-24**.

---

### What’s new in **v1.6.7**

- **Link Build Site commodities** — After a successful link, the Ravencolonial build page should show required commodities right away (same depot data as **Create Project**). You should not need to undock and redock first.
- **Link Build Site naming** — Linked projects use your in-game dock name for **`buildName`**, not the pre-generated plan codename.
- **Link Build Site body** — **Edit project** on Ravencolonial should show the correct **body** from your plan site (moon/orbital assignment from the system planner), not an empty field after link.
- **Plan-site dropdown** — The linked site disappears from **Select Plan Site** as soon as link succeeds.
- **Depot sync (PATCH)** — Construction depot updates from the journal use **PATCH** with the full depot snapshot for remaining need (same model as create/link). Delivery history still uses **contribute** only.
- **Phantom `?` commodity rows** — Template slots Ravencolonial seeds at **‑1** on link are cleared to **0** when the plugin already has a project response in hand.

---

### Highlights from **v1.6.6** (still included)

- **Plan-site architect detection (hotfix)** — If you are the system architect but **Select Plan Site** only showed **orbital** rows (no surface sites, no **Create New**), the plugin now unwraps double-encoded commander names from Ravencolonial’s **`/architect`** endpoint before comparing to your EDMC commander.

---

### Earlier **1.6.2–1.6.5** (still part of today’s plugin)

- **Plan-site refresh UX (1.6.5)** — Failures open a **themed** error dialog with **Copy Error Msg**; the combobox keeps a **short** label. Non-architects still see **orbital** plan rows only; architects see all **plan** rows plus **Create New** when detection succeeds.
- **Dock / project detection (1.6.5)** — **`resolve_build_id`**, throttled **`check_existing_project`**, positive-cache **`get_project`**, Create/Link re-check before starting; **Create Project** success updates **Open Build Page** immediately; dock lookup treats location **`GET`** as authoritative.
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

Thanks to everyone who used and contributed to earlier versions of this plugin (including upstream authors and CMDRs who reported issues). This line of releases keeps colonization tracking, Fleet Carriers (personal and squadron when linked), commander ship context, and Ravencolonial in sync—while tightening plan-site refresh, link/create depot sync, auto-update on Windows, and everyday UI behavior.

If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version and what you were doing in-game when it happened.
