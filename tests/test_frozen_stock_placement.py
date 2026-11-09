"""Keep same-second placement proofs tied to the frozen interval's actual carrier balance."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from test_carrier_cargo_parity import drain, session as _session_fixture, write_market_cargo_file
from test_held_inventory_attribution import full_cargo
from test_mixed_inventory_attribution import journal


def placement_session(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ship_drones: int, carrier_drones: int,
    *, unknown: bool = False,
) -> SimpleNamespace:
    """Establish a real ship point while preserving an optional queued carrier-baseline lookup."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"drones": carrier_drones, "steel": 0}
    monkeypatch.setattr(active.load.config, "default_journal_dir", str(tmp_path), raising=False)
    if unknown:
        monkeypatch.setattr(active.plugin.api_client, "get_all_cmdr_fcs", lambda name: [])
        monkeypatch.setattr(active.plugin.api_client, "get_commander_projects", lambda name: [
            {"linkedFC": [{"marketId": 101, "name": "101"}]},
        ])
    active.journal("Loadout", Ship="python", CargoCapacity=200, Modules=[])
    journal(active, "Location", {"drones": ship_drones, "steel": 10}, Docked=True, StationType="FleetCarrier",
            MarketID=101, StationServices=["squadronBank"])
    full_cargo(active, {"drones": ship_drones, "steel": 10}, 0)
    if not unknown:
        drain(active.plugin)
    return active


@pytest.mark.parametrize("capture", ["snapshot", "sale"])
def test_a_reported_sale_rebases_the_stock_used_to_place_a_frozen_ship_change(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capture: str,
) -> None:
    """Sale50 funds the provable withdrawal40, leaving Raven10 after the service purchase is accounted for."""
    active = placement_session(edmc_plugin, monkeypatch, tmp_path, 100, 0)
    if capture == "snapshot":
        full_cargo(active, {"drones": 120, "steel": 20}, 2)
    else:
        write_market_cargo_file(active, monkeypatch, tmp_path, 140,
                                timestamp="2026-11-08T17:00:02Z",
                                Inventory=[{"Name": "drones", "Count": 120}, {"Name": "steel", "Count": 20}])
    second = 1 if capture == "snapshot" else 2
    journal(active, "MarketSell", {"drones": 70, "steel": 20}, timestamp=f"2026-11-08T17:00:0{second}Z",
            MarketID=101, Type="drones", Count=50)
    if capture == "sale":
        (tmp_path / "Cargo.json").unlink()
    journal(active, "BuyDrones", {"drones": 100, "steel": 20}, timestamp="2026-11-08T17:00:02Z", Count=30)
    journal(active, "CollectCargo", {"drones": 120, "steel": 30}, timestamp="2026-11-08T17:00:01Z",
            Type="steel", Count=10)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 10, "steel": 0}
    full_cargo(active, {"drones": 120, "steel": 20}, 3)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 10, "steel": 0}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


@pytest.mark.parametrize("stock, unknown, expected, unresolved", [
    (10, False, 5, False), (0, False, 0, True), (10, True, 10, True),
])
def test_a_negative_ship_change_uses_the_only_placement_supported_by_the_stock_bound(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    stock: int, unknown: bool, expected: int, unresolved: bool,
) -> None:
    """Known10 proves the service sale is later; an empty or unknown bank cannot prove that placement."""
    active = placement_session(edmc_plugin, monkeypatch, tmp_path, 20, stock, unknown=unknown)
    full_cargo(active, {"drones": 25, "steel": 20}, 2)
    journal(active, "SellDrones", {"drones": 15, "steel": 20}, timestamp="2026-11-08T17:00:02Z", Count=10)
    journal(active, "CollectCargo", {"drones": 15, "steel": 30}, timestamp="2026-11-08T17:00:01Z",
            Type="steel", Count=10)
    drain(active.plugin)
    full_cargo(active, {"drones": 15, "steel": 20}, 3)
    drain(active.plugin)
    assert active.remote[101] == {"drones": expected, "steel": 0}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == (1 if unresolved else 0)


@pytest.mark.parametrize("repeat_point, refinement_after_ack", [(False, False), (True, False), (False, True)])
def test_an_older_callback_keeps_a_same_second_placement_unresolved_until_a_new_complete_hold(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, repeat_point: bool, refinement_after_ack: bool,
) -> None:
    """An older purchase revokes the apparent later-sale proof until a newer complete hold proves Raven5."""
    active = placement_session(edmc_plugin, monkeypatch, tmp_path, 20, 10)
    journal(active, "MarketSell", {"drones": 20, "steel": 9}, timestamp="2026-11-08T17:00:01Z",
            MarketID=101, Type="steel", Count=1)
    full_cargo(active, {"drones": 25, "steel": 19}, 3)
    journal(active, "SellDrones", {"drones": 15, "steel": 19}, timestamp="2026-11-08T17:00:03Z", Count=10)
    if not refinement_after_ack:
        journal(active, "BuyDrones", {"drones": 25, "steel": 19}, timestamp="2026-11-08T17:00:02Z", Count=10)
    journal(active, "CollectCargo", {"drones": 15 if refinement_after_ack else 25, "steel": 29},
            timestamp="2026-11-08T17:00:02Z",
            Type="steel", Count=10)
    if repeat_point:
        full_cargo(active, {"drones": 25, "steel": 19}, 3)
    drain(active.plugin)
    if refinement_after_ack:
        journal(active, "BuyDrones", {"drones": 25, "steel": 19}, timestamp="2026-11-08T17:00:02Z", Count=10)
        drain(active.plugin)
    assert active.remote[101] == {"drones": 10, "steel": 1}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1
    full_cargo(active, {"drones": 25, "steel": 19}, 4)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 5, "steel": 1}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
