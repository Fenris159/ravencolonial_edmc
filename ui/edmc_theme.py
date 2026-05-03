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

import tkinter as tk
from tkinter import ttk

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
