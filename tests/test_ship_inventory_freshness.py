"""Preserve accepted partial ship points alongside complete inventory freshness."""

from pathlib import Path

import pytest

from test_carrier_cargo_parity import drain, write_market_cargo_file
from test_frozen_stock_placement import placement_session
from test_held_inventory_attribution import full_cargo
from test_mixed_inventory_attribution import journal


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


@pytest.mark.parametrize("offsetting_purchase, matching_file", [(False, False), (True, False), (False, True)])
def test_a_delayed_complete_point_sale_stays_covered_after_a_newer_partial_purchase(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, offsetting_purchase: bool, matching_file: bool,
) -> None:
    """Cargo already counted the sale; a newer purchase cannot make its late callback add five again."""
    active = placement_session(edmc_plugin, monkeypatch, tmp_path, 55, 75)
    full_cargo(active, {"drones": 50, "steel": 10}, 2)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 80, "steel": 0}
    journal(active, "MarketBuy", {"drones": 55, "steel": 10}, timestamp="2026-11-08T17:00:03Z",
            MarketID=101, Type="drones", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 75, "steel": 0}
    assert active.ship == {"drones": 55, "steel": 10}

    if matching_file:
        write_market_cargo_file(active, monkeypatch, tmp_path, 60, timestamp="2026-11-08T17:00:02Z",
                                Inventory=[{"Name": "drones", "Count": 50}, {"Name": "steel", "Count": 10}])
    journal(active, "MarketSell", {"drones": 55, "steel": 10}, timestamp="2026-11-08T17:00:02Z",
            MarketID=101, Type="drones", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 75, "steel": 0}
    assert active.ship == {"drones": 55, "steel": 10}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
    (tmp_path / "Cargo.json").unlink(missing_ok=True)
    if offsetting_purchase:
        journal(active, "MarketBuy", {"drones": 55, "steel": 10}, timestamp="2026-11-08T17:00:02Z",
                MarketID=101, Type="drones", Count=5)
    full_cargo(active, {"drones": 55, "steel": 10}, 4)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 75, "steel": 0}
    assert active.ship == {"drones": 55, "steel": 10}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


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


@pytest.mark.parametrize("old_service_state", [55, 60])
def test_a_delayed_ship_only_change_stays_accounted_when_a_later_same_second_trade_rolls_back(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, old_service_state: int,
) -> None:
    """Refine the accepted hold instead of losing the service purchase in an older rollback anchor."""
    active = placement_session(edmc_plugin, monkeypatch, tmp_path, 55, 75)
    full_cargo(active, {"drones": 50, "steel": 10}, 2)
    drain(active.plugin)
    journal(active, "MarketBuy", {"drones": 55, "steel": 10}, timestamp="2026-11-08T17:00:03Z",
            MarketID=101, Type="drones", Count=5)
    drain(active.plugin)
    journal(active, "MarketSell", {"drones": 55, "steel": 10}, timestamp="2026-11-08T17:00:02Z",
            MarketID=101, Type="drones", Count=10)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 75, "steel": 0}
    journal(active, "BuyDrones", {"drones": old_service_state, "steel": 10},
            timestamp="2026-11-08T17:00:02Z", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 80, "steel": 0}
    assert active.ship == {"drones": 55, "steel": 10}
    journal(active, "MarketBuy", {"drones": 60, "steel": 10}, timestamp="2026-11-08T17:00:03Z",
            MarketID=101, Type="drones", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 75, "steel": 0}
    full_cargo(active, {"drones": 60, "steel": 10}, 4)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 75, "steel": 0}
    assert active.ship == {"drones": 60, "steel": 10}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
