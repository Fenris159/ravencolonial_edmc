"""Preserve known movements when speculative attribution reaches zero stock or changes interval."""

import pytest
from pathlib import Path

from test_carrier_cargo_parity import drain
from test_inventory_interval_ordering import prepare_session
from test_mixed_inventory_attribution import inventory, journal


@pytest.mark.parametrize("stock, first, second, event, count, bought, final_hold, drones, expected", [
    (0, 40, 35, "MarketSell", 10, 15, 50, False, 0),
    (0, 50, 45, "MarketBuy", 10, 5, 50, False, 0),
    (20, 60, 55, "MarketBuy", 10, 5, 60, True, 10),
])
def test_transient_reconciliation_does_not_create_stock_after_reaching_zero(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stock: int, first: int, second: int,
    event: str, count: int, bought: int, final_hold: int, drones: bool, expected: int,
) -> None:
    """A fresh physical snapshot cannot create stock from a clamped rollback or forgotten earlier credit."""
    active = prepare_session(edmc_plugin, monkeypatch, stock)
    active.dock(True)
    active.plugin.configure_pending_carrier_deliveries(str(tmp_path))

    def cargo(amount: int, stamp: int, has_drones: bool = False) -> None:
        contents = [{"Name": "steel", "Count": amount}]
        if has_drones:
            contents.append({"Name": "drones", "Count": 1})
        active.journal("Cargo", amount, timestamp=f"2026-11-08T17:00:0{stamp}Z", Vessel="Ship",
                       Count=amount + int(has_drones), Inventory=contents)

    cargo(first, 1)
    drain(active.plugin)
    if drones:
        active.journal("BuyDrones", first, timestamp="2026-11-08T17:00:02Z", Count=1)
    cargo(second, 2, drones)
    drain(active.plugin)
    active.journal(event, second, timestamp="2026-11-08T17:00:01Z", MarketID=101, Type="steel", Count=count)
    active.journal("MarketBuy", final_hold, timestamp="2026-11-08T17:00:02Z", MarketID=101,
                   Type="steel", Count=bought)
    drain(active.plugin)
    if not drones:
        assert active.remote[101] == {"steel": 0}
        restored = active.load.PendingCarrierDeliveries()
        restored.configure(str(tmp_path))
        frame, = restored.inventory_frames("Alpha", 101)
        assert frame["state"]["before"] == {"steel": second}
        assert frame["state"]["accounted"] == {"steel": bought}
        assert restored.records() == []
    else:
        # Retain the settled buy10; defer only the newer bank5 while reporting buy5.
        assert active.remote[101] == {"steel": 5}
    cargo(final_hold, 3, drones)
    drain(active.plugin)
    assert active.remote[101] == {"steel": expected}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
    assert active.plugin.pending_carrier_deliveries.records() == []


def test_unrelated_origin_sale_survives_a_steel_only_transient_frame(edmc_plugin, monkeypatch) -> None:
    """An unchanged copper balance is not deferred by restoring steel's older baseline."""
    active = prepare_session(edmc_plugin, monkeypatch, 75)
    active.remote[101]["copper"] = 100
    journal(active, "Location", {}, Docked=True, StationType="FleetCarrier", MarketID=101,
            StationServices=["squadronBank"])
    inventory(active, 50, 10, 1)
    inventory(active, 40, 10, 2)
    journal(active, "MarketSell", {"steel": 35, "copper": 10}, timestamp="2026-11-08T17:00:02Z",
            MarketID=101, Type="steel", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 80, "copper": 100}
    journal(active, "MarketSell", {"steel": 35, "copper": 8}, timestamp="2026-11-08T17:00:01Z",
            MarketID=101, Type="copper", Count=2)
    inventory(active, 35, 10, 3)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 90, "copper": 102}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
