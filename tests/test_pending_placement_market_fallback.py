"""Keep partial market state from retiring an unresolved complete-inventory placement window."""

import pytest

from test_carrier_cargo_parity import drain, session as _session_fixture
from test_held_inventory_attribution import full_cargo
from test_mixed_inventory_attribution import journal


def test_partial_market_state_retains_the_last_validated_hold_until_a_newer_complete_inventory(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish the known sale25, retain ship35, then reconcile the held withdrawal20 exactly once."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"drones": 50, "steel": 20}
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
    journal(active, "MarketSell", {"drones": 10, "steel": 20}, timestamp="2026-11-08T17:00:03Z",
            MarketID=101, Type="drones", Count=25)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 75, "steel": 20}
    assert active.ship == {"drones": 35, "steel": 20}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1
    full_cargo(active, {"drones": 35, "steel": 20}, 3)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 75, "steel": 20}
    assert active.ship == {"drones": 35, "steel": 20}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1
    full_cargo(active, {"drones": 35, "steel": 20}, 4)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 55, "steel": 20}
    assert active.ship == {"drones": 35, "steel": 20}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
