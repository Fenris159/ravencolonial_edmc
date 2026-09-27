# Ravencolonial EDMC v1.8.3-rc.1

## Development candidate

This pre-release adds a choice of colonization tracker layouts and brings the plugin's Python style checks in line with EDMC's Flake8 extension set. It is intended for active-development validation. Once a GitHub pre-release is published, in-app update checks will offer it only if **Include pre-release versions** is enabled in the plugin settings.

For installation, download `RavenColonial_EDMC-v1.8.3-rc.1.zip` from [Releases](https://github.com/Fenris159/ravencolonial_edmc/releases) once available, extract the `RavenColonial_EDMC` folder into EDMC's plugins directory, and restart EDMC.

## Overlay Format

Choose **Overlay Format** in the Ravencolonial plugin settings:

- **Breakdown** is the default. It retains the Need, Ship, and optional FC's columns.
- **Simplified** replaces those columns with **Purchase**, the amount still to acquire for each commodity after subtracting ship cargo and available carrier cargo from remaining project need. Purchase never falls below zero.

The carrier selection on the main plugin tab controls the calculation: choose one carrier to use its cargo, or **All** to use the combined cargo of linked carriers. Carrier cargo is included when **Enable Carrier Tracking** is on. If a required carrier manifest has not synced, Purchase displays **sync** until the amount is known. The same format appears in the in-game overlay and Popout Tracker. The settings selector adjusts its width to show the selected label.

## Developer checks

Flake8 now runs with EDMC's full plugin extension set across the repository. The README shows its CI status, and local pre-commit and pre-push hooks check it before changes are shared. The existing Python code was updated to pass these checks.

## Validation

The local suite passed with **232 passed, 1 skipped**. Repository-wide Flake8 and both local hook stages passed with **0 findings**. See [CHANGELOG.md](CHANGELOG.md) for the technical change list.
