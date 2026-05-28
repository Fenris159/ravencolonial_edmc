"""Overlay build-project row (Enable Overlay, Always On, refresh, build picker)."""

from __future__ import annotations

import logging
import urllib.parse
from threading import Thread
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import requests
import tkinter as tk

from ..api.client import resolve_build_id_from_site
from ..i18n import tr
from ..plugin_config import PluginConfig
from .edmc_theme import apply_theme_to_widget_subtree
from .themed_combobox import ThemedCombobox
from .themed_report_dialog import show_themed_report_dialog

if TYPE_CHECKING:
    from .manager import UIManager

logger = logging.getLogger(__name__)

OVERLAY_BUILD_PLACEHOLDER_KEY = "__OVERLAY_PLACEHOLDER__"


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
        self.enabled_var: Optional[tk.BooleanVar] = None
        self.always_on_var: Optional[tk.BooleanVar] = None
        self.always_on_cb: Optional[tk.Checkbutton] = None
        self.combo: Optional[ThemedCombobox] = None
        self.combo_var: Optional[tk.StringVar] = None
        self.refresh_btn: Optional[tk.Button] = None
        self._display_to_build_id: Dict[str, Optional[str]] = {}
        self._refresh_inflight: bool = False

    @property
    def plugin(self) -> Any:
        return self._ui.plugin

    def build_row(self, parent: tk.Widget) -> None:
        row = tk.Frame(parent, highlightthickness=0, borderwidth=0)
        row.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        self.row = row

        self.enabled_var = tk.BooleanVar(value=self._enabled_in_config())
        self.always_on_var = tk.BooleanVar(value=self._always_on_in_config())
        self.plugin.overlay_ui_enabled = bool(self.enabled_var.get())
        self.plugin.overlay_always_on = bool(self.always_on_var.get())

        tk.Checkbutton(
            row,
            text=tr("Enable Overlay"),
            variable=self.enabled_var,
            command=self._on_enabled_toggle,
        ).pack(side=tk.LEFT, padx=(5, 4))

        self.always_on_cb = tk.Checkbutton(
            row,
            text=tr("Always On"),
            variable=self.always_on_var,
            command=self._on_always_on_toggle,
        )
        self.always_on_cb.pack(side=tk.LEFT, padx=(0, 8))

        combo_frame = tk.Frame(row, highlightthickness=0, borderwidth=0)
        combo_frame.pack(side=tk.LEFT)
        self.combo_var = tk.StringVar(value="")
        self.combo = ThemedCombobox(combo_frame, textvariable=self.combo_var, state="disabled")
        self.combo.pack(side=tk.LEFT)
        self.combo.bind("<<ComboboxSelected>>", self._on_combo_selected)

        self.refresh_btn = tk.Button(
            row,
            text="\u27f3",
            width=3,
            command=self.start_overlay_sites_refresh,
        )
        self.refresh_btn.pack(side=tk.LEFT, padx=(4, 5))
        try:
            self.refresh_btn.configure(cursor="hand2")
        except tk.TclError:
            pass

        apply_theme_to_widget_subtree(row)
        self._apply_widget_states()

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

    def sync_enabled_from_config(self) -> None:
        self.plugin.overlay_ui_enabled = self._enabled_in_config()
        self.plugin.overlay_always_on = self._always_on_in_config()
        if self.enabled_var is not None:
            self.enabled_var.set(self.plugin.overlay_ui_enabled)
        if self.always_on_var is not None:
            self.always_on_var.set(self.plugin.overlay_always_on)

    def _apply_widget_states(self) -> None:
        overlay_on = bool(self.enabled_var and self.enabled_var.get())
        p = self.plugin
        if self.always_on_var is not None:
            p.overlay_always_on = bool(overlay_on and self.always_on_var.get())
        if self.refresh_btn is not None:
            try:
                self.refresh_btn.configure(
                    state=tk.DISABLED if self._refresh_inflight else tk.NORMAL
                )
            except tk.TclError:
                pass
        if self.always_on_cb is not None:
            try:
                self.always_on_cb.configure(
                    state=tk.NORMAL if overlay_on else tk.DISABLED
                )
            except tk.TclError:
                pass
        if self.combo is None:
            return
        if not overlay_on:
            try:
                self.combo.configure(state="disabled")
            except tk.TclError:
                pass
            return
        cur = p.current_system_address
        key = getattr(p, "overlay_sites_system_key", None)
        try:
            if key is None or cur is None or int(cur) != int(key):
                self.combo.configure(state="disabled")
            else:
                self.combo.configure(state="readonly")
        except tk.TclError:
            pass

    def _on_enabled_toggle(self) -> None:
        p = self.plugin
        if self.enabled_var is None:
            return
        enabled = bool(self.enabled_var.get())
        p.overlay_ui_enabled = enabled
        self._persist_enabled(enabled)
        if not enabled and self.always_on_var is not None:
            self.always_on_var.set(False)
            p.overlay_always_on = False
            self._persist_always_on(False)
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
            if self.always_on_var is not None:
                self.always_on_var.set(False)
            return
        p.overlay_always_on = bool(self.always_on_var.get())
        self._persist_always_on(p.overlay_always_on)
        p.refresh_build_overlay()

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
            self._apply_widget_states()
            return

        msg = getattr(p, "overlay_sites_transient_message", None)
        if msg:
            p.selected_overlay_build_id = None
            _set([str(msg)], str(msg), "disabled")
            self._finish_combo_appearance()
            self._apply_widget_states()
            return

        cur = p.current_system_address
        key = getattr(p, "overlay_sites_system_key", None)
        if key is None or cur is None or int(cur) != int(key):
            p.selected_overlay_build_id = None
            _set([tr("Please Refresh")], tr("Please Refresh"), "disabled")
            self._finish_combo_appearance()
            self._apply_widget_states()
            return

        rows = build_status_rows(p.overlay_build_site_rows)
        if not rows:
            p.selected_overlay_build_id = None
            nb = tr("No Build Projects")
            _set([nb], nb, "disabled")
            self._finish_combo_appearance()
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
            if getattr(p, "build_overlay", None):
                proj = res.get("project")
                p.build_overlay.remember_project(proj if isinstance(proj, dict) else None)
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
