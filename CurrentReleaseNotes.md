# Ravencolonial EDMC v1.8.3

## Release highlights

Version 1.8.3 adds configurable colonization tracker quantities, cleaner overlay layouts, portable button icons, and Linux popout fixes. It also brings the plugin's Python style checks in line with EDMC's Flake8 extension set.

Once published, this stable release will be offered by normal in-app update checks without enabling **Include pre-release versions**. For manual installation, download `RavenColonial_EDMC-v1.8.3.zip` from [Releases](https://github.com/Fenris159/ravencolonial_edmc/releases) once available, extract the `RavenColonial_EDMC` folder into EDMC's plugins directory, and restart EDMC.

## Overlay Format

Choose **Overlay Format** in the Ravencolonial plugin settings:

- **Breakdown** is the default. It retains the Need, Ship, and optional FC's columns.
- **Simplified** replaces those columns with **Purchase**, the amount still to acquire for each commodity after subtracting ship cargo and available carrier cargo from remaining project need. Purchase never falls below zero.

The carrier selection on the main plugin tab controls the calculation: choose one carrier to use its cargo, or **All** to use the combined cargo of linked carriers. Carrier cargo is included when **Enable Carrier Tracking** is on. If a required carrier manifest has not synced, Purchase displays **sync** until the amount is known. The same format appears in the in-game overlay and Popout Tracker. The settings selector adjusts its width to show the selected label.

**Row Highlight Opacity**, below Overlay Theme, adjusts the alternating commodity row highlights in both formats and both tracker windows. The slider shows the selected percentage: **0%** hides the highlights, **100%** makes them opaque, and **8%** preserves the previous appearance. Save Settings to apply and retain the change.

## Developer checks

Flake8 now runs with EDMC's full plugin extension set across the repository. The README shows its CI status, and local pre-commit and pre-push hooks check it before changes are shared. The existing Python code was updated to pass these checks.

## Improvements and fixes

- **Portable button icons** - Main actions, update buttons, refresh controls, and dropdown arrows use bundled DejaVu bitmap files in the active EDMC colors. Refresh controls fit closely around their icons while retaining room for the carrier countdown. Dropdown arrows share one continuous border with their textboxes and follow the entry font. Disabled icons dim cleanly on Linux. Caption buttons keep their spacing, and icons stay visible through theme changes. No extra font installation is needed. Assignment hints use `*` for your commodities, avoiding an emoji-font dependency in the overlay and clipboard.
- **Compact tracker layout** - Simplified brings Purchase closer to commodity names. Both formats enclose category headings with matching solid overlines and underlines. The column-header underline spans the full panel content with a right gutter, including wider build names or footers. Breakdown uses equally sized numeric columns, with headers right-aligned to their values in the overlay and popout. Footer breaks occur at `>` boundaries.
- **Consistent HUD sizing** - Footer lines now share the commodity row grid instead of relying on the renderer's multiline font spacing. Short summaries stay intact; long clauses wrap at word boundaries after the `>` breaks. Wide localized glyphs and combining accents receive better column and rule width estimates. Existing ASCII column positions are retained. Old footer rows clear when content shrinks, and supported font preset changes invalidate the redraw cache. Viewport scaling and font limits remain controlled by Modern Overlay.
- **Completed categories** - Categories stocked by ship and selected carrier cargo hide in both formats. **Show Completed Commodities**, below **Enable Carrier Tracking**, restores the full list and saves your choice. Syncing categories remain visible.
- **Search row** - The search textbox now has its own row above **Select Build Project**, using the active EDMC colors from its first opening without requiring a Settings refresh.
- **Settings colors** - Overlay Format now matches the native settings controls, while still adjusting its width to fit the selected label.
- **Linux Popout Tracker** - The extra native title bar is removed. Dragging the custom title bar no longer jumps downward or loses movement during rapid pointer motion. On X11/XWayland, the tracker remains a normal managed window.
- **Modern Overlay compatibility** - Fixed the font-weight patch that could crash Modern Overlay when rendering text. The fix repairs previously patched installations, measures bold text correctly, and preserves unrelated local modifications. Unknown renderer layouts are left unchanged.

## Validation

The local suite passed with **291 passed, 1 skipped**. Repository-wide Flake8 passed with **0 findings**. Live Tk checks confirmed file icon loading, normal/disabled/hover colors, compact button dimensions at multiple font sizes, continuous dropdown borders through theme/font/state changes, countdown transitions, the opacity slider, saving and restoring 0%, initial search colors, measured column alignment, rule placement, and completed checkbox placement. Rendered previews verified the icon controls and both tracker layouts. Renderer checks covered 72 combinations across both formats, 1080p/1440p/4K, display scale factors 1/1.5/2, Fill/Fit, and Oxanium/DejaVu Sans with default font limits; Fill footer spacing remained 20 logical pixels without overlap. Earlier checks confirmed settings colors, window dragging, and repaired Modern Overlay rendering. See [CHANGELOG.md](CHANGELOG.md) for the technical change list.
