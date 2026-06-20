# Tkinter and EDMC theme practices (Ravencolonial plugin)

This document records how the plugin aligns with [Python tkinter](https://docs.python.org/3/library/tkinter.html), [TkDocs](https://tkdocs.com/tutorial/concepts.html), [EDMC plugin guidance](https://github.com/EDCD/EDMarketConnector/blob/main/PLUGINS.md), and patterns from [EDMC_GalaxyGPS `ui_helpers.py`](https://github.com/Fenris159/EDMC_GalaxyGPS/blob/master/GalaxyGPS/ui_helpers.py).

## EDMC themes

EDMC stores the UI theme in config key `theme`:

| Value | Name | Notes |
|------:|------|--------|
| 0 | Default / light | On Linux, `theme.current` uses `ttk` **clam** + `TLabel` colors ([`theme.py`](https://github.com/EDCD/EDMarketConnector/blob/main/theme.py)). |
| 1 | Dark | Panel `grey4`, text often orange (`dark_text` config). |
| 2 | Transparent | Same palette as dark; different window manager behaviour. |

Plugins should use:

```python
from theme import theme
theme.update(widget)  # register + apply theme.current
```

Ravencolonial walks subtrees via `ui.edmc_theme.apply_theme_to_widget_subtree()` so nested `tk.Frame` children are painted (EDMC’s `theme.update` only updates direct children).

## Widget choices (EDMC + GalaxyGPS)

| Use | Avoid |
|-----|--------|
| `tk.Frame`, `tk.Button`, `tk.Entry`, `tk.Label` for plugin panel controls | `theme.update` on `ttk.Button` / `ttk.Entry` (breaks native chrome, especially on Windows) |
| `ttk.Label` for captions beside custom controls | Stuffing long errors into combobox values (widens EDMC window) |
| `ThemedCombobox` (`ui/themed_combobox.py`) instead of `ttk.Combobox` | `theme.update` on popup `tk.Listbox` (Linux default theme: invisible items) |
| `myNotebook` / `nb.*` in **settings** tab only | `theme.update` on the settings prefs frame (EDMC already styles it) |

## ThemedCombobox rules

Implemented in `ui/themed_combobox.py` and `ui/combo_colors.py`:

1. **Entry and ▼ button** — `_rc_skip_subtree_theme` so only `apply_theme_styling()` calls `theme.update` on them (avoids double-apply from subtree walks).
2. **After `theme.update(entry)`** — dark themes keep the resolved themed entry background, while default/light theme re-applies the normal white entry surface to `background`, `readonlybackground`, and `disabledbackground`; then run `ensure_readable_foreground()` so fg/bg never collapse together.
3. **Popup list** — colors taken from the closed entry; **never** `theme.update(listbox)` (GalaxyGPS still calls it; we intentionally diverge for Linux theme 0).
4. **Open on click only** — no `FocusIn` handler (prevents reopen after dialogs; GalaxyGPS does the same).
5. **Dismiss** — root `<Button-1>` binding always released in `close_dropdown()`.

## Threading and the event loop

Per [tkinter threading](https://docs.python.org/3/library/tkinter.html#threading-model): Tcl/Tk is single-threaded. Background work (`requests`, file I/O) runs in `threading.Thread`; UI updates must use `plugin.frame.after(0, callback)` on the main thread. Ravencolonial uses this for plan-site refresh, overlay refresh, and link/create workers.

## Linux / X11

- **Modal dialogs** — `wait_visibility()` before `grab_set()` (`ui/themed_report_dialog.py`) to avoid a stray grab that blocks all EDMC clicks.
- **Popup placement** — clamp dropdown geometry to screen bounds; minimum height from item count.
- **Diagnostics** — `scripts/linux_edmc_ui_diagnostics.py` prints Tcl/Tk version and `config theme`.

## Verification checklist (manual, in EDMC)

Test with **theme 0 (default)** and **theme 1 (dark)** on Linux:

1. **Select Plan Site** — ↻ refresh; open dropdown; see placeholder, **Create New**, and any plan rows.
2. **Select Build Project** (tracker row) — same for build list when **Enable Overlay** or **Popout Tracker** is active. In default theme, disabled placeholders such as `Please Refresh` and `Select carrier` should keep a white entry background.
3. Themed error dialog — readable summary + detail; **OK** releases grab; rest of EDMC still clickable.
4. Settings tab — unchanged native EDMC styling (no plugin `theme.update` on prefs).

## References

- [tkinter — Python 3](https://docs.python.org/3/library/tkinter.html) — architecture, `StringVar`, threading, geometry managers.
- [TkDocs — Concepts](https://tkdocs.com/tutorial/concepts.html) — widget hierarchy, themed vs classic widgets, event loop.
- [EDMC `theme.py`](https://github.com/EDCD/EDMarketConnector/blob/main/theme.py) — `THEME_DEFAULT` / dark palettes and `_update_widget`.
- [GalaxyGPS `ui_helpers.py`](https://github.com/Fenris159/EDMC_GalaxyGPS/blob/master/GalaxyGPS/ui_helpers.py) — `ThemedCombobox`, `ThemeSafeCanvas`, `style_listbox_for_theme`.
