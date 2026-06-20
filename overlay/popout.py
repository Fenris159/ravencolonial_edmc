"""Tk popout window for the build tracker overlay bundle."""

from __future__ import annotations

import logging
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
import importlib.util
from pathlib import Path
from typing import Any, Optional, Tuple

try:
    from ..i18n import tr
    from ..ui.edmc_theme import OXANIUM_FAMILY, ensure_bundled_oxanium_font_registered
except ImportError:  # pragma: no cover
    from i18n import tr  # type: ignore[no-redef]
    _theme_spec = importlib.util.spec_from_file_location(
        "_ravencolonial_edmc_theme",
        Path(__file__).resolve().parents[1] / "ui" / "edmc_theme.py",
    )
    if _theme_spec is None or _theme_spec.loader is None:
        raise
    _theme_mod = importlib.util.module_from_spec(_theme_spec)
    _theme_spec.loader.exec_module(_theme_mod)
    OXANIUM_FAMILY = _theme_mod.OXANIUM_FAMILY
    ensure_bundled_oxanium_font_registered = _theme_mod.ensure_bundled_oxanium_font_registered

from .layers import (
    LINE_HEIGHT,
    MSG_FOOTER,
    MSG_HDR_BUILD,
    MSG_HDR_SYSTEM,
    MSG_TABLE_FC_PREFIX,
    MSG_TABLE_LABEL_PREFIX,
    MSG_TABLE_NEED_PREFIX,
    MSG_TABLE_SHIP_PREFIX,
    OVERLAY_X,
    OVERLAY_Y,
)
from .render_layers import OverlayRenderBundle

logger = logging.getLogger(__name__)
POPOUT_POSITION_CONFIG_KEY = "ravencolonial_overlay_popout_position"
POPOUT_TRACKER_TITLE_KEY = "Popout Tracker"
POPOUT_DARK_BG = "#000000"
POPOUT_DARK_FG = "#ff8000"


class BuildProjectPopout:
    """Render the current build tracker bundle in a themed secondary Tk window."""

    _PAD_X = 12
    _PAD_Y = 10
    _TITLE_H = 38
    _MIN_CONTENT_W = 360
    _MIN_CONTENT_H = 130
    _X_SCALE = 1.28
    _VALUE_COLUMN_GAP = 22
    _LABEL_VALUE_GAP = 34
    _COPY_FLASH_COLOR = "#66ff99"

    def __init__(self, plugin: Any) -> None:
        self._plugin = plugin
        self._window: Optional[tk.Toplevel] = None
        self._title_bar: Optional[tk.Frame] = None
        self._copy_btn: Optional[tk.Canvas] = None
        self._title_label: Optional[tk.Label] = None
        self._close_btn: Optional[tk.Button] = None
        self._content_frame: Optional[tk.Frame] = None
        self._canvas: Optional[tk.Canvas] = None
        self._last_signature: Optional[str] = None
        self._font_cache: dict[Tuple[int, int], tkfont.Font] = {}
        self._closing_from_ui = False
        self._taskbar_configured = False

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
        if window is not None:
            self._save_window_position(window)
        self._window = None
        self._title_bar = None
        self._copy_btn = None
        self._title_label = None
        self._close_btn = None
        self._content_frame = None
        self._canvas = None
        self._taskbar_configured = False
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

    def refresh_localized_text(self) -> None:
        """Update chrome strings after EDMC reloads plugin translations."""
        self._apply_localized_title()

    def _localized_title(self) -> str:
        return tr(POPOUT_TRACKER_TITLE_KEY)

    def _apply_localized_title(self) -> None:
        text = self._localized_title()
        window = self._window
        if window is not None:
            try:
                window.title(text)
            except tk.TclError:
                pass
        label = self._title_label
        if label is not None:
            try:
                label.configure(text=text)
            except tk.TclError:
                pass

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
            self._window = tk.Toplevel()
            popout_title = self._localized_title()
            self._window.title(popout_title)
            self._window.withdraw()
            self._window.overrideredirect(self._uses_borderless_chrome())
            self._window.protocol("WM_DELETE_WINDOW", self._on_window_close)
            self._configure_window_manager_hints(self._window)
            bg, fg = self._theme_colors(self._window)
            border = self._accent_color(self._window, fallback=fg)
            self._window.configure(background=border)

            outer = tk.Frame(self._window, background=border, highlightthickness=0, borderwidth=0)
            outer.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

            self._title_bar = tk.Frame(outer, bg=bg, height=self._TITLE_H, relief=tk.FLAT, bd=0)
            self._title_bar.pack(fill=tk.X, side=tk.TOP)
            self._title_bar.pack_propagate(False)

            self._copy_btn = tk.Canvas(
                self._title_bar,
                width=44,
                height=34,
                background=bg,
                highlightthickness=0,
                borderwidth=0,
                cursor="hand2",
            )
            self._copy_btn.bind("<Button-1>", lambda _event: self._copy_tracker_to_clipboard())
            self._copy_btn.pack(side=tk.LEFT, padx=(5, 0), pady=2)
            self._draw_copy_icon(bg, fg)

            self._title_label = tk.Label(
                self._title_bar,
                text=popout_title,
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

    def _copy_tracker_to_clipboard(self) -> None:
        window = self._window
        if window is None:
            return
        try:
            payload = self._discord_payload_from_bundle(self._compose_bundle())
            window.clipboard_clear()
            window.clipboard_append(payload)
            window.update_idletasks()
            self._flash_copy_button()
        except tk.TclError as exc:
            logger.debug("Build tracker popout copy failed: %s", exc)
        except Exception:
            logger.debug("Build tracker popout copy failed", exc_info=True)

    def _flash_copy_button(self) -> None:
        button = self._copy_btn
        if button is None:
            return
        try:
            bg, fg = self._theme_colors(button)
            self._draw_copy_icon(bg, self._COPY_FLASH_COLOR, width=4)
            button.after(700, lambda: self._draw_copy_icon(bg, fg))
        except tk.TclError:
            pass

    def _draw_copy_icon(self, bg: str, fg: str, *, width: int = 3) -> None:
        button = self._copy_btn
        if button is None:
            return
        try:
            button.configure(background=bg)
            button.delete("all")
            button.create_rectangle(17, 5, 34, 22, outline=fg, width=width)
            button.create_rectangle(8, 12, 28, 32, outline=bg, fill=bg, width=0)
            button.create_rectangle(9, 13, 26, 30, outline=fg, width=width)
        except tk.TclError:
            pass

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
        if self._copy_btn is not None:
            try:
                self._draw_copy_icon(bg, fg)
            except tk.TclError:
                pass

        row_h = self._row_height()
        column_right_edges, value_header_x = self._popout_column_layout(bundle)
        value_header = self._value_header_text(bundle)
        value_header_drawn = False
        for rect in bundle.rect_layers:
            fill = self._resolve_layer_color(canvas, rect.fill, fallback=bg, background=bg)
            outline = "" if rect.border_color == "none" else self._resolve_layer_color(canvas, rect.border_color, fallback=fill)
            x1 = self._map_x(rect.x)
            y1 = self._map_y(rect.y, row_h)
            rect_w = max(1, int(rect.w * self._X_SCALE))
            if column_right_edges:
                rect_w = max(rect_w, max(column_right_edges.values()) - x1 + self._PAD_X)
            canvas.create_rectangle(
                x1,
                y1,
                x1 + rect_w,
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
            prefix = self._value_prefix(layer.msg_id)
            is_header_value = self._is_value_header(layer.msg_id)
            if is_header_value:
                if not value_header_drawn and value_header:
                    canvas.create_text(
                        value_header_x,
                        self._map_y(layer.y, row_h),
                        text=value_header,
                        anchor="nw",
                        fill=self._resolve_layer_color(canvas, layer.color, fallback=fg),
                        font=self._font_for_layer(layer.weight, layer.msg_id),
                    )
                    value_header_drawn = True
                continue
            if prefix is not None and prefix in column_right_edges:
                canvas.create_text(
                    column_right_edges[prefix],
                    self._map_y(layer.y, row_h),
                    text=layer.text,
                    anchor="ne",
                    fill=self._resolve_layer_color(canvas, layer.color, fallback=fg),
                    font=self._font_for_layer(layer.weight, layer.msg_id),
                )
                continue
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
                    saved = self._saved_window_position()
                    if saved is not None:
                        x, y = saved
                    else:
                        screen_w = self._window.winfo_screenwidth()
                        screen_h = self._window.winfo_screenheight()
                        x = max(0, (screen_w - total_w) // 2)
                        y = max(0, (screen_h - total_h) // 3)
                self._window.geometry(f"{total_w}x{total_h}+{x}+{y}")
                self._window.deiconify()
                self._ensure_taskbar_visibility(self._window)
        except tk.TclError:
            pass

    def _popout_column_layout(self, bundle: OverlayRenderBundle) -> Tuple[dict[str, int], int]:
        value_layers = [
            layer
            for layer in bundle.text_layers
            if self._value_prefix(layer.msg_id) is not None
        ]
        if not value_layers:
            return {}, self._PAD_X

        label_right = self._PAD_X
        for layer in bundle.text_layers:
            if not layer.msg_id.startswith(MSG_TABLE_LABEL_PREFIX):
                continue
            text = str(layer.text or "")
            stripped = text.strip()
            if not stripped or stripped.startswith("-"):
                continue
            font = self._font_for_layer(layer.weight, layer.msg_id)
            try:
                width = font.measure(text)
            except tk.TclError:
                width = len(text) * 10
            label_right = max(label_right, self._map_x(layer.x) + width)

        column_left = max(
            min(self._map_x(layer.x) for layer in value_layers),
            label_right + self._LABEL_VALUE_GAP,
        )
        widths: dict[str, int] = {}
        for prefix in (MSG_TABLE_NEED_PREFIX, MSG_TABLE_SHIP_PREFIX, MSG_TABLE_FC_PREFIX):
            matching = [layer for layer in value_layers if layer.msg_id.startswith(prefix)]
            if not matching:
                continue
            measured: list[int] = []
            for layer in matching:
                text = self._header_cell_text(layer) if self._is_value_header(layer.msg_id) else str(layer.text or "")
                try:
                    measured.append(self._font_for_layer(layer.weight, layer.msg_id).measure(text))
                except tk.TclError:
                    measured.append(len(text) * 10)
            widths[prefix] = max(measured, default=0)

        right_edges: dict[str, int] = {}
        current_right = column_left
        for prefix in (MSG_TABLE_NEED_PREFIX, MSG_TABLE_SHIP_PREFIX, MSG_TABLE_FC_PREFIX):
            width = widths.get(prefix)
            if width is None:
                continue
            current_right += width
            right_edges[prefix] = current_right
            current_right += self._VALUE_COLUMN_GAP
        return right_edges, column_left

    def _value_header_text(self, bundle: OverlayRenderBundle) -> str:
        parts: list[str] = []
        for prefix in (MSG_TABLE_NEED_PREFIX, MSG_TABLE_SHIP_PREFIX, MSG_TABLE_FC_PREFIX):
            for layer in bundle.text_layers:
                if layer.msg_id == f"{prefix}000":
                    text = self._header_cell_text(layer)
                    if text:
                        parts.append(text)
                    break
        return "/".join(parts)

    @staticmethod
    def _value_prefix(msg_id: str) -> Optional[str]:
        for prefix in (MSG_TABLE_NEED_PREFIX, MSG_TABLE_SHIP_PREFIX, MSG_TABLE_FC_PREFIX):
            if msg_id.startswith(prefix):
                return prefix
        return None

    @staticmethod
    def _is_value_header(msg_id: str) -> bool:
        return msg_id in {
            f"{MSG_TABLE_NEED_PREFIX}000",
            f"{MSG_TABLE_SHIP_PREFIX}000",
            f"{MSG_TABLE_FC_PREFIX}000",
        }

    @staticmethod
    def _header_cell_text(layer: Any) -> str:
        return str(getattr(layer, "text", "") or "").strip()

    @classmethod
    def _discord_payload_from_bundle(cls, bundle: OverlayRenderBundle) -> str:
        text = cls._discord_text_from_bundle(bundle).rstrip()
        if not text:
            text = "No tracker data available."
        return f"```\n{text}\n```"

    @classmethod
    def _discord_text_from_bundle(cls, bundle: OverlayRenderBundle) -> str:
        header = ""
        subheader = ""
        labels: dict[int, str] = {}
        needs: dict[int, str] = {}
        fcs: dict[int, str] = {}
        footer_lines: list[str] = []

        for layer in bundle.text_layers:
            msg_id = str(layer.msg_id)
            if msg_id == MSG_HDR_BUILD:
                header = str(layer.text or "").strip()
            elif msg_id == MSG_HDR_SYSTEM:
                subheader = str(layer.text or "").strip()
            elif msg_id.startswith(MSG_TABLE_LABEL_PREFIX):
                idx = cls._message_row_index(msg_id, MSG_TABLE_LABEL_PREFIX)
                if idx is not None:
                    labels[idx] = str(layer.text or "").rstrip()
            elif msg_id.startswith(MSG_TABLE_NEED_PREFIX):
                idx = cls._message_row_index(msg_id, MSG_TABLE_NEED_PREFIX)
                if idx is not None:
                    needs[idx] = str(layer.text or "").strip()
            elif msg_id.startswith(MSG_TABLE_FC_PREFIX):
                idx = cls._message_row_index(msg_id, MSG_TABLE_FC_PREFIX)
                if idx is not None:
                    fcs[idx] = str(layer.text or "").strip()
            elif msg_id == MSG_FOOTER:
                footer_lines.extend(cls._discord_footer_lines(str(layer.text or "")))

        lines: list[str] = []
        if header:
            lines.append(header)
        if subheader:
            lines.append(subheader)

        row_indices = sorted(set(labels) | set(needs) | set(fcs))
        if row_indices:
            if lines:
                lines.append("")
            show_fc = any(text for text in fcs.values())
            label_w = max((len(labels.get(i, "").rstrip()) for i in row_indices), default=0)
            need_w = max((len(needs.get(i, "").strip()) for i in row_indices), default=0)
            fc_w = max((len(fcs.get(i, "").strip()) for i in row_indices), default=0) if show_fc else 0

            table_lines: list[str] = []
            for idx in row_indices:
                label = labels.get(idx, "").rstrip()
                need = needs.get(idx, "").strip()
                fc = fcs.get(idx, "").strip()
                if need or (show_fc and fc):
                    parts = [label.ljust(label_w), need.rjust(need_w)]
                    if show_fc:
                        parts.append(fc.rjust(fc_w))
                    table_lines.append("  ".join(parts).rstrip())
                    continue
                stripped = label.strip()
                if stripped and set(stripped) <= {"-"} and table_lines:
                    table_lines.append("-" * len(table_lines[0]))
                elif label:
                    table_lines.append(label)
            lines.extend(table_lines)

        if footer_lines:
            if lines:
                lines.append("")
            lines.extend(footer_lines)
        return "\n".join(lines)

    @staticmethod
    def _message_row_index(msg_id: str, prefix: str) -> Optional[int]:
        try:
            return int(msg_id[len(prefix) :])
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _discord_footer_lines(text: str) -> list[str]:
        lines: list[str] = []
        for raw in str(text or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            lower = line.lower()
            if "deficit" in lower:
                deficit_end = lower.find("deficit") + len("deficit")
                line = line[:deficit_end].rstrip()
                lines.append(line)
        return lines

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
            self._save_window_position(window)
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
    def _uses_borderless_chrome() -> bool:
        return sys.platform.startswith("win")

    @staticmethod
    def _configure_window_manager_hints(window: tk.Toplevel) -> None:
        if sys.platform.startswith("win"):
            return
        try:
            window.attributes("-type", "normal")
        except tk.TclError:
            pass

    def _ensure_taskbar_visibility(self, window: tk.Toplevel) -> None:
        if self._taskbar_configured:
            return
        if not sys.platform.startswith("win"):
            self._taskbar_configured = True
            return
        try:
            window.after(0, lambda: self._promote_windows_taskbar(window))
            self._taskbar_configured = True
        except tk.TclError:
            pass

    @staticmethod
    def _promote_windows_taskbar(window: tk.Toplevel) -> None:
        try:
            import ctypes

            window.update_idletasks()
            hwnd = int(window.winfo_id())
            user32 = ctypes.windll.user32
            parent_hwnd = int(user32.GetParent(hwnd) or 0)
            if parent_hwnd:
                hwnd = parent_hwnd
            gwl_exstyle = -20
            ws_ex_appwindow = 0x00040000
            ws_ex_toolwindow = 0x00000080
            swp_nosize = 0x0001
            swp_nomove = 0x0002
            swp_nozorder = 0x0004
            swp_framechanged = 0x0020
            try:
                get_window_long = user32.GetWindowLongPtrW
                set_window_long = user32.SetWindowLongPtrW
            except AttributeError:
                get_window_long = user32.GetWindowLongW
                set_window_long = user32.SetWindowLongW
            style = int(get_window_long(hwnd, gwl_exstyle))
            style = (style | ws_ex_appwindow) & ~ws_ex_toolwindow
            set_window_long(hwnd, gwl_exstyle, style)
            user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                swp_nomove | swp_nosize | swp_nozorder | swp_framechanged,
            )
            window.withdraw()
            window.after(0, window.deiconify)
        except Exception:
            logger.debug("Build tracker popout taskbar promotion failed", exc_info=True)

    @staticmethod
    def _saved_window_position() -> Optional[Tuple[int, int]]:
        try:
            from config import config

            raw = str(config.get_str(POPOUT_POSITION_CONFIG_KEY) or "").strip()
        except Exception:
            return None
        if not raw:
            return None
        try:
            x_raw, y_raw = raw.split(",", 1)
            return int(x_raw), int(y_raw)
        except (TypeError, ValueError):
            logger.debug("Ignoring invalid popout position config: %r", raw)
            return None

    @staticmethod
    def _save_window_position(window: tk.Toplevel) -> None:
        try:
            x = int(window.winfo_x())
            y = int(window.winfo_y())
        except tk.TclError:
            return
        try:
            from config import config

            config.set(POPOUT_POSITION_CONFIG_KEY, f"{x},{y}")
        except Exception:
            logger.debug("Build tracker popout position save failed", exc_info=True)

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
        return (
            BuildProjectPopout._tk_color_to_hex(widget, POPOUT_DARK_BG, fallback="#000000"),
            BuildProjectPopout._tk_color_to_hex(widget, POPOUT_DARK_FG, fallback="#ff8000"),
        )

    @staticmethod
    def _accent_color(widget: tk.Widget, *, fallback: str) -> str:
        return BuildProjectPopout._tk_color_to_hex(widget, POPOUT_DARK_FG, fallback=fallback or "#ff8000")

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
