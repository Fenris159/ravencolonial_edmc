"""Styled horizontal rules separating the plugin panel from other EDMC plugins."""

from __future__ import annotations

import tkinter as tk
from typing import Tuple


def _separator_colors() -> Tuple[str, str, str]:
    """
    Return ``(edge, accent, background)`` from EDMC's active theme.

    Edge lines are subdued; accent uses the theme foreground (typically tangerine on dark).
    """
    try:
        from theme import theme  # type: ignore[import-untyped]

        cur = getattr(theme, "current", None) or {}
        bg = str(cur.get("background", "grey15"))
        accent = str(cur.get("foreground", "#ff8000"))
        edge = str(cur.get("disabledforeground") or cur.get("highlight") or "#505050")
        if edge == accent:
            edge = "#505050"
        return edge, accent, bg
    except ImportError:
        return "#505050", "#ff8000", "grey15"


class StyledPluginSeparator(tk.Frame):
    """
    Groove-style rule: full-width edge lines with a shorter centered accent stroke.

    More distinctive than ``ttk.Separator`` while staying theme-aware (EDMC orange on dark).
    """

    _HEIGHT = 7

    def __init__(self, parent: tk.Widget, **kwargs) -> None:
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("borderwidth", 0)
        super().__init__(parent, **kwargs)
        self._edge, self._accent, self._bg = _separator_colors()
        self._canvas = tk.Canvas(
            self,
            width=1,
            height=self._HEIGHT,
            highlightthickness=0,
            borderwidth=0,
            bd=0,
            bg=self._bg,
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas.bind("<Configure>", self._redraw)
        self.configure(bg=self._bg)
        self._redraw()

    def refresh_colors(self) -> None:
        """Re-read EDMC theme colors (call after ``apply_theme_to_widget_subtree``)."""
        self._edge, self._accent, self._bg = _separator_colors()
        try:
            self.configure(bg=self._bg)
            self._canvas.configure(bg=self._bg)
        except tk.TclError:
            pass
        self._redraw()

    def _redraw(self, _event: object = None) -> None:
        c = self._canvas
        try:
            c.delete("all")
            w = max(int(c.winfo_width()), 4)
            h = self._HEIGHT
            edge, accent, bg = self._edge, self._accent, self._bg
            c.configure(bg=bg)
            c.create_line(0, 1, w, 1, fill=edge, width=1, tags="rule")
            c.create_line(0, h - 2, w, h - 2, fill=edge, width=1, tags="rule")
            inset = max(16, w // 6)
            mid = h // 2
            c.create_line(inset, mid, w - inset, mid, fill=accent, width=2, tags="rule")
        except tk.TclError:
            pass


def create_styled_plugin_separator(parent: tk.Widget) -> StyledPluginSeparator:
    return StyledPluginSeparator(parent)
