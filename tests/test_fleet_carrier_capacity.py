"""Regression tests for owner fleet-carrier capacity caching."""

from __future__ import annotations

import sys
import types
from pathlib import Path
import json
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
_PARENT = _ROOT.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

for name in ("timeout_session", "config"):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        if name == "config":
            mod.appname = "test"
        sys.modules[name] = mod

from RavenColonail_EDMC.fleet_carrier_handler import FleetCarrierHandler


def test_carrier_stats_capacity_cache_accepts_carrier_id() -> None:
    handler = FleetCarrierHandler(object())

    handler.update_fc_capacity_from_journal_stats(
        {
            "event": "CarrierStats",
            "CarrierID": 123,
            "Callsign": "N4W-T0Z",
            "SpaceUsage": {
                "TotalCapacity": 25000,
                "FreeSpace": 10000,
            },
        }
    )

    assert handler.get_owner_capacity(123)["freeSpace"] == 10000
    assert handler.get_owner_capacity(123)["callsign"] == "N4W-T0Z"


def test_owner_capacity_cache_persists_free_space_by_market_id(tmp_path: Path) -> None:
    handler = FleetCarrierHandler(object())
    handler.configure_owner_capacity_cache(str(tmp_path))

    handler.update_fc_capacity_from_journal_stats(
        {
            "event": "CarrierStats",
            "CarrierID": 123,
            "Callsign": "N4W-T0Z",
            "SpaceUsage": {"TotalCapacity": 25000, "FreeSpace": 10000},
        }
    )

    cache_path = tmp_path / "fc_owner_capacity_cache.json"
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert data["capacities"]["123"]["freeSpace"] == 10000

    reloaded = FleetCarrierHandler(object())
    reloaded.configure_owner_capacity_cache(str(tmp_path))
    assert reloaded.get_owner_capacity(123)["freeSpace"] == 10000
    assert reloaded.get_owner_capacity(123)["callsign"] == "N4W-T0Z"


def test_owner_capacity_cache_writes_only_when_free_space_changes(tmp_path: Path) -> None:
    handler = FleetCarrierHandler(object())
    handler.configure_owner_capacity_cache(str(tmp_path))

    entry = {
        "event": "CarrierStats",
        "CarrierID": 123,
        "Callsign": "N4W-T0Z",
        "SpaceUsage": {"TotalCapacity": 25000, "FreeSpace": 10000},
    }
    handler.update_fc_capacity_from_journal_stats(entry)
    cache_path = tmp_path / "fc_owner_capacity_cache.json"
    first = cache_path.stat().st_mtime_ns
    handler.update_fc_capacity_from_journal_stats(entry)
    second = cache_path.stat().st_mtime_ns

    assert second == first


def test_replace_fc_cargo_manifest_removes_missing_commodities() -> None:
    handler = FleetCarrierHandler(object())
    handler.linked_fcs[123] = {
        "marketId": 123,
        "cargo": {"steel": 100, "aluminium": 50},
    }

    cargo = handler.replace_fc_cargo_manifest(
        123,
        {"Steel": 25, "CMM Composite": 0},
        source="raven_colonial_api",
        timestamp="2026-06-16T00:00:00Z",
    )

    assert cargo == {"steel": 25}
    assert handler.linked_fcs[123]["cargo"] == {"steel": 25}
    assert handler.linked_fcs[123]["cargoSource"] == "raven_colonial_api"


def test_apply_fc_cargo_delta_removes_zero_quantity() -> None:
    handler = FleetCarrierHandler(object())
    handler.linked_fcs[123] = {"marketId": 123, "cargo": {"steel": 10}}

    cargo = handler.apply_fc_cargo_delta(123, "Steel", -10)

    assert cargo == {}
    assert handler.linked_fcs[123]["cargo"] == {}


def test_capi_does_not_replace_non_empty_server_snapshot_without_timestamp() -> None:
    class ApiQueue:
        def __init__(self) -> None:
            self.queued = []

        def queue_api_call(self, *args) -> None:
            self.queued.append(args)

    api = ApiQueue()
    handler = FleetCarrierHandler(api)
    handler.linked_fcs[123] = {
        "marketId": 123,
        "cargo": {"steel": 100},
        "cargoSource": "raven_colonial_api",
        "cargoUpdatedAt": "2026-06-16T00:00:00Z",
    }

    handler.update_fc_cargo_from_capi(123, {"aluminium": 50})

    assert handler.linked_fcs[123]["cargo"] == {"steel": 100}
    assert api.queued == []


def test_api_refresh_guard_blocks_repeated_refreshes_within_cooldown() -> None:
    handler = FleetCarrierHandler(object())
    handler.current_station_type = "FleetCarrier"

    allowed, reason, _cooldown = handler.can_refresh_fc_cargo_from_api(
        123, "manual_tracking_toggle"
    )
    blocked, blocked_reason, cooldown = handler.can_refresh_fc_cargo_from_api(
        123, "manual_tracking_toggle"
    )

    assert allowed is True
    assert reason == "allowed"
    assert blocked is False
    assert blocked_reason.startswith("cooldown_active_")
    assert cooldown > 0


def test_fc_journal_market_id_strings_match_integer_cache_keys() -> None:
    class ApiQueue:
        def __init__(self) -> None:
            self.queued = []

        def queue_api_call(self, *args) -> None:
            self.queued.append(args)

    api = ApiQueue()
    handler = FleetCarrierHandler(api)
    handler.linked_fcs[123] = {"marketId": 123, "cargo": {"steel": 10}}
    handler.update_eligible_fc_market_ids.add(123)
    handler.current_station_type = "FleetCarrier"

    handled = handler.handle_marketbuy_event(
        {"MarketID": "123", "Type": "Steel", "Count": 4}
    )

    assert handled is True
    assert handler.linked_fcs[123]["cargo"] == {"steel": 6}
    assert len(api.queued) == 1


def test_fc_journal_delta_updates_overlay_cache_when_all_carriers_selected() -> None:
    class ApiQueue:
        def __init__(self) -> None:
            self.queued = []
            self.overlay_carrier_tracking_enabled = True
            self.overlay_fc_selection = "all"
            self.overlay_project_linked_fcs = [{"marketId": 123, "label": "FC-A"}]
            self.overlay_fc_cargo_by_market = {}
            self.refresh_count = 0

        def queue_api_call(self, *args) -> None:
            self.queued.append(args)

        def refresh_build_overlay(self) -> None:
            self.refresh_count += 1

    api = ApiQueue()
    handler = FleetCarrierHandler(api)
    handler.linked_fcs[123] = {"marketId": 123, "cargo": {"steel": 10}}
    handler.update_eligible_fc_market_ids.add(123)
    handler.current_station_type = "FleetCarrier"

    handled = handler.handle_marketbuy_event(
        {"MarketID": 123, "Type": "Steel", "Count": 4}
    )

    assert handled is True
    assert api.overlay_fc_cargo_by_market == {123: {"steel": 6}}
    assert api.refresh_count == 1


def test_fc_journal_delta_does_not_update_overlay_for_unlinked_current_view() -> None:
    api = SimpleNamespace(
        overlay_carrier_tracking_enabled=True,
        overlay_fc_selection="all",
        overlay_project_linked_fcs=[{"marketId": 999, "label": "FC-B"}],
        overlay_fc_cargo_by_market={},
        refresh_build_overlay=lambda: (_ for _ in ()).throw(
            AssertionError("should not refresh unrelated overlay carrier")
        ),
    )
    api.queue_api_call = lambda *args: None
    handler = FleetCarrierHandler(api)
    handler.linked_fcs[123] = {"marketId": 123, "cargo": {"steel": 10}}
    handler.update_eligible_fc_market_ids.add(123)
    handler.current_station_type = "FleetCarrier"

    handled = handler.handle_marketbuy_event(
        {"MarketID": 123, "Type": "Steel", "Count": 4}
    )

    assert handled is True
    assert api.overlay_fc_cargo_by_market == {}


def test_display_only_fc_is_not_patch_eligible_even_if_cached() -> None:
    class ApiQueue:
        def __init__(self) -> None:
            self.queued = []

        def queue_api_call(self, *args) -> None:
            self.queued.append(args)

    api = ApiQueue()
    handler = FleetCarrierHandler(api)
    handler.linked_fcs[123] = {"marketId": 123, "cargo": {"steel": 10}}
    handler.current_station_type = "FleetCarrier"

    handled = handler.handle_marketbuy_event(
        {"MarketID": 123, "Type": "Steel", "Count": 4}
    )

    assert handled is False
    assert handler.linked_fcs[123]["cargo"] == {"steel": 10}
    assert api.queued == []


def test_active_project_linked_fcs_are_update_eligible() -> None:
    class InnerApi:
        def get_all_cmdr_fcs(self, cmdr_name):
            return []

    class PluginApi:
        api_client = InnerApi()

        def __init__(self) -> None:
            self.queued = []

        def get_commander_projects(self, cmdr_name):
            return [
                {
                    "buildId": "build-1",
                    "linkedFC": [
                        {
                            "marketId": 321,
                            "name": "ABC-123",
                            "displayName": "Jaws of Defeat",
                        }
                    ],
                }
            ]

        def queue_api_call(self, *args) -> None:
            self.queued.append(args)

    api = PluginApi()
    handler = FleetCarrierHandler(api)
    assert handler.initialize_fcs("Fenris Nihilus") is True
    assert handler.is_update_eligible_fc(321) is True
    assert handler.linked_fcs[321]["displayName"] == "Jaws of Defeat"
    assert handler.linked_fcs[321]["eligibleViaActiveProject"] is True
    handler.current_station_type = "FleetCarrier"

    handled = handler.handle_marketbuy_event(
        {"MarketID": 321, "Type": "Steel", "Count": 4}
    )

    assert handled is True
    assert len(api.queued) == 1
    assert api.queued[0][1:] == (321, {"steel": -4})


def test_active_project_linked_fc_dedupes_profile_linked_market_id() -> None:
    class InnerApi:
        def get_all_cmdr_fcs(self, cmdr_name):
            return [
                {
                    "marketId": 321,
                    "name": "ABC-123",
                    "displayName": "Jaws of Defeat",
                    "cargo": {"steel": 10},
                }
            ]

    class PluginApi:
        api_client = InnerApi()

        def get_commander_projects(self, cmdr_name):
            return [
                {
                    "buildId": "build-1",
                    "linkedFC": [
                        {
                            "marketId": "321",
                            "name": "ABC-123",
                            "displayName": "Jaws of Defeat",
                        }
                    ],
                }
            ]

    handler = FleetCarrierHandler(PluginApi())

    assert handler.initialize_fcs("Fenris Nihilus") is True
    assert handler.update_eligible_fc_market_ids == {321}
    assert len(handler.linked_fcs) == 1
    assert handler.linked_fcs[321]["cargo"] == {"steel": 10}
    assert handler.linked_fcs[321]["eligibleViaActiveProject"] is True
