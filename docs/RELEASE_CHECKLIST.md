# Release checklist (RavenColonial_EDMC)

Use this before tagging a release on **[Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**.

## Version and metadata

- [ ] **`load.py`**: `plugin_version` / `VERSION` match the tag you will publish.
- [ ] **`plugin_config/settings.py`**: `PluginConfig.VERSION` matches `plugin_version`.
- [ ] **`pyproject.toml`**: project `version` matches `plugin_version`, and `requires-python` still matches the supported EDMC/dev range.
- [ ] **`CHANGELOG.md`**: new section for this version with date (UTC `YYYY-MM-DD`) and accurate Added/Changed/Fixed/Notes.
- [ ] **`CurrentReleaseNotes.md`**: release body matches the version and highlights the user-facing changes.
- [ ] **`README.md`**: version table or summary updated if you surface versions there.

## GitHub Actions (recommended)

- [ ] **Development markers (optional):** On `development` you can tag **without** triggering the release workflow or in-app auto-update:
  - **No workflow:** tags that do **not** match `v*` (e.g. `dev-1.7.0`, `pre-1.7.0`).
  - **Workflow runs but skips the build:** tags under `v*` that are **not** strict `vMAJOR.MINOR.PATCH` (e.g. `v1.7.0-dev`, `v1.7.0-rc.1`) — the **gate** job exits green with a notice; no zip and no publish.
  - **Production:** merge to `main`, then tag **exactly** `vX.Y.Z` matching `load.py` / `PluginConfig.VERSION` — that runs the full **Build release** job and is what auto-update considers.
- [ ] **Dry run / QA zip:** [Actions](https://github.com/Fenris159/ravencolonial_edmc/actions) → **Build release** → **Run workflow**, leave **Publish GitHub release** unchecked. Download the **RavenColonial_EDMC-release-zip** artifact from the run summary (same contents as local `make_release.py`). No tag and no GitHub Release.
- [ ] **Publish entirely from Actions:** Merge version bumps to the default branch, then **Build release** → **Run workflow**, choose that branch, enable **Publish GitHub release**. The workflow builds from `load.py` `plugin_version`, then creates tag **`v{version}`** and a GitHub Release titled **`RavenColonial_EDMC v{version}`** with body from **`CurrentReleaseNotes.md`** and the zip. Fails if that tag/release already exists.
- [ ] **Publish by pushing a tag:** After `load.py` and `PluginConfig.VERSION` match the version, push **`v{version}`** (for example **`v1.8.1`**). The workflow verifies the tag matches `plugin_version`, builds the zip, and publishes/updates the Release with the same title and **`CurrentReleaseNotes.md`** body. If the tag and `plugin_version` disagree, the job fails before publishing.

## Automated verification (local or CI)

Run before tagging (matches GitHub Actions CI):

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
.\.venv\Scripts\python.exe -m flake8 . --statistics --count
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q .
git diff --check v1.8.0...HEAD
python make_release.py
```

- [ ] Record the pytest summary in **`CHANGELOG.md`** and **`CurrentReleaseNotes.md`** (for example `170 passed, 1 skipped` at time of release).
- [ ] Confirm EDMC compatibility strings exist in all shipped **`L10n/*.strings`** files (not just templates).

## Build artifact

- [ ] Run **`make_release.py`** locally if you prefer (from any cwd; output is **`build/release/RavenColonial_EDMC-v{version}.zip`**) with a top-level **`RavenColonial_EDMC/`** folder and all required modules.
- [ ] Optional: run **`python scripts/clean_build_artifacts.py`** before packaging to clear caches and setuptools outputs under **`build/`** — this **never removes `build/release/`**, so existing release zips in that folder are kept.
- [ ] Confirm the zip contains **`LICENSE`**, **`load.py`**, **`__init__.py`**, `api/`, `handlers/`, `overlay/`, `plugin_config/`, `ui/`, `L10n/`, and other packaged `.py` files (see `make_release.py` for the exact list).
- [ ] GitHub **Release** includes an asset named **`RavenColonial_EDMC-v{version}.zip`** (auto-update matches this pattern).

## Smoke tests

- [ ] EDMC loads the plugin; **File → Settings** shows the Ravencolonial tab (API key, three stealth toggles, update options).
- [ ] Journal path: dock at construction site → depot / contribution updates (unless construction stealth on).
- [ ] With API key: FC updates respect FC stealth; **`currentShip`** updates respect ship-cargo stealth.
- [ ] **Check for updates** resolves **`Fenris159/ravencolonial_edmc`** (see `version_check.GITHUB_REPO`).

## Documentation (optional but recommended)

- [ ] **[MANUAL_UPDATE_INSTRUCTIONS.md](MANUAL_UPDATE_INSTRUCTIONS.md)** still points at **[GitHub Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** for manual installs.
- [ ] **[AUTO_UPDATE_FEATURE.md](AUTO_UPDATE_FEATURE.md)** still matches actual update behavior and repo URL.
- [ ] Root **[README.md](../README.md)** still matches current Python metadata, update behavior, and supported EDMC hook usage.

## After publish

- [ ] Verify the **Releases** page shows the tag, notes, and zip download.
- [ ] Optional: install from zip on a clean plugins folder to mimic a user upgrade.
