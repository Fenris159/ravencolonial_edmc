# Ravencolonial EDMC v1.8.1

## Welcome

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository. If you used an older fork or zip, use **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** so in-app update checks and manual installs stay in sync.

**Install this version:** download **`RavenColonial_EDMC-v1.8.1.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC's plugins directory, and restart EDMC. The running plugin reports **v1.8.1** in settings and to EDMC's plugin browser.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** -> **[1.8.1] - 2026-06-21**.

---

## What's New in v1.8.1

- **EDMC version advisory** - Startup warns when EDMC is below the tested minimum (6.1.2) or matches a known-incompatible version, using the normal status/error paths.
- **Safer custom auto-update** - The plugin keeps its custom updater. Downloads are staged into a disabled folder, validated, and promoted during EDMC shutdown after plugin resources are released. If a staging or promotion step fails, the live plugin folder is left in place or restored from backup.
- **Release digest verification** - When GitHub release metadata provides a SHA-256 digest for the zip, the updater verifies it before staging the install.
- **Windows lock handling** - Update promotion now retries short-lived folder rename failures, which helps when Windows or EDMC still has a file handle open during shutdown.
- **EDMC-compatible hook cleanup** - Commander identity now comes from supported journal/CAPI data instead of unsupported monitor state, and CAPI cache snapshots are limited to supported EDMC hook payloads.
- **Squadron carrier path cleanup** - The redundant unsupported `/squadron` Companion-session fetch path was removed. Squadron carrier cargo tracking still works through journal events, linked `marketId`, and `squadronBank` handling.
- **Broader Python metadata** - Local development and package metadata now support `>=3.11,<3.14`, matching the intended EDMC-compatible range.
- **Cross-platform journal fallback** - Journal/market fallback scanning now checks Windows, macOS, and Linux journal locations and skips unreadable files safely.
- **Audit cleanup** - Removed dead FC Market-file fallback, tightened exception handling on hot paths, cleared the Flake8 complexity baseline (all former C901 ignores), refactored journal/UI/update internals for maintainability, and expanded CI lint plus unit test coverage. Missing plugin issue-log creation now points users to the EDMC main log.

---

## Testing

The full local test suite passed for this release candidate with **165 passed, 1 skipped**.

---

## Thank You

Thanks to everyone who reports issues and helps improve the plugin. If something breaks after upgrading, open an issue on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)** with your EDMC version, update path, whether you are using EDMCModernOverlay or Popout Tracker, and what you were doing in-game when it happened.
