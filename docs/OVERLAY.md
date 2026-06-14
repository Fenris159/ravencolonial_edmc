# Build tracker overlay (EDMCModernOverlay)

On-screen commodity table (Need / Have) for one build you choose in the Ravencolonial EDMC tab, or for Track All aggregate totals across the active build projects in the refreshed list. It is similar in spirit to [SrvSurvey](https://github.com/njthomson/SrvSurvey) build tracking.

## Requirements

1. [EDMC](https://github.com/EDCD/EDMarketConnector) with this plugin enabled.
2. [EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay) installed and enabled.
3. Elite Dangerous in borderless or windowed mode.

Linux note: EDMCModernOverlay depends on the local desktop/compositor/window stack. On some Linux distributions, the overlay may require distro-specific troubleshooting before any plugin overlay can draw. Confirm EDMCModernOverlay itself can display a test overlay, use borderless/windowed Elite, and check your compositor/window-manager behavior before debugging the Ravencolonial HUD layer.

## Font (Oxanium)

This plugin bundles [Oxanium](https://fonts.google.com/specimen/Oxanium) (SIL Open Font License 1.1) under `assets/fonts/oxanium/`. On startup it copies the variable font into `EDMCModernOverlay/overlay_client/fonts/` and sets `preferred_fonts.txt` so the HUD uses Oxanium automatically when both plugins are installed.

The build tracker uses multiple font weights (light headers, semibold values, bold build name, and so on). That requires a one-time compatibility patch applied to your Modern Overlay install (done automatically when Ravencolonial loads). Restart EDMC after the first install so the overlay client reloads the font.

You can run the install again anytime under EDMC Settings -> Ravencolonial -> Install overlay fonts (below the Modern Overlay dependency note).

## Overlay Theme

In EDMC Settings -> Ravencolonial, choose Overlay Theme to color the in-game HUD. The default Elite Orange matches in-game UI; other presets are tuned for dark space backgrounds, including Cerulean Gold with cerulean headers, white system line, and gold numeric columns.

HUD text uses a transparent canvas per message. When EDMCModernOverlay is available, the build-tracker plugin group can draw a semi-transparent panel behind the whole block (`#141414CC`). Commodity data rows use alternating semi-transparent gray rectangle bands so each line is easier to scan. Vertical rules between Need, Ship, and FC's are drawn only alongside commodity data rows, not through the column header or category lines.

## Use

On the Ravencolonial tab, above Select Plan Site:

1. Check Enable Overlay.
2. Optionally check Always On to keep the overlay visible while undocked. Otherwise it is intended for docked build work.
3. Click the overlay refresh button, or the plan-sites refresh button, to load build sites for the current system.
4. Choose Track All or a single project from Select Build Project. Only rows in build status are listed; there is no architect/orbital filter.
5. Optionally enable Enable Carrier Tracking and choose All or a project-linked carrier callsign.
6. The plugin loads project details from `GET /api/project/{buildId}` and updates the overlay.

The overlay refresh button refreshes build projects only. The plan-sites refresh button also fills the overlay list when that API response contains build rows.

The footer shows remaining units and estimated trips in this ship, using total need divided by the current `CargoCapacity` from EDMC. With Enable Carrier Tracking, a second line shows FC deficit for the selected carrier, either All or one callsign, and trips to cover that deficit.

Uncheck Enable Overlay to disable the dropdown and clear the overlay.

## Track All

Track All appears as the first active build-project option after a successful project refresh. When selected, the overlay:

- fetches full details for each active build project in the current or searched system list
- sums remaining commodity needs across those projects
- excludes project payloads already marked complete
- combines linked fleet carriers from all tracked projects and deduplicates them by `marketId`
- keeps the carrier picker behavior unchanged: All carriers or one selected callsign

Track All keeps a per-build cache so local updates to one project can rebuild the combined HUD without discarding the other tracked projects.

## Refresh Behavior

The overlay does not poll Ravencolonial in the background. It refreshes on explicit or journal-driven triggers:

- Press the overlay refresh button to reload active build projects for the current or searched system.
- Press the plan-location refresh button to refresh plan rows and build rows together.
- Selecting a single project fetches that project's current details.
- Selecting Track All fetches details for all active projects in the list.
- While docked at a construction depot, `ColonisationConstructionDepot` journal updates keep the currently docked project's remaining commodities current and rebuild Track All totals from cache.
- If a local project completes, the completion path removes that project from Track All totals immediately.
- After construction-depot or fleet-carrier activity, the next `Undocked` journal event triggers a full Track All project-detail refresh so background changes from other commanders are folded in after your local delivery or transfer work is done.

Because there is no polling, changes made by other commanders while you are elsewhere may not appear instantly. Use refresh when you want an immediate network update, or let the event-driven refresh run after the next qualifying construction-depot or fleet-carrier undock.

## Data Shown

- Build name, type, system, or Track All header when aggregate mode is selected.
- Asg - assignment hints from the project: pin = assigned to you, `x` = assigned to another commander. The column is hidden when nothing is assigned.
- Need - server `commodities`, or live journal depot data when docked at that build's market.
- Commodities grouped under Elite market categories such as Chemicals, Foods, Metals, and Industrial Materials, using EDCD FDevIDs data.
- Ship - your ship cargo from journal `Cargo`; zero shows as blank.
- Rows with zero remaining need are hidden.
- FC's - optional fleet carrier surplus/deficit per commodity (`FC stock - need`) when Enable Carrier Tracking is on. Use the carrier dropdown, All or a callsign, below Select Build Project.

## Troubleshooting

- Please Refresh - change system or press refresh after `LoadGame`.
- No Build Projects - no build status sites in this system yet.
- No overlay on screen - confirm Modern Overlay is running; see its wiki for HUD setup.
- Linux no-show or focus quirks - use borderless/windowed Elite, test EDMCModernOverlay independently, and review compositor/window-manager settings. Some distros need additional overlay troubleshooting outside this plugin.
