"""Shared journal and HTTP fixture adapters for carrier behavior tests."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from conftest import settle_commander_links
from test_carrier_cargo_parity import drain, session as _session_fixture


def journal(active, event, cargo, **fields) -> None:
    """Deliver a journal callback with EDMC's matching physical-ship context."""
    active.load.journal_entry("Alpha", False, "Sol", "101", {"event": event, **fields}, {
        "Docked": True, "StationType": "FleetCarrier", "MarketID": 101,
        "ShipType": "python", "Cargo": cargo,
    })
    settle_commander_links(active.plugin)


def inventory(active, steel, copper, second) -> None:
    """Deliver a complete two-commodity main-ship inventory."""
    journal(active, "Cargo", {"steel": steel, "copper": copper},
            timestamp=f"2026-11-08T17:00:0{second}Z", Vessel="Ship", Count=steel + copper,
            Inventory=[{"Name": "steel", "Count": steel}, {"Name": "copper", "Count": copper}])


def full_cargo(active, cargo: dict[str, int], second: int) -> None:
    """Observe one complete main-ship hold at a fixed journal timestamp."""
    journal(active, "Cargo", cargo, timestamp=f"2026-11-08T17:00:0{second}Z", Vessel="Ship",
            Count=sum(cargo.values()), Inventory=[{"Name": key, "Count": count} for key, count in cargo.items()])


def placement_session(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, ship_drones: int, carrier_drones: int,
    *, unknown: bool = False, ship_steel: int = 10,
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
    journal(active, "Location", {"drones": ship_drones, "steel": ship_steel}, Docked=True, StationType="FleetCarrier",
            MarketID=101, StationServices=["squadronBank"])
    full_cargo(active, {"drones": ship_drones, "steel": ship_steel}, 0)
    if not unknown:
        drain(active.plugin)
    return active
