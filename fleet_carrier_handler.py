"""
Fleet Carrier Handler for Ravencolonial EDMC Plugin

This module handles Fleet Carrier commodity tracking and updates to Ravencolonial,
following the same logic as SrvSurvey.
"""

import logging
import os
import json
import time
import tkinter as tk
from typing import Any, Dict, List, Mapping, Optional

from config import appname

from .api.client import normalize_commodity_key
from .fc_jump_timer import FleetCarrierJumpTracker
from .exc_utils import CONFIG_READ_ERRORS, HTTP_CLIENT_ERRORS, JSON_LOAD_ERRORS, OVERLAY_UI_ERRORS
try:
    from .log_utils import configure_standalone_logger
except ImportError:  # pragma: no cover - standalone test/module loading
    from log_utils import configure_standalone_logger


def _commander_in_srv(state: Optional[Mapping[str, Any]]) -> bool:
    """Match SrvSurvey ActiveVehicle.SRV: EDMC state ShipType while driving an SRV."""
    if not state:
        return False
    st = str(state.get("ShipType") or "").lower()
    return "buggy" in st


def _coerce_market_id(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _capacity_block_from_capi(capi_data: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    for key in ("capacity", "Capacity"):
        val = capi_data.get(key)
        if isinstance(val, Mapping):
            return val
    return None


def _free_total_from_capacity_block(cap_block: Mapping[str, Any]) -> tuple[Any, Any]:
    free: Any = None
    total: Any = None
    for fk in ("freeSpace", "FreeSpace"):
        if fk in cap_block:
            free = cap_block[fk]
            break
    for total_key in ("totalCapacity", "TotalCapacity", "cargoSpaceTotal"):
        if total_key in cap_block:
            total = cap_block[total_key]
            break
    return free, total


def _free_total_from_space_usage(capi_data: Mapping[str, Any]) -> tuple[Any, Any]:
    su = capi_data.get("SpaceUsage") or capi_data.get("spaceUsage") or {}
    if not isinstance(su, Mapping):
        return None, None
    free = su.get("FreeSpace") or su.get("freeSpace")
    total = su.get("TotalCapacity") or su.get("totalCapacity")
    return free, total


def _callsign_from_capi_payload(capi_data: Mapping[str, Any]) -> str:
    try:
        name = capi_data.get("name")
        if isinstance(name, Mapping):
            cs = str(name.get("callsign") or "").upper()
            if cs:
                return cs
        return str(capi_data.get("callsign") or "").upper()
    except (TypeError, ValueError, AttributeError, KeyError):
        return ""


def _extract_capi_capacity_values(capi_data: Mapping[str, Any]) -> tuple[Any, Any]:
    if not isinstance(capi_data, Mapping):
        return None, None

    cap_block = _capacity_block_from_capi(capi_data)
    free: Any = None
    total: Any = None
    if cap_block:
        free, total = _free_total_from_capacity_block(cap_block)
    if free is None:
        space_free, space_total = _free_total_from_space_usage(capi_data)
        free = space_free
        if total is None:
            total = space_total
    if free is None:
        free = capi_data.get("freeSpace") or capi_data.get("FreeSpace")
    return free, total


# Use EDMC-compliant logger namespace
plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f'{appname}.{plugin_name}.fc')
configure_standalone_logger(logger, propagate=False)


class FleetCarrierHandler:
    """Handles Fleet Carrier commodity tracking and server updates"""

    def __init__(self, api_client):
        """
        Initialize the Fleet Carrier handler

        :param api_client: The main plugin instance with API methods
        """
        self.api_client = api_client
        self.linked_fcs: Dict[int, Dict[str, Any]] = {}  # marketId -> FC data
        self.update_eligible_fc_market_ids: set[int] = set()
        self.callsign_to_market_id: Dict[str, int] = {}  # callsign -> marketId mapping
        self.current_station_type = None
        self.current_market_id = None
        self.current_carrier_market_id: Optional[int] = None
        self.last_station_services: Optional[List[Any]] = None
        self.skip_next_cargo_event = False
        self.squadron_cmdr_cargo_baseline_ready = False
        self.stealth_mode = False
        self.capi_received_fcs = set()  # Track FCs that have received CAPI data this session
        # marketId -> owner CAPI / CarrierStats capacity snapshot (local only).
        self.owner_capacities: Dict[int, Dict[str, Any]] = {}
        self.owner_capacity_cache_path: Optional[str] = None
        self.fc_cargo_refresh_timestamps: Dict[int, float] = {}
        self.fc_cargo_refresh_cooldown_seconds = 60
        self._baseline_done: set[int] = set()  # marketIds with dock baseline this session
        self.jump_tracker = FleetCarrierJumpTracker(
            schedule_after=self._schedule_ui_after,
            on_state_changed=self._on_jump_state_changed,
        )
        self._overlay_jump_tick_id: Optional[str] = None

    def _schedule_ui_after(self, delay_ms: int, callback) -> Optional[str]:
        plugin = self.api_client
        schedule = getattr(plugin, "schedule_after", None)
        if callable(schedule):
            return schedule(max(0, int(delay_ms)), callback)
        frame = getattr(plugin, "frame", None)
        if frame is None:
            return None
        try:
            return frame.after(max(0, int(delay_ms)), callback)
        except tk.TclError:
            return None

    def _on_jump_state_changed(self) -> None:
        plugin = self.api_client
        if not plugin:
            return
        try:
            plugin.refresh_build_overlay(force=True)
        except OVERLAY_UI_ERRORS as exc:
            logger.warning("Overlay refresh after FC jump state change failed: %s", exc)
        self._schedule_overlay_jump_tick()

    def _schedule_overlay_jump_tick(self) -> None:
        plugin = self.api_client
        frame = getattr(plugin, "frame", None)
        if frame is None:
            return
        if self._overlay_jump_tick_id:
            try:
                frame.after_cancel(self._overlay_jump_tick_id)
            except tk.TclError:
                pass
            self._overlay_jump_tick_id = None
        if not self.jump_tracker.is_active():
            return

        def tick() -> None:
            self._overlay_jump_tick_id = None
            if not self.jump_tracker.is_active():
                return
            try:
                plugin.refresh_build_overlay(force=True)
            except OVERLAY_UI_ERRORS as exc:
                logger.warning("Overlay jump tick refresh failed: %s", exc)
            if self.jump_tracker.is_active():
                self._schedule_overlay_jump_tick()

        self._overlay_jump_tick_id = plugin.schedule_after(1000, tick)

    def handle_jump_requested(self, entry: Mapping[str, Any]) -> bool:
        return self.jump_tracker.handle_jump_requested(entry)

    def handle_jump_cancelled(self, entry: Mapping[str, Any]) -> bool:
        return self.jump_tracker.handle_jump_cancelled(entry)

    def handle_carrier_location(self, entry: Mapping[str, Any]) -> bool:
        return self.jump_tracker.handle_carrier_location(entry)

    def overlay_jump_footer_lines(self, *, prefer_market_id: Optional[int] = None) -> List[str]:
        from .overlay.fc_jump_l10n import format_fc_jump_overlay_lines

        preferred = self.current_carrier_market_id if self.current_carrier_market_id is not None else prefer_market_id

        return self.jump_tracker.overlay_footer_lines(
            prefer_market_id=preferred,
            line_formatter=format_fc_jump_overlay_lines,
        )

    def configure_owner_capacity_cache(self, plugin_dir: str) -> None:
        """Load persistent owner freeSpace cache from the plugin directory."""
        self.owner_capacity_cache_path = os.path.join(plugin_dir, "fc_owner_capacity_cache.json")
        self._load_owner_capacity_cache()

    def _load_owner_capacity_cache(self) -> None:
        path = self.owner_capacity_cache_path
        if not path or not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except JSON_LOAD_ERRORS as e:
            logger.warning("Could not load FC owner capacity cache %s: %s", path, e)
            return
        entries = raw.get("capacities") if isinstance(raw, dict) else raw
        if not isinstance(entries, Mapping):
            return
        loaded = 0
        for market_raw, cap_raw in entries.items():
            mid = _coerce_market_id(market_raw)
            if mid is None or not isinstance(cap_raw, Mapping):
                continue
            try:
                free_i = int(cap_raw.get("freeSpace"))
            except (TypeError, ValueError):
                continue
            total_i = None
            if cap_raw.get("totalCapacity") is not None:
                try:
                    total_i = int(cap_raw.get("totalCapacity"))
                except (TypeError, ValueError):
                    total_i = None
            self.owner_capacities[mid] = {
                "freeSpace": free_i,
                "callsign": str(cap_raw.get("callsign") or "").strip().upper(),
                "totalCapacity": total_i,
                "updated": cap_raw.get("updated"),
            }
            loaded += 1
        if loaded:
            logger.info("Loaded %s FC owner capacity cache entr%s", loaded, "y" if loaded == 1 else "ies")

    def _save_owner_capacity_cache(self) -> None:
        path = self.owner_capacity_cache_path
        if not path:
            return
        payload = {
            "version": 1,
            "capacities": {
                str(mid): {
                    "freeSpace": int(cap.get("freeSpace")),
                    "callsign": str(cap.get("callsign") or "").strip().upper(),
                    "totalCapacity": cap.get("totalCapacity"),
                    "updated": cap.get("updated"),
                }
                for mid, cap in sorted(self.owner_capacities.items())
                if isinstance(cap, Mapping) and cap.get("freeSpace") is not None
            },
        }
        tmp_path = f"{path}.tmp"
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
                f.write("\n")
            os.replace(tmp_path, path)
        except JSON_LOAD_ERRORS as e:
            logger.warning("Could not save FC owner capacity cache %s: %s", path, e)
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass

    def _remember_owner_capacity(
        self,
        market_id: int,
        free_space: int,
        *,
        callsign: str = "",
        total_capacity: Optional[int] = None,
        source: str,
    ) -> None:
        mid = int(market_id)
        existing = self.owner_capacities.get(mid) or {}
        old_free = existing.get("freeSpace")
        cap = {
            "freeSpace": int(free_space),
            "callsign": (callsign or str(existing.get("callsign") or "")).strip().upper(),
            "totalCapacity": total_capacity if total_capacity is not None else existing.get("totalCapacity"),
            "updated": time.time(),
        }
        self.owner_capacities[mid] = cap
        if old_free != cap["freeSpace"]:
            self._save_owner_capacity_cache()
            logger.info(
                "Cached owner capacity (%s) for FC marketId %s: freeSpace=%s",
                source,
                mid,
                cap["freeSpace"],
            )

    def set_stealth_mode(self, enabled: bool):
        """Enable or disable stealth mode"""
        self.stealth_mode = enabled
        if enabled:
            logger.info("Fleet Carrier stealth mode enabled - commodity data will not be sent to Ravencolonial")
        else:
            logger.info("Fleet Carrier stealth mode disabled - commodity data will be sent to Ravencolonial")

    def _linked_fcs_from_active_projects(self, cmdr_name: str) -> Dict[int, Dict[str, Any]]:
        """Return FCs linked to the commander's active projects, keyed by marketId."""
        try:
            projects = self.api_client.get_commander_projects(cmdr_name)
        except HTTP_CLIENT_ERRORS as e:
            logger.warning("Could not load active commander projects for FC eligibility: %s", e, exc_info=True)
            return {}
        if not isinstance(projects, list):
            logger.debug("Commander active projects payload was not a list: %r", type(projects).__name__)
            return {}

        found: Dict[int, Dict[str, Any]] = {}
        for project in projects:
            if not isinstance(project, Mapping):
                continue
            linked = project.get("linkedFC")
            if not isinstance(linked, list):
                continue
            build_id = project.get("buildId") or project.get("buildID") or project.get("id")
            for fc in linked:
                if not isinstance(fc, Mapping):
                    continue
                mid = _coerce_market_id(fc.get("marketId") if fc.get("marketId") is not None else fc.get("MarketID"))
                if mid is None:
                    continue
                entry = dict(fc)
                entry["marketId"] = mid
                entry.setdefault("cargo", {})
                entry["cargoSource"] = entry.get("cargoSource") or "active_project_linked_fc"
                if build_id is not None:
                    entry["eligibleFromBuildId"] = str(build_id)
                found.setdefault(mid, entry)
        return found

    def _load_stealth_mode_setting(self) -> bool:
        try:
            from config import config
            return config.get_bool('ravencolonial_stealth_mode')
        except CONFIG_READ_ERRORS:
            return False

    def _merge_active_project_fcs(self, active_project_fcs: Dict[int, Dict[str, Any]]) -> None:
        for market_id, fc in active_project_fcs.items():
            if market_id in self.linked_fcs:
                existing = self.linked_fcs[market_id]
                for key, value in fc.items():
                    if key not in existing or existing.get(key) in (None, "", [], {}):
                        existing[key] = value
                existing.setdefault("eligibleViaActiveProject", True)
                continue
            self.linked_fcs[market_id] = dict(fc)
            self.linked_fcs[market_id]["eligibleViaActiveProject"] = True

    def _bootstrap_linked_fc_cargo_snapshots(self) -> None:
        now = time.time()
        for market_id, fc in self.linked_fcs.items():
            if fc.get("cargoSource") == "active_project_linked_fc" and not fc.get("cargo"):
                continue
            cargo = fc.get("cargo") if isinstance(fc.get("cargo"), dict) else {}
            self.replace_fc_cargo_manifest(
                int(market_id),
                cargo,
                source="raven_colonial_api",
                timestamp=fc.get("cargoUpdatedAt") or fc.get("cargoSnapshotTimestamp") or now,
            )

    def _rebuild_callsign_to_market_id(self) -> None:
        self.callsign_to_market_id = {}
        for market_id, fc in self.linked_fcs.items():
            callsign = fc.get('name', '').upper()
            if not callsign:
                continue
            self.callsign_to_market_id[callsign] = market_id
            self.jump_tracker.note_linked_market_id(int(market_id), callsign=callsign)
            logger.debug(f"Mapped callsign {callsign} to marketId {market_id}")

    def _log_fc_initialization_summary(
        self,
        cmdr_name: str,
        all_fcs: List[Any],
        active_project_fcs: Dict[int, Dict[str, Any]],
    ) -> None:
        if len(self.linked_fcs) == 0:
            logger.info(
                "No Fleet Carriers linked for commander %s. "
                "To link a Fleet Carrier, visit Ravencolonial.com",
                cmdr_name,
            )
            return

        logger.info(
            "Loaded %s Fleet Carrier(s) eligible for cargo updates "
            "(%s profile-linked, %s active-project-linked)",
            len(self.linked_fcs),
            len(all_fcs),
            len(active_project_fcs),
        )
        for market_id, fc in self.linked_fcs.items():
            fc_name = fc.get('displayName', fc.get('name', 'Unknown'))
            cargo = fc.get('cargo', {})
            total_cargo = sum(cargo.values()) if cargo else 0
            logger.info(
                "FC %s (%s): %s commodity types, %s total units (server baseline)",
                market_id,
                fc_name,
                len(cargo),
                total_cargo,
            )
        logger.info(f"Initial cargo state loaded from Ravencolonial API for {len(self.linked_fcs)} FCs")

    def initialize_fcs(self, cmdr_name: str):
        """Initialize Fleet Carrier data for the commander"""
        try:
            logger.info(f"Initializing Fleet Carriers for commander: {cmdr_name}")

            self.stealth_mode = self._load_stealth_mode_setting()
            if self.stealth_mode:
                logger.info("Fleet Carrier stealth mode is enabled")

            # Get all FCs linked to this commander from Ravencolonial API
            # This gives us the current server-side cargo state as initial baseline
            all_fcs = self.api_client.api_client.get_all_cmdr_fcs(cmdr_name)

            # Store as dictionary by marketId for easy lookup
            self.linked_fcs = {int(fc['marketId']): dict(fc) for fc in all_fcs}
            active_project_fcs = self._linked_fcs_from_active_projects(cmdr_name)
            self._merge_active_project_fcs(active_project_fcs)
            self.update_eligible_fc_market_ids = set(self.linked_fcs.keys())
            self._bootstrap_linked_fc_cargo_snapshots()
            self._rebuild_callsign_to_market_id()
            self._log_fc_initialization_summary(cmdr_name, all_fcs, active_project_fcs)

            return True
        except HTTP_CLIENT_ERRORS as e:
            logger.error("Failed to initialize Fleet Carriers: %s", e, exc_info=True)
            return False

    def is_update_eligible_fc(self, market_id: Any) -> bool:
        """Return True only for profile-linked FCs loaded for this commander."""
        mid = _coerce_market_id(market_id)
        return mid is not None and mid in self.update_eligible_fc_market_ids

    def _normalize_cargo_manifest(self, cargo: Mapping[str, Any]) -> Dict[str, int]:
        normalized: Dict[str, int] = {}
        for raw_key, raw_value in (cargo or {}).items():
            key = normalize_commodity_key(str(raw_key))
            if not key:
                continue
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                continue
            if value > 0:
                normalized[key] = normalized.get(key, 0) + value
        return normalized

    def replace_fc_cargo_manifest(
        self,
        market_id: int,
        cargo: Mapping[str, Any],
        source: str,
        timestamp: Any = None,
    ) -> Dict[str, int]:
        """Replace a carrier cargo manifest with an authoritative full snapshot."""
        mid = _coerce_market_id(market_id)
        if mid is None:
            return {}
        normalized = self._normalize_cargo_manifest(cargo)
        fc = self.linked_fcs.setdefault(mid, {"marketId": mid})
        fc["cargo"] = normalized
        fc["cargoSource"] = source
        fc["cargoUpdatedAt"] = timestamp if timestamp is not None else time.time()
        fc["cargoSnapshotTimestamp"] = fc["cargoUpdatedAt"]
        logger.debug(
            "FC cargo manifest replaced: market_id=%s source=%s timestamp=%s commodities=%s total=%s",
            mid,
            source,
            fc["cargoUpdatedAt"],
            len(normalized),
            sum(normalized.values()),
        )
        return normalized

    def apply_fc_cargo_delta(
        self,
        market_id: int,
        commodity: str,
        delta: int,
        source: str = "journal",
    ) -> Dict[str, int]:
        """Apply a journal/event cargo delta to the trusted local carrier cache."""
        mid = _coerce_market_id(market_id)
        if mid is None:
            return {}
        fc = self.linked_fcs.setdefault(mid, {"marketId": mid})
        cargo = self._normalize_cargo_manifest(fc.get("cargo") or {})
        key = normalize_commodity_key(commodity)
        if not key:
            return cargo
        old_qty = int(cargo.get(key, 0))
        new_qty = max(0, old_qty + int(delta))
        if new_qty > 0:
            cargo[key] = new_qty
        else:
            cargo.pop(key, None)
        fc["cargo"] = cargo
        fc["cargoSource"] = source
        fc["cargoUpdatedAt"] = time.time()
        logger.debug(
            "FC cargo delta applied: market_id=%s commodity=%s delta=%s old=%s new=%s source=%s",
            mid,
            key,
            delta,
            old_qty,
            new_qty,
            source,
        )
        return cargo

    def is_allowed_fc_refresh_context(self, trigger: str) -> bool:
        """Return whether the current event context may refresh FC cargo from the API."""
        trigger_key = str(trigger or "").strip().lower()
        if self.current_station_type == "FleetCarrier":
            return True
        plugin = getattr(self, "api_client", None)
        if bool(getattr(plugin, "is_construction_ship", False)):
            return True
        if trigger_key in {"construction_depot", "colonisationconstructiondepot"}:
            return True
        return False

    def can_refresh_fc_cargo_from_api(self, market_id: int, trigger: str) -> tuple[bool, str, float]:
        mid = _coerce_market_id(market_id)
        if mid is None:
            logger.debug(
                "FC cargo API refresh decision: market_id=%s trigger=%s allowed=%s reason=%s cooldown=%s",
                market_id,
                trigger,
                False,
                "invalid_market_id",
                0,
            )
            return False, "invalid_market_id", 0
        if not self.is_allowed_fc_refresh_context(trigger):
            logger.debug(
                "FC cargo API refresh decision: market_id=%s trigger=%s allowed=%s reason=%s cooldown=%s",
                mid,
                trigger,
                False,
                "context_not_allowed",
                0,
            )
            return False, "context_not_allowed", 0
        now = time.monotonic()
        last = self.fc_cargo_refresh_timestamps.get(mid)
        remaining = 0.0
        if last is not None:
            remaining = self.fc_cargo_refresh_cooldown_seconds - (now - last)
        if last is not None and remaining > 0:
            logger.debug(
                "FC cargo API refresh decision: market_id=%s trigger=%s allowed=%s reason=%s cooldown=%s",
                mid,
                trigger,
                False,
                "cooldown_active",
                remaining,
            )
            return False, f"cooldown_active_{remaining:.1f}s", remaining
        self.fc_cargo_refresh_timestamps[mid] = now
        logger.debug(
            "FC cargo API refresh decision: market_id=%s trigger=%s allowed=%s reason=%s cooldown=%s",
            mid,
            trigger,
            True,
            "allowed",
            0,
        )
        return True, "allowed", 0

    def _cache_is_weak(self, mid: int) -> bool:
        """Return True when local FC cargo is empty or not from a trusted full snapshot."""
        fc = self.linked_fcs.get(mid, {})
        cargo = self._normalize_cargo_manifest(fc.get("cargo") or {})
        if not cargo:
            return True
        source = str(fc.get("cargoSource") or "").strip().lower()
        return source in {"active_project_linked_fc", "journal", ""}

    def _needs_baseline(self, mid: int) -> bool:
        """Return True when this dock visit still needs a local Market manifest baseline."""
        if mid in self._baseline_done:
            return False
        return self._cache_is_weak(mid)

    def _manifests_differ(self, a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
        """Compare normalized cargo manifests."""
        return self._normalize_cargo_manifest(a) != self._normalize_cargo_manifest(b)

    def _journal_market_helpers(self):
        try:
            from .load import _elite_journal_dir, _recent_files
        except ImportError:  # pragma: no cover - standalone test/module loading
            from load import _elite_journal_dir, _recent_files
        return _elite_journal_dir, _recent_files

    def _recent_market_manifest_paths(self, journal_dir: str, limit: int = 1) -> List[str]:
        """Return newest market manifest paths (game writes market.json; also scan Market.*.json)."""
        _elite_journal_dir, _recent_files = self._journal_market_helpers()
        del _elite_journal_dir
        seen: set[str] = set()
        paths: List[str] = []
        for pattern in ("Market.*.json", "market.json", "Market.json"):
            for path in _recent_files(journal_dir, pattern, limit):
                if path not in seen:
                    seen.add(path)
                    paths.append(path)

        def file_mtime(path: str) -> float:
            try:
                return os.path.getmtime(path)
            except OSError:
                return -1.0

        paths.sort(key=file_mtime, reverse=True)
        return paths[:limit]

    def _cargo_from_market_payload(self, market_data: Mapping[str, Any]) -> Dict[str, int]:
        """Extract FC cargo totals from a Market.json Items/Commodities list."""
        items = market_data.get("Items") or market_data.get("Commodities") or []
        if not isinstance(items, list):
            return {}
        cargo: Dict[str, int] = {}
        for item in items:
            if not isinstance(item, Mapping):
                continue
            commodity = normalize_commodity_key(str(item.get("Name") or ""))
            if not commodity:
                continue
            stock_raw = item.get("Stock", item.get("stock", 0))
            try:
                stock = int(stock_raw)
            except (TypeError, ValueError):
                continue
            if stock <= 0:
                continue
            is_producer = bool(item.get("Producer", item.get("producer", False)))
            is_consumer = bool(item.get("Consumer", item.get("consumer", False)))
            if is_producer or (not is_producer and not is_consumer):
                cargo[commodity] = cargo.get(commodity, 0) + stock
        return self._normalize_cargo_manifest(cargo)

    def _read_market_manifest(self, mid: int) -> Optional[Dict[str, int]]:
        """Read the newest local Market manifest for a docked FC marketId."""
        _elite_journal_dir, _ = self._journal_market_helpers()
        journal_dir = _elite_journal_dir()
        if not journal_dir:
            logger.debug("dock_baseline: no journal directory for marketId=%s", mid)
            return None

        for attempt in range(3):
            paths = self._recent_market_manifest_paths(journal_dir, limit=1)
            if not paths:
                if attempt < 2:
                    time.sleep(1)
                    continue
                logger.debug("dock_baseline: no market manifest files for marketId=%s", mid)
                return None

            market_path = paths[0]
            try:
                with open(market_path, "r", encoding="utf-8") as handle:
                    market_data = json.load(handle)
            except (OSError, json.JSONDecodeError) as exc:
                logger.debug(
                    "dock_baseline: could not read %s for marketId=%s (attempt %s): %s",
                    market_path,
                    mid,
                    attempt + 1,
                    exc,
                )
                if attempt < 2:
                    time.sleep(1)
                    continue
                return None

            file_mid = _coerce_market_id(market_data.get("MarketID"))
            if file_mid is not None and file_mid != mid:
                logger.debug(
                    "dock_baseline: manifest MarketID=%s does not match docked marketId=%s",
                    file_mid,
                    mid,
                )
                return None

            cargo = self._cargo_from_market_payload(market_data)
            if cargo or market_data.get("Items") is not None or market_data.get("Commodities") is not None:
                return cargo

            if attempt < 2:
                time.sleep(1)

        return None

    def _maybe_set_dock_baseline(self, mid: int, *, attempt: int = 0, max_attempts: int = 3) -> None:
        """Establish dock baseline from local Market.json when cache is empty or weak."""
        if not self._needs_baseline(mid):
            return
        if self.stealth_mode:
            logger.debug("dock_baseline: stealth mode enabled, skipping marketId=%s", mid)
            self._baseline_done.add(mid)
            return

        fresh = self._read_market_manifest(mid)
        if fresh is None:
            if attempt + 1 < max_attempts:
                def retry() -> None:
                    self._maybe_set_dock_baseline(mid, attempt=attempt + 1, max_attempts=max_attempts)

                if self._schedule_ui_after(1000, retry) is None:
                    self._maybe_set_dock_baseline(mid, attempt=attempt + 1, max_attempts=max_attempts)
                return
            logger.debug("dock_baseline: no manifest available for marketId=%s after retries", mid)
            self._baseline_done.add(mid)
            return

        current = self._normalize_cargo_manifest(self.linked_fcs.get(mid, {}).get("cargo") or {})
        changed = self._manifests_differ(current, fresh)
        if changed:
            self.replace_fc_cargo_manifest(mid, fresh, source="local_dock_baseline")
            self._update_fc_cargo_async(mid, fresh)
            logger.info("dock_baseline: set for %s (changed=%s)", mid, True)
        else:
            logger.info("dock_baseline: skipped (no diff) for %s", mid)
        self._baseline_done.add(mid)

    def clear_dock_context(self) -> None:
        """Call on Undocked — clears FC dock tracking (SrvSurvey lastDocked parity)."""
        if self.current_market_id is not None:
            self._baseline_done.discard(self.current_market_id)
        self.current_station_type = None
        self.current_market_id = None
        self.last_station_services = None
        self.squadron_cmdr_cargo_baseline_ready = False

    def _refresh_station_services(self, entry: Dict[str, Any]) -> None:
        services = entry.get("StationServices")
        if services is not None:
            self.last_station_services = list(services)

    def _services_has_squadron_bank(self) -> bool:
        if not self.last_station_services:
            return False
        for s in self.last_station_services:
            if str(s) == "squadronBank":
                return True
        return False

    def is_docked_linked_squadron_fc(self) -> bool:
        return (
            self.current_station_type == "FleetCarrier" and
            self.current_market_id is not None and
            self.is_update_eligible_fc(self.current_market_id) and
            self._services_has_squadron_bank()
        )

    def consume_skip_next_cargo_event(self) -> bool:
        if self.skip_next_cargo_event:
            self.skip_next_cargo_event = False
            return True
        return False

    def note_commander_full_cargo_snapshot(self) -> None:
        """After a full Cargo journal with inventory — safe baseline for squadron FC diff."""
        if self.is_docked_linked_squadron_fc():
            self.squadron_cmdr_cargo_baseline_ready = True

    def mark_skip_next_cargo_after_market_trade(self) -> None:
        """SrvSurvey: after MarketBuy/MarketSell on a squadron FC, ignore one following Cargo resync for FC diff."""
        if self.is_docked_linked_squadron_fc():
            self.skip_next_cargo_event = True
            logger.debug("Squadron FC: will skip next Cargo journal for FC cargo diff (Market trade follow-up)")

    def handle_squadron_cargo_resync_diff(self, cargo_diff_to_fc: Dict[str, int]) -> bool:
        """
        Apply inverted commander-cargo diff to FC (SrvSurvey onJournalEntry Cargo else-branch).
        cargo_diff_to_fc: commodity -> delta applied to FC (already sign-correct for POST/PATCH supply).
        """
        if self.stealth_mode or not cargo_diff_to_fc:
            return False
        mid = self.current_market_id
        if mid is None or not self.is_update_eligible_fc(mid):
            return False
        logger.info(f"Squadron FC {mid}: applying cargo diff to Ravencolonial: {cargo_diff_to_fc}")
        self._supply_fc_async(mid, cargo_diff_to_fc)
        return True

    def handle_docked_event(self, entry: Dict[str, Any]) -> bool:
        """
        Handle a Docked journal event

        :param entry: The journal entry data
        :return: True if this is a Fleet Carrier, False otherwise
        """
        station_type = entry.get('StationType', '')
        market_id = _coerce_market_id(entry.get('MarketID'))
        station_name = entry.get('StationName', '')

        logger.debug(f"handle_docked_event: station={station_name}, type={station_type}, marketID={market_id}")

        # Update current station info
        self.current_station_type = station_type
        self.current_market_id = market_id
        self._refresh_station_services(entry)

        logger.debug(
            f"Updated current_station_type={self.current_station_type}, current_market_id={self.current_market_id}")

        if station_type == 'FleetCarrier':
            logger.info(f"Docked at Fleet Carrier: {station_name} (MarketID: {market_id})")
            logger.debug(f"Linked FCs: {list(self.linked_fcs.keys())}")

            # Check if this is a linked FC
            if self.is_update_eligible_fc(market_id):
                logger.info("This is a linked Fleet Carrier - will track commodity changes")
                self._maybe_set_dock_baseline(market_id)
                return True
            else:
                logger.info(
                    f"Fleet Carrier {station_name} (MarketID: {market_id}) is not linked to commander in Ravencolonial")
                return True
        else:
            logger.debug(f"Docked at regular station: {station_name} (Type: {station_type})")
            return False

    def handle_marketbuy_event(self, entry: Dict[str, Any]) -> bool:
        """
        Handle a MarketBuy journal event - player bought from FC

        :param entry: The journal entry data
        :return: True if processed as Fleet Carrier purchase, False otherwise
        """
        if self.current_station_type != 'FleetCarrier':
            return False

        market_id = _coerce_market_id(entry.get('MarketID'))
        commodity = normalize_commodity_key(entry.get('Type') or '')
        count = entry.get('Count', 0)

        # Only process if this is a linked FC
        if not self.is_update_eligible_fc(market_id):
            logger.debug(f"MarketBuy for unlinked FC {market_id} - ignoring")
            return False

        # Check stealth mode
        if self.stealth_mode:
            logger.debug(f"MarketBuy for FC {market_id} - stealth mode enabled, ignoring")
            return False

        if not commodity:
            logger.debug("MarketBuy missing commodity Type, ignoring")
            return False

        logger.info(f"Buying {count}x {commodity} from FC {market_id}")

        # Buying from FC reduces FC cargo (negative supply)
        cargo_diff = {commodity: -count}
        self._supply_fc_async(market_id, cargo_diff)
        self.mark_skip_next_cargo_after_market_trade()
        return True

    def handle_marketsell_event(self, entry: Dict[str, Any]) -> bool:
        """
        Handle a MarketSell journal event - player sold to FC

        :param entry: The journal entry data
        :return: True if processed as Fleet Carrier sale, False otherwise
        """
        if self.current_station_type != 'FleetCarrier':
            return False

        market_id = _coerce_market_id(entry.get('MarketID'))
        commodity = normalize_commodity_key(entry.get('Type') or '')
        count = entry.get('Count', 0)

        # Only process if this is a linked FC
        if not self.is_update_eligible_fc(market_id):
            logger.debug(f"MarketSell for unlinked FC {market_id} - ignoring")
            return False

        # Check stealth mode
        if self.stealth_mode:
            logger.debug(f"MarketSell for FC {market_id} - stealth mode enabled, ignoring")
            return False

        if not commodity:
            logger.debug("MarketSell missing commodity Type, ignoring")
            return False

        logger.info(f"Selling {count}x {commodity} to FC {market_id}")

        # Selling to FC increases FC cargo (positive supply)
        cargo_diff = {commodity: count}
        self._supply_fc_async(market_id, cargo_diff)
        self.mark_skip_next_cargo_after_market_trade()
        return True

    def handle_cargotransfer_event(
        self, entry: Dict[str, Any], state: Optional[Mapping[str, Any]] = None
    ) -> bool:
        """
        Handle a CargoTransfer journal event - transfers between ship/carrier/SRV.
        Aligns with SrvSurvey Game.onJournalEntry(CargoTransfer): squadron FCs skip
        branch-A (tocarrier / SRV->ship) supply deltas; branch-B still updates FC.
        """
        logger.debug(
            f"handle_cargotransfer_event: current_station_type={self.current_station_type}, "
            f"current_market_id={self.current_market_id}"
        )

        if self.current_station_type != "FleetCarrier":
            logger.debug("Not at a Fleet Carrier, ignoring CargoTransfer")
            return False

        market_id = self.current_market_id
        logger.debug(f"Checking if FC {market_id} is update eligible: {self.is_update_eligible_fc(market_id)}")

        if not self.is_update_eligible_fc(market_id):
            logger.debug(f"FC {market_id} not update eligible")
            return False

        if self.stealth_mode:
            logger.debug(f"CargoTransfer for FC {market_id} - stealth mode enabled, ignoring")
            return False

        is_srv = _commander_in_srv(state)
        squadron = self._services_has_squadron_bank()
        transfers = entry.get("Transfers", [])
        cargo_diff: Dict[str, int] = {}

        for transfer in transfers:
            direction = (transfer.get("Direction") or "").lower()
            commodity = normalize_commodity_key(transfer.get("Type") or "")
            count = transfer.get("Count", 0)
            if not commodity or not count:
                continue

            # SrvSurvey branch A: (SRV && toship) || (MainShip && tocarrier) — cargo toward carrier / off-SRV to ship
            branch_a = (is_srv and direction == "toship") or (not is_srv and direction == "tocarrier")
            # Branch B: (SRV && tosrv) || (MainShip && toship) — cargo from carrier toward ship hold / into SRV
            branch_b = (is_srv and direction == "tosrv") or (not is_srv and direction == "toship")

            if branch_a:
                if not squadron:
                    cargo_diff[commodity] = cargo_diff.get(commodity, 0) + count
                    logger.debug(f"Transfer branch-A {count}x {commodity} (FC +)")
                else:
                    logger.debug(
                        f"Squadron FC: skip branch-A transfer delta for {commodity} x{count} "
                        f"(SrvSurvey uses Cargo diff instead)"
                    )
            elif branch_b:
                cargo_diff[commodity] = cargo_diff.get(commodity, 0) - count
                logger.debug(f"Transfer branch-B {count}x {commodity} (FC -)")

        if cargo_diff:
            logger.info(f"Cargo transfer for FC {market_id}: {cargo_diff}")
            self._supply_fc_async(market_id, cargo_diff)
            return True

        return False

    def _should_accept_capi_snapshot(
        self,
        market_id: int,
        existing_cargo: Dict[str, int],
        existing_source: str,
        server_time: Any,
        capi_timestamp: Any,
    ) -> tuple[bool, str]:
        if market_id in self.capi_received_fcs:
            return False, "already_received"
        if not existing_cargo:
            return True, "server_cargo_missing"
        if capi_timestamp is not None and server_time is not None and str(capi_timestamp) > str(server_time):
            return True, "capi_newer"
        if existing_source not in {"raven_colonial_api", "capi"} and capi_timestamp is not None:
            return True, "local_source_with_capi_timestamp"
        return False, "freshness_not_verified"

    def _log_capi_cargo_decision(
        self,
        mid: int,
        capi_timestamp: Any,
        server_time: Any,
        accepted: bool,
        reason: str,
        existing_cargo: Dict[str, int],
        cargo_totals: Dict[str, int],
    ) -> None:
        payload = {
            "commodities": len(existing_cargo),
            "total": sum(existing_cargo.values()),
        }
        new_payload = {
            "commodities": len(cargo_totals or {}),
            "total": sum(int(v) for v in (cargo_totals or {}).values()),
        }
        logger.debug(
            "FC CAPI cargo decision: market_id=%s capi_time=%s server_time=%s "
            "accepted=%s reason=%s old_cargo=%s new_cargo=%s",
            mid,
            capi_timestamp,
            server_time,
            accepted,
            reason,
            payload,
            new_payload,
        )

    def update_fc_cargo_from_capi(
        self,
        market_id: int,
        cargo_totals: Dict[str, int],
        capi_timestamp: Any = None,
    ):
        """
        Update FC cargo using data from Frontier CAPI.
        CAPI data significantly lags real-time, so we only use it for the initial
        snapshot on plugin load. After that, we rely on real-time journal events.

        :param market_id: Fleet Carrier market ID
        :param cargo_totals: Dictionary of commodity name -> total quantity
        """
        mid = int(market_id)
        existing = self.linked_fcs.get(mid) or self.linked_fcs.get(str(mid)) or {}
        existing_cargo = self._normalize_cargo_manifest(existing.get("cargo") or {})
        server_time = existing.get("cargoUpdatedAt") or existing.get("cargoSnapshotTimestamp")
        existing_source = str(existing.get("cargoSource") or "").strip().lower()
        accepted, reason = self._should_accept_capi_snapshot(
            market_id,
            existing_cargo,
            existing_source,
            server_time,
            capi_timestamp,
        )

        if reason == "already_received":
            logger.info(
                "Ignoring CAPI data for FC %s - already received initial snapshot, "
                "using real-time journal events instead",
                market_id,
            )
        self._log_capi_cargo_decision(
            mid,
            capi_timestamp,
            server_time,
            accepted,
            reason,
            existing_cargo,
            cargo_totals,
        )
        if not accepted:
            if reason != "already_received":
                logger.info(f"Skipping CAPI cargo for FC {market_id} - {reason}")
            return

        logger.info(f"Receiving initial CAPI snapshot for FC {market_id}")
        logger.debug(f"CAPI cargo totals: {cargo_totals}")

        self.replace_fc_cargo_manifest(mid, cargo_totals, source="capi", timestamp=capi_timestamp)
        try:
            self._maybe_mirror_selected_fc_cargo_and_refresh(mid)
        except OVERLAY_UI_ERRORS:
            # Overlay nudge is best-effort after CAPI cargo baseline.
            pass

        # Mark this FC as having received CAPI data
        self.capi_received_fcs.add(market_id)
        self._baseline_done.add(mid)

        # Update server with full cargo snapshot (initial state only)
        self._update_fc_cargo_async(market_id, cargo_totals)

    def _supply_fc_async(self, market_id: int, cargo_diff: Dict[str, int]):
        """Update FC cargo incrementally using the API queue"""
        for commodity, delta in (cargo_diff or {}).items():
            self.apply_fc_cargo_delta(market_id, commodity, delta, source="journal")
        try:
            self._maybe_mirror_selected_fc_cargo_and_refresh(int(market_id))
        except OVERLAY_UI_ERRORS:
            # Overlay nudge is best-effort before queued supply PATCH.
            pass
        self.api_client.queue_api_call(self._supply_fc, market_id, cargo_diff)

    def _supply_fc(self, market_id: int, cargo_diff: Dict[str, int]) -> bool:
        """Update FC cargo incrementally"""
        try:
            result = self.api_client.api_client.supply_fc(market_id, cargo_diff)
            if result:
                self.replace_fc_cargo_manifest(
                    int(market_id),
                    result,
                    source="raven_colonial_api",
                    timestamp=time.time(),
                )
                # Nudge the overlay (if this is the currently *selected specific* carrier)
                # so that the FC column deltas and any matching "> CALLSIGN Capacity" line update live.
                try:
                    self._maybe_mirror_selected_fc_cargo_and_refresh(int(market_id))
                except OVERLAY_UI_ERRORS:
                    # Overlay nudge is best-effort after journal/API cargo delta.
                    pass
                logger.info(f"Successfully updated FC {market_id} cargo")
                return True
            else:
                logger.error(f"Failed to update FC {market_id} cargo")
                return False
        except HTTP_CLIENT_ERRORS as e:
            logger.error("Exception updating FC cargo: %s", e, exc_info=True)
            return False

    def _update_fc_cargo_async(self, market_id: int, cargo: Dict[str, int]):
        """Replace entire FC cargo manifest using the API queue"""
        self.api_client.queue_api_call(self._update_fc_cargo, market_id, cargo)

    def _update_fc_cargo(self, market_id: int, cargo: Dict[str, int]) -> bool:
        """Replace entire FC cargo manifest"""
        try:
            result = self.api_client.api_client.update_fc_cargo(market_id, cargo)
            if result:
                self.replace_fc_cargo_manifest(
                    int(market_id),
                    result,
                    source="raven_colonial_api",
                    timestamp=time.time(),
                )
                try:
                    self._maybe_mirror_selected_fc_cargo_and_refresh(int(market_id))
                except OVERLAY_UI_ERRORS:
                    # Overlay nudge is best-effort after journal/API cargo delta.
                    pass
                logger.info(f"Successfully replaced FC {market_id} cargo")
                return True
            else:
                logger.error(f"Failed to replace FC {market_id} cargo")
                return False
        except HTTP_CLIENT_ERRORS as e:
            logger.error("Exception replacing FC cargo: %s", e, exc_info=True)
            return False

    def get_market_id_by_callsign(self, callsign: str) -> Optional[int]:
        """
        Look up the market ID for a Fleet Carrier by its callsign.
        Used to match CAPI data to the correct FC.

        :param callsign: Fleet Carrier callsign (e.g., "ABC-123")
        :return: Market ID if found, None otherwise
        """
        # Normalize callsign to uppercase for consistent lookup
        normalized_callsign = callsign.upper()
        market_id = self.callsign_to_market_id.get(normalized_callsign)

        if market_id:
            logger.debug(f"Found marketId {market_id} for callsign {callsign}")
        else:
            logger.warning(
                "No marketId found for callsign %s. Known callsigns: %s",
                callsign,
                list(self.callsign_to_market_id.keys()),
            )

        return market_id

    def update_fc_capacity_from_capi(self, market_id: int, capi_data: Mapping[str, Any]) -> None:
        """
        Cache owner-visible capacity (freeSpace) from a Frontier CAPI /fleetcarrier payload.
        This is local only (per session) and used to enrich the overlay capacity line for
        a selected carrier when the marketId matches the user's CAPI data.

        Accepts the full CAPI dict (or a normalized envelope containing 'capacity' / 'SpaceUsage').
        """
        if self.stealth_mode or not market_id:
            return
        free, total = _extract_capi_capacity_values(capi_data)
        if free is None:
            return
        try:
            free_i = int(free)
        except (TypeError, ValueError):
            return
        total_i: Optional[int] = None
        if total is not None:
            try:
                total_i = int(total)
            except (TypeError, ValueError):
                total_i = None
        cs = _callsign_from_capi_payload(capi_data) if isinstance(capi_data, Mapping) else ""
        self._remember_owner_capacity(
            int(market_id),
            free_i,
            callsign=cs,
            total_capacity=total_i,
            source="capi",
        )
        self.current_carrier_market_id = int(market_id)

    def update_fc_capacity_from_journal_stats(self, entry: Mapping[str, Any]) -> None:
        """
        Optional resilience: consume a journal CarrierStats entry directly (has SpaceUsage).
        """
        if self.stealth_mode or not isinstance(entry, Mapping):
            return
        try:
            market_id = entry.get("MarketID") or entry.get("CarrierID")
            if market_id is None:
                return
            market_id = int(market_id)
            callsign = str(entry.get("Callsign") or "").upper()
            su = entry.get("SpaceUsage") or entry.get("spaceUsage") or {}
            free = None
            total = None
            if isinstance(su, Mapping):
                free = su.get("FreeSpace") or su.get("freeSpace")
                total = su.get("TotalCapacity") or su.get("totalCapacity")
            if free is None:
                return
            free_i = int(free)
            total_i = None
            if total is not None:
                try:
                    total_i = int(total)
                except (TypeError, ValueError):
                    total_i = None
            self._remember_owner_capacity(
                market_id,
                free_i,
                callsign=callsign,
                total_capacity=total_i,
                source="journal",
            )
            self.current_carrier_market_id = market_id
            self.jump_tracker.register_carrier_stats(entry)
            if callsign:
                self.jump_tracker.note_linked_market_id(market_id, callsign=callsign)
        except (TypeError, ValueError, AttributeError, KeyError):
            # Never let a malformed CarrierStats packet break journal handling.
            logger.debug("CarrierStats capacity cache skipped for malformed entry", exc_info=True)

    def get_owned_callsign_for_market(self, market_id: int) -> Optional[str]:
        """Return the owner-visible callsign we saw for this marketId from CAPI/journal, if any."""
        cap = self.get_owner_capacity(market_id)
        if not cap:
            return None
        cs = cap.get("callsign")
        return str(cs).strip() or None

    def _overlay_selection_matches_market(self, plugin: Any, mid: int) -> bool:
        sel = str(getattr(plugin, "overlay_fc_selection", "all") or "all").strip().lower()
        if sel in ("all", ""):
            return True
        try:
            return int(sel) == mid
        except (TypeError, ValueError):
            return False

    def _market_in_overlay_linked_fcs(self, plugin: Any, mid: int) -> bool:
        linked = getattr(plugin, "overlay_project_linked_fcs", None) or []
        if not linked:
            return True
        linked_markets = set()
        for fc in linked:
            try:
                linked_markets.add(int(fc.get("marketId")))
            except (AttributeError, TypeError, ValueError):
                pass
        return mid in linked_markets

    def _overlay_cargo_for_market(self, mid: int) -> Dict[str, int]:
        cached = self.linked_fcs.get(mid) or self.linked_fcs.get(str(mid)) or {}
        raw = cached.get("cargo") or {}
        norm: Dict[str, int] = {}
        for k, v in raw.items():
            nk = normalize_commodity_key(str(k))
            if not nk:
                continue
            try:
                cnt = int(v)
            except (TypeError, ValueError):
                continue
            if cnt > 0:
                norm[nk] = norm.get(nk, 0) + cnt
        return norm

    def _maybe_mirror_selected_fc_cargo_and_refresh(self, market_id: int) -> None:
        """
        If overlay carrier tracking is on and the given market_id belongs to the
        current overlay carrier set, copy the latest cargo from linked_fcs into
        the overlay per-market map and refresh the HUD.

        This keeps specific-carrier, All, and Track All views in sync with
        journal deltas without fetching Raven Colonial during repaint.
        """
        p = getattr(self, "api_client", None)
        if not p:
            return
        try:
            if not getattr(p, "overlay_carrier_tracking_enabled", False):
                return
            mid = int(market_id)
            if not self._overlay_selection_matches_market(p, mid):
                return
            if not self._market_in_overlay_linked_fcs(p, mid):
                return
            current = dict(getattr(p, "overlay_fc_cargo_by_market", None) or {})
            current[mid] = self._overlay_cargo_for_market(mid)
            p.overlay_fc_cargo_by_market = current
            if hasattr(p, "refresh_build_overlay"):
                p.refresh_build_overlay()
        except OVERLAY_UI_ERRORS:
            # Best effort; never break journal/CAPI paths for the overlay nudge.
            pass

    def get_owner_capacity(self, market_id: int) -> Optional[Dict[str, Any]]:
        """Return the locally cached owner capacity for a marketId (from CAPI/CarrierStats), or None."""
        if not market_id:
            return None
        try:
            return self.owner_capacities.get(int(market_id))
        except (TypeError, ValueError):
            return None

    def get_linked_fc_summary(self) -> str:
        """Get a summary of linked Fleet Carriers"""
        if not self.linked_fcs:
            return "No linked Fleet Carriers"

        total_cargo = {}
        for fc in self.linked_fcs.values():
            fc_cargo = fc.get('cargo', {})
            for commodity, count in fc_cargo.items():
                total_cargo[commodity] = total_cargo.get(commodity, 0) + count

        summary = f"Linked Fleet Carriers: {len(self.linked_fcs)}\n"
        summary += f"Total Commodities: {len(total_cargo)}\n"
        if total_cargo:
            summary += "Cargo Summary:\n"
            for commodity, count in sorted(total_cargo.items()):
                if count > 0:
                    summary += f"  {commodity}: {count}\n"

        return summary
