"""
Fleet Carrier Handler for Ravencolonial EDMC Plugin

This module handles Fleet Carrier commodity tracking and updates to Ravencolonial,
following the same logic as SrvSurvey.
"""

import logging
import os
import json
import time
from typing import Any, Dict, List, Mapping, Optional

from config import appname

from .api.client import normalize_commodity_key


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

# Use EDMC-compliant logger namespace
plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f'{appname}.{plugin_name}.fc')
# Disable propagation to avoid inheriting EDMC's osthreadid formatter
logger.propagate = False
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(name)s: %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


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
        self.last_station_services: Optional[List[Any]] = None
        self.skip_next_cargo_event = False
        self.squadron_cmdr_cargo_baseline_ready = False
        self.stealth_mode = False
        self.capi_received_fcs = set()  # Track FCs that have received CAPI data this session
        self.owner_capacities: Dict[int, Dict[str, Any]] = {}  # marketId -> {"freeSpace": int, "callsign": str, "totalCapacity"?: int, "updated": float} from owner CAPI / CarrierStats (local only)
        self.owner_capacity_cache_path: Optional[str] = None
        self.fc_cargo_refresh_timestamps: Dict[int, float] = {}
        self.fc_cargo_refresh_cooldown_seconds = 60

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
        except Exception as e:
            logger.debug("Could not load FC owner capacity cache %s: %s", path, e)
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
        except Exception as e:
            logger.debug("Could not save FC owner capacity cache %s: %s", path, e)
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
        except Exception as e:
            logger.debug("Could not load active commander projects for FC eligibility: %s", e, exc_info=True)
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
    
    def initialize_fcs(self, cmdr_name: str):
        """Initialize Fleet Carrier data for the commander"""
        try:
            logger.info(f"Initializing Fleet Carriers for commander: {cmdr_name}")
            
            # Check stealth mode setting
            try:
                from config import config
                self.stealth_mode = config.get_bool('ravencolonial_stealth_mode')
            except Exception:
                self.stealth_mode = False
                
            if self.stealth_mode:
                logger.info("Fleet Carrier stealth mode is enabled")
            
            # Get all FCs linked to this commander from Ravencolonial API
            # This gives us the current server-side cargo state as initial baseline
            all_fcs = self.api_client.api_client.get_all_cmdr_fcs(cmdr_name)
            
            # Store as dictionary by marketId for easy lookup
            self.linked_fcs = {int(fc['marketId']): dict(fc) for fc in all_fcs}
            active_project_fcs = self._linked_fcs_from_active_projects(cmdr_name)
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
            self.update_eligible_fc_market_ids = set(self.linked_fcs.keys())
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
            
            # Build callsign-to-marketId mapping for CAPI data matching
            # The 'name' field in FC data should be the callsign (e.g., "ABC-123")
            self.callsign_to_market_id = {}
            for market_id, fc in self.linked_fcs.items():
                callsign = fc.get('name', '').upper()  # Normalize to uppercase
                if callsign:
                    self.callsign_to_market_id[callsign] = market_id
                    logger.debug(f"Mapped callsign {callsign} to marketId {market_id}")
            
            if len(self.linked_fcs) == 0:
                logger.info(f"No Fleet Carriers linked for commander {cmdr_name}. To link a Fleet Carrier, visit Ravencolonial.com")
            else:
                logger.info(
                    "Loaded %s Fleet Carrier(s) eligible for cargo updates (%s profile-linked, %s active-project-linked)",
                    len(self.linked_fcs),
                    len(all_fcs),
                    len(active_project_fcs),
                )
                for market_id, fc in self.linked_fcs.items():
                    fc_name = fc.get('displayName', fc.get('name', 'Unknown'))
                    cargo = fc.get('cargo', {})
                    total_cargo = sum(cargo.values()) if cargo else 0
                    logger.info(f"FC {market_id} ({fc_name}): {len(cargo)} commodity types, {total_cargo} total units (server baseline)")
                
                # Mark all FCs as having initial state from server
                # CAPI can still provide a fresher snapshot if it arrives
                logger.info(f"Initial cargo state loaded from Ravencolonial API for {len(self.linked_fcs)} FCs")
            
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Fleet Carriers: {e}", exc_info=True)
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
        last = self.fc_cargo_refresh_timestamps.get(mid, 0)
        remaining = self.fc_cargo_refresh_cooldown_seconds - (now - last)
        if remaining > 0:
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

    def clear_dock_context(self) -> None:
        """Call on Undocked — clears FC dock tracking (SrvSurvey lastDocked parity)."""
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
            self.current_station_type == "FleetCarrier"
            and self.current_market_id is not None
            and self.is_update_eligible_fc(self.current_market_id)
            and self._services_has_squadron_bank()
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

        logger.debug(f"Updated current_station_type={self.current_station_type}, current_market_id={self.current_market_id}")
        
        if station_type == 'FleetCarrier':
            logger.info(f"Docked at Fleet Carrier: {station_name} (MarketID: {market_id})")
            logger.debug(f"Linked FCs: {list(self.linked_fcs.keys())}")
            
            # Check if this is a linked FC
            if self.is_update_eligible_fc(market_id):
                logger.info(f"This is a linked Fleet Carrier - will track commodity changes")
                # Trigger cargo update check after market data is available
                return True
            else:
                logger.info(f"Fleet Carrier {station_name} (MarketID: {market_id}) is not linked to commander in Ravencolonial")
                return True
        else:
            logger.debug(f"Docked at regular station: {station_name} (Type: {station_type})")
            return False
    
    def handle_market_event(self, entry: Dict[str, Any]) -> bool:
        """
        Handle a Market journal event - triggers cargo update for Fleet Carriers
        
        :param entry: The journal entry data
        :return: True if processed as Fleet Carrier, False otherwise
        """
        if entry.get('StationType') != 'FleetCarrier':
            return False
        
        market_id = _coerce_market_id(entry.get('MarketID'))
        
        # Only process if this is a linked FC
        if not self.is_update_eligible_fc(market_id):
            logger.debug(f"Market event for unlinked FC {market_id} - ignoring")
            return False
        
        # Check stealth mode
        if self.stealth_mode:
            logger.debug(f"Market event for FC {market_id} - stealth mode enabled, ignoring")
            return False
        
        logger.info(f"Market event for linked FC {market_id} - updating cargo")
        self._update_fc_from_market(market_id)
        return True
    
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
    
    def _update_fc_from_market(self, market_id: int):
        """Update FC cargo based on current market data"""
        try:
            # Get current FC data from server
            fc_data = self.api_client.api_client.get_fc(market_id)
            if not fc_data:
                logger.error(f"Failed to get FC data for {market_id}")
                return
            
            # Get current market data from EDMC
            market_data = self._get_market_data()
            if not market_data:
                logger.warning(f"No market data available for FC {market_id}")
                return
            
            # Compare market data with server data and update discrepancies
            new_cargo = {}
            server_cargo = fc_data.get('cargo', {})
            server_by_norm: Dict[str, int] = {}
            for sk, sv in server_cargo.items():
                nk = normalize_commodity_key(str(sk))
                if nk:
                    try:
                        server_by_norm[nk] = server_by_norm.get(nk, 0) + int(sv)
                    except (TypeError, ValueError):
                        pass
            
            for item in market_data:
                commodity_name = normalize_commodity_key(item.get('name', ''))
                if not commodity_name:
                    continue
                stock = item.get('stock', 0)
                is_producer = item.get('producer', False)
                is_consumer = item.get('consumer', False)
                
                server_qty = server_by_norm.get(commodity_name, 0)
                # Update if producer with different stock, or non-producer/non-consumer with stock change
                if (is_producer and server_qty != stock) or \
                   (not is_producer and not is_consumer and stock != server_qty):
                    new_cargo[commodity_name] = stock
            
            if new_cargo:
                logger.info(f"Updating FC {market_id} cargo with {len(new_cargo)} changes")
                self._update_fc_cargo_async(market_id, new_cargo)
            else:
                logger.debug(f"No cargo changes needed for FC {market_id}")
                
        except Exception as e:
            logger.error(f"Failed to update FC from market: {e}", exc_info=True)
    
    def _get_market_data(self) -> Optional[List[Dict[str, Any]]]:
        """Get market data from EDMC"""
        try:
            # EDMC provides market data through the plugin system
            # This will need to be integrated with your main plugin's market data access
            if hasattr(self.api_client, 'get_market_data'):
                return self.api_client.get_market_data()
            else:
                logger.warning("No market data access method available")
                return None
        except Exception as e:
            logger.error(f"Failed to get market data: {e}")
            return None
    
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
        accepted = False
        reason = "already_received"

        if market_id in self.capi_received_fcs:
            logger.info(f"Ignoring CAPI data for FC {market_id} - already received initial snapshot, using real-time journal events instead")
            logger.debug(
                "FC CAPI cargo decision: market_id=%s capi_time=%s server_time=%s accepted=%s reason=%s old_cargo=%s new_cargo=%s",
                mid,
                capi_timestamp,
                server_time,
                accepted,
                reason,
                {"commodities": len(existing_cargo), "total": sum(existing_cargo.values())},
                {"commodities": len(cargo_totals or {}), "total": sum(int(v) for v in (cargo_totals or {}).values())},
            )
            return

        if not existing_cargo:
            accepted = True
            reason = "server_cargo_missing"
        elif capi_timestamp is not None and server_time is not None and str(capi_timestamp) > str(server_time):
            accepted = True
            reason = "capi_newer"
        elif existing_source not in {"raven_colonial_api", "capi"} and capi_timestamp is not None:
            accepted = True
            reason = "local_source_with_capi_timestamp"
        else:
            reason = "freshness_not_verified"

        logger.debug(
            "FC CAPI cargo decision: market_id=%s capi_time=%s server_time=%s accepted=%s reason=%s old_cargo=%s new_cargo=%s",
            mid,
            capi_timestamp,
            server_time,
            accepted,
            reason,
            {"commodities": len(existing_cargo), "total": sum(existing_cargo.values())},
            {"commodities": len(cargo_totals or {}), "total": sum(int(v) for v in (cargo_totals or {}).values())},
        )
        if not accepted:
            logger.info(f"Skipping CAPI cargo for FC {market_id} - {reason}")
            return

        logger.info(f"Receiving initial CAPI snapshot for FC {market_id}")
        logger.debug(f"CAPI cargo totals: {cargo_totals}")

        self.replace_fc_cargo_manifest(mid, cargo_totals, source="capi", timestamp=capi_timestamp)
        try:
            self._maybe_mirror_selected_fc_cargo_and_refresh(mid)
        except Exception:  # nosec B110
            pass

        # Mark this FC as having received CAPI data
        self.capi_received_fcs.add(market_id)

        # Update server with full cargo snapshot (initial state only)
        self._update_fc_cargo_async(market_id, cargo_totals)
    
    def _supply_fc_async(self, market_id: int, cargo_diff: Dict[str, int]):
        """Update FC cargo incrementally using the API queue"""
        for commodity, delta in (cargo_diff or {}).items():
            self.apply_fc_cargo_delta(market_id, commodity, delta, source="journal")
        try:
            self._maybe_mirror_selected_fc_cargo_and_refresh(int(market_id))
        except Exception:  # nosec B110
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
                except Exception:  # nosec B110
                    pass
                logger.info(f"Successfully updated FC {market_id} cargo")
                return True
            else:
                logger.error(f"Failed to update FC {market_id} cargo")
                return False
        except Exception as e:
            logger.error(f"Exception updating FC cargo: {e}", exc_info=True)
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
                except Exception:  # nosec B110
                    pass
                logger.info(f"Successfully replaced FC {market_id} cargo")
                return True
            else:
                logger.error(f"Failed to replace FC {market_id} cargo")
                return False
        except Exception as e:
            logger.error(f"Exception replacing FC cargo: {e}", exc_info=True)
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
            logger.warning(f"No marketId found for callsign {callsign}. Known callsigns: {list(self.callsign_to_market_id.keys())}")
        
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
        cap_block: Optional[Mapping[str, Any]] = None
        for key in ("capacity", "Capacity"):
            val = capi_data.get(key) if isinstance(capi_data, Mapping) else None
            if isinstance(val, Mapping):
                cap_block = val
                break
        free: Any = None
        total: Any = None
        if cap_block:
            for fk in ("freeSpace", "FreeSpace"):
                if fk in cap_block:
                    free = cap_block[fk]
                    break
            for tk in ("totalCapacity", "TotalCapacity", "cargoSpaceTotal"):
                if tk in cap_block:
                    total = cap_block[tk]
                    break
        # Fallbacks for journal-shaped SpaceUsage or top-level scalars sometimes seen in envelopes
        if free is None:
            su = None
            if isinstance(capi_data, Mapping):
                su = capi_data.get("SpaceUsage") or capi_data.get("spaceUsage") or {}
            if isinstance(su, Mapping):
                free = su.get("FreeSpace") or su.get("freeSpace")
                total = total or su.get("TotalCapacity") or su.get("totalCapacity")
        if free is None and isinstance(capi_data, Mapping):
            free = capi_data.get("freeSpace") or capi_data.get("FreeSpace")
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
        # Best-effort callsign from the payload for display fallback
        cs = ""
        try:
            name = capi_data.get("name") if isinstance(capi_data, Mapping) else None
            if isinstance(name, Mapping):
                cs = str(name.get("callsign") or "").upper()
            if not cs and isinstance(capi_data, Mapping):
                cs = str(capi_data.get("callsign") or "").upper()
        except Exception:  # nosec B110
            pass
        self._remember_owner_capacity(
            int(market_id),
            free_i,
            callsign=cs,
            total_capacity=total_i,
            source="capi",
        )

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
                except Exception:
                    total_i = None
            self._remember_owner_capacity(
                market_id,
                free_i,
                callsign=callsign,
                total_capacity=total_i,
                source="journal",
            )
        except Exception:  # nosec B110
            # Never let a stats packet break anything
            pass

    def get_owned_callsign_for_market(self, market_id: int) -> Optional[str]:
        """Return the owner-visible callsign we saw for this marketId from CAPI/journal, if any."""
        cap = self.get_owner_capacity(market_id)
        if not cap:
            return None
        cs = cap.get("callsign")
        return str(cs).strip() or None

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
            sel = str(getattr(p, "overlay_fc_selection", "all") or "all").strip().lower()
            mid = int(market_id)
            if sel not in ("all", ""):
                try:
                    if int(sel) != mid:
                        return
                except (TypeError, ValueError):
                    return
            linked = getattr(p, "overlay_project_linked_fcs", None) or []
            if linked:
                linked_markets = set()
                for fc in linked:
                    try:
                        linked_markets.add(int(fc.get("marketId")))
                    except (AttributeError, TypeError, ValueError):
                        pass
                if mid not in linked_markets:
                    return
            # Build a normalized positive-only cargo map for this mid (overlay style).
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
            current = dict(getattr(p, "overlay_fc_cargo_by_market", None) or {})
            current[mid] = norm
            p.overlay_fc_cargo_by_market = current
            if hasattr(p, "refresh_build_overlay"):
                p.refresh_build_overlay()
        except Exception:  # nosec B110
            # Best effort; never break journal/CAPI paths for the overlay nudge.
            pass

    def get_owner_capacity(self, market_id: int) -> Optional[Dict[str, Any]]:
        """Return the locally cached owner capacity for a marketId (from CAPI/CarrierStats), or None."""
        if not market_id:
            return None
        try:
            return self.owner_capacities.get(int(market_id))
        except Exception:
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
