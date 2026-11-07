"""Behavior parity with SrvSurvey-XP e30d561's carrier cargo contracts."""

from copy import deepcopy
import importlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
import requests

from conftest import settle_commander_links


def drain(plugin) -> None:
    """Execute queued network work without starting a background worker."""
    while not plugin.api_queue.empty():
        function, args, kwargs = plugin.api_queue.get_nowait()
        function(*args, **kwargs)
        plugin.api_queue.task_done()


def apply_mentioned_amounts(cargo, amounts) -> None:
    """Model Raven's absolute-write contract: omitted commodities survive, explicit zeros remove stock."""
    for key, value in amounts.items():
        if value:
            cargo[key] = value
        else:
            cargo.pop(key, None)


@pytest.fixture
def session(edmc_plugin, monkeypatch) -> SimpleNamespace:
    """Run the real journal and HTTP client against two isolated carrier manifests."""
    load, plugin = edmc_plugin
    remote = {101: {"steel": 75}, 303: {"steel": 90}}
    writes = []
    monkeypatch.setattr(plugin, "_ensure_api_worker", lambda: None)
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda name: [])
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda name: [
        {"marketId": market_id, "name": str(market_id), "cargo": deepcopy(cargo)}
        for market_id, cargo in remote.items()
    ])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {
        "marketId": mid, "cargo": deepcopy(remote[mid]),
    })

    def request(method, url, **kwargs) -> requests.Response:
        if method == "PATCH" and url.endswith("/cargo"):
            mid = int(url.split("/")[-2])
            delta = kwargs["json"]
            writes.append((mid, dict(delta)))
            for key, value in delta.items():
                remote[mid][key] = max(0, remote[mid].get(key, 0) + value)
            payload = remote[mid]
        elif method == "POST" and url.endswith("/cargo"):
            mid = int(url.split("/")[-2])
            apply_mentioned_amounts(remote[mid], kwargs["json"])
            payload = remote[mid]
        elif method == "POST" and url.endswith("/currentShip"):
            payload = {}
        else:
            raise AssertionError(f"Unexpected HTTP {method} {url}")
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(payload).encode()
        return response

    monkeypatch.setattr(plugin.api_client, "session", SimpleNamespace(request=request, headers={}))

    def journal(event, cargo_count=50, ship_type="python", **fields) -> None:
        state = {"Docked": True, "StationType": "FleetCarrier", "MarketID": 101,
                 "ShipType": ship_type, "Cargo": {"steel": cargo_count}}
        load.journal_entry("Alpha", False, "Sol", "101", {"event": event, **fields}, state)
        settle_commander_links(plugin)

    def dock(squadron) -> None:
        journal("Location", Docked=True, StationType="FleetCarrier", MarketID=101,
                StationName="101", StationServices=["squadronBank"] if squadron else ["commodities"])
        journal("Cargo", Vessel="Ship", Count=50, Inventory=[{"Name": "steel", "Count": 50}])
        drain(plugin)

    return SimpleNamespace(load=load, plugin=plugin, remote=remote, writes=writes, journal=journal, dock=dock)


@pytest.mark.parametrize("squadron", [False, True])
def test_explicit_transfers_and_market_trades_apply_once(session, squadron) -> None:
    """Both carrier types count transfers and trades once despite following snapshots."""
    session.dock(squadron)
    session.journal("CargoTransfer", 40, Transfers=[{"Type": "steel", "Count": 10, "Direction": "tocarrier"}])
    session.journal("Cargo", 40, Vessel="Ship", Count=40, Inventory=[{"Name": "steel", "Count": 40}])
    session.journal("CargoTransfer", 47, Transfers=[{"Type": "steel", "Count": 7, "Direction": "toship"}])
    session.journal("Cargo", 47, Vessel="Ship", Count=47, Inventory=[{"Name": "steel", "Count": 47}])
    session.journal("MarketBuy", 50, MarketID=101, Type="steel", Count=3)
    session.journal("Cargo", 50, Vessel="Ship", Count=50)
    session.journal("MarketSell", 48, MarketID=101, Type="steel", Count=2)
    session.journal("Cargo", 48, Vessel="Ship", Count=48)
    drain(session.plugin)
    assert session.remote[101] == {"steel": 77}
    assert session.writes == [(101, {"steel": 10}), (101, {"steel": -7}),
                              (101, {"steel": -3}), (101, {"steel": 2})]


@pytest.mark.parametrize("squadron, expected", [(False, 75), (True, 85)])
def test_snapshot_only_bank_movement_matches_xp(session, squadron, expected) -> None:
    """Only squadron banks infer otherwise unreported movement from known ship inventory."""
    session.dock(squadron)
    session.journal("Cargo", 40, Vessel="Ship", Count=40, Inventory=[{"Name": "steel", "Count": 40}])
    session.journal("Cargo", 40, Vessel="Ship", Count=40)
    drain(session.plugin)
    assert session.remote[101] == {"steel": expected}


@pytest.mark.parametrize("squadron", [False, True])
def test_srv_transfer_is_not_a_carrier_transaction(session, squadron) -> None:
    """A non-ship transfer cannot mutate a retained carrier dock context."""
    session.dock(squadron)
    session.journal("CargoTransfer", 51, ship_type="testbuggy",
                    Transfers=[{"Type": "steel", "Count": 1, "Direction": "toship"}])
    drain(session.plugin)
    assert session.remote[101] == {"steel": 75}
    assert session.writes == []


def test_trade_for_other_market_does_not_mutate_linked_carrier(session) -> None:
    """A linked market still needs to match this event's current dock."""
    session.dock(False)
    session.journal("MarketBuy", 55, MarketID=303, Type="steel", Count=5)
    drain(session.plugin)
    assert session.remote == {101: {"steel": 75}, 303: {"steel": 90}}


def test_transfer_commodity_token_uses_canonical_key(session) -> None:
    """Journal tokens reach Raven as canonical commodity names."""
    session.dock(False)
    session.journal("CargoTransfer", 46,
                    Transfers=[{"Type": "$Steel_Name;", "Count": 4, "Direction": "tocarrier"}])
    drain(session.plugin)
    assert session.writes == [(101, {"steel": 4})]


@pytest.mark.parametrize("first_is_squadron", [False, True])
def test_cargo_can_move_between_carrier_types_in_one_session(session, first_is_squadron) -> None:
    """Changing docks transfers ten tonnes between carrier types without restarting EDMC."""
    session.dock(first_is_squadron)
    session.journal("CargoTransfer", 60,
                    Transfers=[{"Type": "steel", "Count": 10, "Direction": "toship"}])
    session.journal("Cargo", 60, Vessel="Ship", Count=60, Inventory=[{"Name": "steel", "Count": 60}])
    session.load.journal_entry("Alpha", False, "Sol", "101", {"event": "Undocked"},
                               {"IsDocked": False, "ShipType": "python", "Cargo": {"steel": 60}})
    services = ["commodities"] if first_is_squadron else ["squadronBank"]
    state = {"IsDocked": True, "StationType": "FleetCarrier", "MarketID": 303,
             "ShipType": "python", "Cargo": {"steel": 60}}
    session.load.journal_entry("Alpha", False, "Sol", "303", {
        "event": "Docked", "StationType": "FleetCarrier", "MarketID": 303,
        "StationName": "303", "StationServices": services,
    }, state)
    state["Cargo"] = {"steel": 50}
    session.load.journal_entry("Alpha", False, "Sol", "303", {
        "event": "CargoTransfer",
        "Transfers": [{"Type": "steel", "Count": 10, "Direction": "tocarrier"}],
    }, state)
    session.load.journal_entry("Alpha", False, "Sol", "303", {
        "event": "Cargo", "Vessel": "Ship", "Count": 50,
        "Inventory": [{"Name": "steel", "Count": 50}],
    }, state)
    drain(session.plugin)
    assert session.remote == {101: {"steel": 65}, 303: {"steel": 100}}
    assert session.writes == [(101, {"steel": -10}), (303, {"steel": 10})]


def test_failed_issued_write_retains_reconciliation_evidence(session, monkeypatch, tmp_path) -> None:
    """An issued 503 survives restart as uncertain evidence, rather than replayable unsent cargo."""
    session.dock(True)
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    requests_seen = []

    def request(*args, **kwargs) -> requests.Response:
        requests_seen.append(dict(kwargs["json"]))
        response = requests.Response()
        response.status_code = 503
        response._content = b'{"error":"unavailable"}'
        return response

    monkeypatch.setattr(plugin.api_client, "session", SimpleNamespace(request=request))
    plugin.fc_handler.handle_cargotransfer_event({
        "Transfers": [{"Type": "steel", "Count": 5, "Direction": "tocarrier"}],
    }, {"ShipType": "python"})
    drain(plugin)
    assert requests_seen == [{"steel": 5}]
    restored = session.load.PendingCarrierDeliveries()
    restored.configure(str(tmp_path))
    record, = restored.records("Alpha", 101)
    assert record["cargo"] == {"steel": 5}
    assert record["before"] == {"steel": 75}
    assert record["attempted"] is True
    assert record["uncertain"] is True


@pytest.mark.parametrize("newer_finishes_first", [False, True])
def test_overlapping_reads_keep_the_later_requested_stock(session, newer_finishes_first) -> None:
    """Two reads without an intervening write converge on the later requested observation."""
    session.dock(False)
    handler = session.plugin.fc_handler
    older = handler.cargo_read_revision()
    newer = handler.cargo_read_revision()
    observations = [(older, {"steel": 75}), (newer, {"steel": 90})]
    if newer_finishes_first:
        observations.reverse()
    for revision, cargo in observations:
        handler.replace_fc_cargo_manifest(101, cargo, source="raven_colonial_api", read_revision=revision)
    assert handler.linked_fcs[101]["cargo"] == {"steel": 90}


def test_explicit_rejection_cannot_be_acknowledged_by_another_clients_matching_stock(session, monkeypatch) -> None:
    """A rejected +5 remains pending when a different client's +5 raises Raven to 80."""
    session.dock(False)
    plugin = session.plugin
    request = plugin.api_client.session.request

    def reject(*args, **kwargs) -> requests.Response:
        response = requests.Response()
        response.status_code = 403
        response._content = b'{}'
        return response

    monkeypatch.setattr(plugin.api_client.session, "request", reject)
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    session.remote[101] = {"steel": 80}
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    plugin.fc_handler.retry_pending_deliveries()
    assert session.remote[101] == {"steel": 80}
    record, = plugin.pending_carrier_deliveries.records()
    assert record["cargo"] == {"steel": 5}
    assert record["uncertain"] is False


@pytest.mark.parametrize("failure, expected", [(requests.ConnectTimeout, 80), (requests.ReadTimeout, 75)])
def test_only_definitely_unsent_timeouts_resume_after_connectivity_returns(
    session, monkeypatch, failure, expected,
) -> None:
    """A connect timeout is safe to retry against unchanged stock; a lost reply is ambiguous."""
    session.dock(False)
    plugin = session.plugin
    request = plugin.api_client.session.request

    def timeout(*args, **kwargs) -> None:
        raise failure("network unavailable")

    monkeypatch.setattr(plugin.api_client.session, "request", timeout)
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    plugin.fc_handler.retry_pending_deliveries()
    assert session.remote[101] == {"steel": expected}
    assert session.writes == ([(101, {"steel": 5})] if failure is requests.ConnectTimeout else [])


def test_other_commander_waits_for_same_carriers_unresolved_write(session, monkeypatch) -> None:
    """Bravo cannot advance Alpha's uncertain carrier stock before that outcome is resolved."""
    session.dock(False)
    plugin = session.plugin
    alpha = plugin.fc_handler
    request = plugin.api_client.session.request

    def lose_reply(method, url, **kwargs) -> requests.Response:
        response = request(method, url, **kwargs)
        if method == "PATCH":
            raise requests.ReadTimeout("committed, reply lost")
        return response

    monkeypatch.setattr(plugin.api_client.session, "request", lose_reply)
    alpha._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    session.load.journal_entry("Bravo", False, "Sol", "", {"event": "LoadGame"}, {})
    settle_commander_links(plugin)
    # Bravo's lookup schedules recovery of the retired handler; hold it until after this delivery.
    recovery = []
    while not plugin.api_queue.empty():
        recovery.append(plugin.api_queue.get_nowait())
        plugin.api_queue.task_done()
    plugin.fc_handler._supply_fc_async(101, {"steel": 2})
    plugin.fc_handler._supply_fc_async(303, {"steel": 3})
    drain(plugin)
    assert session.remote == {101: {"steel": 80}, 303: {"steel": 93}}
    alpha.retry_pending_deliveries()
    plugin.fc_handler.retry_pending_deliveries()
    assert session.remote[101] == {"steel": 82}
    assert plugin.pending_carrier_deliveries.records() == []


@pytest.mark.parametrize("tracking_enabled", [False, True])
def test_failed_unknown_withdrawal_stays_unsynced_in_cache_only_overlay(session, monkeypatch, tracking_enabled) -> None:
    """An optimistic empty hold without an observed baseline must not turn sync into zero-stock deficits."""
    plugin = session.plugin
    plugin.overlay_carrier_tracking_enabled = tracking_enabled
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda name: [])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda name: [
        {"linkedFC": [{"marketId": 101, "name": "101"}]},
    ])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: None)

    def timeout(*args, **kwargs) -> None:
        raise requests.ReadTimeout("no acknowledgement")

    monkeypatch.setattr(plugin.api_client.session, "request", timeout)
    session.dock(False)
    plugin.fc_handler._supply_fc_async(101, {"steel": -5})
    drain(plugin)
    assert plugin.overlay_fc_cargo_by_market == {}
    fetch = importlib.import_module(f"{session.load.__package__}.ui.overlay_fc_cargo_fetch")
    result = fetch.build_overlay_fc_cargo_map(
        plugin, [{"marketId": 101}], trigger="journal", allow_api_refresh=False, request_selection="build",
    )
    assert result == {}


@pytest.mark.parametrize("failure", ["lost_reply", "checkpoint"])
def test_replacement_coverage_survives_lost_reply_and_restart(session, monkeypatch, tmp_path, failure) -> None:
    """A POST containing an earlier copper deposit must not leave that deposit replayable after restart."""
    session.remote[101]["copper"] = 10
    session.dock(False)
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    request = plugin.api_client.session.request
    disk_unavailable = [False]
    replace = Path.replace

    def fail_checkpoint(path, target) -> Path:
        if disk_unavailable[0] and Path(target).name == "RavenColonial.carrier-cargo-recovery.json":
            raise OSError("checkpoint unavailable after remote commit")
        return replace(path, target)

    def fail_reply(method, url, **kwargs) -> requests.Response:
        if method == "PATCH":
            raise requests.ReadTimeout("unknown PATCH outcome")
        result = request(method, url, **kwargs)
        if failure == "lost_reply" and method == "POST" and url.endswith("/cargo"):
            raise requests.ReadTimeout("reply lost after commit")
        if failure == "checkpoint" and method == "POST" and url.endswith("/cargo"):
            disk_unavailable[0] = True
        return result

    monkeypatch.setattr(Path, "replace", fail_checkpoint)
    monkeypatch.setattr(plugin.api_client.session, "request", fail_reply)
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    plugin.fc_handler._supply_fc_async(101, {"copper": 2})
    drain(plugin)
    session.journal("Undocked")
    session.load.capi_fleetcarrier({
        "name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:41Z",
        "cargo": [{"commodity": "steel", "qty": 80}, {"commodity": "copper", "qty": 12}],
    })
    drain(plugin)
    assert session.remote[101] == {"steel": 80, "copper": 12}
    disk_unavailable[0] = False
    restored = session.load.RavencolonialPlugin()
    restored.configure_pending_carrier_deliveries(str(tmp_path))
    restored.api_client.session = SimpleNamespace(request=request, headers={})
    monkeypatch.setattr(restored, "_ensure_api_worker", lambda: None)
    for method in ("get_fc", "get_all_cmdr_fcs", "get_commander_projects"):
        monkeypatch.setattr(restored.api_client, method, getattr(plugin.api_client, method))
    session.load.this = restored
    session.load.journal_entry("Alpha", False, "Sol", "", {"event": "LoadGame"}, {})
    for thread in restored._fc_initialization_threads:
        thread.join(timeout=2)
    restored._apply_fc_initialization_results()
    drain(restored)
    assert session.remote[101] == {"steel": 80, "copper": 12}
    assert restored.pending_carrier_deliveries.records() == []


def test_full_snapshot_response_must_confirm_zero_withdrawal_before_retiring_it(session, monkeypatch) -> None:
    """A successful HTTP reply that still contains five steel cannot acknowledge a snapshot of zero."""
    session.remote[101] = {"steel": 5}
    session.dock(False)
    plugin = session.plugin

    def request(method, url, **kwargs) -> requests.Response:
        if method == "PATCH":
            raise requests.ReadTimeout("withdrawal outcome unknown")
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"steel":5}'
        return response

    monkeypatch.setattr(plugin.api_client.session, "request", request)
    plugin.fc_handler._supply_fc_async(101, {"steel": -5})
    drain(plugin)
    session.journal("Undocked")
    session.load.capi_fleetcarrier({
        "name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:41Z", "cargo": [],
    })
    drain(plugin)
    record, = plugin.pending_carrier_deliveries.records()
    assert record["cargo"] == {"steel": -5}


def test_new_commanders_snapshot_covers_earlier_deferred_movement(session, monkeypatch) -> None:
    """Bravo's physical snapshot includes Alpha's earlier deposit even while Alpha's links are delayed."""
    plugin = session.plugin
    profiles = plugin.api_client.get_all_cmdr_fcs
    release, started = threading.Event(), threading.Event()

    def delayed(name) -> list:
        if name == "Alpha":
            started.set()
            assert release.wait(timeout=2)
        return profiles(name)

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", delayed)
    alpha = None
    try:
        state = {"StationType": "FleetCarrier", "MarketID": 101, "ShipType": "python"}
        session.load.journal_entry("Alpha", False, "Sol", "101", {"event": "LoadGame"}, state)
        assert started.wait(timeout=2)
        alpha = plugin.fc_handler
        session.load.journal_entry("Alpha", False, "Sol", "101", {
            "event": "CargoTransfer", "Transfers": [{"Type": "steel", "Count": 5, "Direction": "tocarrier"}],
        }, state)
        session.load.journal_entry("Bravo", False, "Sol", "", {"event": "LoadGame"}, {})
        settle_commander_links(plugin)
        session.load.capi_fleetcarrier({
            "name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:41Z",
            "cargo": [{"commodity": "steel", "qty": 80}],
        })
        drain(plugin)
        assert session.remote[101] == {"steel": 80}
    finally:
        release.set()
        if alpha is not None:
            alpha.initialization_thread.join(timeout=2)
    plugin._apply_fc_initialization_results()
    drain(plugin)
    assert session.remote[101] == {"steel": 80}
    assert plugin.pending_carrier_deliveries.records() == []


def test_baseline_snapshot_handoff_cannot_overwrite_a_new_delta(session, monkeypatch) -> None:
    """A movement arriving while a deferred snapshot enters the queue survives exactly once."""
    plugin = session.plugin
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda name: [])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda name: [
        {"linkedFC": [{"marketId": 101, "name": "101"}]},
    ])
    session.journal("Location", Docked=True, StationType="FleetCarrier", MarketID=101, StationName="101")
    session.journal("Undocked")
    session.load.capi_fleetcarrier({
        "name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:41Z",
        "cargo": [{"commodity": "steel", "qty": 80}],
    })
    enqueue = plugin.queue_api_call
    injected = []

    def queue_call(function, *args, **kwargs) -> None:
        if function.__name__ == "_update_fc_cargo" and not injected:
            injected.append(True)
            plugin.fc_handler._supply_fc_async(101, {"steel": 2})
        enqueue(function, *args, **kwargs)

    monkeypatch.setattr(plugin, "queue_api_call", queue_call)
    drain(plugin)
    assert session.remote[101] == {"steel": 82}
    assert plugin.pending_carrier_deliveries.records() == []


def test_full_snapshot_without_movements_can_resume_after_failed_post(session, monkeypatch) -> None:
    """A failed initial seed remains recoverable even when its local cache already shows the target."""
    session.dock(False)
    session.journal("Undocked")
    plugin = session.plugin
    request = plugin.api_client.session.request

    def fail(*args, **kwargs) -> requests.Response:
        response = requests.Response()
        response.status_code = 503
        response._content = b'{}'
        return response

    data = {"name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:41Z",
            "cargo": [{"commodity": "steel", "qty": 80}]}
    monkeypatch.setattr(plugin.api_client.session, "request", fail)
    session.load.capi_fleetcarrier(data)
    drain(plugin)
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    session.load.capi_fleetcarrier(data)
    drain(plugin)
    assert session.remote[101] == {"steel": 80}
    assert plugin.pending_carrier_deliveries.replacements() == []


def test_snapshot_checkpoint_failure_prevents_any_absolute_write(session, monkeypatch, tmp_path) -> None:
    """A replacement cannot leave covered movements replayable if its pre-HTTP checkpoint fails."""
    session.dock(False)
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    session.journal("Undocked")
    writes = []
    request = plugin.api_client.session.request

    def unavailable(path, target) -> None:
        raise OSError("no durable snapshot evidence")

    def record_request(method, url, **kwargs) -> requests.Response:
        writes.append(method)
        return request(method, url, **kwargs)

    monkeypatch.setattr(Path, "replace", unavailable)
    monkeypatch.setattr(plugin.api_client.session, "request", record_request)
    session.load.capi_fleetcarrier({
        "name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:41Z",
        "cargo": [{"commodity": "steel", "qty": 80}],
    })
    drain(plugin)
    assert writes == []
    assert session.remote[101] == {"steel": 75}


def test_overlay_refresh_can_process_another_movement_during_baseline_completion(session, monkeypatch) -> None:
    """A refresh waiting on UI dispatch cannot hold the cargo lock needed by that UI's next movement."""
    plugin = session.plugin
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda name: [])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda name: [
        {"linkedFC": [{"marketId": 101, "name": "101"}]},
    ])
    session.journal("Location", Docked=True, StationType="FleetCarrier", MarketID=101, StationName="101")
    session.journal("CargoTransfer", 45,
                    Transfers=[{"Type": "steel", "Count": 5, "Direction": "tocarrier"}])
    plugin.overlay_carrier_tracking_enabled = True
    ui_threads = []

    def refresh() -> None:
        if ui_threads or plugin.fc_handler.linked_fcs[101]["cargo"].get("steel") != 80:
            return
        ui = threading.Thread(target=lambda: plugin.fc_handler._supply_fc_async(101, {"steel": 2}))
        ui_threads.append(ui)
        ui.start()
        ui.join(timeout=2)
        assert not ui.is_alive(), "UI cannot process a cargo event while the API worker waits for its refresh"

    monkeypatch.setattr(plugin, "refresh_build_overlay", refresh)
    try:
        drain(plugin)
    finally:
        for ui in ui_threads:
            ui.join(timeout=2)
    assert session.remote[101] == {"steel": 82}


def test_snapshot_handoff_orders_another_commanders_concurrent_movement(session, monkeypatch) -> None:
    """A retired handler's snapshot enters the shared queue before a newer commander's transfer."""
    plugin = session.plugin
    profiles = plugin.api_client.get_all_cmdr_fcs
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda name: [] if name == "Alpha" else profiles(name))
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda name: [
        {"linkedFC": [{"marketId": 101, "name": "101"}]},
    ])
    session.journal("Location", Docked=True, StationType="FleetCarrier", MarketID=101, StationName="101")
    session.journal("Undocked")
    alpha = plugin.fc_handler
    session.load.capi_fleetcarrier({
        "name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:41Z",
        "cargo": [{"commodity": "steel", "qty": 80}],
    })
    session.load.journal_entry("Bravo", False, "Sol", "101", {"event": "LoadGame"}, {
        "StationType": "FleetCarrier", "MarketID": 101,
    })
    settle_commander_links(plugin)
    entered, release = threading.Event(), threading.Event()
    enqueue = plugin.queue_api_call

    def queue_call(function, *args, **kwargs) -> None:
        if function.__name__ == "_update_fc_cargo" and function.__self__ is alpha:
            entered.set()
            assert release.wait(timeout=2)
        enqueue(function, *args, **kwargs)

    monkeypatch.setattr(plugin, "queue_api_call", queue_call)
    worker = threading.Thread(target=lambda: drain(plugin))
    ui = threading.Thread(target=lambda: plugin.fc_handler._supply_fc_async(101, {"steel": 2}))
    try:
        worker.start()
        assert entered.wait(timeout=2)
        ui.start()
        ui.join(timeout=0.1)
    finally:
        release.set()
        worker.join(timeout=2)
        if ui.ident is not None:
            ui.join(timeout=2)
    assert not worker.is_alive() and not ui.is_alive()
    drain(plugin)
    assert session.remote[101] == {"steel": 82}
    assert plugin.pending_carrier_deliveries.records() == []


@pytest.mark.parametrize("with_snapshot, expected", [(False, 77), (True, 82)])
def test_other_commander_waits_through_the_entire_pending_baseline(
    session, monkeypatch, with_snapshot, expected,
) -> None:
    """Bravo's transfer remains ordered even before Alpha's baseline completion starts."""
    plugin = session.plugin
    profiles = plugin.api_client.get_all_cmdr_fcs
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda name: [] if name == "Alpha" else profiles(name))
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda name: [
        {"linkedFC": [{"marketId": 101, "name": "101"}]},
    ])
    session.journal("Location", Docked=True, StationType="FleetCarrier", MarketID=101, StationName="101")
    session.journal("Undocked")
    if with_snapshot:
        session.load.capi_fleetcarrier({
            "name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:41Z",
            "cargo": [{"commodity": "steel", "qty": 80}],
        })
    session.load.journal_entry("Bravo", False, "Sol", "101", {"event": "LoadGame"}, {
        "StationType": "FleetCarrier", "MarketID": 101,
    })
    settle_commander_links(plugin)
    plugin.fc_handler._supply_fc_async(101, {"steel": 2})
    drain(plugin)
    assert session.remote[101] == {"steel": expected}
    assert plugin.fc_handler.linked_fcs[101]["cargo"] == {"steel": expected}
    assert plugin.pending_carrier_deliveries.records() == []


def test_snapshot_rejects_unknown_positive_response_keys_and_can_repair_them(session, monkeypatch) -> None:
    """Failed key discovery cannot turn an empty physical snapshot into a confirmed copper balance."""
    session.dock(False)
    session.remote[101]["copper"] = 10
    session.journal("Undocked")
    plugin = session.plugin
    get_fc = plugin.api_client.get_fc
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: None)
    data = {"name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:41Z", "cargo": []}
    session.load.capi_fleetcarrier(data)
    drain(plugin)
    assert session.remote[101] == {"copper": 10}
    replacement, = plugin.pending_carrier_deliveries.replacements()
    assert replacement["cargo"] == {"steel": 0}
    monkeypatch.setattr(plugin.api_client, "get_fc", get_fc)
    session.load.capi_fleetcarrier(data)
    drain(plugin)
    assert session.remote[101] == {}
    assert plugin.pending_carrier_deliveries.replacements() == []


@pytest.mark.parametrize("manifest", [None, "missing"])
def test_metadata_only_overlay_reply_preserves_known_stock(session, monkeypatch, manifest) -> None:
    """Missing/null cargo is not an observed empty manifest, even after a successful GET."""
    session.dock(False)
    plugin = session.plugin
    response = {"marketId": 101, "name": "101"}
    if manifest is None:
        response["cargo"] = None
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: response)
    fetch = importlib.import_module(f"{session.load.__package__}.ui.overlay_fc_cargo_fetch")
    cargo, _, _ = fetch.fetch_fc_cargo_from_api(
        mid=101, trigger="manual_fc_manifest_refresh", handler=plugin.fc_handler, client=plugin.api_client,
    )
    assert cargo == {"steel": 75}
    assert plugin.fc_handler.linked_fcs[101]["cargo"] == {"steel": 75}


def test_fresh_overlay_read_can_advance_acknowledged_stock(session, monkeypatch) -> None:
    """A read started after an acknowledged write can establish a newer remote baseline."""
    session.dock(False)
    plugin = session.plugin
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    session.remote[101] = {"steel": 90}
    fetch = importlib.import_module(f"{session.load.__package__}.ui.overlay_fc_cargo_fetch")
    cargo, _, _ = fetch.fetch_fc_cargo_from_api(
        mid=101, trigger="manual_fc_manifest_refresh", handler=plugin.fc_handler, client=plugin.api_client,
    )
    assert cargo == {"steel": 90}
    request = plugin.api_client.session.request

    def fail_patch(method, url, **kwargs) -> requests.Response:
        if method == "PATCH":
            response = requests.Response()
            response.status_code = 503
            response._content = b'{}'
            return response
        return request(method, url, **kwargs)

    monkeypatch.setattr(plugin.api_client.session, "request", fail_patch)
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    plugin.fc_handler.retry_pending_deliveries()
    assert session.remote[101] == {"steel": 90}
    record, = plugin.pending_carrier_deliveries.records("Alpha", 101)
    assert record["before"] == {"steel": 90}
    assert record["uncertain"] is True


@pytest.mark.parametrize("later_activity", ["signed", "read"])
def test_manual_acknowledgement_precedes_delayed_ui_and_cannot_downgrade_later_stock(
    session, monkeypatch, later_activity,
) -> None:
    """Manual UI completion cannot downgrade a later write or invalidate a fresh read already in flight."""
    session.dock(False)
    plugin = session.plugin
    module = importlib.import_module(f"{session.load.__package__}.ui.fc_manifest_editor")
    editor = module.FleetCarrierManifestEditor(plugin)
    editor._fc_records = {101: {"marketId": 101, "cargo": {"steel": 75}}}
    editor._select_market(101)
    editor._amount_vars = {"steel": SimpleNamespace(get=lambda: "100")}
    workers, callbacks = [], []
    monkeypatch.setattr(editor, "_schedule_on_main", callbacks.append)
    monkeypatch.setattr(module.threading, "Thread", lambda target, **kwargs: SimpleNamespace(
        start=lambda: workers.append(target),
    ))
    editor._on_save()
    workers.pop()()
    assert session.remote[101] == {"steel": 100}
    if later_activity == "signed":
        plugin.fc_handler._supply_fc_async(101, {"steel": 5})
        drain(plugin)
        callbacks.pop()()
    else:
        session.remote[101] = {"steel": 110}

        def fresh_read(mid) -> dict:
            snapshot = dict(session.remote[mid])
            callbacks.pop()()
            return {"marketId": mid, "cargo": snapshot}

        monkeypatch.setattr(plugin.api_client, "get_fc", fresh_read)
        fetch = importlib.import_module(f"{session.load.__package__}.ui.overlay_fc_cargo_fetch")
        cargo, _, _ = fetch.fetch_fc_cargo_from_api(
            mid=101, trigger="manual_fc_manifest_refresh", handler=plugin.fc_handler, client=plugin.api_client,
        )
        assert cargo == {"steel": 110}
        monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {
            "marketId": mid, "cargo": dict(session.remote[mid]),
        })
    assert session.remote[101] == {"steel": 105 if later_activity == "signed" else 110}
    assert plugin.fc_handler.linked_fcs[101]["cargo"] == {"steel": 105 if later_activity == "signed" else 110}
    request = plugin.api_client.session.request

    def fail_patch(method, url, **kwargs) -> requests.Response:
        if method == "PATCH":
            response = requests.Response()
            response.status_code = 503
            response._content = b'{}'
            return response
        return request(method, url, **kwargs)

    monkeypatch.setattr(plugin.api_client.session, "request", fail_patch)
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    plugin.fc_handler.retry_pending_deliveries()
    record, = plugin.pending_carrier_deliveries.records("Alpha", 101)
    assert record["cargo"] == {"steel": 5}
    assert record["before"] == {"steel": 105 if later_activity == "signed" else 110}
    assert record["uncertain"] is True


def test_vehicle_events_reject_srv_transfers_with_mothership_ship_type(session) -> None:
    """EDMC retains ShipType while driving, so LaunchSRV must guard the transfer."""
    session.dock(True)
    session.journal("LaunchSRV")
    session.journal("CargoTransfer", 51, Transfers=[{"Type": "steel", "Count": 1, "Direction": "toship"}])
    session.journal("Cargo", 1, Vessel="SRV", Count=1, Inventory=[{"Name": "steel", "Count": 1}])
    drain(session.plugin)
    assert session.remote[101] == {"steel": 75}
    assert session.writes == []


def test_dashboard_vehicle_guard_cannot_leak_between_commanders(session) -> None:
    """An old commander's dashboard cannot disable the current commander's ship transfers."""
    session.dock(True)
    session.load.dashboard_entry("Bravo", False, {"Flags": 67108864})
    session.journal("CargoTransfer", 45, Transfers=[{"Type": "steel", "Count": 5, "Direction": "tocarrier"}])
    drain(session.plugin)
    assert session.remote[101] == {"steel": 80}
    session.load.dashboard_entry("Alpha", False, {"Flags": 67108864})
    session.journal("CargoTransfer", 50, Transfers=[{"Type": "steel", "Count": 5, "Direction": "toship"}])
    drain(session.plugin)
    assert session.remote[101] == {"steel": 80}


@pytest.mark.parametrize("bank_first", [False, True])
def test_mixed_snapshot_only_bank_and_market_movement_counts_once(session, bank_first) -> None:
    """A five-tonne purchase and ten-tonne bank deposit are distinct in either order."""
    session.dock(True)
    if bank_first:
        session.journal("Cargo", 40, Vessel="Ship", Count=40, Inventory=[{"Name": "steel", "Count": 40}])
        session.journal("MarketBuy", 45, MarketID=101, Type="steel", Count=5)
    else:
        session.journal("MarketBuy", 55, MarketID=101, Type="steel", Count=5)
    session.journal("Cargo", 45, Vessel="Ship", Count=45, Inventory=[{"Name": "steel", "Count": 45}])
    session.journal("Cargo", 45, Vessel="Ship", Count=45)
    drain(session.plugin)
    assert session.remote[101] == {"steel": 80}


def test_snapshot_can_report_a_known_empty_hold(session) -> None:
    """Depositing the last fifty tonnes is a real bank movement rather than an unknown hold."""
    session.dock(True)
    session.journal("Cargo", 0, Vessel="Ship", Count=0)
    session.journal("Cargo", 0, Vessel="Ship", Count=0)
    drain(session.plugin)
    assert session.remote[101] == {"steel": 125}
    assert session.writes == [(101, {"steel": 50})]


def test_foreign_market_and_nonbank_cargo_cannot_become_bank_deliveries(session) -> None:
    """Rejected trades and known ship-only changes are excluded from the next bank snapshot."""
    session.dock(True)
    session.journal("MarketBuy", 55, MarketID=303, Type="steel", Count=5)
    session.journal("EjectCargo", 53, Type="steel", Count=2)
    session.journal("Cargo", 53, Vessel="Ship", Count=53, Inventory=[{"Name": "steel", "Count": 53}])
    drain(session.plugin)
    assert session.remote == {101: {"steel": 75}, 303: {"steel": 90}}
    assert session.writes == []


def test_lost_acknowledgement_is_recognized_without_another_patch(session, monkeypatch, tmp_path) -> None:
    """Recovery recognizes the applied 75-to-80 change and releases the next +2 once."""
    session.dock(True)
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    original_request = plugin.api_client.session.request

    def lose_reply(method, url, **kwargs) -> requests.Response:
        response = original_request(method, url, **kwargs)
        if method == "PATCH":
            raise requests.ReadTimeout("reply lost after commit")
        return response

    monkeypatch.setattr(plugin.api_client.session, "request", lose_reply)
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    plugin.fc_handler._supply_fc_async(101, {"steel": 2})
    drain(plugin)
    assert session.remote[101] == {"steel": 80}
    assert session.writes == [(101, {"steel": 5})]
    monkeypatch.setattr(plugin.api_client.session, "request", original_request)
    plugin.fc_handler.retry_pending_deliveries()
    assert session.remote[101] == {"steel": 82}
    assert session.writes == [(101, {"steel": 5}), (101, {"steel": 2})]
    assert plugin.pending_carrier_deliveries.records() == []


def test_uncertain_unchanged_write_blocks_only_its_carrier(session, monkeypatch, tmp_path) -> None:
    """Unchanged Raven stock cannot prove a timeout safe to replay, while another carrier can progress."""
    session.dock(True)
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    original_request = plugin.api_client.session.request

    def timeout(method, url, **kwargs) -> requests.Response:
        if method == "PATCH" and "/101/" in url:
            raise requests.ReadTimeout("unknown server outcome")
        return original_request(method, url, **kwargs)

    monkeypatch.setattr(plugin.api_client.session, "request", timeout)
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    plugin.fc_handler._supply_fc_async(101, {"steel": 2})
    plugin.fc_handler._supply_fc_async(303, {"steel": 3})
    drain(plugin)
    monkeypatch.setattr(plugin.api_client.session, "request", original_request)
    plugin.fc_handler.retry_pending_deliveries()
    assert session.remote == {101: {"steel": 75}, 303: {"steel": 93}}
    assert session.writes == [(303, {"steel": 3})]
    assert [record["cargo"] for record in plugin.pending_carrier_deliveries.records()] == [
        {"steel": 5}, {"steel": 2},
    ]


@pytest.mark.parametrize("total", [80, 0])
def test_fresh_capi_reconciles_uncertain_writes_after_the_first_seed(session, monkeypatch, tmp_path, total) -> None:
    """A newer full manifest, including an empty one, resolves retained writes after an earlier CAPI seed."""
    session.dock(True)
    session.journal("Undocked")
    session.load.capi_fleetcarrier({
        "name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:39Z",
        "cargo": [{"commodity": "steel", "qty": 75}],
    })
    session.dock(True)
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    request = plugin.api_client.session.request

    def timeout(*args, **kwargs) -> None:
        raise requests.ReadTimeout("server outcome unknown")

    monkeypatch.setattr(plugin.api_client.session, "request", timeout)
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    session.journal("Undocked")
    session.load.capi_fleetcarrier({
        "name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:41Z",
        "cargo": [{"commodity": "steel", "qty": total}] if total else [],
    })
    drain(plugin)
    assert session.remote[101] == ({"steel": 80} if total else {})
    assert plugin.pending_carrier_deliveries.records() == []
    assert session.writes == []


def test_stale_capi_cannot_retire_an_uncertain_movement(session, monkeypatch, tmp_path) -> None:
    """A Raven refresh cannot let CAPI predating the retained local movement acknowledge it."""
    session.dock(True)
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    request = plugin.api_client.session.request

    def timeout(*args, **kwargs) -> None:
        raise requests.ReadTimeout("server outcome unknown")

    monkeypatch.setattr(plugin.api_client.session, "request", timeout)
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    session.journal("Undocked")
    plugin.fc_handler.replace_fc_cargo_manifest(101, {"steel": 75}, source="raven_colonial_api")
    session.load.capi_fleetcarrier({
        "name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:39Z",
        "cargo": [{"commodity": "steel", "qty": 70}],
    })
    drain(plugin)
    assert session.remote[101] == {"steel": 75}
    assert [record["cargo"] for record in plugin.pending_carrier_deliveries.records()] == [{"steel": 5}]


def test_definitely_rejected_write_retries_only_after_checking_remote_stock(session, monkeypatch, tmp_path) -> None:
    """An explicit 403 can be replayed once credentials recover and Raven still has the before-state."""
    session.dock(True)
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    original_request = plugin.api_client.session.request

    def reject(*args, **kwargs) -> requests.Response:
        response = requests.Response()
        response.status_code = 403
        response._content = b'{}'
        return response

    monkeypatch.setattr(plugin.api_client.session, "request", reject)
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    monkeypatch.setattr(plugin.api_client.session, "request", original_request)
    plugin.fc_handler.retry_pending_deliveries()
    assert session.remote[101] == {"steel": 80}
    assert session.writes == [(101, {"steel": 5})]
    assert plugin.pending_carrier_deliveries.records() == []


def test_uncertain_write_with_concurrent_remote_changes_stays_retained(session, monkeypatch, tmp_path) -> None:
    """Neither the before-state nor expected after-state matches another commander's concurrent update."""
    session.dock(True)
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    original_request = plugin.api_client.session.request

    def timeout(*args, **kwargs) -> None:
        raise requests.ReadTimeout("server outcome unknown")

    monkeypatch.setattr(plugin.api_client.session, "request", timeout)
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    session.remote[101] = {"steel": 77}
    monkeypatch.setattr(plugin.api_client.session, "request", original_request)
    plugin.fc_handler.retry_pending_deliveries()
    assert session.remote[101] == {"steel": 77}
    assert session.writes == []
    assert [record["cargo"] for record in plugin.pending_carrier_deliveries.records()] == [{"steel": 5}]


@pytest.mark.parametrize("committed", [False, True])
def test_restart_recognizes_a_committed_write_without_replaying_it(session, monkeypatch, tmp_path, committed) -> None:
    """Restart preserves old-owner uncertainty and releases dependent cargo only after an applied result."""
    session.dock(True)
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    request = plugin.api_client.session.request

    def lose_reply(method, url, **kwargs) -> requests.Response:
        if method == "PATCH" and not committed:
            raise requests.ReadTimeout("outcome unknown before acknowledgement")
        result = request(method, url, **kwargs)
        if method == "PATCH":
            raise requests.ReadTimeout("lost reply after commit")
        return result

    monkeypatch.setattr(plugin.api_client.session, "request", lose_reply)
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    plugin.fc_handler._supply_fc_async(101, {"steel": 2})
    drain(plugin)
    restored = session.load.RavencolonialPlugin()
    restored.configure_pending_carrier_deliveries(str(tmp_path))
    restored.api_client.session = SimpleNamespace(request=request, headers={})
    monkeypatch.setattr(restored, "_ensure_api_worker", lambda: None)
    monkeypatch.setattr(restored.api_client, "get_all_cmdr_fcs", plugin.api_client.get_all_cmdr_fcs)
    monkeypatch.setattr(restored.api_client, "get_commander_projects", plugin.api_client.get_commander_projects)
    monkeypatch.setattr(restored.api_client, "get_fc", plugin.api_client.get_fc)
    session.load.this = restored
    session.load.journal_entry("Bravo", False, "Sol", "", {"event": "LoadGame"}, {})
    for thread in restored._fc_initialization_threads:
        thread.join(timeout=2)
    restored._apply_fc_initialization_results()
    drain(restored)
    assert session.remote[101] == {"steel": 82 if committed else 75}
    assert session.writes == ([(101, {"steel": 5}), (101, {"steel": 2})] if committed else [])
    assert [record["cargo"] for record in restored.pending_carrier_deliveries.records()] == (
        [] if committed else [{"steel": 5}, {"steel": 2}]
    )


def test_failed_full_manifest_keeps_evidence_until_replacement_succeeds(session, monkeypatch, tmp_path) -> None:
    """A failed recovery POST cannot discard cargo evidence or prevent the next fresh CAPI attempt."""
    session.dock(True)
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    request = plugin.api_client.session.request

    def fail(*args, **kwargs) -> requests.Response:
        response = requests.Response()
        response.status_code = 503
        response._content = b'{}'
        return response

    monkeypatch.setattr(plugin.api_client.session, "request", fail)
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    session.journal("Undocked")
    data = {"name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:41Z",
            "cargo": [{"commodity": "steel", "qty": 80}]}
    session.load.capi_fleetcarrier(data)
    drain(plugin)
    assert [record["cargo"] for record in plugin.pending_carrier_deliveries.records()] == [{"steel": 5}]
    assert session.remote[101] == {"steel": 75}
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    session.load.capi_fleetcarrier(data)
    drain(plugin)
    assert session.remote[101] == {"steel": 80}
    assert plugin.pending_carrier_deliveries.records() == []


def test_full_manifest_and_transactions_waiting_for_dock_baseline_count_once(session, monkeypatch) -> None:
    """A full baseline covers earlier/later queued transfers even if their first PATCH is uncertain."""
    plugin = session.plugin
    request = plugin.api_client.session.request

    def reject_patch(method, url, **kwargs) -> requests.Response:
        if method == "PATCH":
            response = requests.Response()
            response.status_code = 503
            response._content = b'{}'
            return response
        return request(method, url, **kwargs)

    monkeypatch.setattr(plugin.api_client.session, "request", reject_patch)
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda name: [])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda name: [
        {"linkedFC": [{"marketId": 101, "name": "101"}]},
    ])
    session.journal("Location", Docked=True, StationType="FleetCarrier", MarketID=101,
                    StationName="101", StationServices=["squadronBank"])
    session.journal("CargoTransfer", 45,
                    Transfers=[{"Type": "steel", "Count": 5, "Direction": "tocarrier"}])
    session.journal("Undocked")
    session.load.capi_fleetcarrier({
        "name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:41Z",
        "cargo": [{"commodity": "steel", "qty": 80}],
    })
    session.journal("Docked", 45, StationType="FleetCarrier", MarketID=101,
                    StationName="101", StationServices=["squadronBank"])
    session.journal("CargoTransfer", 43,
                    Transfers=[{"Type": "steel", "Count": 2, "Direction": "tocarrier"}])
    drain(plugin)
    plugin.fc_handler.retry_pending_deliveries()
    assert session.remote[101] == {"steel": 82}
    assert plugin.pending_carrier_deliveries.records() == []


def test_recovery_read_failure_does_not_block_a_different_carrier(session, monkeypatch, tmp_path) -> None:
    """A failed reconciliation lookup is local to that market's retained transaction order."""
    session.dock(True)
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    request = plugin.api_client.session.request

    def timeout(*args, **kwargs) -> None:
        raise requests.ReadTimeout("unavailable")

    monkeypatch.setattr(plugin.api_client.session, "request", timeout)
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    plugin.pending_carrier_deliveries.record("Alpha", 303, {"steel": 3})
    monkeypatch.setattr(plugin.api_client, "get_fc", timeout)
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    plugin.fc_handler.retry_pending_deliveries()
    assert session.remote == {101: {"steel": 75}, 303: {"steel": 93}}
    assert session.writes == [(303, {"steel": 3})]
    assert [record["cargo"] for record in plugin.pending_carrier_deliveries.records()] == [{"steel": 5}]


def test_corrupt_recovery_file_is_preserved_and_cannot_issue_replayable_writes(session, tmp_path) -> None:
    """Unreadable persisted evidence blocks new PATCH attempts without crashing journal handling."""
    session.dock(True)
    path = tmp_path / "RavenColonial.carrier-cargo-recovery.json"
    path.write_text('{"version":1,"records":[{}]}')
    session.plugin.configure_pending_carrier_deliveries(str(tmp_path))
    session.journal("CargoTransfer", 45,
                    Transfers=[{"Type": "steel", "Count": 5, "Direction": "tocarrier"}])
    drain(session.plugin)
    assert session.writes == []
    assert session.remote[101] == {"steel": 75}
    assert path.read_text() == '{"version":1,"records":[{}]}'


def test_legacy_mirror_failure_cannot_undo_an_authoritative_transaction(session, monkeypatch, tmp_path) -> None:
    """The committed primary checkpoint governs sends and restart even when its compatibility mirror fails."""
    session.dock(True)
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    replace = Path.replace

    def fail_legacy(path, target) -> Path:
        if Path(target).name == "RavenColonial.pending-carrier-deliveries.json":
            raise OSError("legacy compatibility file unavailable")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_legacy)
    session.journal("CargoTransfer", 45,
                    Transfers=[{"Type": "steel", "Count": 5, "Direction": "tocarrier"}])
    drain(plugin)
    restored = session.load.PendingCarrierDeliveries()
    restored.configure(str(tmp_path))
    assert session.remote[101] == {"steel": 80}
    assert session.writes == [(101, {"steel": 5})]
    assert plugin.pending_carrier_deliveries.records() == []
    assert restored.records() == []


@pytest.mark.parametrize("apply_links_after_write", [False, True])
def test_returning_commander_uses_the_latest_acknowledged_stock(session, monkeypatch, apply_links_after_write) -> None:
    """An earlier session's success cannot impersonate a later failed movement after Alpha-Bravo-Alpha."""
    session.dock(False)
    plugin = session.plugin
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    session.load.journal_entry("Bravo", False, "Sol", "", {"event": "LoadGame"}, {})
    settle_commander_links(plugin)
    release = threading.Event()
    started = threading.Event()
    profiles = plugin.api_client.get_all_cmdr_fcs

    def delayed_links(name) -> list:
        snapshot = profiles(name)
        if name == "Alpha" and apply_links_after_write:
            started.set()
            assert release.wait(timeout=2)
        return snapshot

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", delayed_links)
    try:
        session.load.journal_entry("Alpha", False, "Sol", "", {"event": "LoadGame"}, {})
        if apply_links_after_write:
            assert started.wait(timeout=2)
            drain(plugin)
        else:
            settle_commander_links(plugin)
            drain(plugin)
    finally:
        release.set()
    settle_commander_links(plugin)
    request = plugin.api_client.session.request

    def fail_patch(method, url, **kwargs) -> requests.Response:
        if method == "PATCH":
            response = requests.Response()
            response.status_code = 503
            response._content = b'{}'
            return response
        return request(method, url, **kwargs)

    monkeypatch.setattr(plugin.api_client.session, "request", fail_patch)
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    plugin.fc_handler.retry_pending_deliveries()
    assert session.remote[101] == {"steel": 80}
    assert session.writes == [(101, {"steel": 5})]
    record, = plugin.pending_carrier_deliveries.records("Alpha", 101)
    assert record["cargo"] == {"steel": 5}
    assert record["before"] == {"steel": 80}
    assert record["uncertain"] is True
