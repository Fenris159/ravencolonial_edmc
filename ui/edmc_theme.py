"""
Apply EDMC's global ``theme`` to a widget subtree (depth-first, post-order).

EDMC's ``theme.update(widget)`` only calls ``_update_widget`` on the widget and its
*direct* children; nested ``ttk.Frame`` chains are otherwise left without an initial
paint. GalaxyGPS calls ``theme.update`` per widget; we walk the tree so children are
updated before parents, matching that behavior without hand-maintaining every frame.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


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
        try:
            theme.update(w)
        except (ValueError, TypeError, tk.TclError):
            pass

    visit(root)
