"""Tests for Fleet Carrier dock baseline from local Market.json manifests."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any, Dict, List, Optional

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


def _sample_market_payload(*, market_id: int = 123, items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {
        "timestamp": "2026-06-21T12:00:00Z",
        "event": "Market",
        "MarketID": market_id,
        "StationName": "TEST-FC",
        "Items": items
        if items is not None
        else [
            {
                "Name": "$aluminium_name;",
                "Stock": 50,
                "Producer": True,
                "Consumer": False,
            },
            {
                "Name": "$steel_name;",
                "Stock": 0,
                "Producer": True,
                "Consumer": False,
            },
            {
                "Name": "$water_name;",
                "Stock": 999,
                "Producer": False,
                "Consumer": True,
            },
        ],
    }


class ApiQueue:
    def __init__(self) -> None:
        self.queued: list[tuple] = []

    def queue_api_call(self, *args) -> None:
        self.queued.append(args)


def test_needs_baseline_when_cache_empty() -> None:
    handler = FleetCarrierHandler(object())
    handler.update_eligible_fc_market_ids.add(123)
    handler.linked_fcs[123] = {"marketId": 123, "cargo": {}, "cargoSource": "active_project_linked_fc"}

    assert handler._needs_baseline(123) is True


def test_needs_baseline_for_trusted_server_snapshot_until_compared() -> None:
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


def test_cargo_from_market_payload_uses_producer_stock() -> None:
    handler = FleetCarrierHandler(object())
    cargo = handler._cargo_from_market_payload(_sample_market_payload())

    assert cargo == {"aluminium": 50}


def test_read_market_manifest_reads_market_json(tmp_path: Path, monkeypatch) -> None:
    market_path = tmp_path / "market.json"
    market_path.write_text(json.dumps(_sample_market_payload(market_id=321)), encoding="utf-8")

    handler = FleetCarrierHandler(object())
    monkeypatch.setattr(
        handler,
        "_recent_market_manifest_paths",
        lambda journal_dir, limit=1: [str(market_path)],
    )
    monkeypatch.setattr(handler, "_journal_market_helpers", lambda: (lambda: str(tmp_path), None))

    manifest = handler._read_market_manifest(321)

    assert manifest == {"aluminium": 50}


def test_read_market_manifest_snapshot_preserves_timestamp(tmp_path: Path, monkeypatch) -> None:
    market_path = tmp_path / "market.json"
    market_path.write_text(json.dumps(_sample_market_payload(market_id=321)), encoding="utf-8")

    handler = FleetCarrierHandler(object())
    monkeypatch.setattr(
        handler,
        "_recent_market_manifest_paths",
        lambda journal_dir, limit=1: [str(market_path)],
    )
    monkeypatch.setattr(handler, "_journal_market_helpers", lambda: (lambda: str(tmp_path), None))

    snapshot = handler._read_market_manifest_snapshot(321)

    assert snapshot == ({"aluminium": 50}, "2026-06-21T12:00:00Z")


def test_dock_baseline_pushes_full_snapshot_when_manifest_differs(tmp_path: Path, monkeypatch) -> None:
    market_path = tmp_path / "market.json"
    market_path.write_text(json.dumps(_sample_market_payload(market_id=123)), encoding="utf-8")

    api = ApiQueue()
    handler = FleetCarrierHandler(api)
    handler.update_eligible_fc_market_ids.add(123)
    handler.linked_fcs[123] = {
        "marketId": 123,
        "cargo": {"steel": 10},
        "cargoSource": "active_project_linked_fc",
    }

    monkeypatch.setattr(
        handler,
        "_recent_market_manifest_paths",
        lambda journal_dir, limit=1: [str(market_path)],
    )
    monkeypatch.setattr(handler, "_journal_market_helpers", lambda: (lambda: str(tmp_path), None))

    handler._maybe_set_dock_baseline(123)

    assert handler.linked_fcs[123]["cargo"] == {"aluminium": 50}
    assert handler.linked_fcs[123]["cargoSource"] == "local_dock_baseline"
    assert handler.linked_fcs[123]["cargoUpdatedAt"] == "2026-06-21T12:00:00Z"
    assert handler._baseline_done == {123}
    assert len(api.queued) == 1
    assert api.queued[0][0].__name__ == "_update_fc_cargo"


def test_dock_baseline_skips_server_push_when_manifest_matches(tmp_path: Path, monkeypatch) -> None:
    market_path = tmp_path / "market.json"
    market_path.write_text(json.dumps(_sample_market_payload(market_id=123)), encoding="utf-8")

    api = ApiQueue()
    handler = FleetCarrierHandler(api)
    handler.linked_fcs[123] = {
        "marketId": 123,
        "cargo": {"aluminium": 50},
        "cargoSource": "journal",
    }

    monkeypatch.setattr(
        handler,
        "_recent_market_manifest_paths",
        lambda journal_dir, limit=1: [str(market_path)],
    )
    monkeypatch.setattr(handler, "_journal_market_helpers", lambda: (lambda: str(tmp_path), None))

    handler._maybe_set_dock_baseline(123)

    assert handler.linked_fcs[123]["cargoSource"] == "journal"
    assert api.queued == []
    assert handler._baseline_done == {123}


def test_dock_baseline_compares_trusted_server_snapshot(tmp_path: Path, monkeypatch) -> None:
    market_path = tmp_path / "market.json"
    market_path.write_text(json.dumps(_sample_market_payload(market_id=123)), encoding="utf-8")

    api = ApiQueue()
    handler = FleetCarrierHandler(api)
    handler.linked_fcs[123] = {
        "marketId": 123,
        "cargo": {"aluminium": 50},
        "cargoSource": "raven_colonial_api",
    }

    monkeypatch.setattr(
        handler,
        "_recent_market_manifest_paths",
        lambda journal_dir, limit=1: [str(market_path)],
    )
    monkeypatch.setattr(handler, "_journal_market_helpers", lambda: (lambda: str(tmp_path), None))

    handler._maybe_set_dock_baseline(123)

    assert handler.linked_fcs[123]["cargoSource"] == "raven_colonial_api"
    assert api.queued == []
    assert handler._baseline_done == {123}


def test_handle_docked_event_triggers_baseline_for_eligible_fc(tmp_path: Path, monkeypatch) -> None:
    market_path = tmp_path / "market.json"
    market_path.write_text(json.dumps(_sample_market_payload(market_id=555)), encoding="utf-8")

    api = ApiQueue()
    handler = FleetCarrierHandler(api)
    handler.update_eligible_fc_market_ids.add(555)
    handler.linked_fcs[555] = {"marketId": 555, "cargo": {}, "cargoSource": "active_project_linked_fc"}

    monkeypatch.setattr(
        handler,
        "_recent_market_manifest_paths",
        lambda journal_dir, limit=1: [str(market_path)],
    )
    monkeypatch.setattr(handler, "_journal_market_helpers", lambda: (lambda: str(tmp_path), None))

    assert handler.handle_docked_event(
        {
            "StationType": "FleetCarrier",
            "MarketID": 555,
            "StationName": "TEST-555",
        }
    )

    assert handler._baseline_done == {555}
    assert len(api.queued) == 1


def test_pending_fc_delta_waits_for_delayed_dock_baseline(tmp_path: Path, monkeypatch) -> None:
    api = ApiQueue()
    callbacks = []

    def schedule_after(_delay_ms, callback):
        callbacks.append(callback)
        return "scheduled"

    api.schedule_after = schedule_after
    handler = FleetCarrierHandler(api)
    handler.update_eligible_fc_market_ids.add(123)
    handler.linked_fcs[123] = {
        "marketId": 123,
        "cargo": {"steel": 1},
        "cargoSource": "raven_colonial_api",
    }

    snapshots = [None, ({"aluminium": 50}, "2026-06-21T12:00:00Z")]
    monkeypatch.setattr(handler, "_read_market_manifest_snapshot", lambda mid: snapshots.pop(0))

    assert handler.handle_docked_event(
        {
            "StationType": "FleetCarrier",
            "MarketID": 123,
            "StationName": "TEST-123",
        }
    )
    assert callbacks
    assert handler._baseline_pending == {123}

    assert handler.handle_marketsell_event({"MarketID": 123, "Type": "Steel", "Count": 10})
    assert api.queued == []
    assert handler.linked_fcs[123]["cargo"] == {"steel": 1}

    callbacks.pop(0)()

    assert handler._baseline_pending == set()
    assert handler._baseline_done == {123}
    assert handler.linked_fcs[123]["cargo"] == {"aluminium": 50, "steel": 10}
    assert [call[0].__name__ for call in api.queued] == ["_update_fc_cargo", "_supply_fc"]


def test_clear_dock_context_clears_baseline_guard() -> None:
    handler = FleetCarrierHandler(object())
    handler.current_station_type = "FleetCarrier"
    handler.current_market_id = 123
    handler._baseline_done.add(123)

    handler.clear_dock_context()

    assert handler._baseline_done == set()
    assert handler.current_market_id is None
