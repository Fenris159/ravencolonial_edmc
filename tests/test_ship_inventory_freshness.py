"""Preserve accepted partial ship points alongside complete inventory freshness."""

from pathlib import Path

import pytest

from test_carrier_cargo_parity import drain, write_market_cargo_file
from carrier_test_support import placement_session
from carrier_test_support import full_cargo
from carrier_test_support import journal


@pytest.mark.parametrize("second, partial, expected_ship", [(2, 65, 55), (3, 60, 60)])
def test_an_accepted_partial_point_guards_its_second_without_blocking_a_later_trade(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, second: int, partial: int, expected_ship: int,
) -> None:
    """Two purchases of five leave carrier65; only a newer partial timestamp may advance ship55 to60."""
    active = placement_session(edmc_plugin, monkeypatch, tmp_path, 50, 75)
    journal(active, "MarketBuy", {"drones": 55, "steel": 10}, timestamp="2026-11-08T17:00:02Z",
            MarketID=101, Type="drones", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 70, "steel": 0}
    assert active.ship == {"drones": 55, "steel": 10}

    journal(active, "MarketBuy", {"drones": partial, "steel": 10}, timestamp=f"2026-11-08T17:00:0{second}Z",
            MarketID=101, Type="drones", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 65, "steel": 0}
    assert active.ship == {"drones": expected_ship, "steel": 10}
    full_cargo(active, {"drones": 60, "steel": 10}, second + 1)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 65, "steel": 0}
    assert active.ship == {"drones": 60, "steel": 10}


def test_an_older_matching_file_cannot_replace_a_newer_validated_held_inventory(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Record an old sale once without publishing its older file or retiring the newer held point."""
    active = placement_session(edmc_plugin, monkeypatch, tmp_path, 20, 10)
    full_cargo(active, {"drones": 25, "steel": 20}, 3)
    write_market_cargo_file(active, monkeypatch, tmp_path, 25, timestamp="2026-11-08T17:00:02Z",
                            Inventory=[{"Name": "drones", "Count": 15}, {"Name": "steel", "Count": 10}])
    journal(active, "MarketSell", {"drones": 15, "steel": 10}, timestamp="2026-11-08T17:00:02Z",
            MarketID=101, Type="drones", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 15, "steel": 0}
    assert active.ship == {"drones": 25, "steel": 20}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1

    (tmp_path / "Cargo.json").unlink()
    journal(active, "CollectCargo", {"drones": 25, "steel": 30}, timestamp="2026-11-08T17:00:02Z",
            Type="steel", Count=10)
    full_cargo(active, {"drones": 25, "steel": 20}, 4)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 5, "steel": 0}
    assert active.ship == {"drones": 25, "steel": 20}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
