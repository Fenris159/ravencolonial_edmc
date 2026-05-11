## Welcome — Ravencolonial EDMC

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app “check for updates” and manual installs stay in sync.

**Install this version:** download **`RavenColonial_EDMC-v1.6.4.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC’s plugins directory, and restart EDMC (paths for Windows, Linux, and macOS are in the repo **README**). The running plugin reports **v1.6.4** in settings and to EDMC’s plugin browser.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** → **[1.6.4] - 2026-05-11**.

---

### What’s new in **v1.6.4**

- **Auto-update on Windows** — In-app update replaces the whole plugin folder. The plugin now **closes the issue log and CAPI snapshot writer** before that step so Windows does not hit **`WinError 32`** (“file in use”) on **`logs/RavenColonial_EDMC.log`** or **`capi_cache/`** files.
- **Update banner version text** — The “update available” strip showed **`vv1.6.x`** because GitHub’s tag already starts with **`v`**. Display now uses a single **`v`** for current and remote versions.
- **Failed auto-update and the window width** — Very long error text could stretch the EDMC window; the message shown in the error dialog is shortened (details remain in the log).
- **Status line layout** — Main-tab status messages **wrap** instead of forcing a wide single line.

---

### Highlights from **v1.6.3** (still included)

- **Link Build Site** — **`PUT /api/project`** includes **`architectName`** when your commander name is known; **`GET /api/v2/system/{id64}/sites`** preflight; **`404`** completion hints; normalized **`/api/system/...`**; short-lived project GET cache; depot supply dedup; undock status shows the station name (see **CHANGELOG**).

---

### Highlights from **v1.6.2** (still included)

- **Squadron fleet carriers** — Journal handling recognizes squadron FCs (**`StationServices`** including **`squadronBank`**) and applies **SrvSurvey-style** cargo logic when docked on a **linked** squadron FC.
- **CAPI snapshot cache** — Optional **`capi_cache/`** dumps for debugging Companion payloads (**`latest_*.json`**, rolling snapshots) on a background thread.
- **Plugin issue log** — **`logs/RavenColonial_EDMC.log`** under the plugin folder for bug reports (see **README** troubleshooting).
- **UI theming** — Main tab, update banner, settings GitHub link, and Create Project **Notes** follow EDMC’s theme (**`ttk`** / **`HyperlinkLabel`** / styled **`tk.Text`** where applicable).

---

### Highlights from **v1.6.1** (still part of the plugin)

- **Commander ship and cargo** — Sync current ship to Ravencolonial when configured (journal-driven, similar to other commander tools).
- **Three privacy toggles** — Fleet Carrier only, commander ship cargo only, or construction reporting only.
- **Localized UI** — Ravencolonial strings follow EDMC’s language where keys exist.
- **Optional “show API key”** in settings.

---

### Fixes and polish you might notice

- **Settings** persist when you close EDMC’s settings with **OK**, even if you did not press Save inside the Ravencolonial tab first (same fields as Save).
- **Custom API base URL** is honored instead of silently falling back to the default.
- **Create Project** — Clearer errors when the journal is behind the game or required fields are missing.
- **Market / JSON** files opened with UTF-8 consistently.

---

### Project & license

- **Open source:** the project is offered under the **MIT License** (see **`LICENSE`** in the zip and on the repo).

---

### Thank you

Thanks to everyone who used and contributed to earlier versions of this plugin (including upstream authors and CMDRs who reported issues). This release line keeps the same in-game goals—colonization tracking, Fleet Carriers (personal and squadron when linked), commander ship context, and Ravencolonial—while improving safety around linking, API clarity, auto-update on Windows, and day-to-day UI messages.

If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version and what you were doing in-game when it happened.
