"""
UI Manager for Ravencolonial EDMC Plugin

Handles UI state management and updates.
"""

import logging
import os
import urllib.parse
import tkinter as tk
from dataclasses import dataclass
from enum import Enum, auto
from tkinter import ttk, messagebox
from threading import Thread
from typing import Any, Dict, List, Optional, Union, cast

import plug
import requests
from config import config

from ..api.client import (
    active_project_from_system_location_json,
    completed_project_hint_from_system_location_json,
    parse_system_architect_response,
    plan_site_body_num,
    plan_site_put_body_fields,
    prepare_put_project_body,
    resolve_build_id,
)
from ..orbital_allowlist import is_orbital_build_type
from ..station_names import normalize_dock_station_name
from ..i18n import tr, trf
from ..plugin_config import PluginConfig
from .edmc_theme import apply_theme_to_widget_subtree, plugin_header_font, reapply_plugin_header_font
from .panel_collapse import PanelCollapseToggle
from .themed_combobox import ThemedCombobox
from .themed_report_dialog import show_themed_report_dialog
from .overlay_row import OverlayBuildRowController, build_status_rows
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


def _short_exception_detail(exc: BaseException, limit: int = 480) -> str:
    """Avoid huge ``str(exc)`` strings in dialogs that can widen EDMC's window."""
    s = str(exc).strip()
    if not s:
        return type(exc).__name__
    s = " ".join(s.split())
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "\u2026"


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
        except Exception:
            return True

    @staticmethod
    def _save_panel_expanded(expanded: bool) -> None:
        try:
            config.set("ravencolonial_panel_expanded", bool(expanded))
        except Exception as exc:
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

    def refresh_overlay_build_row_state(self) -> None:
        self._overlay_row.refresh_row_state()

    def refresh_localized_text(self) -> None:
        """Repaint plugin-owned text after EDMC changes language in Settings."""
        frame = getattr(self.plugin, "frame", None)
        if frame is None:
            return
        try:
            if not frame.winfo_exists():
                return
        except tk.TclError:
            return

        if self.header_label is not None:
            try:
                self.header_label.configure(text=tr("RavenColonialWeb"))
            except tk.TclError:
                pass
        if self.plan_sites_label is not None:
            try:
                self.plan_sites_label.configure(text=tr("Select Plan Site"))
            except tk.TclError:
                pass

        self._overlay_row.refresh_localized_text()
        self.refresh_plan_site_row_state()
        self.update_create_button()

        if self.status_label is not None:
            try:
                if self._status_l10n_key:
                    self.status_label.configure(text=tr(self._status_l10n_key))
            except tk.TclError:
                pass

        if self.update_frame is not None:
            try:
                self.update_frame.destroy()
            except tk.TclError:
                pass
            self.update_frame = None
            self._check_and_show_update_notification()

        self.refresh_theme()

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

        def _set_combo(values: List[str], display: str, state: str) -> None:
            combo["values"] = tuple(values)
            var.set(display)
            try:
                combo.configure(state=state)
            except tk.TclError:
                pass

        msg = getattr(p, "plan_sites_transient_message", None)
        if msg:
            p.selected_plan_site_id = None
            p.selected_plan_site_obj = None
            m = str(msg)
            _set_combo([m], m, "disabled")
            self._finish_plan_site_combo_appearance()
            return

        cache_matches_current_system = False
        if key is not None and cur is not None:
            try:
                cache_matches_current_system = int(cur) == int(key)
            except (TypeError, ValueError):
                cache_matches_current_system = False
        if not cache_matches_current_system:
            if key is not None or rows or getattr(p, "selected_plan_site_id", None):
                logger.debug(
                    "Clearing stale plan-site cache: cache_system=%s current_system=%s rows=%d",
                    key,
                    cur,
                    len(rows),
                )
                p.clear_plan_sites_cache()
            _set_combo([tr("Please Refresh")], tr("Please Refresh"), "disabled")
            self._finish_plan_site_combo_appearance()
            return

        placeholder = tr("— choose site —")
        create_new_lbl = tr("Create New")
        allow_cn = getattr(p, "plan_sites_allow_create_new", True)

        if not rows:
            build_n = len(getattr(p, "overlay_build_site_rows", None) or [])
            if allow_cn:
                labels_single = [placeholder, create_new_lbl]
                self._plan_site_display_to_id[placeholder] = None
                self._plan_site_display_to_id[create_new_lbl] = PLAN_SITE_CREATE_NEW_ID
                _set_combo(labels_single, placeholder, "readonly")
                self._restore_plan_site_combo_selection(p, rows, placeholder, create_new_lbl)
                issue_log.info(
                    "Plan sites: no plan rows in system %s (%d build site(s)); showing Create New",
                    key,
                    build_n,
                )
            else:
                no_orb = tr("No Orbitals")
                p.selected_plan_site_id = None
                p.selected_plan_site_obj = None
                _set_combo([no_orb], no_orb, "disabled")
                issue_log.info(
                    "Plan sites: no orbital plan rows for non-architect in system %s "
                    "(%d build site(s))",
                    key,
                    build_n,
                )
            self._finish_plan_site_combo_appearance()
            return

        labels: List[str] = [placeholder]
        self._plan_site_display_to_id[placeholder] = None
        if allow_cn:
            labels.append(create_new_lbl)
            self._plan_site_display_to_id[create_new_lbl] = PLAN_SITE_CREATE_NEW_ID
        for site in rows:
            name = str(site.get("name") or "").strip()
            bt = str(site.get("buildType") or "").strip()
            label = f"{name} | {bt}" if name or bt else tr("(unnamed site)")
            sid = site.get("id")
            if label in self._plan_site_display_to_id:
                label = f"{label}  ({sid})"
            self._plan_site_display_to_id[label] = str(sid) if sid is not None else None
            labels.append(label)

        _set_combo(labels, placeholder, "readonly")
        self._restore_plan_site_combo_selection(p, rows, placeholder, create_new_lbl)
        issue_log.info(
            "Plan sites: %d plan row(s) in combobox for system %s (create_new=%s)",
            len(rows),
            key,
            allow_cn,
        )

        self._finish_plan_site_combo_appearance()

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

    def start_plan_sites_refresh(self) -> None:
        """Spawn worker: ``GET .../architect`` (compare cmdr) then ``GET .../sites``; apply on main thread via ``after``.

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
        if self.plan_sites_refresh_btn:
            try:
                self.plan_sites_refresh_btn.configure(state=tk.DISABLED)
            except tk.TclError:
                pass

        base = PluginConfig.get_api_base().rstrip("/")
        ua = PluginConfig.get_user_agent()
        headers = {"User-Agent": ua, "Accept": "application/json"}
        seg = urllib.parse.quote(str(sa), safe="")
        snap = (getattr(p, "cmdr_name", None) or getattr(p, "cmdr_snapshot", None) or "").strip()

        def work() -> Dict[str, Any]:
            result: Dict[str, Any] = {
                "ok": False,
                "reason": None,
                "system_address": int(sa),
                "rows": [],
            }
            try:
                if not snap or not str(snap).strip():
                    result["reason"] = "no_cmdr"
                    return result

                arch_url = f"{base}/api/v2/system/{seg}/architect"
                ar = requests.get(arch_url, headers=headers, timeout=12)
                ar.raise_for_status()
                try:
                    arch_raw = ar.json()
                except ValueError:
                    arch_raw = (ar.text or "").strip()
                arch_name = parse_system_architect_response(arch_raw)
                is_architect = bool(
                    arch_name
                    and str(arch_name).strip().lower() == str(snap).strip().lower()
                )
                logger.debug(
                    "Plan sites architect gate: api=%r cmdr=%r match=%s plan_rows_pending",
                    arch_name,
                    snap,
                    is_architect,
                )

                sites_url = f"{base}/api/v2/system/{seg}/sites"
                sr = requests.get(sites_url, headers=headers, timeout=15)
                sr.raise_for_status()
                data = sr.json()
                if isinstance(data, list):
                    sites = data
                elif isinstance(data, dict):
                    inner = data.get("sites") or data.get("items") or []
                    sites = inner if isinstance(inner, list) else []
                else:
                    sites = []
                plan_rows = [
                    s
                    for s in sites
                    if isinstance(s, dict) and str(s.get("status", "")).lower() == "plan"
                ]
                build_rows = build_status_rows(sites)
                result["build_rows"] = build_rows
                if is_architect:
                    result["rows"] = plan_rows
                    result["allow_create_new"] = True
                else:
                    result["rows"] = [
                        s for s in plan_rows if is_orbital_build_type(s.get("buildType"))
                    ]
                    result["allow_create_new"] = False
                logger.debug(
                    "Plan sites refresh: %d plan, %d build, showing %d plan (architect=%s)",
                    len(plan_rows),
                    len(build_rows),
                    len(result["rows"]),
                    is_architect,
                )
                result["ok"] = True
                return result
            except requests.RequestException as e:
                result["reason"] = "http_error"
                result["detail"] = str(e)
                return result
            except Exception as e:
                result["reason"] = "http_error"
                result["detail"] = str(e)
                return result

        def finish(res: Dict[str, Any]) -> None:
            self._plan_site_refresh_inflight = False
            if self.plan_sites_refresh_btn:
                try:
                    self.plan_sites_refresh_btn.configure(state=tk.NORMAL)
                except tk.TclError:
                    pass
            self.apply_plan_sites_worker_result(res)

        def run() -> None:
            try:
                res = work()
            except Exception as e:
                logger.exception("Plan sites refresh worker failed")
                res = {
                    "ok": False,
                    "reason": "http_error",
                    "detail": str(e),
                    "system_address": int(sa),
                    "rows": [],
                }
            try:
                frame.after(0, lambda r=res: finish(r))
            except tk.TclError:
                self._plan_site_refresh_inflight = False
                if self.plan_sites_refresh_btn:
                    try:
                        self.plan_sites_refresh_btn.configure(state=tk.NORMAL)
                    except tk.TclError:
                        pass

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
            p.plan_sites_system_key is not None
            and p.current_system_address is not None
            and int(p.plan_sites_system_key) == int(p.current_system_address)
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

    def update_create_button(self):
        """Enable/disable create button based on docking status and existing projects"""
        logger.debug(f"update_create_button - is_docked: {self.plugin.is_docked}, market_id: {self.plugin.current_market_id}, is_construction_ship: {self.plugin.is_construction_ship}")
        
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

    def _start_link_build_site(self) -> None:
        """Worker thread: GET project by location; if free, PUT link payload; UI updates on main thread."""
        p = self.plugin
        frame = getattr(p, "frame", None)
        if not p or frame is None:
            return

        site_obj = p.selected_plan_site_obj
        mid = p.current_market_id
        sa_cache = p.plan_sites_system_key
        sa_cur = p.current_system_address

        if not site_obj or mid is None:
            messagebox.showwarning(tr("Link Build Site"), tr("Missing site selection or dock MarketID."))
            return
        if sa_cache is None or sa_cur is None or int(sa_cache) != int(sa_cur):
            messagebox.showwarning(tr("Link Build Site"), tr("Plan sites cache does not match current system — refresh."))
            return

        site_id = site_obj.get("id")
        plan_name = str(site_obj.get("name") or "").strip()
        dock_name = normalize_dock_station_name(getattr(p, "current_station", None))
        build_name = dock_name or plan_name
        build_type = str(site_obj.get("buildType") or "").strip()
        if not site_id or not build_type:
            messagebox.showerror(tr("Link Build Site"), tr("Selected site is missing id or buildType."))
            return
        if not build_name:
            messagebox.showerror(
                tr("Link Build Site"),
                tr("Could not determine a build name from the dock station or selected plan site."),
            )
            return
        if dock_name:
            logger.debug(
                "Link Build Site buildName from dock station %r -> %r (plan row was %r)",
                p.current_station,
                build_name,
                plan_name or None,
            )
        else:
            logger.debug(
                "Link Build Site buildName from plan row %r (no dock station name)",
                build_name,
            )

        arch_name = (p.cmdr_name or getattr(p, "cmdr_snapshot", None) or "").strip()
        if not arch_name:
            messagebox.showwarning(
                tr("Link Build Site"),
                tr("No commander name — wait for LoadGame or restart EDMC with a journal."),
            )
            return

        if not self._preflight_active_project_before_create_or_link():
            return

        depot_fields = p.build_depot_project_fields(refresh=True)
        if not depot_fields:
            if not p.construction_depot_data:
                messagebox.showerror(
                    tr("Link Build Site"),
                    tr(
                        "No ColonisationConstructionDepot data yet. Wait a few seconds after docking, then try again; "
                        "if this persists, undock and dock again at the construction site so the journal can update."
                    ),
                )
            else:
                messagebox.showerror(
                    tr("Link Build Site"),
                    tr(
                        "Could not read any required commodities from the depot snapshot. "
                        "Wait for the next depot update, or undock and dock again at the construction site, then retry."
                    ),
                )
            return

        if self._link_build_inflight:
            return
        self._link_build_inflight = True
        if self.create_button:
            try:
                self.create_button.configure(state=tk.DISABLED)
            except tk.TclError:
                pass

        # Site rows include bodyNum; resolve bodyName from /bodies (same as create dialog).
        system_bodies = p.get_system_bodies(int(sa_cache))
        cached_body_fields = plan_site_put_body_fields(site_obj, system_bodies)
        if cached_body_fields:
            logger.info(
                "Link Build Site body fields from plan row: bodyNum=%s bodyName=%r",
                cached_body_fields.get("bodyNum"),
                cached_body_fields.get("bodyName"),
            )
        elif plan_site_body_num(site_obj) is None:
            logger.debug("Link Build Site: selected plan row has no bodyNum")

        def work() -> Dict[str, Any]:
            # Standalone HTTP (do not use shared api_client Session from a worker thread).
            out: Dict[str, Any] = {"phase": "error", "detail": ""}
            base = PluginConfig.get_api_base().rstrip("/")
            ua = PluginConfig.get_user_agent()
            headers = {"User-Agent": ua, "Accept": "application/json", "Content-Type": "application/json"}
            try:
                # Guard against stale local cache: re-check selected site status live.
                sites_url = f"{base}/api/v2/system/{int(sa_cache)}/sites"
                rs = requests.get(sites_url, headers={"User-Agent": ua, "Accept": "application/json"}, timeout=15)
                if rs.ok:
                    try:
                        sites_data = rs.json()
                    except ValueError:
                        sites_data = []
                    if isinstance(sites_data, dict):
                        inner = sites_data.get("sites") or sites_data.get("items") or []
                        sites = inner if isinstance(inner, list) else []
                    elif isinstance(sites_data, list):
                        sites = sites_data
                    else:
                        sites = []
                    live_site_row: Optional[Dict[str, Any]] = None
                    for row in sites:
                        if isinstance(row, dict) and str(row.get("id")) == str(site_id):
                            live_site_row = row
                            live_status = str(row.get("status") or "").strip().lower()
                            if live_status and live_status != "plan":
                                out["phase"] = "site_not_plan"
                                out["detail"] = live_status
                                return out
                            break
                else:
                    live_site_row = None

                site_row_for_body = live_site_row if isinstance(live_site_row, dict) else site_obj
                body_fields = plan_site_put_body_fields(site_row_for_body, system_bodies) or cached_body_fields

                q_url = f"{base}/api/system/{int(sa_cache)}/{int(mid)}"
                rg = requests.get(q_url, headers={"User-Agent": ua, "Accept": "application/json"}, timeout=15)
                if not rg.ok and rg.status_code != 404:
                    out["phase"] = "http_error"
                    out["detail"] = f"GET {q_url}: HTTP {rg.status_code} {(rg.text or '')[:400]}"
                    return out
                try:
                    data = rg.json()
                except ValueError:
                    data = (rg.text or "").strip() or None
                if active_project_from_system_location_json(data) is not None:
                    out["phase"] = "exists"
                    return out
                if rg.status_code == 404 and completed_project_hint_from_system_location_json(data) is not None:
                    out["phase"] = "exists_complete"
                    return out
                put_base: Dict[str, Any] = {
                    "marketId": int(mid),
                    "systemAddress": int(sa_cache),
                    "buildName": build_name,
                    "buildType": build_type,
                    "systemSiteId": site_id,
                    "architectName": arch_name,
                }
                if body_fields:
                    put_base.update(body_fields)
                payload = prepare_put_project_body(put_base, depot_fields)
                pu = f"{base}/api/project"
                rp = requests.put(pu, headers=headers, json=payload, timeout=15)
                if not rp.ok:
                    out["phase"] = "put_failed"
                    out["detail"] = (rp.text or "")[:500]
                    return out
                try:
                    body = rp.json()
                except ValueError:
                    body = {}
                out["phase"] = "ok"
                out["site_id"] = site_id
                out["build_id"] = body.get("buildId") if isinstance(body, dict) else None
                out["project"] = body if isinstance(body, dict) else None
                return out
            except Exception as e:
                out["phase"] = "error"
                out["detail"] = str(e)
                return out

        def finish(res: Dict[str, Any]) -> None:
            try:
                phase = res.get("phase")
                if phase == "exists":
                    messagebox.showinfo(
                        tr("Link Build Site"),
                        tr("A project already exists at this station — link cancelled."),
                    )
                    return
                if phase == "exists_complete":
                    messagebox.showinfo(
                        tr("Link Build Site"),
                        tr("A completed project record already exists at this station — link cancelled."),
                    )
                    return
                if phase == "site_not_plan":
                    messagebox.showinfo(
                        tr("Link Build Site"),
                        trf("Selected site is no longer in plan status ({status}) — link cancelled.", status=res.get("detail") or "?"),
                    )
                    return
                if phase == "put_failed":
                    detail = (res.get("detail") or "").strip()
                    msg = tr("Server rejected create — see EDMC log.")
                    if detail:
                        msg = f"{msg}\n{detail[:400]}"
                    messagebox.showerror(tr("Link Build Site"), msg)
                    return
                if phase == "error":
                    messagebox.showerror(tr("Link Build Site"), res.get("detail") or tr("Unknown error"))
                    return
                sid_mark = res.get("site_id")
                if sid_mark:
                    p.plan_sites_rows = [
                        r
                        for r in p.plan_sites_rows
                        if not (isinstance(r, dict) and str(r.get("id")) == str(sid_mark))
                    ]
                p.selected_plan_site_id = None
                p.selected_plan_site_obj = None
                bid = res.get("build_id")
                if bid:
                    p.current_build_id = bid
                    p.maybe_clear_phantom_commodities(bid, res.get("project"))
                    p.queue_initial_project_supply_update(bid, depot_fields)
                p.invalidate_project_location_cache()
                self.refresh_plan_site_row_state()
                self.update_create_button()
                messagebox.showinfo(
                    tr("Link Build Site"),
                    trf("Linked plan site. buildId={bid}", bid=bid or "?"),
                )
            finally:
                self._link_build_inflight = False
                self.update_create_button()

        def run() -> None:
            r = work()
            try:
                frame.after(0, lambda: finish(r))
            except tk.TclError:
                self._link_build_inflight = False
                try:
                    frame.after(0, self.update_create_button)
                except tk.TclError:
                    pass

        Thread(target=run, daemon=True).start()

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
                dialog = create_project_dialog.CreateProjectDialog(parent, self.plugin)
            except Exception as e:
                logger.error(f"Failed to open create dialog: {e}", exc_info=True)
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
        except Exception:
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
                    self.plugin.frame.after(0, self._dismiss_update_notification)
                if self.status_label:
                    self.plugin.frame.after(
                        0,
                        lambda: self.update_status(
                            tr("Ravencolonial: Update installed - Restart EDMC"),
                            l10n_key="Ravencolonial: Update installed - Restart EDMC",
                        ),
                    )
                
            except Exception as e:
                logger.error(f"Manual auto-update failed: {e}", exc_info=True)
                plug.show_error(
                    trf(
                        "Ravencolonial: Update failed - {detail}",
                        detail=_short_exception_detail(e),
                    )
                    + "\nPlease try manual installation from docs/MANUAL_UPDATE_INSTRUCTIONS.md."
                )
                
                # Re-enable buttons
                if self.update_frame:
                    def re_enable():
                        for widget in self.update_frame.winfo_children():
                            if isinstance(widget, (tk.Button, ttk.Button)):
                                widget.config(state=tk.NORMAL)
                    self.plugin.frame.after(0, re_enable)
                
                if self.status_label:
                    self.plugin.frame.after(
                        0,
                        lambda: self.update_status(
                            tr("Ravencolonial: Update failed"),
                            l10n_key="Ravencolonial: Update failed",
                        ),
                    )
        
        # Start update in background
        Thread(target=update_thread, daemon=True, name="manual-autoupdate").start()
