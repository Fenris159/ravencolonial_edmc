# Build tracker overlay and popout

Commodity tracker table for one build you choose in the Ravencolonial EDMC tab, or for Track All aggregate totals across the active build projects in the refreshed list. It can render as an in-game HUD through EDMCModernOverlay, or as an EDMC-dark popout window with the same layout. It is similar in spirit to [SrvSurvey](https://github.com/njthomson/SrvSurvey) build tracking.

## Requirements

1. [EDMC](https://github.com/EDCD/EDMarketConnector) with this plugin enabled.
2. For the in-game HUD only: [EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay) installed and enabled.
3. For the in-game HUD only: Elite Dangerous in borderless or windowed mode.

The **Popout Tracker** does not require EDMCModernOverlay. It opens an EDMC-dark secondary window and is useful when the overlay stack is unavailable or you prefer to keep the tracker outside Elite. The popout remembers its last position across toggles and EDMC restarts, appears on the taskbar where the platform supports separate tool windows, and resizes itself when the tracker content changes.

Linux note: EDMCModernOverlay depends on the local desktop/compositor/window stack. On some Linux distributions, the overlay may require distro-specific troubleshooting before any plugin overlay can draw. Confirm EDMCModernOverlay itself can display a test overlay, use borderless/windowed Elite, and check your compositor/window-manager behavior before debugging the Ravencolonial HUD layer. Use **Popout Tracker** if you want the same tracker table without that external overlay path.

## Font (Oxanium)

This plugin bundles [Oxanium](https://fonts.google.com/specimen/Oxanium) (SIL Open Font License 1.1) under `assets/fonts/oxanium/`. On startup it copies the variable font into `EDMCModernOverlay/overlay_client/fonts/` and sets `preferred_fonts.txt` so the HUD uses Oxanium automatically when both plugins are installed. The popout also tries to register the bundled Oxanium font with Tk and falls back to EDMC's default font if the platform cannot load it.

The build tracker uses multiple font weights (light headers, semibold values, bold build name, and so on). That requires a one-time compatibility patch applied to your Modern Overlay install (done automatically when Ravencolonial loads). Restart EDMC after the first install so the overlay client reloads the font.

You can run the install again anytime under EDMC Settings -> Ravencolonial -> Install overlay fonts (below the Modern Overlay dependency note).

## Overlay Format

In EDMC Settings -> Ravencolonial, choose **Overlay Format**. **Breakdown** is the default and keeps the Need, Ship, and optional FC's columns. **Simplified** shows one **Purchase** column instead, in both the in-game HUD and Popout Tracker. Purchase is `max(0, remaining need - ship cargo - selected carrier cargo)` for each commodity.

Both formats hide categories when every commodity is covered by ship and selected carrier cargo. Mixed categories keep all their outstanding construction rows; unknown manifests keep their categories visible. Check **Show Completed Commodities** below **Enable Carrier Tracking** on the main tab to restore stocked categories and zero-need commodities supplied by the project cache. The checkbox choice is saved between sessions.

Simplified places Purchase close to the commodity names. Both formats use plain, left-aligned accent category headings enclosed by matching solid overlines and underlines ending at the commodity column edge. The column-header underline spans the full panel content with a right gutter, including wider build names or footers. Long footers wrap at `>` boundaries before breaking individual phrases. **Search** opens a dedicated system-name row above **Select Build Project**, styled with EDMC's active colors as soon as it opens.

The carrier dropdown in the main Ravencolonial tab determines whether Purchase uses one carrier or the combined cargo of **All** linked carriers. Enable Carrier Tracking to use that cargo; with tracking off, Purchase subtracts ship cargo only. When a selected carrier manifest has not synced, Purchase shows `sync` rather than treating its cargo as zero. In Track All, the plugin sums project needs first and subtracts the ship hold and selected carrier cargo once per commodity.

The footer still reports total remaining build need and ship trips, which may be larger than the amount to purchase.

## Tracker Theme

In EDMC Settings -> Ravencolonial, choose Overlay Theme to color the in-game HUD and popout tracker text. The popout window chrome always uses an EDMC-dark style. The default Elite Orange matches in-game UI; other presets are tuned for dark space backgrounds, including Cerulean Gold with cerulean headers, white system line, and gold numeric columns.

HUD text uses a transparent canvas per message. When EDMCModernOverlay is available, the build-tracker plugin group can draw a semi-transparent panel behind the whole block (`#141414CC`). Commodity data rows use alternating semi-transparent gray rectangle bands so each line is easier to scan. Vertical rules between Need, Ship, and FC's are drawn only alongside commodity data rows, not through the column header or category lines.

In plugin settings, **Row Highlight Opacity** controls the strength of those alternating commodity row bands in both formats and both tracker windows. Use the 0–100% slider and percentage readout: 0% hides the bands, 100% makes them opaque, and the default 8% matches the original shading. Save Settings to apply and retain your choice.

The popout uses the same tracker text colors as the selected overlay theme, but its custom title bar and window body stay EDMC-dark even when EDMC itself is using the default light theme. In Breakdown, equally sized numeric columns use equal gaps, with each header right-aligned to the values in its column. Simplified has one right-aligned Purchase column. Solid header and category underlines appear in both the overlay and popout.

## Use

On the Ravencolonial tab, above Select Plan Site:

1. Check **Enable Overlay** for the in-game HUD, or **Popout Tracker** for an EDMC window.
2. In overlay mode, optionally check **Always On** to keep the HUD visible while undocked. Otherwise it is intended for docked build work. In popout mode, **Always On** is hidden because the tracker is a normal window.
3. Click the overlay refresh button, or the plan-sites refresh button, to load build sites for the current system.
4. Choose Track All or a single project from Select Build Project. Only rows in build status are listed; there is no architect/orbital filter.
5. Optionally enable Enable Carrier Tracking and choose All or a project-linked carrier callsign.
6. The plugin loads project details from `GET /api/project/{buildId}` and updates the active tracker output.

The overlay refresh button refreshes build projects only. The plan-sites refresh button also fills the overlay list when that API response contains build rows.

The footer shows remaining units and estimated trips in this ship, using total need divided by the current `CargoCapacity` from EDMC. With Enable Carrier Tracking, a second line shows FC deficit for the selected carrier, either All or one callsign, and trips to cover that deficit.

Carrier cargo uses the plugin's local Fleet Carrier manifest cache. Manual/context-allowed refreshes establish the Ravencolonial baseline, then journal cargo events update matching tracked carriers live; normal overlay redraws do not poll Ravencolonial. If a selected project-linked carrier has no local cargo manifest yet, the overlay makes one guarded seed request to `GET /api/fc/{marketId}`; if that still does not produce a manifest, the FC column shows `sync` rather than calculating against zero stock. The refresh button beside the carrier dropdown is a manual fallback: with one callsign selected it reloads that carrier manifest, and with All selected it reloads every linked carrier shown in the carrier picker. The button changes to a live 60-second countdown after each click and re-enables when the countdown finishes. Carriers linked to your active projects can also be eligible for cargo PATCH updates when their `marketId` appears in `GET /api/cmdr/{cmdr}/active`.

Linked carrier cargo updates are marketId-based. `MarketBuy`, `MarketSell`, and `CargoTransfer` events for an eligible docked `FleetCarrier` send signed deltas to `PATCH /api/fc/{marketId}/cargo`. Squadron Carriers are not handled through a separate cargo endpoint or an inferred Cargo snapshot diff; if the docked carrier marketId is eligible, the journal direction determines the signed FC cargo delta.

When a single carrier is selected, the optional capacity footer appears only if the plugin has a matching local `freeSpace` cache entry for that carrier market ID. Missing capacity data hides the row rather than showing a null value.

Uncheck **Enable Overlay** to clear the in-game HUD. Uncheck **Popout Tracker** or close the popout window to return the row to its normal state and close the popout.

## Popout Copy Button

The popout title bar has a copy button next to **Popout Tracker**. It copies the current tracker contents to the clipboard as a Discord-friendly fixed-width block wrapped in triple backticks.

The copied output is meant for sharing hauling status. In Breakdown, it differs slightly from the on-screen table:

- the **Ship** column is omitted
- the "trips in this ship" footer row is omitted
- Fleet Carrier jump-timer rows are omitted
- the FC deficit footer is kept when carrier tracking has enough data

In Simplified, the copy keeps the Purchase column.

Paste it directly into Discord to keep commodity columns aligned.

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
- Press the carrier manifest refresh button to reload FC cargo from Ravencolonial for the selected carrier, or all linked carriers when All is selected. This is a manual fallback only; it does not run continuously.
- Selecting a single project fetches that project's current details.
- Selecting Track All fetches details for all active projects in the list.
- While docked at a construction depot, `ColonisationConstructionDepot` journal updates keep the currently docked project's remaining commodities current and rebuild Track All totals from cache.
- If a local project completes, the completion path removes that project from Track All totals immediately.
- After construction-depot or fleet-carrier activity, the next `Undocked` journal event triggers a full Track All project-detail refresh so background changes from other commanders are folded in after your local delivery or transfer work is done.

Because there is no polling, changes made by other commanders while you are elsewhere may not appear instantly. Use refresh when you want an immediate network update, or let the event-driven refresh run after the next qualifying construction-depot or fleet-carrier undock.

## Data Shown

- Build name, type, system, or Track All header when aggregate mode is selected.
- Asg - assignment hints from the project: pin = assigned to you, `x` = assigned to another commander. The column is hidden when nothing is assigned.
- Need (Breakdown) - server `commodities`, or live journal depot data when docked at that build's market.
- Commodities grouped under Elite market categories such as Chemicals, Foods, Metals, and Industrial Materials, using EDCD FDevIDs data.
- Ship (Breakdown) - your ship cargo from journal `Cargo`; zero shows as blank.
- Rows with zero remaining need are hidden.
- FC's (Breakdown) - optional fleet carrier surplus/deficit per commodity (`FC stock - need`) when Enable Carrier Tracking is on. Use the carrier dropdown, All or a callsign, below Select Build Project.
- Purchase (Simplified) - units still to acquire after subtracting ship and selected carrier cargo from remaining need.
- Popout mode uses the same rows, colors, and footer text as the in-game HUD, but draws them into an EDMC-dark Tk window instead of EDMCModernOverlay messages. The window dynamically resizes to fit updated row and footer content.

## Troubleshooting

- Please Refresh - no build rows are loaded yet. If Search fails with an empty query, the popup still appears but the dropdown stays on this label.
- No Build Projects - no build status sites in this system yet, or a known-system refresh failed and fell back to this stable state.
- No overlay on screen - confirm Modern Overlay is running; see its wiki for HUD setup. If you only need the tracker table, use Popout Tracker instead.
- Popout window closed - the Popout Tracker checkbox turns off and the main-tab tracker controls return to their normal inactive state.
- Popout window opens off to the side - move it where you want it; the last position is remembered for the next toggle and EDMC restart.
- Popout copied text is missing ship/jump-timer rows - this is intentional for Discord sharing. The copy format keeps project need and carrier deficit information, not your local ship hold or live timer lines.
- Linux no-show or focus quirks - use borderless/windowed Elite, test EDMCModernOverlay independently, and review compositor/window-manager settings. Some distros need additional overlay troubleshooting outside this plugin.
