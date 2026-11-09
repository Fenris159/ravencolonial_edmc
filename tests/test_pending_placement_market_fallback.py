"""Keep partial market state from retiring an unresolved complete-inventory placement window."""

import pytest

from test_carrier_cargo_parity import drain, session as _session_fixture, write_market_cargo_file
from test_held_inventory_attribution import full_cargo
from test_frozen_stock_placement import placement_session
from test_mixed_inventory_attribution import journal


def acknowledge_next_carrier_write(active) -> None:
    """Execute queued HTTP work through the next carrier response, leaving later writes queued."""
    before = len(active.writes)
    while len(active.writes) == before:
        function, args, kwargs = active.plugin.api_queue.get_nowait()
        function(*args, **kwargs)
        active.plugin.api_queue.task_done()


@pytest.mark.parametrize("event, initial, partial_hold, immediate, final", [
    ("MarketSell", 50, 10, 75, 55), ("MarketBuy", 10, 60, 10, 15),
])
def test_partial_market_state_retains_the_last_validated_hold_until_a_newer_complete_inventory(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, event: str, initial: int,
    partial_hold: int, immediate: int, final: int,
) -> None:
    """Retain ship35, fund known trades safely, and reconcile the complete physical interval exactly once."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"drones": initial, "steel": 20}
    monkeypatch.setattr(active.plugin.api_client, "get_all_cmdr_fcs", lambda name: [])
    monkeypatch.setattr(active.plugin.api_client, "get_commander_projects", lambda name: [
        {"linkedFC": [{"marketId": 101, "name": "101"}]},
    ])
    active.journal("Loadout", Ship="python", CargoCapacity=100, Modules=[])
    journal(active, "Location", {"drones": 20, "steel": 10}, Docked=True, StationType="FleetCarrier",
            MarketID=101, StationServices=["squadronBank"])
    full_cargo(active, {"drones": 20, "steel": 10}, 0)
    full_cargo(active, {"drones": 40, "steel": 20}, 2)
    journal(active, "BuyDrones", {"drones": 60, "steel": 20}, timestamp="2026-11-08T17:00:02Z", Count=20)
    full_cargo(active, {"drones": 35, "steel": 20}, 2)
    journal(active, "CollectCargo", {"drones": 35, "steel": 30}, timestamp="2026-11-08T17:00:01Z",
            Type="steel", Count=10)
    journal(active, event, {"drones": partial_hold, "steel": 20}, timestamp="2026-11-08T17:00:03Z",
            MarketID=101, Type="drones", Count=25)
    drain(active.plugin)
    assert active.remote[101] == {"drones": immediate, "steel": 20}
    assert active.ship == {"drones": 35, "steel": 20}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1
    full_cargo(active, {"drones": 35, "steel": 20}, 3)
    drain(active.plugin)
    assert active.remote[101] == {"drones": immediate, "steel": 20}
    assert active.ship == {"drones": 35, "steel": 20}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1
    full_cargo(active, {"drones": 35, "steel": 20}, 4)
    drain(active.plugin)
    assert active.remote[101] == {"drones": final, "steel": 20}
    assert active.ship == {"drones": 35, "steel": 20}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


@pytest.mark.parametrize("complete", [False, True])
def test_a_deferred_purchase_reserves_withdrawals_queued_before_an_unrelated_acknowledgement(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path, complete: bool,
) -> None:
    """Reserve the first twenty so the second purchase waits, preserving bank15 instead of clamping to zero."""
    active = placement_session(edmc_plugin, monkeypatch, tmp_path, 20, 30, ship_steel=1)
    journal(active, "MarketSell", {"drones": 20}, timestamp="2026-11-08T17:00:01Z",
            MarketID=101, Type="steel", Count=1)
    journal(active, "MarketBuy", {"drones": 40}, timestamp="2026-11-08T17:00:02Z",
            MarketID=101, Type="drones", Count=20)
    full_cargo(active, {"drones": 60}, 3)
    journal(active, "BuyDrones", {"drones": 80}, timestamp="2026-11-08T17:00:03Z", Count=20)
    full_cargo(active, {"drones": 55}, 3)
    # Execute the first carrier response while the drone withdrawal remains queued.
    acknowledge_next_carrier_write(active)
    assert active.remote[101] == {"drones": 30, "steel": 1}

    second = 3 if complete else 4
    if complete:
        write_market_cargo_file(active, monkeypatch, tmp_path, 55, timestamp="2026-11-08T17:00:03Z",
                                Inventory=[{"Name": "drones", "Count": 55}])
    journal(active, "MarketBuy", {"drones": 55}, timestamp=f"2026-11-08T17:00:0{second}Z",
            MarketID=101, Type="drones", Count=25)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 10, "steel": 1}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1
    full_cargo(active, {"drones": 55}, 5)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 15, "steel": 1}
    assert active.ship == {"drones": 55}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


@pytest.mark.parametrize("observation", ["cargo", "complete_purchase", "partial_purchase"])
def test_every_new_withdrawal_reserves_already_queued_purchases(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path, observation: str,
) -> None:
    """Hold an unaffordable twenty until known collection explains it, preserving carrier10 throughout."""
    active = placement_session(edmc_plugin, monkeypatch, tmp_path, 20, 30, ship_steel=1)
    journal(active, "MarketSell", {"drones": 20}, timestamp="2026-11-08T17:00:01Z",
            MarketID=101, Type="steel", Count=1)
    journal(active, "MarketBuy", {"drones": 40}, timestamp="2026-11-08T17:00:02Z",
            MarketID=101, Type="drones", Count=20)
    acknowledge_next_carrier_write(active)
    assert active.remote[101] == {"drones": 30, "steel": 1}
    if observation == "cargo":
        full_cargo(active, {"drones": 60}, 3)
    else:
        if observation == "complete_purchase":
            write_market_cargo_file(active, monkeypatch, tmp_path, 60, timestamp="2026-11-08T17:00:03Z",
                                    Inventory=[{"Name": "drones", "Count": 60}])
        journal(active, "MarketBuy", {"drones": 60}, timestamp="2026-11-08T17:00:03Z",
                MarketID=101, Type="drones", Count=20)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 10, "steel": 1}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1

    (tmp_path / "Cargo.json").unlink(missing_ok=True)
    journal(active, "CollectCargo", {"drones": 80}, timestamp="2026-11-08T17:00:02Z", Type="drones", Count=20)
    full_cargo(active, {"drones": 60}, 4)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 10, "steel": 1}
    assert active.ship == {"drones": 60}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
