"""Preserve accepted partial ship points alongside complete inventory freshness."""

from pathlib import Path

import pytest

from test_carrier_cargo_parity import drain
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
