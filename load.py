"""
EDMC Plugin for Ravencolonial Colonization Tracking

This plugin tracks Elite Dangerous colonization activities and sends data
to Ravencolonial (ravencolonial.com) by grinning2001
"""

import tkinter as tk
from tkinter import ttk, messagebox
import myNotebook as nb
from config import appname, config
from companion import CAPIData
from collections import deque
from typing import Optional, Dict, Any, List, Union, Tuple, Deque
from threading import Thread, Lock
from datetime import datetime, timezone
import queue
import logging
import os
import sys
import functools
import l10n
import plug
import webbrowser
import json
import time
import requests
import timeout_session

try:
    from ttkHyperlinkLabel import HyperlinkLabel
except ImportError:  # pragma: no cover - only when running outside EDMC
    HyperlinkLabel = None  # type: ignore[misc, assignment]

from . import create_project_dialog
from . import construction_completion
from . import i18n
from . import fleet_carrier_handler
from . import version_check
from . import capi_cache
from . import plugin_file_log
from .api import RavencolonialAPIClient
from .api.client import normalize_commodity_key, _normalize_cargo_map, resolve_build_id
from .handlers import JournalEventHandler
from .plugin_config import PluginConfig
from .station_names import normalize_dock_station_name
from .site_market_id_repair import (
    dock_context_skips_market_id_repair,
    market_id_is_player_colony_station,
    market_id_repair_candidates,
    site_name_repair_candidates,
    site_market_id_missing,
    site_market_id_repair_retry_delay,
)
from .ui import UIManager

# Plugin metadata
plugin_name = os.path.basename(os.path.dirname(__file__))
plugin_version = "1.7.6"
# Exposed for EDMC plug.get_version() / Plugin Browser (see PLUGINS.md)
VERSION = plugin_version

# Setup logging per EDMC documentation
# A Logger is used per 'found' plugin to make it easy to include the plugin's
# folder name in the logging output format.
# NB: plugin_name here *must* be the plugin's folder name
logger = logging.getLogger(f'{appname}.{plugin_name}')

# If the Logger has handlers then it was already set up by the core code, else
# it needs setting up here.
if not logger.hasHandlers():
    level = logging.INFO  # So logger.info(...) is equivalent to print()
    
    logger.setLevel(level)
    logger_channel = logging.StreamHandler()
    # Use simple formatter to avoid osthreadid issues
    logger_formatter = logging.Formatter('%(name)s: %(levelname)s - %(message)s')
    logger_channel.setFormatter(logger_formatter)
    logger.addHandler(logger_channel)

# Setup localization
plugin_tl = functools.partial(l10n.translations.tl, context=__file__)
i18n.set_translate(plugin_tl)

# Global state
this = None


def _notify_plugin_status_main_thread(message: str) -> None:
    """Log and refresh plugin status from a worker thread without plug.show_error (no error sound)."""
    global this
    logger.info(message)
    if not this:
        return
    frame = getattr(this, 'frame', None)
    if frame is None:
        return

    def apply() -> None:
        try:
            if frame.winfo_exists() and getattr(this, 'ui_manager', None):
                this.ui_manager.update_status(message)
        except tk.TclError:
            pass

    try:
        frame.after(0, apply)
    except tk.TclError:
        pass


def _strip_leading_v_for_display(version: Optional[str]) -> str:
    """Return version text without a leading GitHub tag ``v`` for UI strings that add it."""
    if not version:
        return "?"
    s = str(version).strip()
    return s[1:] if s[:1].lower() == "v" else s


def _journal_parse_timestamp(entry: Dict[str, Any]) -> Optional[datetime]:
    raw = entry.get("timestamp")
    if not raw or not isinstance(raw, str):
        return None
    try:
        s = raw.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _journal_entry_is_dock_context(entry: Dict[str, Any]) -> bool:
    """True for journal rows that describe being docked at a station (current dock target)."""
    ev = entry.get("event")
    if ev == "Docked":
        return True
    return ev == "Location" and entry.get("Docked") is True


def _stealth_construction_reporting() -> bool:
    """When True, skip journal-driven construction depot, contributions, and depot deliveries to the API."""
    try:
        return config.get_bool("ravencolonial_stealth_construction_reporting")
    except Exception:
        return False


def _elite_journal_dir() -> Optional[str]:
    """Elite Dangerous journal folder from EDMC config or default Saved Games path."""
    journal_dir: Optional[str] = None
    try:
        journal_dir = config.get_str("journaldir") or None
    except Exception:
        journal_dir = None
    if not journal_dir:
        try:
            candidate = os.path.join(
                os.path.expanduser("~"),
                "Saved Games",
                "Frontier Developments",
                "Elite Dangerous",
            )
            if os.path.isdir(candidate):
                journal_dir = candidate
        except Exception:
            pass
    if journal_dir and os.path.isdir(journal_dir):
        return journal_dir
    return None


class RavencolonialPlugin:
    """Main plugin class to track colonization data"""
    
    def __init__(self):
        # Initialize API client
        self.api_client = RavencolonialAPIClient(
            api_base=PluginConfig.get_api_base(),
            user_agent=PluginConfig.get_user_agent()
        )
        
        # Initialize journal event handler
        self.journal_handler = JournalEventHandler(self)
        
        # Initialize UI manager
        self.ui_manager = UIManager(self)
        
        # Plugin state
        self.cmdr_name: Optional[str] = None
        self.current_system: Optional[str] = None
        self.current_station: Optional[str] = None
        self.current_market_id: Optional[int] = None
        self.current_system_address: Optional[int] = None
        self.star_pos: Optional[List[float]] = None
        self.body_num: Optional[int] = None
        self.body_name: Optional[str] = None
        self.station_type: Optional[str] = None
        self.faction_name: Optional[str] = None
        self.cargo: Dict[str, int] = {}
        self.last_cargo: Dict[str, int] = {}
        # Commander ship snapshot for POST /api/cmdr/currentShip (SrvSurvey parity)
        self.ship_display_name: Optional[str] = None
        self.ship_ident: Optional[str] = None
        self.ship_type: Optional[str] = None
        self.ship_cargo_capacity: Optional[int] = None
        self._last_current_ship_sig: Optional[str] = None
        self.construction_depot_data: Optional[Dict[str, Any]] = None  # Full ColonisationConstructionDepot event
        self.last_depot_remaining_need: Dict[str, int] = {}  # Full remaining-need map for depot PATCH diffing
        # Short TTL cache for GET /api/system/{id64}/{marketId} — avoids hammering the API when
        # ColonisationConstructionDepot fires frequently or update_create_button runs often at the same dock.
        self._project_location_cache_ttl_s: float = 4.0
        self._project_location_cache: Optional[
            Tuple[int, int, Optional[Dict[str, Any]], float]
        ] = None  # (system_address, market_id, payload, monotonic_ts)
        # After one "no project" GET for (sa, mid), skip further location GETs until
        # ``invalidate_project_location_cache`` or ``check_existing_project(..., force=True)``.
        self._project_location_probe_frozen: Optional[Tuple[int, int]] = None
        self._last_depot_patch_payload_sig: Optional[str] = None  # Skip duplicate PATCH /api/project/{buildId} depot bodies
        self._site_market_id_repair_inflight: set[Tuple[int, str, int]] = set()
        self._site_market_id_repair_visited: Deque[Tuple[int, str]] = deque(maxlen=50)
        self._site_market_id_repair_visited_set: set[Tuple[int, str]] = set()
        self._site_market_id_repair_visit_cache_path: Optional[str] = None
        self._site_market_id_repair_lock = Lock()
        self.is_construction_ship = False
        self.is_docked = False
        self._bodies_fetched = False
        # EDMC journal_entry ``state`` (shallow copy); SystemAddress tracks current system after Undocked too
        self._last_edmc_state: Optional[Dict[str, Any]] = None
        # One-time snapshot from EDMC ``monitor.cmdr`` (journal commander string can differ slightly)
        self.cmdr_snapshot: Optional[str] = None
        # Plan sites (v2 /sites) cache: last successful refresh for a system (re-enabled when you return)
        self.plan_sites_system_key: Optional[int] = None
        self.plan_sites_rows: List[Dict[str, Any]] = []
        # True after refresh when commander matches system architect (scratch Create New allowed).
        self.plan_sites_allow_create_new: bool = True
        self.plan_sites_transient_message: Optional[str] = None
        self.selected_plan_site_id: Optional[str] = None
        # Full site dict when a plan row is selected (for Link Build Site); None for Create New / placeholder
        self.selected_plan_site_obj: Optional[Dict[str, Any]] = None
        self.overlay_build_site_rows: List[Dict[str, Any]] = []
        self.overlay_sites_system_key: Optional[int] = None
        self.overlay_sites_transient_message: Optional[str] = None
        self.selected_overlay_build_id: Optional[str] = None
        self.overlay_ui_enabled: bool = False
        self.overlay_always_on: bool = False
        self.overlay_carrier_tracking_enabled: bool = False
        self.overlay_fc_selection: str = "all"
        self.overlay_project_linked_fcs: List[Dict[str, Any]] = []
        self.overlay_fc_cargo_by_market: Dict[int, Dict[str, int]] = {}
        self._overlay_fc_cargo_inflight: bool = False
        self.overlay_project_fetch_inflight: bool = False
        self.overlay_project_cache_by_build_id: Dict[str, Dict[str, Any]] = {}
        self._track_all_refresh_on_qualifying_undock: bool = False
        self.overlay_theme_id: Optional[str] = None
        # Piggyback CAPI refresh cadence: fetch /squadron at most every ~15 minutes
        self._squadron_cache_interval_s: float = 15 * 60
        self._last_squadron_fetch_attempt_monotonic: float = 0.0
        self._squadron_fetch_inflight: bool = False
        self._squadron_fetch_lock = Lock()
        
        # Queue for async API calls
        self.api_queue = queue.Queue()
        self.worker_thread: Optional[Thread] = None
        self._worker_lock = Lock()
        
        # UI elements are now managed by UIManager
        # These references are kept for backward compatibility
        self.status_label = None
        self.frame = None
        self.create_button = None
        self.project_link_label = None
        self.current_build_id = None
        self.overlay_project_cache: Optional[Dict[str, Any]] = None
        self.build_overlay = None
        
        # Build types cache
        self.build_types: List[Dict] = []
        
        # Construction completion handler
        self.completion_handler = construction_completion.ConstructionCompletionHandler(self)
        
        # Fleet Carrier handler
        self.fc_handler = fleet_carrier_handler.FleetCarrierHandler(self)
        
        # Update checker
        self.update_info = version_check.UpdateInfo(
            logger, 
            plugin_name,
            allow_prerelease=PluginConfig.get_check_prerelease()
        )
        self.update_available = False
        self.update_dismissed = False

    def ensure_cmdr_snapshot_once(self) -> None:
        """Read ``monitor.cmdr`` from EDMC once and cache for architect gate (main thread)."""
        if self.cmdr_snapshot is not None:
            return
        try:
            from monitor import monitor  # type: ignore[import-untyped]

            raw = getattr(monitor, "cmdr", None)
            if raw is not None and str(raw).strip():
                self.cmdr_snapshot = str(raw).strip()
                logger.debug("cmdr_snapshot set from monitor.cmdr")
        except Exception as e:
            logger.debug("cmdr_snapshot not available yet: %s", e)

    def refresh_plan_sites_ui(self) -> None:
        """Reconcile plan-site and overlay build comboboxes (main thread)."""
        if getattr(self, "ui_manager", None):
            self.ui_manager.refresh_plan_site_row_state()
            self.ui_manager.refresh_overlay_build_row_state()

    def refresh_track_all_projects_if_selected(self, reason: str = "") -> None:
        """Refresh all Track All project details for construction/FC dock context changes."""
        if (
            not getattr(self, "overlay_ui_enabled", False)
            or getattr(self, "selected_overlay_build_id", None) != "__OVERLAY_TRACK_ALL__"
            or getattr(self, "overlay_project_fetch_inflight", False)
        ):
            return
        ui = getattr(self, "ui_manager", None)
        row = getattr(ui, "_overlay_row", None) if ui is not None else None
        fetch_all = getattr(row, "fetch_all_projects_async", None)
        if callable(fetch_all):
            logger.debug("Refreshing Track All project details after %s", reason or "event")
            fetch_all()

    def get_project_by_build_id(self, build_id: str) -> Optional[Dict]:
        """GET /api/project/{buildId} for overlay display."""
        return self.api_client.get_project_by_build_id(build_id)
        
    def _api_worker(self):
        """Background worker thread for API calls"""
        while True:
            try:
                task = self.api_queue.get()
                if task is None:
                    break
                    
                func, args, kwargs = task
                try:
                    func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"API call failed: {e}", exc_info=True)
                    # Show error in EDMC status bar asynchronously
                    error_msg = i18n.tr("Ravencolonial API error:") + f" {str(e)}"
                    plug.show_error(error_msg)
                finally:
                    self.api_queue.task_done()
            except Exception as e:
                logger.error(f"Worker thread error: {e}", exc_info=True)
    
    def queue_api_call(self, func, *args, **kwargs):
        """Queue an API call to be executed in background thread"""
        self._ensure_api_worker()
        self.api_queue.put((func, args, kwargs))

    def _ensure_api_worker(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return
        with self._worker_lock:
            if self.worker_thread and self.worker_thread.is_alive():
                return
            self.worker_thread = Thread(
                target=self._api_worker,
                daemon=True,
                name="ravencolonial-api-worker",
            )
            self.worker_thread.start()

    def maybe_queue_squadron_cache_refresh(
        self,
        trigger: str,
        is_beta: Optional[bool],
        source_host: Optional[str],
        request_cmdr: Optional[str],
    ) -> None:
        """
        Piggyback on EDMC CAPI refresh: throttle and enqueue one /squadron fetch.
        Network I/O runs on plugin worker thread (never on the EDMC UI thread).
        """
        now = time.monotonic()
        with self._squadron_fetch_lock:
            if self._squadron_fetch_inflight:
                logger.debug("Skipping /squadron fetch (%s): request already in flight", trigger)
                return
            if (now - self._last_squadron_fetch_attempt_monotonic) < self._squadron_cache_interval_s:
                return
            self._last_squadron_fetch_attempt_monotonic = now
            self._squadron_fetch_inflight = True

        self.queue_api_call(
            self._fetch_and_cache_squadron,
            trigger,
            is_beta,
            source_host,
            request_cmdr,
        )

    def _fetch_and_cache_squadron(
        self,
        trigger: str,
        is_beta: Optional[bool],
        source_host: Optional[str],
        request_cmdr: Optional[str],
    ) -> None:
        """Fetch /squadron using a dedicated HTTP session (auth copied from EDMC).

        Avoids sharing ``companion.session.requests_session`` with EDMC's CAPI worker,
        which can run concurrent GETs on another thread.
        """
        try:
            import companion

            sess = getattr(companion, "session", None)
            edmc_session = getattr(sess, "requests_session", None) if sess else None
            if edmc_session is None:
                logger.debug("Skipping /squadron fetch (%s): Companion session not ready", trigger)
                return

            auth = edmc_session.headers.get("Authorization")
            if not auth:
                logger.debug("Skipping /squadron fetch (%s): no Authorization on EDMC session", trigger)
                return

            capi_host = source_host or sess.capi_host_for_galaxy()
            if not capi_host:
                logger.debug("Skipping /squadron fetch (%s): unresolved CAPI host", trigger)
                return

            url = f"{capi_host}/squadron"
            with requests.Session() as http:
                http.headers["Authorization"] = auth
                ua = edmc_session.headers.get("User-Agent")
                if ua:
                    http.headers["User-Agent"] = ua
                response = http.get(url, timeout=20)

            # Not all accounts/roles expose /squadron. Keep this silent and non-fatal.
            if response.status_code in (401, 403, 404):
                logger.debug(
                    "/squadron unavailable (%s): HTTP %s",
                    trigger,
                    response.status_code,
                )
                return

            response.raise_for_status()
            raw = response.json()
            payload = {
                "/squadron": {
                    "query_time": datetime.now(timezone.utc).isoformat(sep=" "),
                    "raw_data": raw,
                }
            }
            capi_cache.write(
                "squadron",
                payload,
                is_beta=is_beta,
                source_host=capi_host,
                request_cmdr=request_cmdr or self.cmdr_name,
            )
            logger.info("Cached /squadron snapshot from Companion (%s)", trigger)
        except Exception as e:
            logger.debug("Squadron CAPI cache fetch failed (%s): %s", trigger, e, exc_info=True)
        finally:
            with self._squadron_fetch_lock:
                self._squadron_fetch_inflight = False

    def _refresh_ship_from_state(self, state: Dict[str, Any]) -> None:
        """Mirror EDMC monitor ship fields (Loadout / LoadGame progression)."""
        cap = state.get("CargoCapacity")
        if cap is not None:
            try:
                self.ship_cargo_capacity = int(cap)
            except (TypeError, ValueError):
                pass
        st = state.get("ShipType")
        if st:
            s = str(st).strip()
            if s:
                self.ship_type = s
        ident = state.get("ShipIdent")
        if ident is not None:
            sid = str(ident).strip()
            self.ship_ident = sid if sid else self.ship_ident
        sn = state.get("ShipName")
        if sn is not None and str(sn).strip() not in ("", " "):
            self.ship_display_name = str(sn).strip()

    def _refresh_ship_from_loadout_entry(self, entry: Dict[str, Any]) -> None:
        """Apply Loadout journal row (main ship only; skip fighter/SRV)."""
        cap = entry.get("CargoCapacity")
        if cap is not None:
            try:
                self.ship_cargo_capacity = int(cap)
            except (TypeError, ValueError):
                pass
        if entry.get("Ship"):
            s = str(entry["Ship"]).strip()
            if s:
                self.ship_type = s
        ident = entry.get("ShipIdent")
        if ident is not None:
            sid = str(ident).strip()
            self.ship_ident = sid if sid else None
        sn = entry.get("ShipName")
        if sn and str(sn).strip() not in ("", " "):
            self.ship_display_name = str(sn).strip()

    def _build_current_ship_payload(self, state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Body for POST /api/cmdr/currentShip; None if API key, cmdr, or ship metadata is missing."""
        if not getattr(self.api_client, "api_key", None):
            return None
        cmdr = self.cmdr_name or getattr(self.api_client, "cmdr_name", None)
        if not cmdr:
            return None

        merged: Dict[str, Any] = {}
        if state:
            merged.update(state)
        if self.ship_cargo_capacity is not None:
            merged["CargoCapacity"] = self.ship_cargo_capacity
        if self.ship_type:
            merged["ShipType"] = self.ship_type
        if self.ship_ident is not None:
            merged["ShipIdent"] = self.ship_ident
        if self.ship_display_name:
            merged["ShipName"] = self.ship_display_name

        max_cargo = merged.get("CargoCapacity")
        if max_cargo is None:
            return None
        try:
            max_cargo_i = int(max_cargo)
        except (TypeError, ValueError):
            return None

        ship_type = str(merged.get("ShipType") or "").strip()
        if not ship_type:
            return None

        name = merged.get("ShipName")
        if not name or str(name).strip() in ("", " "):
            name = merged.get("ShipIdent")
        if not name or str(name).strip() in ("", " "):
            name = ship_type

        cargo_norm = _normalize_cargo_map(dict(self.cargo))
        return {
            "cmdr": cmdr,
            "name": str(name).strip(),
            "type": ship_type,
            "maxCargo": max_cargo_i,
            "cargo": cargo_norm,
        }

    def _queue_publish_current_ship(self, state: Optional[Dict[str, Any]], reason: str) -> None:
        """Enqueue POST /api/cmdr/currentShip when cargo or ship identity changes (SrvSurvey parity)."""
        try:
            if config.get_bool("ravencolonial_stealth_ship_cargo"):
                logger.debug("Ship cargo stealth: skip publish current ship (%s)", reason)
                return
        except Exception:
            pass

        payload = self._build_current_ship_payload(state)
        if not payload:
            logger.debug("publish current ship skipped (%s): incomplete context", reason)
            return

        sig = json.dumps(payload, sort_keys=True, default=str)
        if sig == self._last_current_ship_sig:
            return
        self.queue_api_call(self._run_publish_current_ship_payload, sig, payload)

    def _run_publish_current_ship_payload(self, sig: str, payload: Dict[str, Any]) -> None:
        if self.api_client.publish_current_ship(payload):
            self._last_current_ship_sig = sig

    def _handle_commander_market_trade(
        self,
        entry: Dict[str, Any],
        *,
        is_buy: bool,
        state: Optional[Dict[str, Any]],
    ) -> None:
        """Apply station MarketBuy/MarketSell to commander hold (non-fleet-carrier trades)."""
        try:
            if config.get_bool("ravencolonial_stealth_ship_cargo"):
                return
        except Exception:
            pass

        updated = _apply_market_trade_to_cargo(
            _normalize_cargo_map(dict(self.cargo or {})),
            entry,
            is_buy=is_buy,
        )
        if updated == _normalize_cargo_map(dict(self.cargo or {})):
            return

        self.cargo = updated
        logger.debug(
            "Commander market %s hold: %s",
            "buy" if is_buy else "sell",
            updated,
        )
        self._queue_publish_current_ship(state, "MarketBuy" if is_buy else "MarketSell")

    def invalidate_project_location_cache(self) -> None:
        """Clear cached GET /api/system/... result (dock change, new project, link, etc.)."""
        self._project_location_cache = None
        self._project_location_probe_frozen = None

    def get_project(
        self,
        system_address: int,
        market_id: int,
        *,
        use_location_cache: bool = False,
    ) -> Optional[Dict]:
        """Get project details for a specific system/station (GET /api/system/{id64}/{marketId})."""
        now = time.monotonic()
        if use_location_cache:
            c = self._project_location_cache
            if (
                c is not None
                and c[0] == system_address
                and c[1] == market_id
                and (now - c[3]) < self._project_location_cache_ttl_s
            ):
                return c[2]
        result = self.api_client.get_project(system_address, market_id)
        if use_location_cache:
            # Only cache successful project payloads. Caching ``None`` hid new projects for
            # the TTL after a prior "no project" response (Open Build Page never appeared).
            if result is not None:
                self._project_location_cache = (system_address, market_id, result, now)
            else:
                self._project_location_cache = None
        return result
    
    def contribute_cargo(self, build_id: str, cmdr: str, cargo_diff: Dict[str, int]):
        """Submit cargo contribution to Ravencolonial"""
        return self.api_client.contribute_cargo(build_id, cmdr, cargo_diff)
    
    def patch_project_depot_state(
        self, build_id: str, payload: Dict, depot_sig: Optional[str] = None
    ) -> bool:
        """PATCH remaining need from ``ColonisationConstructionDepot`` journal truth (not /supply)."""
        project_view = self.api_client.patch_project_update(build_id, payload)
        if project_view is not None:
            self.maybe_clear_phantom_commodities(build_id, project_view)
            commodities = payload.get("commodities")
            if isinstance(commodities, dict):
                self.remember_depot_remaining_need(commodities)
            if depot_sig is not None:
                self._last_depot_patch_payload_sig = depot_sig
            if isinstance(project_view, dict):
                if getattr(self, "selected_overlay_build_id", None) == "__OVERLAY_TRACK_ALL__":
                    cache = dict(getattr(self, "overlay_project_cache_by_build_id", None) or {})
                    cache[str(build_id)] = dict(project_view)
                    self.overlay_project_cache_by_build_id = cache
                    build_overlay = getattr(self, "build_overlay", None)
                    if build_overlay is not None and hasattr(build_overlay, "remember_all_projects"):
                        build_overlay.remember_all_projects(list(cache.values()))
                else:
                    self.overlay_project_cache = project_view
            self.refresh_build_overlay()
            return True
        logger.warning(
            "Depot PATCH failed for %s — local need unchanged; will retry on next depot event",
            build_id,
        )
        return False
    
    def get_commander_projects(self, cmdr: str) -> list:
        """Get all projects for a commander"""
        return self.api_client.get_commander_projects(cmdr)
    
    def get_system_sites(self, name_or_num: Optional[Union[str, int]] = None) -> List[Dict]:
        """
        GET /api/v2/system/{nameOrNum}/sites.

        Pass the system **name** or **id64** (same as Ravencolonial ``nameOrNum``).
        If omitted, uses ``current_system_address`` (resolving from journal when missing).
        """
        key: Optional[Union[str, int]] = name_or_num
        if key is None:
            if not self.current_system_address:
                logger.debug("No system address available, trying to get from journal")
                self.current_system_address = self.get_system_address_from_journal()
            key = self.current_system_address

        if key is None:
            logger.error("Cannot get system sites - no system name/id64 (pass argument or dock so journal has address)")
            return []

        return self.api_client.get_system_sites(key)

    def remember_site_market_id_repair_visit(self, market_id: int, station_name: Optional[str] = None) -> None:
        """Remember recently processed dock marketId/name contexts to avoid repeat /sites API checks."""
        try:
            mid = int(market_id)
        except (TypeError, ValueError):
            return
        station_key = normalize_dock_station_name(station_name).casefold() if station_name is not None else ""
        visited_key = (mid, station_key)
        with self._site_market_id_repair_lock:
            if visited_key in self._site_market_id_repair_visited_set:
                return
            if len(self._site_market_id_repair_visited) == self._site_market_id_repair_visited.maxlen:
                old = self._site_market_id_repair_visited.popleft()
                self._site_market_id_repair_visited_set.discard(old)
            self._site_market_id_repair_visited.append(visited_key)
            self._site_market_id_repair_visited_set.add(visited_key)
            recent = len(self._site_market_id_repair_visited)
            self._save_site_market_id_repair_visits_locked()
        logger.debug(
            "Recorded site repair visit marketId=%s station_key=%r (recent=%s)",
            mid,
            station_key,
            recent,
        )

    def configure_site_market_id_repair_visit_cache(self, plugin_dir: str) -> None:
        """Load the persistent rolling repair-visit cache from the plugin directory."""
        self._site_market_id_repair_visit_cache_path = os.path.join(
            plugin_dir,
            "site_market_id_repair_visits.json",
        )
        self._load_site_market_id_repair_visits()

    def _load_site_market_id_repair_visits(self) -> None:
        path = self._site_market_id_repair_visit_cache_path
        if not path or not os.path.exists(path):
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            logger.debug("Could not load site repair visit cache %s: %s", path, e)
            return

        visits_raw = raw.get("visits") if isinstance(raw, dict) else raw
        if not isinstance(visits_raw, list):
            return

        visits: List[Tuple[int, str]] = []
        for item in visits_raw:
            market_raw: Any
            station_raw: Any
            if isinstance(item, dict):
                market_raw = item.get("marketId")
                station_raw = item.get("stationKey", item.get("name", item.get("stationName", "")))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                market_raw, station_raw = item[0], item[1]
            else:
                continue

            try:
                market_id = int(market_raw)
            except (TypeError, ValueError):
                continue
            station_key = normalize_dock_station_name(station_raw).casefold()
            if station_key:
                visits.append((market_id, station_key))

        with self._site_market_id_repair_lock:
            self._site_market_id_repair_visited.clear()
            self._site_market_id_repair_visited_set.clear()
            for visited_key in visits[-50:]:
                if visited_key in self._site_market_id_repair_visited_set:
                    continue
                self._site_market_id_repair_visited.append(visited_key)
                self._site_market_id_repair_visited_set.add(visited_key)

        logger.debug("Loaded %s site repair visit cache entries", len(self._site_market_id_repair_visited_set))

    def _save_site_market_id_repair_visits_locked(self) -> None:
        path = self._site_market_id_repair_visit_cache_path
        if not path:
            return

        payload = {
            "version": 1,
            "visits": [
                {
                    "marketId": market_id,
                    "stationKey": station_key,
                    "stationName": station_key,
                }
                for market_id, station_key in self._site_market_id_repair_visited
            ],
        }
        tmp_path = f"{path}.tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp_path, path)
        except Exception as e:
            logger.debug("Could not save site repair visit cache %s: %s", path, e)
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    def maybe_queue_site_market_id_repair(self, entry: Dict[str, Any]) -> None:
        """
        Queue a conservative repair for legacy v2 site rows missing ``marketId``.

        The worker re-fetches live ``/sites`` rows and updates exactly one matching
        completed/statusless row by normalized journal station name. Repair is skipped
        when more than one ``/sites`` row shares that normalized name.
        """
        if not getattr(self.api_client, "api_key", None):
            logger.debug("Site marketId repair skipped: no RavenColonial API key")
            return

        station_type = entry.get("StationType") or self.station_type
        station_name = entry.get("StationName") or self.current_station
        if dock_context_skips_market_id_repair(
            station_type=station_type,
            station_name=station_name,
            is_construction_ship=bool(self.is_construction_ship),
        ):
            logger.debug(
                "Site marketId repair skipped: dock context type=%r station=%r construction_ship=%s",
                station_type,
                station_name,
                self.is_construction_ship,
            )
            return

        system_address = entry.get("SystemAddress") or self.current_system_address
        market_id = entry.get("MarketID") or self.current_market_id

        if system_address is None or market_id is None or not station_name:
            logger.debug(
                "Site marketId repair skipped: incomplete dock context system=%r market=%r station=%r",
                system_address,
                market_id,
                station_name,
            )
            return

        try:
            sa = int(system_address)
            mid = int(market_id)
        except (TypeError, ValueError):
            logger.debug(
                "Site marketId repair skipped: non-numeric system/market system=%r market=%r",
                system_address,
                market_id,
            )
            return

        if not market_id_is_player_colony_station(mid):
            logger.debug(
                "Site marketId repair skipped: marketId %s is outside player colonization prefixes",
                mid,
            )
            return

        station_key = normalize_dock_station_name(station_name).casefold()
        if not station_key:
            logger.debug("Site marketId repair skipped: empty normalized station name")
            return

        dedupe_key = (sa, station_key, mid)
        visited_key = (mid, station_key)
        with self._site_market_id_repair_lock:
            if visited_key in self._site_market_id_repair_visited_set:
                logger.debug(
                    "Site repair skipped: marketId %s station_key=%r checked recently",
                    mid,
                    station_key,
                )
                return
            if dedupe_key in self._site_market_id_repair_inflight:
                logger.debug("Site marketId repair already in flight for %s", dedupe_key)
                return
            self._site_market_id_repair_inflight.add(dedupe_key)

        self.queue_api_call(
            self.repair_site_market_id_from_dock,
            sa,
            mid,
            str(station_name),
            dedupe_key,
        )

    def repair_site_market_id_from_dock(
        self,
        system_address: int,
        market_id: int,
        station_name: str,
        dedupe_key: Optional[Tuple[int, str, int]] = None,
    ) -> bool:
        """Fetch live system sites, match dock context, and PATCH safe site repairs."""
        try:
            max_fetch_attempts = 3
            station_label = normalize_dock_station_name(station_name)
            sites: Optional[List[Dict[str, Any]]] = None
            fetch_attempts = 0
            for attempt in range(max_fetch_attempts):
                fetch_attempts = attempt + 1
                sites = self.api_client.fetch_system_sites(system_address)
                if sites is not None:
                    break
                if attempt < max_fetch_attempts - 1:
                    delay = site_market_id_repair_retry_delay(attempt)
                    logger.debug(
                        "Site marketId repair /sites fetch failed for %s station=%r; retrying in %.1fs",
                        system_address,
                        station_label,
                        delay,
                    )
                    time.sleep(delay)

            if sites is None:
                logger.info(
                    "Site marketId repair skipped for %s station=%r marketId=%s: /sites fetch failed after %s attempt(s)",
                    system_address,
                    station_label,
                    market_id,
                    fetch_attempts,
                )
                return False

            matches = market_id_repair_candidates(
                sites,
                station_name=station_name,
                dock_market_id=market_id,
            )
            name_matches: List[Dict[str, Any]] = []
            if len(matches) != 1:
                name_matches = site_name_repair_candidates(
                    sites,
                    station_name=station_name,
                    dock_market_id=market_id,
                )

            if len(matches) != 1 and len(name_matches) != 1:
                logger.info(
                    "Site repair skipped for %s station=%r marketId=%s: expected one marketId or name repair match, got marketId=%s name=%s",
                    system_address,
                    station_label,
                    market_id,
                    len(matches),
                    len(name_matches),
                )
                return False

            repair_name = len(matches) != 1
            site = name_matches[0] if repair_name else matches[0]
            previous_market_id = site.get("marketId")
            previous_name = site.get("name")
            site_id = site.get("id")
            if site_id is None or not str(site_id).strip():
                logger.warning(
                    "Site repair failed for system=%s station=%r marketId=%s: matched row has no site id",
                    system_address,
                    station_label,
                    market_id,
                )
                return False
            patch_kwargs: Dict[str, Any]
            if repair_name:
                patch_kwargs = {"name": station_label}
            else:
                patch_kwargs = {"market_id": int(market_id)}
            result = self.api_client.patch_system_site(system_address, str(site_id).strip(), **patch_kwargs)
            if result is None:
                logger.warning(
                    "Site repair failed for site id=%s system=%s marketId=%s",
                    site_id,
                    system_address,
                    market_id,
                )
                return False

            if repair_name:
                logger.info(
                    "Repaired site name for system=%s site id=%s marketId=%s from %r to %r",
                    system_address,
                    site.get("id"),
                    market_id,
                    previous_name,
                    station_label,
                )
            elif site_market_id_missing(previous_market_id):
                logger.info(
                    "Repaired site marketId for system=%s site id=%s name=%r bodyNum=%s marketId=%s",
                    system_address,
                    site.get("id"),
                    site.get("name"),
                    site.get("bodyNum"),
                    market_id,
                )
            else:
                logger.info(
                    "Corrected site marketId for system=%s site id=%s name=%r bodyNum=%s from %s to %s",
                    system_address,
                    site.get("id"),
                    site.get("name"),
                    site.get("bodyNum"),
                    previous_market_id,
                    market_id,
                )
            self.remember_site_market_id_repair_visit(market_id, station_name)
            return True
        finally:
            if dedupe_key is not None:
                with self._site_market_id_repair_lock:
                    self._site_market_id_repair_inflight.discard(dedupe_key)
    
    def get_system_bodies(self, name_or_num: Union[str, int]) -> List[Dict]:
        """GET /api/v2/system/{nameOrNum}/bodies — system name or id64."""
        return self.api_client.get_system_bodies(name_or_num)
    
    def get_system_architect(self, name_or_num: Union[str, int]) -> Optional[str]:
        """GET /api/v2/system/{nameOrNum}/architect — system name or id64."""
        return self.api_client.get_system_architect(name_or_num)
    
    def check_existing_project(
        self, system_address: int, market_id: int, *, force: bool = False
    ) -> Optional[Dict]:
        """
        Check if a project already exists at this location (GET /api/system/...).

        Without ``force``, the first probe that finds no project freezes further GETs for
        that (system_address, market_id) until cache invalidation or ``force=True`` (used
        before Create / Link) so frequent UI refresh does not burst the API.
        """
        sa, mid = int(system_address), int(market_id)
        logger.debug(
            "Checking for existing project at system %s market %s force=%s",
            sa,
            mid,
            force,
        )
        if force:
            self._project_location_probe_frozen = None
            now = time.monotonic()
            result = self.api_client.get_project(sa, mid)
            if resolve_build_id(result):
                self._project_location_cache = (sa, mid, result, now)
                self._project_location_probe_frozen = None
            else:
                self._project_location_cache = None
                self._project_location_probe_frozen = (sa, mid)
            return result
        if self._project_location_probe_frozen == (sa, mid):
            logger.debug(
                "check_existing_project: skip GET (negative frozen) for %s/%s", sa, mid
            )
            return None
        result = self.get_project(sa, mid, use_location_cache=True)
        if resolve_build_id(result):
            self._project_location_probe_frozen = None
            now = time.monotonic()
            self._project_location_cache = (sa, mid, result, now)
        else:
            self._project_location_probe_frozen = (sa, mid)
        return result

    def create_project(self, project_data: Dict[str, Any]) -> Optional[Dict]:
        """Create a new colonization project"""
        result = self.api_client.create_project(project_data)
        if result:
            self.invalidate_project_location_cache()
        return result
    
    def handle_cargo_depot(self, entry: Dict[str, Any]):
        """Handle CargoDepot journal event"""
        return self.journal_handler.handle_cargo_depot(entry)
    
    def handle_colonisation_construction_depot(self, entry: Dict[str, Any]):
        """Handle ColonisationConstructionDepot journal event"""
        return self.journal_handler.handle_colonisation_construction_depot(entry)
    
    def handle_colonisation_contribution(self, entry: Dict[str, Any]):
        """Handle ColonisationContribution journal event"""
        return self.journal_handler.handle_colonisation_contribution(entry)
    
    def handle_market(self, entry: Dict[str, Any]):
        """Handle Market journal event"""
        return self.journal_handler.handle_market(entry)
    
    def get_market_data(self) -> Optional[List[Dict[str, Any]]]:
        """Get current market data from EDMC"""
        try:
            # EDMC provides market data through the monitor's market file
            # This is a simplified implementation - in practice you'd need to
            # access EDMC's market data through the appropriate API
            import json
            import os
            
            # Get the market file path from EDMC's config
            journal_dir = config.get_str('journaldir') or None
            if not journal_dir:
                logger.warning("No journal directory configured")
                return None
            
            # Look for the latest market file
            market_files = [f for f in os.listdir(journal_dir) if f.startswith('Market.') and f.endswith('.json')]
            if not market_files:
                logger.warning("No market files found")
                return None
            
            # Get the most recent market file
            latest_file = sorted(market_files)[-1]
            market_path = os.path.join(journal_dir, latest_file)
            
            with open(market_path, "r", encoding="utf-8") as f:
                market_data = json.load(f)
            
            # Extract items from market data
            items = market_data.get('Items', [])
            logger.debug(f"Loaded {len(items)} items from market file")
            
            return items
        except Exception as e:
            logger.error(f"Failed to get market data: {e}")
            return None
    
    def update_status(self, message: str, *, l10n_key: Optional[str] = None):
        """Update the UI status label"""
        return self.ui_manager.update_status(message, l10n_key=l10n_key)
    
    def update_create_button(self):
        """Enable/disable create button based on docking status and existing projects"""
        self.ui_manager.update_create_button()
        self.refresh_build_overlay()

    def refresh_build_overlay(self) -> None:
        """Update in-game overlay (EDMCModernOverlay) from current build/depot state."""
        if (
            not getattr(self, "build_overlay", None)
            and (
                not getattr(self, "overlay_ui_enabled", False)
                or not getattr(self, "selected_overlay_build_id", None)
            )
        ):
            return
        try:
            if getattr(self, "build_overlay", None) is None:
                from .overlay import BuildProjectOverlay

                self.build_overlay = BuildProjectOverlay(self)
            self.build_overlay.refresh()
        except Exception as e:
            logger.debug("Build overlay refresh failed: %s", e)
    
    def get_system_address_from_journal(self) -> Optional[int]:
        """
        Resolve the commander's current system id64.

        Prefer EDMC's merged ``state`` (``SystemAddress`` stays current after Undocked / jumps).
        Otherwise scan journals for the **latest** ``Docked`` or ``Location`` with ``Docked: true``
        by event timestamp (handles load-already-docked and multi-file sessions).
        """
        logger.debug("get_system_address_from_journal() called")
        try:
            snap = self._last_edmc_state
            if snap and snap.get("SystemAddress") is not None:
                try:
                    addr = int(snap["SystemAddress"])
                except (TypeError, ValueError):
                    addr = None
                if addr is not None:
                    logger.debug("Using SystemAddress %s from EDMC state snapshot", addr)
                    sn = snap.get("SystemName")
                    if isinstance(sn, str) and sn and not self.current_system:
                        self.current_system = sn
                    sp = snap.get("StarPos")
                    if sp and not self.star_pos:
                        self.star_pos = sp
                    return addr

            import glob

            journal_dir = _elite_journal_dir()
            if not journal_dir:
                logger.debug("No valid journal directory found")
                return None

            journal_files = glob.glob(os.path.join(journal_dir, "Journal.*.log"))
            if not journal_files:
                logger.debug("No journal files found")
                return None

            journal_files.sort(key=os.path.getmtime, reverse=True)
            max_files_to_check = 5
            files_to_check = journal_files[:max_files_to_check]
            logger.debug("Scanning %s journal file(s) for latest dock context", len(files_to_check))

            candidates: List[tuple] = []
            for file_index, journal_file in enumerate(files_to_check):
                try:
                    with open(journal_file, "r", encoding="utf-8") as f:
                        for line_index, line in enumerate(f):
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                entry = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if not _journal_entry_is_dock_context(entry):
                                continue
                            sa = entry.get("SystemAddress")
                            if sa is None:
                                continue
                            try:
                                sa_int = int(sa)
                            except (TypeError, ValueError):
                                continue
                            ts = _journal_parse_timestamp(entry)
                            if ts is None:
                                ts = datetime.min.replace(tzinfo=timezone.utc)
                            candidates.append(
                                (ts, file_index, line_index, sa_int, entry.get("StarSystem"), entry.get("StarPos"))
                            )
                except OSError as e:
                    logger.debug("Error reading journal file %s: %s", journal_file, e)

            if not candidates:
                logger.debug("No Docked / Location(docked) with SystemAddress in journal scan")
                return None

            best = max(candidates, key=lambda c: (c[0], -c[1], c[2]))
            _, _, _, addr, star_system, star_pos = best
            logger.debug(
                "Using journal dock context SystemAddress=%s at %s (file_index=%s line=%s)",
                addr,
                best[0].isoformat(),
                best[1],
                best[2],
            )
            if star_system and not self.current_system:
                self.current_system = star_system
            if star_pos and not self.star_pos:
                self.star_pos = star_pos
            return addr

        except Exception as e:
            logger.error(
                "Exception in get_system_address_from_journal: %s: %s",
                type(e).__name__,
                e,
                exc_info=True,
            )
            return None

    def refresh_construction_depot_from_journal(self) -> bool:
        """
        Set ``construction_depot_data`` from the newest ``ColonisationConstructionDepot`` line
        in recent journal files. Does not run depot handler side effects (no API supply calls).

        Prefer rows whose ``MarketID`` matches ``current_market_id`` when that is set.
        """
        import glob

        journal_dir = _elite_journal_dir()
        if not journal_dir:
            logger.debug("refresh_construction_depot_from_journal: no journal directory")
            return False

        journal_files = glob.glob(os.path.join(journal_dir, "Journal.*.log"))
        if not journal_files:
            return False

        journal_files.sort(key=os.path.getmtime, reverse=True)
        files_to_check = journal_files[:5]
        candidates: List[tuple] = []

        for file_index, journal_file in enumerate(files_to_check):
            try:
                with open(journal_file, "r", encoding="utf-8") as f:
                    for line_index, line in enumerate(f):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if entry.get("event") != "ColonisationConstructionDepot":
                            continue
                        ts = _journal_parse_timestamp(entry)
                        if ts is None:
                            ts = datetime.min.replace(tzinfo=timezone.utc)
                        candidates.append((ts, file_index, line_index, entry))
            except OSError as e:
                logger.debug("refresh_construction_depot_from_journal: skip %s: %s", journal_file, e)

        if not candidates:
            logger.debug("refresh_construction_depot_from_journal: no ColonisationConstructionDepot lines found")
            return False

        target_mid = self.current_market_id
        if target_mid is not None:
            matched = [c for c in candidates if c[3].get("MarketID") == target_mid]
            if matched:
                candidates = matched

        best = max(candidates, key=lambda c: (c[0], -c[1], c[2]))
        entry = best[3]
        self.construction_depot_data = entry

        if entry.get("MarketID") and not self.current_market_id:
            self.current_market_id = entry.get("MarketID")
        if entry.get("SystemAddress") is not None and not self.current_system_address:
            try:
                self.current_system_address = int(entry["SystemAddress"])
            except (TypeError, ValueError):
                pass

        logger.info(
            "Loaded ColonisationConstructionDepot from journal (event time %s, marketId=%s)",
            best[0].isoformat(),
            entry.get("MarketID"),
        )
        return True

    @staticmethod
    def depot_remaining_need_map(entry: Dict[str, Any]) -> Dict[str, int]:
        """Per-commodity remaining need from a ColonisationConstructionDepot journal line (0 when satisfied)."""
        from .api.client import normalize_commodity_key

        needed: Dict[str, int] = {}
        for resource in entry.get("ResourcesRequired", []):
            commodity_name = normalize_commodity_key(resource.get("Name", ""))
            required = resource.get("RequiredAmount", 0)
            provided = resource.get("ProvidedAmount", 0)
            still_needed = max(0, required - provided)
            if commodity_name and required > 0:
                needed[commodity_name] = still_needed
        return needed

    def build_depot_project_fields(self, *, refresh: bool = True) -> Optional[Dict[str, Any]]:
        """
        Build commodity fields for ``PUT /api/project`` and ``PATCH`` depot sync from the
        ColonisationConstructionDepot journal snapshot.

        Returns ``None`` when no depot line exists or no required commodities could be read.
        """
        from .api.client import normalize_commodity_key

        if refresh:
            self.refresh_construction_depot_from_journal()

        entry = self.construction_depot_data
        if not entry:
            return None

        commodities: Dict[str, int] = {}
        supply_commodities: Dict[str, int] = {}
        max_need = 0
        resources = entry.get("ResourcesRequired", [])
        if not resources:
            logger.warning("ColonisationConstructionDepot snapshot has no ResourcesRequired list")

        for resource in resources:
            commodity_name = normalize_commodity_key(resource.get("Name", ""))
            required_amount = resource.get("RequiredAmount", 0)
            provided_amount = resource.get("ProvidedAmount", 0)

            if commodity_name and required_amount > 0:
                commodities[commodity_name] = commodities.get(commodity_name, 0) + required_amount
                max_need += required_amount

                remaining_need = max(0, required_amount - provided_amount)
                if remaining_need > 0:
                    supply_commodities[commodity_name] = (
                        supply_commodities.get(commodity_name, 0) + remaining_need
                    )

        if not commodities:
            return None

        return {
            "commodities": commodities,
            "maxNeed": max_need,
            "colonisationConstructionDepot": entry,
            "supply_commodities": supply_commodities,
            "remaining_need": self.depot_remaining_need_map(entry),
        }

    def build_depot_patch_payload(self, build_id: str, depot_fields: Dict[str, Any]) -> Dict[str, Any]:
        """``ProjectUpdate`` body for PATCH — depot snapshot is authoritative for need totals."""
        entry = depot_fields["colonisationConstructionDepot"]
        return {
            "buildId": build_id,
            "colonisationConstructionDepot": entry,
            "commodities": depot_fields.get("remaining_need") or self.depot_remaining_need_map(entry),
            "maxNeed": depot_fields["maxNeed"],
        }

    def remember_depot_remaining_need(
        self, remaining: Dict[str, int], *, depot_fields: Optional[Dict[str, Any]] = None
    ) -> None:
        """Store the full per-commodity remaining-need map for the next ``ColonisationConstructionDepot`` diff."""
        if depot_fields is not None:
            entry = depot_fields.get("colonisationConstructionDepot") or {}
            remaining = depot_fields.get("remaining_need") or self.depot_remaining_need_map(entry)
        self.last_depot_remaining_need = dict(remaining)

    def maybe_clear_phantom_commodities(
        self, build_id: str, project_view: Optional[Dict[str, Any]]
    ) -> None:
        """
        When a project payload already in hand has negative commodity values, PATCH them to ``0``.

        Does not perform any extra GET — only acts on responses the plugin already fetched or received.
        """
        from .api.client import phantom_commodity_zero_patch_map

        if not build_id or not project_view:
            return
        zero_map = phantom_commodity_zero_patch_map(project_view.get("commodities") or {})
        if not zero_map:
            return
        logger.info(
            "Clearing %d phantom commodity slot(s) on project %s: %s",
            len(zero_map),
            build_id,
            sorted(zero_map.keys()),
        )
        self.queue_api_call(
            self.api_client.patch_project_update,
            build_id,
            {"buildId": build_id, "commodities": zero_map},
        )

    def queue_initial_project_supply_update(
        self, build_id: str, depot_fields: Dict[str, Any]
    ) -> None:
        """
        Queue a depot PATCH after create/link when PUT did not already reflect live remaining need.

        On a fresh dock, PUT includes the same depot snapshot — skip the redundant PATCH.
        """
        if not build_id:
            return

        entry = depot_fields.get("colonisationConstructionDepot") or {}
        remaining = depot_fields.get("remaining_need") or self.depot_remaining_need_map(entry)
        put_commodities = depot_fields.get("commodities") or {}
        supply_commodities = depot_fields.get("supply_commodities") or {}

        if supply_commodities and supply_commodities == put_commodities:
            logger.info(
                "Project %s: skipping redundant depot PATCH — PUT already sent the depot snapshot",
                build_id,
            )
            self.remember_depot_remaining_need(remaining)
            return

        if supply_commodities:
            payload = self.build_depot_patch_payload(build_id, depot_fields)
            logger.info("Patching depot state for project %s after create/link", build_id)
            logger.debug("Depot PATCH commodities: %s", payload.get("commodities"))
            self.queue_api_call(self.patch_project_depot_state, build_id, payload, None)
        elif put_commodities:
            logger.info(
                "Project %s has no remaining supply needs — all commodities satisfied",
                build_id,
            )
            self.remember_depot_remaining_need(remaining)


def plugin_start3(plugin_dir: str) -> str:
    """
    Load the plugin.
    
    :param plugin_dir: The plugin directory
    :return: Plugin name
    """
    global this
    try:
        this = RavencolonialPlugin()
        capi_cache.init(plugin_dir)
        plugin_file_log.init_issue_log(plugin_dir, appname, plugin_name)
        this.configure_site_market_id_repair_visit_cache(plugin_dir)
        logger.info(f"RavenColonial_EDMC v{PluginConfig.VERSION} loaded")
        
        # Start background update check if enabled
        if PluginConfig.get_check_updates():
            logger.info("Starting update check in background thread...")
            
            def update_check_thread():
                """Background thread to check for updates"""
                try:
                    # Give UI time to initialize
                    time.sleep(2)
                    
                    # Check for updates
                    result = this.update_info.check()
                    
                    if result is None:
                        logger.warning("Could not check for updates")
                        return
                    
                    # Compare versions
                    if not this.update_info.is_current_version_outdated():
                        logger.info("Plugin is up to date")
                        return
                    
                    logger.info(f"Update available: {this.update_info.remote_version}")
                    this.update_available = True
                    
                    # If autoupdate is enabled, install automatically
                    if PluginConfig.get_autoupdate():
                        logger.info("Auto-update enabled, installing update...")
                        try:
                            this.update_info.run_autoupdate()
                            _notify_plugin_status_main_thread(
                                i18n.trf(
                                    "{plugin_name}: Update installed — restart EDMC to use v{version}",
                                    plugin_name=plugin_name,
                                    version=_strip_leading_v_for_display(this.update_info.remote_version),
                                )
                            )
                        except Exception as e:
                            logger.error(f"Auto-update failed: {e}", exc_info=True)
                            plug.show_error(
                                i18n.trf(
                                    "{plugin_name}: Auto-update failed. Check logs.",
                                    plugin_name=plugin_name,
                                )
                            )
                    else:
                        # Just notify user that update is available
                        logger.info("Update available but auto-update disabled")
                        # UI will show the update notification
                        
                except Exception as e:
                    logger.error(f"Update check thread error: {e}", exc_info=True)
            
            # Start update check in background
            Thread(
                target=update_check_thread,
                daemon=True,
                name="ravencolonial-update-check"
            ).start()
        else:
            logger.info("Update checking disabled in settings")
        
        return plugin_name
    except Exception as e:
        logger.error(f"Failed to initialize: {e}", exc_info=True)
        raise


def plugin_stop() -> None:
    """
    Unload the plugin.
    """
    global this
    capi_cache.stop()
    plugin_file_log.stop_issue_log()
    if this and getattr(this, "build_overlay", None):
        try:
            this.build_overlay.clear()
        except Exception as e:
            logger.debug("Build overlay clear on stop failed: %s", e)
    if this:
        # Signal worker thread to stop
        if this.worker_thread and this.worker_thread.is_alive():
            this.api_queue.put(None)
        # Wait for worker thread to finish (recommended by EDMC docs)
        if this.worker_thread and this.worker_thread.is_alive():
            this.worker_thread.join(timeout=5)  # 5 second timeout to avoid hanging
        logger.info(f"{PluginConfig.NAME} stopped")


def check_github_version() -> Optional[str]:
    """
    Check GitHub for the latest release version.
    
    :return: Latest version string or None if check fails
    """
    try:
        # Same rules as auto-update: only strict vX.Y.Z tags with a zip (ignore dev-shaped tags).
        latest_version = version_check.latest_stable_release_version_string(logger)
        if latest_version:
            logger.debug(f"Latest stable GitHub version: {latest_version}")
        return latest_version
    except Exception as e:
        logger.debug(f"Failed to check GitHub version: {e}")
        return None


def _persist_ravencolonial_prefs_from_frame(frame: nb.Frame, cmdr: Optional[str]) -> None:
    """Write Ravencolonial plugin preference widgets to EDMC config and refresh runtime state."""
    global this
    config.set('ravencolonial_api_key', frame.api_key_var.get())
    config.set('ravencolonial_stealth_mode', frame.stealth_var.get())
    config.set('ravencolonial_stealth_ship_cargo', frame.stealth_ship_cargo_var.get())
    config.set('ravencolonial_stealth_construction_reporting', frame.stealth_construction_var.get())
    _theme_pick = frame.overlay_theme_combo.get()
    _theme_tid = frame._theme_display_to_id.get(_theme_pick, frame.overlay_theme_var.get())
    config.set('ravencolonial_overlay_theme', _theme_tid)
    frame.overlay_theme_var.set(_theme_tid)
    PluginConfig.set_check_updates(frame.check_updates_var.get())
    PluginConfig.set_autoupdate(frame.autoupdate_var.get())
    PluginConfig.set_check_prerelease(frame.prerelease_var.get())
    effective_cmdr = (cmdr or '') or (this.cmdr_name if this else '') or ''
    if this and frame.api_key_var.get() and effective_cmdr:
        this.api_client.set_credentials(effective_cmdr, frame.api_key_var.get())
    if this and hasattr(this, 'fc_handler'):
        this.fc_handler.set_stealth_mode(frame.stealth_var.get())
    if this and hasattr(this, 'update_info'):
        this.update_info._beta = frame.prerelease_var.get()
    if this:
        this.overlay_theme_id = _theme_tid
        if getattr(this, "build_overlay", None):
            this.build_overlay.refresh(force=True)


def plugin_prefs(parent: nb.Notebook, cmdr: Optional[str], is_beta: bool) -> nb.Frame:
    """
    Create settings page for the plugin.
    
    :param parent: The notebook parent
    :param cmdr: Commander name
    :param is_beta: Whether in beta
    :return: Settings frame
    """
    global this
    from .overlay.themes import DEFAULT_OVERLAY_THEME_ID, overlay_theme_choices

    logger.info("Creating plugin preferences page")
    
    # Create a frame for the settings (use nb.Frame as EDMC expects)
    frame = nb.Frame(parent)

    # Use nb.Label / nb.Checkbutton / nb.Button like prefs.py — matches notebook page
    # (SystemWindow / nb.T* styles). Do not apply plugin theme.update here; that paints
    # main-window dark theme and fights the Settings dialog appearance.

    # Title
    title_label = nb.Label(frame, text=i18n.tr("Ravencolonial Plugin Settings"), font=('TkDefaultFont', 12, 'bold'))
    title_label.grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 20))

    # API Key setting
    api_key_label = nb.Label(frame, text=i18n.tr("Ravencolonial API Key:"))
    api_key_label.grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)
    
    try:
        api_key_value = config.get_str('ravencolonial_api_key') or ''
    except Exception:
        api_key_value = ''
    
    # Store as frame attribute to prevent garbage collection
    frame.api_key_var = tk.StringVar(value=api_key_value)
    frame.api_key_entry = ttk.Entry(frame, textvariable=frame.api_key_var, width=40, show="*")
    frame.api_key_entry.grid(row=1, column=1, sticky=tk.W, padx=10, pady=5)

    frame.show_api_key_var = tk.BooleanVar(value=False)

    def _on_toggle_show_api_key() -> None:
        frame.api_key_entry.config(show="" if frame.show_api_key_var.get() else "*")

    show_api_key_check = nb.Checkbutton(
        frame,
        text=i18n.tr("Show API Key"),
        variable=frame.show_api_key_var,
        command=_on_toggle_show_api_key,
    )
    show_api_key_check.grid(row=2, column=1, sticky=tk.W, padx=10, pady=(0, 2))

    # API Key help text
    api_key_help = nb.Label(frame, text=i18n.tr("Get your API key from Ravencolonial account settings"))
    api_key_help.grid(row=3, column=1, sticky=tk.W, padx=10, pady=(0, 10))
    
    # Stealth: Fleet Carrier only
    try:
        stealth_value = config.get_bool('ravencolonial_stealth_mode')
    except Exception:
        stealth_value = False
    
    # Store as frame attribute to prevent garbage collection
    frame.stealth_var = tk.BooleanVar(value=stealth_value)
    stealth_check = nb.Checkbutton(
        frame, text=i18n.tr("Stealth: Fleet Carrier data"), variable=frame.stealth_var
    )
    stealth_check.grid(row=4, column=0, columnspan=2, sticky=tk.W, padx=10, pady=5)

    stealth_help = nb.Label(
        frame,
        text=i18n.tr("When enabled, stops Fleet Carrier commodity and CAPI cargo sync to Ravencolonial"),
    )
    stealth_help.grid(row=5, column=1, sticky=tk.W, padx=10, pady=(0, 5))

    # Stealth: commander ship hold (POST /api/cmdr/currentShip)
    try:
        stealth_ship = config.get_bool('ravencolonial_stealth_ship_cargo')
    except Exception:
        stealth_ship = False
    frame.stealth_ship_cargo_var = tk.BooleanVar(value=stealth_ship)
    stealth_ship_check = nb.Checkbutton(
        frame, text=i18n.tr("Stealth: commander ship cargo"), variable=frame.stealth_ship_cargo_var
    )
    stealth_ship_check.grid(row=6, column=0, columnspan=2, sticky=tk.W, padx=10, pady=5)
    stealth_ship_help = nb.Label(
        frame,
        text=i18n.tr("When enabled, does not send your ship cargo hold or loadout snapshot to Ravencolonial"),
    )
    stealth_ship_help.grid(row=7, column=1, sticky=tk.W, padx=10, pady=(0, 5))

    # Stealth: construction delivery / depot journal reporting
    try:
        stealth_construction = config.get_bool('ravencolonial_stealth_construction_reporting')
    except Exception:
        stealth_construction = False
    frame.stealth_construction_var = tk.BooleanVar(value=stealth_construction)
    stealth_construction_check = nb.Checkbutton(
        frame,
        text=i18n.tr("Stealth: all construction delivery reporting"),
        variable=frame.stealth_construction_var,
    )
    stealth_construction_check.grid(row=8, column=0, columnspan=2, sticky=tk.W, padx=10, pady=5)
    stealth_construction_help = nb.Label(
        frame,
        text=i18n.tr(
            "When enabled, does not send colonization depot progress, contribution totals, "
            "or CargoDepot deliveries to Ravencolonial (journal-driven construction sync only)"
        ),
    )
    stealth_construction_help.grid(row=9, column=1, sticky=tk.W, padx=10, pady=(0, 10))
    
    # Update Settings Section
    update_section_label = nb.Label(frame, text=i18n.tr("Update Settings:"), font=('TkDefaultFont', 10, 'bold'))
    update_section_label.grid(row=10, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 5))

    # Check for updates checkbox - store as frame attribute
    frame.check_updates_var = tk.BooleanVar(value=PluginConfig.get_check_updates())
    check_updates_check = nb.Checkbutton(frame, text=i18n.tr("Check for updates on startup"), variable=frame.check_updates_var)
    check_updates_check.grid(row=11, column=0, columnspan=2, sticky=tk.W, padx=10, pady=2)

    # Auto-update checkbox - store as frame attribute
    frame.autoupdate_var = tk.BooleanVar(value=PluginConfig.get_autoupdate())
    autoupdate_check = nb.Checkbutton(frame, text=i18n.tr("Automatically install updates"), variable=frame.autoupdate_var)
    autoupdate_check.grid(row=12, column=0, columnspan=2, sticky=tk.W, padx=10, pady=2)

    # Check pre-releases checkbox - store as frame attribute
    frame.prerelease_var = tk.BooleanVar(value=PluginConfig.get_check_prerelease())
    prerelease_check = nb.Checkbutton(frame, text=i18n.tr("Include pre-release versions"), variable=frame.prerelease_var)
    prerelease_check.grid(row=13, column=0, columnspan=2, sticky=tk.W, padx=10, pady=2)

    # Update settings help text
    update_help = nb.Label(frame, text=i18n.tr("Auto-update requires EDMC restart to apply. Use cautiously."))
    update_help.grid(row=14, column=1, sticky=tk.W, padx=10, pady=(0, 10))
    
    # Version number with update check
    # Store as frame attributes to prevent garbage collection
    frame.version_text = tk.StringVar(
        value=i18n.trf("Version: {version} (checking for updates...)", version=plugin_version)
    )
    frame.version_label = nb.Label(frame, textvariable=frame.version_text)
    frame.version_label.grid(row=15, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 5))
    
    def check_for_updates():
        """Check GitHub for updates in background thread"""
        try:
            latest = check_github_version()
            
            # Check if frame still exists before updating
            if not frame.winfo_exists():
                logger.debug("Settings frame no longer exists, skipping version update")
                return
            
            if latest:
                logger.debug(f"Comparing versions: current={plugin_version}, latest={latest}")
                if version_check.compare_versions(plugin_version, latest, logger):
                    # Update available
                    frame.version_text.set(
                        i18n.trf(
                            "Version: {version} (Update available: {latest})",
                            version=plugin_version,
                            latest=latest,
                        )
                    )
                    logger.info(f"Update available: {latest} (current: {plugin_version})")
                else:
                    # Up to date
                    frame.version_text.set(
                        i18n.trf("Version: {version} (up to date)", version=plugin_version)
                    )
                    logger.debug(f"Plugin is up to date: {plugin_version}")
            else:
                # Check failed, just show version
                logger.debug("GitHub version check returned None, showing version only")
                frame.version_text.set(i18n.trf("Version: {version}", version=plugin_version))
        except tk.TclError as e:
            logger.debug(f"Frame destroyed before update could be displayed: {e}")
        except Exception as e:
            logger.warning(f"Error checking for updates: {e}", exc_info=True)
            # Always show version even if check fails
            try:
                if frame.winfo_exists():
                    frame.version_text.set(i18n.trf("Version: {version}", version=plugin_version))
            except Exception as e2:
                logger.error(f"Failed to set version text: {e2}", exc_info=True)
    
    # Start version check in background thread
    frame.update_check_thread = Thread(target=check_for_updates, daemon=True)
    frame.update_check_thread.start()
    
    # GitHub link — match notebook page bg (HyperlinkLabel defaults to blue on light page)
    github_url = f"https://github.com/{version_check.GITHUB_REPO}"
    if HyperlinkLabel is not None:
        _page_bg = "SystemWindow" if sys.platform == "win32" else ttk.Style().lookup("TLabel", "background")
        github_link = HyperlinkLabel(
            frame,
            text=github_url,
            url=github_url,
            underline=True,
            background=_page_bg,
            foreground="blue",
        )
    else:
        github_link = nb.Label(frame, text=github_url)
        github_link['cursor'] = 'hand2'

        def open_github_fallback(_event: tk.Event) -> None:
            webbrowser.open(github_url)

        github_link.bind('<Button-1>', open_github_fallback)
    github_link.grid(row=16, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 10))


    overlay_theme_label = nb.Label(
        frame,
        text=i18n.tr("Overlay Theme:"),
        font=("TkDefaultFont", 10, "bold"),
    )
    overlay_theme_label.grid(row=17, column=0, sticky=tk.W, padx=10, pady=(8, 2))

    try:
        _saved_theme = config.get_str("ravencolonial_overlay_theme") or DEFAULT_OVERLAY_THEME_ID
    except Exception:
        _saved_theme = DEFAULT_OVERLAY_THEME_ID
    _theme_labels = [label for _tid, label in overlay_theme_choices()]
    _theme_ids = [tid for tid, _label in overlay_theme_choices()]
    if _saved_theme not in _theme_ids:
        _saved_theme = DEFAULT_OVERLAY_THEME_ID
    frame.overlay_theme_var = tk.StringVar(value=_saved_theme)
    overlay_theme_combo = ttk.Combobox(
        frame,
        textvariable=frame.overlay_theme_var,
        values=_theme_labels,
        state="readonly",
        width=28,
    )
    _theme_display_to_id = {label: tid for tid, label in overlay_theme_choices()}
    _theme_id_to_display = {tid: label for tid, label in overlay_theme_choices()}
    overlay_theme_combo.set(_theme_id_to_display.get(_saved_theme, _theme_labels[0]))

    def _on_overlay_theme_selected(_event: object = None) -> None:
        display = overlay_theme_combo.get()
        tid = _theme_display_to_id.get(display, DEFAULT_OVERLAY_THEME_ID)
        frame.overlay_theme_var.set(tid)

    overlay_theme_combo.bind("<<ComboboxSelected>>", _on_overlay_theme_selected)
    frame.overlay_theme_combo = overlay_theme_combo
    frame._theme_display_to_id = _theme_display_to_id
    overlay_theme_combo.grid(row=17, column=1, sticky=tk.W, padx=10, pady=(8, 2))

    overlay_theme_help = nb.Label(
        frame,
        text=i18n.tr(
            "Colors the in-game overlay: build name and trip lines, system name, commodity names, and numeric columns."
        ),
    )
    overlay_theme_help.grid(row=18, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 8))

    overlay_dep_label = nb.Label(
        frame,
        text=i18n.tr("Overlay dependency:"),
        font=("TkDefaultFont", 10, "bold"),
    )
    overlay_dep_label.grid(row=20, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(4, 5))

    overlay_dep_help = nb.Label(
        frame,
        text=i18n.tr(
            "The build tracker overlay requires EDMC Modern Overlay to be installed and enabled in EDMC."
        ),
    )
    overlay_dep_help.grid(row=21, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 4))

    modern_overlay_url = "https://github.com/SweetJonnySauce/EDMCModernOverlay"
    if HyperlinkLabel is not None:
        overlay_dep_link = HyperlinkLabel(
            frame,
            text=modern_overlay_url,
            url=modern_overlay_url,
            underline=True,
            background=_page_bg,
            foreground="blue",
        )
    else:
        overlay_dep_link = nb.Label(frame, text=modern_overlay_url)
        overlay_dep_link["cursor"] = "hand2"

        def open_modern_overlay_repo(_event: tk.Event) -> None:
            webbrowser.open(modern_overlay_url)

        overlay_dep_link.bind("<Button-1>", open_modern_overlay_repo)
    overlay_dep_link.grid(row=22, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 6))

    overlay_font_hint = nb.Label(
        frame,
        text=i18n.tr("Click here to install custom fonts."),
    )
    overlay_font_hint.grid(row=23, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 4))

    _prefs_plugin_dir = os.path.dirname(os.path.abspath(__file__))

    def _install_overlay_fonts() -> None:
        from .overlay.font_setup import retry_install_oxanium_font

        ok, msg = retry_install_oxanium_font(_prefs_plugin_dir)
        body = i18n.tr(msg) if msg and not msg.startswith("Font install failed") else (
            i18n.trf("Font install failed: {error}", error=msg) if msg else ""
        )
        if ok:
            messagebox.showinfo(i18n.tr("Overlay fonts"), body, parent=frame)
        else:
            messagebox.showerror(i18n.tr("Overlay fonts"), body, parent=frame)

    overlay_font_button = nb.Button(
        frame,
        text=i18n.tr("Install overlay fonts"),
        command=_install_overlay_fonts,
    )
    overlay_font_button.grid(row=24, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 10))

    # Save button (explicit save; prefs_changed also persists when the main Settings dialog OK is used)
    def save_settings():
        """Save the settings to EDMC config"""
        _persist_ravencolonial_prefs_from_frame(frame, cmdr)

    save_button = nb.Button(frame, text=i18n.tr("Save Settings"), command=save_settings)
    save_button.grid(row=25, column=0, columnspan=2, pady=20)

    if this:
        this._prefs_frame = frame

    logger.info("Plugin preferences page created successfully")
    return frame


def prefs_changed(cmdr: Optional[str], is_beta: bool) -> None:
    """
    Called when the EDMC settings dialog is dismissed with OK.
    Persist widget values before EDMC destroys the prefs tab (see PLUGINS.md).
    """
    global this
    if this:
        prefs_frame = getattr(this, '_prefs_frame', None)
        if prefs_frame is not None:
            try:
                if prefs_frame.winfo_exists():
                    _persist_ravencolonial_prefs_from_frame(prefs_frame, cmdr)
            except tk.TclError:
                logger.debug('Plugin prefs frame unavailable during prefs_changed')
            finally:
                this._prefs_frame = None
        if getattr(this, 'ui_manager', None):
            this.ui_manager.refresh_localized_text()
        this.update_create_button()


def plugin_app(parent: tk.Frame) -> tk.Widget:
    """
    Create a frame for the main EDMC window.
    
    :param parent: The parent frame
    :return: Plugin root frame (``tk.Frame`` themed via ``theme.update`` like GalaxyGPS).
    """
    global this

    if not this:
        return tk.Frame(parent, highlightthickness=0, borderwidth=0)
    
    # Use the UI manager to create the plugin frame
    frame = this.ui_manager.create_plugin_frame(parent)
    
    return frame


def _cargo_from_journal_inventory(inventory: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for item in inventory or []:
        name = str(item.get("Name", "")).replace("_name", "")
        nk = normalize_commodity_key(name)
        if nk:
            out[nk] = int(item.get("Count", 0))
    return out


def _cargo_from_edmc_state(state: Optional[Dict[str, Any]]) -> Dict[str, int]:
    if not state:
        return {}
    raw = state.get("Cargo")
    if not raw:
        return {}
    out: Dict[str, int] = {}
    try:
        for k, v in raw.items():
            nk = normalize_commodity_key(str(k))
            if nk:
                out[nk] = out.get(nk, 0) + int(v)
    except (TypeError, ValueError, AttributeError):
        pass
    return out


def _cargo_count_diff(old: Dict[str, int], new: Dict[str, int]) -> Dict[str, int]:
    diff: Dict[str, int] = {}
    for k in set(old) | set(new):
        d = new.get(k, 0) - old.get(k, 0)
        if d:
            diff[k] = d
    return diff


def _apply_market_trade_to_cargo(
    cargo: Dict[str, int],
    entry: Dict[str, Any],
    *,
    is_buy: bool,
) -> Dict[str, int]:
    """Merge a station MarketBuy/MarketSell row into a normalized commodity hold map."""
    commodity = normalize_commodity_key(entry.get("Type") or "")
    try:
        count = int(entry.get("Count", 0) or 0)
    except (TypeError, ValueError):
        return dict(cargo or {})
    if not commodity or count <= 0:
        return dict(cargo or {})

    out = dict(cargo or {})
    if is_buy:
        out[commodity] = out.get(commodity, 0) + count
    else:
        remaining = out.get(commodity, 0) - count
        if remaining <= 0:
            out.pop(commodity, None)
        else:
            out[commodity] = remaining
    return out


def journal_entry(
    cmdr: str, is_beta: bool, system: str, station: str, entry: Dict[str, Any], state: Dict[str, Any]
) -> Optional[str]:
    """
    Handle journal entry events.
    
    :param cmdr: Commander name
    :param is_beta: Whether in beta
    :param system: Current system
    :param station: Current station
    :param entry: The journal entry
    :param state: Current game state
    :return: Optional status message
    """
    global this
    
    if not this:
        return None
    
    # Update commander and location
    this.cmdr_name = cmdr
    this.current_system = system
    this.current_station = station
    if state is not None:
        try:
            this._last_edmc_state = dict(state)
        except Exception:
            this._last_edmc_state = state  # fallback if not a plain mapping
        this._refresh_ship_from_state(state)
        # EDMC monitor state: keep id64 current (e.g. after Undocked) for plan-site API
        sa = state.get("SystemAddress")
        if sa is not None:
            try:
                this.current_system_address = int(sa)
            except (TypeError, ValueError):
                pass

    this.ensure_cmdr_snapshot_once()
    this.refresh_plan_sites_ui()

    logger.debug(f"Journal entry - cmdr: {cmdr}, system: {system}, station: {station}")
    
    # Initialize Fleet Carrier handler on first commander event
    logger.debug(f"FC init check: cmdr={cmdr}, has_initialized={hasattr(this.fc_handler, '_initialized')}")
    if cmdr and not hasattr(this.fc_handler, '_initialized'):
        logger.info(f"Initializing Fleet Carrier handler for {cmdr}")
        # Set API client credentials for Fleet Carrier operations
        api_key = config.get_str('ravencolonial_api_key') or ''
        logger.debug(f"API key present: {bool(api_key)}")
        if api_key:
            this.api_client.set_credentials(cmdr, api_key)
            logger.debug("API credentials set")
        
        this.fc_handler.initialize_fcs(cmdr)
        
        # Initialize current station state from game state (in case already docked when EDMC starts)
        if state:
            station_type = state.get('StationType')
            market_id = state.get('MarketID')
            if station_type and market_id:
                this.fc_handler.current_station_type = station_type
                this.fc_handler.current_market_id = market_id
                logger.info(f"Initialized FC handler with current station: {station_type}, marketID: {market_id}")
        
        this.fc_handler._initialized = True
        logger.info("Fleet Carrier handler initialization complete")
    
    event = entry.get('event')
    
    # Handle different events
    if event == 'Docked':
        logger.info(f"Docked at {station}, MarketID: {entry.get('MarketID')}")
        this.current_market_id = entry.get('MarketID')
        this.current_system_address = entry.get('SystemAddress')
        this.star_pos = entry.get('StarPos')
        if entry.get('BodyID') is not None:
            this.body_num = entry.get('BodyID')
        if entry.get('Body') is not None:
            this.body_name = entry.get('Body')
        this.station_type = entry.get('StationType')
        this.faction_name = entry.get('StationFaction', {}).get('Name')
        this.is_docked = True
        # Check if this is a colonization ship - they appear as SurfaceStation but have ColonisationShip in the name
        station_name = entry.get('StationName', '')
        this.is_construction_ship = 'ColonisationShip' in station_name
        logger.debug(f"Docked details - StationType: {this.station_type}, is_construction_ship: {this.is_construction_ship}")
        
        # Handle Fleet Carrier docking
        docked_fc = this.fc_handler.handle_docked_event(entry)
        if this.is_construction_ship:
            this._track_all_refresh_on_qualifying_undock = True
        elif docked_fc:
            this._track_all_refresh_on_qualifying_undock = True
        
        this.update_status(i18n.trf("Docked at {station}", station=station))
        this.maybe_queue_site_market_id_repair(entry)
        this.update_create_button()
        
    elif event == 'CarrierStats' and this.fc_handler:
        # Optional direct resilience: some users may have CarrierStats routed to journal_entry.
        try:
            this.fc_handler.update_fc_capacity_from_journal_stats(entry)
        except Exception:
            logger.debug("journal CarrierStats capacity cache skipped", exc_info=True)

    elif event == 'Undocked':
        # EDMC passes station=None here: monitor clears state['StationName'] before notify_journal_entry.
        # The journal line still carries the facility you left.
        left_station = entry.get('StationName') or station or i18n.tr("Unknown")
        logger.info(f"Undocked from {left_station}")
        this.is_docked = False
        this.is_construction_ship = False
        this.current_market_id = None
        this._bodies_fetched = False  # Reset flag for next docking
        this.last_depot_remaining_need = {}
        this.invalidate_project_location_cache()
        this._last_depot_patch_payload_sig = None
        this.fc_handler.clear_dock_context()
        this.update_status(i18n.trf("Undocked from {station}", station=left_station))
        this.update_create_button()
        if getattr(this, "_track_all_refresh_on_qualifying_undock", False):
            this._track_all_refresh_on_qualifying_undock = False
            this.refresh_track_all_projects_if_selected("qualifying undock")
        
    elif event == 'Location':
        logger.info(f"Location event - system: {system}, station: {station}")
        this.current_system_address = entry.get('SystemAddress')
        this.star_pos = entry.get('StarPos')
        if entry.get('Docked'):
            this.current_market_id = entry.get('MarketID')
            if entry.get('BodyID') is not None:
                this.body_num = entry.get('BodyID')
            if entry.get('Body') is not None:
                this.body_name = entry.get('Body')
            this.station_type = entry.get('StationType')
            this.is_docked = True
            # Check if this is a colonization ship - they appear as SurfaceStation but have ColonisationShip in the name
            station_name = entry.get('StationName', '')
            this.is_construction_ship = 'ColonisationShip' in station_name
            logger.info(f"Location event - docked at {station}, StationType: {this.station_type}, StationName: {station_name}, is_construction_ship: {this.is_construction_ship}")
            docked_fc = this.fc_handler.handle_docked_event(entry)
            if this.is_construction_ship:
                this._track_all_refresh_on_qualifying_undock = True
            elif docked_fc:
                this._track_all_refresh_on_qualifying_undock = True
            this.maybe_queue_site_market_id_repair(entry)
            this.update_create_button()
        else:
            this.is_docked = False
            this.is_construction_ship = False
            this.current_market_id = None
            this.invalidate_project_location_cache()
            this._last_depot_patch_payload_sig = None
            this.fc_handler.clear_dock_context()
            this.update_create_button()
            
    elif event == 'CargoDepot':
        if _stealth_construction_reporting():
            logger.debug("Construction reporting stealth: skipping CargoDepot API handling")
        else:
            this.handle_cargo_depot(entry)
        
    elif event == 'Market':
        this.handle_market(entry)
        # Handle Fleet Carrier market updates
        # Disabled for now - MarketBuy/MarketSell events handle commodity updates
        # this.fc_handler.handle_market_event(entry)
        
    elif event == 'MarketBuy':
        if not this.fc_handler.handle_marketbuy_event(entry):
            this._handle_commander_market_trade(entry, is_buy=True, state=state)
        
    elif event == 'MarketSell':
        logger.debug(f"MarketSell event received: {entry}")
        if not this.fc_handler.handle_marketsell_event(entry):
            this._handle_commander_market_trade(entry, is_buy=False, state=state)
        
    elif event == 'CargoTransfer':
        # Handle Fleet Carrier cargo transfers
        logger.debug(f"CargoTransfer event received: {entry}")
        result = this.fc_handler.handle_cargotransfer_event(entry, state)
        logger.debug(f"CargoTransfer handler returned: {result}")
        
    elif event == 'Cargo':
        # Commander cargo: full snapshot vs forced re-read (SrvSurvey / squadron FC parity)
        inv = entry.get("Inventory")
        count = int(entry.get("Count", 0) or 0)
        has_full_snapshot = count > 0 and inv and len(inv) > 0

        if has_full_snapshot:
            this.cargo = {item["Name"].replace("_name", ""): item["Count"] for item in inv}
            this.fc_handler.note_commander_full_cargo_snapshot()
        else:
            new_norm = _cargo_from_edmc_state(state)
            if this.fc_handler.consume_skip_next_cargo_event():
                logger.debug("Squadron FC: consumed skip-next-Cargo flag after Market trade")
            elif (
                this.fc_handler.is_docked_linked_squadron_fc()
                and not this.fc_handler.stealth_mode
                and this.fc_handler.squadron_cmdr_cargo_baseline_ready
            ):
                old_norm: Dict[str, int] = {}
                for k, v in (this.cargo or {}).items():
                    nk = normalize_commodity_key(str(k))
                    if nk:
                        try:
                            old_norm[nk] = old_norm.get(nk, 0) + int(v)
                        except (TypeError, ValueError):
                            pass
                diff_cmdr = _cargo_count_diff(old_norm, new_norm)
                if diff_cmdr:
                    diff_fc = {k: -v for k, v in diff_cmdr.items()}
                    this.fc_handler.handle_squadron_cargo_resync_diff(diff_fc)
            if count == 0:
                this.cargo = dict(new_norm) if new_norm else {}
            elif new_norm:
                this.cargo = dict(new_norm)
            elif count > 0:
                logger.debug(
                    "Sparse Cargo (Count=%s) without Inventory or EDMC breakdown — keeping plugin hold",
                    count,
                )
        this._queue_publish_current_ship(state, "Cargo")
        this.refresh_build_overlay()

    elif event == 'Loadout':
        ship_raw = str(entry.get('Ship', '')).lower()
        if 'fighter' not in ship_raw and 'buggy' not in ship_raw:
            this._refresh_ship_from_loadout_entry(entry)
            if state is not None:
                this._refresh_ship_from_state(state)
            this._queue_publish_current_ship(state, "Loadout")
            this.refresh_build_overlay()

    elif event == 'SetUserShipName':
        if entry.get('UserShipName') and str(entry.get('UserShipName')).strip() not in ('', ' '):
            this.ship_display_name = str(entry['UserShipName']).strip()
        if 'UserShipId' in entry:
            uid = entry.get('UserShipId')
            this.ship_ident = str(uid).strip() if uid else None
        this._queue_publish_current_ship(state, "SetUserShipName")

    elif event == 'ColonisationConstructionDepot':
        logger.debug("ColonisationConstructionDepot event received")
        if _stealth_construction_reporting():
            logger.debug("Construction reporting stealth: not processing colonization depot")
        else:
            this.handle_colonisation_construction_depot(entry)
    
    elif event == 'ColonisationContribution':
        logger.debug("ColonisationContribution event received")
        if _stealth_construction_reporting():
            logger.debug("Construction reporting stealth: not processing colonization contribution")
        else:
            this.handle_colonisation_contribution(entry)
    
    return None


def cmdr_data(data: CAPIData, is_beta: bool) -> Optional[str]:
    """
    EDMC hook: fresh ``/profile`` bundle (plus ``marketdata`` / ``shipdata`` when present).
    Cached to ``<plugin>/capi_cache/`` for analysis; no gameplay side effects.
    """
    try:
        capi_cache.write("cmdr_data", data, is_beta)
    except Exception as e:
        logger.debug("CAPI cmdr_data cache skipped: %s", e)
    if this:
        this.maybe_queue_squadron_cache_refresh(
            trigger="cmdr_data",
            is_beta=is_beta,
            source_host=getattr(data, "source_host", None),
            request_cmdr=getattr(data, "request_cmdr", None),
        )
    return None


def cmdr_data_legacy(data: CAPIData, is_beta: bool) -> Optional[str]:
    """EDMC hook: Legacy-galaxy CAPI profile bundle — same cache treatment as ``cmdr_data``."""
    try:
        capi_cache.write("cmdr_data_legacy", data, is_beta)
    except Exception as e:
        logger.debug("CAPI cmdr_data_legacy cache skipped: %s", e)
    if this:
        this.maybe_queue_squadron_cache_refresh(
            trigger="cmdr_data_legacy",
            is_beta=is_beta,
            source_host=getattr(data, "source_host", None),
            request_cmdr=getattr(data, "request_cmdr", None),
        )
    return None


def capi_fleetcarrier(data: CAPIData) -> Optional[str]:
    """
    Handle Fleet Carrier CAPI data from Frontier.
    Called when EDMC fetches fresh FC data after CarrierStats journal events.
    
    :param data: CAPIData object with FC information
    :return: Optional status message
    """
    global this

    try:
        capi_cache.write("fleetcarrier", data, None)
    except Exception as e:
        logger.debug("CAPI fleetcarrier cache skipped: %s", e)
    if this:
        this.maybe_queue_squadron_cache_refresh(
            trigger="capi_fleetcarrier",
            is_beta=None,
            source_host=getattr(data, "source_host", None),
            request_cmdr=getattr(data, "request_cmdr", None),
        )

    if not this or not this.fc_handler:
        return None
    
    try:
        # Extract FC callsign and market ID
        if 'name' not in data or 'callsign' not in data['name']:
            logger.warning("CAPI FC data missing name/callsign")
            return None
        
        callsign = data['name']['callsign']
        logger.info(f"Received CAPI data for Fleet Carrier: {callsign}")
        
        # Look up the market ID using the callsign from CAPI data
        # This ensures we update the correct FC even if the player is docked at a different one
        market_id = this.fc_handler.get_market_id_by_callsign(callsign)
        if not market_id:
            logger.warning(f"Cannot find market ID for FC callsign {callsign} - FC may not be linked")
            return None
        
        logger.info(f"Matched CAPI callsign {callsign} to marketId {market_id}")
        
        # Cache owner-visible capacity (freeSpace) from CAPI for local overlay use when
        # the player selects this carrier in the dropdown (local only, never sent to server).
        if this.fc_handler:
            try:
                this.fc_handler.update_fc_capacity_from_capi(market_id, data)
            except Exception:
                logger.debug("owner capacity cache from CAPI skipped", exc_info=True)
            # Real-time HUD update: if the user currently has a specific carrier (not "All")
            # selected in the dropdown for a non-aggregate project, and this CAPI marketId matches,
            # poke the overlay so the new "> CALLSIGN Capacity: X/Y" line appears/ updates right away.
            try:
                if getattr(this, "overlay_carrier_tracking_enabled", False):
                    sel = str(getattr(this, "overlay_fc_selection", "all") or "all").strip().lower()
                    if sel not in ("all", ""):
                        try:
                            if int(sel) == int(market_id):
                                # Only refresh when not in Track All aggregate (build id guard is inside compose as well).
                                this.refresh_build_overlay()
                        except Exception:
                            pass
            except Exception:
                pass
        
        # Check stealth mode
        if this.fc_handler.stealth_mode:
            logger.info(f"Stealth mode enabled - ignoring CAPI data for FC {callsign}")
            return None
        
        # Extract cargo data from CAPI
        cargo_list = data.get('cargo', [])
        if not cargo_list:
            logger.info(f"No cargo data in CAPI response for FC {callsign}")
            return None
        
        # Convert CAPI cargo format to our format
        # CAPI format: [{"commodity": "name", "qty": 1, "value": X, ...}, ...]
        # Our format: {"commodity": total_quantity, ...}
        cargo_totals = {}
        for item in cargo_list:
            commodity = normalize_commodity_key(item.get('commodity', ''))
            qty = item.get('qty', 0)
            if commodity:
                cargo_totals[commodity] = cargo_totals.get(commodity, 0) + qty
        
        logger.info(f"CAPI FC cargo for {callsign}: {len(cargo_totals)} commodity types, {sum(cargo_totals.values())} total units")
        logger.debug(f"CAPI cargo details: {cargo_totals}")
        
        # Update FC cargo on server
        this.fc_handler.update_fc_cargo_from_capi(market_id, cargo_totals)
        
    except Exception as e:
        logger.error(f"Error processing CAPI FC data: {e}", exc_info=True)
    
    return None


def open_url(url: str):
    """Open URL in browser"""
    webbrowser.open(url)


def open_project_link():
    """Open the existing project in browser"""
    global this
    if this and this.current_build_id:
        url = f"https://ravencolonial.com/#build={this.current_build_id}"
        logger.info(f"Opening project page: {url}")
        open_url(url)


def open_create_dialog(parent):
    """Open the Create Project dialog"""
    global this
    if this:
        try:
            dialog = create_project_dialog.CreateProjectDialog(parent, this)
        except Exception as e:
            logger.error(f"Failed to open create dialog: {e}", exc_info=True)
            messagebox.showerror(
                i18n.tr("Error"),
                i18n.trf("Failed to open dialog: {detail}", detail=str(e)),
            )
