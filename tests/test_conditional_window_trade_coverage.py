"""Keep partial trades and service changes behind the accepted repair's retained physical window."""

from pathlib import Path

import pytest

from test_carrier_cargo_parity import drain
from test_frozen_stock_placement import placement_session
from test_held_inventory_attribution import full_cargo
from test_mixed_inventory_attribution import journal


@pytest.mark.parametrize("event, partial, final_hold, expected", [
    ("MarketBuy", 125, 120, 10), ("MarketBuy", 125, 125, 5),
    ("MarketSell", 115, 120, 10), ("MarketSell", 115, 115, 15),
    ("BuyDrones", 125, 120, 15), ("BuyDrones", 125, 125, 10),
    ("SellDrones", 115, 120, 5), ("SellDrones", 115, 115, 10),
])
def test_a_partial_change_waits_for_fresh_inventory_to_prove_whether_the_repair_already_covers_it(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    event: str, partial: int, final_hold: int, expected: int,
) -> None:
    """Keep Raven10 and validated ship120 until full inventory separates covered and genuinely new changes."""
    active = placement_session(edmc_plugin, monkeypatch, tmp_path, 100, 0)
    full_cargo(active, {"drones": 120, "steel": 20}, 2)
    journal(active, "MarketSell", {"drones": 70, "steel": 20}, timestamp="2026-11-08T17:00:01Z",
            MarketID=101, Type="drones", Count=50)
    journal(active, "BuyDrones", {"drones": 100, "steel": 20}, timestamp="2026-11-08T17:00:02Z", Count=30)
    journal(active, "CollectCargo", {"drones": 120, "steel": 30}, timestamp="2026-11-08T17:00:01Z",
            Type="steel", Count=10)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 10, "steel": 0}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1

    fields = {"MarketID": 101, "Type": "drones"} if event in {"MarketBuy", "MarketSell"} else {}
    journal(active, event, {"drones": partial, "steel": 20}, timestamp="2026-11-08T17:00:02Z", Count=5, **fields)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 10, "steel": 0}
    assert active.ship == {"drones": 120, "steel": 20}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1

    full_cargo(active, {"drones": final_hold, "steel": 20}, 3)
    drain(active.plugin)
    assert active.remote[101] == {"drones": expected, "steel": 0}
    assert active.ship == {"drones": final_hold, "steel": 20}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
