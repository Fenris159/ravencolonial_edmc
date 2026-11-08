"""Cover old raw cargo attribution without discarding later physical movement."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from test_carrier_cargo_parity import (
    drain, market_session as _market_fixture, session as _session_fixture, write_market_cargo_file,
)
from test_mixed_inventory_attribution import journal


def cargo(active: SimpleNamespace, key: str, amount: int, second: int) -> None:
    """Deliver a full ship inventory at the game-file boundary."""
    journal(active, "Cargo", {key: amount}, timestamp=f"2026-11-08T17:00:0{second}Z", Vessel="Ship",
            Count=amount, Inventory=[{"Name": key, "Count": amount}])


def setup_ship(edmc_plugin, monkeypatch: pytest.MonkeyPatch, key: str, stock: int) -> SimpleNamespace:
    """Establish the initial carrier and ship inventories before introducing raw inference."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {key: stock}
    _market_fixture.__wrapped__(active)
    journal(active, "Location", {key: 20 if key == "drones" else 50}, Docked=True,
            StationType="FleetCarrier", MarketID=101, StationServices=["squadronBank"])
    cargo(active, key, 20 if key == "drones" else 50, 0)
    drain(active.plugin)
    return active


@pytest.mark.parametrize("stock, raw_stock, final_stock", [(5, 15, 7), (20, 30, 22)])
def test_manual_manifest_covers_the_old_ship_only_component(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stock: int, raw_stock: int, final_stock: int,
) -> None:
    """A delayed SellDrones cannot debit a corrected5/20; nonunique placement remains explicit on disk."""
    active = setup_ship(edmc_plugin, monkeypatch, "drones", stock)
    active.plugin.configure_pending_carrier_deliveries(str(tmp_path))
    cargo(active, "drones", 10, 1)
    drain(active.plugin)
    assert active.remote[101] == {"drones": raw_stock}
    handler = active.plugin.fc_handler
    identity = handler.prepare_manual_manifest(101, {"drones": stock})
    assert handler.save_manual_manifest(101, {"drones": stock}, identity) == {"drones": stock}
    handler.finish_manual_manifest(identity)
    journal(active, "SellDrones", {"drones": 0}, timestamp="2026-11-08T17:00:01Z", Count=10)
    cargo(active, "drones", 10, 2)
    drain(active.plugin)
    assert active.remote[101] == {"drones": stock}
    if stock == 20:
        restored = active.load.PendingCarrierDeliveries()
        restored.configure(str(tmp_path))
        frame, = restored.inventory_frames("Alpha", 101)
        assert frame["state"]["manual_uncertain_changes"] == {"drones": -10}
        identity = handler.prepare_manual_manifest(101, {"drones": 20})
        assert handler.save_manual_manifest(101, {"drones": 20}, identity) == {"drones": 20}
        handler.finish_manual_manifest(identity)
        cargo(active, "drones", 10, 3)
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
    cargo(active, "drones", 8, 4)
    drain(active.plugin)
    assert active.remote[101] == {"drones": final_stock}
    assert active.plugin.pending_carrier_deliveries.records() == []


@pytest.mark.parametrize("initial, target, new_ship_only, expected", [
    (0, 10, False, 15), (20, 20, False, 25), (0, 10, True, 10),
])
def test_new_physical_evidence_survives_the_manual_http_completion(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, initial: int, target: int, new_ship_only: bool, expected: int,
) -> None:
    """The next bank5 survives, and a later journal can still classify evidence observed during the write."""
    active = setup_ship(edmc_plugin, monkeypatch, "steel", initial)
    cargo(active, "steel", 40, 1)
    drain(active.plugin)
    handler = active.plugin.fc_handler
    identity = handler.prepare_manual_manifest(101, {"steel": target})
    request = active.plugin.api_client.session.request

    def reply_after_new_cargo(method: str, url: str, **kwargs) -> requests.Response:
        response = request(method, url, **kwargs)
        if method == "POST" and url.endswith("/cargo"):
            cargo(active, "steel", 35, 2)
        return response

    monkeypatch.setattr(active.plugin.api_client.session, "request", reply_after_new_cargo)
    assert handler.save_manual_manifest(101, {"steel": target}, identity) == {"steel": target}
    handler.finish_manual_manifest(identity)
    drain(active.plugin)
    if new_ship_only:
        journal(active, "EjectCargo", {"steel": 30}, timestamp="2026-11-08T17:00:02Z", Type="steel", Count=5)
        cargo(active, "steel", 35, 3)
        drain(active.plugin)
    assert active.remote[101] == {"steel": expected}
    assert active.plugin.pending_carrier_deliveries.records() == []


def test_retained_manual_intent_covers_raw_evidence_after_a_checkpoint_failure(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Retrying a durably delayed Save cannot release an old correction after its accepted reservation."""
    active = setup_ship(edmc_plugin, monkeypatch, "drones", 5)
    active.plugin.configure_pending_carrier_deliveries(str(tmp_path))
    cargo(active, "drones", 10, 1)
    drain(active.plugin)
    handler = active.plugin.fc_handler

    def unavailable(path: Path, target: Path) -> None:
        raise OSError("checkpoint unavailable")

    with monkeypatch.context() as blocked:
        blocked.setattr(Path, "replace", unavailable)
        with pytest.raises(OSError, match="checkpoint unavailable"):
            handler.prepare_manual_manifest(101, {"drones": 5})
    journal(active, "SellDrones", {"drones": 0}, timestamp="2026-11-08T17:00:01Z", Count=10)
    cargo(active, "drones", 10, 2)
    handler.retry_pending_deliveries()
    drain(active.plugin)
    assert active.remote[101] == {"drones": 5}
    cargo(active, "drones", 8, 3)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 7}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


@pytest.mark.parametrize("event, hold, expected", [("MarketSell", 35, 15), ("MarketBuy", 45, 5)])
def test_same_second_trade_after_manual_save_uses_its_complete_inventory(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, event: str, hold: int, expected: int,
) -> None:
    """A valid matching game-file observation updates the bank and ship without another Cargo callback."""
    active = setup_ship(edmc_plugin, monkeypatch, "steel", 0)
    cargo(active, "steel", 40, 1)
    drain(active.plugin)
    write_market_cargo_file(active, monkeypatch, tmp_path, 40, timestamp="2026-11-08T17:00:01Z")
    handler = active.plugin.fc_handler
    identity = handler.prepare_manual_manifest(101, {"steel": 10})
    assert handler.save_manual_manifest(101, {"steel": 10}, identity) == {"steel": 10}
    handler.finish_manual_manifest(identity)
    write_market_cargo_file(active, monkeypatch, tmp_path, hold, timestamp="2026-11-08T17:00:01Z")
    journal(active, event, {"steel": hold}, timestamp="2026-11-08T17:00:01Z", MarketID=101,
            Type="steel", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"steel": expected}
    assert active.ship == {"steel": hold}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_repeated_new_ship_only_changes_after_manual_save_preserve_later_bank_movement(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Two proved new limpet purchases cannot make the following two-tonne deposit ambiguous."""
    active = setup_ship(edmc_plugin, monkeypatch, "drones", 0)
    cargo(active, "drones", 10, 1)
    drain(active.plugin)
    handler = active.plugin.fc_handler
    identity = handler.prepare_manual_manifest(101, {"drones": 0})
    assert handler.save_manual_manifest(101, {"drones": 0}, identity) == {}
    handler.finish_manual_manifest(identity)
    for hold in (15, 20):
        write_market_cargo_file(
            active, monkeypatch, tmp_path, hold, timestamp="2026-11-08T17:00:01Z",
            Inventory=[{"Name": "drones", "Count": hold}],
        )
        journal(active, "BuyDrones", {"drones": hold}, timestamp="2026-11-08T17:00:01Z", Count=5)
        drain(active.plugin)
    cargo(active, "drones", 18, 2)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 2}
    assert active.ship == {"drones": 18}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
