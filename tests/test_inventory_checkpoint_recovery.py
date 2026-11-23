"""Keep inventory barriers durable and their retained delivery identities unique after restart."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from test_inventory_frame_recovery import inventory_session as _inventory_fixture
from test_carrier_cargo_parity import drain


@pytest.fixture
def checkpoint_session(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Use the real journal/client and frozen-clock setup from the inventory recovery suite."""
    return _inventory_fixture.__wrapped__(edmc_plugin, monkeypatch)


def test_restart_cannot_reuse_an_acknowledged_delivery_permitted_by_an_old_inventory_frame(
    checkpoint_session: SimpleNamespace, tmp_path: Path,
) -> None:
    """A new sale must stay blocked rather than inheriting permission from a retired transaction."""
    active = checkpoint_session
    active.dock(False)
    store = active.plugin.pending_carrier_deliveries
    store.configure(str(tmp_path))
    identity, _ = store.checkpoint_inventory("Alpha", 101, {"steel": 1}, {"before": {"steel": 50}})
    store.acknowledge([identity])
    checkpoint = tmp_path / "RavenColonial.carrier-cargo-recovery.json"
    payload = json.loads(checkpoint.read_text())
    payload.pop("next_id", None)  # Migrate an existing checkpoint written before the durable allocator.
    checkpoint.write_text(json.dumps(payload))
    store = active.load.PendingCarrierDeliveries()
    store.configure(str(tmp_path))
    active.plugin.pending_carrier_deliveries = store
    active.journal("MarketSell", 45, MarketID=101, Type="steel", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 75}
    record, = store.records("Alpha", 101)
    assert record["id"] == 3
    assert record["cargo"] == {"steel": 5}
    assert record["attempted"] is False


def test_restart_retains_the_allocator_after_all_transactions_are_acknowledged(
    checkpoint_session: SimpleNamespace, tmp_path: Path,
) -> None:
    """Acknowledging the last record must not make its identity available to the next session."""
    store = checkpoint_session.plugin.pending_carrier_deliveries
    store.configure(str(tmp_path))
    first = store.record("Alpha", 101, {"steel": 1})
    store.acknowledge([first])
    restored = checkpoint_session.load.PendingCarrierDeliveries()
    restored.configure(str(tmp_path))
    assert restored.record("Alpha", 101, {"steel": 2}) == 2


@pytest.mark.parametrize("remove", [False, True], ids=["new-frame", "cleared-frame"])
def test_frame_only_checkpoint_retries_when_storage_returns_without_an_http_transaction(
    checkpoint_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, remove: bool,
) -> None:
    """A zero-delta frame creation or removal must survive restart once its failed disk write is retried."""
    store = checkpoint_session.plugin.pending_carrier_deliveries
    store.configure(str(tmp_path))
    state = {"before": {"steel": 50}, "accounted": {"steel": -5}}
    frame_id = None
    if remove:
        _, frame_id = store.checkpoint_inventory("Alpha", 101, {}, state)

    def unavailable(path: Path, target: Any) -> None:
        raise OSError("temporary storage failure")

    with monkeypatch.context() as broken_storage:
        broken_storage.setattr(Path, "replace", unavailable)
        store.checkpoint_inventory("Alpha", 101, {}, None if remove else state, frame_id)
        assert store.retry_checkpoint() is False
        assert store.checkpoint_pending() is True
    assert store.records() == []
    assert store.replacements() == []
    assert store.retry_checkpoint() is True
    restored = checkpoint_session.load.PendingCarrierDeliveries()
    restored.configure(str(tmp_path))
    assert restored.inventory_frames() == ([] if remove else [{
        "id": 1, "commander": "Alpha", "market_id": 101, "state": state,
        "permitted_ids": [], "observed_at": 1000.0, "provisional": False,
    }])
    assert store.checkpoint_pending() is False


def pending_unlinked_inventory(
    active: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, *, frame_only: bool = False, linked_other: bool = False,
    linked_current: bool = False,
) -> tuple[Any, Any]:
    """Pause the real link lookup while provisional physical evidence reaches the journal hook."""
    import threading

    release, started = threading.Event(), threading.Event()
    profiles = active.plugin.api_client.get_all_cmdr_fcs

    def delayed(name: str) -> list:
        if name == "Unlinked":
            started.set()
            assert release.wait(timeout=2)
            if linked_current:
                return [{"marketId": 101, "name": "101", "cargo": {"steel": 75}}]
            return [{"marketId": 303, "name": "303", "cargo": {"steel": 90}}] if linked_other else []
        return profiles(name)

    monkeypatch.setattr(active.plugin.api_client, "get_all_cmdr_fcs", delayed)

    def journal(event: str, amount: int, market: int = 101, **fields: Any) -> None:
        active.load.journal_entry("Unlinked", False, "Sol", str(market), {"event": event, **fields}, {
            "Docked": True, "StationType": "FleetCarrier", "MarketID": market,
            "ShipType": "python", "Cargo": {"steel": amount}, "StationServices": ["squadronBank"],
        })

    journal("Location", 50, Docked=True, StationType="FleetCarrier", MarketID=101,
            StationName="101", StationServices=["squadronBank"])
    assert started.wait(timeout=2)
    journal("Cargo", 50 if frame_only else 40, timestamp="2026-11-08T17:00:02Z", Vessel="Ship",
            Count=50 if frame_only else 40,
            Inventory=[{"Name": "steel", "Count": 50 if frame_only else 40}])
    if frame_only:
        journal("EjectCargo", 47, timestamp="2026-11-08T17:00:02Z", Type="steel", Count=3)
    else:
        journal("MarketSell", 35, timestamp="2026-11-08T17:00:02Z", MarketID=101, Type="steel", Count=5)
    if linked_other:
        journal("Location", 50, 303, Docked=True, StationType="FleetCarrier", MarketID=303,
                StationName="303", StationServices=["commodities"])
        journal("CargoTransfer", 48, 303, Transfers=[{"Type": "steel", "Count": 2, "Direction": "tocarrier"}])
    return release, active.plugin.fc_handler


@pytest.mark.parametrize("frame_only", [False, True], ids=["provisional-deliveries", "no-delivery-record"])
def test_successful_unlinked_lookup_discards_its_provisional_inventory_barrier(
    checkpoint_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, frame_only: bool,
) -> None:
    """Rejected provisional tracking cannot leave an orphan barrier blocking a later eligible commander."""
    from conftest import settle_commander_links

    active = checkpoint_session
    release, handler = pending_unlinked_inventory(active, monkeypatch, frame_only=frame_only)
    try:
        frame, = active.plugin.pending_carrier_deliveries.inventory_frames("Unlinked", 101)
        assert frame["provisional"] is True
    finally:
        release.set()
        handler.initialization_thread.join(timeout=2)
    settle_commander_links(active.plugin)
    drain(active.plugin)
    assert active.plugin.pending_carrier_deliveries.inventory_frames("Unlinked", 101) == []
    assert active.plugin.pending_carrier_deliveries.records("Unlinked", 101) == []
    active.journal("Location", 50, Docked=True, StationType="FleetCarrier", MarketID=101,
                   StationName="101", StationServices=["squadronBank"])
    active.journal("MarketSell", 48, timestamp="2026-11-08T17:00:04Z", MarketID=101, Type="steel", Count=2)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 77}


def test_failed_ineligible_cleanup_retains_evidence_without_blocking_another_market(
    checkpoint_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A cleanup disk failure preserves one carrier's evidence while eligible work for another carrier succeeds."""
    from conftest import settle_commander_links

    active = checkpoint_session
    active.plugin.pending_carrier_deliveries.configure(str(tmp_path))
    release, handler = pending_unlinked_inventory(active, monkeypatch, linked_other=True)
    replace = Path.replace

    def reject_cleanup(path: Path, target: Any) -> Any:
        if Path(target).name == "RavenColonial.carrier-cargo-recovery.json":
            frames = json.loads(path.read_text())["inventory_frames"]
            if not any(frame["commander"] == "Unlinked" and frame["market_id"] == 101 for frame in frames):
                raise OSError("cleanup unavailable")
        return replace(path, target)

    try:
        with monkeypatch.context() as failing_cleanup:
            failing_cleanup.setattr(Path, "replace", reject_cleanup)
            release.set()
            handler.initialization_thread.join(timeout=2)
            settle_commander_links(active.plugin)
            drain(active.plugin)
            frame, = active.plugin.pending_carrier_deliveries.inventory_frames("Unlinked", 101)
            assert frame["provisional"] is True
            assert active.remote == {101: {"steel": 75}, 303: {"steel": 92}}
    finally:
        release.set()
        handler.initialization_thread.join(timeout=2)
    handler.retry_pending_deliveries()
    assert active.plugin.pending_carrier_deliveries.inventory_frames("Unlinked", 101) == []
    assert active.plugin.pending_carrier_deliveries.records("Unlinked", 101) == []


def test_discarding_provisional_inventory_preserves_issued_and_other_commander_evidence(
    checkpoint_session: SimpleNamespace,
) -> None:
    """Local eligibility cleanup removes only unissued work and physical frames belonging to that commander."""
    store = checkpoint_session.plugin.pending_carrier_deliveries
    issued = store.record("Alpha", 101, {"steel": 5})
    assert store.begin(issued, {"steel": 75}) is True
    store.checkpoint_inventory("Alpha", 101, {"steel": 2}, {"before": {"steel": 50}}, provisional=True)
    store.checkpoint_inventory("Bravo", 101, {"steel": 3}, {"before": {"steel": 40}})
    store.discard_provisional_inventory("Alpha", 101)
    assert [record["cargo"] for record in store.records("Alpha", 101)] == [{"steel": 5}]
    frame, = store.inventory_frames("Bravo", 101)
    assert frame["state"]["before"] == {"steel": 40}
    assert [record["cargo"] for record in store.records("Bravo", 101)] == [{"steel": 3}]
    assert store.inventory_frames("Alpha", 101) == []


def test_confirmed_inventory_evidence_survives_a_later_loss_of_link_eligibility(
    checkpoint_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A frame accepted while the commander was linked cannot be discarded as provisional on a later login."""
    from conftest import settle_commander_links

    active = checkpoint_session
    release, handler = pending_unlinked_inventory(active, monkeypatch, linked_current=True)
    try:
        provisional, = active.plugin.pending_carrier_deliveries.inventory_frames("Unlinked", 101)
        assert provisional["provisional"] is True
    finally:
        release.set()
        handler.initialization_thread.join(timeout=2)
    settle_commander_links(active.plugin)
    drain(active.plugin)
    confirmed, = active.plugin.pending_carrier_deliveries.inventory_frames("Unlinked", 101)
    assert confirmed["provisional"] is False
    assert active.remote[101] == {"steel": 85}
    profiles = active.plugin.api_client.get_all_cmdr_fcs
    monkeypatch.setattr(active.plugin.api_client, "get_all_cmdr_fcs",
                        lambda name: [] if name == "Unlinked" else profiles(name))
    for commander in ("Alpha", "Unlinked"):
        active.load.journal_entry(commander, False, "Sol", "", {"event": "LoadGame"}, {})
        settle_commander_links(active.plugin)
    drain(active.plugin)
    assert active.plugin.pending_carrier_deliveries.inventory_frames("Unlinked", 101) == [confirmed]
    assert active.remote[101] == {"steel": 85}


@pytest.mark.parametrize("entrypoint", ["periodic", "shutdown"])
def test_frame_only_dirty_checkpoint_is_flushed_by_the_existing_recovery_entrypoints(
    checkpoint_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, entrypoint: str,
) -> None:
    """Periodic recovery and shutdown both persist unsaved physical evidence without needing an HTTP transaction."""
    active = checkpoint_session
    active.dock(False)
    store = active.plugin.pending_carrier_deliveries
    store.configure(str(tmp_path))

    def unavailable(path: Path, target: Any) -> None:
        raise OSError("temporary storage failure")

    with monkeypatch.context() as broken_storage:
        broken_storage.setattr(Path, "replace", unavailable)
        store.checkpoint_inventory("Alpha", 101, {}, {"before": {"steel": 50}})
    if entrypoint == "periodic":
        active.plugin.fc_handler.maybe_queue_delivery_recovery()
        drain(active.plugin)
    else:
        active.load.plugin_stop()
    restored = active.load.PendingCarrierDeliveries()
    restored.configure(str(tmp_path))
    frame, = restored.inventory_frames("Alpha", 101)
    assert frame["state"]["before"] == {"steel": 50}
    assert restored.records() == []
    assert restored.replacements() == []
    assert store.checkpoint_pending() is False


@pytest.mark.parametrize("provisional", [None, "false"], ids=["legacy-frame", "malformed-flag"])
def test_checkpoint_cleanup_cannot_treat_legacy_or_malformed_flags_as_provisional_permission(
    checkpoint_session: SimpleNamespace, tmp_path: Path, provisional: Any,
) -> None:
    """Missing or invalid ownership flags cannot authorize deleting physical recovery evidence."""
    checkpoint = tmp_path / "RavenColonial.carrier-cargo-recovery.json"
    frame = {"id": 1, "commander": "Alpha", "market_id": 101,
             "permitted_ids": [], "state": {"before": {"steel": 50}}}
    if provisional is not None:
        frame["provisional"] = provisional
    contents = json.dumps({"version": 2, "records": [], "replacements": [], "inventory_frames": [frame]})
    checkpoint.write_text(contents)
    store = checkpoint_session.load.PendingCarrierDeliveries()
    store.configure(str(tmp_path))
    store.discard_provisional_inventory("Alpha", 101)
    assert checkpoint.read_text() == contents
