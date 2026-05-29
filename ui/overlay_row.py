"""Overlay build-project row (Enable Overlay, Always On, refresh, build & carrier pickers)."""

from __future__ import annotations

import logging
import urllib.parse
from threading import Thread
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import requests
import tkinter as tk
from tkinter import ttk

from ..api.client import resolve_build_id_from_site
from ..i18n import tr
from ..overlay.availability import overlay_dependency_satisfied
from ..overlay.fc_cargo import OVERLAY_FC_ALL, cargo_from_fc_record, parse_project_linked_fcs
from ..plugin_config import PluginConfig
from .edmc_theme import ThemedCheckbox, apply_theme_to_widget_subtree
from .themed_combobox import ThemedCombobox
from .themed_report_dialog import show_themed_alert_dialog, show_themed_report_dialog

if TYPE_CHECKING:
    from .manager import UIManager

logger = logging.getLogger(__name__)

OVERLAY_BUILD_PLACEHOLDER_KEY = "__OVERLAY_PLACEHOLDER__"
OVERLAY_FC_PLACEHOLDER_KEY = "__OVERLAY_FC_PLACEHOLDER__"


def build_status_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        s
        for s in rows
        if isinstance(s, dict) and str(s.get("status", "")).lower() == "build"
    ]


def _parse_sites_payload(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [s for s in data if isinstance(s, dict)]
    if isinstance(data, dict):
        inner = data.get("sites") or data.get("items") or []
        return [s for s in inner if isinstance(s, dict)] if isinstance(inner, list) else []
    return []


class OverlayBuildRowController:
    """Main-tab overlay controls with its own sites refresh (no architect/orbital filter)."""

    def __init__(self, ui: "UIManager") -> None:
        self._ui = ui
        self.row: Optional[tk.Frame] = None
        self.build_picker_row: Optional[tk.Frame] = None
        self.fc_row: Optional[tk.Frame] = None
        self.enabled_var: Optional[tk.BooleanVar] = None
        self.always_on_var: Optional[tk.BooleanVar] = None
        self.enabled_cb: Optional[ThemedCheckbox] = None
        self.always_on_cb: Optional[ThemedCheckbox] = None
        self.carrier_var: Optional[tk.BooleanVar] = None
        self.carrier_cb: Optional[ThemedCheckbox] = None
        self.combo: Optional[ThemedCombobox] = None
        self.combo_var: Optional[tk.StringVar] = None
        self.fc_combo: Optional[ThemedCombobox] = None
        self.fc_combo_var: Optional[tk.StringVar] = None
        self.refresh_btn: Optional[tk.Button] = None
        self._display_to_build_id: Dict[str, Optional[str]] = {}
        self._fc_label_to_market: Dict[str, str] = {}
        self._refresh_inflight: bool = False

    @property
    def plugin(self) -> Any:
        return self._ui.plugin

    def build_row(self, parent: tk.Widget) -> None:
        toggle_row = tk.Frame(parent, highlightthickness=0, borderwidth=0)
        toggle_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 2))
        self.row = toggle_row

        build_picker_row = tk.Frame(parent, highlightthickness=0, borderwidth=0)
        build_picker_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 2))
        self.build_picker_row = build_picker_row

        p = self.plugin
        self.enabled_var = tk.BooleanVar(value=self._enabled_in_config())
        self.always_on_var = tk.BooleanVar(value=self._always_on_in_config())
        self.carrier_var = tk.BooleanVar(value=self._carrier_tracking_in_config())
        overlay_on = bool(self.enabled_var.get())
        p.overlay_ui_enabled = overlay_on
        p.overlay_always_on = bool(overlay_on and self.always_on_var.get())
        p.overlay_carrier_tracking_enabled = bool(
            overlay_on and self.carrier_var.get()
        )
        p.overlay_fc_selection = self._fc_selection_in_config()

        self.enabled_cb = ThemedCheckbox(
            toggle_row,
            text=tr("Enable Overlay"),
            variable=self.enabled_var,
            command=self._on_enabled_toggle,
            padx=(5, 4),
        )

        self.always_on_cb = ThemedCheckbox(
            toggle_row,
            text=tr("Always On"),
            variable=self.always_on_var,
            command=self._on_always_on_toggle,
            padx=(0, 8),
        )

        build_lbl = ttk.Label(build_picker_row, text=tr("Select Build Project"))
        build_lbl.pack(side=tk.LEFT, padx=(5, 6))

        combo_frame = tk.Frame(build_picker_row, highlightthickness=0, borderwidth=0)
        combo_frame.pack(side=tk.LEFT)
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
        fc_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
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

        apply_theme_to_widget_subtree(toggle_row)
        apply_theme_to_widget_subtree(build_picker_row)
        apply_theme_to_widget_subtree(fc_row)
        self.refresh_checkbox_themes()
        self.refresh_fc_combo_state()
        self._apply_widget_states()

    def refresh_checkbox_themes(self) -> None:
        """Re-sync overlay checkboxes after a parent ``apply_theme_to_widget_subtree`` pass."""
        for themed_cb in (self.enabled_cb, self.always_on_cb, self.carrier_cb):
            if themed_cb is not None:
                themed_cb.refresh_theme()

    def _enabled_in_config(self) -> bool:
        try:
            from config import config

            return bool(config.get_bool("ravencolonial_overlay_enabled", default=False))
        except Exception:
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

    def _persist_enabled(self, enabled: bool) -> None:
        try:
            from config import config

            config.set("ravencolonial_overlay_enabled", enabled)
        except Exception:
            pass

    def _persist_always_on(self, always_on: bool) -> None:
        try:
            from config import config

            config.set("ravencolonial_overlay_always_on", always_on)
        except Exception:
            pass

    def _persist_carrier_tracking(self, enabled: bool) -> None:
        try:
            from config import config

            config.set("ravencolonial_overlay_carrier_tracking", enabled)
        except Exception:
            pass

    def _persist_fc_selection(self, selection: str) -> None:
        try:
            from config import config

            config.set("ravencolonial_overlay_fc_selection", selection)
        except Exception:
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
        if self.carrier_var is not None:
            self.carrier_var.set(self._carrier_tracking_in_config())
        self._apply_widget_states()
        self.refresh_checkbox_themes()

    def _apply_widget_states(self) -> None:
        overlay_on = bool(self.enabled_var and self.enabled_var.get())
        p = self.plugin
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
        if self.carrier_cb is not None:
            self.carrier_cb.set_interactable(overlay_on)

        build_combo_ok = False
        if self.combo is not None:
            if not overlay_on:
                try:
                    self.combo.configure(state="disabled")
                except tk.TclError:
                    pass
            else:
                cur = p.current_system_address
                key = getattr(p, "overlay_sites_system_key", None)
                try:
                    if key is None or cur is None or int(cur) != int(key):
                        self.combo.configure(state="disabled")
                    else:
                        self.combo.configure(state="readonly")
                        build_combo_ok = True
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

        self.refresh_checkbox_themes()

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
        self._apply_widget_states()
        if not enabled:
            p.selected_overlay_build_id = None
            if getattr(p, "build_overlay", None):
                p.build_overlay.remember_project(None)
            p.refresh_build_overlay()
        else:
            self.refresh_row_state()
            if p.selected_overlay_build_id:
                self.fetch_project_async(p.selected_overlay_build_id)
            else:
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
            self.fetch_fc_cargo_async()
        else:
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
        p.refresh_build_overlay()

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

    def _finish_fc_combo_appearance(self) -> None:
        if self.fc_combo and self.fc_combo_var:
            self.fc_combo.apply_theme_styling()
            self.fc_combo.set_entry_width_for_text(self.fc_combo_var.get() or "")

    def fetch_fc_cargo_async(self) -> None:
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

        def work() -> Dict[int, Dict[str, int]]:
            out: Dict[int, Dict[str, int]] = {}
            handler = getattr(p, "fc_handler", None)
            handler_fcs: Dict[Any, Any] = {}
            if handler is not None:
                handler_fcs = getattr(handler, "linked_fcs", None) or {}
            client = getattr(p, "api_client", None)
            for fc in linked:
                mid = int(fc["marketId"])
                cargo: Dict[str, int] = {}
                cached = handler_fcs.get(mid) or handler_fcs.get(str(mid))
                if isinstance(cached, dict):
                    cargo = cargo_from_fc_record(cached)
                if not cargo and client is not None:
                    try:
                        data = client.get_fc(mid)
                        cargo = cargo_from_fc_record(data)
                    except Exception as e:
                        logger.debug("GET /api/fc/%s failed: %s", mid, e)
                out[mid] = cargo
            return out

        def finish(cargo_map: Dict[int, Dict[str, int]]) -> None:
            p._overlay_fc_cargo_inflight = False
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

    def on_external_refresh_complete(self) -> None:
        """After plan-site or overlay sites refresh — reload project + carrier list."""
        p = self.plugin
        bid = getattr(p, "selected_overlay_build_id", None)
        if bid and p.overlay_ui_enabled:
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

        sa = p.current_system_address or p.get_system_address_from_journal()
        if sa is not None and p.current_system_address is None:
            p.current_system_address = sa
        if sa is None:
            self._show_feedback_dialog(
                title=tr("Build projects"),
                summary=tr("Cannot refresh build projects."),
                detail=tr("No system context"),
            )
            p.overlay_sites_transient_message = tr("Build projects error")
            self.refresh_row_state()
            return

        self._refresh_inflight = True
        self._apply_widget_states()
        base = PluginConfig.get_api_base().rstrip("/")
        headers = {"User-Agent": PluginConfig.get_user_agent(), "Accept": "application/json"}
        seg = urllib.parse.quote(str(sa), safe="")

        def work() -> Dict[str, Any]:
            result: Dict[str, Any] = {
                "ok": False,
                "reason": None,
                "system_address": int(sa),
                "build_rows": [],
            }
            try:
                url = f"{base}/api/v2/system/{seg}/sites"
                sr = requests.get(url, headers=headers, timeout=15)
                sr.raise_for_status()
                result["build_rows"] = build_status_rows(_parse_sites_payload(sr.json()))
                result["ok"] = True
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
                    "system_address": int(sa),
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
        if res.get("ok"):
            p.overlay_sites_transient_message = None
            p.overlay_sites_system_key = res.get("system_address")
            p.overlay_build_site_rows = list(res.get("build_rows") or [])
        elif res.get("reason") == "http_error":
            detail_src = (res.get("detail") or "").strip()
            self._show_feedback_dialog(
                title=tr("Build projects"),
                summary=tr("Could not load build projects from the API."),
                detail=tr("Build projects refresh failed")
                + (f": {detail_src}" if detail_src else ""),
            )
            p.overlay_sites_transient_message = tr("Build projects error")
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

        msg = getattr(p, "overlay_sites_transient_message", None)
        if msg:
            p.selected_overlay_build_id = None
            _set([str(msg)], str(msg), "disabled")
            self._finish_combo_appearance()
            self.refresh_fc_combo_state()
            self._apply_widget_states()
            return

        cur = p.current_system_address
        key = getattr(p, "overlay_sites_system_key", None)
        if key is None or cur is None or int(cur) != int(key):
            p.selected_overlay_build_id = None
            _set([tr("Please Refresh")], tr("Please Refresh"), "disabled")
            self._finish_combo_appearance()
            self.refresh_fc_combo_state()
            self._apply_widget_states()
            return

        rows = build_status_rows(p.overlay_build_site_rows)
        if not rows:
            p.selected_overlay_build_id = None
            nb = tr("No Build Projects")
            _set([nb], nb, "disabled")
            self._finish_combo_appearance()
            self.refresh_fc_combo_state()
            self._apply_widget_states()
            return

        labels = [placeholder]
        for site in rows:
            name = str(site.get("name") or site.get("buildName") or "").strip()
            bt = str(site.get("buildType") or "").strip()
            label = f"{name} | {bt}" if name or bt else tr("(unnamed site)")
            bid = resolve_build_id_from_site(
                site,
                system_address=p.current_system_address,
                get_project_at_location=p.get_project,
            )
            if label in self._display_to_build_id:
                label = f"{label}  ({bid or site.get('id')})"
            self._display_to_build_id[label] = bid
            labels.append(label)

        _set(labels, placeholder, "readonly")
        try:
            from config import config

            saved = (config.get_str("ravencolonial_overlay_build_id") or "").strip()
            if saved and not p.selected_overlay_build_id:
                for lab, bid in self._display_to_build_id.items():
                    if bid == saved and lab in labels:
                        p.selected_overlay_build_id = saved
                        break
        except Exception:
            pass
        self._restore_selection(placeholder)
        self._finish_combo_appearance()
        self._apply_widget_states()
        if p.overlay_ui_enabled and p.selected_overlay_build_id and not p.overlay_project_cache:
            self.fetch_project_async(p.selected_overlay_build_id)
        else:
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
        try:
            from config import config

            config.set("ravencolonial_overlay_build_id", p.selected_overlay_build_id)
        except Exception:
            pass
        self.fetch_project_async(p.selected_overlay_build_id)

    def fetch_project_async(self, build_id: str) -> None:
        p = self.plugin
        frame = getattr(p, "frame", None)
        if not frame or not build_id or p.overlay_project_fetch_inflight:
            return
        p.overlay_project_fetch_inflight = True

        def work() -> Dict[str, Any]:
            return {"build_id": build_id, "project": p.get_project_by_build_id(build_id)}

        def finish(res: Dict[str, Any]) -> None:
            p.overlay_project_fetch_inflight = False
            if res.get("build_id") != getattr(p, "selected_overlay_build_id", None):
                return
            proj = res.get("project")
            if getattr(p, "build_overlay", None):
                p.build_overlay.remember_project(proj if isinstance(proj, dict) else None)
            elif isinstance(proj, dict):
                p.overlay_project_linked_fcs = parse_project_linked_fcs(proj)
            else:
                p.overlay_project_linked_fcs = []
            self.refresh_fc_combo_state()
            if p.overlay_carrier_tracking_enabled and isinstance(proj, dict):
                self.fetch_fc_cargo_async()
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
