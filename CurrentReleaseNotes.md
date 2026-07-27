# Ravencolonial EDMC v1.8.2-rc.2

## Welcome

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository.

**This is a pre-release.** Enable **Include pre-release versions** in plugin settings if you want in-app update checks to offer it. Manual install: download **`RavenColonial_EDMC-v1.8.2-rc.2.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC's plugins directory, and restart EDMC.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** → **[1.8.2-rc.2]**.

---

## What's New in v1.8.2-rc.2

### Build tracker / popout (selected project cache)

- **Latest selection wins** — Switching between projects, or from a project to Track All, supersedes an older in-flight fetch. An out-of-order response can no longer leave the tracker empty or restore a stale project's demand list.
- **Track All works in the popout by itself** — The combined project is built in the shared cache layer rather than by the Modern Overlay renderer, so all loaded incomplete-project needs appear when only the Popout Tracker is active.
- **Demand list follows the selected project** — The header and commodity demand list both come from the selected project's cache. You no longer need a full EDMC restart to clear a previous project's remaining-need rows.
- **Docked is visibility only** — Being docked at a construction depot no longer overrides which project's needs the overlay/popout displays. Journal `ColonisationConstructionDepot` events still update the **matching** build (by market / build id) in the project cache; the HUD always paints the **selected** entry.
- **Scoped cache writes** — Depot journal snapshots, successful API PATCHes, and completion events merge into `overlay_project_cache_by_build_id` for the matching build id. They update the selected single-project cache only when ids match; Track All rebuilds from the by-id cache.

### Known focus for testing

- Switch between two incomplete build projects while docked at one of them: name and need list should both match the selection.
- Track All: incomplete projects should still aggregate; completed projects stay excluded.
- Away from the system: selected project should still show last cached needs until you refresh/search.

---

## Testing

The full local suite passed with **219 passed, 1 skipped**, and repository-wide flake8 passed with **0** errors. Regression coverage includes rapid project switching, project-to-Track-All switching, popout-only aggregation, selected-cache isolation, matching depot updates, completion filtering, and cache-driven demand rendering. Report issues with EDMC version, Overlay vs Popout Tracker, and whether you were docked when the problem appeared.

---

## Thank You

Thanks to commanders who report tracker issues (including the Discord report that drove this fix). Open issues on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)**.
