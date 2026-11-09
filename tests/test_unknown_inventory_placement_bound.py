"""Keep metadata-only carrier manifests distinct from a known empty physical inventory."""

import json
from pathlib import Path

import pytest

from test_carrier_cargo_parity import drain, session as _session_fixture
from test_held_inventory_attribution import full_cargo
from test_mixed_inventory_attribution import journal


@pytest.mark.parametrize("capture", ["cargo", "journal"])
def test_an_unknown_project_baseline_cannot_prove_a_same_second_change_was_already_in_the_hold(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capture: str,
) -> None:
    """A pending baseline must retain placement uncertainty instead of later debiting Raven60 to40."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"drones": 50, "steel": 0}
    monkeypatch.setattr(active.plugin.api_client, "get_all_cmdr_fcs", lambda name: [])
    monkeypatch.setattr(active.plugin.api_client, "get_commander_projects", lambda name: [
        {"linkedFC": [{"marketId": 101, "name": "101"}]},
    ])
    active.journal("Loadout", Ship="python", CargoCapacity=100, Modules=[])
    journal(active, "Location", {"drones": 20, "steel": 10}, Docked=True, StationType="FleetCarrier",
            MarketID=101, StationServices=["squadronBank"])
    full_cargo(active, {"drones": 10, "steel": 10}, 1)
    if capture == "cargo":
        full_cargo(active, {"drones": 30, "steel": 20}, 2)
    else:
        monkeypatch.setattr(active.load.config, "default_journal_dir", str(tmp_path), raising=False)
        (tmp_path / "Cargo.json").write_text(json.dumps({
            "event": "Cargo", "timestamp": "2026-11-08T17:00:02Z", "Vessel": "Ship", "Count": 50,
            "Inventory": [{"Name": "drones", "Count": 30}, {"Name": "steel", "Count": 20}],
        }))
        journal(active, "CollectCargo", {"drones": 30, "steel": 20},
                timestamp="2026-11-08T17:00:02Z", Type="steel", Count=10)
        (tmp_path / "Cargo.json").unlink()
    journal(active, "BuyDrones", {"drones": 50, "steel": 20}, timestamp="2026-11-08T17:00:02Z", Count=20)
    if capture == "cargo":
        journal(active, "CollectCargo", {"drones": 50, "steel": 30},
                timestamp="2026-11-08T17:00:01Z", Type="steel", Count=10)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 60, "steel": 0}
    full_cargo(active, {"drones": 50, "steel": 20}, 3)
    drain(active.plugin)
    assert active.remote[101] == {"drones": 60, "steel": 0}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1
