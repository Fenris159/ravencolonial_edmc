"""Preserve signed obligations while replacing a held physical observation."""

import pytest

from test_carrier_cargo_parity import drain, session as _session_fixture
from test_held_inventory_attribution import full_cargo
from test_mixed_inventory_attribution import journal


@pytest.mark.parametrize("new_steel, placement, expected", [
    (20, "before", {"drones": 10, "steel": 0}), (10, "before", {"drones": 10, "steel": 10}),
    (20, "after", {"drones": 10, "steel": 0}),
])
def test_unissued_compensation_survives_both_rejected_and_accepted_new_inventories(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, new_steel: int, placement: str, expected: dict,
) -> None:
    """Replacing the observation cannot forget the twenty-tonne reversal already owed to Raven."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"drones": 0, "steel": 0}
    active.journal("Loadout", Ship="python", CargoCapacity=100, Modules=[])
    journal(active, "Location", {"drones": 20, "steel": 10}, Docked=True, StationType="FleetCarrier",
            MarketID=101, StationServices=["squadronBank"])
    full_cargo(active, {"drones": 10, "steel": 10}, 2)
    drain(active.plugin)
    full_cargo(active, {"drones": 30, "steel": 20}, 3)
    journal(active, "CollectCargo", {"drones": 50, "steel": 20}, timestamp="2026-11-08T17:00:01Z",
            Type="drones", Count=20)
    if placement == "before":
        journal(active, "BuyDrones", {"drones": 80, "steel": 20}, timestamp="2026-11-08T17:00:03Z", Count=30)
        full_cargo(active, {"drones": 60, "steel": new_steel}, 4)
    else:
        full_cargo(active, {"drones": 30, "steel": new_steel}, 4)
        journal(active, "BuyDrones", {"drones": 60, "steel": new_steel}, timestamp="2026-11-08T17:00:04Z", Count=30)
    journal(active, "CollectCargo", {"drones": 60, "steel": new_steel + 10}, timestamp="2026-11-08T17:00:02Z",
            Type="steel", Count=10)
    drain(active.plugin)
    assert active.remote[101] == expected
    full_cargo(active, {"drones": 60, "steel": new_steel}, 5)
    drain(active.plugin)
    assert active.remote[101] == expected


@pytest.mark.parametrize("second, expected", [
    (2, {"drones": 50, "steel": 10}), (3, {"drones": 55, "steel": 10}),
])
def test_only_a_strictly_newer_complete_inventory_retires_pending_placement(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, second: int, expected: dict,
) -> None:
    """A newer point consumes the known purchase; another point in its second cannot prove placement."""
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
    full_cargo(active, {"drones": 35, "steel": 20}, second)
    drain(active.plugin)
    assert active.remote[101] == expected
    full_cargo(active, {"drones": 35, "steel": 20}, 4)
    drain(active.plugin)
    assert active.remote[101] == expected
