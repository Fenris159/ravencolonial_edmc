"""Tests for Fleet Carrier dock baselines from server/CAPI manifests."""

from __future__ import annotations

import sys
import types
from typing import Any, Dict, Optional

_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
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


class ServerApi:
    def __init__(self, fc: Optional[Dict[str, Any]] = None) -> None:
        self.fc = fc
        self.get_fc_calls: list[int] = []

    def get_fc(self, market_id: int) -> Optional[Dict[str, Any]]:
        self.get_fc_calls.append(market_id)
        return self.fc


class ApiQueue:
    def __init__(self, fc: Optional[Dict[str, Any]] = None) -> None:
        self.queued: list[tuple] = []
        self.api_client = ServerApi(fc)

    def queue_api_call(self, *args) -> None:
        self.queued.append(args)


def test_needs_baseline_when_cache_empty() -> None:
    handler = FleetCarrierHandler(object())
    handler.update_eligible_fc_market_ids.add(123)
    handler.linked_fcs[123] = {"marketId": 123, "cargo": {}, "cargoSource": "active_project_linked_fc"}

    assert handler._needs_baseline(123) is True


def test_needs_baseline_until_dock_visit_completed() -> None:
    handler = FleetCarrierHandler(object())
    handler.linked_fcs[123] = {
        "marketId": 123,
        "cargo": {"steel": 10},
        "cargoSource": "raven_colonial_api",
    }

    assert handler._needs_baseline(123) is True

    handler._baseline_done.add(123)

    assert handler._needs_baseline(123) is False


def test_manifests_differ_normalizes_keys() -> None:
    handler = FleetCarrierHandler(object())

    assert handler._manifests_differ({"Steel": 10}, {"steel": 10}) is False
    assert handler._manifests_differ({"steel": 10}, {"steel": 11}) is True


def test_dock_baseline_uses_server_cache_without_fetch() -> None:
    api = ApiQueue()
    handler = FleetCarrierHandler(api)
    handler.update_eligible_fc_market_ids.add(123)
    handler.linked_fcs[123] = {
        "marketId": 123,
        "cargo": {"aluminium": 50},
        "cargoSource": "raven_colonial_api",
    }

    handler._maybe_set_dock_baseline(123)

    assert handler._baseline_done == {123}
    assert handler._baseline_pending == set()
    assert api.queued == []


def test_empty_server_manifest_is_valid_baseline() -> None:
    api = ApiQueue()
    handler = FleetCarrierHandler(api)
    handler.update_eligible_fc_market_ids.add(123)
    handler.linked_fcs[123] = {
        "marketId": 123,
        "cargo": {},
        "cargoSource": "raven_colonial_api",
    }

    handler._maybe_set_dock_baseline(123)

    assert handler._baseline_done == {123}
    assert api.queued == []


def test_dock_baseline_fetches_server_manifest_when_cache_missing() -> None:
    api = ApiQueue(
        {
            "marketId": 123,
            "cargo": {"aluminium": 50},
            "lastRefresh": "2026-06-23T02:35:17.3803583+00:00",
        }
    )
    handler = FleetCarrierHandler(api)
    handler.update_eligible_fc_market_ids.add(123)
    handler.linked_fcs[123] = {
        "marketId": 123,
        "cargo": {},
        "cargoSource": "active_project_linked_fc",
    }

    handler._maybe_set_dock_baseline(123)

    assert handler._baseline_pending == {123}
    assert len(api.queued) == 1
    func, market_id = api.queued.pop(0)
    assert func.__name__ == "_fetch_fc_baseline"

    assert func(market_id) is True

    assert handler._baseline_done == {123}
    assert handler._baseline_pending == set()
    assert handler.linked_fcs[123]["cargo"] == {"aluminium": 50}
    assert handler.linked_fcs[123]["cargoSource"] == "raven_colonial_api"
    assert handler.linked_fcs[123]["cargoUpdatedAt"] == "2026-06-23T02:35:17.3803583+00:00"


def test_capi_snapshot_satisfies_later_dock_baseline() -> None:
    api = ApiQueue()
    handler = FleetCarrierHandler(api)
    handler.update_eligible_fc_market_ids.add(123)
    handler.linked_fcs[123] = {
        "marketId": 123,
        "cargo": {},
        "cargoSource": "active_project_linked_fc",
    }

    handler.update_fc_cargo_from_capi(
        123,
        {"steel": 20},
        capi_timestamp="2026-06-22T04:43:51Z",
    )

    assert handler.linked_fcs[123]["cargo"] == {"steel": 20}
    assert handler._baseline_done == set()
    assert [call[0].__name__ for call in api.queued] == ["_update_fc_cargo"]

    handler._maybe_set_dock_baseline(123)

    assert handler._baseline_done == {123}
    assert handler.linked_fcs[123]["cargoSource"] == "capi"
    assert [call[0].__name__ for call in api.queued] == ["_update_fc_cargo"]


def test_handle_docked_event_triggers_server_baseline_for_eligible_fc() -> None:
    api = ApiQueue()
    handler = FleetCarrierHandler(api)
    handler.update_eligible_fc_market_ids.add(555)
    handler.linked_fcs[555] = {
        "marketId": 555,
        "cargo": {"steel": 1},
        "cargoSource": "raven_colonial_api",
    }

    assert handler.handle_docked_event(
        {
            "StationType": "FleetCarrier",
            "MarketID": 555,
            "StationName": "TEST-555",
        }
    )

    assert handler._baseline_done == {555}
    assert api.queued == []


def test_startup_current_state_triggers_dock_baseline_for_eligible_fc() -> None:
    api = ApiQueue()
    handler = FleetCarrierHandler(api)
    handler.update_eligible_fc_market_ids.add(555)
    handler.linked_fcs[555] = {
        "marketId": 555,
        "cargo": {"steel": 1},
        "cargoSource": "raven_colonial_api",
    }

    assert handler.initialize_current_dock_context(
        {
            "StationType": "FleetCarrier",
            "MarketID": 555,
            "StationName": "TEST-555",
        }
    )

    assert handler.current_station_type == "FleetCarrier"
    assert handler.current_market_id == 555
    assert handler._baseline_done == {555}
    assert api.queued == []


def test_startup_current_state_initializes_non_fc_without_baseline() -> None:
    handler = FleetCarrierHandler(object())

    assert handler.initialize_current_dock_context(
        {
            "StationType": "Coriolis",
            "MarketID": 999,
            "StationName": "TEST-STATION",
            "StationServices": ["commodities"],
        }
    ) is False

    assert handler.current_station_type == "Coriolis"
    assert handler.current_market_id == 999
    assert handler.last_station_services == ["commodities"]
    assert handler._baseline_done == set()


def test_pending_fc_delta_waits_for_server_baseline_fetch() -> None:
    api = ApiQueue(
        {
            "marketId": 123,
            "cargo": {"aluminium": 50},
            "lastRefresh": "2026-06-23T02:35:17.3803583+00:00",
        }
    )
    handler = FleetCarrierHandler(api)
    handler.update_eligible_fc_market_ids.add(123)
    handler.linked_fcs[123] = {
        "marketId": 123,
        "cargo": {},
        "cargoSource": "active_project_linked_fc",
    }

    assert handler.handle_docked_event(
        {
            "StationType": "FleetCarrier",
            "MarketID": 123,
            "StationName": "TEST-123",
        }
    )
    assert handler._baseline_pending == {123}
    assert [call[0].__name__ for call in api.queued] == ["_fetch_fc_baseline"]

    assert handler.handle_marketsell_event({"MarketID": 123, "Type": "Steel", "Count": 10})
    assert [call[0].__name__ for call in api.queued] == ["_fetch_fc_baseline"]
    assert handler.linked_fcs[123]["cargo"] == {}

    fetch_call = api.queued.pop(0)
    assert fetch_call[0](*fetch_call[1:]) is True

    assert handler._baseline_pending == set()
    assert handler._baseline_done == {123}
    assert handler.linked_fcs[123]["cargo"] == {"aluminium": 50, "steel": 10}
    assert [call[0].__name__ for call in api.queued] == ["_supply_fc"]


def test_failed_server_baseline_fetch_releases_pending_delta() -> None:
    api = ApiQueue(None)
    handler = FleetCarrierHandler(api)
    handler.update_eligible_fc_market_ids.add(123)
    handler.linked_fcs[123] = {
        "marketId": 123,
        "cargo": {},
        "cargoSource": "active_project_linked_fc",
    }

    assert handler.handle_docked_event(
        {
            "StationType": "FleetCarrier",
            "MarketID": 123,
            "StationName": "TEST-123",
        }
    )
    assert handler.handle_marketsell_event({"MarketID": 123, "Type": "Steel", "Count": 10})

    fetch_call = api.queued.pop(0)
    assert fetch_call[0](*fetch_call[1:]) is False

    assert handler._baseline_pending == set()
    assert handler._baseline_done == {123}
    assert handler.linked_fcs[123]["cargo"] == {"steel": 10}
    assert [call[0].__name__ for call in api.queued] == ["_supply_fc"]


def test_clear_dock_context_clears_baseline_guard() -> None:
    handler = FleetCarrierHandler(object())
    handler.current_station_type = "FleetCarrier"
    handler.current_market_id = 123
    handler._baseline_done.add(123)

    handler.clear_dock_context()

    assert handler._baseline_done == set()
    assert handler.current_market_id is None
