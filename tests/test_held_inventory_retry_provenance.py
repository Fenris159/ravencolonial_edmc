"""Keep affordable retries within the physical evidence that still owns them."""

from pathlib import Path

import pytest

from test_carrier_cargo_parity import drain, session as _session_fixture, write_market_cargo_file
from test_held_inventory_attribution import full_cargo
from test_inventory_acceptance_ownership import game_file
from test_mixed_inventory_attribution import inventory, journal


@pytest.mark.parametrize("owner", ["unfunded", "released", "ordinary"])
def test_a_later_same_second_limpet_purchase_cannot_credit_an_older_held_inventory(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, owner: str,
) -> None:
    """The later service purchase cannot invent bank stock or need a compensating clamped withdrawal."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"drones": 0, "steel": 0}
    active.journal("Loadout", Ship="python", CargoCapacity=100, Modules=[])
    journal(active, "Location", {"drones": 20, "steel": 10}, Docked=True, StationType="FleetCarrier",
            MarketID=101, StationServices=["squadronBank"])
    full_cargo(active, {"drones": 10, "steel": 10}, 2)
    if owner != "ordinary":
        write_market_cargo_file(active, monkeypatch, tmp_path, 40, timestamp="2026-11-08T17:00:03Z",
                                Inventory=[{"Name": "drones", "Count": 30}, {"Name": "steel", "Count": 10}])
        journal(active, "CargoTransfer", {"drones": 30, "steel": 10}, timestamp="2026-11-08T17:00:03Z",
                Transfers=[{"Type": "drones", "Count": 20, "Direction": "toship"}])
    full_cargo(active, {"drones": 30, "steel": 20}, 3)
    if owner != "ordinary":
        (tmp_path / "Cargo.json").unlink()
    if owner != "unfunded":
        journal(active, "CollectCargo", {"drones": 50, "steel": 20}, timestamp="2026-11-08T17:00:01Z",
                Type="drones", Count=20)
    observed_drones = 60 if owner == "unfunded" else 80
    journal(active, "BuyDrones", {"drones": observed_drones, "steel": 20},
            timestamp="2026-11-08T17:00:03Z", Count=30)
    journal(active, "CollectCargo", {"drones": observed_drones, "steel": 30}, timestamp="2026-11-08T17:00:02Z",
            Type="steel", Count=10)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 10, "steel": 0}
    full_cargo(active, {"drones": 60, "steel": 20}, 4)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 10, "steel": 0}


def test_an_origin_revocation_keeps_a_quantitative_remainder_out_of_automatic_retry(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Affordability cannot turn uncertain steel attribution into a permanent five-tonne credit."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"steel": 0, "copper": 0}
    active.journal("Loadout", Ship="python", CargoCapacity=100, Modules=[])
    journal(active, "Location", {}, Docked=True, StationType="FleetCarrier", MarketID=101,
            StationServices=["squadronBank"])
    inventory(active, 50, 10, 0)
    inventory(active, 40, 10, 2)
    game_file(active, monkeypatch, tmp_path, 60, 10, 3)
    journal(active, "CargoTransfer", {"steel": 60, "copper": 10}, timestamp="2026-11-08T17:00:03Z",
            Transfers=[{"Type": "steel", "Count": 20, "Direction": "toship"}])
    inventory(active, 35, 20, 5)
    (tmp_path / "Cargo.json").unlink()
    journal(active, "MarketSell", {"steel": 25, "copper": 20}, timestamp="2026-11-08T17:00:00Z",
            MarketID=101, Type="steel", Count=10)
    journal(active, "CollectCargo", {"steel": 35, "copper": 30}, timestamp="2026-11-08T17:00:04Z",
            Type="copper", Count=10)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 10, "copper": 0}
    inventory(active, 35, 20, 6)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 10, "copper": 0}


def test_a_fundable_zero_sum_cannot_prove_same_second_placement(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When both placements are possible, retain a recovery barrier for a verified carrier correction."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"drones": 50, "steel": 0}
    active.journal("Loadout", Ship="python", CargoCapacity=100, Modules=[])
    journal(active, "Location", {"drones": 20, "steel": 10}, Docked=True, StationType="FleetCarrier",
            MarketID=101, StationServices=["squadronBank"])
    full_cargo(active, {"drones": 10, "steel": 10}, 1)
    full_cargo(active, {"drones": 30, "steel": 20}, 2)
    journal(active, "BuyDrones", {"drones": 50, "steel": 20}, timestamp="2026-11-08T17:00:02Z", Count=20)
    journal(active, "CollectCargo", {"drones": 50, "steel": 30}, timestamp="2026-11-08T17:00:01Z",
            Type="steel", Count=10)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 60, "steel": 0}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1
    full_cargo(active, {"drones": 50, "steel": 20}, 3)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 60, "steel": 0}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1
