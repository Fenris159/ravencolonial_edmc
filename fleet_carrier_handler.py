"""
Fleet Carrier Handler for Ravencolonial EDMC Plugin.

This module handles Fleet Carrier commodity tracking and updates to Ravencolonial,
following the same logic as SrvSurvey.
"""

import logging
import os
import json
import time
import tkinter as tk
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional

from config import appname

from .api.client import normalize_commodity_key
from .fc_jump_timer import FleetCarrierJumpTracker
from .carrier_cargo_tracking import CarrierShipCargoTracker, cargo_counts
from .pending_carrier_deliveries import CarrierCargoQueueState, CarrierCheckpointError, InventoryFrameSuperseded
from .exc_utils import CONFIG_READ_ERRORS, FILE_IO_ERRORS, HTTP_CLIENT_ERRORS, JSON_LOAD_ERRORS, OVERLAY_UI_ERRORS
try:
    from .log_utils import configure_standalone_logger
except ImportError:  # pragma: no cover - standalone test/module loading
    from log_utils import configure_standalone_logger


def _coerce_market_id(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _timestamp_to_epoch(value: Any) -> Optional[float]:
    """Normalize supported timestamp shapes to epoch seconds for comparisons."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        pass
    try:
        normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _timestamp_newer(candidate: Any, baseline: Any) -> bool:
    candidate_epoch = _timestamp_to_epoch(candidate)
    baseline_epoch = _timestamp_to_epoch(baseline)
    return candidate_epoch is not None and baseline_epoch is not None and candidate_epoch > baseline_epoch


def _fc_record_timestamp(fc: Mapping[str, Any]) -> Any:
    return fc.get("lastRefresh") or fc.get("cargoUpdatedAt") or fc.get("cargoSnapshotTimestamp")


def _fc_cache_timestamp(fc: Mapping[str, Any]) -> Any:
    return fc.get("cargoUpdatedAt") or fc.get("cargoSnapshotTimestamp")


def _fc_server_last_refresh(fc: Mapping[str, Any]) -> Any:
    return fc.get("lastRefresh")


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
    """Handles Fleet Carrier commodity tracking and server updates."""

    def __init__(self, api_client):
        """
        Initialize the Fleet Carrier handler.

        :param api_client: The main plugin instance with API methods
        """
        self.api_client = api_client
        self.initialized_cmdr: Optional[str] = None
        self.commander_name: Optional[str] = None
        self.initializing_cmdr: Optional[str] = None
        self.initialization_thread: Any = None
        self.initialization_attempts = 0
        self.next_initialization_retry = 0.0
        self._retired = False
        self.ship_cargo_tracker = CarrierShipCargoTracker()
        self._inventory_frame_id: Optional[int] = None
        self._inventory_frame_generation: Optional[int] = None
        self._inventory_lookup_captured = False
        self._inventory_lookup_frame_ids: set[int] = set()
        self._inventory_lookup_record_ids: set[int] = set()
        self._inventory_lookup_replacement_ids: set[int] = set()
        self._initialization_deltas: Dict[int, Dict[str, int]] = {}
        self._observed_initial_delivery_ids: set[int] = set()
        self._initial_inventory_release_depth = 0
        self._journal_inventory_depth = 0
        self._deferred_inventory_retries: set[int] = set()
        self._initialization_events: List[Callable[[], None]] = []
        deliveries = getattr(api_client, "pending_carrier_deliveries", None)
        cargo_queue = deliveries.cargo_queue_state() if deliveries is not None else CarrierCargoQueueState()
        self._cargo_state_lock = cargo_queue.lock
        self._pending_capi_updates = cargo_queue.snapshots
        self._pending_capi_recovery_ids = cargo_queue.snapshot_coverage
        self._pending_capi_times = cargo_queue.snapshot_times
        self._pending_capi_ownership = cargo_queue.snapshot_ownership
        self._snapshot_versions = cargo_queue.snapshot_versions
        self.linked_fcs: Dict[int, Dict[str, Any]] = {}  # marketId -> FC data
        self._acknowledged_fc_cargo: Dict[int, Dict[str, int]] = {}
        self._link_read_revision: Optional[int] = None
        self.update_eligible_fc_market_ids: set[int] = set()
        self.callsign_to_market_id: Dict[str, int] = {}  # callsign -> marketId mapping
        self.current_station_type = None
        self.current_market_id = None
        self.current_carrier_market_id: Optional[int] = None
        self.last_station_services: Optional[List[Any]] = None
        self.stealth_mode = False
        self.capi_received_fcs = cargo_queue.capi_received
        # marketId -> owner CAPI / CarrierStats capacity snapshot (local only).
        self.owner_capacities: Dict[int, Dict[str, Any]] = {}
        self.owner_capacity_cache_path: Optional[str] = None
        self.fc_cargo_refresh_timestamps: Dict[int, float] = {}
        self.fc_cargo_refresh_cooldown_seconds = 60
        self._baseline_done: set[int] = set()  # marketIds with dock baseline this session
        self._baseline_pending = cargo_queue.baseline_pending
        self._pending_fc_deltas = cargo_queue.deltas
        self._delivery_recovery_queued = False
        self._next_delivery_recovery = 0.0
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
        if not plugin or self._retired:
            return
        try:
            plugin.refresh_build_overlay(force=True)
        except OVERLAY_UI_ERRORS as exc:
            logger.warning("Overlay refresh after FC jump state change failed: %s", exc)
        self._schedule_overlay_jump_tick()

    def _schedule_overlay_jump_tick(self) -> None:
        if self._retired:
            return
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
            if self._retired or not self.jump_tracker.is_active():
                return
            try:
                plugin.refresh_build_overlay(force=True)
            except OVERLAY_UI_ERRORS as exc:
                logger.warning("Overlay jump tick refresh failed: %s", exc)
            if self.jump_tracker.is_active():
                self._schedule_overlay_jump_tick()

        self._overlay_jump_tick_id = plugin.schedule_after(1000, tick)

    def handle_jump_requested(self, entry: Mapping[str, Any]) -> bool:
        """Handle jump requested."""
        return self.jump_tracker.handle_jump_requested(entry)

    def handle_jump_cancelled(self, entry: Mapping[str, Any]) -> bool:
        """Handle jump cancelled."""
        return self.jump_tracker.handle_jump_cancelled(entry)

    def handle_carrier_location(self, entry: Mapping[str, Any]) -> bool:
        """Handle carrier location."""
        return self.jump_tracker.handle_carrier_location(entry)

    def overlay_jump_footer_lines(self, *, prefer_market_id: Optional[int] = None) -> List[str]:
        """Return jump countdown lines for the overlay."""
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
            capacity = self._parse_owner_capacity_cache_entry(cap_raw)
            if capacity is None:
                continue
            self.owner_capacities[mid] = capacity
            loaded += 1
        if loaded:
            logger.info("Loaded %s FC owner capacity cache entr%s", loaded, "y" if loaded == 1 else "ies")

    @staticmethod
    def _parse_owner_capacity_cache_entry(cap_raw: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            free_space = int(cap_raw.get("freeSpace"))
        except (TypeError, ValueError):
            return None
        total_capacity = None
        if cap_raw.get("totalCapacity") is not None:
            try:
                total_capacity = int(cap_raw.get("totalCapacity"))
            except (TypeError, ValueError):
                pass
        return {
            "freeSpace": free_space,
            "callsign": str(cap_raw.get("callsign") or "").strip().upper(),
            "totalCapacity": total_capacity,
            "updated": cap_raw.get("updated"),
        }

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
        """Enable or disable stealth mode."""
        self.stealth_mode = enabled
        if enabled:
            logger.info("Fleet Carrier stealth mode enabled - commodity data will not be sent to Ravencolonial")
        else:
            logger.info("Fleet Carrier stealth mode disabled - commodity data will be sent to Ravencolonial")

    def _linked_fcs_from_active_projects(self, cmdr_name: str) -> Dict[int, Dict[str, Any]]:
        """Return FCs linked to the commander's active projects, keyed by marketId."""
        projects = self.api_client.get_commander_projects(cmdr_name)
        if not isinstance(projects, list):
            raise ValueError("Commander projects could not be loaded")

        found: Dict[int, Dict[str, Any]] = {}
        for project in projects:
            for mid, entry in self._eligible_fcs_for_project(project).items():
                found.setdefault(mid, entry)
        return found

    @staticmethod
    def _eligible_fcs_for_project(project: Any) -> Dict[int, Dict[str, Any]]:
        if not isinstance(project, Mapping):
            return {}
        linked = project.get("linkedFC")
        if not isinstance(linked, list):
            return {}
        build_id = project.get("buildId") or project.get("buildID") or project.get("id")
        result: Dict[int, Dict[str, Any]] = {}
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
            result.setdefault(mid, entry)
        return result

    def _load_stealth_mode_setting(self) -> bool:
        try:
            from config import config
            return config.get_bool('ravencolonial_stealth_mode')
        except CONFIG_READ_ERRORS:
            return self.stealth_mode

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
                timestamp=_fc_record_timestamp(fc) or now,
                read_revision=self._link_read_revision,
            )

    def _rebuild_callsign_to_market_id(self) -> None:
        self.callsign_to_market_id = {}
        for market_id, fc in self.linked_fcs.items():
            callsign = str(fc.get('name') or '').upper()
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

    def _clear_commander_context(self) -> None:
        """Revoke old links and discard cargo baselines before loading a new commander."""
        self.initialized_cmdr = None
        self.linked_fcs = {}
        self.update_eligible_fc_market_ids.clear()
        self.callsign_to_market_id.clear()
        self.clear_dock_context()
        self.current_carrier_market_id = None
        self.fc_cargo_refresh_timestamps.clear()
        self._baseline_done.clear()
        self._inventory_lookup_captured = False
        self._inventory_lookup_frame_ids.clear()
        self._inventory_lookup_record_ids.clear()
        self._inventory_lookup_replacement_ids.clear()

    def initialize_fcs(self, cmdr_name: str):
        """Initialize Fleet Carrier data for the commander."""
        if self.initialized_cmdr != cmdr_name:
            self._clear_commander_context()
        self.commander_name = cmdr_name
        self.capture_inventory_lookup()
        try:
            self.stealth_mode = self._load_stealth_mode_setting()
            self.apply_commander_links(cmdr_name, *self.fetch_commander_links(cmdr_name))
            return True
        except HTTP_CLIENT_ERRORS as e:
            logger.error("Failed to initialize Fleet Carriers: %s", e, exc_info=True)
            return False

    def fetch_commander_links(self, cmdr_name: str) -> tuple[list, Dict[int, Dict[str, Any]]]:
        """Read both link sources without changing journal or UI state (worker thread)."""
        self._link_read_revision = self.cargo_read_revision()
        all_fcs = self.api_client.api_client.get_all_cmdr_fcs(cmdr_name)
        if not isinstance(all_fcs, list):
            raise ValueError("Commander carriers could not be loaded")
        return all_fcs, self._linked_fcs_from_active_projects(cmdr_name)

    def capture_inventory_lookup(self) -> None:
        """Capture recovery ownership before a lookup worker can outlive its commander handler."""
        with self._cargo_state_lock:
            if self._inventory_lookup_captured or self.commander_name is None:
                return
            self._capture_inventory_evidence()
            self._inventory_lookup_captured = True

    def _capture_inventory_evidence(self) -> None:
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        if deliveries is None or self.commander_name is None:
            return
        self._inventory_lookup_frame_ids.update(item["id"] for item in deliveries.inventory_frames(self.commander_name))
        self._inventory_lookup_record_ids.update(item["id"] for item in deliveries.records(self.commander_name))
        for item in deliveries.replacements(self.commander_name):
            self._inventory_lookup_replacement_ids.update({item["id"], item.get("reservation_id", item["id"])})

    def remember_inventory_replacement(self, identity: Optional[int]) -> Optional[int]:
        """Retain recovery ownership of full writes created by this handler's already queued work."""
        if identity is not None:
            self._inventory_lookup_replacement_ids.add(identity)
            deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
            if deliveries is not None:
                for item in deliveries.replacements(self.commander_name):
                    root = item.get("reservation_id", item["id"])
                    if identity in (item["id"], root):
                        self._inventory_lookup_replacement_ids.update({item["id"], root})
        return identity

    def apply_commander_links(self, cmdr_name: str, all_fcs: list, active_project_fcs: dict) -> None:
        """Install a successful link snapshot and release transfers observed during loading."""
        with self._cargo_state_lock:
            self._initial_inventory_release_depth += 1
        try:
            self._install_commander_links(cmdr_name, all_fcs, active_project_fcs)
        finally:
            with self._cargo_state_lock:
                self._initial_inventory_release_depth -= 1
        if self.current_station_type == "FleetCarrier" and self.is_update_eligible_fc(self.current_market_id):
            self._retry_held_inventory(self.current_market_id)
        self.maybe_queue_delivery_recovery()

    def _install_commander_links(self, cmdr_name: str, all_fcs: list, active_project_fcs: dict) -> None:
        self.commander_name = cmdr_name
        self.linked_fcs = {int(fc['marketId']): dict(fc) for fc in all_fcs}
        self._merge_active_project_fcs(active_project_fcs)
        self.update_eligible_fc_market_ids = set(self.linked_fcs)
        self._bootstrap_linked_fc_cargo_snapshots()
        self._rebuild_callsign_to_market_id()
        self._log_fc_initialization_summary(cmdr_name, all_fcs, active_project_fcs)
        self.initialized_cmdr = cmdr_name
        self._discard_ineligible_inventory()
        pending, self._initialization_deltas = self._initialization_deltas, {}
        events, self._initialization_events = self._initialization_events, []
        if events:
            for event in events:
                event()
        else:
            for mid, cargo_diff in pending.items():
                self._release_initial_delta(mid, cargo_diff)
        if self.current_station_type == "FleetCarrier" and self.is_update_eligible_fc(self.current_market_id):
            self._maybe_set_dock_baseline(self.current_market_id)

    def _release_initial_delta(
        self, market_id: int, cargo_diff: Dict[str, int], delivery_id: Optional[int] = None,
    ) -> None:
        if self.is_update_eligible_fc(market_id):
            self._maybe_set_dock_baseline(market_id)
            self._supply_fc_async(market_id, cargo_diff, record_delivery=False, delivery_id=delivery_id)
        else:
            deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
            if deliveries is not None and self.commander_name is not None:
                try:
                    provisional = any(item.get("provisional", False)
                                      and item["id"] in self._inventory_lookup_frame_ids
                                      for item in deliveries.inventory_frames(self.commander_name, market_id))
                    if provisional:
                        deliveries.discard_provisional_inventory(
                            self.commander_name, market_id, frame_ids=self._inventory_lookup_frame_ids,
                            record_ids=self._inventory_lookup_record_ids,
                        )
                    else:
                        deliveries.consume(self.commander_name, market_id, cargo_diff, delivery_id)
                except FILE_IO_ERRORS as error:
                    logger.warning("Ineligible delivery checkpoint for %s retained: %s", market_id, error)

    def _discard_ineligible_inventory(self) -> None:
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        if deliveries is None or self.commander_name is None or self.initialized_cmdr != self.commander_name:
            return
        deliveries.confirm_inventory_eligibility(
            self.commander_name, self.update_eligible_fc_market_ids, frame_ids=self._inventory_lookup_frame_ids,
        )
        evidence = [item for item in deliveries.inventory_frames(self.commander_name)
                    if item.get("provisional", False) and item["id"] in self._inventory_lookup_frame_ids]
        for mid in {item["market_id"] for item in evidence}:
            if not self.is_update_eligible_fc(mid):
                try:
                    deliveries.discard_provisional_inventory(
                        self.commander_name, mid, frame_ids=self._inventory_lookup_frame_ids,
                        record_ids=self._inventory_lookup_record_ids,
                    )
                except FILE_IO_ERRORS as error:
                    logger.warning("Ineligible inventory checkpoint for %s retained: %s", mid, error)

    def defer_initialization_event(self, event: Callable[[], None]) -> None:
        """Preserve CAPI/transfer arrival order while commander links are loading."""
        self._initialization_events.append(event)

    def retire(self) -> None:
        """Keep already-observed cargo work alive while detaching it from the current UI."""
        with self._cargo_state_lock:
            if not self._retired:
                self._capture_inventory_evidence()
            self._retired = True

    def _can_track_carrier(self, market_id: Any) -> bool:
        return _coerce_market_id(market_id) is not None and (
            self.is_update_eligible_fc(market_id) or
            (self.commander_name is not None and self.initialized_cmdr is None)
        )

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
        *,
        read_revision: Optional[int] = None,
        written: bool = False,
    ) -> Dict[str, int]:
        """Replace a carrier cargo manifest with an authoritative full snapshot."""
        with self._cargo_state_lock:
            normalized = self._replace_fc_cargo_manifest_serial(
                market_id, cargo, source, timestamp, read_revision=read_revision, written=written,
            )
        if written and source in {"raven_colonial_api", "manual_manifest_editor"}:
            self._project_acknowledged_cargo_to_active_handler(int(market_id), normalized, timestamp)
        return normalized

    def _replace_fc_cargo_manifest_serial(
        self, market_id: int, cargo: Mapping[str, Any], source: str, timestamp: Any,
        *, read_revision: Optional[int], written: bool,
    ) -> Dict[str, int]:
        mid = _coerce_market_id(market_id)
        if mid is None:
            return {}
        normalized = self._normalize_cargo_manifest(cargo)
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        if (source in {"raven_colonial_api", "manual_manifest_editor"}
                and deliveries is not None and self.commander_name is not None):
            if source == "manual_manifest_editor" and read_revision is not None:
                normalized = deliveries.cargo_for_display(mid, normalized)
            else:
                normalized = deliveries.remember_cargo(
                    mid, normalized, read_revision=read_revision,
                    written=written or source == "manual_manifest_editor",
                )
        fc = self.linked_fcs.setdefault(mid, {"marketId": mid})
        fc["cargo"] = normalized
        fc["cargoSource"] = source
        fc["cargoBaselineKnown"] = True
        fc["cargoUpdatedAt"] = timestamp if timestamp is not None else time.time()
        fc["cargoSnapshotTimestamp"] = fc["cargoUpdatedAt"]
        if source in {"raven_colonial_api", "manual_manifest_editor"}:
            self._acknowledged_fc_cargo[mid] = dict(normalized)
        logger.debug(
            "FC cargo manifest replaced: market_id=%s source=%s timestamp=%s commodities=%s total=%s",
            mid,
            source,
            fc["cargoUpdatedAt"],
            len(normalized),
            sum(normalized.values()),
        )
        return normalized

    def _project_acknowledged_cargo_to_active_handler(
        self, market_id: int, cargo: Dict[str, int], timestamp: Any,
    ) -> None:
        """Project acknowledged physical stock without changing current-commander eligibility."""
        active = getattr(self.api_client, "fc_handler", None)
        if active is not None and active is not self and active.is_update_eligible_fc(market_id):
            active.replace_fc_cargo_manifest(market_id, cargo, source="raven_colonial_api", timestamp=timestamp)
            active._maybe_mirror_selected_fc_cargo_and_refresh(market_id)

    def cargo_read_revision(self) -> Optional[int]:
        """Tag a cargo read so an older completion cannot downgrade a newer acknowledged stock."""
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        return deliveries.cargo_revision() if deliveries is not None else None

    def cargo_write_scope(self) -> Any:
        """Serialize signed/full/manual HTTP writes across commander handler generations."""
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        return deliveries.cargo_write_scope() if deliveries is not None else nullcontext()

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
        baseline_known = self._has_fc_cargo_baseline(mid)
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
        fc["cargoBaselineKnown"] = baseline_known
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
        """Check whether refresh fc cargo from api."""
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

    def _needs_baseline(self, mid: int) -> bool:
        """Return True when this dock visit still needs a server/cache baseline check."""
        return mid not in self._baseline_done

    def _has_fc_cargo_baseline(self, mid: int) -> bool:
        fc = self.linked_fcs.get(mid) or self.linked_fcs.get(str(mid)) or {}
        source = str(fc.get("cargoSource") or "")
        cargo = fc.get("cargo")
        if "cargoBaselineKnown" in fc:
            return bool(fc["cargoBaselineKnown"])
        if source in ("raven_colonial_api", "capi", "manual_manifest_editor"):
            return isinstance(cargo, Mapping)
        return bool(self._normalize_cargo_manifest(cargo or {}))

    def _queue_pending_fc_delta(
        self, market_id: int, cargo_diff: Dict[str, int], delivery_id: Optional[int] = None,
    ) -> bool:
        mid = _coerce_market_id(market_id)
        if mid is None or mid not in self._baseline_pending:
            return False
        self._pending_fc_deltas.setdefault(mid, []).append((dict(cargo_diff), delivery_id, self))
        logger.info("Queued FC cargo delta while dock baseline is pending for %s: %s", mid, cargo_diff)
        return True

    def _complete_dock_baseline(self, mid: int) -> None:
        with self._cargo_state_lock:
            capi = self._pending_capi_updates.pop(mid, None)
            recovery_ids = self._pending_capi_recovery_ids.pop(mid, [])
            snapshot_at = self._pending_capi_times.pop(mid, None)
            prepared_id, frame_ids, snapshot_version = self._pending_capi_ownership.pop(mid, (None, None, None))
            pending = self._pending_fc_deltas.pop(mid, [])
            if capi is not None:
                for _, delivery_id, _ in pending:
                    if delivery_id is not None and delivery_id not in recovery_ids:
                        recovery_ids.append(delivery_id)
                # Reserve this complete target before another movement can reuse its
                # physical evidence. New arrivals remain deferred after this target.
                queued = self._update_fc_cargo_async(
                    mid, capi, recovery_ids=recovery_ids, snapshot_at=snapshot_at,
                    prepared_id=prepared_id, covered_frame_ids=frame_ids,
                    snapshot_version=snapshot_version,
                )
                if queued:
                    pending = []
            pending.extend(self._pending_fc_deltas.pop(mid, []))
            self._baseline_done.add(mid)
            self._baseline_pending.discard(mid)
            self._release_uncovered_fc_deltas(mid, pending)
            self._retry_held_inventory(mid)
        self._maybe_mirror_selected_fc_cargo_and_refresh(mid)

    def _retry_held_inventory(self, mid: int) -> None:
        """Release this dock's complete observation after the initial carrier stock becomes available."""
        with self._cargo_state_lock:
            if self._journal_inventory_depth:
                self._deferred_inventory_retries.add(mid)
                return
            if (self._initial_inventory_release_depth or self.current_station_type != "FleetCarrier"
                    or self.current_market_id != mid
                    or not self.is_update_eligible_fc(mid) or self._load_stealth_mode_setting()
                    or not self._has_fc_cargo_baseline(mid)):
                return
            self._check_inventory_frame()
            previous = self.ship_cargo_tracker.deferred_inventory()
            delta = self.ship_cargo_tracker.retry_held_inventory(self._available_inventory_stock(mid))
            if delta is not None and (delta or self.ship_cargo_tracker.deferred_inventory() != previous):
                self._queue_inventory_delta(mid, delta)

    def _available_inventory_stock(self, mid: int) -> Dict[str, int]:
        """Reserve every outstanding withdrawal before funding speculative physical attribution."""
        stock = dict(self._acknowledged_fc_cargo.get(mid, self.linked_fcs[mid]["cargo"]))
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        if deliveries is not None:
            stock = deliveries.cargo_for_display(mid, stock)
            for record in deliveries.records(market_id=mid):
                for key, delta in record["cargo"].items():
                    if delta < 0:
                        stock[key] = max(0, stock.get(key, 0) + delta)
        return stock

    @contextmanager
    def journal_inventory_update(self, entry: Mapping[str, Any], state: Mapping[str, Any]) -> Iterator[None]:
        """Keep one journal callback's observed accounting and classification ahead of worker replay."""
        with self._cargo_state_lock:
            self.ship_cargo_tracker.observe_journal(entry, state, self.current_market_id)
            self._journal_inventory_depth += 1
        try:
            yield
        finally:
            with self._cargo_state_lock:
                self._journal_inventory_depth -= 1
                pending = set()
                if not self._journal_inventory_depth:
                    pending, self._deferred_inventory_retries = self._deferred_inventory_retries, set()
            for mid in pending:
                self._retry_held_inventory(mid)

    def _release_uncovered_fc_deltas(self, mid: int, pending: list) -> None:
        """Keep later movements when a full target was superseded, without replaying its covered records."""
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        remaining = {item["id"] for item in deliveries.records(market_id=mid)} if deliveries is not None else None
        for delta, identity, owner in pending:
            if identity is None or remaining is None or identity in remaining:
                owner._supply_fc_async_serial(mid, delta, record_delivery=False, delivery_id=identity)

    def _manifests_differ(self, a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
        """Compare normalized cargo manifests."""
        return self._normalize_cargo_manifest(a) != self._normalize_cargo_manifest(b)

    def _maybe_set_dock_baseline(self, mid: int) -> None:
        """Establish dock baseline from server/CAPI cargo cache once per dock visit."""
        if mid in self._baseline_pending or not self._needs_baseline(mid):
            return
        if self.stealth_mode:
            logger.debug("dock_baseline: stealth mode enabled, skipping marketId=%s", mid)
            self._complete_dock_baseline(mid)
            return

        if self._has_fc_cargo_baseline(mid):
            logger.info("dock_baseline: using cached server/CAPI manifest for marketId=%s", mid)
            self._complete_dock_baseline(mid)
            return

        logger.info("dock_baseline: no cached manifest for marketId=%s; fetching server baseline", mid)
        self._baseline_pending.add(mid)
        self._fetch_fc_baseline_async(mid)

    def _fetch_fc_baseline_async(self, market_id: int) -> None:
        self.api_client.queue_api_call(self._fetch_fc_baseline, market_id)

    def _fetch_fc_baseline(self, market_id: int) -> bool:
        mid = _coerce_market_id(market_id)
        if mid is None:
            return False
        try:
            revision = self.cargo_read_revision()
            result = self.api_client.api_client.get_fc(mid)
            if isinstance(result, Mapping):
                cargo = result.get("cargo")
                if isinstance(cargo, Mapping):
                    self.replace_fc_cargo_manifest(
                        mid,
                        cargo,
                        source="raven_colonial_api",
                        timestamp=_fc_record_timestamp(result) or time.time(),
                        read_revision=revision,
                    )
                    logger.info("dock_baseline: loaded server manifest for marketId=%s", mid)
                    try:
                        self._maybe_mirror_selected_fc_cargo_and_refresh(mid)
                    except OVERLAY_UI_ERRORS:
                        pass
                    return True
            logger.warning("dock_baseline: server baseline fetch returned no cargo for marketId=%s", mid)
            return False
        except HTTP_CLIENT_ERRORS as e:
            logger.error("dock_baseline: server baseline fetch failed for marketId=%s: %s", mid, e, exc_info=True)
            return False
        finally:
            self._complete_dock_baseline(mid)

    def clear_dock_context(self) -> None:
        """Call on Undocked — clears FC dock tracking (SrvSurvey lastDocked parity)."""
        with self._cargo_state_lock:
            if self.current_market_id is not None:
                self._baseline_done.discard(self.current_market_id)
            self.current_station_type = None
            self.current_market_id = None
            self.last_station_services = None
            self.ship_cargo_tracker.reset()
            self._inventory_frame_id = None

    def _refresh_station_services(self, entry: Dict[str, Any]) -> None:
        services = entry.get("StationServices")
        if services is not None:
            self.last_station_services = list(services)

    def handle_docked_event(self, entry: Dict[str, Any]) -> bool:
        """
        Handle a Docked journal event.

        :param entry: The journal entry data
        :return: True if this is a Fleet Carrier, False otherwise
        """
        station_type = entry.get('StationType', '')
        market_id = _coerce_market_id(entry.get('MarketID'))
        station_name = entry.get('StationName', '')

        logger.debug(f"handle_docked_event: station={station_name}, type={station_type}, marketID={market_id}")

        # Update current station info
        with self._cargo_state_lock:
            if self.current_market_id != market_id or self.current_station_type != station_type:
                self.last_station_services = None
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

    def initialize_current_dock_context(self, state: Mapping[str, Any]) -> bool:
        """Initialize dock tracking from EDMC's current state during plugin startup."""
        if not isinstance(state, Mapping):
            return False

        station_type = state.get("StationType")
        market_id = _coerce_market_id(state.get("MarketID"))
        if not station_type or market_id is None:
            return False

        entry = dict(state)
        entry["StationType"] = station_type
        entry["MarketID"] = market_id
        if "StationName" not in entry:
            entry["StationName"] = state.get("station") or ""

        if station_type == "FleetCarrier":
            logger.info(
                "Startup state is docked at Fleet Carrier - initializing dock baseline workflow for marketId=%s",
                market_id,
            )
            return self.handle_docked_event(entry)

        with self._cargo_state_lock:
            self.current_station_type = station_type
            self.current_market_id = market_id
            self._refresh_station_services(entry)
        logger.info("Initialized FC handler with current station: %s, marketID: %s", station_type, market_id)
        return False

    def handle_marketbuy_event(
        self, entry: Dict[str, Any], state: Optional[Mapping[str, Any]] = None,
        ship_cargo: Optional[Mapping[str, int]] = None, complete_inventory: bool = False,
    ) -> bool:
        """
        Handle a MarketBuy journal event - player bought from FC.

        :param entry: The journal entry data
        :return: True if processed as Fleet Carrier purchase, False otherwise
        """
        return self._handle_market_trade(entry, -1, state, ship_cargo, complete_inventory)

    def handle_marketsell_event(
        self, entry: Dict[str, Any], state: Optional[Mapping[str, Any]] = None,
        ship_cargo: Optional[Mapping[str, int]] = None, complete_inventory: bool = False,
    ) -> bool:
        """
        Handle a MarketSell journal event - player sold to FC.

        :param entry: The journal entry data
        :return: True if processed as Fleet Carrier sale, False otherwise
        """
        return self._handle_market_trade(entry, 1, state, ship_cargo, complete_inventory)

    def _handle_market_trade(
        self, entry: Mapping[str, Any], sign: int, state: Optional[Mapping[str, Any]],
        ship_cargo: Optional[Mapping[str, int]], complete_inventory: bool,
    ) -> bool:
        market_id = _coerce_market_id(entry.get('MarketID'))
        commodity = normalize_commodity_key(str(entry.get('Type') or '').lower())
        try:
            count = int(entry.get('Count') or 0)
        except (TypeError, ValueError):
            return False
        if (self.current_station_type != 'FleetCarrier' or count <= 0 or not commodity
                or self.current_market_id is not None and market_id != self.current_market_id
                or not self.ship_cargo_tracker.is_main_ship(state)):
            return False
        if not self._can_track_carrier(market_id) or self._load_stealth_mode_setting():
            return False
        self._report_cargo_movement(market_id, entry, {commodity: sign * count}, ship_cargo, complete_inventory)
        return True

    def _report_cargo_movement(
        self, market_id: int, entry: Mapping[str, Any], explicit: Dict[str, int],
        ship_cargo: Optional[Mapping[str, int]], complete_inventory: bool,
    ) -> None:
        with self._cargo_state_lock:
            reconciled = self._bank_market_delta(entry, ship_cargo, complete_inventory)
            delta = explicit if reconciled is None else reconciled
            self._queue_inventory_delta(market_id, delta)
        self._maybe_mirror_selected_fc_cargo_and_refresh(market_id)

    def _queue_inventory_delta(self, market_id: int, delta: Dict[str, int]) -> None:
        self.ship_cargo_tracker.note_reported_delta(delta)
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        if self._inventory_frame_generation != self.ship_cargo_tracker.context_generation():
            self._inventory_frame_id = None
        state = self.ship_cargo_tracker.deferred_inventory()
        if (deliveries is not None and self.commander_name
                and (state is not None or self._inventory_frame_id is not None)):
            try:
                identity, frame_id = deliveries.checkpoint_inventory(
                    self.commander_name, market_id, delta, state, self._inventory_frame_id,
                    provisional=self.initialized_cmdr is None,
                )
            except InventoryFrameSuperseded:
                self.ship_cargo_tracker.reset()
                self._inventory_frame_id = None
                return
            self._inventory_frame_id = frame_id
            if frame_id is not None:
                self._inventory_lookup_frame_ids.add(frame_id)
            if identity is not None:
                self._inventory_lookup_record_ids.add(identity)
            self._inventory_frame_generation = self.ship_cargo_tracker.context_generation()
            if delta:
                self._supply_fc_async_serial(market_id, delta, record_delivery=False, delivery_id=identity)
        elif delta:
            self._supply_fc_async_serial(market_id, delta, record_delivery=True, delivery_id=None)

    def _check_inventory_frame(self) -> bool:
        if self._inventory_frame_id is None:
            return False
        if self._inventory_frame_generation != self.ship_cargo_tracker.context_generation():
            self._inventory_frame_id = None
            return False
        deliveries = self.api_client.pending_carrier_deliveries
        if not deliveries.inventory_frame_active(self._inventory_frame_id):
            # The full target covers this uncertainty even while its acknowledgement is pending.
            self.ship_cargo_tracker.reset()
            self._inventory_frame_id = None
            return True
        return False

    def _bank_market_delta(
        self, entry: Mapping[str, Any], ship_cargo: Optional[Mapping[str, int]],
        complete_inventory: bool = False, carrier_move: bool = True,
    ) -> Optional[Dict[str, int]]:
        if not any(str(service).lower() == "squadronbank" for service in self.last_station_services or []):
            return None
        self._check_inventory_frame()
        tracker = self.ship_cargo_tracker
        if tracker.manual_covers(entry):
            if complete_inventory and ship_cargo is not None and tracker.manual_inventory_candidate(entry):
                return tracker.reconcile(
                    ship_cargo, allow_bank_movement=True, timestamp=entry.get("timestamp"),
                    carrier_stock=self.linked_fcs.get(self.current_market_id, {}).get("cargo"),
                )
            return {}
        origin, remaining = tracker.resolve_origin_movement(entry, carrier_move)
        if remaining is None:
            return origin
        result = self._bank_journal_delta(remaining, ship_cargo, complete_inventory, carrier_move)
        if origin is None:
            return result
        if result is None:
            result = tracker.explicit_carrier_movement(remaining) if carrier_move else {}
        for key, amount in result.items():
            origin[key] = origin.get(key, 0) + amount
        return {key: amount for key, amount in origin.items() if amount}

    def _bank_journal_delta(
        self, entry: Mapping[str, Any], ship_cargo: Optional[Mapping[str, int]],
        complete_inventory: bool, carrier_move: bool,
    ) -> Optional[Dict[str, int]]:
        """Reconcile the components whose origin does not require a full carrier correction."""
        tracker = self.ship_cargo_tracker
        stock = self.linked_fcs.get(self.current_market_id, {}).get("cargo")
        if tracker.inventory_covers_market(entry):
            if tracker.market_was_reconciled(entry):
                return tracker.covered_movement(entry, carrier_move, carrier_stock=stock)
            if not tracker.movement_awaits_inventory(entry):
                tracker.consume_market(entry)
            return None if carrier_move else {}
        if ship_cargo is None and tracker.inventory_shares_time(entry):
            return tracker.retain_untrusted_movement(
                entry, carrier_move, carrier_stock=stock,
                reversal_stock=self._pending_reversal_stock() if stock is None else stock,
            )
        if ship_cargo is not None:
            return tracker.reconcile_market(
                entry, ship_cargo, complete=complete_inventory, carrier_move=carrier_move,
                carrier_stock=stock,
            )
        return None

    def _pending_reversal_stock(self) -> Dict[str, int]:
        """Bound a correction by this lookup's queued positives after every earlier market withdrawal."""
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        available: Dict[str, int] = {}
        if deliveries is None:
            return available
        for record in deliveries.records(market_id=self.current_market_id):
            for key, delta in record["cargo"].items():
                if delta < 0 or (record["commander"] == self.commander_name
                                 and record["id"] in self._observed_initial_delivery_ids):
                    available[key] = max(0, available.get(key, 0) + delta)
        return available

    def handle_ship_mutation(
        self, entry: Mapping[str, Any], state: Mapping[str, Any], ship_cargo: Optional[Mapping[str, int]],
        complete_inventory: bool,
    ) -> None:
        """Exclude known non-carrier changes from an inventory that arrived ahead of their journal events."""
        if (self.current_station_type != "FleetCarrier" or not self._can_track_carrier(self.current_market_id)
                or self._load_stealth_mode_setting() or not self.ship_cargo_tracker.is_main_ship(state)):
            return
        tracker = self.ship_cargo_tracker
        if (not complete_inventory and not tracker.inventory_covers_market(entry)
                and not tracker.inventory_shares_time(entry)):
            return
        with self._cargo_state_lock:
            delta = self._bank_market_delta(entry, ship_cargo, complete_inventory, False)
            self._queue_inventory_delta(self.current_market_id, delta or {})
        self._maybe_mirror_selected_fc_cargo_and_refresh(self.current_market_id)

    @staticmethod
    def _cargo_transfer_fields(transfer: Mapping[str, Any]) -> tuple[str, int, str]:
        direction = (transfer.get("Direction") or "").lower()
        commodity = normalize_commodity_key(str(transfer.get("Type") or "").lower())
        try:
            count = int(transfer.get("Count", 0) or 0)
        except (TypeError, ValueError):
            count = 0
        return commodity, count, direction

    def handle_cargotransfer_event(
        self, entry: Dict[str, Any], state: Optional[Mapping[str, Any]] = None,
        ship_cargo: Optional[Mapping[str, int]] = None, complete_inventory: bool = False,
    ) -> bool:
        """
        Handle a CargoTransfer journal event - transfers between ship/carrier/SRV.

        Raven updates linked Fleet Carrier cargo uniformly by marketId. Squadron
        Carriers are not special-cased here; if the docked FleetCarrier marketId
        is eligible, CargoTransfer direction determines the signed FC cargo delta.
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

        if not self._can_track_carrier(market_id):
            logger.debug(f"FC {market_id} not update eligible")
            return False

        if self._load_stealth_mode_setting():
            logger.debug(f"CargoTransfer for FC {market_id} - stealth mode enabled, ignoring")
            return False

        if not self.ship_cargo_tracker.is_main_ship(state):
            return False
        transfers = entry.get("Transfers", [])
        cargo_diff: Dict[str, int] = {}

        for transfer in transfers:
            if not isinstance(transfer, Mapping):
                continue
            commodity, count, direction = self._cargo_transfer_fields(transfer)
            if not commodity or count <= 0:
                continue
            if direction == "tocarrier":
                cargo_diff[commodity] = cargo_diff.get(commodity, 0) + count
            elif direction == "toship":
                cargo_diff[commodity] = cargo_diff.get(commodity, 0) - count
            logger.debug(
                "CargoTransfer FC decision: marketId=%s eligible=%s direction=%s "
                "cargo_diff=%s",
                self.current_market_id,
                self.is_update_eligible_fc(self.current_market_id),
                direction,
                cargo_diff,
            )

        if cargo_diff:
            logger.info(f"Cargo transfer for FC {market_id}: {cargo_diff}")
            self._report_cargo_movement(market_id, entry, cargo_diff, ship_cargo, complete_inventory)
            return True

        return False

    def handle_ship_cargo_snapshot(
        self, entry: Mapping[str, Any], state: Mapping[str, Any], cargo: Mapping[str, Any],
    ) -> bool:
        """Recover snapshot-only squadron bank movement after excluding explicit journal deltas."""
        with self._cargo_state_lock:
            changed = self._handle_ship_cargo_snapshot_serial(entry, state, cargo)
        self._maybe_mirror_selected_fc_cargo_and_refresh(self.current_market_id)
        return changed

    def _handle_ship_cargo_snapshot_serial(
        self, entry: Mapping[str, Any], state: Mapping[str, Any], cargo: Mapping[str, Any],
    ) -> bool:
        tracker = self.ship_cargo_tracker
        self._check_inventory_frame()
        if not tracker.is_main_ship(state) or str(entry.get("Vessel") or "Ship").lower() != "ship":
            tracker.reset()
            return False
        known = (isinstance(entry.get("Inventory"), list) and bool(entry["Inventory"])
                 or isinstance(state.get("Cargo"), Mapping) and bool(cargo_counts(state["Cargo"]))
                 or entry.get("Count") == 0)
        if not known:
            return False
        squadron = any(str(service).lower() == "squadronbank" for service in self.last_station_services or [])
        allowed = (squadron and self.current_station_type == "FleetCarrier"
                   and state.get("Docked") is not False and state.get("IsDocked") is not False
                   and self._can_track_carrier(self.current_market_id) and not self._load_stealth_mode_setting())
        delta = tracker.reconcile(
            cargo, allow_bank_movement=allowed, timestamp=entry.get("timestamp"),
            carrier_stock=self.linked_fcs.get(self.current_market_id, {}).get("cargo") if allowed else None,
        )
        self._queue_inventory_delta(self.current_market_id, delta)
        return bool(delta)

    def _pending_delivery_records(
        self, market_id: int, observed_delivery_ids: Optional[list[int]] = None,
    ) -> list[dict[str, Any]]:
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        if deliveries is None:
            return []
        records = deliveries.records(market_id=market_id)
        return records if observed_delivery_ids is None else [
            record for record in records if record["id"] in observed_delivery_ids
        ]

    def _has_cargo_recovery_barrier(self, market_id: int) -> bool:
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        return bool(deliveries is not None and (
            deliveries.replacements(market_id=market_id) or deliveries.inventory_frames(market_id=market_id)
        ))

    def _should_accept_capi_snapshot(
        self,
        market_id: int,
        existing_cargo: Dict[str, int],
        cache_time: Any,
        capi_timestamp: Any,
        was_docked: Optional[bool] = None,
        observed_delivery_ids: Optional[list[int]] = None,
    ) -> tuple[bool, str]:
        docked = was_docked if was_docked is not None else self.current_station_type is not None
        if docked:
            return False, "player_docked"
        records = self._pending_delivery_records(market_id, observed_delivery_ids)
        capi_epoch = _timestamp_to_epoch(capi_timestamp)
        if self._capi_predates_completed_movement(market_id, capi_epoch):
            return False, "capi_predates_completed_movement"
        if self._capi_predates_pending_movement(records, capi_epoch):
            return False, "capi_predates_pending_movement"
        if self._capi_predates_inventory_frame(market_id, capi_epoch):
            return False, "capi_predates_inventory_frame"
        recovering = any(record["attempted"] for record in records) or self._has_cargo_recovery_barrier(market_id)
        if market_id in self.capi_received_fcs and not recovering:
            return False, "already_received"
        if capi_timestamp is None or _timestamp_to_epoch(capi_timestamp) is None:
            return False, "missing_capi_timestamp"
        if not existing_cargo:
            return True, "server_cargo_missing"
        same_recovery_snapshot = recovering and capi_epoch == _timestamp_to_epoch(cache_time)
        if cache_time is not None and not _timestamp_newer(capi_timestamp, cache_time) and not same_recovery_snapshot:
            return False, "capi_not_newer_than_cache"
        return True, "capi_accepted"

    def _capi_predates_completed_movement(self, market_id: int, capi_epoch: Optional[float]) -> bool:
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        completed_at = deliveries.cargo_observed_at(market_id) if deliveries is not None else None
        return completed_at is not None and (capi_epoch is None or capi_epoch <= completed_at)

    def _capi_predates_inventory_frame(self, market_id: int, capi_epoch: Optional[float]) -> bool:
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        frames = deliveries.inventory_frames(market_id=market_id) if deliveries is not None else []
        for frame in frames:
            stamps = [frame.get("observed_at"), frame["state"].get("inventory_time")]
            if capi_epoch is None or any(stamp is not None and capi_epoch <= stamp for stamp in stamps):
                return True
        return False

    @staticmethod
    def _capi_predates_pending_movement(records: list[dict], capi_epoch: Optional[float]) -> bool:
        return bool(records) and (capi_epoch is None or any(
            record.get("observed_at") is None or capi_epoch <= record["observed_at"] for record in records
        ))

    def _log_capi_cargo_decision(
        self,
        mid: int,
        capi_timestamp: Any,
        server_time: Any,
        accepted: bool,
        reason: str,
        existing_cargo: Dict[str, int],
        cargo_totals: Dict[str, int],
        cache_time: Any = None,
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
            "FC CAPI cargo decision: market_id=%s capi_time=%s server_time=%s cache_time=%s "
            "accepted=%s reason=%s old_cargo=%s new_cargo=%s",
            mid,
            capi_timestamp,
            server_time,
            cache_time,
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
        *,
        was_docked: Optional[bool] = None,
        observed_delivery_ids: Optional[list[int]] = None,
    ):
        """Apply a fresh physical snapshot while preserving journal/queue handoff order."""
        with self._cargo_state_lock:
            self._update_fc_cargo_from_capi_serial(
                market_id, cargo_totals, capi_timestamp,
                was_docked=was_docked, observed_delivery_ids=observed_delivery_ids,
            )
        self._maybe_mirror_selected_fc_cargo_and_refresh(market_id)

    def _update_fc_cargo_from_capi_serial(
        self, market_id: int, cargo_totals: Dict[str, int], capi_timestamp: Any,
        *, was_docked: Optional[bool], observed_delivery_ids: Optional[list[int]],
    ) -> None:
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
        server_time = _fc_server_last_refresh(existing)
        cache_source = str(existing.get("cargoSource") or "")
        cache_time = None if cache_source == "raven_colonial_api" else _fc_cache_timestamp(existing)
        accepted, reason = self._should_accept_capi_snapshot(
            market_id,
            existing_cargo,
            cache_time,
            capi_timestamp,
            was_docked,
            observed_delivery_ids,
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
            cache_time,
        )
        if not accepted:
            if reason != "already_received":
                logger.info(f"Skipping CAPI cargo for FC {market_id} - {reason}")
            return
        records = self._pending_delivery_records(mid, observed_delivery_ids)
        recovery_ids = [record["id"] for record in records]
        if (not recovery_ids and not self._has_cargo_recovery_barrier(mid)
                and not self._manifests_differ(existing_cargo, cargo_totals)):
            logger.info(f"Skipping CAPI cargo for FC {market_id} - manifest matches cache")
            self.capi_received_fcs.add(market_id)
            return

        logger.info(f"Receiving initial CAPI snapshot for FC {market_id}")
        logger.debug(f"CAPI cargo totals: {cargo_totals}")

        self.replace_fc_cargo_manifest(mid, cargo_totals, source="capi", timestamp=capi_timestamp)

        # Mark this FC as having received CAPI data
        self.capi_received_fcs.add(market_id)

        self._queue_capi_manifest(mid, cargo_totals, recovery_ids, capi_timestamp)

    def _queue_capi_manifest(
        self, mid: int, cargo_totals: Dict[str, int], recovery_ids: list[int], capi_timestamp: Any,
    ) -> None:
        """Own the snapshot's physical evidence before deferring its completed target to the API queue."""
        snapshot_version = self._advance_snapshot_version(mid)
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        snapshot_at = _timestamp_to_epoch(capi_timestamp) if deliveries is not None else None
        frame_ids = ([frame["id"] for frame in deliveries.inventory_frames(market_id=mid)]
                     if deliveries is not None else None)
        prepared_id = None
        if frame_ids:
            prepared_id = self._prepare_automatic_manifest(
                mid, cargo_totals, recovery_ids, snapshot_at, covered_frame_ids=frame_ids,
            )
            if prepared_id is None:
                return
        if mid in self._baseline_pending:
            self._pending_capi_updates[mid] = dict(cargo_totals)
            self._pending_capi_recovery_ids[mid] = recovery_ids
            self._pending_capi_times[mid] = snapshot_at
            self._pending_capi_ownership[mid] = prepared_id, frame_ids, snapshot_version
        else:
            self._update_fc_cargo_async(
                mid, cargo_totals, recovery_ids=recovery_ids, snapshot_at=snapshot_at,
                prepared_id=prepared_id, covered_frame_ids=frame_ids,
                snapshot_version=snapshot_version,
            )

    def _supply_fc_async(
        self, market_id: int, cargo_diff: Dict[str, int], *, record_delivery: bool = True,
        delivery_id: Optional[int] = None,
    ):
        """Update FC cargo incrementally using the API queue."""
        with self._cargo_state_lock:
            self._supply_fc_async_serial(
                market_id, cargo_diff, record_delivery=record_delivery, delivery_id=delivery_id,
            )
        self._maybe_mirror_selected_fc_cargo_and_refresh(market_id)

    def _supply_fc_async_serial(
        self, market_id: int, cargo_diff: Dict[str, int], *, record_delivery: bool,
        delivery_id: Optional[int],
    ) -> None:
        mid = _coerce_market_id(market_id)
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        if record_delivery and mid is not None and deliveries is not None and self.commander_name is not None:
            delivery_id = deliveries.record(self.commander_name, mid, cargo_diff)
        if mid is not None and self.commander_name is not None and self.initialized_cmdr is None:
            if delivery_id is not None:
                self._inventory_lookup_record_ids.add(delivery_id)
                self._observed_initial_delivery_ids.add(delivery_id)
            pending = self._initialization_deltas.setdefault(mid, {})
            for key, delta in cargo_diff.items():
                pending[key] = pending.get(key, 0) + delta
            snapshot = dict(cargo_diff)
            self.defer_initialization_event(lambda: self._release_initial_delta(mid, snapshot, delivery_id))
            return
        self._adjust_pending_capi(mid, cargo_diff)
        if mid is not None and self._queue_pending_fc_delta(mid, cargo_diff, delivery_id):
            return
        for commodity, delta in (cargo_diff or {}).items():
            self.apply_fc_cargo_delta(market_id, commodity, delta, source="journal")
        if delivery_id is None:
            self.api_client.queue_api_call(self._supply_fc, market_id, cargo_diff)
        else:
            self.api_client.queue_api_call(self._supply_fc, market_id, cargo_diff, delivery_id)

    def _adjust_pending_capi(self, market_id: int, cargo_diff: Mapping[str, int]) -> None:
        snapshot = self._pending_capi_updates.get(market_id)
        if snapshot is not None:
            for key, delta in cargo_diff.items():
                snapshot[key] = max(0, snapshot.get(key, 0) + delta)

    def _prepare_delivery_attempt(self, market_id: int, delivery_id: Optional[int]) -> Optional[bool]:
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        if deliveries is None or self.commander_name is None:
            return None
        if not self.api_client.api_client.api_key:
            logger.warning("Carrier delivery retained for restart recovery; API key is missing")
            return False
        if delivery_id is None:
            return None
        records = deliveries.records(self.commander_name, market_id)
        if not any(record["id"] == delivery_id for record in records):
            return True
        if not deliveries.begin(delivery_id, self._acknowledged_fc_cargo.get(int(market_id))):
            return False
        return None

    def _retain_failed_delivery(self, delivery_id: Optional[int]) -> None:
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        if deliveries is not None and delivery_id is not None:
            status = getattr(self.api_client.api_client, "fc_supply_failure_status", None)
            rejected = isinstance(status, int) and 400 <= status < 500 and status != 408
            rejected = rejected or getattr(self.api_client.api_client, "fc_supply_definitely_unsent", False) is True
            deliveries.failed(delivery_id, definite_rejection=rejected)

    def _supply_fc(self, market_id: int, cargo_diff: Dict[str, int], delivery_id: Optional[int] = None) -> bool:
        """Update FC cargo incrementally."""
        with self.cargo_write_scope():
            return self._supply_fc_serial(market_id, cargo_diff, delivery_id)

    def _supply_fc_serial(self, market_id: int, cargo_diff: Dict[str, int], delivery_id: Optional[int]) -> bool:
        if self._load_stealth_mode_setting():
            logger.info("Carrier delivery retained for restart recovery: stealth mode is enabled")
            return False
        try:
            prepared = self._prepare_delivery_attempt(market_id, delivery_id)
            if prepared is not None:
                return prepared
            clear_failure = getattr(self.api_client.api_client, "clear_fc_supply_failure", None)
            if callable(clear_failure):
                clear_failure()
            result = self.api_client.api_client.supply_fc(market_id, cargo_diff)
            if isinstance(result, dict):
                self._acknowledge_delivery_cargo(int(market_id), delivery_id, result)
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
                self._retain_failed_delivery(delivery_id)
                logger.error(f"Failed to update FC {market_id} cargo")
                return False
        except (*HTTP_CLIENT_ERRORS, *FILE_IO_ERRORS) as e:
            logger.error("Exception updating FC cargo: %s", e, exc_info=True)
            return False

    def _acknowledge_delivery_cargo(
        self, mid: int, delivery_id: Optional[int], cargo: Dict[str, int], *,
        read_revision: Optional[int] = None, written: bool = True,
    ) -> None:
        """Publish confirmed stock atomically with removing the withdrawal it already includes."""
        timestamp = time.time()
        with self._cargo_state_lock:
            deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
            if deliveries is not None and delivery_id is not None:
                deliveries.acknowledge([delivery_id])
            normalized = self._replace_fc_cargo_manifest_serial(
                mid, cargo, "raven_colonial_api", timestamp, read_revision=read_revision, written=written,
            )
        if written:
            self._project_acknowledged_cargo_to_active_handler(mid, normalized, timestamp)
        self._retry_held_inventory(mid)

    def has_pending_deliveries(self) -> bool:
        """Keep originating handlers alive while their transactions need recovery."""
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        return bool(deliveries is not None and self.commander_name and (
            deliveries.records(self.commander_name) or deliveries.replacements(self.commander_name)
            or deliveries.inventory_frames(self.commander_name)
            or deliveries.checkpoint_pending()
        ))

    def maybe_queue_delivery_recovery(self) -> None:
        """Schedule bounded recovery outside EDMC's journal/UI thread."""
        if (not self.has_pending_deliveries() or self.initialized_cmdr is None
                or self._delivery_recovery_queued or time.monotonic() < self._next_delivery_recovery):
            return
        self._delivery_recovery_queued = True
        self._next_delivery_recovery = time.monotonic() + 60
        self.api_client.queue_api_call(self.retry_pending_deliveries)

    def retry_pending_deliveries(self) -> None:
        """Reconcile attempted writes and preserve ordering independently for each carrier."""
        try:
            deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
            if deliveries is None or not deliveries.retry_checkpoint():
                return
            self._discard_ineligible_inventory()
            if not self.commander_name or self._load_stealth_mode_setting() or not self.api_client.api_client.api_key:
                return
            blocked = set()
            for replacement in self._owned_recovery_evidence(deliveries.replacements(), replacements=True):
                mid = replacement["market_id"]
                if self.is_update_eligible_fc(mid) and not self._reconcile_replacement(replacement):
                    blocked.add(mid)
            for record in self._owned_recovery_evidence(deliveries.records(self.commander_name)):
                mid = record["market_id"]
                if mid in blocked or mid in self._baseline_pending or not self.is_update_eligible_fc(mid):
                    continue
                if not self._retry_delivery_record(record):
                    blocked.add(mid)
        finally:
            self._delivery_recovery_queued = False

    def _owned_recovery_evidence(self, evidence: list[dict], *, replacements: bool = False) -> list[dict]:
        """Limit retired recovery to captured work and its already queued writers."""
        if not self._retired:
            return evidence
        identities = self._inventory_lookup_replacement_ids if replacements else self._inventory_lookup_record_ids
        return [item for item in evidence if item["id"] in identities
                or replacements and item.get("reservation_id", item["id"]) in identities]

    def _retry_delivery_record(self, record: Mapping[str, Any]) -> bool:
        try:
            if not self.api_client.pending_carrier_deliveries.is_first(record["id"], record["market_id"]):
                return False
            if record["attempted"]:
                return self._reconcile_delivery(record)
            return self._supply_fc(record["market_id"], record["cargo"], record["id"])
        except (*HTTP_CLIENT_ERRORS, *FILE_IO_ERRORS) as error:
            logger.warning("Carrier %s cargo recovery retained: %s", record["market_id"], error)
            return False

    def _reconcile_delivery(self, record: Mapping[str, Any]) -> bool:
        with self.cargo_write_scope():
            return self._reconcile_delivery_serial(record)

    def _reconcile_delivery_serial(self, record: Mapping[str, Any]) -> bool:
        mid = record["market_id"]
        revision = self.cargo_read_revision()
        remote = self.api_client.api_client.get_fc(mid)
        if (not isinstance(remote, Mapping) or not isinstance(remote.get("cargo"), Mapping)
                or remote.get("marketId", mid) != mid):
            return False
        before = record["before"]
        if before is None:
            return False
        cargo = self._normalize_cargo_manifest(remote["cargo"])
        applied = all(cargo.get(key, 0) == max(0, before.get(key, 0) + delta)
                      for key, delta in record["cargo"].items())
        deliveries = self.api_client.pending_carrier_deliveries
        if applied and record["uncertain"]:
            self._acknowledge_delivery_cargo(mid, record["id"], cargo, read_revision=revision, written=False)
            return True
        unchanged = all(cargo.get(key, 0) == before.get(key, 0) for key in record["cargo"])
        if unchanged and not record["uncertain"]:
            deliveries.allow_retry(record["id"])
            self.replace_fc_cargo_manifest(mid, cargo, source="raven_colonial_api", read_revision=revision)
            return self._supply_fc(mid, record["cargo"], record["id"])
        logger.info("Carrier %s cargo write remains uncertain; waiting for an authoritative manifest", mid)
        return False

    def _update_fc_cargo_async(
        self, market_id: int, cargo: Dict[str, int], *, recovery_ids: Optional[list[int]] = None,
        snapshot_at: Optional[float] = None,
        prepared_id: Optional[int] = None, covered_frame_ids: Optional[list[int]] = None,
        snapshot_version: Optional[int] = None,
    ) -> bool:
        """Reserve a full target before later journal work, then send it using the API queue."""
        if self._load_stealth_mode_setting():
            return False
        with self._cargo_state_lock:
            if snapshot_version is None:
                snapshot_version = self._advance_snapshot_version(market_id)
            if not self._snapshot_is_current(market_id, snapshot_version):
                return False
            target = self._normalize_cargo_manifest(cargo)
            covered = list(recovery_ids or [])
            deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
            if deliveries is None:
                self.api_client.queue_api_call(self._update_fc_cargo, market_id, target)
                return True
            frame_ids = covered_frame_ids
            if frame_ids is None:
                frame_ids = [frame["id"] for frame in deliveries.inventory_frames(market_id=market_id)]
            if prepared_id is not None or frame_ids:
                try:
                    prepared_id = self._prepare_automatic_manifest(
                        market_id, target, covered, snapshot_at,
                        prepared_id=prepared_id, covered_frame_ids=frame_ids,
                    )
                except RuntimeError:
                    logger.info("Skipping automatic carrier target superseded before its baseline completed")
                    return False
                if prepared_id is None:
                    return False
            self.api_client.queue_api_call(
                self._update_fc_cargo, market_id, target, covered,
                prepared_id=prepared_id, snapshot_at=snapshot_at, covered_frame_ids=frame_ids,
                snapshot_version=snapshot_version,
            )
            return True

    def _advance_snapshot_version(self, market_id: int) -> int:
        """Order every accepted full target, including frame-free targets that need no durable barrier."""
        version = self._snapshot_versions.get(market_id, 0) + 1
        self._snapshot_versions[market_id] = version
        return version

    def _snapshot_is_current(self, market_id: int, version: Optional[int]) -> bool:
        return version is None or self._snapshot_versions.get(market_id) == version

    def _snapshot_version_for_write(
        self, market_id: int, prepared_id: Optional[int], version: Optional[int],
    ) -> Optional[int]:
        """Version fresh direct targets without making recovery reservations appear newly accepted."""
        if version is None and prepared_id is None:
            return self._advance_snapshot_version(market_id)
        return version

    def _prepare_automatic_manifest(
        self, market_id: int, cargo: Dict[str, int], covered_ids: list[int], snapshot_at: Optional[float],
        *, prepared_id: Optional[int] = None, covered_frame_ids: Optional[list[int]] = None,
    ) -> Optional[int]:
        """Own the old inventory frames before preflight HTTP can overlap another journal event."""
        deliveries = self.api_client.pending_carrier_deliveries
        try:
            return self.remember_inventory_replacement(deliveries.begin_replacement(
                self.commander_name or "", market_id, cargo, covered_ids, attempted=False,
                source="automatic", authoritative_at=snapshot_at, expected_id=prepared_id,
                covered_frame_ids=covered_frame_ids,
            ))
        except CarrierCheckpointError as error:
            logger.warning("Automatic carrier reservation retained for recovery: %s", error)
            return self.remember_inventory_replacement(next((
                item["id"] for item in deliveries.replacements(market_id=market_id)
                if item.get("reservation_id", item["id"]) == error.reservation_id
            ), None))

    def _update_fc_cargo(
        self, market_id: int, cargo: Dict[str, int], recovery_ids: Optional[list[int]] = None,
        *, prepared_id: Optional[int] = None, snapshot_at: Optional[float] = None,
        expected_before: Optional[Dict[str, int]] = None,
        covered_frame_ids: Optional[list[int]] = None,
        snapshot_version: Optional[int] = None,
    ) -> bool:
        """Replace entire FC cargo manifest."""
        with self.cargo_write_scope():
            return self._update_fc_cargo_serial(
                market_id, cargo, recovery_ids, prepared_id, snapshot_at, expected_before,
                covered_frame_ids,
                snapshot_version,
            )

    def _update_fc_cargo_serial(
        self, market_id: int, cargo: Dict[str, int], recovery_ids: Optional[list[int]],
        prepared_id: Optional[int], snapshot_at: Optional[float],
        expected_before: Optional[Dict[str, int]],
        covered_frame_ids: Optional[list[int]],
        snapshot_version: Optional[int],
    ) -> bool:
        if self._load_stealth_mode_setting():
            logger.info("Skipping automatic carrier snapshot: stealth mode is enabled")
            return False
        try:
            with self._cargo_state_lock:
                snapshot_version = self._snapshot_version_for_write(market_id, prepared_id, snapshot_version)
                if not self._snapshot_is_current(market_id, snapshot_version):
                    return False
                target = self._normalize_cargo_manifest(cargo)
                covered_ids = list(recovery_ids or [])
                deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
                if covered_frame_ids is None and deliveries is not None:
                    covered_frame_ids = [frame["id"] for frame in deliveries.inventory_frames(market_id=market_id)]
                if prepared_id is None and covered_frame_ids:
                    prepared_id = self._prepare_automatic_manifest(
                        market_id, target, covered_ids, snapshot_at, covered_frame_ids=covered_frame_ids,
                    )
                    if prepared_id is None:
                        return False
            result = self._write_fc_manifest(
                market_id, target, covered_ids, source="automatic", prepared_id=prepared_id, snapshot_at=snapshot_at,
                expected_before=expected_before,
                covered_frame_ids=covered_frame_ids,
                snapshot_version=snapshot_version,
            )
            if isinstance(result, dict):
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
        except (*HTTP_CLIENT_ERRORS, *FILE_IO_ERRORS) as e:
            logger.error("Exception replacing FC cargo: %s", e, exc_info=True)
            return False

    def prepare_manual_manifest(self, market_id: int, cargo: Dict[str, int]) -> Optional[int]:
        """Reserve the user's absolute correction before later journal writes can overtake it."""
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        if deliveries is None:
            return None
        with self._cargo_state_lock:
            self._advance_snapshot_version(market_id)
            covered = [item["id"] for item in deliveries.records(market_id=market_id)]
            generation = self.ship_cargo_tracker.context_generation()
            try:
                identity = deliveries.begin_replacement(
                    self.commander_name or "", market_id, cargo, covered, attempted=False, source="manual",
                    live_worker=True,
                )
            except CarrierCheckpointError:
                self._cover_manual_attribution(market_id, cargo, generation)
                raise
            if identity is not None:
                self._cover_manual_attribution(market_id, cargo, generation)
            return identity

    def _cover_manual_attribution(self, market_id: int, cargo: Dict[str, int], generation: int) -> None:
        if (self.current_market_id == market_id
                and self.ship_cargo_tracker.context_generation() == generation):
            self.ship_cargo_tracker.cover_manual_manifest(cargo)

    def finish_manual_manifest(self, reservation_id: Optional[int]) -> None:
        """Release editor ownership after delivering a failed or superseded save result."""
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        if deliveries is not None:
            deliveries.finish_manual_worker(reservation_id)

    def save_manual_manifest(
        self, market_id: int, cargo: Dict[str, int], prepared_id: Optional[int],
        *, expected_before: Optional[Dict[str, int]] = None,
    ) -> Optional[Dict[str, int]]:
        """Durably supersede earlier recovery evidence with the user's explicit full manifest."""
        with self.cargo_write_scope():
            deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
            covered = []
            if deliveries is not None:
                prepared = next((item for item in deliveries.replacements(market_id=market_id)
                                 if item["id"] == prepared_id), None)
                if prepared is None:
                    raise RuntimeError("Manifest save was superseded by a newer cargo snapshot")
                covered = prepared["covered_ids"]
            return self._write_fc_manifest(
                market_id, cargo, covered, source="manual", prepared_id=prepared_id, expected_before=expected_before,
            )

    def _begin_owned_replacement(
        self, market_id: int, cargo: Dict[str, int], covered_ids: list[int], **kwargs: Any,
    ) -> Optional[int]:
        """Retain reservation ownership even when its authoritative checkpoint cannot be committed."""
        deliveries = self.api_client.pending_carrier_deliveries
        try:
            return deliveries.begin_replacement(self.commander_name or "", market_id, cargo, covered_ids, **kwargs)
        except CarrierCheckpointError as error:
            self.remember_inventory_replacement(error.reservation_id)
            raise

    def _write_fc_manifest(
        self, market_id: int, cargo: Dict[str, int], covered_ids: list[int],
        *, source: str, prepared_id: Optional[int] = None, snapshot_at: Optional[float] = None,
        expected_before: Optional[Dict[str, int]] = None,
        covered_frame_ids: Optional[list[int]] = None,
        snapshot_version: Optional[int] = None,
    ) -> Optional[Dict[str, int]]:
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        target, before = self._replacement_cargo_target(market_id, cargo)
        if expected_before is not None and before != expected_before:
            logger.info("Carrier %s stock changed during recovery preflight; retaining the original write", market_id)
            return None
        replacement_id = None
        with self._cargo_state_lock:
            if not self._snapshot_is_current(market_id, snapshot_version):
                return None
            if deliveries is not None:
                replacement_id = self._begin_owned_replacement(
                    market_id, target, covered_ids, source=source, expected_id=prepared_id,
                    authoritative_at=snapshot_at, before=before, covered_frame_ids=covered_frame_ids,
                )
                if replacement_id is None:
                    logger.info("Carrier %s automatic snapshot deferred behind a manual correction", market_id)
                    return None
            self.remember_inventory_replacement(replacement_id)
        result = self.api_client.api_client.update_fc_cargo(market_id, target)
        if not isinstance(result, dict):
            if replacement_id is not None:
                status = self.api_client.api_client.fc_supply_failure_status
                rejected = isinstance(status, int) and 400 <= status < 500 and status != 408
                rejected = rejected or self.api_client.api_client.fc_supply_definitely_unsent
                deliveries.replacement_failed(replacement_id, definite_rejection=rejected)
            return None
        self.replace_fc_cargo_manifest(
            market_id, result, source="manual_manifest_editor" if source == "manual" else "raven_colonial_api",
            timestamp=time.time(), written=True,
        )
        if replacement_id is not None and not self._acknowledge_written_manifest(replacement_id, market_id, result):
            return None
        return result

    def _acknowledge_written_manifest(self, identity: int, market_id: int, cargo: Dict[str, int]) -> bool:
        deliveries = self.api_client.pending_carrier_deliveries
        replacement = next((item for item in deliveries.replacements(market_id=market_id)
                            if item["id"] == identity), None)
        if replacement is None:
            return False
        was_live = deliveries.manual_worker_active(replacement)
        if not deliveries.acknowledge_replacement(identity, self._normalize_cargo_manifest(cargo)):
            logger.warning("Carrier %s replacement response does not confirm the full target", market_id)
            return False
        if not was_live:
            self._notify_manifest_recovery(replacement.get("reservation_id", identity), market_id, cargo)
        return True

    def _notify_manifest_recovery(self, reservation_id: int, market_id: int, cargo: Dict[str, int]) -> None:
        editor = getattr(self.api_client, "fc_manifest_editor", None)
        if editor is not None:
            try:
                editor.recovery_completed(reservation_id, market_id, cargo)
            except OVERLAY_UI_ERRORS:
                logger.debug("Recovered manifest editor refresh was skipped", exc_info=True)

    def _replacement_cargo_target(
        self, market_id: int, cargo: Dict[str, int],
    ) -> tuple[Dict[str, int], Optional[Dict[str, int]]]:
        """POST only replaces mentioned keys, so full snapshots must explicitly remove old stock."""
        known = set(self._acknowledged_fc_cargo.get(market_id, {}))
        deliveries = getattr(self.api_client, "pending_carrier_deliveries", None)
        if deliveries is not None:
            known.update(deliveries.cargo_for_display(market_id, {}))
            evidence = deliveries.records(market_id=market_id) + deliveries.replacements(market_id=market_id)
            for record in evidence:
                known.update(record["cargo"])
        remote = self.api_client.api_client.get_fc(market_id)
        before = None
        if isinstance(remote, Mapping) and isinstance(remote.get("cargo"), Mapping):
            before = self._normalize_cargo_manifest(remote["cargo"])
            known.update(before)
        return {**dict.fromkeys(known, 0), **cargo}, before

    def _reconcile_replacement(self, replacement: Mapping[str, Any]) -> bool:
        """Resolve a persisted full-write barrier before any of its covered movements can resume."""
        mid = replacement["market_id"]
        if (mid in self._baseline_pending and replacement.get("source") == "automatic"
                and not replacement.get("attempted", True)):
            return False
        try:
            with self.cargo_write_scope():
                deliveries = self.api_client.pending_carrier_deliveries
                if not any(item["id"] == replacement["id"] for item in deliveries.replacements(market_id=mid)):
                    return True
                if deliveries.manual_worker_active(replacement):
                    return False
                if not replacement.get("attempted", True):
                    if replacement.get("source") == "manual":
                        return self.save_manual_manifest(mid, replacement["cargo"], replacement["id"]) is not None
                    return self._update_fc_cargo(
                        mid, replacement["cargo"], replacement["covered_ids"], prepared_id=replacement["id"],
                    )
                revision = self.cargo_read_revision()
                remote = self.api_client.api_client.get_fc(mid)
                if not isinstance(remote, Mapping) or not isinstance(remote.get("cargo"), Mapping):
                    return False
                cargo = self._normalize_cargo_manifest(remote["cargo"])
                if (not replacement.get("uncertain", True) and replacement.get("before") == cargo
                        and cargo != self._normalize_cargo_manifest(replacement["cargo"])):
                    if replacement.get("source") == "manual":
                        return self.save_manual_manifest(
                            mid, replacement["cargo"], replacement["id"], expected_before=cargo,
                        ) is not None
                    return self._update_fc_cargo(
                        mid, replacement["cargo"], replacement["covered_ids"], prepared_id=replacement["id"],
                        expected_before=cargo,
                    )
                if not self.api_client.pending_carrier_deliveries.acknowledge_replacement(replacement["id"], cargo):
                    return False
                self.replace_fc_cargo_manifest(mid, cargo, source="raven_colonial_api", read_revision=revision)
                self._notify_manifest_recovery(replacement.get("reservation_id", replacement["id"]), mid, cargo)
                return True
        except (*HTTP_CLIENT_ERRORS, *FILE_IO_ERRORS) as error:
            logger.warning("Carrier %s replacement recovery retained: %s", mid, error)
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
        """Consume a journal CarrierStats entry directly (has SpaceUsage)."""
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
        If overlay carrier tracking is on and the given market_id belongs to the.

        current overlay carrier set, copy the latest cargo from linked_fcs into
        the overlay per-market map and refresh the HUD.

        This keeps specific-carrier, All, and Track All views in sync with
        journal deltas without fetching Raven Colonial during repaint.
        """
        p = getattr(self, "api_client", None)
        if not p or self._retired or getattr(p, "_stopping", False):
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
            if self._has_fc_cargo_baseline(mid):
                current[mid] = self._overlay_cargo_for_market(mid)
            else:
                current.pop(mid, None)
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
        """Get a summary of linked Fleet Carriers."""
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
