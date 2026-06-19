"""Tk popout window for the build tracker overlay bundle."""

from __future__ import annotations

import logging
import threading
import tkinter as tk
import tkinter.font as tkfont
from typing import Any, Optional, Tuple

try:
    from ..ui.edmc_theme import OXANIUM_FAMILY, ensure_bundled_oxanium_font_registered
except ImportError:  # pragma: no cover
    from ui.edmc_theme import OXANIUM_FAMILY, ensure_bundled_oxanium_font_registered

from .layers import OVERLAY_X, OVERLAY_Y
from .render_layers import OverlayRenderBundle

logger = logging.getLogger(__name__)


class BuildProjectPopout:
    """Render the current build tracker bundle in a themed secondary Tk window."""

    _PAD_X = 18
    _PAD_Y = 16

    def __init__(self, plugin: Any) -> None:
        self._plugin = plugin
        self._window: Optional[tk.Toplevel] = None
        self._canvas: Optional[tk.Canvas] = None
        self._last_signature: Optional[str] = None
        self._font_cache: dict[Tuple[int, int], tkfont.Font] = {}
        self._closing_from_ui = False

    def enabled(self) -> bool:
        plugin = self._plugin
        return bool(
            getattr(plugin, "overlay_popout_enabled", False)
            and getattr(plugin, "overlay_ui_enabled", False)
        )

    def clear(self) -> None:
        """Close the popout window."""
        self._last_signature = None
        self._font_cache.clear()
        window = self._window
        self._window = None
        self._canvas = None
        if window is not None:
            try:
                self._closing_from_ui = True
                window.destroy()
            except tk.TclError:
                pass
            finally:
                self._closing_from_ui = False

    def refresh(self, *, force: bool = False) -> None:
        frame = getattr(self._plugin, "frame", None)
        if frame is not None and threading.current_thread() is not threading.main_thread():
            try:
                frame.after(0, lambda: self._refresh_main(force=force))
                return
            except tk.TclError:
                pass
        self._refresh_main(force=force)

    def _refresh_main(self, *, force: bool = False) -> None:
        if not self.enabled():
            self.clear()
            return
        self._ensure_window()
        canvas = self._canvas
        if canvas is None:
            return

        bundle = self._compose_bundle()
        signature = self._bundle_signature(bundle)
        if not force and signature == self._last_signature:
            return

        canvas.delete("all")
        self._draw_bundle(canvas, bundle)
        self._last_signature = signature

    def _ensure_window(self) -> None:
        if self._window is not None and self._canvas is not None:
            return
        parent = getattr(self._plugin, "frame", None)
        try:
            self._window = tk.Toplevel(parent) if parent is not None else tk.Toplevel()
            self._window.title("Popout Tracker")
            self._window.minsize(360, 160)
            self._window.protocol("WM_DELETE_WINDOW", self._on_window_close)
            bg, _fg = self._theme_colors(self._window)
            self._window.configure(background=bg)
            self._canvas = tk.Canvas(
                self._window,
                background=bg,
                highlightthickness=0,
                borderwidth=0,
            )
            self._canvas.pack(fill=tk.BOTH, expand=True)
        except tk.TclError as exc:
            logger.debug("Build tracker popout create failed: %s", exc)
            self._window = None
            self._canvas = None

    def _on_window_close(self) -> None:
        if self._closing_from_ui:
            return
        ui = getattr(self._plugin, "ui_manager", None)
        row = getattr(ui, "_overlay_row", None) if ui is not None else None
        if row is not None and hasattr(row, "disable_popout_from_window"):
            row.disable_popout_from_window()
            return
        self._plugin.overlay_popout_enabled = False
        self._plugin.overlay_ui_enabled = False
        self.clear()

    def _compose_bundle(self) -> OverlayRenderBundle:
        overlay = getattr(self._plugin, "build_overlay", None)
        if overlay is not None and hasattr(overlay, "compose_layers"):
            return overlay.compose_layers()
        try:
            from .build_project import BuildProjectOverlay

            return BuildProjectOverlay(self._plugin).compose_layers()
        except Exception as exc:
            logger.debug("Build tracker popout compose failed: %s", exc)
            return OverlayRenderBundle([])

    @staticmethod
    def _bundle_signature(bundle: OverlayRenderBundle) -> str:
        parts: list[str] = []
        for rect in bundle.rect_layers:
            parts.append(f"R|{rect.fill}|{rect.x}|{rect.y}|{rect.w}|{rect.h}")
        for vector in bundle.vector_layers:
            parts.append(f"V|{vector.color}|{vector.x}|{vector.y1}|{vector.y2}")
        for layer in bundle.text_layers:
            parts.append(f"T|{layer.color}|{layer.x}|{layer.y}|{layer.weight}|{layer.text}")
        return "\x1e".join(parts)

    def _draw_bundle(self, canvas: tk.Canvas, bundle: OverlayRenderBundle) -> None:
        bg, fg = self._theme_colors(canvas)
        try:
            canvas.configure(background=bg)
        except tk.TclError:
            pass
        if self._window is not None:
            try:
                self._window.configure(background=bg)
            except tk.TclError:
                pass

        dx = self._PAD_X - OVERLAY_X
        dy = self._PAD_Y - OVERLAY_Y
        for rect in bundle.rect_layers:
            fill = self._resolve_layer_color(canvas, rect.fill, fallback=bg, background=bg)
            outline = "" if rect.border_color == "none" else self._resolve_layer_color(canvas, rect.border_color, fallback=fill)
            canvas.create_rectangle(
                rect.x + dx,
                rect.y + dy,
                rect.x + rect.w + dx,
                rect.y + rect.h + dy,
                fill=fill,
                outline=outline,
            )
        for vector in bundle.vector_layers:
            canvas.create_line(
                vector.x + dx,
                vector.y1 + dy,
                vector.x + dx,
                vector.y2 + dy,
                fill=self._resolve_layer_color(canvas, vector.color, fallback=fg),
                width=1,
            )
        for layer in bundle.text_layers:
            canvas.create_text(
                layer.x + dx,
                layer.y + dy,
                text=layer.text,
                anchor="nw",
                fill=self._resolve_layer_color(canvas, layer.color, fallback=fg),
                font=self._font_for_layer(layer.weight, layer.msg_id),
            )
        self._fit_canvas(canvas)

    def _fit_canvas(self, canvas: tk.Canvas) -> None:
        bbox = canvas.bbox("all")
        if not bbox:
            width, height = 360, 160
        else:
            width = max(360, int(bbox[2] + self._PAD_X))
            height = max(160, int(bbox[3] + self._PAD_Y))
        try:
            canvas.configure(width=width, height=height, scrollregion=(0, 0, width, height))
            if self._window is not None:
                self._window.geometry(f"{width}x{height}")
        except tk.TclError:
            pass

    def _font_for_layer(self, weight: int, msg_id: str) -> tkfont.Font:
        size = 10
        if msg_id.endswith("hdr-build"):
            size = 13
        elif msg_id.endswith("hdr-system"):
            size = 11
        weight_i = int(weight or 400)
        key = (size, weight_i)
        cached = self._font_cache.get(key)
        if cached is not None:
            return cached

        family = self._resolve_oxanium_family()
        tk_weight = "bold" if weight_i >= 600 else "normal"
        font = tkfont.Font(family=family, size=size, weight=tk_weight)
        self._font_cache[key] = font
        return font

    @staticmethod
    def _resolve_oxanium_family() -> str:
        try:
            ensure_bundled_oxanium_font_registered()
            font = tkfont.Font(family=OXANIUM_FAMILY, size=10)
            if font.actual("family") == OXANIUM_FAMILY:
                return OXANIUM_FAMILY
        except tk.TclError:
            pass
        try:
            return tkfont.nametofont("TkDefaultFont").actual("family")
        except tk.TclError:
            return "TkDefaultFont"

    @staticmethod
    def _theme_colors(widget: tk.Widget) -> Tuple[str, str]:
        bg = "#1e1e1e"
        fg = "#f0f0f0"
        try:
            from theme import theme  # type: ignore[import-untyped]

            cur = getattr(theme, "current", None) or {}
            bg = str(cur.get("background") or bg)
            fg = str(cur.get("foreground") or fg)
        except ImportError:
            pass
        return (
            BuildProjectPopout._tk_color_to_hex(widget, bg, fallback="#1e1e1e"),
            BuildProjectPopout._tk_color_to_hex(widget, fg, fallback="#f0f0f0"),
        )

    @staticmethod
    def _resolve_layer_color(
        widget: tk.Widget,
        color: str,
        *,
        fallback: str,
        background: Optional[str] = None,
    ) -> str:
        raw = str(color or "").strip()
        if raw.startswith("#") and len(raw) == 9 and background:
            return BuildProjectPopout._blend_argb(raw, background)
        return BuildProjectPopout._tk_color_to_hex(widget, raw, fallback=fallback)

    @staticmethod
    def _tk_color_to_hex(widget: tk.Widget, color: str, *, fallback: str) -> str:
        raw = str(color or "").strip() or fallback
        try:
            r, g, b = widget.winfo_rgb(raw)
            return f"#{r // 257:02x}{g // 257:02x}{b // 257:02x}"
        except tk.TclError:
            if raw.startswith("#") and len(raw) == 7:
                return raw
            return fallback

    @staticmethod
    def _blend_argb(argb: str, background: str) -> str:
        try:
            alpha = int(argb[1:3], 16) / 255.0
            fg = tuple(int(argb[i : i + 2], 16) for i in (3, 5, 7))
            bg = tuple(int(background[i : i + 2], 16) for i in (1, 3, 5))
            mixed = tuple(int(round(f * alpha + b * (1.0 - alpha))) for f, b in zip(fg, bg))
            return f"#{mixed[0]:02x}{mixed[1]:02x}{mixed[2]:02x}"
        except Exception:
            return background
