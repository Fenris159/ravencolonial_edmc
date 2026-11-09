"""Keep partial market state from retiring an unresolved complete-inventory placement window."""

import pytest

from test_carrier_cargo_parity import drain, session as _session_fixture
from test_held_inventory_attribution import full_cargo
from test_mixed_inventory_attribution import journal


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
