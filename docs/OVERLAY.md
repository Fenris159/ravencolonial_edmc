# Build tracker overlay (EDMCModernOverlay)

On-screen commodity table (Need / Have) for a **build** you choose in the Ravencolonial EDMC tab—similar to [SrvSurvey](https://github.com/njthomson/SrvSurvey) build tracking.

## Requirements

1. [EDMC](https://github.com/EDCD/EDMarketConnector) with this plugin enabled.
2. [EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay) installed and enabled.
3. Elite Dangerous in **borderless** or **windowed** mode.

## Use

On the **Ravencolonial** tab (above **Select Plan Site**):

1. Click **↻** on the plan-sites row to refresh system sites (same fetch loads both dropdowns).
2. Check **Enable Overlay**.
3. Choose a project from **Select Build Project** (only sites with status **build** in the current system; no architect/orbital filter).
4. The plugin loads project details from `GET /api/project/{buildId}` and updates the overlay.

Uncheck **Enable Overlay** to disable the dropdown and clear the overlay.

## Data shown

- Build name, type, system (from API project)
- **Need** — server `commodities`, or live journal depot when docked at that build’s market
- **Have** — your ship cargo from journal `Cargo`

## Troubleshooting

- **Please Refresh** — change system or press ↻ after `LoadGame`.
- **No Build Projects** — no `build` status sites in this system yet.
- No overlay on screen — confirm Modern Overlay is running; see its wiki for HUD setup.
