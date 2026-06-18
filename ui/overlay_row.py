"""Overlay build-project row (Enable Overlay, Always On, refresh, build & carrier pickers)."""

from __future__ import annotations

import logging
import time
import urllib.parse
from threading import Thread
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import requests
import tkinter as tk
from tkinter import ttk

from ..api.client import resolve_build_id, resolve_build_id_from_site
from ..i18n import tr
from ..overlay.availability import overlay_dependency_satisfied
from ..overlay.fc_cargo import OVERLAY_FC_ALL, cargo_from_fc_record, parse_project_linked_fcs
from ..overlay.formatting import resolve_project_needs
from ..plugin_config import PluginConfig
from .edmc_theme import ThemedCheckbox, apply_theme_to_widget_subtree
from .combo_colors import fallback_background, preferred_entry_colors
from .themed_combobox import ThemedCombobox
from .themed_report_dialog import show_themed_alert_dialog, show_themed_report_dialog

if TYPE_CHECKING:
    from .manager import UIManager

logger = logging.getLogger(__name__)

OVERLAY_BUILD_PLACEHOLDER_KEY = "__OVERLAY_PLACEHOLDER__"
OVERLAY_TRACK_ALL_KEY = "__OVERLAY_TRACK_ALL__"
OVERLAY_FC_PLACEHOLDER_KEY = "__OVERLAY_FC_PLACEHOLDER__"
SYSTEM_SEARCH_PLACEHOLDER = "System Name"


def _site_status_key(site: Dict[str, Any]) -> str:
    return "".join(ch for ch in str(site.get("status", "")).strip().lower() if ch.isalnum())


def build_status_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    active_statuses = {"build", "building", "active", "inprogress"}
    return [
        s
        for s in rows
        if isinstance(s, dict) and _site_status_key(s) in active_statuses
    ]


def _parse_sites_payload(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [s for s in data if isinstance(s, dict)]
    if isinstance(data, dict):
        inner = data.get("sites") or data.get("items") or []
        return [s for s in inner if isinstance(s, dict)] if isinstance(inner, list) else []
    return []


def _combined_project_linked_fcs(projects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for project in projects:
        for fc in parse_project_linked_fcs(project):
            try:
                mid = int(fc["marketId"])
            except (KeyError, TypeError, ValueError):
                continue
            if mid in seen:
                continue
            seen.add(mid)
            out.append(dict(fc))
    out.sort(key=lambda x: str(x.get("label", "")).lower())
    return out


class OverlayBuildRowController:
    """Main-tab overlay controls with its own sites refresh (no architect/orbital filter)."""

    def __init__(self, ui: "UIManager") -> None:
        self._ui = ui
        self._row_parent: Optional[tk.Widget] = None
        self.row: Optional[tk.Frame] = None
        self.build_picker_row: Optional[tk.Frame] = None
        self.fc_row: Optional[tk.Frame] = None
        self.overlay_separator: Optional[tk.Frame] = None
        self._details_built: bool = False
        self.enabled_var: Optional[tk.BooleanVar] = None
        self.always_on_var: Optional[tk.BooleanVar] = None
        self.search_var: Optional[tk.BooleanVar] = None
        self.enabled_cb: Optional[ThemedCheckbox] = None
        self.always_on_cb: Optional[ThemedCheckbox] = None
        self.search_cb: Optional[ThemedCheckbox] = None
        self.carrier_var: Optional[tk.BooleanVar] = None
        self.carrier_cb: Optional[ThemedCheckbox] = None
        self.build_label: Optional[ttk.Label] = None
        self.system_search_var: Optional[tk.StringVar] = None
        self.system_search_entry: Optional[tk.Entry] = None
        self._system_search_placeholder_active = True
        self.build_combo_frame: Optional[tk.Frame] = None
        self.combo: Optional[ThemedCombobox] = None
        self.combo_var: Optional[tk.StringVar] = None
        self.fc_combo: Optional[ThemedCombobox] = None
        self.fc_combo_var: Optional[tk.StringVar] = None
        self.refresh_btn: Optional[tk.Button] = None
        self.fc_refresh_btn: Optional[tk.Button] = None
        self._fc_refresh_cooldown_until: float = 0.0
        self._fc_refresh_countdown_job: Optional[str] = None
        self._display_to_build_id: Dict[str, Optional[str]] = {}
        self._fc_label_to_market: Dict[str, str] = {}
        self._refresh_inflight: bool = False

    @property
    def plugin(self) -> Any:
        return self._ui.plugin

    def build_row(self, parent: tk.Widget) -> None:
        self._row_parent = parent
        toggle_row = tk.Frame(parent, highlightthickness=0, borderwidth=0)
        toggle_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 2))
        self.row = toggle_row

        p = self.plugin
        self.enabled_var = tk.BooleanVar(value=self._enabled_in_config())
        overlay_on = bool(self.enabled_var.get())
        p.overlay_ui_enabled = overlay_on
        p.overlay_always_on = bool(overlay_on and self._always_on_in_config())
        p.overlay_carrier_tracking_enabled = bool(
            overlay_on and self._carrier_tracking_in_config()
        )
        p.overlay_fc_selection = self._fc_selection_in_config()
        if overlay_on:
            p.selected_overlay_build_id = self._build_id_in_config() or None
        logger.debug(
            "Overlay row init: enabled=%s always_on=%s carrier=%s saved_build_id=%s current_system=%s",
            overlay_on,
            p.overlay_always_on,
            p.overlay_carrier_tracking_enabled,
            p.selected_overlay_build_id,
            getattr(p, "current_system_address", None),
        )

        self.enabled_cb = ThemedCheckbox(
            toggle_row,
            text=tr("Enable Overlay"),
            variable=self.enabled_var,
            command=self._on_enabled_toggle,
            padx=(5, 4),
        )
        apply_theme_to_widget_subtree(toggle_row)

        self._apply_widget_states()
        self.refresh_checkbox_themes()
        self.refresh_row_state()

    def _ensure_details_built(self) -> bool:
        if self._details_built:
            return True
        parent = self._row_parent
        if parent is None:
            return False

        p = self.plugin
        before = self._ui.plan_sites_row
        self.always_on_var = tk.BooleanVar(value=self._always_on_in_config())
        self.search_var = tk.BooleanVar(value=False)
        self.carrier_var = tk.BooleanVar(value=self._carrier_tracking_in_config())

        build_picker_row = tk.Frame(parent, highlightthickness=0, borderwidth=0)
        build_pack_opts: Dict[str, Any] = {"side": tk.TOP, "fill": tk.X, "pady": (0, 2)}
        if before is not None and before.winfo_manager():
            build_pack_opts["before"] = before
        build_picker_row.pack(**build_pack_opts)
        self.build_picker_row = build_picker_row

        self.always_on_cb = ThemedCheckbox(
            self.row if self.row is not None else parent,
            text=tr("Always On"),
            variable=self.always_on_var,
            command=self._on_always_on_toggle,
            padx=(0, 8),
        )

        self.search_cb = ThemedCheckbox(
            self.row if self.row is not None else parent,
            text=tr("Search"),
            variable=self.search_var,
            command=self._on_search_toggle,
            padx=(0, 8),
        )

        build_lbl = ttk.Label(build_picker_row, text=tr("Select Build Project"))
        build_lbl.pack(side=tk.LEFT, padx=(5, 6))
        self.build_label = build_lbl

        self.system_search_var = tk.StringVar(value=tr(SYSTEM_SEARCH_PLACEHOLDER))
        self.system_search_entry = tk.Entry(
            build_picker_row,
            textvariable=self.system_search_var,
            width=24,
        )
        self.system_search_entry._rc_skip_subtree_theme = True  # type: ignore[attr-defined]
        self.system_search_entry.bind("<FocusIn>", self._on_system_search_focus_in)
        self.system_search_entry.bind("<FocusOut>", self._on_system_search_focus_out)

        combo_frame = tk.Frame(build_picker_row, highlightthickness=0, borderwidth=0)
        combo_frame.pack(side=tk.LEFT)
        self.build_combo_frame = combo_frame
        self.combo_var = tk.StringVar(value="")
        self.combo = ThemedCombobox(combo_frame, textvariable=self.combo_var, state="disabled")
        self.combo.pack(side=tk.LEFT)
        self.combo.bind("<<ComboboxSelected>>", self._on_combo_selected)

        self.refresh_btn = tk.Button(
            build_picker_row,
            text="\u27f3",
            width=3,
            command=self.start_overlay_sites_refresh,
        )
        self.refresh_btn.pack(side=tk.LEFT, padx=(4, 5))
        try:
            self.refresh_btn.configure(cursor="hand2")
        except tk.TclError:
            pass

        fc_row = tk.Frame(parent, highlightthickness=0, borderwidth=0)
        fc_pack_opts: Dict[str, Any] = {"side": tk.TOP, "fill": tk.X, "pady": (0, 4)}
        if before is not None and before.winfo_manager():
            fc_pack_opts["before"] = before
        fc_row.pack(**fc_pack_opts)
        self.fc_row = fc_row

        self.carrier_cb = ThemedCheckbox(
            fc_row,
            text=tr("Enable Carrier Tracking"),
            variable=self.carrier_var,
            command=self._on_carrier_tracking_toggle,
            padx=(5, 4),
        )

        fc_combo_frame = tk.Frame(fc_row, highlightthickness=0, borderwidth=0)
        fc_combo_frame.pack(side=tk.LEFT)
        self.fc_combo_var = tk.StringVar(value="")
        self.fc_combo = ThemedCombobox(fc_combo_frame, textvariable=self.fc_combo_var, state="disabled")
        self.fc_combo.pack(side=tk.LEFT)
        self.fc_combo.bind("<<ComboboxSelected>>", self._on_fc_combo_selected)

        self.fc_refresh_btn = tk.Button(
            fc_row,
            text="\u27f3",
            width=3,
            command=self.start_selected_fc_manifest_refresh,
        )
        self.fc_refresh_btn.pack(side=tk.LEFT, padx=(4, 5))
        try:
            self.fc_refresh_btn.configure(cursor="hand2")
        except tk.TclError:
            pass

        separator = tk.Frame(parent, height=1, highlightthickness=0, borderwidth=0)
        self.overlay_separator = separator
        sep_pack_opts: Dict[str, Any] = {"side": tk.TOP, "fill": tk.X, "padx": 6, "pady": (0, 4)}
        if before is not None and before.winfo_manager():
            sep_pack_opts["before"] = before
        separator.pack(**sep_pack_opts)

        if self.row is not None:
            apply_theme_to_widget_subtree(self.row)
        apply_theme_to_widget_subtree(build_picker_row)
        apply_theme_to_widget_subtree(fc_row)
        self._refresh_separator_color()
        self.refresh_checkbox_themes()
        self._refresh_system_search_entry_theme()
        self._details_built = True
        self.refresh_fc_combo_state()
        self._apply_widget_states()
        return True

    def refresh_checkbox_themes(self) -> None:
        """Re-sync overlay checkboxes after a parent ``apply_theme_to_widget_subtree`` pass."""
        for themed_cb in (self.enabled_cb, self.always_on_cb, self.search_cb, self.carrier_cb):
            if themed_cb is not None:
                themed_cb.refresh_theme()

    def refresh_theme(self) -> None:
        """Repaint row widgets after EDMC changes theme."""
        for row in (self.row, self.build_picker_row, self.fc_row):
            if row is not None:
                apply_theme_to_widget_subtree(row)
        self._refresh_separator_color()
        if self.combo is not None:
            self.combo.apply_theme_styling()
        if self.fc_combo is not None:
            self.fc_combo.apply_theme_styling()
        self._refresh_system_search_entry_theme()
        self.refresh_checkbox_themes()

    def refresh_localized_text(self) -> None:
        """Repaint labels and placeholder rows after EDMC reloads translations."""
        if self.enabled_cb is not None:
            self.enabled_cb.set_text(tr("Enable Overlay"))
        if self.always_on_cb is not None:
            self.always_on_cb.set_text(tr("Always On"))
        if self.search_cb is not None:
            self.search_cb.set_text(tr("Search"))
        if self.carrier_cb is not None:
            self.carrier_cb.set_text(tr("Enable Carrier Tracking"))
        if self.build_label is not None:
            try:
                self.build_label.configure(text=tr("Select Build Project"))
            except tk.TclError:
                pass
        if self.system_search_var is not None and self._system_search_placeholder_active:
            self.system_search_var.set(tr(SYSTEM_SEARCH_PLACEHOLDER))
            self._refresh_system_search_entry_theme()
        self.refresh_row_state()
        self.refresh_fc_combo_state()
        self.refresh_theme()

    def _enabled_in_config(self) -> bool:
        """Overlay is opt-in per EDMC session to keep plugin startup lightweight."""
        return False

    def _always_on_in_config(self) -> bool:
        try:
            from config import config

            return bool(config.get_bool("ravencolonial_overlay_always_on", default=False))
        except Exception:
            return False

    def _carrier_tracking_in_config(self) -> bool:
        try:
            from config import config

            return bool(config.get_bool("ravencolonial_overlay_carrier_tracking", default=False))
        except Exception:
            return False

    def _fc_selection_in_config(self) -> str:
        try:
            from config import config

            return (config.get_str("ravencolonial_overlay_fc_selection") or OVERLAY_FC_ALL).strip() or OVERLAY_FC_ALL
        except Exception:
            return OVERLAY_FC_ALL

    def _build_id_in_config(self) -> str:
        try:
            from config import config

            return (config.get_str("ravencolonial_overlay_build_id") or "").strip()
        except Exception:
            return ""

    def _search_mode_enabled(self) -> bool:
        return bool(self.search_var and self.search_var.get())

    def _system_search_text(self) -> str:
        if self.system_search_var is None or self._system_search_placeholder_active:
            return ""
        return (self.system_search_var.get() or "").strip()

    @staticmethod
    def _system_search_key(system_name: str) -> str:
        return f"name:{' '.join(system_name.split()).casefold()}"

    def _persist_enabled(self, enabled: bool) -> None:
        try:
            from config import config

            config.set("ravencolonial_overlay_enabled", enabled)
        except Exception:  # nosec B110
            pass

    def _persist_always_on(self, always_on: bool) -> None:
        try:
            from config import config

            config.set("ravencolonial_overlay_always_on", always_on)
        except Exception:  # nosec B110
            pass

    def _persist_carrier_tracking(self, enabled: bool) -> None:
        try:
            from config import config

            config.set("ravencolonial_overlay_carrier_tracking", enabled)
        except Exception:  # nosec B110
            pass

    def _persist_fc_selection(self, selection: str) -> None:
        try:
            from config import config

            config.set("ravencolonial_overlay_fc_selection", selection)
        except Exception:  # nosec B110
            pass

    def sync_enabled_from_config(self) -> None:
        p = self.plugin
        overlay_on = self._enabled_in_config()
        p.overlay_ui_enabled = overlay_on
        p.overlay_always_on = bool(overlay_on and self._always_on_in_config())
        p.overlay_carrier_tracking_enabled = bool(
            overlay_on and self._carrier_tracking_in_config()
        )
        p.overlay_fc_selection = self._fc_selection_in_config()
        if self.enabled_var is not None:
            self.enabled_var.set(overlay_on)
        if self.always_on_var is not None:
            self.always_on_var.set(self._always_on_in_config())
        if self.search_var is not None:
            self.search_var.set(False)
        if self.carrier_var is not None:
            self.carrier_var.set(self._carrier_tracking_in_config())
        if overlay_on:
            self._ensure_details_built()
        self._apply_widget_states()
        self.refresh_checkbox_themes()
        if overlay_on:
            self.refresh_row_state()

    def _apply_widget_states(self) -> None:
        overlay_on = bool(self.enabled_var and self.enabled_var.get())
        p = self.plugin
        self._sync_optional_controls_visibility(overlay_on)
        if self.always_on_var is not None:
            p.overlay_always_on = bool(overlay_on and self.always_on_var.get())
        if self.carrier_var is not None:
            p.overlay_carrier_tracking_enabled = bool(
                overlay_on and self.carrier_var.get()
            )
        if self.refresh_btn is not None:
            try:
                refresh_ok = overlay_on and not self._refresh_inflight
                self.refresh_btn.configure(
                    state=tk.NORMAL if refresh_ok else tk.DISABLED
                )
            except tk.TclError:
                pass
        if self.always_on_cb is not None:
            self.always_on_cb.set_interactable(overlay_on)
        if self.search_cb is not None:
            self.search_cb.set_interactable(overlay_on)
        if self.carrier_cb is not None:
            self.carrier_cb.set_interactable(overlay_on)
        self._sync_build_lookup_widgets(overlay_on)

        build_combo_ok = False
        if self.combo is not None:
            if not overlay_on:
                try:
                    self.combo.configure(state="disabled")
                except tk.TclError:
                    pass
            elif build_status_rows(getattr(p, "overlay_build_site_rows", [])):
                try:
                    self.combo.configure(state="readonly")
                    build_combo_ok = True
                except tk.TclError:
                    pass
            else:
                try:
                    self.combo.configure(state="disabled")
                except tk.TclError:
                    pass

        if self.fc_combo is not None:
            carrier_on = bool(overlay_on and p.overlay_carrier_tracking_enabled)
            has_build = bool(p.selected_overlay_build_id)
            if not carrier_on or not overlay_on or not has_build or not build_combo_ok:
                try:
                    self.fc_combo.configure(state="disabled")
                except tk.TclError:
                    pass
            else:
                try:
                    self.fc_combo.configure(state="readonly")
                except tk.TclError:
                    pass

        self._refresh_fc_manifest_button_state()
        self.refresh_checkbox_themes()

    def _sync_optional_controls_visibility(self, overlay_on: bool) -> None:
        """Hide secondary overlay controls unless the overlay itself is enabled."""
        before = self._ui.plan_sites_row
        if self.always_on_cb is not None:
            self._pack_child_if_needed(
                self.always_on_cb.frame,
                visible=overlay_on,
                side=tk.LEFT,
                padx=(0, 8),
            )
        if self.search_cb is not None:
            self._pack_child_if_needed(
                self.search_cb.frame,
                visible=overlay_on,
                side=tk.LEFT,
                padx=(0, 8),
            )
        if self.build_picker_row is not None:
            self._pack_row_if_needed(
                self.build_picker_row,
                visible=overlay_on,
                pady=(0, 2),
                before=before,
            )
        if self.fc_row is not None:
            self._pack_row_if_needed(
                self.fc_row,
                visible=overlay_on,
                pady=(0, 4),
                before=before,
            )
        if self.overlay_separator is not None:
            self._pack_row_if_needed(
                self.overlay_separator,
                visible=overlay_on,
                padx=6,
                pady=(0, 4),
                before=before,
            )

    def _sync_build_lookup_widgets(self, overlay_on: bool) -> None:
        search_on = bool(overlay_on and self._search_mode_enabled())
        if self.build_label is not None:
            self._pack_child_if_needed(
                self.build_label,
                visible=bool(overlay_on and not search_on),
                side=tk.LEFT,
                padx=(5, 6),
                before=self.build_combo_frame,
            )
        if self.system_search_entry is not None:
            self._pack_child_if_needed(
                self.system_search_entry,
                visible=search_on,
                side=tk.LEFT,
                padx=(5, 6),
                before=self.build_combo_frame,
            )
            try:
                self.system_search_entry.configure(state=tk.NORMAL if search_on else tk.DISABLED)
            except tk.TclError:
                pass
            self._refresh_system_search_entry_theme()

    def _on_system_search_focus_in(self, _event: object = None) -> None:
        if not self.system_search_entry or not self.system_search_var:
            return
        if self._system_search_placeholder_active:
            self._system_search_placeholder_active = False
            self.system_search_var.set("")
            self._refresh_system_search_entry_theme()

    def _on_system_search_focus_out(self, _event: object = None) -> None:
        if not self.system_search_entry or not self.system_search_var:
            return
        if not (self.system_search_var.get() or "").strip():
            self._system_search_placeholder_active = True
            self.system_search_var.set(tr(SYSTEM_SEARCH_PLACEHOLDER))
            self._refresh_system_search_entry_theme()

    def _on_search_toggle(self) -> None:
        p = self.plugin
        if self.search_var is None or not p.overlay_ui_enabled:
            return
        p.selected_overlay_build_id = None
        if getattr(p, "build_overlay", None):
            p.build_overlay.remember_project(None)
        self.refresh_row_state()
        p.refresh_build_overlay()

    def _refresh_system_search_entry_theme(self) -> None:
        entry = self.system_search_entry
        if entry is None:
            return
        try:
            from config import config  # type: ignore[import-untyped]

            dark = config.get_int("theme") in (1, 2)
        except Exception:
            dark = False
        try:
            bg = entry.master.cget("bg") if entry.master is not None else ""
            if not bg or str(bg).lower() in ("white", "systembuttonface", "systemwindow"):
                bg = fallback_background(dark=dark)
            bg, fg = preferred_entry_colors(str(bg), dark=dark)
            placeholder_fg = "#8a8a8a" if dark else "#707070"
            entry.configure(
                bg=bg,
                fg=placeholder_fg if self._system_search_placeholder_active else fg,
                insertbackground=fg,
                disabledbackground=bg,
                disabledforeground=placeholder_fg,
                highlightbackground=bg,
                highlightcolor=fg,
            )
        except tk.TclError:
            pass

    @staticmethod
    def _pack_child_if_needed(
        widget: tk.Widget,
        *,
        visible: bool,
        side: str,
        padx: tuple[int, int],
        before: Optional[tk.Widget] = None,
    ) -> None:
        try:
            if visible:
                if not widget.winfo_manager():
                    pack_opts: Dict[str, Any] = {"side": side, "padx": padx}
                    if before is not None and before.winfo_manager():
                        pack_opts["before"] = before
                    widget.pack(**pack_opts)
            elif widget.winfo_manager():
                widget.pack_forget()
        except tk.TclError:
            pass

    @staticmethod
    def _pack_row_if_needed(
        widget: tk.Widget,
        *,
        visible: bool,
        pady: tuple[int, int],
        before: Optional[tk.Widget] = None,
        padx: int = 0,
    ) -> None:
        try:
            if visible:
                if widget.winfo_manager():
                    return
                pack_opts: Dict[str, Any] = {
                    "side": tk.TOP,
                    "fill": tk.X,
                    "pady": pady,
                }
                if padx:
                    pack_opts["padx"] = padx
                if before is not None and before.winfo_manager():
                    pack_opts["before"] = before
                widget.pack(**pack_opts)
            elif widget.winfo_manager():
                widget.pack_forget()
        except tk.TclError:
            pass

    def _refresh_separator_color(self) -> None:
        if self.overlay_separator is None:
            return
        color = "#505050"
        try:
            from theme import theme  # type: ignore[import-untyped]

            cur = getattr(theme, "current", None) or {}
            color = str(cur.get("disabledforeground") or cur.get("highlight") or color)
        except ImportError:
            pass
        try:
            self.overlay_separator.configure(background=color)
        except tk.TclError:
            pass

    def _on_enabled_toggle(self) -> None:
        p = self.plugin
        if self.enabled_var is None:
            return
        enabled = bool(self.enabled_var.get())
        if enabled and not overlay_dependency_satisfied():
            self.enabled_var.set(False)
            self._show_overlay_dependency_alert()
            return
        p.overlay_ui_enabled = enabled
        self._persist_enabled(enabled)
        logger.debug(
            "Overlay enabled toggled: enabled=%s saved_build_id=%s selected_before=%s",
            enabled,
            self._build_id_in_config(),
            getattr(p, "selected_overlay_build_id", None),
        )
        self._apply_widget_states()
        if not enabled:
            p.selected_overlay_build_id = None
            if getattr(p, "build_overlay", None):
                p.build_overlay.remember_project(None)
            p.refresh_build_overlay()
        else:
            self._ensure_details_built()
            p.selected_overlay_build_id = None
            if getattr(p, "build_overlay", None):
                p.build_overlay.remember_project(None)
            self.refresh_row_state()
            p.refresh_build_overlay()

    def _on_always_on_toggle(self) -> None:
        p = self.plugin
        if self.always_on_var is None or not p.overlay_ui_enabled:
            return
        p.overlay_always_on = bool(self.always_on_var.get())
        self._persist_always_on(p.overlay_always_on)
        p.refresh_build_overlay()

    def _on_carrier_tracking_toggle(self) -> None:
        p = self.plugin
        if self.carrier_var is None or not p.overlay_ui_enabled:
            return
        p.overlay_carrier_tracking_enabled = bool(self.carrier_var.get())
        self._persist_carrier_tracking(p.overlay_carrier_tracking_enabled)
        self._apply_widget_states()
        if p.overlay_carrier_tracking_enabled and p.selected_overlay_build_id:
            p.overlay_fc_cargo_by_market = {}
            self.fetch_fc_cargo_async(trigger="manual_tracking_toggle", allow_api_refresh=True)
        else:
            p.overlay_fc_cargo_by_market = {}
            p.refresh_build_overlay()

    def _on_fc_combo_selected(self, _event: object = None) -> None:
        p = self.plugin
        if not self.fc_combo or not p.overlay_carrier_tracking_enabled:
            return
        try:
            text = self.fc_combo.get()
        except tk.TclError:
            return
        sel = self._fc_label_to_market.get(text, OVERLAY_FC_PLACEHOLDER_KEY)
        if sel == OVERLAY_FC_PLACEHOLDER_KEY:
            return
        p.overlay_fc_selection = sel
        self._persist_fc_selection(sel)
        if sel != OVERLAY_FC_ALL and self._selected_fc_manifest_missing(sel):
            self.fetch_fc_cargo_async(trigger="manual_fc_selection", allow_api_refresh=True)
        else:
            self._refresh_fc_manifest_button_state()
            p.refresh_build_overlay()

    def _selected_fc_market_id(self) -> Optional[int]:
        p = self.plugin
        selection = str(getattr(p, "overlay_fc_selection", OVERLAY_FC_ALL) or OVERLAY_FC_ALL)
        if selection == OVERLAY_FC_ALL:
            return None
        try:
            return int(selection)
        except (TypeError, ValueError):
            return None

    def _has_refreshable_fc_selection(self) -> bool:
        p = self.plugin
        linked = getattr(p, "overlay_project_linked_fcs", None) or []
        selection = str(getattr(p, "overlay_fc_selection", OVERLAY_FC_ALL) or OVERLAY_FC_ALL)
        if selection == OVERLAY_FC_ALL:
            return bool(linked)
        return self._selected_fc_market_id() is not None

    def _selected_fc_manifest_missing(self, selection: str) -> bool:
        try:
            mid = int(selection)
        except (TypeError, ValueError):
            return False
        cargo_by_market = getattr(self.plugin, "overlay_fc_cargo_by_market", None) or {}
        return mid not in cargo_by_market and str(mid) not in cargo_by_market

    def _fetch_fc_cargo_after_project_update(self, trigger: str = "overlay_refresh") -> None:
        sel = str(getattr(self.plugin, "overlay_fc_selection", OVERLAY_FC_ALL) or OVERLAY_FC_ALL)
        allow_api_refresh = sel != OVERLAY_FC_ALL and self._selected_fc_manifest_missing(sel)
        self.fetch_fc_cargo_async(trigger=trigger, allow_api_refresh=allow_api_refresh)

    def start_selected_fc_manifest_refresh(self) -> None:
        if not self._has_refreshable_fc_selection():
            self._refresh_fc_manifest_button_state()
            return
        now = time.monotonic()
        if now < getattr(self, "_fc_refresh_cooldown_until", 0.0):
            self._refresh_fc_manifest_button_state()
            return
        self._fc_refresh_cooldown_until = now + 60.0
        self._refresh_fc_manifest_button_state()
        self.fetch_fc_cargo_async(trigger="manual_fc_manifest_refresh", allow_api_refresh=True)

    def _fc_manifest_refresh_available(self) -> bool:
        p = self.plugin
        if not bool(getattr(p, "overlay_ui_enabled", False)):
            return False
        if not bool(getattr(p, "overlay_carrier_tracking_enabled", False)):
            return False
        if not getattr(p, "selected_overlay_build_id", None):
            return False
        if getattr(p, "_overlay_fc_cargo_inflight", False):
            return False
        return self._has_refreshable_fc_selection()

    def _refresh_fc_manifest_button_state(self) -> None:
        btn = self.fc_refresh_btn
        if btn is None:
            return
        now = time.monotonic()
        remaining = max(0, int(getattr(self, "_fc_refresh_cooldown_until", 0.0) - now + 0.999))
        if remaining > 0:
            try:
                btn.configure(text=str(remaining), state=tk.DISABLED, cursor="")
            except tk.TclError:
                return
            self._schedule_fc_manifest_countdown_tick()
            return
        self._fc_refresh_cooldown_until = 0.0
        enabled = self._fc_manifest_refresh_available()
        try:
            btn.configure(
                text="\u27f3",
                state=tk.NORMAL if enabled else tk.DISABLED,
                cursor="hand2" if enabled else "",
            )
        except tk.TclError:
            return

    def _schedule_fc_manifest_countdown_tick(self) -> None:
        if getattr(self, "_fc_refresh_countdown_job", None) is not None:
            return
        frame = getattr(self.plugin, "frame", None)
        if frame is None:
            return

        def tick() -> None:
            self._fc_refresh_countdown_job = None
            self._refresh_fc_manifest_button_state()

        try:
            self._fc_refresh_countdown_job = frame.after(1000, tick)
        except tk.TclError:
            self._fc_refresh_countdown_job = None

    def refresh_fc_combo_state(self) -> None:
        combo = self.fc_combo
        var = self.fc_combo_var
        p = self.plugin
        if not combo or not var:
            return

        self._fc_label_to_market.clear()
        all_label = tr("All")
        self._fc_label_to_market[all_label] = OVERLAY_FC_ALL

        linked = getattr(p, "overlay_project_linked_fcs", None) or []
        labels = [all_label]
        for fc in linked:
            label = str(fc.get("label") or "").strip()
            if not label or label in self._fc_label_to_market:
                continue
            self._fc_label_to_market[label] = str(fc["marketId"])
            labels.append(label)

        placeholder = tr("Select carrier")
        if not p.selected_overlay_build_id:
            combo["values"] = (placeholder,)
            var.set(placeholder)
            self._finish_fc_combo_appearance()
            self._apply_widget_states()
            self._refresh_fc_manifest_button_state()
            return

        combo["values"] = tuple(labels)
        want = str(getattr(p, "overlay_fc_selection", OVERLAY_FC_ALL) or OVERLAY_FC_ALL)
        if want != OVERLAY_FC_ALL and want not in self._fc_label_to_market.values():
            want = OVERLAY_FC_ALL
            p.overlay_fc_selection = OVERLAY_FC_ALL
            self._persist_fc_selection(OVERLAY_FC_ALL)
        display = all_label
        if want != OVERLAY_FC_ALL:
            for lab, mid in self._fc_label_to_market.items():
                if mid == want:
                    display = lab
                    break
        var.set(display)
        self._finish_fc_combo_appearance()
        self._apply_widget_states()
        self._refresh_fc_manifest_button_state()

    def _finish_fc_combo_appearance(self) -> None:
        if self.fc_combo and self.fc_combo_var:
            self.fc_combo.apply_theme_styling()
            self.fc_combo.set_entry_width_for_text(self.fc_combo_var.get() or "")

    def fetch_fc_cargo_async(
        self,
        *,
        trigger: str = "overlay_cache_rebuild",
        allow_api_refresh: bool = False,
    ) -> None:
        p = self.plugin
        frame = getattr(p, "frame", None)
        linked = getattr(p, "overlay_project_linked_fcs", None) or []
        if not frame or not linked:
            p.overlay_fc_cargo_by_market = {}
            p.refresh_build_overlay()
            return
        if getattr(p, "_overlay_fc_cargo_inflight", False):
            return
        p._overlay_fc_cargo_inflight = True
        request_selection = getattr(p, "selected_overlay_build_id", None)
        request_markets = tuple(sorted(int(fc["marketId"]) for fc in linked))

        def work() -> Dict[int, Dict[str, int]]:
            out: Dict[int, Dict[str, int]] = {}
            handler = getattr(p, "fc_handler", None)
            handler_fcs: Dict[Any, Any] = {}
            if handler is not None:
                handler_fcs = getattr(handler, "linked_fcs", None) or {}
            client = getattr(p, "api_client", None)
            for fc in linked:
                mid = int(fc["marketId"])
                fc_selection = str(getattr(p, "overlay_fc_selection", "") or "")
                manual_selected_refresh = (
                    allow_api_refresh
                    and str(trigger or "") == "manual_fc_manifest_refresh"
                    and (fc_selection == OVERLAY_FC_ALL or fc_selection == str(mid))
                )
                cargo: Dict[str, int] = {}
                cached = handler_fcs.get(mid) or handler_fcs.get(str(mid))
                source = "none"
                cached_source = str(cached.get("cargoSource") or "") if isinstance(cached, dict) else ""
                cached_cargo = cached.get("cargo") if isinstance(cached, dict) else None
                selected_specific_missing = (
                    allow_api_refresh
                    and str(getattr(p, "overlay_fc_selection", "") or "") == str(mid)
                    and (
                        not isinstance(cached, dict)
                        or (cached_source == "active_project_linked_fc" and not isinstance(cached_cargo, dict))
                        or (cached_source == "active_project_linked_fc" and not cached_cargo)
                    )
                )
                selected_manifest_seed_only = str(trigger or "") in {
                    "manual_fc_selection",
                    "manual_fc_manifest_refresh",
                    "project_changed",
                    "all_projects_refresh",
                    "project_refresh",
                }
                if allow_api_refresh and handler is not None and client is not None:
                    if manual_selected_refresh:
                        allowed, reason, cooldown = True, "manual_fc_manifest_refresh", 0
                    elif selected_manifest_seed_only and not selected_specific_missing:
                        allowed, reason, cooldown = False, "selected_manifest_seed_only", 0
                    elif selected_specific_missing:
                        attempted = set(getattr(p, "_overlay_fc_manifest_fetch_attempted", set()) or set())
                        if mid in attempted:
                            allowed, reason, cooldown = False, "selected_manifest_missing_already_attempted", 0
                        else:
                            attempted.add(mid)
                            p._overlay_fc_manifest_fetch_attempted = attempted
                            allowed, reason, cooldown = True, "selected_manifest_missing", 0
                    else:
                        try:
                            allowed, reason, cooldown = handler.can_refresh_fc_cargo_from_api(mid, trigger)
                        except Exception as e:
                            allowed, reason, cooldown = False, f"guard_error_{e}", 0
                    if allowed:
                        try:
                            data = client.get_fc(mid)
                            if isinstance(data, dict):
                                cargo = cargo_from_fc_record(data)
                                if hasattr(handler, "replace_fc_cargo_manifest"):
                                    handler.replace_fc_cargo_manifest(
                                        mid,
                                        cargo,
                                        source="raven_colonial_api",
                                        timestamp=(data or {}).get("cargoUpdatedAt")
                                        or (data or {}).get("cargoSnapshotTimestamp"),
                                    )
                                cached = handler_fcs.get(mid) or handler_fcs.get(str(mid)) or data
                                source = "raven_colonial_api"
                            else:
                                logger.debug(
                                    "GET /api/fc/%s returned no FC record for trigger %s",
                                    mid,
                                    trigger,
                                )
                        except Exception as e:
                            logger.debug("GET /api/fc/%s failed for trigger %s: %s", mid, trigger, e)
                    else:
                        logger.debug(
                            "Overlay FC cargo API refresh skipped: market_id=%s trigger=%s reason=%s cooldown=%s",
                            mid,
                            trigger,
                            reason,
                            cooldown,
                        )
                if isinstance(cached, dict):
                    cargo = cargo_from_fc_record(cached)
                    source = str(cached.get("cargoSource") or source or "local_cache")
                logger.debug(
                    "Overlay FC cargo source: build=%s selected_fc=%s market_id=%s source=%s cargo=%s",
                    request_selection,
                    getattr(p, "overlay_fc_selection", None),
                    mid,
                    source,
                    cargo,
                )
                manifest_known = source == "raven_colonial_api"
                if isinstance(cached, dict):
                    known_source = str(cached.get("cargoSource") or "")
                    manifest_known = manifest_known or (
                        known_source not in {"", "active_project_linked_fc"} or bool(cargo)
                    )
                if manifest_known:
                    out[mid] = cargo
            return out

        def finish(cargo_map: Dict[int, Dict[str, int]]) -> None:
            p._overlay_fc_cargo_inflight = False
            current_linked = getattr(p, "overlay_project_linked_fcs", None) or []
            current_markets = tuple(sorted(int(fc["marketId"]) for fc in current_linked))
            if (
                request_selection != getattr(p, "selected_overlay_build_id", None)
                or request_markets != current_markets
            ):
                logger.debug(
                    "Overlay FC cargo fetch ignored: requested=%s/%s selected_now=%s/%s",
                    request_selection,
                    request_markets,
                    getattr(p, "selected_overlay_build_id", None),
                    current_markets,
                )
                if p.overlay_carrier_tracking_enabled and current_linked:
                    self._fetch_fc_cargo_after_project_update(trigger="project_changed")
                return
            p.overlay_fc_cargo_by_market = dict(cargo_map)
            self.refresh_fc_combo_state()
            p.refresh_build_overlay()

        def run() -> None:
            try:
                result = work()
            except Exception as e:
                logger.exception("Overlay FC cargo fetch failed: %s", e)
                result = {}
            try:
                frame.after(0, lambda r=result: finish(r))
            except tk.TclError:
                p._overlay_fc_cargo_inflight = False

        Thread(target=run, daemon=True).start()

    def fetch_all_projects_async(self) -> None:
        p = self.plugin
        frame = getattr(p, "frame", None)
        build_ids = self._active_build_ids_from_rows()
        if frame and p.overlay_ui_enabled and not build_ids:
            self._show_feedback_dialog(
                title=tr("Build projects"),
                summary=tr("Cannot refresh build projects."),
                detail=tr("Could not resolve build IDs for active projects."),
            )
            if getattr(p, "build_overlay", None):
                p.build_overlay.remember_project(None)
            p.refresh_build_overlay()
            return
        if not frame or not build_ids or p.overlay_project_fetch_inflight:
            logger.debug(
                "Overlay all-project fetch skipped: has_frame=%s build_ids=%d inflight=%s selected=%s",
                bool(frame),
                len(build_ids),
                getattr(p, "overlay_project_fetch_inflight", None),
                getattr(p, "selected_overlay_build_id", None),
            )
            return
        p.overlay_project_fetch_inflight = True
        logger.debug("Overlay all-project fetch start: build_ids=%d", len(build_ids))

        def work() -> Dict[str, Any]:
            cache = dict(getattr(p, "overlay_project_cache_by_build_id", None) or {})
            projects: List[Dict[str, Any]] = []
            failed: List[str] = []
            for bid in build_ids:
                cached = cache.get(bid)
                project = p.get_project_by_build_id(bid)
                if not isinstance(project, dict) and isinstance(cached, dict):
                    project = cached
                if isinstance(project, dict):
                    resolved = resolve_build_id(project) or bid
                    cache[str(resolved)] = dict(project)
                    projects.append(dict(project))
                else:
                    failed.append(bid)
            return {
                "build_ids": list(build_ids),
                "projects": projects,
                "cache": cache,
                "failed": failed,
            }

        def finish(res: Dict[str, Any]) -> None:
            p.overlay_project_fetch_inflight = False
            if getattr(p, "selected_overlay_build_id", None) != OVERLAY_TRACK_ALL_KEY:
                logger.debug(
                    "Overlay all-project fetch ignored: selected_now=%s",
                    getattr(p, "selected_overlay_build_id", None),
                )
                return
            projects = [x for x in res.get("projects", []) if isinstance(x, dict)]
            p.overlay_project_cache_by_build_id = dict(res.get("cache") or {})
            if not projects:
                if getattr(p, "build_overlay", None):
                    p.build_overlay.remember_project(None)
                else:
                    p.overlay_project_cache = None
                    p.overlay_project_linked_fcs = []
                    p.overlay_fc_cargo_by_market = {}
            elif getattr(p, "build_overlay", None):
                p.build_overlay.remember_all_projects(projects)
            else:
                p.overlay_project_cache = None
                p.overlay_project_linked_fcs = _combined_project_linked_fcs(projects)
            logger.debug(
                "Overlay all-project fetch finish: requested=%d loaded=%d failed=%d",
                len(res.get("build_ids") or []),
                len(projects),
                len(res.get("failed") or []),
            )
            self.refresh_fc_combo_state()
            if p.overlay_carrier_tracking_enabled and projects:
                self._fetch_fc_cargo_after_project_update(trigger="all_projects_refresh")
            else:
                p.refresh_build_overlay()

        def run() -> None:
            try:
                res = work()
            except Exception as e:
                logger.exception("Overlay all-project fetch failed: %s", e)
                res = {
                    "build_ids": list(build_ids),
                    "projects": [],
                    "cache": getattr(p, "overlay_project_cache_by_build_id", None) or {},
                    "failed": list(build_ids),
                }
            try:
                frame.after(0, lambda r=res: finish(r))
            except tk.TclError:
                p.overlay_project_fetch_inflight = False

        Thread(target=run, daemon=True).start()

    def on_external_refresh_complete(self) -> None:
        """After plan-site or overlay sites refresh — reload project + carrier list."""
        p = self.plugin
        bid = getattr(p, "selected_overlay_build_id", None)
        if bid == OVERLAY_TRACK_ALL_KEY and p.overlay_ui_enabled:
            self.fetch_all_projects_async()
        elif bid and p.overlay_ui_enabled:
            self.fetch_project_async(str(bid))

    def _show_overlay_dependency_alert(self) -> None:
        parent = getattr(self.plugin, "frame", None)
        if parent is None:
            return
        show_themed_alert_dialog(
            parent,
            title=tr("Enable Overlay"),
            message=tr("Check plugin settings for dependency."),
            ok_button_text=tr("OK"),
        )

    def _show_feedback_dialog(self, *, title: str, summary: str, detail: str) -> None:
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

    def start_overlay_sites_refresh(self) -> None:
        p = self.plugin
        frame = getattr(p, "frame", None)
        if not p or frame is None or self._refresh_inflight:
            return

        search_enabled = self._search_mode_enabled()
        search_name = self._system_search_text() if search_enabled else ""
        if search_enabled and not search_name:
            self._show_feedback_dialog(
                title=tr("Build projects"),
                summary=tr("Cannot refresh build projects."),
                detail=tr("Enter a system name."),
            )
            self.refresh_row_state()
            return

        if search_name:
            lookup_value: object = " ".join(search_name.split())
            lookup_key: object = self._system_search_key(str(lookup_value))
            lookup_system_address: Optional[int] = None
        else:
            sa = p.current_system_address or p.get_system_address_from_journal()
            if sa is not None and p.current_system_address is None:
                p.set_current_system_address(sa)
            if sa is None:
                self._show_feedback_dialog(
                    title=tr("Build projects"),
                    summary=tr("Cannot refresh build projects."),
                    detail=tr("No system context"),
                )
                self.refresh_row_state()
                return
            lookup_value = int(sa)
            lookup_key = int(sa)
            lookup_system_address = int(sa)

        self._refresh_inflight = True
        self._apply_widget_states()
        base = PluginConfig.get_api_base().rstrip("/")
        fallback_base = PluginConfig.DEFAULT_API_BASE.rstrip("/")
        headers = {"User-Agent": PluginConfig.get_user_agent(), "Accept": "application/json"}
        seg = urllib.parse.quote(str(lookup_value), safe="")

        def work() -> Dict[str, Any]:
            result: Dict[str, Any] = {
                "ok": False,
                "reason": None,
                "system_key": lookup_key,
                "system_address": lookup_system_address,
                "build_rows": [],
            }
            bases = [base]
            if fallback_base and fallback_base.lower() != base.lower():
                bases.append(fallback_base)
            try:
                last_error = None
                for api_base in bases:
                    try:
                        url = f"{api_base}/api/v2/system/{seg}/sites"
                        sr = requests.get(url, headers=headers, timeout=15)
                        sr.raise_for_status()
                        sites = _parse_sites_payload(sr.json())
                        result["raw_rows_count"] = len(sites)
                        result["build_rows"] = build_status_rows(sites)
                        result["api_base"] = api_base
                        result["ok"] = True
                        break
                    except Exception as e:
                        last_error = e
                        if api_base == bases[-1]:
                            raise
                        logger.debug(
                            "Overlay sites refresh retrying default API base after %s failed: %s",
                            api_base,
                            e,
                        )
                if not result["ok"] and last_error is not None:
                    raise last_error
            except Exception as e:
                result["reason"] = "http_error"
                result["detail"] = str(e)
            return result

        def finish(res: Dict[str, Any]) -> None:
            self._refresh_inflight = False
            self._apply_widget_states()
            self.apply_refresh_result(res)

        def run() -> None:
            try:
                res = work()
            except Exception as e:
                logger.exception("Overlay sites refresh failed: %s", e)
                res = {
                    "ok": False,
                    "reason": "http_error",
                    "detail": str(e),
                    "system_key": lookup_key,
                    "system_address": lookup_system_address,
                    "build_rows": [],
                }
            try:
                frame.after(0, lambda r=res: finish(r))
            except tk.TclError:
                self._refresh_inflight = False
                self._apply_widget_states()

        Thread(target=run, daemon=True).start()

    def apply_refresh_result(self, res: Dict[str, Any]) -> None:
        p = self.plugin
        response_system = res.get("system_address")
        current_system = getattr(p, "current_system_address", None)
        if response_system is not None and current_system is not None:
            try:
                if int(response_system) != int(current_system):
                    logger.debug(
                        "Overlay sites refresh ignored: requested_system=%s current_system=%s",
                        response_system,
                        current_system,
                    )
                    self.refresh_row_state()
                    self.on_external_refresh_complete()
                    return
            except (TypeError, ValueError):
                pass
        if res.get("ok"):
            p.overlay_sites_transient_message = None
            p.overlay_sites_system_key = res.get("system_key", res.get("system_address"))
            p.overlay_build_site_rows = list(res.get("build_rows") or [])
            logger.debug(
                "Overlay sites refresh OK: system_key=%s api_base=%s raw_rows=%s build_rows=%d",
                p.overlay_sites_system_key,
                res.get("api_base"),
                res.get("raw_rows_count"),
                len(p.overlay_build_site_rows),
            )
        elif res.get("reason") == "http_error":
            detail_src = (res.get("detail") or "").strip()
            logger.warning(
                "Overlay sites refresh failed: %s",
                detail_src or tr("Could not load build projects from the API."),
            )
            if res.get("system_key") is not None:
                p.overlay_sites_system_key = res.get("system_key")
            elif current_system is not None:
                p.overlay_sites_system_key = current_system
            p.overlay_sites_transient_message = None
        self.refresh_row_state()
        self.on_external_refresh_complete()

    def _finish_combo_appearance(self) -> None:
        if self.combo and self.combo_var:
            self.combo.apply_theme_styling()
            self.combo.set_entry_width_for_text(self.combo_var.get() or "")

    def refresh_row_state(self) -> None:
        combo = self.combo
        var = self.combo_var
        p = self.plugin
        if p.overlay_ui_enabled:
            self._ensure_details_built()
            combo = self.combo
            var = self.combo_var
        if not combo or not var:
            return

        self._display_to_build_id.clear()
        placeholder = tr("Select Build Project")
        self._display_to_build_id[placeholder] = OVERLAY_BUILD_PLACEHOLDER_KEY

        def _set(values: List[str], display: str, state: str) -> None:
            combo["values"] = tuple(values)
            var.set(display)
            try:
                combo.configure(state=state)
            except tk.TclError:
                pass

        if not p.overlay_ui_enabled:
            _set([placeholder], placeholder, "disabled")
            self._finish_combo_appearance()
            self.refresh_fc_combo_state()
            self._apply_widget_states()
            return

        rows = build_status_rows(getattr(p, "overlay_build_site_rows", []))

        msg = getattr(p, "overlay_sites_transient_message", None)
        if msg and not rows:
            p.selected_overlay_build_id = None
            _set([str(msg)], str(msg), "disabled")
            self._finish_combo_appearance()
            self.refresh_fc_combo_state()
            self._apply_widget_states()
            return

        if not rows:
            if getattr(p, "overlay_sites_system_key", None) is not None:
                p.selected_overlay_build_id = None
                nb = tr("No Build Projects")
                _set([nb], nb, "disabled")
                self._finish_combo_appearance()
                self.refresh_fc_combo_state()
                self._apply_widget_states()
                return
            _set([tr("Please Refresh")], tr("Please Refresh"), "disabled")
            self._finish_combo_appearance()
            self.refresh_fc_combo_state()
            self._apply_widget_states()
            return

        track_all_label = tr("Track All")
        self._display_to_build_id[track_all_label] = OVERLAY_TRACK_ALL_KEY
        labels = [placeholder, track_all_label]
        for site in rows:
            name = str(site.get("name") or site.get("buildName") or "").strip()
            bt = str(site.get("buildType") or "").strip()
            label = f"{name} | {bt}" if name or bt else tr("(unnamed site)")
            lookup_system_address = p.current_system_address if not self._search_mode_enabled() else None
            bid = resolve_build_id_from_site(
                site,
                system_address=lookup_system_address,
                get_project_at_location=p.get_project,
            )
            if label in self._display_to_build_id:
                label = f"{label}  ({bid or site.get('id')})"
            self._display_to_build_id[label] = bid
            labels.append(label)

        _set(labels, placeholder, "readonly")
        self._restore_selection(placeholder)
        self._finish_combo_appearance()
        self._apply_widget_states()
        self.refresh_fc_combo_state()

    def _restore_selection(self, placeholder: str) -> None:
        p = self.plugin
        if not self.combo or not self.combo_var:
            return
        want = p.selected_overlay_build_id
        labels = list(self.combo["values"]) if self.combo["values"] else []
        if want:
            for lab, bid in self._display_to_build_id.items():
                if bid == want and lab in labels:
                    self.combo_var.set(lab)
                    return
        self.combo_var.set(placeholder)
        p.selected_overlay_build_id = None

    def _on_combo_selected(self, _event: object = None) -> None:
        p = self.plugin
        if not self.combo or not p.overlay_ui_enabled:
            return
        try:
            text = self.combo.get()
        except tk.TclError:
            return
        key = self._display_to_build_id.get(text)
        if key in (None, OVERLAY_BUILD_PLACEHOLDER_KEY):
            p.selected_overlay_build_id = None
            if getattr(p, "build_overlay", None):
                p.build_overlay.remember_project(None)
            self.refresh_fc_combo_state()
            p.refresh_build_overlay()
            return
        if not key:
            return
        p.selected_overlay_build_id = str(key).strip()
        self._persist_build_selection(p.selected_overlay_build_id)
        if p.selected_overlay_build_id == OVERLAY_TRACK_ALL_KEY:
            self.fetch_all_projects_async()
        else:
            self.fetch_project_async(p.selected_overlay_build_id)

    def _active_build_ids_from_rows(self) -> List[str]:
        p = self.plugin
        out: List[str] = []
        seen: set[str] = set()
        lookup_system_address = p.current_system_address if not self._search_mode_enabled() else None
        for site in build_status_rows(getattr(p, "overlay_build_site_rows", [])):
            bid = resolve_build_id_from_site(
                site,
                system_address=lookup_system_address,
                get_project_at_location=p.get_project,
            )
            if not bid:
                continue
            bid_s = str(bid).strip()
            if bid_s and bid_s not in seen:
                seen.add(bid_s)
                out.append(bid_s)
        return out

    def _persist_build_selection(self, selection: str) -> None:
        try:
            from config import config

            config.set("ravencolonial_overlay_build_id", selection)
        except Exception:  # nosec B110
            pass

    def fetch_project_async(self, build_id: str) -> None:
        p = self.plugin
        frame = getattr(p, "frame", None)
        if not frame or not build_id or p.overlay_project_fetch_inflight:
            logger.debug(
                "Overlay project fetch skipped: has_frame=%s build_id=%s inflight=%s selected=%s",
                bool(frame),
                build_id,
                getattr(p, "overlay_project_fetch_inflight", None),
                getattr(p, "selected_overlay_build_id", None),
            )
            return
        p.overlay_project_fetch_inflight = True
        logger.debug("Overlay project fetch start: build_id=%s", build_id)

        def work() -> Dict[str, Any]:
            return {"build_id": build_id, "project": p.get_project_by_build_id(build_id)}

        def finish(res: Dict[str, Any]) -> None:
            p.overlay_project_fetch_inflight = False
            if res.get("build_id") != getattr(p, "selected_overlay_build_id", None):
                logger.debug(
                    "Overlay project fetch ignored: requested=%s selected_now=%s",
                    res.get("build_id"),
                    getattr(p, "selected_overlay_build_id", None),
                )
                return
            proj = res.get("project")
            needs = resolve_project_needs(proj) if isinstance(proj, dict) else {}
            logger.debug(
                "Overlay project fetch finish: requested=%s found=%s project_build_id=%s needs_count=%d needs_total=%d linked_fcs=%d",
                res.get("build_id"),
                isinstance(proj, dict),
                resolve_build_id(proj) if isinstance(proj, dict) else None,
                len(needs),
                sum(int(v) for v in needs.values()),
                len(parse_project_linked_fcs(proj)) if isinstance(proj, dict) else 0,
            )
            if getattr(p, "build_overlay", None):
                p.build_overlay.remember_project(proj if isinstance(proj, dict) else None)
            elif isinstance(proj, dict):
                p.overlay_project_cache = dict(proj)
                p.overlay_project_linked_fcs = parse_project_linked_fcs(proj)
            else:
                p.overlay_project_cache = None
                p.overlay_project_linked_fcs = []
                p.overlay_fc_cargo_by_market = {}
            if isinstance(proj, dict):
                bid = resolve_build_id(proj) or str(res.get("build_id") or "")
                if bid:
                    cache = dict(getattr(p, "overlay_project_cache_by_build_id", None) or {})
                    cache[str(bid)] = dict(proj)
                    p.overlay_project_cache_by_build_id = cache
            self.refresh_fc_combo_state()
            if p.overlay_carrier_tracking_enabled and isinstance(proj, dict):
                self._fetch_fc_cargo_after_project_update(trigger="project_refresh")
            else:
                p.refresh_build_overlay()

        def run() -> None:
            try:
                res = work()
            except Exception as e:
                logger.exception("Overlay project fetch failed: %s", e)
                res = {"build_id": build_id, "project": None}
            try:
                frame.after(0, lambda r=res: finish(r))
            except tk.TclError:
                p.overlay_project_fetch_inflight = False

        Thread(target=run, daemon=True).start()
