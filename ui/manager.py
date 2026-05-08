"""
UI Manager for Ravencolonial EDMC Plugin

Handles UI state management and updates.
"""

import logging
import urllib.parse
import tkinter as tk
from tkinter import ttk, messagebox
from threading import Thread
from typing import Any, Dict, List, Optional, Union, cast

import plug
import requests

from ..api.client import (
    active_project_from_system_location_json,
    completed_project_hint_from_system_location_json,
)
from ..i18n import tr, trf
from ..plugin_config import PluginConfig
from .edmc_theme import apply_theme_to_widget_subtree

# Plan-site dropdown: synthetic id for "Create New" (scratch create dialog)
PLAN_SITE_CREATE_NEW_ID = "__CREATE_NEW__"


def _parse_architect_name(data: Any) -> Optional[str]:
    """Normalize GET /api/v2/system/.../architect JSON (string or object) to a commander name."""
    if data is None:
        return None
    if isinstance(data, str):
        s = data.strip()
        return s or None
    if isinstance(data, dict):
        for k in ("architect", "name", "cmdr", "commander"):
            v = data.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
        return None
    return None


try:
    from ttkHyperlinkLabel import HyperlinkLabel
except ImportError:  # pragma: no cover - only when running outside EDMC
    HyperlinkLabel = None  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)


class UIManager:
    """Manages UI elements and state for the Ravencolonial plugin"""
    
    def __init__(self, plugin_instance):
        """
        Initialize the UI manager
        
        :param plugin_instance: The main plugin instance
        """
        self.plugin = plugin_instance
        self.status_label: Optional[ttk.Label] = None
        self.create_button: Optional[tk.Button] = None
        self.project_link_label: Optional[Union[ttk.Label, ttk.Widget]] = None
        self.update_frame: Optional[tk.Frame] = None
        self.main_controls_frame: Optional[tk.Frame] = None
        # Plan sites row (v2 /sites + architect gate)
        self.plan_sites_row: Optional[tk.Frame] = None
        self.plan_sites_combo: Optional[ttk.Combobox] = None
        self.plan_sites_refresh_btn: Optional[tk.Button] = None
        self.plan_sites_combo_var: Optional[tk.StringVar] = None
        self._plan_site_display_to_id: Dict[str, Optional[str]] = {}
        self._plan_site_refresh_inflight: bool = False
    
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

        # Main controls frame (contains status and buttons)
        self.main_controls_frame = tk.Frame(frame, highlightthickness=0, borderwidth=0)
        self.main_controls_frame.pack(side=tk.TOP, fill=tk.X)

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
        
        # Status row frame (contains status label)
        status_row = tk.Frame(self.main_controls_frame, highlightthickness=0, borderwidth=0)
        status_row.pack(side=tk.TOP, fill=tk.X)
        
        # Status label
        self.status_label = ttk.Label(status_row, text=tr("Ravencolonial: Ready"))
        self.status_label.pack(side=tk.LEFT, padx=5)
        self.plugin.status_label = self.status_label
        
        # Check for updates after a short delay to allow UI to settle
        frame.after(3000, self._check_and_show_update_notification)

        apply_theme_to_widget_subtree(frame)
        self.refresh_plan_site_row_state()
        return frame

    def _build_plan_sites_row(self, parent: tk.Widget) -> None:
        """Row: label + plan-site combobox + refresh (worker fetches; UI updates on main thread only)."""
        row = tk.Frame(parent, highlightthickness=0, borderwidth=0)
        row.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
        self.plan_sites_row = row

        lbl = ttk.Label(row, text=tr("Select Plan Site"))
        lbl.pack(side=tk.LEFT, padx=(5, 6))

        combo_frame = tk.Frame(row, highlightthickness=0, borderwidth=0)
        combo_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.plan_sites_combo_var = tk.StringVar(value="")
        self.plan_sites_combo = ttk.Combobox(
            combo_frame,
            textvariable=self.plan_sites_combo_var,
            state="disabled",
            width=36,
        )
        self.plan_sites_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
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
        rows = p.plan_sites_rows

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
            _set_combo([str(msg)], str(msg), "disabled")
            return

        if getattr(p, "plan_sites_architect_denied", False):
            p.selected_plan_site_id = None
            p.selected_plan_site_obj = None
            _set_combo([tr("Not Architect")], tr("Not Architect"), "disabled")
            return

        if key is None or cur is None or int(cur) != int(key):
            p.selected_plan_site_id = None
            p.selected_plan_site_obj = None
            _set_combo([tr("Please Refresh")], tr("Please Refresh"), "disabled")
            return

        placeholder = tr("— choose site —")
        create_new_lbl = tr("Create New")

        if not rows:
            # Still offer scratch create via "Create New" when cache matches system
            labels_single = [placeholder, create_new_lbl]
            self._plan_site_display_to_id[placeholder] = None
            self._plan_site_display_to_id[create_new_lbl] = PLAN_SITE_CREATE_NEW_ID
            _set_combo(labels_single, placeholder, "readonly")
            self._restore_plan_site_combo_selection(p, rows, placeholder, create_new_lbl)
            return

        labels: List[str] = [placeholder, create_new_lbl]
        self._plan_site_display_to_id[placeholder] = None
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
        """Spawn worker: architect gate then GET /sites; apply on main thread via ``after``."""
        p = self.plugin
        frame = getattr(p, "frame", None) if p else None
        if not p or frame is None:
            return
        if self._plan_site_refresh_inflight:
            return

        sa = p.current_system_address
        if sa is None:
            p.plan_sites_transient_message = tr("No system context")
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
        snap = p.cmdr_snapshot

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
                arch_name = _parse_architect_name(arch_raw)
                if not arch_name or str(arch_name).strip().lower() != str(snap).strip().lower():
                    result["reason"] = "not_architect"
                    return result

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
                plan_rows = [s for s in sites if isinstance(s, dict) and str(s.get("status", "")).lower() == "plan"]
                result["ok"] = True
                result["rows"] = plan_rows
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
        if res.get("ok"):
            p.plan_sites_transient_message = None
            p.plan_sites_architect_denied = False
            p.plan_sites_system_key = res.get("system_address")
            p.plan_sites_rows = list(res.get("rows") or [])
            p.selected_plan_site_id = None
            p.selected_plan_site_obj = None
        elif res.get("reason") == "not_architect":
            p.plan_sites_transient_message = None
            p.plan_sites_architect_denied = True
        elif res.get("reason") == "no_cmdr":
            p.plan_sites_transient_message = tr("No commander (wait for LoadGame)")
            p.plan_sites_architect_denied = False
        elif res.get("reason") == "http_error":
            p.plan_sites_architect_denied = False
            detail = res.get("detail") or ""
            p.plan_sites_transient_message = tr("Plan sites refresh failed") + (f": {detail}" if detail else "")
        self.refresh_plan_site_row_state()
    
    def update_status(self, message: str):
        """
        Update the UI status label
        
        :param message: The status message to display
        """
        if self.status_label:
            self.status_label['text'] = message
            logger.info(message)
    
    def update_create_button(self):
        """Enable/disable create button based on docking status and existing projects"""
        logger.debug(f"update_create_button - is_docked: {self.plugin.is_docked}, market_id: {self.plugin.current_market_id}, is_construction_ship: {self.plugin.is_construction_ship}")
        
        if not self.create_button:
            return

        if self.plan_sites_combo:
            self.refresh_plan_site_row_state()

        # Check if we're at a construction ship
        if self.plugin.is_docked and self.plugin.current_market_id and self.plugin.is_construction_ship:
            # Get system address if we don't have it
            if not self.plugin.current_system_address:
                logger.debug("No system_address, fetching from journal for project check")
                self.plugin.current_system_address = self.plugin.get_system_address_from_journal()
            
            # Check for existing project
            if self.plugin.current_system_address:
                existing_project = self.plugin.check_existing_project(self.plugin.current_system_address, self.plugin.current_market_id)
            else:
                logger.warning("Could not get system_address, unable to check for existing project")
                existing_project = None
            
            if existing_project and existing_project.get("buildId"):
                # Project exists - change button to open build page
                build_id = existing_project.get('buildId', '')
                build_name = existing_project.get('buildName', tr("Unknown"))
                logger.info(f"Found existing project: {build_name} ({build_id})")
                
                self.create_button['state'] = tk.NORMAL
                self.create_button['text'] = tr("🌐 Open Build Page")
                # Change button command to open project link
                self.create_button['command'] = lambda: self._open_project_link()
                
                if self.project_link_label:
                    link_text = f"{build_name}"
                    self.project_link_label['text'] = link_text
                
                # Store build_id for click handler
                self.plugin.current_build_id = build_id
            else:
                # No project yet — button depends on plan-site dropdown (Create New vs link site)
                logger.info("No existing project found")
                
                if self.project_link_label:
                    self.project_link_label['text'] = ""
                    self.plugin.current_build_id = None
                
                p = self.plugin
                ca_ok = (
                    p.plan_sites_system_key is not None
                    and p.current_system_address is not None
                    and int(p.plan_sites_system_key) == int(p.current_system_address)
                )
                sel_id = p.selected_plan_site_id

                if not ca_ok:
                    self.create_button['state'] = tk.DISABLED
                    self.create_button['text'] = tr("Refresh plan sites")
                    self.create_button['command'] = lambda: None
                elif sel_id is None:
                    # Stay enabled so focus/layout never blocks using the plan-site combobox above.
                    self.create_button['state'] = tk.NORMAL
                    self.create_button['text'] = tr("Select plan site first")
                    self.create_button['command'] = self._prompt_select_plan_site_first
                elif sel_id == PLAN_SITE_CREATE_NEW_ID:
                    if p.current_system and not hasattr(p, '_bodies_fetched'):
                        logger.debug("Pre-fetching body data for Create dialog")
                        if not p.current_system_address:
                            p.current_system_address = p.get_system_address_from_journal()
                        p._bodies_fetched = True
                    self.create_button['state'] = tk.NORMAL
                    self.create_button['text'] = tr("🚧Create Build Project")
                    if p.frame:
                        self.create_button['command'] = lambda: self._open_create_dialog(p.frame.master)
                else:
                    self.create_button['state'] = tk.NORMAL
                    self.create_button['text'] = tr("🔗 Link Build Site")
                    self.create_button['command'] = self._start_link_build_site
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
        messagebox.showinfo(
            tr("Select plan site first"),
            tr("Choose a plan site from the dropdown above, or pick Create New."),
        )

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
        build_name = str(site_obj.get("name") or "").strip()
        build_type = str(site_obj.get("buildType") or "").strip()
        if not site_id or not build_type:
            messagebox.showerror(tr("Link Build Site"), tr("Selected site is missing id or buildType."))
            return

        arch_name = (p.cmdr_name or getattr(p, "cmdr_snapshot", None) or "").strip()
        if not arch_name:
            messagebox.showwarning(
                tr("Link Build Site"),
                tr("No commander name — wait for LoadGame or restart EDMC with a journal."),
            )
            return

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
                    for row in sites:
                        if isinstance(row, dict) and str(row.get("id")) == str(site_id):
                            live_status = str(row.get("status") or "").strip().lower()
                            if live_status and live_status != "plan":
                                out["phase"] = "site_not_plan"
                                out["detail"] = live_status
                                return out
                            break

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
                payload = {
                    "marketId": int(mid),
                    "systemAddress": int(sa_cache),
                    "buildName": build_name,
                    "buildType": build_type,
                    "systemSiteId": site_id,
                    "architectName": arch_name,
                }
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
                return out
            except Exception as e:
                out["phase"] = "error"
                out["detail"] = str(e)
                return out

        def finish(res: Dict[str, Any]) -> None:
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
                for row in p.plan_sites_rows:
                    if isinstance(row, dict) and str(row.get("id")) == str(sid_mark):
                        row["status"] = "build"
                        break
            bid = res.get("build_id")
            if bid:
                p.current_build_id = bid
            p.invalidate_project_location_cache()
            self.refresh_plan_site_row_state()
            self.update_create_button()
            messagebox.showinfo(
                tr("Link Build Site"),
                trf("Linked plan site. buildId={bid}", bid=bid or "?"),
            )

        def run() -> None:
            r = work()
            try:
                frame.after(0, lambda: finish(r))
            except tk.TclError:
                pass

        Thread(target=run, daemon=True).start()

    def _open_project_link(self):
        """Open the existing project in browser"""
        if self.plugin and self.plugin.current_build_id:
            import webbrowser
            url = f"https://ravencolonial.com/#build={self.plugin.current_build_id}"
            logger.info(f"Opening project page: {url}")
            webbrowser.open(url)
    
    def _open_create_dialog(self, parent):
        """Open the Create Project dialog"""
        if self.plugin:
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
        
        # tk.Frame so theme background matches the rest of the plugin strip (see create_plugin_frame).
        self.update_frame = tk.Frame(self.plugin.frame, highlightthickness=0, borderwidth=0)
        self.update_frame.pack(side=tk.TOP, fill=tk.X, padx=4, pady=4, before=self.main_controls_frame)
        for col in range(3):
            self.update_frame.columnconfigure(col, weight=1)
        
        # Get version info
        try:
            from ..version_check import CURRENT_VERSION
            current = CURRENT_VERSION()
        except Exception:
            current = "unknown"
        
        remote = self.plugin.update_info.remote_version or "unknown"
        
        # Info label — theme foreground/background (no hard-coded accent colors)
        info_text = trf("Update Available: v{current} → v{remote}", current=current, remote=remote)
        info_label = ttk.Label(
            self.update_frame,
            text=info_text,
            wraplength=560,
            justify=tk.LEFT,
        )
        info_label.grid(row=0, column=0, columnspan=3, sticky=tk.W, padx=2, pady=2)
        
        # Buttons
        btn_download = tk.Button(
            self.update_frame,
            text=tr("📥 Go to Download"),
            command=self._open_download_page,
        )
        btn_download.grid(row=1, column=0, padx=2, pady=2)

        btn_autoupdate = tk.Button(
            self.update_frame,
            text=tr("⚡ Auto-Update"),
            command=self._trigger_autoupdate,
        )
        btn_autoupdate.grid(row=1, column=1, padx=2, pady=2)

        btn_dismiss = tk.Button(
            self.update_frame,
            text=tr("✖ Dismiss"),
            command=self._dismiss_update_notification,
        )
        btn_dismiss.grid(row=1, column=2, padx=2, pady=2)

        ttk.Separator(self.update_frame, orient=tk.HORIZONTAL).grid(
            row=2, column=0, columnspan=3, sticky=tk.EW, pady=(4, 0)
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
        self.update_status(tr("Ravencolonial: Updating..."))
        
        def update_thread():
            """Background thread for update installation"""
            try:
                logger.info("Manual auto-update triggered")
                self.plugin.update_info.run_autoupdate()
                logger.info(
                    "Update complete — restart EDMC to use v%s",
                    self.plugin.update_info.remote_version,
                )

                # Update UI
                if self.update_frame:
                    self.plugin.frame.after(0, self._dismiss_update_notification)
                if self.status_label:
                    self.plugin.frame.after(
                        0,
                        lambda: self.update_status(tr("Ravencolonial: Update installed - Restart EDMC")),
                    )
                
            except Exception as e:
                logger.error(f"Manual auto-update failed: {e}", exc_info=True)
                plug.show_error(trf("Ravencolonial: Update failed - {detail}", detail=str(e)))
                
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
                        lambda: self.update_status(tr("Ravencolonial: Update failed")),
                    )
        
        # Start update in background
        Thread(target=update_thread, daemon=True, name="manual-autoupdate").start()
