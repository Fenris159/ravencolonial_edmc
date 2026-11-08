"""Keep mixed transfers correct when only one commodity has unresolved origin evidence."""

import json
from types import SimpleNamespace

import pytest

from conftest import settle_commander_links
from test_carrier_cargo_parity import drain
from test_inventory_frame_recovery import inventory_session as _inventory_fixture


@pytest.fixture
def mixed_session(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Exercise actual journal attribution and the HTTP client with two physical commodities."""
    active = _inventory_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101]["copper"] = 100
    return active


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


@pytest.mark.parametrize("observation", ["later", "same_second", "newer", "origin"])
def test_mixed_transfer_reconciles_each_commodity_against_its_own_evidence(
    mixed_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path, observation: str,
) -> None:
    """Steel's pending origin cannot count copper5 twice or swallow its first explicit transfer."""
    active = mixed_session
    journal(active, "Location", {}, Docked=True, StationType="FleetCarrier", MarketID=101,
            StationServices=["squadronBank"])
    inventory(active, 50, 10, 1)
    inventory(active, 40, 10, 2)
    journal(active, "MarketSell", {"steel": 30, "copper": 10}, timestamp="2026-11-08T17:00:01Z",
            MarketID=101, Type="steel", Count=10)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 85, "copper": 100}

    if observation in {"same_second", "newer"}:
        inventory(active, 38, 5, 3 if observation == "same_second" else 4)
        drain(active.plugin)
        assert active.remote[101] == {"steel": 85, "copper": 105}
    if observation == "same_second":
        monkeypatch.setattr(active.load.config, "default_journal_dir", str(tmp_path), raising=False)
        (tmp_path / "Cargo.json").write_text(json.dumps({
            "event": "Cargo", "timestamp": "2026-11-08T17:00:03Z", "Vessel": "Ship", "Count": 43,
            "Inventory": [{"Name": "steel", "Count": 38}, {"Name": "copper", "Count": 5}],
        }))
    second = 1 if observation == "origin" else 3
    journal(active, "CargoTransfer", {"steel": 38, "copper": 5},
            timestamp=f"2026-11-08T17:00:0{second}Z", Transfers=[
                {"Type": "steel", "Count": 2, "Direction": "tocarrier"},
                {"Type": "copper", "Count": 5, "Direction": "tocarrier"},
            ])
    drain(active.plugin)
    assert active.remote[101] == {"steel": 87, "copper": 105}
    inventory(active, 38, 10 if observation == "origin" else 5, 5)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 87, "copper": 105}
