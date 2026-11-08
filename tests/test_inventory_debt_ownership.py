"""Keep deferred cargo changes represented once across anchor restoration and later callbacks."""

import json
from pathlib import Path

import pytest

from test_carrier_cargo_parity import drain, session as _session_fixture
from test_held_inventory_attribution import full_cargo, waiting_links as _waiting_fixture
from test_mixed_inventory_attribution import journal


@pytest.fixture
def waiting_stock(edmc_plugin, monkeypatch: pytest.MonkeyPatch):
    """Use the real gated profile boundary for delayed old limpet callbacks."""
    yield from _waiting_fixture.__wrapped__(edmc_plugin, monkeypatch)


def prepare(edmc_plugin, monkeypatch: pytest.MonkeyPatch):
    """Begin with a known ship and an empty carrier before a read-ahead steel deposit."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"steel": 0, "drones": 0}
    active.journal("Loadout", Ship="python", CargoCapacity=100, Modules=[])
    journal(active, "Location", {"steel": 50, "drones": 20}, Docked=True, StationType="FleetCarrier",
            MarketID=101, StationServices=["squadronBank"])
    return active


def file_hold(active, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, amount: int, second: int) -> None:
    """Supply a complete matching main-ship game file for the next callback."""
    monkeypatch.setattr(active.load.config, "default_journal_dir", str(tmp_path), raising=False)
    (tmp_path / "Cargo.json").write_text(json.dumps({
        "event": "Cargo", "timestamp": f"2026-11-08T17:00:0{second}Z", "Vessel": "Ship", "Count": amount + 20,
        "Inventory": [{"Name": "steel", "Count": amount}, {"Name": "drones", "Count": 20}],
    }))


def held_withdrawal(active, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Observe a complete withdrawal20 while Raven has only10; retain the debt rather than clamping."""
    full_cargo(active, {"steel": 40, "drones": 20}, 2)
    drain(active.plugin)
    file_hold(active, monkeypatch, tmp_path, 60, 3)
    journal(active, "CargoTransfer", {"steel": 60, "drones": 20}, timestamp="2026-11-08T17:00:03Z",
            Transfers=[{"Type": "steel", "Count": 20, "Direction": "toship"}])
    drain(active.plugin)


def test_refined_complete_interval_keeps_its_accounting_when_a_later_callback_restores_the_anchor(
    waiting_stock,
) -> None:
    """Buy10, deposit5, then buy1 leaves five bank drones even after same-second rollback."""
    active, raw = waiting_stock.active, waiting_stock.raw
    active.remote[101] = {"steel": 0, "drones": 0}
    raw("Cargo", {"steel": 50, "drones": 25}, timestamp="2026-11-08T17:00:02Z", Vessel="Ship", Count=75,
        Inventory=[{"Name": "steel", "Count": 50}, {"Name": "drones", "Count": 25}])
    raw("BuyDrones", {"steel": 50, "drones": 35}, timestamp="2026-11-08T17:00:01Z", Count=10)
    waiting_stock.finish()
    journal(active, "BuyDrones", {"steel": 50, "drones": 26}, timestamp="2026-11-08T17:00:02Z", Count=1)
    full_cargo(active, {"steel": 50, "drones": 26}, 3)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 0, "drones": 5}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_restoring_an_anchor_does_not_duplicate_its_unissued_ship_only_correction(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ejection20 and collection20 cancel; restoring an anchor must preserve the separate bank10."""
    active = prepare(edmc_plugin, monkeypatch)
    full_cargo(active, {"steel": 40, "drones": 20}, 3)
    drain(active.plugin)
    journal(active, "EjectCargo", {"steel": 20, "drones": 20}, timestamp="2026-11-08T17:00:01Z",
            Type="steel", Count=20)
    journal(active, "BuyDrones", {"steel": 40, "drones": 21}, timestamp="2026-11-08T17:00:03Z", Count=1)
    journal(active, "CollectCargo", {"steel": 60, "drones": 21}, timestamp="2026-11-08T17:00:02Z",
            Type="steel", Count=20)
    full_cargo(active, {"steel": 40, "drones": 21}, 4)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 10, "drones": 0}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


@pytest.mark.parametrize("deposit, counts, expected", [(False, (10,), 0), (False, (5, 5), 0), (True, (10,), 5)])
def test_old_ship_only_refinement_nets_with_the_withheld_withdrawal(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, deposit: bool, counts: tuple, expected: int,
) -> None:
    """Bank deposit20 plus collection10 followed by withdrawal20 leaves zero bank steel."""
    active = prepare(edmc_plugin, monkeypatch)
    held_withdrawal(active, monkeypatch, tmp_path)
    if deposit:
        full_cargo(active, {"steel": 55, "drones": 20}, 4)
    for index, count in enumerate(counts):
        journal(active, "CollectCargo", {"steel": 70, "drones": 20}, timestamp="2026-11-08T17:00:01Z",
                Type="steel", Count=count)
        if len(counts) == 2 and index == 0:
            drain(active.plugin)
            assert active.remote[101] == {"steel": 10, "drones": 0}
    full_cargo(active, {"steel": 55 if deposit else 60, "drones": 20}, 5)
    drain(active.plugin)
    assert active.remote[101] == {"steel": expected, "drones": 0}


def test_a_later_known_sale_is_reported_while_an_older_withdrawal_remains_unfunded(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """The five-tonne sale is independent of the older held withdrawal and survives unchanged inventory."""
    active = prepare(edmc_plugin, monkeypatch)
    held_withdrawal(active, monkeypatch, tmp_path)
    file_hold(active, monkeypatch, tmp_path, 55, 4)
    journal(active, "MarketSell", {"steel": 55, "drones": 20}, timestamp="2026-11-08T17:00:04Z",
            MarketID=101, Type="steel", Count=5)
    full_cargo(active, {"steel": 55, "drones": 20}, 5)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 15, "drones": 0}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames("Alpha", 101)) == 1
