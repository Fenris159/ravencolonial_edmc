# Release checklist (RavenColonial_EDMC)

Use this before tagging a release on **[Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**.

## Version and metadata

- [ ] **`load.py`**: `plugin_version` / `VERSION` match the tag you will publish.
- [ ] **`plugin_config/settings.py`**: `PluginConfig.VERSION` matches `plugin_version`.
- [ ] **`pyproject.toml`**: project `version` matches `plugin_version`, and `requires-python` still matches the supported EDMC/dev range.
- [ ] **Stable version shape:** stable releases use `X.Y.Z` and tag `vX.Y.Z`.
- [ ] **Pre-release version shape:** pre-releases use SemVer suffixes such as `X.Y.Z-beta.1` or `X.Y.Z-rc.1` and tag `vX.Y.Z-beta.1` / `vX.Y.Z-rc.1`.
- [ ] **`CHANGELOG.md`**: new section for this version with date (UTC `YYYY-MM-DD`) and accurate Added/Changed/Fixed/Notes.
- [ ] **`CurrentReleaseNotes.md`**: release body matches the version and highlights the user-facing changes. For pre-releases, frame it as pre-release / active-development validation and tell users that in-app pre-release updates require the **Include pre-release versions** setting.
- [ ] **`README.md`**: version table or summary updated if you surface versions there.

## GitHub Actions (recommended)

- [ ] **Development markers that should not publish:** tags that do **not** match `v*` do not start this workflow. Tags under `v*` that are not `vX.Y.Z` or `vX.Y.Z-beta.1` / `vX.Y.Z-rc.1` are skipped by the gate job.
- [ ] **Dry run / QA zip:** [Actions](https://github.com/Fenris159/ravencolonial_edmc/actions) -> **Build release** -> **Run workflow**, choose the branch to build from, leave **Publish GitHub release** unchecked. Download the **RavenColonial_EDMC-release-zip** artifact from the run summary (same contents as local `make_release.py`). No tag and no GitHub Release.
- [ ] **Publish stable from Actions:** Merge version bumps to `main`, then **Build release** -> **Run workflow**, choose `main`, set **release_channel** to **stable**, and enable **Publish GitHub release**. The workflow creates tag **`v{version}`** at the selected commit and publishes a normal GitHub Release.
- [ ] **Publish pre-release from Actions:** Commit version bumps to `development`, then **Build release** -> **Run workflow**, choose `development`, set **release_channel** to **prerelease**, and enable **Publish GitHub release**. The workflow creates tag **`v{version}`** at the selected development commit, publishes a GitHub **Pre-release**, and uses **`CurrentReleaseNotes.md`** as the body.
- [ ] **Publish by pushing a tag:** After `load.py`, `PluginConfig.VERSION`, and `pyproject.toml` match the version, push **`v{version}`** (for example **`v1.8.1`** or **`v1.8.2-rc.1`**). The workflow verifies the tag matches `plugin_version`, builds the zip, and publishes/updates the Release with the same title and **`CurrentReleaseNotes.md`** body. If the tag and `plugin_version` disagree, the job fails before publishing.
  - Pushing `vX.Y.Z` publishes a normal Release.
  - Pushing `vX.Y.Z-beta.1` or `vX.Y.Z-rc.1` publishes a GitHub Pre-release.

## Automated verification (local or CI)

Run before tagging. The release workflow also runs dependency install, flake8, pytest, and compileall before packaging:

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
- [ ] For a pre-release smoke test, confirm stable users do **not** see the pre-release with **Include pre-release versions** disabled, and testers do see it with that setting enabled.

## Build artifact

- [ ] Run **`make_release.py`** locally if you prefer (from any cwd; output is **`build/release/RavenColonial_EDMC-v{version}.zip`**) with a top-level **`RavenColonial_EDMC/`** folder and all required modules.
- [ ] Optional: run **`python scripts/clean_build_artifacts.py`** before packaging to clear caches and setuptools outputs under **`build/`** - this **never removes `build/release/`**, so existing release zips in that folder are kept.
- [ ] Confirm the zip contains **`LICENSE`**, **`load.py`**, **`__init__.py`**, `api/`, `handlers/`, `overlay/`, `plugin_config/`, `ui/`, `L10n/`, and other packaged `.py` files (see `make_release.py` for the exact list).
- [ ] GitHub **Release** includes an asset named **`RavenColonial_EDMC-v{version}.zip`** (auto-update matches this pattern).
- [ ] GitHub **Pre-release** checkbox is set for any `vX.Y.Z-beta.N` or `vX.Y.Z-rc.N` build.

## Smoke tests

- [ ] EDMC loads the plugin; **File -> Settings** shows the Ravencolonial tab (API key, three stealth toggles, update options).
- [ ] Journal path: dock at construction site -> depot / contribution updates (unless construction stealth on).
- [ ] With API key: FC updates respect FC stealth; **`currentShip`** updates respect ship-cargo stealth.
- [ ] **Check for updates** resolves **`Fenris159/ravencolonial_edmc`** (see `version_check.GITHUB_REPO`).

## Documentation (optional but recommended)

- [ ] **[MANUAL_UPDATE_INSTRUCTIONS.md](MANUAL_UPDATE_INSTRUCTIONS.md)** still points at **[GitHub Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)** for manual installs.
- [ ] **[AUTO_UPDATE_FEATURE.md](AUTO_UPDATE_FEATURE.md)** still matches actual update behavior and repo URL.
- [ ] Root **[README.md](../README.md)** still matches current Python metadata, update behavior, supported EDMC hook usage, and prerelease behavior.

## After publish

- [ ] Verify the **Releases** page shows the tag, notes, zip download, and the correct stable/pre-release state.
- [ ] Optional: install from zip on a clean plugins folder to mimic a user upgrade.
