# RavenColonial_EDMC documentation

Project docs live here so the repository root stays focused on **`README.md`** (overview) and **`CHANGELOG.md`** (release history).

| Document | Purpose |
|----------|---------|
| [MANUAL_UPDATE_INSTRUCTIONS.md](MANUAL_UPDATE_INSTRUCTIONS.md) | Install or replace the plugin from GitHub when in-app auto-update is not used or fails. |
| [AUTO_UPDATE_FEATURE.md](AUTO_UPDATE_FEATURE.md) | How GitHub release checks and optional auto-install work. |
| [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) | Maintainer steps before publishing a release. |
| [LOGGING_CONVERSION.md](LOGGING_CONVERSION.md) | Internal notes on logger usage vs `print` debugging. |
| [RavenColonial_API_Reference.md](RavenColonial_API_Reference.md) | Large inferred API reference for Ravencolonial HTTP routes and schemas (developer reference). Includes **construction need vs delivery history** (`PATCH` depot, `/contribute`, `/supply`). |
| [ACTION_MAP_API_FLOWS.md](ACTION_MAP_API_FLOWS.md) | Journal events and UI actions mapped to the plugin’s RavenColonial API calls. |
| [OVERLAY.md](OVERLAY.md) | Build tracker overlay and popout: setup, columns, themes, and troubleshooting. |
| [THEME_UI.md](THEME_UI.md) | Tkinter + EDMC theme practices, `ThemedCombobox`, Linux compatibility checklist. |

### Maintainer scripts (`../scripts/`)

| Script | Purpose |
|--------|---------|
| [clean_build_artifacts.py](../scripts/clean_build_artifacts.py) | Remove Python caches and setuptools junk (`dist/`, `__pycache__/`, most of `build/`). **Does not delete `build/release/`** (release zips from `make_release.py` stay). Optional `--include-stray-root-zips` only clears legacy `RavenColonial_EDMC-v*.zip` in the repo root. |
| [generate_plugin_l10n.py](../scripts/generate_plugin_l10n.py) | Regenerate `L10n/*.strings` from `en.template` (see script docstring). |

Root **[README.md](../README.md)** and **[CHANGELOG.md](../CHANGELOG.md)** are the primary user-facing entry points.
