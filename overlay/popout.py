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

from .layers import LINE_HEIGHT, OVERLAY_X, OVERLAY_Y
from .render_layers import OverlayRenderBundle

logger = logging.getLogger(__name__)


class BuildProjectPopout:
    """Render the current build tracker bundle in a themed secondary Tk window."""

    _PAD_X = 12
    _PAD_Y = 10
    _TITLE_H = 30
    _MIN_CONTENT_W = 360
    _MIN_CONTENT_H = 130
    _X_SCALE = 1.28

    def __init__(self, plugin: Any) -> None:
        self._plugin = plugin
        self._window: Optional[tk.Toplevel] = None
        self._title_bar: Optional[tk.Frame] = None
        self._title_label: Optional[tk.Label] = None
        self._close_btn: Optional[tk.Button] = None
        self._content_frame: Optional[tk.Frame] = None
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
        self._title_bar = None
        self._title_label = None
        self._close_btn = None
        self._content_frame = None
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
            self._window.withdraw()
            self._window.overrideredirect(True)
            self._window.protocol("WM_DELETE_WINDOW", self._on_window_close)
            bg, fg = self._theme_colors(self._window)
            border = self._accent_color(self._window, fallback=fg)
            self._window.configure(background=border)

            outer = tk.Frame(self._window, background=border, highlightthickness=0, borderwidth=0)
            outer.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

            self._title_bar = tk.Frame(outer, bg=bg, height=self._TITLE_H, relief=tk.FLAT, bd=0)
            self._title_bar.pack(fill=tk.X, side=tk.TOP)
            self._title_bar.pack_propagate(False)

            self._title_label = tk.Label(
                self._title_bar,
                text="Popout Tracker",
                bg=bg,
                fg=fg,
                font=self._chrome_font(weight="bold"),
                anchor="w",
            )
            self._title_label.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 4))

            self._close_btn = tk.Button(
                self._title_bar,
                text="X",
                command=self._on_window_close,
                width=3,
                bg=bg,
                fg=fg,
                relief=tk.FLAT,
                bd=0,
                activebackground="#ff4444",
                activeforeground="#ffffff",
                font=self._chrome_font(weight="bold", size=12),
                takefocus=0,
            )
            self._close_btn.pack(side=tk.RIGHT, padx=(0, 5), pady=2)

            self._content_frame = tk.Frame(outer, bg=bg, highlightthickness=0, borderwidth=0)
            self._content_frame.pack(fill=tk.BOTH, expand=True)
            self._canvas = tk.Canvas(
                self._content_frame,
                background=bg,
                highlightthickness=0,
                borderwidth=0,
            )
            self._canvas.pack(fill=tk.BOTH, expand=True)
            self._bind_window_drag()
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
        border = self._accent_color(canvas, fallback=fg)
        try:
            canvas.configure(background=bg)
        except tk.TclError:
            pass
        if self._window is not None:
            try:
                self._window.configure(background=border)
            except tk.TclError:
                pass
        for widget in (self._title_bar, self._title_label, self._content_frame):
            if widget is not None:
                try:
                    widget.configure(background=bg)
                except tk.TclError:
                    pass
        if self._title_label is not None:
            try:
                self._title_label.configure(foreground=fg)
            except tk.TclError:
                pass
        if self._close_btn is not None:
            try:
                self._close_btn.configure(background=bg, foreground=fg)
            except tk.TclError:
                pass

        row_h = self._row_height()
        for rect in bundle.rect_layers:
            fill = self._resolve_layer_color(canvas, rect.fill, fallback=bg, background=bg)
            outline = "" if rect.border_color == "none" else self._resolve_layer_color(canvas, rect.border_color, fallback=fill)
            x1 = self._map_x(rect.x)
            y1 = self._map_y(rect.y, row_h)
            canvas.create_rectangle(
                x1,
                y1,
                x1 + max(1, int(rect.w * self._X_SCALE)),
                y1 + max(1, int(rect.h * row_h / LINE_HEIGHT)),
                fill=fill,
                outline=outline,
            )
        for vector in bundle.vector_layers:
            x = self._map_x(vector.x)
            canvas.create_line(
                x,
                self._map_y(vector.y1, row_h),
                x,
                self._map_y(vector.y2, row_h),
                fill=self._resolve_layer_color(canvas, vector.color, fallback=fg),
                width=1,
            )
        for layer in bundle.text_layers:
            canvas.create_text(
                self._map_x(layer.x),
                self._map_y(layer.y, row_h),
                text=layer.text,
                anchor="nw",
                fill=self._resolve_layer_color(canvas, layer.color, fallback=fg),
                font=self._font_for_layer(layer.weight, layer.msg_id),
            )
        self._fit_canvas(canvas)

    def _fit_canvas(self, canvas: tk.Canvas) -> None:
        bbox = canvas.bbox("all")
        if not bbox:
            content_w, content_h = self._MIN_CONTENT_W, self._MIN_CONTENT_H
        else:
            content_w = max(self._MIN_CONTENT_W, int(bbox[2] + self._PAD_X))
            content_h = max(self._MIN_CONTENT_H, int(bbox[3] + self._PAD_Y))
        total_w = content_w + 2
        total_h = content_h + self._TITLE_H + 2
        try:
            canvas.configure(width=content_w, height=content_h, scrollregion=(0, 0, content_w, content_h))
            if self._window is not None:
                if self._window.winfo_ismapped():
                    x, y = self._window.winfo_x(), self._window.winfo_y()
                else:
                    screen_w = self._window.winfo_screenwidth()
                    screen_h = self._window.winfo_screenheight()
                    x = max(0, (screen_w - total_w) // 2)
                    y = max(0, (screen_h - total_h) // 3)
                self._window.geometry(f"{total_w}x{total_h}+{x}+{y}")
                self._window.deiconify()
        except tk.TclError:
            pass

    def _font_for_layer(self, weight: int, msg_id: str) -> tkfont.Font:
        size = 9
        if msg_id.endswith("hdr-build"):
            size = 11
        elif msg_id.endswith("hdr-system"):
            size = 9
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

    def _chrome_font(self, *, weight: str = "normal", size: int = 10) -> tkfont.Font:
        return tkfont.Font(family=self._resolve_oxanium_family(), size=size, weight=weight)

    def _row_height(self) -> int:
        fonts = [
            self._font_for_layer(700, "hdr-build"),
            self._font_for_layer(500, "hdr-system"),
            self._font_for_layer(400, "body"),
        ]
        heights = []
        for font in fonts:
            try:
                heights.append(int(font.metrics("linespace")))
            except tk.TclError:
                pass
        return max(20, max(heights, default=18) + 3)

    def _map_x(self, x: int) -> int:
        return self._PAD_X + int(max(0, x - OVERLAY_X) * self._X_SCALE)

    def _map_y(self, y: int, row_h: int) -> int:
        return self._PAD_Y + int(round(max(0, y - OVERLAY_Y) / LINE_HEIGHT) * row_h)

    def _bind_window_drag(self) -> None:
        window = self._window
        if window is None:
            return

        def start_drag(event: tk.Event) -> None:
            window._rc_drag_x = event.x_root  # type: ignore[attr-defined]
            window._rc_drag_y = event.y_root  # type: ignore[attr-defined]

        def on_drag(event: tk.Event) -> None:
            if not hasattr(window, "_rc_drag_x"):
                return
            dx = int(event.x_root - window._rc_drag_x)  # type: ignore[attr-defined]
            dy = int(event.y_root - window._rc_drag_y)  # type: ignore[attr-defined]
            window.geometry(f"+{window.winfo_x() + dx}+{window.winfo_y() + dy}")
            window._rc_drag_x = event.x_root  # type: ignore[attr-defined]
            window._rc_drag_y = event.y_root  # type: ignore[attr-defined]

        def stop_drag(_event: tk.Event) -> None:
            for attr in ("_rc_drag_x", "_rc_drag_y"):
                if hasattr(window, attr):
                    delattr(window, attr)

        for widget in (self._title_bar, self._title_label):
            if widget is None:
                continue
            widget.bind("<Button-1>", start_drag)
            widget.bind("<B1-Motion>", on_drag)
            widget.bind("<ButtonRelease-1>", stop_drag)

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
        fg = "#ff8c00"
        try:
            from theme import theme  # type: ignore[import-untyped]

            cur = getattr(theme, "current", None) or {}
            bg = str(cur.get("background") or bg)
            fg = str(cur.get("foreground") or fg)
        except ImportError:
            pass
        return (
            BuildProjectPopout._tk_color_to_hex(widget, bg, fallback="#1e1e1e"),
            BuildProjectPopout._tk_color_to_hex(widget, fg, fallback="#ff8c00"),
        )

    @staticmethod
    def _accent_color(widget: tk.Widget, *, fallback: str) -> str:
        raw = fallback or "#ff8c00"
        try:
            from theme import theme  # type: ignore[import-untyped]

            cur = getattr(theme, "current", None) or {}
            raw = str(cur.get("foreground") or cur.get("highlight") or raw)
        except ImportError:
            pass
        return BuildProjectPopout._tk_color_to_hex(widget, raw, fallback="#ff8c00")

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
