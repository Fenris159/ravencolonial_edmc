# Ravencolonial EDMC v1.8.2

## Welcome

Ongoing maintenance lives at **[github.com/Fenris159/ravencolonial_edmc](https://github.com/Fenris159/ravencolonial_edmc)**. Updates, issues, and downloads come from this repository.

**Stable release.** Download **`RavenColonial_EDMC-v1.8.2.zip`** from **[Releases](https://github.com/Fenris159/ravencolonial_edmc/releases)**, extract the **`RavenColonial_EDMC`** folder into EDMC's plugins directory, and restart EDMC. In-app update checks offer this build without enabling **Include pre-release versions**.

**Full technical list:** **[CHANGELOG.md](CHANGELOG.md)** → **[1.8.2]**.

---

## What's New in v1.8.2

This release promotes the **1.8.2-rc.1** through **1.8.2-rc.3** tracker fixes to stable and adds Dodec Starport to Create Project.

### Create Project — Dodec Starport

- **Tier 3: Dodec Starport** is now selectable in Construction Type.
- Models: **Dodec**, **Quint truss**, and **Dec truss** (API codes `dodec`, `quint_truss`, `dec_truss`), matching SrvSurvey layout names so Dodec plan sites and new Dodec builds can be created correctly.

### Popout Tracker window recovery

- **Automatic off-screen recovery** — On opening or resizing the tracker, its title bar must intersect a currently connected monitor's usable work area. A position stranded by a removed monitor, resolution/DPI change, or display rearrangement is centered on the display containing EDMC.
- **Multi-monitor-aware validation** — Valid positions on monitors left of or above the primary display remain intact; only positions without a reachable title bar on any connected display are recovered.
- **Minimized state is not saved as a position** — Closing EDMC while the tracker is minimized no longer risks persisting Windows' off-screen minimized coordinates.
- **Manual recovery in Settings** — **Reset and show Popout Tracker** activates popout mode, centers the window on the EDMC display, restores it to normal state, and brings it to the foreground.

### Build tracker / popout (selected project cache)

- **Latest selection wins** — Switching between projects, or from a project to Track All, supersedes an older in-flight fetch. An out-of-order response can no longer leave the tracker empty or restore a stale project's demand list.
- **Track All works in the popout by itself** — The combined project is built in the shared cache layer rather than by the Modern Overlay renderer, so all loaded incomplete-project needs appear when only the Popout Tracker is active.
- **Demand list follows the selected project** — The header and commodity demand list both come from the selected project's cache. You no longer need a full EDMC restart to clear a previous project's remaining-need rows.
- **Docked is visibility only** — Being docked at a construction depot no longer overrides which project's needs the overlay/popout displays. Journal `ColonisationConstructionDepot` events still update the **matching** build (by market / build id) in the project cache; the HUD always paints the **selected** entry.
- **Scoped cache writes** — Depot journal snapshots, successful API PATCHes, and completion events merge into `overlay_project_cache_by_build_id` for the matching build id. They update the selected single-project cache only when ids match; Track All rebuilds from the by-id cache.

---

## Testing

The full local suite passed with **225 passed, 1 skipped**, and repository-wide flake8 passed with **0** errors. Regression coverage includes off-screen window recovery, absolute negative monitor coordinates, minimized-state persistence, rapid project switching, project-to-Track-All switching, popout-only aggregation, selected-cache isolation, matching depot updates, completion filtering, and cache-driven demand rendering. Report issues with EDMC version, display arrangement, Overlay vs Popout Tracker, and whether you were docked when the problem appeared.

---

## Thank You

Thanks to commanders who reported tracker issues (including the Discord report that drove the off-screen recovery work) and who flagged missing Dodec Create Project options. Open issues on **[github.com/Fenris159/ravencolonial_edmc/issues](https://github.com/Fenris159/ravencolonial_edmc/issues)**.
