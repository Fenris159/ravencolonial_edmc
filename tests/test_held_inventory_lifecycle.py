"""Keep held physical observations ordered, serialized, and tied to their original evidence time."""

from types import SimpleNamespace
import threading

import pytest

from conftest import settle_commander_links
from test_carrier_cargo_parity import drain, session as _session_fixture
from test_mixed_inventory_attribution import journal


def setup_ship(edmc_plugin, monkeypatch: pytest.MonkeyPatch, key: str, stock: int, amount: int) -> SimpleNamespace:
    """Establish real server and ship baselines using the existing isolated HTTP/journal boundary."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {key: stock}
    journal(active, "Loadout", {key: amount}, Ship="python", CargoCapacity=100, Modules=[])
    journal(active, "Location", {key: amount}, Docked=True, StationType="FleetCarrier", MarketID=101,
            StationServices=["squadronBank"])
    journal(active, "Cargo", {key: amount}, timestamp="1970-01-01T00:00:00Z", Vessel="Ship", Count=amount,
            Inventory=[{"Name": key, "Count": amount}])
    drain(active.plugin)
    return active


def test_held_observation_waits_until_earlier_initial_deliveries_are_represented(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Buying10 exhausts Raven10; the later five collected tonnes cannot become a carrier refund."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"steel": 10}
    entered, release = threading.Event(), threading.Event()

    def links(name: str) -> list:
        entered.set()
        assert release.wait(timeout=3)
        return [{"marketId": 101, "name": "101", "cargo": {"steel": 10}}]

    def raw(event: str, amount: int, **fields) -> None:
        active.load.journal_entry("Alpha", False, "Sol", "101", {"event": event, **fields}, {
            "Docked": True, "StationType": "FleetCarrier", "MarketID": 101,
            "ShipType": "python", "Cargo": {"steel": amount},
        })

    monkeypatch.setattr(active.plugin.api_client, "get_all_cmdr_fcs", links)
    try:
        raw("Loadout", 50, Ship="python", CargoCapacity=100, Modules=[])
        assert entered.wait(timeout=3)
        raw("Location", 50, Docked=True, StationType="FleetCarrier", MarketID=101,
            StationServices=["squadronBank"])
        raw("Cargo", 50, timestamp="2026-11-08T17:00:00Z", Vessel="Ship", Count=50,
            Inventory=[{"Name": "steel", "Count": 50}])
        raw("MarketBuy", 60, timestamp="2026-11-08T17:00:01Z", MarketID=101, Type="steel", Count=10)
        raw("Cargo", 65, timestamp="2026-11-08T17:00:02Z", Vessel="Ship", Count=65,
            Inventory=[{"Name": "steel", "Count": 65}])
    finally:
        release.set()
    settle_commander_links(active.plugin)
    drain(active.plugin)
    raw("CollectCargo", 65, timestamp="2026-11-08T17:00:02Z", Type="steel", Count=5)
    raw("Cargo", 65, timestamp="2026-11-08T17:00:03Z", Vessel="Ship", Count=65,
        Inventory=[{"Name": "steel", "Count": 65}])
    drain(active.plugin)
    assert active.remote[101] == {"steel": 0}
    assert active.plugin.pending_carrier_deliveries.records() == []


def test_worker_replay_cannot_mix_a_held_inventory_with_new_journal_accounting(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An older held25 and a concurrent BuyDrones10 cannot manufacture five drones against Raven2."""
    active = setup_ship(edmc_plugin, monkeypatch, "drones", 2, 20)
    journal(active, "Cargo", {"drones": 25}, timestamp="1970-01-01T00:00:01Z", Vessel="Ship", Count=25,
            Inventory=[{"Name": "drones", "Count": 25}])
    drain(active.plugin)
    owner = active.plugin.fc_handler
    replay_started, release_replay, journal_at_lock = threading.Event(), threading.Event(), threading.Event()
    lock = owner._cargo_state_lock

    class ObservedLock:
        """Pause the real worker-owned lock while the new journal reaches the same boundary."""

        def __enter__(self):
            thread = threading.current_thread().name
            if thread == "new-drone-journal":
                journal_at_lock.set()
            lock.acquire()
            if thread == "held-drone-replay" and not replay_started.is_set():
                replay_started.set()
                assert release_replay.wait(timeout=3)
            return self

        def __exit__(self, *args) -> None:
            lock.release()

    monkeypatch.setattr(owner, "_cargo_state_lock", ObservedLock())
    errors = []

    def replay() -> None:
        try:
            owner._retry_held_inventory(101)
        except BaseException as error:
            errors.append(error)

    def newer_journal() -> None:
        try:
            journal(active, "BuyDrones", {"drones": 35}, timestamp="1970-01-01T00:00:02Z", Count=10)
        except BaseException as error:
            errors.append(error)
        finally:
            journal_at_lock.set()

    worker = threading.Thread(target=replay, name="held-drone-replay")
    newer = threading.Thread(target=newer_journal, name="new-drone-journal")
    worker.start()
    try:
        assert replay_started.wait(timeout=3)
        newer.start()
        assert journal_at_lock.wait(timeout=3)
    finally:
        release_replay.set()
        worker.join(timeout=3)
        if newer.ident is not None:
            newer.join(timeout=3)
    assert not worker.is_alive()
    assert not newer.is_alive()
    assert errors == []
    drain(active.plugin)
    assert active.remote[101] == {"drones": 2}
    journal(active, "Cargo", {"drones": 35}, timestamp="1970-01-01T00:00:03Z", Vessel="Ship", Count=35,
            Inventory=[{"Name": "drones", "Count": 35}])
    drain(active.plugin)
    assert active.remote[101] == {"drones": 2}


def test_unchanged_failed_replay_does_not_make_a_fresh_capi_snapshot_look_stale(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry at200 cannot move evidence observed at100 past a valid physical carrier snapshot captured at150."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    clock = [100.0]
    monkeypatch.setattr(active.load.time, "time", lambda: clock[0])
    active.remote[101] = {"steel": 2}
    journal(active, "Loadout", {"steel": 50}, Ship="python", CargoCapacity=100, Modules=[])
    journal(active, "Location", {"steel": 50}, Docked=True, StationType="FleetCarrier", MarketID=101,
            StationServices=["squadronBank"])
    journal(active, "Cargo", {"steel": 50}, timestamp="1970-01-01T00:00:00Z", Vessel="Ship", Count=50,
            Inventory=[{"Name": "steel", "Count": 50}])
    journal(active, "Cargo", {"steel": 60}, timestamp="1970-01-01T00:01:40Z", Vessel="Ship", Count=60,
            Inventory=[{"Name": "steel", "Count": 60}])
    drain(active.plugin)
    owner = active.plugin.fc_handler
    clock[0] = 200.0
    owner._retry_held_inventory(101)
    active.load.journal_entry("Alpha", False, "Sol", "", {"event": "Undocked"},
                              {"Docked": False, "ShipType": "python", "Cargo": {"steel": 60}})
    owner.update_fc_cargo_from_capi(101, {"steel": 1}, 150.0)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 1}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
