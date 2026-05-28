# Build tracker overlay (EDMCModernOverlay)

On-screen commodity table (Need / Have) for a **build** you choose in the Ravencolonial EDMC tab—similar to [SrvSurvey](https://github.com/njthomson/SrvSurvey) build tracking.

## Requirements

1. [EDMC](https://github.com/EDCD/EDMarketConnector) with this plugin enabled.
2. [EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay) installed and enabled.
3. Elite Dangerous in **borderless** or **windowed** mode.

## Overlay theme

In **EDMC Settings → Ravencolonial**, choose **Overlay Theme** to color the in-game HUD. The default **Elite Orange** matches in-game UI; other presets are tuned for dark space backgrounds.

HUD text uses a transparent canvas per message. When EDMCModernOverlay is available, the build-tracker **plugin group** can draw a semi-transparent panel behind the whole block (`#141414CC`). Commodity **data rows** use alternating semi-transparent gray rectangle bands so each line is easier to scan (category headers and column titles are not banded).
 Vertical rules between **Need**, **Ship**, and **FC's** (when carrier tracking is on) are drawn only alongside commodity data rows—not through the column header or category lines.

## Use

On the **Ravencolonial** tab (above **Select Plan Site**):

1. Check **Enable Overlay**.
2. Optionally check **Always On** to keep the overlay visible while undocked (default: only while docked).
3. Click **↻** on the overlay row (or on the plan-sites row) to load **build** sites for the current system.
4. Choose a project from **Select Build Project** (status **build** only; no architect/orbital filter).
5. Optionally enable **Enable Carrier Tracking** and choose **All** or a project-linked carrier callsign.
6. The plugin loads project details from `GET /api/project/{buildId}` and updates the overlay.

The overlay row **↻** refreshes build projects only; the plan-sites **↻** also fills the overlay list when you use plan-site refresh.

The footer shows **remaining units** and estimated **trips in this ship** (total need ÷ current `CargoCapacity` from EDMC). With **Enable Carrier Tracking**, a second line shows **FC deficit** for the selected carrier (All or one callsign) and trips to cover that deficit.

Uncheck **Enable Overlay** to disable the dropdown and clear the overlay.

## Data shown

- Build name, type, system (from API project)
- **Asg** — assignment hints from the project (`📌` = assigned to you, `x` = assigned to another commander); column hidden when nothing is assigned
- **Need** — server `commodities`, or live journal depot when docked at that build’s market
- Commodities are grouped under **Elite market categories** (Chemicals, Foods, Metals, …) using EDCD FDevIDs data
- **Ship** — your ship cargo from journal `Cargo` (zero shows as blank)
- Rows with **zero remaining need** are hidden (fulfilled commodities)
- **FC's** (optional) — fleet carrier surplus/deficit per commodity (`FC stock − need`) when **Enable Carrier Tracking** is on; use the carrier dropdown (**All** or a callsign) below **Select Build Project**

## Troubleshooting

- **Please Refresh** — change system or press ↻ after `LoadGame`.
- **No Build Projects** — no `build` status sites in this system yet.
- No overlay on screen — confirm Modern Overlay is running; see its wiki for HUD setup.
