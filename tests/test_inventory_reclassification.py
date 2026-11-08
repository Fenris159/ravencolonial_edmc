"""Protect per-commodity coverage and stock bounds when delayed callbacks refine inventory."""

import json
from pathlib import Path
import threading

import pytest

from conftest import settle_commander_links
from test_carrier_cargo_parity import drain, session as _session_fixture, write_market_cargo_file
from test_inventory_interval_ordering import prepare_session
from test_mixed_inventory_attribution import inventory, journal


@pytest.mark.parametrize("project_only, retired, complete", [
    (False, False, False), (True, False, False), (False, True, False), (False, False, True),
])
def test_unknown_stock_partial_trade_cannot_release_clamped_debit_and_compensation(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    project_only: bool, retired: bool, complete: bool,
) -> None:
    """Deposit15 plus buy20 against Raven10 must finish at5 when commander links become available."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"steel": 10}
    entered, release = threading.Event(), threading.Event()

    def profiles(name: str) -> list:
        entered.set()
        assert release.wait(timeout=3)
        return [] if project_only else [{"marketId": 101, "name": "101", "cargo": {"steel": 10}}]

    def raw(event: str, amount: int, **fields) -> None:
        active.load.journal_entry("Alpha", False, "Sol", "101", {"event": event, **fields}, {
            "Docked": True, "StationType": "FleetCarrier", "MarketID": 101,
            "ShipType": "python", "Cargo": {"steel": amount},
        })

    monkeypatch.setattr(active.plugin.api_client, "get_all_cmdr_fcs", profiles)
    if project_only:
        monkeypatch.setattr(active.plugin.api_client, "get_commander_projects", lambda name: [
            {"linkedFC": [{"marketId": 101, "name": "101"}]},
        ])
    try:
        raw("Loadout", 50, Ship="python", CargoCapacity=100, Modules=[])
        assert entered.wait(timeout=3)
        raw("Location", 50, Docked=True, StationType="FleetCarrier", MarketID=101,
            StationServices=["squadronBank"])
        raw("Cargo", 50, timestamp="2026-11-08T17:00:00Z", Vessel="Ship", Count=50,
            Inventory=[{"Name": "steel", "Count": 50}])
        if complete:
            write_market_cargo_file(active, monkeypatch, tmp_path, 55, timestamp="2026-11-08T17:00:01Z")
        raw("MarketBuy", 55, timestamp="2026-11-08T17:00:01Z", MarketID=101, Type="steel", Count=20)
        raw("Cargo", 55, timestamp="2026-11-08T17:00:02Z", Vessel="Ship", Count=55,
            Inventory=[{"Name": "steel", "Count": 55}])
        if retired:
            active.load.journal_entry("Bravo", False, "Sol", "", {"event": "LoadGame"}, {})
    finally:
        release.set()
    settle_commander_links(active.plugin)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 5}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_ship_only_reclassification_cannot_create_stock_after_a_purchase_spends_its_credit(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Deposit10, buy10, then eject10 leaves no bank stock, even with delayed ship-only attribution."""
    active = prepare_session(edmc_plugin, monkeypatch, 0)
    active.dock(True)
    inventory(active, 40, 0, 1)
    drain(active.plugin)
    write_market_cargo_file(active, monkeypatch, tmp_path, 50, timestamp="2026-11-08T17:00:01Z")
    journal(active, "MarketBuy", {"steel": 50}, timestamp="2026-11-08T17:00:01Z",
            MarketID=101, Type="steel", Count=10)
    drain(active.plugin)
    write_market_cargo_file(active, monkeypatch, tmp_path, 40, timestamp="2026-11-08T17:00:02Z")
    journal(active, "EjectCargo", {"steel": 40}, timestamp="2026-11-08T17:00:01Z", Type="steel", Count=10)
    inventory(active, 40, 0, 2)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 0}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


@pytest.mark.parametrize("credit, steel, expected", [("active", 40, 85), ("retired", 40, 85), ("zero", 50, 75)])
def test_reclassifying_one_commodity_retains_other_commodities_inventory_coverage(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, credit: str, steel: int, expected: int,
) -> None:
    """Removing ten ship-only drones cannot count the already observed steel sale twice."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"steel": 75, "drones": 0}
    active.journal("Loadout", Ship="python", CargoCapacity=100, Modules=[])
    journal(active, "Location", {"steel": 50, "drones": 20}, Docked=True, StationType="FleetCarrier",
            MarketID=101, StationServices=["squadronBank"])
    if credit == "retired":
        journal(active, "Cargo", {"steel": 40, "drones": 20}, timestamp="2026-11-08T17:00:01Z",
                Vessel="Ship", Count=60, Inventory=[{"Name": "steel", "Count": 40}, {"Name": "drones", "Count": 20}])
    journal(active, "Cargo", {"steel": steel, "drones": 10}, timestamp="2026-11-08T17:00:02Z",
            Vessel="Ship", Count=steel + 10,
            Inventory=[{"Name": "steel", "Count": steel}, {"Name": "drones", "Count": 10}])
    drain(active.plugin)
    journal(active, "SellDrones", {"steel": steel}, timestamp="2026-11-08T17:00:02Z", Count=10)
    journal(active, "MarketSell", {"steel": steel - 10, "drones": 10}, timestamp="2026-11-08T17:00:01Z",
            MarketID=101, Type="steel", Count=10)
    journal(active, "Cargo", {"steel": steel, "drones": 10}, timestamp="2026-11-08T17:00:03Z",
            Vessel="Ship", Count=steel + 10,
            Inventory=[{"Name": "steel", "Count": steel}, {"Name": "drones", "Count": 10}])
    drain(active.plugin)
    assert active.remote[101] == {"steel": expected, "drones": 0}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


@pytest.mark.parametrize("stock, hold, second, follow, count, expected", [
    (100, 8, 1, None, 0, 102), (100, 4, 2, "MarketSell", 2, 106), (0, 20, 1, "CollectCargo", 14, 4),
])
def test_complete_mixed_transfer_holds_only_the_unfunded_component(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    stock: int, hold: int, second: int, follow: str, count: int, expected: int,
) -> None:
    """A held steel withdrawal cannot replay the copper deposit already credited by inventory."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"steel": 0, "copper": stock}
    active.journal("Loadout", Ship="python", CargoCapacity=100, Modules=[])
    journal(active, "Location", {"steel": 50, "copper": 10}, Docked=True, StationType="FleetCarrier",
            MarketID=101, StationServices=["squadronBank"])
    inventory(active, 50, 10, 0)
    inventory(active, 40, 8, 1)
    drain(active.plugin)
    monkeypatch.setattr(active.load.config, "default_journal_dir", str(tmp_path), raising=False)
    (tmp_path / "Cargo.json").write_text(json.dumps({
        "event": "Cargo", "timestamp": f"2026-11-08T17:00:0{second}Z", "Vessel": "Ship", "Count": 60 + hold,
        "Inventory": [{"Name": "steel", "Count": 60}, {"Name": "copper", "Count": hold}],
    }))
    journal(active, "CargoTransfer", {"steel": 60, "copper": hold},
            timestamp=f"2026-11-08T17:00:0{second}Z", Transfers=[
        {"Type": "steel", "Count": 20, "Direction": "toship"},
        {"Type": "copper", "Count": 2, "Direction": "tocarrier"},
    ])
    if follow:
        (tmp_path / "Cargo.json").unlink()
        journal(active, follow, {"steel": 60, "copper": 2 if follow == "MarketSell" else 34},
                timestamp=f"2026-11-08T17:00:0{second}Z", MarketID=101, Type="copper", Count=count)
    inventory(active, 60, hold, 3)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 10, "copper": expected}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames("Alpha", 101)) == 1
    handler = active.plugin.fc_handler
    identity = handler.prepare_manual_manifest(101, {"steel": 0, "copper": expected})
    assert handler.save_manual_manifest(101, {"steel": 0, "copper": expected}, identity) == {"copper": expected}
    handler.finish_manual_manifest(identity)
    inventory(active, 60, hold, 4)
    drain(active.plugin)
    assert active.remote[101] == {"copper": expected}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
