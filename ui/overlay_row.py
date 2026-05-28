"""Overlay build-project row (Enable Overlay + Select Build Project combobox)."""

from __future__ import annotations

import logging
from threading import Thread
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import tkinter as tk

from ..api.client import resolve_build_id_from_site
from ..i18n import tr
from .edmc_theme import apply_theme_to_widget_subtree
from .themed_combobox import ThemedCombobox

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


class OverlayBuildRowController:
    """Main-tab overlay controls; sites list comes from the plan-sites refresh worker."""

    def __init__(self, ui: "UIManager") -> None:
        self._ui = ui
        self.row: Optional[tk.Frame] = None
        self.enabled_var: Optional[tk.BooleanVar] = None
        self.combo: Optional[ThemedCombobox] = None
        self.combo_var: Optional[tk.StringVar] = None
        self._display_to_build_id: Dict[str, Optional[str]] = {}

    @property
    def plugin(self) -> Any:
        return self._ui.plugin

    def build_row(self, parent: tk.Widget) -> None:
        row = tk.Frame(parent, highlightthickness=0, borderwidth=0)
        row.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        self.row = row

        self.enabled_var = tk.BooleanVar(value=self._enabled_in_config())
        self.plugin.overlay_ui_enabled = bool(self.enabled_var.get())

        tk.Checkbutton(
            row,
            text=tr("Enable Overlay"),
            variable=self.enabled_var,
            command=self._on_enabled_toggle,
        ).pack(side=tk.LEFT, padx=(5, 8))

        combo_frame = tk.Frame(row, highlightthickness=0, borderwidth=0)
        combo_frame.pack(side=tk.LEFT)
        self.combo_var = tk.StringVar(value="")
        self.combo = ThemedCombobox(combo_frame, textvariable=self.combo_var, state="disabled")
        self.combo.pack(side=tk.LEFT)
        self.combo.bind("<<ComboboxSelected>>", self._on_combo_selected)

        apply_theme_to_widget_subtree(row)
        self._apply_widget_states()

    def _enabled_in_config(self) -> bool:
        try:
            from config import config

            return bool(config.get_bool("ravencolonial_overlay_enabled", default=False))
        except Exception:
            return False

    def _persist_enabled(self, enabled: bool) -> None:
        try:
            from config import config

            config.set("ravencolonial_overlay_enabled", enabled)
        except Exception:
            pass

    def sync_enabled_from_config(self) -> None:
        enabled = self._enabled_in_config()
        self.plugin.overlay_ui_enabled = enabled
        if self.enabled_var is not None:
            self.enabled_var.set(enabled)

    def _apply_widget_states(self) -> None:
        if self.combo is None:
            return
        if not self.enabled_var or not self.enabled_var.get():
            try:
                self.combo.configure(state="disabled")
            except tk.TclError:
                pass
            return
        p = self.plugin
        cur = p.current_system_address
        key = p.plan_sites_system_key
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
            return

        cur = p.current_system_address
        key = p.plan_sites_system_key
        msg = getattr(p, "plan_sites_transient_message", None)
        if msg:
            p.selected_overlay_build_id = None
            _set([str(msg)], str(msg), "disabled")
            self._finish_combo_appearance()
            return

        if key is None or cur is None or int(cur) != int(key):
            p.selected_overlay_build_id = None
            _set([tr("Please Refresh")], tr("Please Refresh"), "disabled")
            self._finish_combo_appearance()
            return

        rows = build_status_rows(p.overlay_build_site_rows)
        if not rows:
            p.selected_overlay_build_id = None
            nb = tr("No Build Projects")
            _set([nb], nb, "disabled")
            self._finish_combo_appearance()
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
        self._restore_selection(rows, placeholder)
        self._finish_combo_appearance()
        self._apply_widget_states()
        if p.overlay_ui_enabled and p.selected_overlay_build_id and not p.overlay_project_cache:
            self.fetch_project_async(p.selected_overlay_build_id)

    def _restore_selection(self, rows: List[Dict[str, Any]], placeholder: str) -> None:
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
        if not frame or not build_id:
            return
        if p.overlay_project_fetch_inflight:
            return
        p.overlay_project_fetch_inflight = True

        def work() -> Dict[str, Any]:
            project = p.get_project_by_build_id(build_id)
            return {"build_id": build_id, "project": project}

        def finish(res: Dict[str, Any]) -> None:
            p.overlay_project_fetch_inflight = False
            if res.get("build_id") != getattr(p, "selected_overlay_build_id", None):
                return
            project = res.get("project")
            if getattr(p, "build_overlay", None):
                p.build_overlay.remember_project(project if isinstance(project, dict) else None)
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
