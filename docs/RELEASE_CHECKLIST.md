# Release checklist (RavenColonial_EDMC)

Use this before tagging a release on **[Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**.

## Version and metadata

- [ ] **`load.py`**: `plugin_version` / `VERSION` match the tag you will publish.
- [ ] **`plugin_config/settings.py`**: `PluginConfig.VERSION` matches `plugin_version`.
- [ ] **`CHANGELOG.md`**: new section for this version with date (UTC `YYYY-MM-DD`) and accurate Added/Changed/Fixed/Notes.
- [ ] **`README.md`**: version table or summary updated if you surface versions there.

## Build artifact

- [ ] Run **`make_release.py`** (from any cwd; output is **`build/release/RavenColonial_EDMC-v{version}.zip`**) with a top-level **`RavenColonial_EDMC/`** folder and all required modules.
- [ ] Optional: run **`python scripts/clean_build_artifacts.py`** before packaging to clear caches and setuptools outputs under **`build/`** — this **never removes `build/release/`**, so existing release zips in that folder are kept.
- [ ] Confirm the zip contains **`LICENSE`**, **`load.py`**, **`__init__.py`**, `api/`, `handlers/`, `plugin_config/`, `ui/`, `L10n/`, and other packaged `.py` files (see `make_release.py` for the exact list).
- [ ] GitHub **Release** includes an asset named **`RavenColonial_EDMC-v{version}.zip`** (auto-update matches this pattern).

## Smoke tests

- [ ] EDMC loads the plugin; **File → Settings** shows the Ravencolonial tab (API key, three stealth toggles, update options).
- [ ] Journal path: dock at construction site → depot / contribution updates (unless construction stealth on).
- [ ] With API key: FC updates respect FC stealth; **`currentShip`** updates respect ship-cargo stealth.
- [ ] **Check for updates** resolves **`Fenris159/ravencolonial_edmc`** (see `version_check.GITHUB_REPO`).

## Documentation (optional but recommended)

- [ ] **[MANUAL_UPDATE_INSTRUCTIONS.md](MANUAL_UPDATE_INSTRUCTIONS.md)** still points at **[GitHub Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** for manual installs.
- [ ] **[AUTO_UPDATE_FEATURE.md](AUTO_UPDATE_FEATURE.md)** still matches actual update behavior and repo URL.

## After publish

- [ ] Verify the **Releases** page shows the tag, notes, and zip download.
- [ ] Optional: install from zip on a clean plugins folder to mimic a user upgrade.
