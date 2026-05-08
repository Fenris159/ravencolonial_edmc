## Welcome — releases under the new maintainer

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app “check for updates” and manual installs stay in sync.

**Install (latest published release):** download **`RavenColonial_EDMC-v1.6.2.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC’s plugins directory, and restart EDMC (paths for Windows, Linux, and macOS are in the repo **README**).

**Development build (1.6.3):** the repo and git tag **`v1.6.3`** carry **`plugin_version` 1.6.3** and the changes listed under **[CHANGELOG.md](CHANGELOG.md)** → **`[1.6.3] - Unreleased`**. There is **no** **`RavenColonial_EDMC-v1.6.3.zip`** on GitHub Releases until that version is published; clone or zip from **`main`** if you want to test **1.6.3** before release.

---

### What’s new in **v1.6.2**

- **Squadron fleet carriers** — Journal handling now recognizes **squadron** fleet carriers (e.g. **`StationServices`** including **`squadronBank`**) and applies **SrvSurvey-style** cargo logic when you are docked on a **linked** squadron FC—so buy/sell/transfer and forced **`Cargo`** resync behave like your personal carrier, as long as that hull is linked to your commander on Ravencolonial (**`/fc/all`**).
- **CAPI snapshot cache (for debugging / analysis)** — Each time EDMC delivers fresh Companion data, the plugin can write **`latest_*.json`** and rolling **`snapshot_*.json`** files under **`<plugin folder>/capi_cache/`** for **`cmdr_data`**, **`cmdr_data_legacy`**, and **`capi_fleetcarrier`**. Encoding and disk I/O run on a **background thread** so the EDMC UI thread stays responsive. The folder is **gitignored** in the repo and safe to delete locally if you do not need dumps.
- **Plugin issue log (for bug reports)** — A dedicated rotating log at **`<plugin folder>/logs/RavenColonial_EDMC.log`** captures this plugin’s own messages (including **API** and **fleet carrier** traffic), separate from EDMC’s main log. Attach it when you open a GitHub issue (see the **README** troubleshooting section for typical paths).
- **README** — Documents personal and **squadron** carrier linking, API key scope, the issue log, and the above behavior in plain language.

#### UI: matches EDMC light / dark and custom themes

These updates remove **classic `tk`** widgets (and hard-coded colors) where they made the Ravencolonial tab or settings look like the wrong palette next to the rest of EDMC.

- **Main plugin tab** — Status line, **Create build project** control, and the **“update available”** strip (message plus **Go to Download**, **Auto-Update**, **Dismiss**) now use **`ttk`** so they follow the same theme as core EDMC. The optional **project name** link uses EDMC’s **`HyperlinkLabel`** when available (same pattern as plugins like EDDN/Inara), instead of a plain label forced to blue.
- **Settings tab** — The **GitHub** URL under update settings is also a **`HyperlinkLabel`** with the notebook background, not a fixed **blue** foreground that breaks on dark themes.
- **Create Colonization Project** dialog — There is still no **`ttk`** multiline editor, so **Notes** stays a **`tk.Text`**, but its **background**, **text**, **insert**, and **selection** colors are taken from **`ttk.Style`** (**`TEntry`** / **`TLabel`**) so it reads like the single-line fields next to it. The dialog **Toplevel** uses the same **frame** background as **`ttk`**, and column weights let the form stretch cleanly when you resize the window.

---

### Highlights from **v1.6.1** (still part of the plugin today)

- **Commander ship and cargo** — With your Ravencolonial API key set, the plugin can sync your **current ship** (name, type, max cargo, and hold contents) to Ravencolonial, similar to other commander-oriented tools. Updates follow your journal when cargo, loadout, or ship name changes.
- **Clearer “Create build project” flow** — When you’re docked at a construction ship, the plugin refreshes depot data from the journal before submitting a project, and it **blocks** a create if the game hasn’t given a usable depot snapshot yet—so you get a clear “wait / re-dock” style message instead of a bad submission.
- **Three separate privacy toggles** — You can independently limit what leaves your machine:
  - **Fleet Carrier only** — stop sending FC commodity / CAPI stock updates.
  - **Commander ship cargo only** — stop sending the ship snapshot (FC and construction flows unchanged).
  - **Construction reporting only** — stop sending colonization depot, contribution, and related cargo-depot journal updates to Ravencolonial (the in-game Create Project dialog still works).
- **Plugin text follows EDMC’s language** — Buttons, labels, and messages in the Ravencolonial tab try to match the language EDMC is using, with English as the base and other locales filled in where available.
- **Optional “show API key”** — In settings you can temporarily show the key while you copy or verify it (off by default).
- **Smoother status and updates** — Successful update checks and routine status use the normal status line instead of looking like hard errors; real failures still surface clearly.
- **Safer in-app updates** — When the plugin installs an update ZIP from GitHub, it validates paths inside the archive before extracting, so a tampered zip cannot unpack files outside the plugin folder.

---

### Fixes and polish you might notice

- **UI theming (v1.6.2)** — Ravencolonial’s own tab, update banner, settings link, and Create Project **Notes** area respect EDMC’s current theme; see **“UI: matches EDMC…”** under **v1.6.2** above for detail.
- **Settings actually stick** when you close EDMC’s settings with **OK**, even if you didn’t hit Save inside the tab first (same fields as Save).
- **API base URL** — If you use a custom Ravencolonial API URL, it is read correctly instead of silently falling back to the default.
- **Create Project** — Better handling when the game’s journal is slightly behind what you see on screen, more reliable system address from the journal, and clearer errors when something is missing.
- **Market / JSON files** — Opened with consistent UTF-8 encoding so odd characters don’t break reads on some systems.
- **Removed** the old optional **dock-to-dock timing CSV** log under Documents; nothing on the website depended on it.

---

### Project & license

- **Open source:** the project is offered under the **MIT License** (see the **`LICENSE`** file in the zip and on the repo).

---

### Thank you

Thanks to everyone who used and contributed to earlier versions of this plugin (including upstream authors and CMDRs who reported issues). This release line keeps the same in-game goals—colonization tracking, Fleet Carriers (personal and squadron when linked), commander ship context, and Ravencolonial—while improving privacy, installs, and parity with tools like SrvSurvey.

If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version and what you were doing in-game when it happened.
