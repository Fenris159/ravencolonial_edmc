"""Keep deferred ship evidence behind the authoritative carrier correction that covers it."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import requests

from test_carrier_cargo_parity import drain, market_session as _market_fixture, session as _session_fixture


@pytest.fixture
def inventory_session(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Reuse the actual journal and HTTP boundary setup without collecting another test module."""
    return _market_fixture.__wrapped__(_session_fixture.__wrapped__(edmc_plugin, monkeypatch))


def defer_bank_evidence(inventory_session: SimpleNamespace) -> None:
    """Leave a ten-tonne bank movement unresolved after a same-second sale."""
    inventory_session.dock(True)
    inventory_session.journal("Cargo", 40, timestamp="2026-11-08T17:00:02Z", Vessel="Ship", Count=40,
                              Inventory=[{"Name": "steel", "Count": 40}])
    inventory_session.journal("MarketSell", 35, timestamp="2026-11-08T17:00:02Z", MarketID=101,
                              Type="steel", Count=5)
    drain(inventory_session.plugin)
    assert inventory_session.remote[101] == {"steel": 85}


def test_late_ship_inventory_cannot_reapply_bank_evidence_covered_by_a_manual_save(
    inventory_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late confirmation of an earlier bank movement must leave the user's corrected stock at125."""
    active = inventory_session
    defer_bank_evidence(active)
    handler = active.plugin.fc_handler
    reservation = handler.prepare_manual_manifest(101, {"steel": 125})
    request = active.plugin.api_client.session.request

    def reply_after_inventory(method: str, url: str, **kwargs: Any) -> requests.Response:
        response = request(method, url, **kwargs)
        if method == "POST" and url.endswith("/cargo"):
            active.journal("Cargo", 35, timestamp="2026-11-08T17:00:03Z", Vessel="Ship", Count=35,
                           Inventory=[{"Name": "steel", "Count": 35}])
        return response

    monkeypatch.setattr(active.plugin.api_client.session, "request", reply_after_inventory)
    assert handler.save_manual_manifest(101, {"steel": 125}, reservation) == {"steel": 125}
    handler.finish_manual_manifest(reservation)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 125}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
    assert active.plugin.pending_carrier_deliveries.records() == []


def test_new_trade_while_a_manual_save_is_pending_survives_the_old_inventory_barrier(
    inventory_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuinely new sale adds two after the125 correction rather than disappearing with old evidence."""
    active = inventory_session
    defer_bank_evidence(active)
    handler = active.plugin.fc_handler
    reservation = handler.prepare_manual_manifest(101, {"steel": 125})
    request = active.plugin.api_client.session.request

    def reply_after_trade(method: str, url: str, **kwargs: Any) -> requests.Response:
        response = request(method, url, **kwargs)
        if method == "POST" and url.endswith("/cargo"):
            active.journal("MarketSell", 33, timestamp="2026-11-08T17:00:03Z", MarketID=101,
                           Type="steel", Count=2)
        return response

    monkeypatch.setattr(active.plugin.api_client.session, "request", reply_after_trade)
    assert handler.save_manual_manifest(101, {"steel": 125}, reservation) == {"steel": 125}
    handler.finish_manual_manifest(reservation)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 127}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
    assert active.plugin.pending_carrier_deliveries.records() == []


def test_failed_manual_save_retains_the_covered_inventory_barrier_across_restart(
    inventory_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An uncertain full write must retain the old physical evidence and hold a later sale after restart."""
    active = inventory_session
    active.plugin.configure_pending_carrier_deliveries(str(tmp_path))
    defer_bank_evidence(active)
    handler = active.plugin.fc_handler
    reservation = handler.prepare_manual_manifest(101, {"steel": 125})
    request = active.plugin.api_client.session.request

    def reject_after_inventory(method: str, url: str, **kwargs: Any) -> requests.Response:
        if method == "POST" and url.endswith("/cargo"):
            active.journal("Cargo", 35, timestamp="2026-11-08T17:00:03Z", Vessel="Ship", Count=35,
                           Inventory=[{"Name": "steel", "Count": 35}])
            response = requests.Response()
            response.status_code = 503
            response._content = b"{}"
            return response
        return request(method, url, **kwargs)

    monkeypatch.setattr(active.plugin.api_client.session, "request", reject_after_inventory)
    assert handler.save_manual_manifest(101, {"steel": 125}, reservation) is None
    handler.finish_manual_manifest(reservation)
    active.journal("MarketSell", 33, timestamp="2026-11-08T17:00:04Z", MarketID=101, Type="steel", Count=2)
    drain(active.plugin)
    restored = active.load.PendingCarrierDeliveries()
    restored.configure(str(tmp_path))
    frame, = restored.inventory_frames("Alpha", 101)
    replacement, = restored.replacements("Alpha", 101)
    record, = restored.records("Alpha", 101)
    assert frame["state"]["reason"] == "ambiguous"
    assert replacement["cargo"] == {"steel": 125}
    assert replacement["covered_frame_ids"] == [frame["id"]]
    assert record["cargo"] == {"steel": 2}
    assert record["attempted"] is False
    assert active.remote[101] == {"steel": 85}


def test_manual_acknowledgement_preserves_a_new_inventory_frame_created_during_the_write(
    inventory_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A newer bank ambiguity remains recoverable after acknowledgement of a correction covering older evidence."""
    active = inventory_session
    defer_bank_evidence(active)
    handler = active.plugin.fc_handler
    reservation = handler.prepare_manual_manifest(101, {"steel": 125})
    request = active.plugin.api_client.session.request

    def reply_after_new_frame(method: str, url: str, **kwargs: Any) -> requests.Response:
        response = request(method, url, **kwargs)
        if method == "POST" and url.endswith("/cargo"):
            active.journal("Cargo", 35, timestamp="2026-11-08T17:00:03Z", Vessel="Ship", Count=35,
                           Inventory=[{"Name": "steel", "Count": 35}])
            active.journal("Cargo", 30, timestamp="2026-11-08T17:00:04Z", Vessel="Ship", Count=30,
                           Inventory=[{"Name": "steel", "Count": 30}])
            active.journal("MarketSell", 28, timestamp="2026-11-08T17:00:04Z", MarketID=101,
                           Type="steel", Count=2)
        return response

    monkeypatch.setattr(active.plugin.api_client.session, "request", reply_after_new_frame)
    assert handler.save_manual_manifest(101, {"steel": 125}, reservation) == {"steel": 125}
    handler.finish_manual_manifest(reservation)
    drain(active.plugin)
    frame, = active.plugin.pending_carrier_deliveries.inventory_frames("Alpha", 101)
    assert frame["state"]["reason"] == "ambiguous"
    assert active.remote[101] == {"steel": 130}
    active.journal("Cargo", 28, timestamp="2026-11-08T17:00:05Z", Vessel="Ship", Count=28,
                   Inventory=[{"Name": "steel", "Count": 28}])
    drain(active.plugin)
    assert active.remote[101] == {"steel": 132}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_fresh_capi_can_resolve_inventory_evidence_after_a_previous_capi_seed(
    inventory_session: SimpleNamespace,
) -> None:
    """A fresh complete carrier stock can resolve deferred bank evidence even after initial CAPI sync."""
    active = inventory_session
    active.dock(True)
    handler = active.plugin.fc_handler
    handler.update_fc_cargo_from_capi(101, {"steel": 75}, "2026-11-08T17:00:01Z", was_docked=False)
    drain(active.plugin)
    defer_bank_evidence(active)
    handler.update_fc_cargo_from_capi(101, {"steel": 90}, "2026-11-08T17:00:02Z", was_docked=False)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 85}
    frame, = active.plugin.pending_carrier_deliveries.inventory_frames("Alpha", 101)
    assert frame["state"]["reason"] == "ambiguous"
    active.load.journal_entry("Alpha", False, "Sol", "", {"event": "Undocked"},
                              {"Docked": False, "ShipType": "python", "Cargo": {"steel": 35}})
    handler.update_fc_cargo_from_capi(101, {"steel": 90}, "2026-11-08T17:00:04Z")
    drain(active.plugin)
    assert active.remote[101] == {"steel": 90}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
    assert active.plugin.pending_carrier_deliveries.replacements() == []
    assert active.plugin.pending_carrier_deliveries.records() == []


@pytest.mark.parametrize("field, value", [
    ("inventory_time", "invalid"), ("observed_at", True),
    ("inventory_time", float("nan")), ("observed_at", float("inf")),
])
def test_invalid_inventory_timestamps_preserve_the_checkpoint_and_block_carrier_writes(
    inventory_session: SimpleNamespace, tmp_path: Path, field: str, value: Any, caplog: pytest.LogCaptureFixture,
) -> None:
    """Corrupt recovery evidence must fail closed instead of crashing CAPI or overwriting the checkpoint."""
    active = inventory_session
    active.dock(True)
    frame = {"id": 1, "commander": "Alpha", "market_id": 101, "permitted_ids": [],
             "observed_at": 1000.0, "state": {"inventory_time": 1000.0}}
    target = frame if field == "observed_at" else frame["state"]
    target[field] = value
    checkpoint = tmp_path / "RavenColonial.carrier-cargo-recovery.json"
    checkpoint.write_text(json.dumps({"version": 2, "records": [], "replacements": [], "inventory_frames": [frame]}))
    original = checkpoint.read_bytes()
    active.plugin.configure_pending_carrier_deliveries(str(tmp_path))
    active.plugin.fc_handler.update_fc_cargo_from_capi(
        101, {"steel": 90}, "2026-11-08T17:00:04Z", was_docked=False,
    )
    drain(active.plugin)
    assert active.remote[101] == {"steel": 75}
    assert checkpoint.read_bytes() == original
    assert "Could not read pending carrier deliveries: Invalid inventory reconciliation timestamp" in caplog.text


def test_manual_frame_retirement_keeps_ship_cargo_ready_for_following_market_trades(
    inventory_session: SimpleNamespace,
) -> None:
    """Retiring bank inference cannot stop subsequent validated ship cargo from being published."""
    active = inventory_session
    defer_bank_evidence(active)
    handler = active.plugin.fc_handler
    reservation = handler.prepare_manual_manifest(101, {"steel": 125})
    assert handler.save_manual_manifest(101, {"steel": 125}, reservation) == {"steel": 125}
    handler.finish_manual_manifest(reservation)
    for second, after in ((3, 33), (4, 31)):
        active.journal("MarketSell", after, timestamp=f"2026-11-08T17:00:0{second}Z", MarketID=101,
                       Type="steel", Count=2)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 129}
    assert active.ship == {"steel": 31}


def test_rejected_bank_attribution_still_learns_ship_inventory_for_later_market_publications(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid first ship inventory remains publishable even if its inferred bank withdrawal was rejected."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"steel": 0}
    _market_fixture.__wrapped__(active)
    active.journal("Location", 50, Docked=True, StationType="FleetCarrier", MarketID=101,
                   StationServices=["squadronBank"])
    active.journal("Cargo", 60, timestamp="2026-11-08T17:00:01Z", Vessel="Ship", Count=60,
                   Inventory=[{"Name": "steel", "Count": 60}])
    drain(active.plugin)
    handler = active.plugin.fc_handler
    reservation = handler.prepare_manual_manifest(101, {})
    assert handler.save_manual_manifest(101, {}, reservation) == {"steel": 0}
    handler.finish_manual_manifest(reservation)
    for second, after in ((2, 58), (3, 56)):
        active.journal("MarketSell", after, timestamp=f"2026-11-08T17:00:0{second}Z", MarketID=101,
                       Type="steel", Count=2)
    drain(active.plugin)
    assert active.ship == {"steel": 56}
    assert active.remote[101] == {"steel": 4}
