"""Keep retired link results within their original physical evidence and validate recovery identities."""

import json
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from conftest import settle_commander_links
from test_carrier_cargo_parity import drain
from test_inventory_frame_recovery import inventory_session as _inventory_fixture


@pytest.fixture
def generation_session(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Exercise actual journal and HTTP behavior with isolated state and a frozen clock."""
    return _inventory_fixture.__wrapped__(edmc_plugin, monkeypatch)


@pytest.mark.parametrize("old_linked", [False, True], ids=["retired-unlinked", "retired-linked"])
def test_retired_lookup_cannot_settle_a_newer_handlers_provisional_inventory(
    generation_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, old_linked: bool,
) -> None:
    """An older Alpha result cannot delete or confirm the physical evidence of a later Alpha login."""
    active = generation_session
    profiles = active.plugin.api_client.get_all_cmdr_fcs
    releases = [threading.Event(), threading.Event()]
    started = [threading.Event(), threading.Event()]
    counter = [0]
    counter_lock = threading.Lock()

    def delayed(name: str) -> list:
        if name != "Alpha":
            return profiles(name)
        with counter_lock:
            index = counter[0]
            counter[0] += 1
        started[index].set()
        assert releases[index].wait(timeout=3)
        linked = old_linked if index == 0 else not old_linked
        return profiles(name) if linked else []

    def journal(commander: str, event: str, amount: int = 50, **fields: Any) -> None:
        active.load.journal_entry(commander, False, "Sol", "101", {"event": event, **fields}, {
            "Docked": True, "StationType": "FleetCarrier", "MarketID": 101,
            "ShipType": "python", "Cargo": {"steel": amount}, "StationServices": ["squadronBank"],
        })

    active.journal("LoadGame", 50)
    active.load.journal_entry("Bravo", False, "Sol", "", {"event": "LoadGame"}, {})
    settle_commander_links(active.plugin)
    monkeypatch.setattr(active.plugin.api_client, "get_all_cmdr_fcs", delayed)
    old_handler = None
    new_handler = None
    try:
        journal("Alpha", "LoadGame")
        old_handler = active.plugin.fc_handler
        assert started[0].wait(timeout=3)
        active.load.journal_entry("Bravo", False, "Sol", "", {"event": "LoadGame"}, {})
        settle_commander_links(active.plugin)
        journal("Alpha", "Location", Docked=True, StationType="FleetCarrier", MarketID=101,
                StationName="101", StationServices=["squadronBank"])
        new_handler = active.plugin.fc_handler
        assert started[1].wait(timeout=3)
        journal("Alpha", "Cargo", 40, timestamp="2026-11-08T17:00:02Z", Vessel="Ship", Count=40,
                Inventory=[{"Name": "steel", "Count": 40}])
        journal("Alpha", "MarketSell", 35, timestamp="2026-11-08T17:00:02Z", MarketID=101, Type="steel", Count=5)
        frame, = active.plugin.pending_carrier_deliveries.inventory_frames("Alpha", 101)
        assert frame["provisional"] is True
        releases[0].set()
        old_handler.initialization_thread.join(timeout=3)
        active.plugin._apply_fc_initialization_results()
        drain(active.plugin)
        assert active.plugin.pending_carrier_deliveries.inventory_frames("Alpha", 101) == [frame]
        assert [item["cargo"] for item in active.plugin.pending_carrier_deliveries.records("Alpha", 101)] == [
            {"steel": 10},
        ]
    finally:
        for release in releases:
            release.set()
        for handler in (old_handler, new_handler):
            if handler is not None:
                handler.initialization_thread.join(timeout=3)
    settle_commander_links(active.plugin)
    drain(active.plugin)
    if old_linked:
        assert active.plugin.pending_carrier_deliveries.inventory_frames("Alpha", 101) == []
        journal("Bravo", "Location", Docked=True, StationType="FleetCarrier", MarketID=101,
                StationName="101", StationServices=["squadronBank"])
        settle_commander_links(active.plugin)
        journal("Bravo", "MarketSell", 48, timestamp="2026-11-08T17:00:04Z", MarketID=101, Type="steel", Count=2)
        drain(active.plugin)
        assert active.remote[101] == {"steel": 77}
    else:
        journal("Alpha", "Cargo", 35, timestamp="2026-11-08T17:00:03Z", Vessel="Ship", Count=35,
                Inventory=[{"Name": "steel", "Count": 35}])
        drain(active.plugin)
        assert active.remote[101] == {"steel": 90}


@pytest.mark.parametrize("field, invalid", [
    ("reservation_id", 1.5), ("reservation_id", True), ("reservation_id", 0),
    ("covered_ids", [1.5]), ("covered_frame_ids", [True]), ("permitted_ids", [0]),
])
def test_invalid_recovery_reference_identity_fails_closed_without_rewriting_evidence(
    generation_session: SimpleNamespace, tmp_path: Path, field: str, invalid: Any,
) -> None:
    """Nonpositive or noninteger recovery identities cannot enter the allocator or authorize carrier HTTP writes."""
    store = generation_session.plugin.pending_carrier_deliveries
    store.configure(str(tmp_path))
    store.begin_replacement("Alpha", 101, {"steel": 125}, [], attempted=False, source="manual")
    if field == "permitted_ids":
        store.checkpoint_inventory("Alpha", 101, {}, {"before": {"steel": 50}})
    checkpoint = tmp_path / "RavenColonial.carrier-cargo-recovery.json"
    payload = json.loads(checkpoint.read_text())
    payload.pop("next_id", None)
    target = payload["inventory_frames"][0] if field == "permitted_ids" else payload["replacements"][0]
    target[field] = invalid
    contents = json.dumps(payload)
    checkpoint.write_text(contents)
    restored = generation_session.load.PendingCarrierDeliveries()
    restored.configure(str(tmp_path))
    identity = restored.record("Bravo", 303, {"steel": 2})
    with pytest.raises(OSError, match="could not be loaded"):
        restored.begin(identity, {"steel": 90})
    assert checkpoint.read_text() == contents


def test_scoped_inventory_cleanup_preserves_later_same_commander_evidence(
    generation_session: SimpleNamespace,
) -> None:
    """The durable cleanup operation removes only the frame and records captured by its lookup owner."""
    store = generation_session.plugin.pending_carrier_deliveries
    old_record, old_frame = store.checkpoint_inventory(
        "Alpha", 101, {"steel": 5}, {"before": {"steel": 50}}, provisional=True,
    )
    store.checkpoint_inventory("Alpha", 101, {"steel": 2}, {"before": {"steel": 40}}, provisional=True)
    store.discard_provisional_inventory("Alpha", 101, frame_ids={old_frame}, record_ids={old_record})
    frame, = store.inventory_frames("Alpha", 101)
    assert frame["state"]["before"] == {"steel": 40}
    assert [record["cargo"] for record in store.records("Alpha", 101)] == [{"steel": 2}]
