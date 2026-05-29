"""
Apply EDMC's global ``theme`` to a widget subtree (depth-first, post-order).

EDMC's ``theme.update(widget)`` only calls ``_update_widget`` on the widget and its
*direct* children; nested ``ttk.Frame`` chains are otherwise left without an initial
paint. GalaxyGPS calls ``theme.update`` per widget; we walk the tree so children are
updated before parents, matching that behavior without hand-maintaining every frame.

``theme._update_widget`` is aimed at classic ``tk`` widgets. Calling ``theme.update`` on
``ttk.Button`` / ``ttk.Entry`` / etc. fights the Ttk style engine (flat wrong colors,
bright disabled states on Windows). Skip those; use ``tk.Button`` + ``theme.update`` for
controls that should match plugins like GalaxyGPS (see ``ui/manager.py``).
"""

from __future__ import annotations

import logging
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk
from typing import Optional

logger = logging.getLogger(__name__)

HEADER_FONT_SCALE = 1.5
OXANIUM_VARIABLE_FILENAME = "Oxanium[wght].ttf"

_oxanium_header_font: Optional[tkfont.Font] = None
_oxanium_header_font_failed = False

# Widget types where theme.update breaks native ttk appearance (EDMC dark theme).
_TTK_SKIP_THEME_UPDATE: tuple[type, ...] = (
    ttk.Button,
    ttk.Checkbutton,
    ttk.Radiobutton,
    ttk.Entry,
    ttk.Combobox,
    ttk.Spinbox,
    ttk.Treeview,
    ttk.Notebook,
    ttk.Progressbar,
    ttk.Scale,
    ttk.Scrollbar,
)


def apply_theme_to_widget_subtree(root: tk.Widget) -> None:
    """Register and paint ``root`` and descendants with EDMC's active theme."""
    try:
        from theme import theme  # type: ignore[import-untyped]
    except ImportError:
        return
    if not getattr(theme, "current", None):
        return

    def visit(w: tk.Widget) -> None:
        try:
            children = w.winfo_children()
        except tk.TclError:
            children = ()
        for c in children:
            visit(c)
        if isinstance(w, _TTK_SKIP_THEME_UPDATE):
            return
        try:
            theme.update(w)
        except (ValueError, TypeError, tk.TclError):
            pass

    visit(root)


def bundled_oxanium_font_path() -> Optional[Path]:
    """Path to the bundled Oxanium variable font shipped with this plugin."""
    path = (
        Path(__file__).resolve().parents[1]
        / "assets"
        / "fonts"
        / "oxanium"
        / OXANIUM_VARIABLE_FILENAME
    )
    return path if path.is_file() else None


def _default_header_point_size(scale: float) -> int:
    base = tkfont.nametofont("TkDefaultFont")
    try:
        size = int(base.cget("size"))
    except tk.TclError:
        size = 10
    if size <= 0:
        size = 10
    return max(8, int(round(size * scale)))


def plugin_header_font(scale: float = HEADER_FONT_SCALE) -> tkfont.Font:
    """Bold Oxanium when bundled; otherwise scaled EDMC default (plugin strip title)."""
    global _oxanium_header_font, _oxanium_header_font_failed

    if _oxanium_header_font is not None:
        return _oxanium_header_font

    point_size = _default_header_point_size(scale)
    if not _oxanium_header_font_failed:
        oxanium_path = bundled_oxanium_font_path()
        if oxanium_path is not None:
            try:
                _oxanium_header_font = tkfont.Font(
                    file=str(oxanium_path),
                    size=point_size,
                    weight="bold",
                )
                logger.debug("Plugin header using Oxanium from %s", oxanium_path)
                return _oxanium_header_font
            except tk.TclError as exc:
                _oxanium_header_font_failed = True
                logger.warning("Oxanium header font unavailable, using default: %s", exc)

    base = tkfont.nametofont("TkDefaultFont")
    return tkfont.Font(
        family=base.actual("family"),
        size=point_size,
        weight="bold",
    )


def reapply_plugin_header_font(label: tk.Label, scale: float = HEADER_FONT_SCALE) -> None:
    """Re-apply header font after EDMC ``theme.update`` (which may reset widget fonts)."""
    try:
        label.configure(font=plugin_header_font(scale))
    except tk.TclError as exc:
        logger.debug("Could not reapply plugin header font: %s", exc)
