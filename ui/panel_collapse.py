"""Right-aligned rotating chevron for collapsing the main plugin panel."""

from __future__ import annotations

import math
import tkinter as tk
from typing import Callable, Optional, Tuple


def _theme_fg_bg(widget: tk.Misc) -> Tuple[str, str]:
    try:
        from theme import theme  # type: ignore[import-untyped]

        cur = getattr(theme, "current", None) or {}
        fg = str(cur.get("foreground", "#ff8000"))
        bg = str(cur.get("background", "grey15"))
        return fg, bg
    except ImportError:
        return "#ff8000", "grey15"


class PanelCollapseToggle:
    """Canvas chevron: points down when expanded, left when collapsed."""

    SIZE = 44
    ANIM_MS = 14
    ANIM_STEPS = 10
    _EXPANDED_ANGLE = 0.0
    _COLLAPSED_ANGLE = 90.0

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_toggle: Callable[[bool], None],
        expanded: bool = True,
    ) -> None:
        self._on_toggle = on_toggle
        self._expanded = expanded
        self._angle = self._EXPANDED_ANGLE if expanded else self._COLLAPSED_ANGLE
        self._target_angle = self._angle
        self._anim_after: Optional[str] = None
        self._fg, self._bg = _theme_fg_bg(parent)
        self._hover = False

        self.canvas = tk.Canvas(
            parent,
            width=self.SIZE,
            height=self.SIZE,
            highlightthickness=0,
            borderwidth=0,
            bd=0,
            bg=self._bg,
            cursor="hand2",
        )
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        self._redraw()

    @property
    def widget(self) -> tk.Canvas:
        return self.canvas

    @property
    def expanded(self) -> bool:
        return self._expanded

    def apply_theme(self, *, background: Optional[str] = None) -> None:
        self._fg, default_bg = _theme_fg_bg(self.canvas)
        self._bg = background or default_bg
        try:
            self.canvas.configure(bg=self._bg)
        except tk.TclError:
            pass
        self._redraw()

    def set_expanded(self, expanded: bool, *, animate: bool = True) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._target_angle = self._EXPANDED_ANGLE if expanded else self._COLLAPSED_ANGLE
        if animate:
            self._start_animation()
        else:
            self._angle = self._target_angle
            self._redraw()

    def _on_click(self, _event: object = None) -> None:
        self._expanded = not self._expanded
        self._target_angle = self._EXPANDED_ANGLE if self._expanded else self._COLLAPSED_ANGLE
        self._start_animation()
        self._on_toggle(self._expanded)

    def _on_enter(self, _event: object = None) -> None:
        self._hover = True
        self._redraw()

    def _on_leave(self, _event: object = None) -> None:
        self._hover = False
        self._redraw()

    def _start_animation(self) -> None:
        if self._anim_after is not None:
            try:
                self.canvas.after_cancel(self._anim_after)
            except tk.TclError:
                pass
            self._anim_after = None
        self._animate_step()

    def _animate_step(self) -> None:
        delta = self._target_angle - self._angle
        if abs(delta) < 0.5:
            self._angle = self._target_angle
            self._redraw()
            self._anim_after = None
            return
        self._angle += delta / self.ANIM_STEPS
        self._redraw()
        try:
            self._anim_after = self.canvas.after(self.ANIM_MS, self._animate_step)
        except tk.TclError:
            self._anim_after = None

    @staticmethod
    def _rotate(x: float, y: float, cx: float, cy: float, rad: float) -> Tuple[float, float]:
        dx, dy = x - cx, y - cy
        cos_a, sin_a = math.cos(rad), math.sin(rad)
        return cx + dx * cos_a - dy * sin_a, cy + dx * sin_a + dy * cos_a

    def _chevron_points(self) -> Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]]:
        cx = cy = self.SIZE / 2.0
        half_w, half_h = 10.0, 7.0
        pts = (
            (cx - half_w, cy - half_h),
            (cx, cy + half_h),
            (cx + half_w, cy - half_h),
        )
        rad = math.radians(self._angle)
        return tuple(self._rotate(x, y, cx, cy, rad) for x, y in pts)  # type: ignore[return-value]

    def _redraw(self) -> None:
        c = self.canvas
        try:
            c.delete("all")
            if self._hover:
                pad = 4
                c.create_oval(
                    pad,
                    pad,
                    self.SIZE - pad,
                    self.SIZE - pad,
                    outline=self._fg,
                    width=1,
                )
            p1, p2, p3 = self._chevron_points()
            c.create_line(
                p1[0],
                p1[1],
                p2[0],
                p2[1],
                p3[0],
                p3[1],
                fill=self._fg,
                width=4,
                capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
                smooth=True,
            )
        except tk.TclError:
            pass
