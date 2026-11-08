"""Retain complete physical intervals and journal intent while stock bounds are unavailable."""

import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from conftest import settle_commander_links
from test_carrier_cargo_parity import drain, session as _session_fixture
from test_mixed_inventory_attribution import inventory, journal


def full_cargo(active, cargo: dict[str, int], second: int) -> None:
    """Observe one complete main-ship hold at a fixed journal timestamp."""
    journal(active, "Cargo", cargo, timestamp=f"2026-11-08T17:00:0{second}Z", Vessel="Ship",
            Count=sum(cargo.values()), Inventory=[{"Name": key, "Count": count} for key, count in cargo.items()])


@pytest.fixture
def waiting_links(edmc_plugin, monkeypatch: pytest.MonkeyPatch):
    """Hold the profile HTTP boundary while actual journal events populate this commander's tracker."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"steel": 100, "drones": 0}
    profiles = active.plugin.api_client.get_all_cmdr_fcs
    entered, release = threading.Event(), threading.Event()

    def blocked(name: str) -> list:
        entered.set()
        assert release.wait(timeout=3)
        return profiles(name)

    def raw(event: str, cargo: dict[str, int], **fields) -> None:
        active.load.journal_entry("Alpha", False, "Sol", "101", {"event": event, **fields}, {
            "Docked": True, "StationType": "FleetCarrier", "MarketID": 101,
            "ShipType": "python", "Cargo": cargo,
        })

    monkeypatch.setattr(active.plugin.api_client, "get_all_cmdr_fcs", blocked)
    raw("Loadout", {"steel": 50, "drones": 20}, Ship="python", CargoCapacity=100, Modules=[])
    assert entered.wait(timeout=3)
    owner = active.plugin.fc_handler
    raw("Location", {"steel": 50, "drones": 20}, Docked=True, StationType="FleetCarrier", MarketID=101,
        StationServices=["squadronBank"])
    raw("Cargo", {"steel": 50, "drones": 20}, timestamp="2026-11-08T17:00:00Z", Vessel="Ship", Count=70,
        Inventory=[{"Name": "steel", "Count": 50}, {"Name": "drones", "Count": 20}])

    def finish() -> None:
        release.set()
        owner.initialization_thread.join(timeout=3)
        assert not owner.initialization_thread.is_alive()
        settle_commander_links(active.plugin)
        drain(active.plugin)

    try:
        yield SimpleNamespace(active=active, raw=raw, finish=finish)
    finally:
        release.set()
        owner.initialization_thread.join(timeout=3)


@pytest.mark.parametrize("event, key, count, second, cached, final_hold, expected", [
    ("BuyDrones", "drones", 1, 3, {"steel": 55, "drones": 21}, {"steel": 55, "drones": 21}, 95),
    ("CollectCargo", "steel", 5, 3, {"steel": 60, "drones": 20}, {"steel": 60, "drones": 20}, 95),
    ("CollectCargo", "steel", 5, 1, {"steel": 60, "drones": 20}, {"steel": 55, "drones": 20}, 100),
])
def test_known_ship_changes_preserve_a_complete_held_interval(
    waiting_links, event: str, key: str, count: int, second: int, cached: dict, final_hold: dict, expected: int,
) -> None:
    """Later ship changes stay separate; a delayed change already inside the point refines its bank movement."""
    active, raw = waiting_links.active, waiting_links.raw
    raw("MarketBuy", {"steel": 55, "drones": 20}, timestamp="2026-11-08T17:00:01Z",
        MarketID=101, Type="steel", Count=20)
    raw("Cargo", {"steel": 55, "drones": 20}, timestamp="2026-11-08T17:00:02Z", Vessel="Ship", Count=75,
        Inventory=[{"Name": "steel", "Count": 55}, {"Name": "drones", "Count": 20}])
    raw(event, cached, timestamp=f"2026-11-08T17:00:0{second}Z", Count=count, Type=key)
    waiting_links.finish()
    assert active.remote[101] == {"steel": expected, "drones": 0}
    full_cargo(active, final_hold, 4)
    drain(active.plugin)
    assert active.remote[101] == {"steel": expected, "drones": 0}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_omitted_partial_purchase_remains_recoverable_without_another_inventory(
    waiting_links, tmp_path: Path,
) -> None:
    """Buy20 is retained while links are unknown, then reported once when Raven100 can fund it."""
    active, raw = waiting_links.active, waiting_links.raw
    active.plugin.configure_pending_carrier_deliveries(str(tmp_path))
    raw("MarketBuy", {"steel": 55, "drones": 20}, timestamp="2026-11-08T17:00:01Z",
        MarketID=101, Type="steel", Count=20)
    restored = active.load.PendingCarrierDeliveries()
    restored.configure(str(tmp_path))
    frame, = restored.inventory_frames("Alpha", 101)
    waiting_links.finish()
    assert active.remote[101] == {"steel": 80, "drones": 0}
    assert frame["state"]["held_carrier_intents"] == [
        {"cargo": {"steel": -20}, "timestamp": "2026-11-08T17:00:01Z"},
    ]
    full_cargo(active, {"steel": 55, "drones": 20}, 2)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 95, "drones": 0}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_the_callback_capturing_a_held_interval_cannot_reduce_its_movement_twice(
    waiting_links, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A bank withdrawal10 followed by sale5 finishes at95, including the current fallback credit once."""
    active, raw = waiting_links.active, waiting_links.raw
    monkeypatch.setattr(active.load.config, "default_journal_dir", str(tmp_path), raising=False)
    (tmp_path / "Cargo.json").write_text(json.dumps({
        "event": "Cargo", "timestamp": "2026-11-08T17:00:01Z", "Vessel": "Ship", "Count": 75,
        "Inventory": [{"Name": "steel", "Count": 55}, {"Name": "drones", "Count": 20}],
    }))
    raw("MarketSell", {"steel": 55, "drones": 20}, timestamp="2026-11-08T17:00:01Z",
        MarketID=101, Type="steel", Count=5)
    waiting_links.finish()
    assert active.remote[101] == {"steel": 95, "drones": 0}
    full_cargo(active, {"steel": 55, "drones": 20}, 2)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 95, "drones": 0}


def test_unfunded_withdrawal_keeps_earlier_market_coverage(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A sale already credited before the held withdrawal cannot be sent again by the new hold."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"steel": 0, "copper": 100}
    active.journal("Loadout", Ship="python", CargoCapacity=100, Modules=[])
    journal(active, "Location", {"steel": 50, "copper": 10}, Docked=True, StationType="FleetCarrier",
            MarketID=101, StationServices=["squadronBank"])
    inventory(active, 40, 8, 2)
    drain(active.plugin)
    monkeypatch.setattr(active.load.config, "default_journal_dir", str(tmp_path), raising=False)
    (tmp_path / "Cargo.json").write_text(json.dumps({
        "event": "Cargo", "timestamp": "2026-11-08T17:00:03Z", "Vessel": "Ship", "Count": 66,
        "Inventory": [{"Name": "steel", "Count": 60}, {"Name": "copper", "Count": 6}],
    }))
    journal(active, "CargoTransfer", {"steel": 60, "copper": 6}, timestamp="2026-11-08T17:00:03Z", Transfers=[
        {"Type": "steel", "Count": 20, "Direction": "toship"},
        {"Type": "copper", "Count": 2, "Direction": "tocarrier"},
    ])
    journal(active, "MarketSell", {"steel": 50, "copper": 6}, timestamp="2026-11-08T17:00:01Z",
            MarketID=101, Type="steel", Count=10)
    inventory(active, 60, 6, 4)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 10, "copper": 104}


def test_old_opposing_ship_only_corrections_cannot_clamp_and_create_stock(edmc_plugin, monkeypatch) -> None:
    """SellDrones10 then BuyDrones10 already in an unchanged hold cannot create ten bank drones."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"steel": 0, "drones": 0}
    active.journal("Loadout", Ship="python", CargoCapacity=100, Modules=[])
    journal(active, "Location", {"steel": 50, "drones": 20}, Docked=True, StationType="FleetCarrier",
            MarketID=101, StationServices=["squadronBank"])
    full_cargo(active, {"steel": 40, "drones": 20}, 3)
    drain(active.plugin)
    journal(active, "EjectCargo", {"steel": 30, "drones": 20}, timestamp="2026-11-08T17:00:03Z",
            Type="steel", Count=10)
    journal(active, "SellDrones", {"steel": 40, "drones": 10}, timestamp="2026-11-08T17:00:01Z", Count=10)
    journal(active, "BuyDrones", {"steel": 40, "drones": 20}, timestamp="2026-11-08T17:00:02Z", Count=10)
    full_cargo(active, {"steel": 40, "drones": 20}, 4)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 0, "drones": 0}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
