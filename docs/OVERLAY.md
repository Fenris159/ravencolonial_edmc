# Build tracker overlay (EDMCModernOverlay)

This plugin can show an on-screen commodity table while you work on a **tracked colonization build**, similar to [SrvSurvey](https://github.com/njthomson/SrvSurvey) `PlotBuildCommodities`.

## Requirements

1. [EDMC](https://github.com/EDCD/EDMarketConnector) with this Ravencolonial plugin enabled.
2. [EDMCModernOverlay](https://github.com/SweetJonnySauce/EDMCModernOverlay) installed and enabled as a separate EDMC plugin.
3. Elite Dangerous in **borderless** or **windowed** mode (not exclusive fullscreen).

There is **no pip package** to install: Modern Overlay registers an in-process API that this plugin calls via `EDMCOverlay.edmcoverlay`.

## Enable

**EDMC → Settings → Ravencolonial** → enable **Show build tracker overlay** (on by default).

## When it appears

The overlay updates when you are docked at a **colonization megaship** with an **active Ravencolonial project** at that station (the same build shown as **Open Build Page** in the plugin tab).

It shows:

- Build name and type (and system when known)
- **Need** — remaining commodities (live journal depot when available, else server project data)
- **Have** — counts in your ship cargo hold (from journal `Cargo`)
- **Remaining** — total units still required

It clears when you undock or leave the construction site without a tracked build.

## SrvSurvey comparison

SrvSurvey draws its own WinForms overlay and supports multiple projects, primary build selection, and fleet-carrier columns. This EDMC plugin focuses on the **currently linked build at dock** using Ravencolonial API + journal depot data—the same workflow as the main EDMC tab.

## Troubleshooting

- No overlay: confirm Modern Overlay is installed, enabled, and its overlay client is running (see Modern Overlay logs / `port.json`).
- Overlay frozen: toggle the setting off and on, or restart EDMC.
- Wrong cargo counts: ensure journal `Cargo` events are flowing (not in SRV-only edge cases without a full inventory snapshot).
