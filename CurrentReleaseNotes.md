# Ravencolonial EDMC

## Welcome

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app “check for updates” and manual installs stay in sync.

**Install this version:** download **`RavenColonial_EDMC-v1.7.0.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC’s plugins directory, and restart EDMC (paths for Windows, Linux, and macOS are in the repo **README**). The running plugin reports **v1.7.0** in settings and to EDMC’s plugin browser.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** → **[1.7.0] - 2026-05-28**.

---

### What’s new in **v1.7.0**

- **Build tracker overlay** — Track a colonization **build** you pick on the Ravencolonial tab with an on-screen HUD (Need, Ship cargo, optional fleet-carrier column, assignment hints, and trip estimates). Powered by **[EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay)** (install separately; see **[docs/OVERLAY.md](docs/OVERLAY.md)** in the plugin folder).
- **Main-tab controls** — **Enable Overlay**, **Always On** to keep the HUD while undocked, **Select Build Project** for `build` sites in your current system, a dedicated **↻** refresh, and optional **Enable Carrier Tracking** (**All** or one linked carrier).
- **Easier to read HUD** — Five color themes (default **Elite Orange**), grouped commodity categories, alternating row shading, column dividers between Need / Ship / FC, and a trip footer (remaining tons and loads for your ship; FC deficit when tracking is on).
- **Less clutter** — Fulfilled commodities disappear from the list; zero ship cargo shows as blank instead of `0`.
- **Settings & UI** — Overlay theme picker and Modern Overlay dependency link; gear button opens plugin settings; header and panel separators on the main tab.

---

### Highlights from **v1.6.8** (still included)

- **Commander ship cargo after station buys** — Market buy/sell at normal stations updates Ravencolonial ship hold promptly; sparse **`Cargo`** journal lines no longer wipe the hold when EDMC is still catching up.
- **Depot sync when the API hiccups** — Construction depot **PATCH** can retry after timeouts without false “already synced” state; **contribute** avoids read-timeout retries so delivery history is not double-counted.

---

### Highlights from **v1.6.7** and earlier (still included)

- **Link Build Site** — Depot commodities and body on link, normalized dock **buildName**, plan row drops from the dropdown after link, **PATCH** depot sync, phantom **`?`** rows cleared.
- **Plan sites, FC tracking, ship snapshot, stealth toggles, auto-update, localization** — See **[CHANGELOG.md](CHANGELOG.md)** for the full history.

---

### Thank you

Thanks to everyone who reports issues and helps improve the plugin. **v1.7.0** adds the optional build overlay for commanders who use EDMCModernOverlay alongside Ravencolonial colonization tracking.

If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version, whether EDMCModernOverlay is installed, and what you were doing in-game when it happened.
