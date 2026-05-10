## Welcome — Ravencolonial EDMC

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app “check for updates” and manual installs stay in sync.

**Install this version:** download **`RavenColonial_EDMC-v1.6.3.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC’s plugins directory, and restart EDMC (paths for Windows, Linux, and macOS are in the repo **README**). The running plugin reports **v1.6.3** in settings and to EDMC’s plugin browser.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** → **[1.6.3] - 2026-05-06**.

---

### What’s new in **v1.6.3**

- **Link Build Site** — **`PUT /api/project`** sends **`architectName`** from your commander (when EDMC has provided it). Linking does not start without a known commander name.
- **Safer linking** — Before **`PUT`**, the plugin calls **`GET /api/v2/system/{id64}/sites`**. If the selected plan site is no longer in **`plan`** state, linking stops with a clear message instead of creating a duplicate or bad link.
- **Completed builds** — When **`GET /api/system/{id64}/{marketId}`** returns **`404`** with JSON that indicates the build is already finished, the plugin treats that as completion and does not **`PUT`** again.
- **Clearer “active project” handling** — Responses from **`/api/system/...`** are normalized so empty or non-project bodies are not mistaken for a real project unless **`buildId`** is present. The main-tab **Open Build Page** action only appears when a resolved project includes **`buildId`**.
- **Less API noise** — A short (**4s**) in-memory cache for **`GET /api/system/...`** where a stable snapshot is enough; cache is cleared on undock, after create, and after a successful link. Construction depot **`POST`** skips when the payload matches the last queued update. Some paths still force a fresh **`get_project`** where correctness matters (depot resolution, completion).
- **Undock status** — After **Undocked**, the status line shows the station you left (from the journal line), not **“Undocked from None”**.

**Docs** — **`docs/ACTION_MAP_API_FLOWS.md`** and **README** plan-site / Link Build Site sections are updated for this flow.

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

Thanks to everyone who used and contributed to earlier versions of this plugin (including upstream authors and CMDRs who reported issues). This release line keeps the same in-game goals—colonization tracking, Fleet Carriers (personal and squadron when linked), commander ship context, and Ravencolonial—while improving safety around linking, API clarity, and day-to-day UI messages.

If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version and what you were doing in-game when it happened.
