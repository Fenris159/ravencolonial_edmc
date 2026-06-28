"""
UI Manager for Ravencolonial EDMC Plugin

Handles UI state management and updates.
"""

import logging
import math
import os
import tkinter as tk
from dataclasses import dataclass
from enum import Enum, auto
from tkinter import ttk, messagebox
from threading import Thread
from typing import Any, Dict, List, Optional, Union, cast

import plug
from config import config

from ..api.client import resolve_build_id
from ..i18n import tr, trf
from ..plugin_config import PluginConfig
from ..exc_utils import CONFIG_READ_ERRORS, HTTP_CLIENT_ERRORS, OVERLAY_UI_ERRORS, UPDATE_PATH_ERRORS
from .edmc_theme import apply_theme_to_widget_subtree, plugin_header_font, reapply_plugin_header_font
from .panel_collapse import PanelCollapseToggle
from .theme_safe_canvas import ThemeSafeCanvas
from .themed_combobox import ThemedCombobox
from .themed_report_dialog import show_themed_report_dialog
from .link_build_site_worker import (
    apply_link_build_site_success,
    prepare_link_build_site_context,
    depot_fields_error_message,
    run_link_build_site_worker,
    show_link_build_site_phase_dialog,
    validate_link_build_site_inputs,
)
from .overlay_row import OverlayBuildRowController
from .plan_site_combo import (
    PlanSiteComboUpdate,
    plan_site_cache_matches_system,
    plan_site_empty_rows_update,
    plan_site_populated_rows_update,
    plan_site_stale_cache_update,
    plan_site_transient_update,
)
from .plan_sites_refresh import fetch_plan_sites_worker
from .plugin_separator import StyledPluginSeparator, create_styled_plugin_separator

# Plan-site dropdown: synthetic id for "Create New" (scratch create dialog)
PLAN_SITE_CREATE_NEW_ID = "__CREATE_NEW__"


class _DockedCreateBtnKind(Enum):
    """Main action button while docked at a construction megaship (plan row + project probe)."""

    OPEN_BUILD = auto()
    REFRESH_PLAN_SITES = auto()
    SELECT_PLAN_SITE = auto()
    SCRATCH_CREATE = auto()
    LINK_PLAN_SITE = auto()


@dataclass(frozen=True)
class _DockedCreateButtonPlan:
    kind: _DockedCreateBtnKind
    build_id: str = ""
    build_display_name: str = ""


class _SimpleTooltip:
    """Small Tk tooltip for icon-only plugin buttons."""

    def __init__(self, widget: tk.Widget, text: str) -> None:
        self._widget = widget
        self._text = text
        self._tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def set_text(self, text: str) -> None:
        self._text = text

    def _show(self, _event: object = None) -> None:
        if self._tip is not None or not self._text:
            return
        try:
            x = self._widget.winfo_rootx() + 10
            y = max(0, self._widget.winfo_rooty() - 28)
        except tk.TclError:
            return
        tip = tk.Toplevel(self._widget)
        self._tip = tip
        try:
            tip.wm_overrideredirect(True)
            tip.wm_geometry(f"+{x}+{y}")
            label = tk.Label(
                tip,
                text=self._text,
                justify=tk.LEFT,
                relief=tk.SOLID,
                borderwidth=1,
                padx=6,
                pady=3,
            )
            label.pack()
            apply_theme_to_widget_subtree(tip)
        except tk.TclError:
            self._hide()

    def _hide(self, _event: object = None) -> None:
        tip = self._tip
        self._tip = None
        if tip is not None:
            try:
                tip.destroy()
            except tk.TclError:
                pass


def _plan_rows_only(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cached plan-site rows still in ``plan`` status (linked rows become ``build`` or are removed)."""
    return [
        s
        for s in rows
        if isinstance(s, dict) and str(s.get("status", "")).lower() == "plan"
    ]


def _strip_leading_v_for_display(version: str) -> str:
    """GitHub ``tag_name`` values include a leading ``v``; UI strings already prefix ``v{{…}}``."""
    if not version or version == "unknown":
        return version
    version = str(version).strip()
    return version[1:] if version[:1].lower() == "v" else version


def _plugin_frame_alive(plugin: Any) -> bool:
    frame = getattr(plugin, "frame", None)
    if frame is None:
        return False
    try:
        return bool(frame.winfo_exists())
    except tk.TclError:
        return False


def _safe_widget_configure(widget: Any, **kwargs: Any) -> None:
    if widget is None:
        return
    try:
        widget.configure(**kwargs)
    except tk.TclError:
        pass


def _short_exception_detail(exc: BaseException, limit: int = 480) -> str:
    """Avoid huge ``str(exc)`` strings in dialogs that can widen EDMC's window."""
    s = str(exc).strip()
    if not s:
        return type(exc).__name__
    s = " ".join(s.split())
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "\u2026"


def _widget_color_hex(widget: tk.Widget, color: str, fallback: str) -> str:
    raw = str(color or "").strip() or fallback
    try:
        r, g, b = widget.winfo_rgb(raw)
        return f"#{r // 257:02x}{g // 257:02x}{b // 257:02x}"
    except tk.TclError:
        if raw.startswith("#") and len(raw) == 7:
            return raw
        return fallback


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    h = color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _blend_hex(fg: str, bg: str, alpha: float) -> str:
    fr, fg_g, fb = _hex_to_rgb(fg)
    br, bg_g, bb = _hex_to_rgb(bg)
    a = max(0.0, min(1.0, alpha))
    red = round(fr * a + br * (1 - a))
    green = round(fg_g * a + bg_g * (1 - a))
    blue = round(fb * a + bb * (1 - a))
    return f"#{red:02x}{green:02x}{blue:02x}"


def _distance_to_segment(px: float, py: float, segment: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = segment
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def _line_coverage(
    x: int,
    y: int,
    segments: tuple[tuple[float, float, float, float], ...],
    *,
    stroke_width: float,
    samples: int = 4,
) -> float:
    hits = 0
    threshold = stroke_width / 2.0
    for sy in range(samples):
        py = y + (sy + 0.5) / samples
        for sx in range(samples):
            px = x + (sx + 0.5) / samples
            if any(_distance_to_segment(px, py, seg) <= threshold for seg in segments):
                hits += 1
    return hits / float(samples * samples)


def _segments_from_points(points: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float, float, float], ...]:
    return tuple(
        (points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])
        for i in range(len(points) - 1)
    )


try:
    from ttkHyperlinkLabel import HyperlinkLabel
except ImportError:  # pragma: no cover - only when running outside EDMC
    HyperlinkLabel = None  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)

try:
    from config import appname  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    appname = "EDMarketConnector"

# Same namespace as ``load.py`` / the RavenColonial issue log file.
issue_log = logging.getLogger(
    f"{appname}.{os.path.basename(os.path.dirname(os.path.dirname(__file__)))}"
)


class UIManager:
    """Manages UI elements and state for the Ravencolonial plugin"""

    def __init__(self, plugin_instance):
        """
        Initialize the UI manager

        :param plugin_instance: The main plugin instance
        """
        self.plugin = plugin_instance
        self.status_label: Optional[ttk.Label] = None
        self._status_l10n_key: Optional[str] = None
        self.create_button: Optional[tk.Button] = None
        self.fc_manifest_button: Optional[ThemeSafeCanvas] = None
        self._fc_manifest_icon_image: Optional[tk.PhotoImage] = None
        self._fc_manifest_tooltip: Optional[_SimpleTooltip] = None
        self.project_link_label: Optional[Union[ttk.Label, ttk.Widget]] = None
        self.update_frame: Optional[tk.Frame] = None
        self.top_separator: Optional[StyledPluginSeparator] = None
        self.bottom_separator: Optional[StyledPluginSeparator] = None
        self.header_frame: Optional[tk.Frame] = None
        self.header_label: Optional[tk.Label] = None
        self._body_frame: Optional[tk.Frame] = None
        self._collapse_toggle: Optional[PanelCollapseToggle] = None
        self._panel_expanded: bool = True
        self.main_controls_frame: Optional[tk.Frame] = None
        # Plan sites row (v2 /sites + architect gate)
        self.plan_sites_row: Optional[tk.Frame] = None
        self.plan_sites_label: Optional[ttk.Label] = None
        self.plan_sites_combo: Optional[ThemedCombobox] = None
        self.plan_sites_refresh_btn: Optional[tk.Button] = None
        self.plan_sites_combo_var: Optional[tk.StringVar] = None
        self._plan_site_display_to_id: Dict[str, Optional[str]] = {}
        self._plan_site_refresh_inflight: bool = False
        self._link_build_inflight: bool = False
        self._overlay_row = OverlayBuildRowController(self)
        self._theme_refresh_after_id: Optional[str] = None
        self._theme_binding_target: Optional[tk.Misc] = None
        self._theme_binding_id: Optional[str] = None

    def _project_link_url(self, _text: str) -> str:
        """URL for HyperlinkLabel (evaluated when the user clicks)."""
        bid = self.plugin.current_build_id if self.plugin else None
        if bid:
            return f"https://ravencolonial.com/#build={bid}"
        return "https://ravencolonial.com/"

    def create_plugin_frame(self, parent: tk.Widget) -> tk.Widget:
        """
        Create the main plugin frame for EDMC

        :param parent: The parent frame
        :return: The created frame
        """
        # Layout uses tk.Frame so EDMC theme.update can set background (grey4 / system).
        # ttk.Frame keeps the Ttk style panel color on Windows, which shows as light bands
        # around tk.Button / labels — GalaxyGPS uses tk.Frame for the same reason.
        frame = tk.Frame(parent, highlightthickness=0, borderwidth=0)
        self.plugin.frame = frame
        self._panel_expanded = self._panel_expanded_from_config()

        self.top_separator = create_styled_plugin_separator(frame)
        self.top_separator.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(4, 2))

        header_row = tk.Frame(frame, highlightthickness=0, borderwidth=0)
        header_row.pack(side=tk.TOP, fill=tk.X)
        self.header_frame = header_row
        _header_font = plugin_header_font()
        self.header_label = tk.Label(
            header_row,
            text=tr("RavenColonialWeb"),
            font=_header_font,
            anchor=tk.W,
        )
        self.header_label.pack(side=tk.LEFT, padx=(5, 5), pady=(6, 4))

        self._collapse_toggle = PanelCollapseToggle(
            header_row,
            on_toggle=self._on_panel_collapse_toggle,
            expanded=self._panel_expanded,
        )
        self._collapse_toggle.widget.pack(side=tk.RIGHT, padx=(5, 5), pady=(6, 4))

        self._body_frame = tk.Frame(frame, highlightthickness=0, borderwidth=0)
        self._body_frame.pack(side=tk.TOP, fill=tk.X)

        # Main controls frame (contains status and buttons)
        self.main_controls_frame = tk.Frame(self._body_frame, highlightthickness=0, borderwidth=0)
        self.main_controls_frame.pack(side=tk.TOP, fill=tk.X)

        self._overlay_row.build_row(self.main_controls_frame)
        # Plan site selector (above dock / create controls)
        self._build_plan_sites_row(self.main_controls_frame)

        # Button row frame (contains button and project link)
        button_row = tk.Frame(self.main_controls_frame, highlightthickness=0, borderwidth=0)
        button_row.pack(side=tk.TOP, fill=tk.X)

        # Project link: themed hyperlink when EDMC's widget is available
        if HyperlinkLabel is not None:
            self.project_link_label = cast(ttk.Widget, HyperlinkLabel(
                button_row,
                text="",
                url=self._project_link_url,
                underline=True,
            ))
        else:
            self.project_link_label = ttk.Label(button_row, text="", cursor="hand2")
            self.project_link_label.bind("<Button-1>", lambda e: self._open_project_link())
        self.project_link_label.pack(side=tk.LEFT, padx=5)
        self.plugin.project_link_label = self.project_link_label
        self.plugin.current_build_id = None

        # Classic tk.Button + theme.update matches EDMC dark theme and plugins like GalaxyGPS
        # (ttk.Button + theme.update strips TButton chrome / wrong disabled colors on Windows).
        self.create_button = tk.Button(
            button_row,
            text=tr("Waiting for Dock"),
            command=lambda: self._open_create_dialog(parent),
            state=tk.DISABLED,
        )
        self.create_button.pack(side=tk.LEFT, padx=5)
        self.plugin.create_button = self.create_button

        self.fc_manifest_button = ThemeSafeCanvas(
            button_row,
            width=40,
            height=44,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
        )
        self.fc_manifest_button.pack(side=tk.RIGHT, padx=(5, 5))
        self.fc_manifest_button.bind("<Button-1>", lambda _event: self.open_fc_manifest_editor())
        self.fc_manifest_button.bind("<Enter>", lambda _event: self._draw_fc_manifest_button_icon(hover=True), add="+")
        self.fc_manifest_button.bind("<Leave>", lambda _event: self._draw_fc_manifest_button_icon(hover=False), add="+")
        self._fc_manifest_tooltip = _SimpleTooltip(self.fc_manifest_button, tr("Edit Carrier Manifest"))

        # Status row frame
        status_row = tk.Frame(self.main_controls_frame, highlightthickness=0, borderwidth=0)
        status_row.pack(side=tk.TOP, fill=tk.X)

        # Status label
        self.status_label = ttk.Label(
            status_row,
            text=tr("Ravencolonial: Ready"),
            wraplength=360,
        )
        self._status_l10n_key = "Ravencolonial: Ready"
        self.status_label.pack(side=tk.LEFT, padx=5)
        self.plugin.status_label = self.status_label

        # Check for updates after a short delay to allow UI to settle
        frame.after(3000, self._check_and_show_update_notification)

        self.bottom_separator = create_styled_plugin_separator(frame)
        self.bottom_separator.pack(side=tk.TOP, fill=tk.X, padx=6, pady=(2, 4))

        apply_theme_to_widget_subtree(frame)
        self._draw_fc_manifest_button_icon()
        if self.header_label is not None:
            reapply_plugin_header_font(self.header_label)
        if self.top_separator is not None:
            self.top_separator.refresh_colors()
        if self.bottom_separator is not None:
            self.bottom_separator.refresh_colors()
        self._refresh_collapse_toggle_theme()
        self._apply_panel_expanded(self._panel_expanded)
        self._overlay_row.refresh_checkbox_themes()
        self._overlay_row.sync_enabled_from_config()
        self.refresh_overlay_build_row_state()
        self.refresh_plan_site_row_state()
        self._bind_theme_refresh_events(frame)
        return frame

    def _on_panel_collapse_toggle(self, expanded: bool) -> None:
        self._panel_expanded = expanded
        self._save_panel_expanded(expanded)
        self._apply_panel_expanded(expanded)

    def _apply_panel_expanded(self, expanded: bool) -> None:
        """Show or hide plugin controls; header and divider lines stay visible."""
        body = self._body_frame
        header = self.header_frame
        bottom_sep = self.bottom_separator
        if body is None or header is None:
            return
        try:
            if expanded:
                if not body.winfo_manager():
                    pack_opts: dict[str, object] = {"side": tk.TOP, "fill": tk.X, "after": header}
                    if bottom_sep is not None and bottom_sep.winfo_manager():
                        pack_opts["before"] = bottom_sep
                    body.pack(**pack_opts)
            elif body.winfo_manager():
                body.pack_forget()
        except tk.TclError:
            pass

    @staticmethod
    def _panel_expanded_from_config() -> bool:
        try:
            return bool(config.get_bool("ravencolonial_panel_expanded", default=True))
        except CONFIG_READ_ERRORS:
            return True

    @staticmethod
    def _save_panel_expanded(expanded: bool) -> None:
        try:
            config.set("ravencolonial_panel_expanded", bool(expanded))
        except CONFIG_READ_ERRORS as exc:
            logger.debug("Could not save panel expanded state: %s", exc)

    def _refresh_collapse_toggle_theme(self) -> None:
        toggle = self._collapse_toggle
        header = self.header_frame
        if toggle is None:
            return
        bg = None
        if header is not None:
            try:
                bg = header.cget("bg")
            except tk.TclError:
                bg = None
        toggle.apply_theme(background=bg)

    def _bind_theme_refresh_events(self, frame: tk.Widget) -> None:
        """Listen for Tk/ttk theme changes and repaint plugin-owned classic widgets."""
        try:
            root = frame.winfo_toplevel()
            self._theme_binding_target = root
            self._theme_binding_id = root.bind("<<ThemeChanged>>", self._on_theme_changed, add="+")
            frame.bind("<Destroy>", self._on_plugin_frame_destroy, add="+")
        except tk.TclError:
            pass

    def _on_plugin_frame_destroy(self, event: tk.Event) -> None:
        frame = getattr(self.plugin, "frame", None)
        if event.widget is not frame:
            return
        if self._theme_refresh_after_id and frame is not None:
            try:
                frame.after_cancel(self._theme_refresh_after_id)
            except tk.TclError:
                pass
        self._theme_refresh_after_id = None
        if self._theme_binding_target is not None and self._theme_binding_id:
            try:
                self._theme_binding_target.unbind("<<ThemeChanged>>", self._theme_binding_id)
            except tk.TclError:
                pass
        self._theme_binding_target = None
        self._theme_binding_id = None

    def _on_theme_changed(self, _event: tk.Event) -> None:
        frame = getattr(self.plugin, "frame", None)
        if frame is None:
            return
        if self._theme_refresh_after_id:
            try:
                frame.after_cancel(self._theme_refresh_after_id)
            except tk.TclError:
                pass
        try:
            self._theme_refresh_after_id = frame.after(50, self.refresh_theme)
        except tk.TclError:
            self._theme_refresh_after_id = None

    def refresh_theme(self) -> None:
        """Re-apply EDMC theme to plugin widgets that are not native ttk controls."""
        self._theme_refresh_after_id = None
        frame = getattr(self.plugin, "frame", None)
        if frame is None:
            return
        try:
            if not frame.winfo_exists():
                return
        except tk.TclError:
            return

        apply_theme_to_widget_subtree(frame)
        if self.header_label is not None:
            reapply_plugin_header_font(self.header_label)
        if self.top_separator is not None:
            self.top_separator.refresh_colors()
        if self.bottom_separator is not None:
            self.bottom_separator.refresh_colors()
        self._refresh_collapse_toggle_theme()
        self._overlay_row.refresh_theme()
        if self.plan_sites_row is not None:
            apply_theme_to_widget_subtree(self.plan_sites_row)
        if self.plan_sites_combo is not None:
            self.plan_sites_combo.apply_theme_styling()
        if self.update_frame is not None:
            apply_theme_to_widget_subtree(self.update_frame)
        if getattr(self.plugin, "fc_manifest_editor", None):
            self.plugin.fc_manifest_editor.refresh_theme()
        self._draw_fc_manifest_button_icon()

    def _draw_fc_manifest_button_icon(self, *, hover: bool = False) -> None:
        canvas = self.fc_manifest_button
        if canvas is None:
            return
        dark = False
        try:
            dark = config.get_int("theme") in (1, 2)
        except CONFIG_READ_ERRORS:
            pass
        bg = "#1e1e1e" if dark else "#f0f0f0"
        line = "orange" if dark else "#000000"
        try:
            parent_bg = canvas.master.cget("background")
            if parent_bg and str(parent_bg).lower() not in ("systembuttonface", "white", "#ffffff"):
                bg = str(parent_bg)
        except tk.TclError:
            pass
        if dark:
            try:
                from theme import theme  # type: ignore[import-untyped]

                current = getattr(theme, "current", None) or {}
                line = str(current.get("foreground") or line)
            except ImportError:
                pass
        hover_fill = "#2a2a2a" if dark else "#e8e8e8"
        try:
            bg_hex = _widget_color_hex(canvas, bg, "#1e1e1e" if dark else "#f0f0f0")
            line_hex = _widget_color_hex(canvas, line, "#ff8000" if dark else "#000000")
            hover_hex = _widget_color_hex(canvas, hover_fill, bg_hex)
            canvas.configure(background=bg)
            canvas.delete("all")
            self._fc_manifest_icon_image = self._carrier_manifest_icon_image(
                bg=hover_hex if hover else bg_hex,
                line=line_hex,
            )
            canvas.create_image(20, 22, image=self._fc_manifest_icon_image)
        except tk.TclError:
            pass

    @staticmethod
    def _carrier_manifest_icon_image(*, bg: str, line: str) -> tk.PhotoImage:
        width = 40
        height = 44
        outer = _segments_from_points(((20, 5), (35, 21), (27, 37), (13, 37), (5, 21), (20, 5)))
        inner = _segments_from_points(((20, 15), (26, 18), (26, 25), (20, 29), (14, 25), (14, 18), (20, 15)))
        mark = ((16, 22, 24, 22),)
        segments = outer + inner + mark
        image = tk.PhotoImage(width=width, height=height)
        rows: List[str] = []
        for y in range(height):
            row: List[str] = []
            for x in range(width):
                coverage = _line_coverage(x, y, segments, stroke_width=2.2)
                row.append(_blend_hex(line, bg, coverage) if coverage else bg)
            rows.append("{" + " ".join(row) + "}")
        image.put(" ".join(rows), to=(0, 0))
        return image

    def refresh_overlay_build_row_state(self) -> None:
        self._overlay_row.refresh_row_state()

    def refresh_localized_text(self) -> None:
        """Repaint plugin-owned text after EDMC changes language in Settings."""
        if not _plugin_frame_alive(self.plugin):
            return
        self._refresh_localized_static_labels()
        self._overlay_row.refresh_localized_text()
        if self._fc_manifest_tooltip is not None:
            self._fc_manifest_tooltip.set_text(tr("Edit Carrier Manifest"))
        self.refresh_plan_site_row_state()
        self.update_create_button()
        self._refresh_localized_status_label()
        self._rebuild_update_notification_frame()
        self.refresh_theme()

    def _refresh_localized_static_labels(self) -> None:
        _safe_widget_configure(self.header_label, text=tr("RavenColonialWeb"))
        _safe_widget_configure(self.plan_sites_label, text=tr("Select Plan Site"))

    def _refresh_localized_status_label(self) -> None:
        if self.status_label is None or not self._status_l10n_key:
            return
        _safe_widget_configure(self.status_label, text=tr(self._status_l10n_key))

    def _rebuild_update_notification_frame(self) -> None:
        if self.update_frame is None:
            return
        try:
            self.update_frame.destroy()
        except tk.TclError:
            pass
        self.update_frame = None
        self._check_and_show_update_notification()

    @property
    def overlay_build_combo(self) -> Optional[ThemedCombobox]:
        return self._overlay_row.combo

    def _build_plan_sites_row(self, parent: tk.Widget) -> None:
        """Row: label + plan-site combobox + refresh (worker fetches; UI updates on main thread only)."""
        row = tk.Frame(parent, highlightthickness=0, borderwidth=0)
        row.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        self.plan_sites_row = row

        lbl = ttk.Label(row, text=tr("Select Plan Site"))
        lbl.pack(side=tk.LEFT, padx=(5, 6))
        self.plan_sites_label = lbl

        # Tight horizontal packing: collapsed width is set from the visible label text;
        # the dropdown list opens at full measured width (see ``ThemedCombobox``).
        combo_frame = tk.Frame(row, highlightthickness=0, borderwidth=0)
        combo_frame.pack(side=tk.LEFT)
        self.plan_sites_combo_var = tk.StringVar(value="")
        self.plan_sites_combo = ThemedCombobox(
            combo_frame,
            textvariable=self.plan_sites_combo_var,
            state="disabled",
        )
        self.plan_sites_combo.pack(side=tk.LEFT)
        self.plan_sites_combo.bind("<<ComboboxSelected>>", self._on_plan_site_combo_selected)

        self.plan_sites_refresh_btn = tk.Button(
            row,
            text="\u27f3",
            width=3,
            command=self.start_plan_sites_refresh,
        )
        self.plan_sites_refresh_btn.pack(side=tk.LEFT, padx=(4, 5))
        try:
            self.plan_sites_refresh_btn.configure(cursor="hand2")
        except tk.TclError:
            pass

        apply_theme_to_widget_subtree(row)
        if self.plan_sites_combo:
            self.plan_sites_combo.apply_theme_styling()

    def _show_plan_sites_feedback_dialog(self, *, title: str, summary: str, detail: str) -> None:
        """GalaxyGPS-style modal: full error text here; combobox stays a short label."""
        parent = getattr(self.plugin, "frame", None)
        if parent is None:
            return
        show_themed_report_dialog(
            parent,
            title=title,
            summary=summary,
            detail=detail,
            copy_button_text=tr("Copy Error Msg"),
            ok_button_text=tr("OK"),
        )

    def _finish_plan_site_combo_appearance(self) -> None:
        """Theme + compact entry width after values/text change (GalaxyGPS-style combobox)."""
        combo = self.plan_sites_combo
        var = self.plan_sites_combo_var
        if not combo or not var:
            return
        combo.apply_theme_styling()
        combo.set_entry_width_for_text(var.get() or "")

    def _apply_plan_site_combo_update(
        self,
        update: PlanSiteComboUpdate,
        *,
        p: Any,
        rows: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        combo = self.plan_sites_combo
        var = self.plan_sites_combo_var
        if not combo or not var:
            return
        self._plan_site_display_to_id = dict(update.display_to_id)
        if update.clear_selection:
            p.selected_plan_site_id = None
            p.selected_plan_site_obj = None
        combo["values"] = tuple(update.values)
        var.set(update.display)
        try:
            combo.configure(state=update.state)
        except tk.TclError:
            pass
        if rows is not None and update.state == "readonly":
            placeholder = tr("— choose site —")
            create_new_lbl = tr("Create New")
            self._restore_plan_site_combo_selection(p, rows, placeholder, create_new_lbl)
        self._finish_plan_site_combo_appearance()

    def refresh_plan_site_row_state(self) -> None:
        """Main thread: reconcile combobox with cache vs current ``SystemAddress``."""
        combo = self.plan_sites_combo
        var = self.plan_sites_combo_var
        p = self.plugin
        if not combo or not var or not p:
            return

        self._plan_site_display_to_id.clear()
        cur = p.current_system_address
        key = p.plan_sites_system_key
        rows = _plan_rows_only(p.plan_sites_rows)

        msg = getattr(p, "plan_sites_transient_message", None)
        if msg:
            self._apply_plan_site_combo_update(plan_site_transient_update(msg), p=p)
            return

        if not plan_site_cache_matches_system(key, cur):
            if key is not None or rows or getattr(p, "selected_plan_site_id", None):
                logger.debug(
                    "Clearing stale plan-site cache: cache_system=%s current_system=%s rows=%d",
                    key,
                    cur,
                    len(rows),
                )
                p.clear_plan_sites_cache()
            self._apply_plan_site_combo_update(plan_site_stale_cache_update(), p=p)
            return

        allow_cn = getattr(p, "plan_sites_allow_create_new", True)
        if not rows:
            build_n = len(getattr(p, "overlay_build_site_rows", None) or [])
            update = plan_site_empty_rows_update(
                allow_create_new=allow_cn,
                create_new_id=PLAN_SITE_CREATE_NEW_ID,
            )
            self._apply_plan_site_combo_update(update, p=p, rows=[])
            if allow_cn:
                issue_log.info(
                    "Plan sites: no plan rows in system %s (%d build site(s)); showing Create New",
                    key,
                    build_n,
                )
            else:
                issue_log.info(
                    "Plan sites: no orbital plan rows for non-architect in system %s "
                    "(%d build site(s))",
                    key,
                    build_n,
                )
            return

        update = plan_site_populated_rows_update(
            rows,
            allow_create_new=allow_cn,
            create_new_id=PLAN_SITE_CREATE_NEW_ID,
        )
        self._apply_plan_site_combo_update(update, p=p, rows=rows)
        issue_log.info(
            "Plan sites: %d plan row(s) in combobox for system %s (create_new=%s)",
            len(rows),
            key,
            allow_cn,
        )

    def _restore_plan_site_combo_selection(
        self,
        p: Any,
        rows: List[Dict[str, Any]],
        placeholder: str,
        create_new_lbl: str,
    ) -> None:
        """Keep combobox selection when values still valid (e.g. after ``update_create_button``)."""
        combo = self.plan_sites_combo
        var = self.plan_sites_combo_var
        if not combo or not var:
            return
        want = getattr(p, "selected_plan_site_id", None)
        labels = list(combo["values"]) if combo["values"] else []
        restored = False
        if want == PLAN_SITE_CREATE_NEW_ID and create_new_lbl in labels:
            var.set(create_new_lbl)
            p.selected_plan_site_id = PLAN_SITE_CREATE_NEW_ID
            p.selected_plan_site_obj = None
            restored = True
        elif want:
            for lab, iid in list(self._plan_site_display_to_id.items()):
                if iid == want and lab in labels:
                    var.set(lab)
                    p.selected_plan_site_id = want
                    p.selected_plan_site_obj = None
                    for r in rows:
                        if str(r.get("id")) == str(want):
                            p.selected_plan_site_obj = r
                            break
                    restored = True
                    break
        if not restored:
            var.set(placeholder)
            p.selected_plan_site_id = None
            p.selected_plan_site_obj = None

    def _on_plan_site_combo_selected(self, _event: object = None) -> None:
        combo = self.plan_sites_combo
        p = self.plugin
        if not combo or not p:
            return
        try:
            text = combo.get()
        except tk.TclError:
            return
        sid = self._plan_site_display_to_id.get(text)
        p.selected_plan_site_id = sid
        p.selected_plan_site_obj = None
        if sid and sid != PLAN_SITE_CREATE_NEW_ID:
            for r in p.plan_sites_rows or []:
                if isinstance(r, dict) and str(r.get("id")) == str(sid):
                    p.selected_plan_site_obj = r
                    break
        logger.debug("Plan site selected id=%r display=%r", sid, text)
        self.update_create_button()

    def _set_plan_sites_refresh_btn_state(self, state: str) -> None:
        if not self.plan_sites_refresh_btn:
            return
        try:
            self.plan_sites_refresh_btn.configure(state=state)
        except tk.TclError:
            pass

    def start_plan_sites_refresh(self) -> None:
        """Spawn worker for architect/sites refresh; apply on main thread via ``after``.

        Architects get all ``plan`` rows plus **Create New**. Other commanders get only
        orbital ``plan`` rows (``orbital_allowlist.is_orbital_build_type``), no **Create New**.
        """
        p = self.plugin
        frame = getattr(p, "frame", None) if p else None
        if not p or frame is None:
            return
        if self._plan_site_refresh_inflight:
            return

        sa = p.current_system_address
        if sa is None:
            detail = tr("No system context")
            self._show_plan_sites_feedback_dialog(
                title=tr("Plan sites"),
                summary=tr("Cannot refresh plan sites."),
                detail=detail,
            )
            p.plan_sites_transient_message = tr("Plan sites error")
            self.refresh_plan_site_row_state()
            return

        self._plan_site_refresh_inflight = True
        self._set_plan_sites_refresh_btn_state(tk.DISABLED)

        base = PluginConfig.get_api_base().rstrip("/")
        ua = PluginConfig.get_user_agent()
        headers = {"User-Agent": ua, "Accept": "application/json"}
        snap = (getattr(p, "cmdr_name", None) or "").strip()

        def work() -> Dict[str, Any]:
            return fetch_plan_sites_worker(
                base=base,
                system_address=int(sa),
                cmdr_name=snap,
                headers=headers,
            )

        def finish(res: Dict[str, Any]) -> None:
            self._plan_site_refresh_inflight = False
            self._set_plan_sites_refresh_btn_state(tk.NORMAL)
            self.apply_plan_sites_worker_result(res)

        def run() -> None:
            try:
                res = work()
            except HTTP_CLIENT_ERRORS as e:
                logger.exception("Plan sites refresh worker failed")
                res = {
                    "ok": False,
                    "reason": "http_error",
                    "detail": str(e),
                    "system_address": int(sa),
                    "rows": [],
                }
            if p.schedule_after(0, lambda r=res: finish(r)) is None:
                self._plan_site_refresh_inflight = False
                self._set_plan_sites_refresh_btn_state(tk.NORMAL)

        Thread(target=run, daemon=True).start()

    def apply_plan_sites_worker_result(self, res: Dict[str, Any]) -> None:
        """Main thread: apply refresh worker output to plugin state and refresh combobox."""
        p = self.plugin
        if not p:
            return
        response_system = res.get("system_address")
        current_system = getattr(p, "current_system_address", None)
        if response_system is not None and current_system is not None:
            try:
                if int(response_system) != int(current_system):
                    logger.debug(
                        "Plan sites refresh ignored: requested_system=%s current_system=%s",
                        response_system,
                        current_system,
                    )
                    self.refresh_plan_site_row_state()
                    self.refresh_overlay_build_row_state()
                    return
            except (TypeError, ValueError):
                pass
        if res.get("ok"):
            p.plan_sites_transient_message = None
            p.plan_sites_system_key = res.get("system_address")
            p.plan_sites_rows = list(res.get("rows") or [])
            p.overlay_build_site_rows = list(res.get("build_rows") or [])
            p.overlay_sites_system_key = res.get("system_address")
            p.overlay_sites_transient_message = None
            p.plan_sites_allow_create_new = bool(res.get("allow_create_new", True))
            p.selected_plan_site_id = None
            p.selected_plan_site_obj = None
            issue_log.info(
                "Plan sites refresh OK: system=%s plan_rows=%d build_rows=%d architect_create_new=%s",
                res.get("system_address"),
                len(p.plan_sites_rows),
                len(p.overlay_build_site_rows),
                p.plan_sites_allow_create_new,
            )
        elif res.get("reason") == "no_cmdr":
            detail = tr("No commander (wait for LoadGame)")
            self._show_plan_sites_feedback_dialog(
                title=tr("Plan sites"),
                summary=tr("Commander not ready."),
                detail=detail,
            )
            p.plan_sites_transient_message = tr("Plan sites error")
        elif res.get("reason") == "http_error":
            detail_src = (res.get("detail") or "").strip()
            full_detail = tr("Plan sites refresh failed") + (f": {detail_src}" if detail_src else "")
            self._show_plan_sites_feedback_dialog(
                title=tr("Plan sites"),
                summary=tr("Could not load plan sites from the API."),
                detail=full_detail,
            )
            p.plan_sites_transient_message = tr("Plan sites error")
        self.refresh_plan_site_row_state()
        self.refresh_overlay_build_row_state()
        self._overlay_row.on_external_refresh_complete()

    def update_status(self, message: str, *, l10n_key: Optional[str] = None):
        """
        Update the UI status label

        :param message: The status message to display
        :param l10n_key: Optional translation key for repainting after language changes
        """
        self._status_l10n_key = l10n_key
        if self.status_label:
            self.status_label['text'] = message
            logger.info(message)

    def _resolve_docked_create_button_plan(self) -> _DockedCreateButtonPlan:
        """Project probe + plan-site row state → a single button plan (no widget writes)."""
        p = self.plugin
        if not p.current_system_address:
            logger.debug("No system_address, fetching from journal for project check")
            p.set_current_system_address(p.get_system_address_from_journal())

        existing_project: Optional[Dict[str, Any]] = None
        if p.current_system_address:
            existing_project = p.check_existing_project(
                p.current_system_address, p.current_market_id
            )
        else:
            logger.warning("Could not get system_address, unable to check for existing project")

        bid = resolve_build_id(existing_project) if isinstance(existing_project, dict) else None
        if existing_project and bid:
            name = existing_project.get("buildName", tr("Unknown"))
            if not isinstance(name, str):
                name = str(name)
            return _DockedCreateButtonPlan(
                _DockedCreateBtnKind.OPEN_BUILD,
                build_id=bid,
                build_display_name=name,
            )

        ca_ok = (
            p.plan_sites_system_key is not None and
            p.current_system_address is not None and
            int(p.plan_sites_system_key) == int(p.current_system_address)
        )
        sel_id = p.selected_plan_site_id
        if not ca_ok:
            return _DockedCreateButtonPlan(_DockedCreateBtnKind.REFRESH_PLAN_SITES)
        if sel_id is None:
            return _DockedCreateButtonPlan(_DockedCreateBtnKind.SELECT_PLAN_SITE)
        if sel_id == PLAN_SITE_CREATE_NEW_ID:
            return _DockedCreateButtonPlan(_DockedCreateBtnKind.SCRATCH_CREATE)
        return _DockedCreateButtonPlan(_DockedCreateBtnKind.LINK_PLAN_SITE)

    def _apply_docked_create_button_plan(self, plan: _DockedCreateButtonPlan) -> None:
        """Apply ``_resolve_docked_create_button_plan`` to the create button and link label."""
        btn = self.create_button
        if btn is None:
            return
        p = self.plugin

        if plan.kind == _DockedCreateBtnKind.OPEN_BUILD:
            logger.info(
                "Found existing project: %s (%s)", plan.build_display_name, plan.build_id
            )
            btn["state"] = tk.NORMAL
            btn["text"] = tr("🌐 Open Build Page")
            btn["command"] = lambda b=plan.build_id: self._open_project_build_url(b)
            if self.project_link_label:
                self.project_link_label["text"] = plan.build_display_name
            p.current_build_id = plan.build_id
            return

        logger.info("No existing project found")
        if self.project_link_label:
            self.project_link_label["text"] = ""
        p.current_build_id = None

        if plan.kind == _DockedCreateBtnKind.REFRESH_PLAN_SITES:
            btn["state"] = tk.DISABLED
            btn["text"] = tr("Refresh plan sites")
            btn["command"] = lambda: None
        elif plan.kind == _DockedCreateBtnKind.SELECT_PLAN_SITE:
            btn["state"] = tk.NORMAL
            btn["text"] = tr("Select plan site first")
            btn["command"] = self._prompt_select_plan_site_first
        elif plan.kind == _DockedCreateBtnKind.SCRATCH_CREATE:
            if p.current_system and not hasattr(p, "_bodies_fetched"):
                logger.debug("Pre-fetching body data for Create dialog")
                if not p.current_system_address:
                    p.set_current_system_address(p.get_system_address_from_journal())
                p._bodies_fetched = True
            btn["state"] = tk.NORMAL
            btn["text"] = tr("🚧Create Build Project")
            if p.frame:
                btn["command"] = lambda: self._open_create_dialog(p.frame.master)
        else:
            btn["state"] = tk.NORMAL
            btn["text"] = tr("🔗 Link Build Site")
            btn["command"] = self._start_link_build_site

    def open_fc_manifest_editor(self) -> None:
        """Open the Fleet Carrier manifest editor popout."""
        try:
            from .fc_manifest_editor import FleetCarrierManifestEditor

            editor = getattr(self.plugin, "fc_manifest_editor", None)
            if editor is None:
                editor = FleetCarrierManifestEditor(self.plugin)
                self.plugin.fc_manifest_editor = editor
            editor.open()
        except (ImportError, OVERLAY_UI_ERRORS) as exc:
            logger.warning("Could not open Fleet Carrier manifest editor: %s", exc, exc_info=True)
            show_themed_report_dialog(
                self.plugin.frame,
                title=tr("Edit Carrier Manifest"),
                summary=tr("Could not open the Fleet Carrier manifest editor."),
                detail=str(exc),
                copy_button_text=tr("Copy Error Msg"),
                ok_button_text=tr("OK"),
            )

    def update_create_button(self):
        """Enable/disable create button based on docking status and existing projects"""
        logger.debug(
            "update_create_button - is_docked: %s, market_id: %s, is_construction_ship: %s",
            self.plugin.is_docked,
            self.plugin.current_market_id,
            self.plugin.is_construction_ship,
        )

        if not self.create_button:
            return

        if self.plan_sites_combo:
            self.refresh_plan_site_row_state()
        if self.overlay_build_combo:
            self.refresh_overlay_build_row_state()

        # Check if we're at a construction ship
        if self.plugin.is_docked and self.plugin.current_market_id and self.plugin.is_construction_ship:
            plan = self._resolve_docked_create_button_plan()
            self._apply_docked_create_button_plan(plan)
        else:
            # Not at construction ship - disable button and restore original command
            logger.debug("Disabling create button (not at construction ship or missing state)")
            self.create_button['text'] = tr("Waiting for Dock")
            self.create_button['state'] = tk.DISABLED

            # Restore original command to open create dialog
            if self.plugin.frame:
                self.create_button['command'] = lambda: self._open_create_dialog(self.plugin.frame.master)

            if self.project_link_label:
                self.project_link_label['text'] = ""
                self.plugin.current_build_id = None

    def _prompt_select_plan_site_first(self) -> None:
        """Placeholder row selected — keep button enabled; click explains what to do next."""
        p = self.plugin
        if p and getattr(p, "plan_sites_allow_create_new", True):
            body = tr("Choose a plan site from the dropdown above, or pick Create New.")
        else:
            body = tr("Choose an orbital plan site from the dropdown above.")
        messagebox.showinfo(tr("Select plan site first"), body)

    def _preflight_active_project_before_create_or_link(self) -> bool:
        """Fresh location GET; if a project exists, refresh the button and block create/link."""
        p = self.plugin
        if not p or p.current_system_address is None or p.current_market_id is None:
            return True
        fresh = p.check_existing_project(
            int(p.current_system_address), int(p.current_market_id), force=True
        )
        bid = resolve_build_id(fresh) if isinstance(fresh, dict) else None
        if fresh and bid:
            self.update_create_button()
            messagebox.showinfo(
                tr("Project exists"),
                tr("A build project is now active at this station. Use Open Build Page."),
            )
            return False
        return True

    def _begin_link_build_site_worker(
        self,
        *,
        p: Any,
        site_obj: Dict[str, Any],
        sa_cache: int,
        depot_fields: Dict[str, Any],
        frame: tk.Widget,
    ) -> None:
        ctx = prepare_link_build_site_context(
            p,
            site_obj=site_obj,
            sa_cache=sa_cache,
            depot_fields=depot_fields,
        )

        def finish(res: Dict[str, Any]) -> None:
            try:
                if show_link_build_site_phase_dialog(res):
                    return
                apply_link_build_site_success(p, res, depot_fields)
                self.refresh_plan_site_row_state()
                self.update_create_button()
            finally:
                self._link_build_inflight = False
                self.update_create_button()

        def run() -> None:
            r = run_link_build_site_worker(ctx)
            if p.schedule_after(0, lambda: finish(r)) is None:
                self._link_build_inflight = False
                p.schedule_after(0, self.update_create_button)

        Thread(target=run, daemon=True).start()

    def _start_link_build_site(self) -> None:
        """Worker thread: GET project by location; if free, PUT link payload; UI updates on main thread."""
        p = self.plugin
        frame = getattr(p, "frame", None)
        if not p or frame is None:
            return

        site_obj = p.selected_plan_site_obj
        validation_error = validate_link_build_site_inputs(
            p,
            site_obj=site_obj,
            mid=p.current_market_id,
            sa_cache=p.plan_sites_system_key,
            sa_cur=p.current_system_address,
        )
        if validation_error:
            messagebox.showwarning(tr("Link Build Site"), validation_error)
            return
        if not self._preflight_active_project_before_create_or_link():
            return

        depot_fields = p.build_depot_project_fields(refresh=True)
        if not depot_fields:
            messagebox.showerror(tr("Link Build Site"), depot_fields_error_message(p))
            return
        if self._link_build_inflight:
            return

        self._link_build_inflight = True
        if self.create_button:
            try:
                self.create_button.configure(state=tk.DISABLED)
            except tk.TclError:
                pass

        self._begin_link_build_site_worker(
            p=p,
            site_obj=site_obj,
            sa_cache=int(p.plan_sites_system_key),
            depot_fields=depot_fields,
            frame=frame,
        )

    def _open_project_build_url(self, build_id: str) -> None:
        """Open ``https://ravencolonial.com/#build={id}`` (used by main button and hyperlink)."""
        bid = (build_id or "").strip()
        if not bid:
            logger.warning("Open build page: empty buildId")
            return
        import webbrowser

        url = f"https://ravencolonial.com/#build={bid}"
        logger.info("Opening project page: %s", url)
        webbrowser.open(url)

    def _open_project_link(self):
        """Open build page using ``plugin.current_build_id`` (HyperlinkLabel / legacy callers)."""
        if self.plugin and self.plugin.current_build_id:
            self._open_project_build_url(str(self.plugin.current_build_id))

    def _open_create_dialog(self, parent):
        """Open the Create Project dialog"""
        if self.plugin:
            if not self._preflight_active_project_before_create_or_link():
                return
            try:
                import create_project_dialog
                create_project_dialog.CreateProjectDialog(parent, self.plugin)
            except (ImportError, OVERLAY_UI_ERRORS, tk.TclError, AttributeError, TypeError, ValueError) as e:
                logger.error("Failed to open create dialog: %s", e, exc_info=True)
                from tkinter import messagebox
                messagebox.showerror(tr("Error"), trf("Failed to open dialog: {detail}", detail=str(e)))

    def _check_and_show_update_notification(self):
        """Check if update is available and show notification if needed"""
        if self.plugin.update_available and not self.plugin.update_dismissed:
            self._show_update_notification()

    def _show_update_notification(self):
        """Display update notification banner with action buttons"""
        if self.update_frame:
            return  # Already showing

        if not self.plugin.frame:
            return

        body = self._body_frame or self.plugin.frame
        # tk.Frame so theme background matches the rest of the plugin strip (see create_plugin_frame).
        self.update_frame = tk.Frame(body, highlightthickness=0, borderwidth=0)
        self.update_frame.pack(side=tk.TOP, anchor=tk.W, padx=4, pady=4, before=self.main_controls_frame)

        # Get version info
        try:
            from ..version_check import CURRENT_VERSION
            current = CURRENT_VERSION()
        except (ImportError, AttributeError, TypeError, ValueError):
            current = "unknown"

        remote = self.plugin.update_info.remote_version or "unknown"
        current_d = _strip_leading_v_for_display(current)
        remote_d = _strip_leading_v_for_display(remote)

        # Info label — theme foreground/background (no hard-coded accent colors)
        info_text = trf(
            "Update Available: v{current} → v{remote}",
            current=current_d,
            remote=remote_d,
        )
        info_label = ttk.Label(
            self.update_frame,
            text=info_text,
            wraplength=360,
            justify=tk.LEFT,
        )
        info_label.pack(side=tk.TOP, anchor=tk.W, padx=2, pady=2)

        button_row = tk.Frame(self.update_frame, highlightthickness=0, borderwidth=0)
        button_row.pack(side=tk.TOP, anchor=tk.W)

        # Buttons
        btn_download = tk.Button(
            button_row,
            text=tr("📥 Go to Download"),
            command=self._open_download_page,
        )
        btn_download.pack(side=tk.LEFT, padx=2, pady=2)

        btn_autoupdate = tk.Button(
            button_row,
            text=tr("⚡ Auto-Update"),
            command=self._trigger_autoupdate,
        )
        btn_autoupdate.pack(side=tk.LEFT, padx=2, pady=2)

        btn_dismiss = tk.Button(
            button_row,
            text=tr("✖ Dismiss"),
            command=self._dismiss_update_notification,
        )
        btn_dismiss.pack(side=tk.LEFT, padx=2, pady=2)

        ttk.Separator(self.update_frame, orient=tk.HORIZONTAL).pack(
            side=tk.TOP, fill=tk.X, pady=(4, 0)
        )

        apply_theme_to_widget_subtree(self.update_frame)

    def _dismiss_update_notification(self):
        """Hide the update notification banner"""
        if self.update_frame:
            self.update_frame.destroy()
            self.update_frame = None
        self.plugin.update_dismissed = True

    def _open_download_page(self):
        """Open the GitHub release page in browser"""
        if self.plugin.update_info:
            self.plugin.update_info.open_download_page()

    def _trigger_autoupdate(self):
        """Manually trigger auto-update in background thread"""
        if not self.plugin.update_info:
            return

        # Disable buttons during update
        if self.update_frame:
            for widget in self.update_frame.winfo_children():
                if isinstance(widget, (tk.Button, ttk.Button)):
                    widget.config(state=tk.DISABLED)

        # Show updating message
        self.update_status(
            tr("Ravencolonial: Updating..."),
            l10n_key="Ravencolonial: Updating...",
        )

        def update_thread():
            """Background thread for update installation"""
            try:
                logger.info("Manual auto-update triggered")
                self.plugin.update_info.run_autoupdate()
                rv = self.plugin.update_info.remote_version
                tail = _strip_leading_v_for_display(rv) if rv else "?"
                logger.info(
                    "Update complete — restart EDMC to use v%s",
                    tail,
                )

                # Update UI
                if self.update_frame:
                    self.plugin.schedule_after(0, self._dismiss_update_notification)
                if self.status_label:
                    self.plugin.schedule_after(
                        0,
                        lambda: self.update_status(
                            tr("Ravencolonial: Update downloaded - Restart EDMC to install"),
                            l10n_key="Ravencolonial: Update downloaded - Restart EDMC to install",
                        ),
                    )

            except (HTTP_CLIENT_ERRORS, UPDATE_PATH_ERRORS) as e:
                logger.error("Manual auto-update failed: %s", e, exc_info=True)
                detail = _short_exception_detail(e)

                def show_failure():
                    plug.show_error(
                        trf(
                            "Ravencolonial: Update failed - {detail}",
                            detail=detail,
                        ) +
                        "\nPlease try manual installation from docs/MANUAL_UPDATE_INSTRUCTIONS.md."
                    )

                    # Re-enable buttons
                    if self.update_frame:
                        for widget in self.update_frame.winfo_children():
                            if isinstance(widget, (tk.Button, ttk.Button)):
                                widget.config(state=tk.NORMAL)

                    if self.status_label:
                        self.update_status(
                            tr("Ravencolonial: Update failed"),
                            l10n_key="Ravencolonial: Update failed",
                        )

                self.plugin.schedule_after(0, show_failure)

        # Start update in background
        Thread(target=update_thread, daemon=True, name="manual-autoupdate").start()
