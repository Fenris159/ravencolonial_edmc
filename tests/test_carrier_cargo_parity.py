"""Behavior parity with SrvSurvey-XP e30d561's carrier cargo contracts."""

from copy import deepcopy
import json
from pathlib import Path
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
            remote[mid] = dict(kwargs["json"])
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
