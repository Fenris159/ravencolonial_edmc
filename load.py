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
from typing import Optional, Dict, Any, List, Union, Tuple, Deque, Callable
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
import zipfile
from pathlib import Path

try:
    from ttkHyperlinkLabel import HyperlinkLabel
except ImportError:  # pragma: no cover - only when running outside EDMC
    HyperlinkLabel = None  # type: ignore[misc, assignment]

from . import create_project_dialog
from . import construction_completion
from . import edmc_compat
from . import i18n
from . import fleet_carrier_handler
from . import version_check
from . import capi_cache
from . import plugin_file_log
from .api import RavencolonialAPIClient
from .api.client import normalize_commodity_key, _normalize_cargo_map, resolve_build_id
from .handlers import JournalEventHandler
from .overlay.project_cache import apply_project_cache_update
from .plugin_config import PluginConfig, edmc_log_path_hint
from .station_names import normalize_dock_station_name
from .dock_state_sync import apply_plugin_dock_fields_from_edmc_state
from .site_market_id_repair import (
    dock_context_skips_market_id_repair,
    market_id_is_player_colony_station,
    market_id_repair_candidates,
    site_name_repair_candidates,
    site_market_id_missing,
    site_market_id_repair_retry_delay,
)
from .ui import UIManager
from .exc_utils import (
    CONFIG_READ_ERRORS,
    FILE_IO_ERRORS,
    HTTP_CLIENT_ERRORS,
    JSON_LOAD_ERRORS,
    OVERLAY_UI_ERRORS,
    STATE_COPY_ERRORS,
    UPDATE_PATH_ERRORS,
)

_UPDATE_ERRORS = HTTP_CLIENT_ERRORS + UPDATE_PATH_ERRORS + (zipfile.BadZipFile, ValueError)

# Plugin metadata
plugin_name = os.path.basename(os.path.dirname(__file__))
plugin_version = "1.8.2-rc.3"
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
    logger.info(message)
    if _edmc_is_shutting_down():
        return
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


def _show_plugin_error_main_thread(message: str) -> None:
    """Show an EDMC plugin error from the Tk main thread."""
    if _edmc_is_shutting_down():
        logger.error(message)
        return
    if not this:
        logger.error(message)
        return
    frame = getattr(this, 'frame', None)
    if frame is None:
        logger.error(message)
        return

    def show() -> None:
        try:
            if frame.winfo_exists():
                plug.show_error(message)
        except tk.TclError:
            pass

    try:
        frame.after(0, show)
    except tk.TclError:
        logger.error(message)


def _strip_leading_v_for_display(version: Optional[str]) -> str:
    """Return version text without a leading GitHub tag ``v`` for UI strings that add it."""
    if not version:
        return "?"
    s = str(version).strip()
    return s[1:] if s[:1].lower() == "v" else s


def _log_edmc_compat_result(compat: edmc_compat.EdmcCompatResult) -> None:
    """Log EDMC core compatibility outcome during plugin startup."""
    if compat.level == "advisory" and compat.reason == "below_minimum":
        logger.warning(
            "EDMC core %s is below tested minimum %s",
            compat.core_version or "?",
            edmc_compat.MIN_SUPPORTED_EDMC_VERSION,
        )
        return
    if compat.level == "blocking" and compat.reason == "known_incompatible":
        logger.error(
            "EDMC core %s is known incompatible with this plugin",
            compat.core_version or "?",
        )
        return
    if compat.core_version:
        logger.info("EDMC core version: %s", compat.core_version)


def _apply_edmc_compat_notice(compat: edmc_compat.EdmcCompatResult) -> None:
    """Surface EDMC compatibility results through the main-thread status/error paths."""
    if compat.level == "blocking" and compat.reason == "known_incompatible":
        _show_plugin_error_main_thread(
            i18n.trf(
                "{plugin_name}: EDMC {current} is known incompatible with this plugin.",
                plugin_name=plugin_name,
                current=compat.core_version or "?",
            )
        )
        return
    if compat.level == "advisory" and compat.reason == "below_minimum":
        _notify_plugin_status_main_thread(
            i18n.trf(
                "{plugin_name}: EDMC {current} is below tested minimum {minimum}. "
                "Upgrade EDMC for best compatibility.",
                plugin_name=plugin_name,
                current=compat.core_version or "?",
                minimum=edmc_compat.MIN_SUPPORTED_EDMC_VERSION,
            )
        )


def _edmc_is_shutting_down() -> bool:
    """EDMC exposes ``config.shutting_down`` as a property, not a function."""
    try:
        return bool(getattr(config, "shutting_down", False))
    except (AttributeError, TypeError):
        return False


def schedule_after(
    delay_ms: int,
    callback: Callable[[], None],
    *,
    widget: Optional[tk.Misc] = None,
) -> Optional[str]:
    """Schedule a callback on the plugin frame when EDMC is not shutting down."""
    if _edmc_is_shutting_down():
        return None
    if not this:
        return None
    frame = getattr(this, "frame", None)
    if frame is None:
        return None
    if widget is not None:
        try:
            if not widget.winfo_exists():
                return None
        except tk.TclError:
            return None
    try:
        if not frame.winfo_exists():
            return None
    except tk.TclError:
        return None
    try:
        return frame.after(max(0, int(delay_ms)), callback)
    except tk.TclError:
        return None


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


def _cmdr_name_from_capi_data(data: Any) -> Optional[str]:
    """Commander name from supported CAPIData fields/properties."""
    for raw in (
        getattr(data, "request_cmdr", None),
        (data.get("commander") or {}).get("name") if hasattr(data, "get") else None,
    ):
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return None


def _stealth_construction_reporting() -> bool:
    """When True, skip journal-driven construction depot, contributions, and depot deliveries to the API."""
    try:
        return config.get_bool("ravencolonial_stealth_construction_reporting")
    except CONFIG_READ_ERRORS:
        return False


def _candidate_elite_journal_dirs() -> List[Path]:
    """Likely Elite Dangerous journal folders for EDMC config fallback."""
    candidates: List[Path] = []
    try:
        configured = (config.get_str("journaldir") or "").strip()
    except CONFIG_READ_ERRORS:
        configured = ""
    if configured:
        candidates.append(Path(os.path.expandvars(os.path.expanduser(configured))))

    home = Path.home()
    if os.name == "nt":
        candidates.append(home / "Saved Games" / "Frontier Developments" / "Elite Dangerous")
    elif sys.platform == "darwin":
        candidates.extend(
            [
                home / "Library" / "Application Support" / "Frontier Developments" / "Elite Dangerous",
                home / "Library" / "Application Support" / "Steam" / "steamapps" / "compatdata" /
                "359320" / "pfx" / "drive_c" / "users" / "steamuser" / "Saved Games" /
                "Frontier Developments" / "Elite Dangerous",
            ]
        )
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            candidates.append(
                Path(xdg_data) /
                "Steam" / "steamapps" / "compatdata" / "359320" / "pfx" / "drive_c" /
                "users" / "steamuser" / "Saved Games" / "Frontier Developments" / "Elite Dangerous"
            )
        candidates.extend(
            [
                home / ".steam" / "steam" / "steamapps" / "compatdata" / "359320" / "pfx" /
                "drive_c" / "users" / "steamuser" / "Saved Games" / "Frontier Developments" /
                "Elite Dangerous",
                home / ".local" / "share" / "Steam" / "steamapps" / "compatdata" / "359320" /
                "pfx" / "drive_c" / "users" / "steamuser" / "Saved Games" /
                "Frontier Developments" / "Elite Dangerous",
            ]
        )
    return candidates


def _elite_journal_dir() -> Optional[str]:
    """Elite Dangerous journal folder from EDMC config or platform defaults."""
    for candidate in _candidate_elite_journal_dirs():
        try:
            if candidate.is_dir():
                return str(candidate)
        except OSError:
            continue
    return None


def _recent_files(directory: str, pattern: str, limit: int) -> List[str]:
    """Return recent files by mtime, tolerating disappearing journal files."""
    try:
        root = Path(directory)
        files = [p for p in root.glob(pattern) if p.is_file()]
    except OSError as e:
        logger.debug("Could not scan %s for %s: %s", directory, pattern, e)
        return []

    def file_mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return -1.0

    files.sort(key=file_mtime, reverse=True)
    return [str(p) for p in files[:limit]]


def _scan_recent_journal_entries(
    journal_dir: str,
    *,
    event_name: Optional[str] = None,
    predicate: Optional[Callable[[Dict[str, Any]], bool]] = None,
    limit: int = 5,
) -> List[Tuple[datetime, int, int, Dict[str, Any]]]:
    """
    Scan recent journal files for matching events.

    Returns ``(timestamp, file_index, line_index, entry)`` tuples from the newest files first.
    """
    journal_files = _recent_files(journal_dir, "Journal.*.log", limit)
    if not journal_files:
        return []

    candidates: List[Tuple[datetime, int, int, Dict[str, Any]]] = []
    for file_index, journal_file in enumerate(journal_files):
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
                    if event_name is not None and entry.get("event") != event_name:
                        continue
                    if predicate is not None and not predicate(entry):
                        continue
                    ts = _journal_parse_timestamp(entry)
                    if ts is None:
                        ts = datetime.min.replace(tzinfo=timezone.utc)
                    candidates.append((ts, file_index, line_index, entry))
        except OSError as e:
            logger.debug("Error reading journal file %s: %s", journal_file, e)
    return candidates


def _system_address_from_edmc_snapshot(
    plugin: Any, snap: Dict[str, Any]
) -> Optional[int]:
    if snap.get("SystemAddress") is None:
        return None
    try:
        addr = int(snap["SystemAddress"])
    except (TypeError, ValueError):
        return None
    logger.debug("Using SystemAddress %s from EDMC state snapshot", addr)
    sn = snap.get("SystemName")
    if isinstance(sn, str) and sn and not plugin.current_system:
        plugin.current_system = sn
    sp = snap.get("StarPos")
    if sp and not plugin.star_pos:
        plugin.star_pos = sp
    return addr


def _dock_context_address_candidates(journal_dir: str) -> List[tuple]:
    candidates: List[tuple] = []
    for ts, file_index, line_index, entry in _scan_recent_journal_entries(
        journal_dir, predicate=_journal_entry_is_dock_context, limit=5
    ):
        sa = entry.get("SystemAddress")
        if sa is None:
            continue
        try:
            sa_int = int(sa)
        except (TypeError, ValueError):
            continue
        candidates.append(
            (ts, file_index, line_index, sa_int, entry.get("StarSystem"), entry.get("StarPos"))
        )
    return candidates


def _apply_dock_context_scan_result(plugin: Any, best: tuple) -> int:
    _, _, _, addr, star_system, star_pos = best
    logger.debug(
        "Using journal dock context SystemAddress=%s at %s (file_index=%s line=%s)",
        addr,
        best[0].isoformat(),
        best[1],
        best[2],
    )
    if star_system and not plugin.current_system:
        plugin.current_system = star_system
    if star_pos and not plugin.star_pos:
        plugin.star_pos = star_pos
    return addr


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
        # Skip duplicate PATCH /api/project/{buildId} depot bodies
        self._last_depot_patch_payload_sig: Optional[str] = None
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
        self.overlay_modern_enabled: bool = False
        self.overlay_popout_enabled: bool = False
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
        self.build_popout = None
        self.fc_manifest_editor = None

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
        self.schedule_after = schedule_after

    def remember_commander_from_hook(
        self,
        cmdr: Any,
        *,
        source: str,
        authoritative: bool = False,
    ) -> None:
        """Cache commander identity from supported EDMC hook parameters."""
        if cmdr is None:
            return
        name = str(cmdr).strip()
        if not name:
            return
        if authoritative or not self.cmdr_name:
            if self.cmdr_name != name:
                logger.debug("Commander name set from %s: %s", source, name)
            self.cmdr_name = name
            return
        if self.cmdr_name != name:
            logger.debug(
                "Ignoring non-authoritative commander name from %s (%s); current is %s",
                source,
                name,
                self.cmdr_name,
            )

    def refresh_plan_sites_ui(self) -> None:
        """Reconcile plan-site and overlay build comboboxes (main thread)."""
        if getattr(self, "ui_manager", None):
            self.ui_manager.refresh_plan_site_row_state()
            self.ui_manager.refresh_overlay_build_row_state()

    def clear_plan_sites_cache(self) -> None:
        """Clear system-scoped plan-site rows without touching persistent overlay tracking."""
        self.plan_sites_system_key = None
        self.plan_sites_rows = []
        self.plan_sites_transient_message = None
        self.selected_plan_site_id = None
        self.selected_plan_site_obj = None
        self.plan_sites_allow_create_new = True

    def set_current_system_address(self, system_address: Any) -> None:
        """Set current system id64 and clear plan-site cache when the system changes."""
        if system_address is None:
            return
        try:
            new_address = int(system_address)
        except (TypeError, ValueError):
            return
        old_address = self.current_system_address
        try:
            old_i = int(old_address) if old_address is not None else None
        except (TypeError, ValueError):
            old_i = None
        if old_i is not None and old_i != new_address:
            logger.debug(
                "System changed from %s to %s; clearing plan-site cache",
                old_i,
                new_address,
            )
            self.clear_plan_sites_cache()
        self.current_system_address = new_address

    def refresh_track_all_projects_if_selected(self, reason: str = "") -> None:
        """Refresh all Track All project details for construction/FC dock context changes."""
        if (
            not getattr(self, "overlay_ui_enabled", False) or
            getattr(self, "selected_overlay_build_id", None) != "__OVERLAY_TRACK_ALL__" or
            getattr(self, "overlay_project_fetch_inflight", False)
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
                except HTTP_CLIENT_ERRORS as e:
                    logger.error("API call failed: %s", e, exc_info=True)
                    # Show error in EDMC status bar asynchronously on the Tk main thread.
                    error_msg = i18n.tr("Ravencolonial API error:") + f" {str(e)}"
                    _show_plugin_error_main_thread(error_msg)
                finally:
                    self.api_queue.task_done()
            except Exception as e:
                # Keep worker alive for subsequent queued API calls after unexpected failures.
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

    def _queue_publish_current_ship(
        self,
        state: Optional[Dict[str, Any]],
        reason: str,
        *,
        journal_timestamp: Optional[Any] = None,
        cargo_delta: Optional[Dict[str, int]] = None,
    ) -> None:
        """Enqueue POST /api/cmdr/currentShip when cargo or ship identity changes (SrvSurvey parity)."""
        try:
            if config.get_bool("ravencolonial_stealth_ship_cargo"):
                logger.debug("Ship cargo stealth: skip publish current ship (%s)", reason)
                return
        except CONFIG_READ_ERRORS:
            # Stealth prefs unavailable: default to publishing ship cargo.
            pass

        payload = self._build_current_ship_payload(state)
        if not payload:
            logger.debug("publish current ship skipped (%s): incomplete context", reason)
            return

        sig = json.dumps(payload, sort_keys=True, default=str)
        if sig == self._last_current_ship_sig:
            cargo = _normalize_cargo_map(payload.get("cargo") or {})
            logger.debug(
                "publish current ship skipped (%s): unchanged timestamp=%s cargo=%s total=%s",
                reason,
                journal_timestamp,
                cargo,
                _cargo_total(cargo),
            )
            return
        cargo = _normalize_cargo_map(payload.get("cargo") or {})
        logger.debug(
            "Queue current ship publish (%s): timestamp=%s delta=%s cargo=%s total=%s maxCargo=%s ship=%s",
            reason,
            journal_timestamp,
            cargo_delta or {},
            cargo,
            _cargo_total(cargo),
            payload.get("maxCargo"),
            payload.get("type"),
        )
        self.queue_api_call(
            self._run_publish_current_ship_payload,
            sig,
            payload,
            reason,
            journal_timestamp,
            cargo_delta or {},
        )

    def _run_publish_current_ship_payload(
        self,
        sig: str,
        payload: Dict[str, Any],
        reason: str = "unknown",
        journal_timestamp: Optional[Any] = None,
        cargo_delta: Optional[Dict[str, int]] = None,
    ) -> None:
        cargo = _normalize_cargo_map(payload.get("cargo") or {})
        logger.debug(
            "POST /api/cmdr/currentShip (%s): timestamp=%s delta=%s cargo=%s total=%s maxCargo=%s ship=%s",
            reason,
            journal_timestamp,
            cargo_delta or {},
            cargo,
            _cargo_total(cargo),
            payload.get("maxCargo"),
            payload.get("type"),
        )
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
        except CONFIG_READ_ERRORS:
            # Stealth prefs unavailable: default to applying market trades locally.
            pass

        previous = _normalize_cargo_map(dict(self.cargo or {}))
        updated = _apply_market_trade_to_cargo(previous, entry, is_buy=is_buy)
        if updated == previous:
            return

        self.cargo = updated
        diff_cmdr = _cargo_count_diff(previous, updated)
        logger.debug(
            "Commander market cargo %s: timestamp=%s delta=%s cargo=%s total=%s",
            "buy" if is_buy else "sell",
            entry.get("timestamp"),
            diff_cmdr,
            updated,
            _cargo_total(updated),
        )
        self._queue_publish_current_ship(
            state,
            "MarketBuy" if is_buy else "MarketSell",
            journal_timestamp=entry.get("timestamp"),
            cargo_delta=diff_cmdr,
        )

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
                c is not None and
                c[0] == system_address and
                c[1] == market_id and
                (now - c[3]) < self._project_location_cache_ttl_s
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
            remaining = commodities if isinstance(commodities, dict) else None
            if remaining is not None:
                self.remember_depot_remaining_need(remaining)
            if depot_sig is not None:
                self._last_depot_patch_payload_sig = depot_sig
            if isinstance(project_view, dict):
                apply_project_cache_update(
                    self,
                    str(build_id),
                    remaining_need=remaining,
                    project_view=project_view,
                )
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
                self.set_current_system_address(self.get_system_address_from_journal())
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
        except JSON_LOAD_ERRORS as e:
            logger.warning("Could not load site repair visit cache %s: %s", path, e)
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
        except FILE_IO_ERRORS as e:
            logger.warning("Could not save site repair visit cache %s: %s", path, e)
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
                    "Site marketId repair skipped for %s station=%r marketId=%s: "
                    "/sites fetch failed after %s attempt(s)",
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
                    "Site repair skipped for %s station=%r marketId=%s: expected one marketId or "
                    "name repair match, got marketId=%s name=%s",
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

    def _sync_docked_state_from_edmc_state(
        self,
        state: Optional[Dict[str, Any]],
        *,
        station: str = "",
    ) -> bool:
        if not state:
            return False
        return apply_plugin_dock_fields_from_edmc_state(self, state, station=station)

    def _journal_maybe_init_fc_handler(self, cmdr: str, state: Optional[Dict[str, Any]]) -> None:
        """Initialize Fleet Carrier handler on first commander event."""
        logger.debug(f"FC init check: cmdr={cmdr}, has_initialized={hasattr(self.fc_handler, '_initialized')}")
        if not cmdr or hasattr(self.fc_handler, '_initialized'):
            return
        logger.info(f"Initializing Fleet Carrier handler for {cmdr}")
        api_key = config.get_str('ravencolonial_api_key') or ''
        logger.debug(f"API key present: {bool(api_key)}")
        if api_key:
            self.api_client.set_credentials(cmdr, api_key)
            logger.debug("API credentials set")

        self.fc_handler.initialize_fcs(cmdr)

        if state:
            self.fc_handler.initialize_current_dock_context(state)

        self.fc_handler._initialized = True
        logger.info("Fleet Carrier handler initialization complete")

    def _journal_apply_track_all_on_dock(self, docked_fc: bool) -> None:
        if self.is_construction_ship or docked_fc:
            self._track_all_refresh_on_qualifying_undock = True

    def _journal_handle_docked(self, entry: Dict[str, Any], *, station: str) -> None:
        logger.info(f"Docked at {station}, MarketID: {entry.get('MarketID')}")
        self.current_market_id = entry.get('MarketID')
        self.set_current_system_address(entry.get('SystemAddress'))
        self.star_pos = entry.get('StarPos')
        if entry.get('BodyID') is not None:
            self.body_num = entry.get('BodyID')
        if entry.get('Body') is not None:
            self.body_name = entry.get('Body')
        self.station_type = entry.get('StationType')
        self.faction_name = entry.get('StationFaction', {}).get('Name')
        self.is_docked = True
        station_name = entry.get('StationName', '')
        self.is_construction_ship = 'ColonisationShip' in station_name
        logger.debug(
            f"Docked details - StationType: {self.station_type}, is_construction_ship: {self.is_construction_ship}"
        )

        docked_fc = self.fc_handler.handle_docked_event(entry)
        self._journal_apply_track_all_on_dock(docked_fc)

        self.update_status(i18n.trf("Docked at {station}", station=station))
        self.maybe_queue_site_market_id_repair(entry)

    def _journal_handle_carrier_stats(self, entry: Dict[str, Any]) -> None:
        try:
            self.fc_handler.update_fc_capacity_from_journal_stats(entry)
        except (TypeError, ValueError, AttributeError, KeyError):
            logger.warning("journal CarrierStats capacity cache skipped", exc_info=True)

    def _journal_handle_carrier_jump_request(self, entry: Dict[str, Any]) -> None:
        if not self.fc_handler:
            return
        try:
            self.fc_handler.handle_jump_requested(entry)
        except (TypeError, ValueError, AttributeError, KeyError):
            logger.warning("journal CarrierJumpRequest handling failed", exc_info=True)

    def _journal_handle_carrier_jump_cancelled(self, entry: Dict[str, Any]) -> None:
        if not self.fc_handler:
            return
        try:
            self.fc_handler.handle_jump_cancelled(entry)
        except (TypeError, ValueError, AttributeError, KeyError):
            logger.warning("journal CarrierJumpCancelled handling failed", exc_info=True)

    def _journal_handle_carrier_location(self, entry: Dict[str, Any]) -> None:
        if not self.fc_handler:
            return
        try:
            self.fc_handler.handle_carrier_location(entry)
        except (TypeError, ValueError, AttributeError, KeyError):
            logger.warning("journal CarrierLocation handling failed", exc_info=True)

    def _journal_handle_undocked(self, entry: Dict[str, Any], *, station: str) -> None:
        left_station = entry.get('StationName') or station or i18n.tr("Unknown")
        logger.info(f"Undocked from {left_station}")
        self.is_docked = False
        self.is_construction_ship = False
        self.current_market_id = None
        self._bodies_fetched = False
        self.last_depot_remaining_need = {}
        self.invalidate_project_location_cache()
        self._last_depot_patch_payload_sig = None
        self.fc_handler.clear_dock_context()
        self.update_status(i18n.trf("Undocked from {station}", station=left_station))
        self.update_create_button()
        if getattr(self, "_track_all_refresh_on_qualifying_undock", False):
            self._track_all_refresh_on_qualifying_undock = False
            self.refresh_track_all_projects_if_selected("qualifying undock")

    def _journal_handle_location(
        self, entry: Dict[str, Any], *, station: str, system: str
    ) -> None:
        logger.info(f"Location event - system: {system}, station: {station}")
        self.set_current_system_address(entry.get('SystemAddress'))
        self.star_pos = entry.get('StarPos')
        if entry.get('Docked'):
            self.current_market_id = entry.get('MarketID')
            if entry.get('BodyID') is not None:
                self.body_num = entry.get('BodyID')
            if entry.get('Body') is not None:
                self.body_name = entry.get('Body')
            self.station_type = entry.get('StationType')
            self.is_docked = True
            station_name = entry.get('StationName', '')
            self.is_construction_ship = 'ColonisationShip' in station_name
            logger.info(
                "Location event - docked at %s, StationType: %s, StationName: %s, is_construction_ship: %s",
                station,
                self.station_type,
                station_name,
                self.is_construction_ship,
            )
            docked_fc = self.fc_handler.handle_docked_event(entry)
            self._journal_apply_track_all_on_dock(docked_fc)
            self.maybe_queue_site_market_id_repair(entry)
            self.update_create_button()
        else:
            self.is_docked = False
            self.is_construction_ship = False
            self.current_market_id = None
            self.invalidate_project_location_cache()
            self._last_depot_patch_payload_sig = None
            self.fc_handler.clear_dock_context()
            self.update_create_button()

    def _journal_handle_cargo_depot(self, entry: Dict[str, Any]) -> None:
        if _stealth_construction_reporting():
            logger.debug("Construction reporting stealth: skipping CargoDepot API handling")
        else:
            self.handle_cargo_depot(entry)

    def _journal_handle_market(self, entry: Dict[str, Any]) -> None:
        self.handle_market(entry)

    def _journal_handle_market_buy(self, entry: Dict[str, Any], *, state: Dict[str, Any]) -> None:
        if not self.fc_handler.handle_marketbuy_event(entry):
            self._handle_commander_market_trade(entry, is_buy=True, state=state)

    def _journal_handle_market_sell(self, entry: Dict[str, Any], *, state: Dict[str, Any]) -> None:
        logger.debug(f"MarketSell event received: {entry}")
        if not self.fc_handler.handle_marketsell_event(entry):
            self._handle_commander_market_trade(entry, is_buy=False, state=state)

    def _journal_handle_cargo_transfer(self, entry: Dict[str, Any], *, state: Dict[str, Any]) -> None:
        logger.debug(f"CargoTransfer event received: {entry}")
        ship_delta = _ship_delta_from_cargo_transfer_entry(entry)
        if ship_delta:
            logger.debug(
                "Commander cargo transfer: timestamp=%s delta=%s",
                entry.get("timestamp"),
                ship_delta,
            )
        result = self.fc_handler.handle_cargotransfer_event(entry, state)
        logger.debug(f"CargoTransfer handler returned: {result}")

    def _journal_handle_cargo(self, entry: Dict[str, Any], *, state: Dict[str, Any]) -> None:
        previous_cargo = _normalize_cargo_map(dict(self.cargo or {}))
        inv = entry.get("Inventory")
        count = int(entry.get("Count", 0) or 0)
        has_full_snapshot = count > 0 and inv and len(inv) > 0

        if has_full_snapshot:
            self.cargo = {item["Name"].replace("_name", ""): item["Count"] for item in inv}
        else:
            new_norm = _cargo_from_edmc_state(state)
            if count == 0:
                self.cargo = dict(new_norm) if new_norm else {}
            elif new_norm:
                self.cargo = dict(new_norm)
            elif count > 0:
                logger.debug(
                    "Sparse Cargo (Count=%s) without Inventory or EDMC breakdown — keeping plugin hold",
                    count,
                )
        current_cargo = _normalize_cargo_map(dict(self.cargo or {}))
        diff_cmdr = _cargo_count_diff(previous_cargo, current_cargo)
        logger.debug(
            "Commander cargo snapshot from Cargo: timestamp=%s count=%s delta=%s cargo=%s total=%s",
            entry.get("timestamp"),
            count,
            diff_cmdr,
            current_cargo,
            _cargo_total(current_cargo),
        )
        self._queue_publish_current_ship(
            state,
            "Cargo",
            journal_timestamp=entry.get("timestamp"),
            cargo_delta=diff_cmdr,
        )
        self.refresh_build_overlay()

    def _journal_handle_loadout(self, entry: Dict[str, Any], *, state: Dict[str, Any]) -> None:
        ship_raw = str(entry.get('Ship', '')).lower()
        if 'fighter' not in ship_raw and 'buggy' not in ship_raw:
            self._refresh_ship_from_loadout_entry(entry)
            if state is not None:
                self._refresh_ship_from_state(state)
            self._queue_publish_current_ship(
                state,
                "Loadout",
                journal_timestamp=entry.get("timestamp"),
            )
            self.refresh_build_overlay()

    def _journal_handle_set_user_ship_name(self, entry: Dict[str, Any], *, state: Dict[str, Any]) -> None:
        if entry.get('UserShipName') and str(entry.get('UserShipName')).strip() not in ('', ' '):
            self.ship_display_name = str(entry['UserShipName']).strip()
        if 'UserShipId' in entry:
            uid = entry.get('UserShipId')
            self.ship_ident = str(uid).strip() if uid else None
        self._queue_publish_current_ship(
            state,
            "SetUserShipName",
            journal_timestamp=entry.get("timestamp"),
        )

    def _journal_handle_colonisation_construction_depot(self, entry: Dict[str, Any]) -> None:
        logger.debug("ColonisationConstructionDepot event received")
        if _stealth_construction_reporting():
            logger.debug("Construction reporting stealth: not processing colonization depot")
        else:
            self.handle_colonisation_construction_depot(entry)

    def _journal_handle_colonisation_contribution(self, entry: Dict[str, Any]) -> None:
        logger.debug("ColonisationContribution event received")
        if _stealth_construction_reporting():
            logger.debug("Construction reporting stealth: not processing colonization contribution")
        else:
            self.handle_colonisation_contribution(entry)

    def update_status(self, message: str, *, l10n_key: Optional[str] = None):
        """Update the UI status label"""
        return self.ui_manager.update_status(message, l10n_key=l10n_key)

    def update_create_button(self):
        """Enable/disable create button based on docking status and existing projects"""
        self.ui_manager.update_create_button()
        self.refresh_build_overlay()

    def refresh_build_overlay(self, *, force: bool = False) -> None:
        """Update build tracker outputs from current build/depot state."""
        modern_enabled = bool(getattr(self, "overlay_modern_enabled", False))
        popout_enabled = bool(getattr(self, "overlay_popout_enabled", False))
        build_overlay = getattr(self, "build_overlay", None)
        build_popout = getattr(self, "build_popout", None)
        if not modern_enabled and not popout_enabled and build_overlay is None and build_popout is None:
            return
        if modern_enabled or build_overlay is not None:
            try:
                if build_overlay is None:
                    from .overlay import BuildProjectOverlay

                    self.build_overlay = BuildProjectOverlay(self)
                    build_overlay = self.build_overlay
                build_overlay.refresh(force=force)
            except OVERLAY_UI_ERRORS as e:
                logger.warning("Build overlay refresh failed: %s", e, exc_info=True)
        if popout_enabled or build_popout is not None:
            try:
                if build_popout is None:
                    from .overlay.popout import BuildProjectPopout

                    self.build_popout = BuildProjectPopout(self)
                    build_popout = self.build_popout
                build_popout.refresh(force=force)
            except OVERLAY_UI_ERRORS as e:
                logger.warning("Build popout refresh failed: %s", e, exc_info=True)

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
            if snap:
                addr = _system_address_from_edmc_snapshot(self, snap)
                if addr is not None:
                    return addr

            journal_dir = _elite_journal_dir()
            if not journal_dir:
                logger.debug("No valid journal directory found")
                return None

            logger.debug("Scanning recent journal file(s) for latest dock context")
            candidates = _dock_context_address_candidates(journal_dir)
            if not candidates:
                logger.debug("No Docked / Location(docked) with SystemAddress in journal scan")
                return None

            best = max(candidates, key=lambda c: (c[0], -c[1], c[2]))
            return _apply_dock_context_scan_result(self, best)

        except (OSError, TypeError, ValueError, KeyError) as e:
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
        journal_dir = _elite_journal_dir()
        if not journal_dir:
            logger.debug("refresh_construction_depot_from_journal: no journal directory")
            return False

        candidates = _scan_recent_journal_entries(
            journal_dir, event_name="ColonisationConstructionDepot", limit=5
        )
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
            self.set_current_system_address(entry["SystemAddress"])

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
        issue_log = plugin_file_log.init_issue_log(plugin_dir, appname, plugin_name)
        if issue_log is None:
            logger.warning(
                "RavenColonial issue log could not be initialized; use EDMC main log instead: %s",
                edmc_log_path_hint(),
            )
        this.configure_site_market_id_repair_visit_cache(plugin_dir)
        this.fc_handler.configure_owner_capacity_cache(plugin_dir)
        this._edmc_compat_notice = edmc_compat.check_edmc_compatibility()
        _log_edmc_compat_result(this._edmc_compat_notice)
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
                                    "{plugin_name}: Update downloaded - restart EDMC to install v{version}",
                                    plugin_name=plugin_name,
                                    version=_strip_leading_v_for_display(this.update_info.remote_version),
                                )
                            )
                        except _UPDATE_ERRORS as e:
                            logger.error(f"Auto-update failed: {e}", exc_info=True)
                            _notify_plugin_status_main_thread(
                                i18n.trf(
                                    "{plugin_name}: Auto-update failed. Check logs.",
                                    plugin_name=plugin_name,
                                )
                            )
                            _show_plugin_error_main_thread(
                                i18n.trf(
                                    "{plugin_name}: Auto-update failed. Check logs.",
                                    plugin_name=plugin_name,
                                ) +
                                "\nPlease try manual installation from docs/MANUAL_UPDATE_INSTRUCTIONS.md."
                            )
                    else:
                        # Just notify user that update is available
                        logger.info("Update available but auto-update disabled")
                        # UI will show the update notification

                except _UPDATE_ERRORS as e:
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
        # Fatal init: log any startup failure and re-raise so EDMC marks the plugin broken.
        logger.error(f"Failed to initialize: {e}", exc_info=True)
        raise


def _close_ui_surfaces_on_stop() -> None:
    if not this:
        return
    surfaces = (
        ("build_overlay", "clear", "Build overlay clear on stop failed: %s"),
        ("build_popout", "clear", "Build popout clear on stop failed: %s"),
        ("fc_manifest_editor", "close", "FC manifest editor close on stop failed: %s"),
    )
    for attr, method_name, message in surfaces:
        surface = getattr(this, attr, None)
        if surface is None:
            continue
        try:
            getattr(surface, method_name)()
        except OVERLAY_UI_ERRORS as e:
            logger.debug(message, e)


def plugin_stop() -> None:
    """
    Unload the plugin.
    """
    try:
        from .ui.edmc_theme import release_bundled_oxanium_font

        release_bundled_oxanium_font()
    except OVERLAY_UI_ERRORS as e:
        logger.debug("Oxanium font release on stop failed: %s", e)
    capi_cache.stop()
    plugin_file_log.stop_issue_log()
    _close_ui_surfaces_on_stop()
    if this:
        # Signal worker thread to stop
        if this.worker_thread and this.worker_thread.is_alive():
            this.api_queue.put(None)
        # Wait for worker thread to finish (recommended by EDMC docs)
        if this.worker_thread and this.worker_thread.is_alive():
            this.worker_thread.join(timeout=5)  # 5 second timeout to avoid hanging
        if getattr(this, "update_info", None):
            try:
                this.update_info.install_staged_update_on_shutdown()
            except UPDATE_PATH_ERRORS as e:
                logger.error("Failed to install staged update on shutdown: %s", e, exc_info=True)
        logger.info(f"{PluginConfig.NAME} stopped")


def check_github_version(allow_prerelease: Optional[bool] = None) -> Optional[str]:
    """
    Check GitHub for the latest release version.

    :return: Latest version string or None if check fails
    """
    try:
        if allow_prerelease is None:
            allow_prerelease = PluginConfig.get_check_prerelease()
        latest_version = version_check.latest_release_version_string(
            logger,
            allow_prerelease=bool(allow_prerelease),
        )
        if latest_version:
            channel = "pre-release-enabled" if allow_prerelease else "stable"
            logger.debug(f"Latest GitHub version ({channel} channel): {latest_version}")
        return latest_version
    except HTTP_CLIENT_ERRORS as e:
        logger.debug("Failed to check GitHub version: %s", e)
        return None


def _persist_ravencolonial_prefs_from_frame(frame: nb.Frame, cmdr: Optional[str]) -> None:
    """Write Ravencolonial plugin preference widgets to EDMC config and refresh runtime state."""
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
        if getattr(this, "build_popout", None):
            this.build_popout.refresh(force=True)


def _prefs_on_toggle_show_api_key(frame: nb.Frame) -> None:
    frame.api_key_entry.config(show="" if frame.show_api_key_var.get() else "*")


def _prefs_check_for_updates(frame: nb.Frame) -> None:
    """Check GitHub for updates in background thread."""
    try:
        allow_prerelease = PluginConfig.get_check_prerelease()
        try:
            allow_prerelease = bool(frame.prerelease_var.get())
        except (AttributeError, tk.TclError):
            pass
        latest = check_github_version(allow_prerelease=allow_prerelease)

        if not frame.winfo_exists():
            logger.debug("Settings frame no longer exists, skipping version update")
            return

        if latest:
            logger.debug(f"Comparing versions: current={plugin_version}, latest={latest}")
            if version_check.compare_versions(plugin_version, latest, logger):
                frame.version_text.set(
                    i18n.trf(
                        "Version: {version} (Update available: {latest})",
                        version=plugin_version,
                        latest=latest,
                    )
                )
                logger.info(f"Update available: {latest} (current: {plugin_version})")
            else:
                frame.version_text.set(
                    i18n.trf("Version: {version} (up to date)", version=plugin_version)
                )
                logger.debug(f"Plugin is up to date: {plugin_version}")
        else:
            logger.debug("GitHub version check returned None, showing version only")
            frame.version_text.set(i18n.trf("Version: {version}", version=plugin_version))
    except tk.TclError as e:
        logger.debug(f"Frame destroyed before update could be displayed: {e}")
    except HTTP_CLIENT_ERRORS as e:
        logger.warning("Error checking for updates: %s", e, exc_info=True)
        try:
            if frame.winfo_exists():
                frame.version_text.set(i18n.trf("Version: {version}", version=plugin_version))
        except tk.TclError as e2:
            logger.error("Failed to set version text: %s", e2, exc_info=True)


def _prefs_save_settings(frame: nb.Frame, cmdr: Optional[str]) -> None:
    _persist_ravencolonial_prefs_from_frame(frame, cmdr)


def _prefs_install_overlay_fonts(frame: nb.Frame, plugin_dir: str) -> None:
    from .overlay.font_setup import retry_install_oxanium_font

    ok, msg = retry_install_oxanium_font(plugin_dir)
    body = i18n.tr(msg) if msg and not msg.startswith("Font install failed") else (
        i18n.trf("Font install failed: {error}", error=msg) if msg else ""
    )
    if ok:
        messagebox.showinfo(i18n.tr("Overlay fonts"), body, parent=frame)
    else:
        messagebox.showerror(i18n.tr("Overlay fonts"), body, parent=frame)


def _prefs_reset_popout_position(frame: nb.Frame) -> None:
    """Center and activate the Popout Tracker from the settings page."""
    try:
        if this is None:
            raise RuntimeError("Plugin runtime is unavailable")
        overlay_row = getattr(getattr(this, "ui_manager", None), "_overlay_row", None)
        if overlay_row is not None and overlay_row.reset_and_show_popout():
            return

        # The main tab is normally present before Settings opens. Keep a fallback
        # for unusual EDMC startup ordering so the recovery control remains useful.
        this.overlay_popout_enabled = True
        this.overlay_modern_enabled = False
        this.overlay_ui_enabled = True
        this.overlay_always_on = False
        this.refresh_build_overlay(force=True)
        popout = getattr(this, "build_popout", None)
        if popout is None:
            raise RuntimeError("Popout Tracker could not be created")
        popout.reset_position()
    except OVERLAY_UI_ERRORS as exc:
        logger.warning("Could not reset Popout Tracker position: %s", exc, exc_info=True)
        messagebox.showerror(
            i18n.tr("Popout Tracker unavailable"),
            i18n.tr("Could not reset the Popout Tracker window. Check the EDMC log."),
            parent=frame,
        )


def _add_prefs_api_key_section(frame: nb.Frame) -> int:
    """API key row widgets; returns next grid row."""
    api_key_label = nb.Label(frame, text=i18n.tr("Ravencolonial API Key:"))
    api_key_label.grid(row=1, column=0, sticky=tk.W, padx=10, pady=5)

    try:
        api_key_value = config.get_str('ravencolonial_api_key') or ''
    except CONFIG_READ_ERRORS:
        api_key_value = ''

    frame.api_key_var = tk.StringVar(value=api_key_value)
    frame.api_key_entry = ttk.Entry(frame, textvariable=frame.api_key_var, width=40, show="*")
    frame.api_key_entry.grid(row=1, column=1, sticky=tk.W, padx=10, pady=5)

    frame.show_api_key_var = tk.BooleanVar(value=False)
    show_api_key_check = nb.Checkbutton(
        frame,
        text=i18n.tr("Show API Key"),
        variable=frame.show_api_key_var,
        command=lambda: _prefs_on_toggle_show_api_key(frame),
    )
    show_api_key_check.grid(row=2, column=1, sticky=tk.W, padx=10, pady=(0, 2))

    api_key_help = nb.Label(frame, text=i18n.tr("Get your API key from Ravencolonial account settings"))
    api_key_help.grid(row=3, column=1, sticky=tk.W, padx=10, pady=(0, 10))
    return 4


def _add_stealth_section(frame: nb.Frame, start_row: int) -> int:
    """Stealth checkboxes; returns next grid row."""
    row = start_row

    try:
        stealth_value = config.get_bool('ravencolonial_stealth_mode')
    except CONFIG_READ_ERRORS:
        stealth_value = False
    frame.stealth_var = tk.BooleanVar(value=stealth_value)
    nb.Checkbutton(
        frame, text=i18n.tr("Stealth: Fleet Carrier data"), variable=frame.stealth_var
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=5)
    row += 1
    nb.Label(
        frame,
        text=i18n.tr("When enabled, stops Fleet Carrier commodity and CAPI cargo sync to Ravencolonial"),
    ).grid(row=row, column=1, sticky=tk.W, padx=10, pady=(0, 5))
    row += 1

    try:
        stealth_ship = config.get_bool('ravencolonial_stealth_ship_cargo')
    except CONFIG_READ_ERRORS:
        stealth_ship = False
    frame.stealth_ship_cargo_var = tk.BooleanVar(value=stealth_ship)
    nb.Checkbutton(
        frame, text=i18n.tr("Stealth: commander ship cargo"), variable=frame.stealth_ship_cargo_var
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=5)
    row += 1
    nb.Label(
        frame,
        text=i18n.tr("When enabled, does not send your ship cargo hold or loadout snapshot to Ravencolonial"),
    ).grid(row=row, column=1, sticky=tk.W, padx=10, pady=(0, 5))
    row += 1

    try:
        stealth_construction = config.get_bool('ravencolonial_stealth_construction_reporting')
    except CONFIG_READ_ERRORS:
        stealth_construction = False
    frame.stealth_construction_var = tk.BooleanVar(value=stealth_construction)
    nb.Checkbutton(
        frame,
        text=i18n.tr("Stealth: all construction delivery reporting"),
        variable=frame.stealth_construction_var,
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=5)
    row += 1
    nb.Label(
        frame,
        text=i18n.tr(
            "When enabled, does not send colonization depot progress, contribution totals, "
            "or CargoDepot deliveries to Ravencolonial (journal-driven construction sync only)"
        ),
    ).grid(row=row, column=1, sticky=tk.W, padx=10, pady=(0, 10))
    return row + 1


def _add_update_section(frame: nb.Frame, start_row: int) -> int:
    """Update settings and version check; returns next grid row."""
    row = start_row
    nb.Label(frame, text=i18n.tr("Update Settings:"), font=('TkDefaultFont', 10, 'bold')).grid(
        row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 5)
    )
    row += 1

    frame.check_updates_var = tk.BooleanVar(value=PluginConfig.get_check_updates())
    nb.Checkbutton(
        frame, text=i18n.tr("Check for updates on startup"), variable=frame.check_updates_var
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=2)
    row += 1

    frame.autoupdate_var = tk.BooleanVar(value=PluginConfig.get_autoupdate())
    nb.Checkbutton(
        frame, text=i18n.tr("Automatically install updates"), variable=frame.autoupdate_var
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=2)
    row += 1

    frame.prerelease_var = tk.BooleanVar(value=PluginConfig.get_check_prerelease())
    nb.Checkbutton(
        frame, text=i18n.tr("Include pre-release versions"), variable=frame.prerelease_var
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=2)
    row += 1

    nb.Label(frame, text=i18n.tr("Auto-update requires EDMC restart to apply. Use cautiously.")).grid(
        row=row, column=1, sticky=tk.W, padx=10, pady=(0, 10)
    )
    row += 1

    frame.version_text = tk.StringVar(
        value=i18n.trf("Version: {version} (checking for updates...)", version=plugin_version)
    )
    frame.version_label = nb.Label(frame, textvariable=frame.version_text)
    frame.version_label.grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 5))
    row += 1

    frame.update_check_thread = Thread(target=lambda: _prefs_check_for_updates(frame), daemon=True)
    frame.update_check_thread.start()

    github_url = f"https://github.com/{version_check.GITHUB_REPO}"
    page_bg = "SystemWindow" if sys.platform == "win32" else ttk.Style().lookup("TLabel", "background")
    if HyperlinkLabel is not None:
        github_link = HyperlinkLabel(
            frame,
            text=github_url,
            url=github_url,
            underline=True,
            background=page_bg,
            foreground="blue",
        )
    else:
        github_link = nb.Label(frame, text=github_url)
        github_link['cursor'] = 'hand2'
        github_link.bind('<Button-1>', lambda _event: webbrowser.open(github_url))
    github_link.grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 10))
    frame._prefs_page_bg = page_bg
    return row + 1


def _add_overlay_theme_section(frame: nb.Frame, start_row: int) -> int:
    """Overlay theme combobox; returns next grid row."""
    from .overlay.themes import DEFAULT_OVERLAY_THEME_ID, overlay_theme_choices

    row = start_row
    nb.Label(
        frame,
        text=i18n.tr("Overlay Theme:"),
        font=("TkDefaultFont", 10, "bold"),
    ).grid(row=row, column=0, sticky=tk.W, padx=10, pady=(8, 2))

    try:
        saved_theme = config.get_str("ravencolonial_overlay_theme") or DEFAULT_OVERLAY_THEME_ID
    except CONFIG_READ_ERRORS:
        saved_theme = DEFAULT_OVERLAY_THEME_ID
    theme_labels = [label for _tid, label in overlay_theme_choices()]
    theme_ids = [tid for tid, _label in overlay_theme_choices()]
    if saved_theme not in theme_ids:
        saved_theme = DEFAULT_OVERLAY_THEME_ID
    frame.overlay_theme_var = tk.StringVar(value=saved_theme)
    overlay_theme_combo = ttk.Combobox(
        frame,
        textvariable=frame.overlay_theme_var,
        values=theme_labels,
        state="readonly",
        width=28,
    )
    theme_display_to_id = {label: tid for tid, label in overlay_theme_choices()}
    theme_id_to_display = {tid: label for tid, label in overlay_theme_choices()}
    overlay_theme_combo.set(theme_id_to_display.get(saved_theme, theme_labels[0]))

    def _on_overlay_theme_selected(_event: object = None) -> None:
        display = overlay_theme_combo.get()
        tid = theme_display_to_id.get(display, DEFAULT_OVERLAY_THEME_ID)
        frame.overlay_theme_var.set(tid)

    overlay_theme_combo.bind("<<ComboboxSelected>>", _on_overlay_theme_selected)
    frame.overlay_theme_combo = overlay_theme_combo
    frame._theme_display_to_id = theme_display_to_id
    overlay_theme_combo.grid(row=row, column=1, sticky=tk.W, padx=10, pady=(8, 2))
    row += 1

    nb.Label(
        frame,
        text=i18n.tr(
            "Colors the in-game overlay: build name and trip lines, system name, commodity names, and numeric columns."
        ),
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 8))
    return row + 1


def _add_popout_recovery_section(frame: nb.Frame, start_row: int) -> int:
    """Popout window recovery control; returns next grid row."""
    row = start_row
    nb.Label(
        frame,
        text=i18n.tr("Popout Tracker window:"),
        font=("TkDefaultFont", 10, "bold"),
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(4, 5))
    row += 1
    nb.Label(
        frame,
        text=i18n.tr(
            "If the tracker is off-screen, center it on the EDMC display and bring it to the front."
        ),
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 4))
    row += 1
    nb.Button(
        frame,
        text=i18n.tr("Reset and show Popout Tracker"),
        command=lambda: _prefs_reset_popout_position(frame),
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 10))
    return row + 1


def _add_overlay_dependency_section(frame: nb.Frame, start_row: int) -> int:
    """Overlay dependency help and font install; returns next grid row."""
    row = start_row
    page_bg = getattr(frame, "_prefs_page_bg", "SystemWindow")

    nb.Label(
        frame,
        text=i18n.tr("Overlay dependency:"),
        font=("TkDefaultFont", 10, "bold"),
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(4, 5))
    row += 1

    nb.Label(
        frame,
        text=i18n.tr(
            "The build tracker overlay requires EDMC Modern Overlay to be installed and enabled in EDMC."
        ),
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 4))
    row += 1

    modern_overlay_url = "https://github.com/SweetJonnySauce/EDMCModernOverlay"
    if HyperlinkLabel is not None:
        overlay_dep_link = HyperlinkLabel(
            frame,
            text=modern_overlay_url,
            url=modern_overlay_url,
            underline=True,
            background=page_bg,
            foreground="blue",
        )
    else:
        overlay_dep_link = nb.Label(frame, text=modern_overlay_url)
        overlay_dep_link["cursor"] = "hand2"
        overlay_dep_link.bind("<Button-1>", lambda _event: webbrowser.open(modern_overlay_url))
    overlay_dep_link.grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 6))
    row += 1

    nb.Label(
        frame,
        text=i18n.tr("Click here to install custom fonts."),
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 4))
    row += 1

    prefs_plugin_dir = os.path.dirname(os.path.abspath(__file__))
    nb.Button(
        frame,
        text=i18n.tr("Install overlay fonts"),
        command=lambda: _prefs_install_overlay_fonts(frame, prefs_plugin_dir),
    ).grid(row=row, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 10))
    return row + 1


def plugin_prefs(parent: nb.Notebook, cmdr: Optional[str], is_beta: bool) -> nb.Frame:
    """
    Create settings page for the plugin.

    :param parent: The notebook parent
    :param cmdr: Commander name
    :param is_beta: Whether in beta
    :return: Settings frame
    """
    logger.info("Creating plugin preferences page")

    frame = nb.Frame(parent)

    nb.Label(
        frame,
        text=i18n.tr("Ravencolonial Plugin Settings"),
        font=('TkDefaultFont', 12, 'bold'),
    ).grid(row=0, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 20))

    next_row = _add_prefs_api_key_section(frame)
    next_row = _add_stealth_section(frame, next_row)
    next_row = _add_update_section(frame, next_row)
    next_row = _add_overlay_theme_section(frame, next_row)
    next_row = _add_popout_recovery_section(frame, next_row)
    next_row = _add_overlay_dependency_section(frame, next_row)

    nb.Button(
        frame,
        text=i18n.tr("Save Settings"),
        command=lambda: _prefs_save_settings(frame, cmdr),
    ).grid(row=next_row, column=0, columnspan=2, pady=20)

    if this:
        this._prefs_frame = frame

    logger.info("Plugin preferences page created successfully")
    return frame


def prefs_changed(cmdr: Optional[str], is_beta: bool) -> None:
    """
    Called when the EDMC settings dialog is dismissed with OK.
    Persist widget values before EDMC destroys the prefs tab (see PLUGINS.md).
    """
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
    if not this:
        return tk.Frame(parent, highlightthickness=0, borderwidth=0)

    # Use the UI manager to create the plugin frame
    frame = this.ui_manager.create_plugin_frame(parent)

    notice = getattr(this, "_edmc_compat_notice", None)
    if notice is not None and notice.level != "ok":
        _apply_edmc_compat_notice(notice)

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


def _cargo_total(cargo: Dict[str, int]) -> int:
    total = 0
    for value in cargo.values():
        try:
            total += int(value)
        except (TypeError, ValueError):
            pass
    return total


def _ship_delta_from_cargo_transfer_entry(entry: Dict[str, Any]) -> Dict[str, int]:
    diff: Dict[str, int] = {}
    transfers = entry.get("Transfers") or []
    if not isinstance(transfers, list):
        return diff
    for transfer in transfers:
        if not isinstance(transfer, dict):
            continue
        commodity = normalize_commodity_key(str(transfer.get("Type") or ""))
        if not commodity:
            continue
        try:
            count = int(transfer.get("Count") or 0)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        direction = str(transfer.get("Direction") or "").lower()
        if direction == "toship":
            diff[commodity] = diff.get(commodity, 0) + count
        elif direction == "tocarrier":
            diff[commodity] = diff.get(commodity, 0) - count
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


def _capi_fc_callsign_from_data(data: CAPIData) -> Optional[str]:
    if 'name' not in data or 'callsign' not in data['name']:
        logger.warning("CAPI FC data missing name/callsign")
        return None
    return data['name']['callsign']


def _capi_fc_cargo_totals_from_data(data: CAPIData) -> Dict[str, int]:
    cargo_list = data.get('cargo', [])
    cargo_totals: Dict[str, int] = {}
    for item in cargo_list:
        commodity = normalize_commodity_key(item.get('commodity', ''))
        qty = item.get('qty', 0)
        if commodity:
            cargo_totals[commodity] = cargo_totals.get(commodity, 0) + qty
    return cargo_totals


def _capi_fc_timestamp_from_data(data: CAPIData) -> Optional[Any]:
    """Return Frontier's timestamp for the FC CAPI payload when present."""
    try:
        return data.get("timestamp")
    except AttributeError:
        return None


def _capi_fc_refresh_overlay_if_selected(plugin: RavencolonialPlugin, market_id: Any) -> None:
    try:
        if not getattr(plugin, "overlay_carrier_tracking_enabled", False):
            return
        sel = str(getattr(plugin, "overlay_fc_selection", "all") or "all").strip().lower()
        if sel in ("all", ""):
            return
        try:
            if int(sel) == int(market_id):
                plugin.refresh_build_overlay()
        except (TypeError, ValueError):
            pass
    except OVERLAY_UI_ERRORS:
        pass


_JOURNAL_EVENT_HANDLERS: Dict[str, Callable[..., None]] = {
    'CarrierJumpRequest': lambda plugin, entry, **_kw: plugin._journal_handle_carrier_jump_request(entry),
    'CarrierJumpCancelled': lambda plugin, entry, **_kw: plugin._journal_handle_carrier_jump_cancelled(entry),
    'CarrierLocation': lambda plugin, entry, **_kw: plugin._journal_handle_carrier_location(entry),
    'Undocked': lambda plugin, entry, station='', **_kw: plugin._journal_handle_undocked(entry, station=station),
    'Location': lambda plugin, entry, station='', system='', **_kw: plugin._journal_handle_location(
        entry, station=station, system=system
    ),
    'CargoDepot': lambda plugin, entry, **_kw: plugin._journal_handle_cargo_depot(entry),
    'Market': lambda plugin, entry, **_kw: plugin._journal_handle_market(entry),
    'MarketBuy': lambda plugin, entry, state=None, **_kw: plugin._journal_handle_market_buy(entry, state=state),
    'MarketSell': lambda plugin, entry, state=None, **_kw: plugin._journal_handle_market_sell(entry, state=state),
    'CargoTransfer': lambda plugin, entry, state=None, **_kw: plugin._journal_handle_cargo_transfer(entry, state=state),
    'Cargo': lambda plugin, entry, state=None, **_kw: plugin._journal_handle_cargo(entry, state=state),
    'Loadout': lambda plugin, entry, state=None, **_kw: plugin._journal_handle_loadout(entry, state=state),
    'SetUserShipName': lambda plugin, entry, state=None, **_kw: plugin._journal_handle_set_user_ship_name(
        entry, state=state
    ),
    'ColonisationConstructionDepot': (
        lambda plugin, entry, **_kw: plugin._journal_handle_colonisation_construction_depot(entry)
    ),
    'ColonisationContribution': lambda plugin, entry, **_kw: plugin._journal_handle_colonisation_contribution(entry),
}


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
    if not this:
        return None

    this.remember_commander_from_hook(cmdr, source="journal_entry", authoritative=True)
    this.current_system = system
    this.current_station = station
    if state is not None:
        try:
            this._last_edmc_state = dict(state)
        except STATE_COPY_ERRORS:
            this._last_edmc_state = state
        this._refresh_ship_from_state(state)
        sa = state.get("SystemAddress")
        if sa is not None:
            this.set_current_system_address(sa)
        this._sync_docked_state_from_edmc_state(state, station=station)

    this.refresh_plan_sites_ui()

    logger.debug(f"Journal entry - cmdr: {cmdr}, system: {system}, station: {station}")

    this._journal_maybe_init_fc_handler(cmdr, state)

    event = entry.get('event')
    # Docked/Location handlers call this.set_current_system_address(entry.get('SystemAddress'))

    if event == 'Docked':
        this._journal_handle_docked(entry, station=station)
        this.update_create_button()
    elif event == 'CarrierStats' and this.fc_handler:
        this._journal_handle_carrier_stats(entry)
    else:
        handler = _JOURNAL_EVENT_HANDLERS.get(event)
        if handler:
            handler(this, entry, state=state, station=station, system=system)

    return None


def cmdr_data(data: CAPIData, is_beta: bool) -> Optional[str]:
    """
    EDMC hook: fresh ``/profile`` bundle (plus ``marketdata`` / ``shipdata`` when present).
    Cached to ``<plugin>/capi_cache/`` for analysis; no gameplay side effects.
    """
    try:
        capi_cache.write("cmdr_data", data, is_beta)
    except FILE_IO_ERRORS as e:
        logger.debug("CAPI cmdr_data cache skipped: %s", e)
    if this:
        this.remember_commander_from_hook(
            _cmdr_name_from_capi_data(data),
            source="cmdr_data",
            authoritative=False,
        )
    return None


def cmdr_data_legacy(data: CAPIData, is_beta: bool) -> Optional[str]:
    """EDMC hook: Legacy-galaxy CAPI profile bundle — same cache treatment as ``cmdr_data``."""
    try:
        capi_cache.write("cmdr_data_legacy", data, is_beta)
    except FILE_IO_ERRORS as e:
        logger.debug("CAPI cmdr_data_legacy cache skipped: %s", e)
    if this:
        this.remember_commander_from_hook(
            _cmdr_name_from_capi_data(data),
            source="cmdr_data_legacy",
            authoritative=False,
        )
    return None


def _capi_fc_market_id_for_callsign(plugin: RavencolonialPlugin, callsign: str) -> Optional[Any]:
    market_id = plugin.fc_handler.get_market_id_by_callsign(callsign)
    if not market_id:
        logger.warning(f"Cannot find market ID for FC callsign {callsign} - FC may not be linked")
        return None
    logger.info(f"Matched CAPI callsign {callsign} to marketId {market_id}")
    return market_id


def _capi_fc_cache_capacity_and_nudge_overlay(
    plugin: RavencolonialPlugin, market_id: Any, data: CAPIData
) -> None:
    try:
        plugin.fc_handler.update_fc_capacity_from_capi(market_id, data)
    except (TypeError, ValueError, AttributeError, KeyError):
        logger.warning("owner capacity cache from CAPI skipped", exc_info=True)
    _capi_fc_refresh_overlay_if_selected(plugin, market_id)


def capi_fleetcarrier(data: CAPIData) -> Optional[str]:
    """
    Handle Fleet Carrier CAPI data from Frontier.
    Called when EDMC fetches fresh FC data after CarrierStats journal events.

    :param data: CAPIData object with FC information
    :return: Optional status message
    """
    try:
        capi_cache.write("fleetcarrier", data, None)
    except FILE_IO_ERRORS as e:
        logger.debug("CAPI fleetcarrier cache skipped: %s", e)
    if this:
        this.remember_commander_from_hook(
            getattr(data, "request_cmdr", None),
            source="capi_fleetcarrier",
            authoritative=False,
        )

    if not this or not this.fc_handler:
        return None

    try:
        callsign = _capi_fc_callsign_from_data(data)
        if not callsign:
            return None

        logger.info(f"Received CAPI data for Fleet Carrier: {callsign}")

        market_id = _capi_fc_market_id_for_callsign(this, callsign)
        if not market_id:
            return None

        _capi_fc_cache_capacity_and_nudge_overlay(this, market_id, data)

        if this.fc_handler.stealth_mode:
            logger.info(f"Stealth mode enabled - ignoring CAPI data for FC {callsign}")
            return None

        cargo_list = data.get('cargo', [])
        if not cargo_list:
            logger.info(f"No cargo data in CAPI response for FC {callsign}")
            return None

        cargo_totals = _capi_fc_cargo_totals_from_data(data)
        logger.info(
            "CAPI FC cargo for %s: %s commodity types, %s total units",
            callsign,
            len(cargo_totals),
            sum(cargo_totals.values()),
        )
        logger.debug(f"CAPI cargo details: {cargo_totals}")

        this.fc_handler.update_fc_cargo_from_capi(
            market_id,
            cargo_totals,
            capi_timestamp=_capi_fc_timestamp_from_data(data),
        )

    except (TypeError, ValueError, AttributeError, KeyError) as e:
        logger.error("Error processing CAPI FC data: %s", e, exc_info=True)

    return None


def open_url(url: str):
    """Open URL in browser"""
    webbrowser.open(url)


def open_project_link():
    """Open the existing project in browser"""
    if this and this.current_build_id:
        url = f"https://ravencolonial.com/#build={this.current_build_id}"
        logger.info(f"Opening project page: {url}")
        open_url(url)


def open_create_dialog(parent):
    """Open the Create Project dialog"""
    if this:
        try:
            create_project_dialog.CreateProjectDialog(parent, this)
        except (ImportError, OVERLAY_UI_ERRORS, tk.TclError, AttributeError, TypeError, ValueError) as e:
            logger.error(f"Failed to open create dialog: {e}", exc_info=True)
            messagebox.showerror(
                i18n.tr("Error"),
                i18n.trf("Failed to open dialog: {detail}", detail=str(e)),
            )
