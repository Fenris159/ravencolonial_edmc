"""Consume held cargo ownership once when physical points or quantitative balances advance."""

import json
from pathlib import Path

import pytest

from test_carrier_cargo_parity import drain, session as _session_fixture, write_market_cargo_file
from test_mixed_inventory_attribution import inventory, journal


def game_file(active, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, steel: int, copper: int, second: int) -> None:
    """Supply a matching complete two-commodity ship inventory at the game-file boundary."""
    monkeypatch.setattr(active.load.config, "default_journal_dir", str(tmp_path), raising=False)
    (tmp_path / "Cargo.json").write_text(json.dumps({
        "event": "Cargo", "timestamp": f"2026-11-08T17:00:0{second}Z", "Vessel": "Ship", "Count": steel + copper,
        "Inventory": [{"Name": "steel", "Count": steel}, {"Name": "copper", "Count": copper}],
    }))


def mixed_hold(edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, acknowledged: bool):
    """Create the same held steel20 with either queued or acknowledged earlier steel10."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"steel": 0, "copper": 0}
    active.journal("Loadout", Ship="python", CargoCapacity=100, Modules=[])
    journal(active, "Location", {"steel": 50, "copper": 10}, Docked=True, StationType="FleetCarrier",
            MarketID=101, StationServices=["squadronBank"])
    inventory(active, 40, 10, 2)
    if acknowledged:
        drain(active.plugin)
    game_file(active, monkeypatch, tmp_path, 60, 10, 3)
    journal(active, "CargoTransfer", {"steel": 60, "copper": 10}, timestamp="2026-11-08T17:00:03Z",
            Transfers=[{"Type": "steel", "Count": 20, "Direction": "toship"}])
    return active


@pytest.mark.parametrize("withdrawals", [((5, 65, 4),), ((2, 62, 4), (3, 65, 5))])
def test_reported_trade_keeps_its_accounting_when_another_commodity_rejects_the_snapshot(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, withdrawals: tuple,
) -> None:
    """A later withdrawal5 cannot enter the held balance again after copper's observation is repaired."""
    active = mixed_hold(edmc_plugin, monkeypatch, tmp_path, True)
    for amount, hold, second in withdrawals:
        game_file(active, monkeypatch, tmp_path, hold, 20, second)
        journal(active, "CargoTransfer", {"steel": hold, "copper": 20},
                timestamp=f"2026-11-08T17:00:0{second}Z",
                Transfers=[{"Type": "steel", "Count": amount, "Direction": "toship"}])
    (tmp_path / "Cargo.json").unlink()
    journal(active, "CollectCargo", {"steel": 65, "copper": 30}, timestamp="2026-11-08T17:00:04Z",
            Type="copper", Count=10)
    inventory(active, 65, 20, 6)
    journal(active, "CollectCargo", {"steel": 85, "copper": 20}, timestamp="2026-11-08T17:00:01Z",
            Type="steel", Count=20)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 5, "copper": 0}


def test_accepting_a_later_held_point_transfers_its_unissued_purchase_into_the_balance_once(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A purchase5 included in an accepted held point cannot also debit independently after a sale funds it."""
    active = mixed_hold(edmc_plugin, monkeypatch, tmp_path, False)
    game_file(active, monkeypatch, tmp_path, 70, 10, 4)
    journal(active, "CargoTransfer", {"steel": 70, "copper": 10}, timestamp="2026-11-08T17:00:04Z",
            Transfers=[{"Type": "steel", "Count": 10, "Direction": "toship"}])
    game_file(active, monkeypatch, tmp_path, 75, 20, 5)
    journal(active, "CargoTransfer", {"steel": 75, "copper": 20}, timestamp="2026-11-08T17:00:05Z",
            Transfers=[{"Type": "steel", "Count": 5, "Direction": "toship"}])
    journal(active, "MarketSell", {"steel": 65, "copper": 20}, timestamp="2026-11-08T17:00:06Z",
            MarketID=101, Type="steel", Count=10)
    (tmp_path / "Cargo.json").unlink()
    journal(active, "CollectCargo", {"steel": 65, "copper": 30}, timestamp="2026-11-08T17:00:05Z",
            Type="copper", Count=10)
    drain(active.plugin)
    inventory(active, 65, 20, 7)
    journal(active, "CollectCargo", {"steel": 95, "copper": 20}, timestamp="2026-11-08T17:00:01Z",
            Type="steel", Count=30)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 15, "copper": 0}


def test_accepting_a_held_interval_consumes_known_changes_into_the_unfunded_physical_point(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An already known collection10 cannot become a withdrawal10 after held copper is resolved."""
    active = mixed_hold(edmc_plugin, monkeypatch, tmp_path, False)
    (tmp_path / "Cargo.json").unlink()
    journal(active, "CollectCargo", {"steel": 70, "copper": 10}, timestamp="2026-11-08T17:00:04Z",
            Type="steel", Count=10)
    inventory(active, 70, 20, 5)
    journal(active, "CollectCargo", {"steel": 70, "copper": 30}, timestamp="2026-11-08T17:00:04Z",
            Type="copper", Count=10)
    drain(active.plugin)
    inventory(active, 70, 20, 6)
    journal(active, "CollectCargo", {"steel": 90, "copper": 20}, timestamp="2026-11-08T17:00:01Z",
            Type="steel", Count=20)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 10, "copper": 0}


def test_a_purchase_absorbed_into_the_unfunded_balance_cannot_replay_as_a_separate_intent(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Collection4, deposit3, two buys2, and sale2 finish at carrier2 rather than debiting one buy twice."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"steel": 1}
    active.journal("Loadout", Ship="python", CargoCapacity=100, Modules=[])
    active.dock(True)
    inventory(active, 50, 0, 0)
    active.journal("MarketBuy", 53, timestamp="2026-11-08T17:00:02Z", MarketID=101, Type="steel", Count=2)
    write_market_cargo_file(active, monkeypatch, tmp_path, 55, timestamp="2026-11-08T17:00:03Z")
    active.journal("MarketBuy", 55, timestamp="2026-11-08T17:00:03Z", MarketID=101, Type="steel", Count=2)
    active.journal("CollectCargo", 59, timestamp="2026-11-08T17:00:01Z", Type="steel", Count=4)
    drain(active.plugin)
    write_market_cargo_file(active, monkeypatch, tmp_path, 53, timestamp="2026-11-08T17:00:04Z")
    active.journal("MarketSell", 53, timestamp="2026-11-08T17:00:04Z", MarketID=101, Type="steel", Count=2)
    inventory(active, 53, 0, 5)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 2}
    assert active.plugin.pending_carrier_deliveries.records() == []
