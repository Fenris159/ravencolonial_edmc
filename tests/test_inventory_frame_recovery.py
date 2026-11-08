"""Keep deferred ship evidence behind the authoritative carrier correction that covers it."""

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
    assert inventory_session.remote[101] == {"steel": 80}


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
    assert frame["state"]["before"] == {"steel": 50}
    assert replacement["cargo"] == {"steel": 125}
    assert replacement["covered_frame_ids"] == [frame["id"]]
    assert record["cargo"] == {"steel": 2}
    assert record["attempted"] is False
    assert active.remote[101] == {"steel": 80}


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
    assert frame["state"]["before"] == {"steel": 35}
    assert frame["state"]["accounted"] == {"steel": -2}
    assert active.remote[101] == {"steel": 127}
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
    assert active.remote[101] == {"steel": 80}
    frame, = active.plugin.pending_carrier_deliveries.inventory_frames("Alpha", 101)
    assert frame["state"]["accounted"] == {"steel": -5}
    active.load.journal_entry("Alpha", False, "Sol", "", {"event": "Undocked"},
                              {"Docked": False, "ShipType": "python", "Cargo": {"steel": 35}})
    handler.update_fc_cargo_from_capi(101, {"steel": 90}, "2026-11-08T17:00:04Z")
    drain(active.plugin)
    assert active.remote[101] == {"steel": 90}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
    assert active.plugin.pending_carrier_deliveries.replacements() == []
    assert active.plugin.pending_carrier_deliveries.records() == []


def test_inventory_compensation_waits_for_a_durable_checkpoint_then_recovers(
    inventory_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A disk failure cannot send compensation without its recovery evidence; retry preserves the bank deposit."""
    active = inventory_session
    active.plugin.configure_pending_carrier_deliveries(str(tmp_path))
    active.dock(True)
    active.journal("Cargo", 40, timestamp="2026-11-08T17:00:02Z", Vessel="Ship", Count=40,
                   Inventory=[{"Name": "steel", "Count": 40}])
    drain(active.plugin)
    assert active.remote[101] == {"steel": 85}
    replace = Path.replace

    def unavailable(path: Path, target: Any) -> None:
        raise OSError("temporary storage failure")

    monkeypatch.setattr(Path, "replace", unavailable)
    active.journal("MarketSell", 35, timestamp="2026-11-08T17:00:02Z", MarketID=101, Type="steel", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 85}
    monkeypatch.setattr(Path, "replace", replace)
    active.plugin.fc_handler.retry_pending_deliveries()
    drain(active.plugin)
    assert active.remote[101] == {"steel": 80}
    restored = active.load.PendingCarrierDeliveries()
    restored.configure(str(tmp_path))
    frame, = restored.inventory_frames("Alpha", 101)
    assert frame["state"]["before"] == {"steel": 50}
    assert frame["state"]["accounted"] == {"steel": -5}
    active.journal("Cargo", 35, timestamp="2026-11-08T17:00:03Z", Vessel="Ship", Count=35,
                   Inventory=[{"Name": "steel", "Count": 35}])
    drain(active.plugin)
    assert active.remote[101] == {"steel": 90}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
