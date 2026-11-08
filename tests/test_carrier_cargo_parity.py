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


def entry_value(amount) -> SimpleNamespace:
    """Model a mutable Tk variable at the UI boundary."""
    value = [str(amount)]
    return SimpleNamespace(get=lambda: value[0], set=lambda text: value.__setitem__(0, str(text)))


@pytest.fixture
def session(edmc_plugin, monkeypatch) -> SimpleNamespace:
    """Run the real journal and HTTP client against two isolated carrier manifests."""
    load, plugin = edmc_plugin
    remote = {101: {"steel": 75}, 303: {"steel": 90}}
    writes = []
    ship = {}
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
            ship.clear()
            ship.update(deepcopy(kwargs["json"].get("cargo") or {}))
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

    return SimpleNamespace(load=load, plugin=plugin, remote=remote, ship=ship,
                           writes=writes, journal=journal, dock=dock)


@pytest.fixture
def market_session(session) -> SimpleNamespace:
    """Provide enough ship identity for the real currentShip HTTP publication path."""
    session.journal("Loadout", 50, Ship="python", ShipName="Test ship", ShipIdent="TEST", CargoCapacity=50, Modules=[])
    return session


def write_market_cargo_file(session, monkeypatch, tmp_path, amount, **fields) -> None:
    """Write a game-style Cargo.json at the EDMC filesystem boundary."""
    monkeypatch.setattr(session.load.config, "default_journal_dir", str(tmp_path), raising=False)
    payload = {"event": "Cargo", "timestamp": "2026-11-08T17:00:02Z", "Vessel": "Ship", "Count": amount,
               "Inventory": [{"Name": "steel", "Count": amount}] if amount else []}
    payload.update(fields)
    (tmp_path / "Cargo.json").write_text(json.dumps(payload))


@pytest.mark.parametrize("event, count, after, cached, stock", [
    ("MarketSell", 50, 0, 0, 125), ("MarketSell", 20, 30, 10, 95), ("MarketBuy", 10, 60, 70, 65),
])
def test_read_ahead_inventory_does_not_double_a_market_trade(
    market_session, monkeypatch, tmp_path, event, count, after, cached, stock,
) -> None:
    """A sale already visible in Cargo.json changes carrier stock exactly once, including partial sales."""
    session = market_session
    session.dock(True)
    write_market_cargo_file(session, monkeypatch, tmp_path, after)
    session.journal("Cargo", after, timestamp="2026-11-08T17:00:02Z", Vessel="Ship", Count=after,
                    Inventory=[{"Name": "steel", "Count": after}] if after else [])
    drain(session.plugin)
    session.journal(event, cached, timestamp="2026-11-08T17:00:02Z", MarketID=101, Type="steel", Count=count)
    drain(session.plugin)
    assert session.remote[101] == {"steel": stock}
    assert session.ship == ({"steel": after} if after else {})


@pytest.mark.parametrize("squadron", [False, True])
@pytest.mark.parametrize("event, count, after, stock", [("MarketSell", 50, 0, 125), ("MarketBuy", 10, 60, 65)])
def test_market_trade_publishes_ship_cargo_without_waiting_for_an_inventory_event(
    market_session, squadron, event, count, after, stock,
) -> None:
    """Carrier trades update both physical stocks without requiring a later Cargo journal."""
    session = market_session
    session.dock(squadron)
    session.journal(event, after, MarketID=101, Type="steel", Count=count)
    drain(session.plugin)
    assert session.remote[101] == {"steel": stock}
    assert session.ship == ({"steel": after} if after else {})


def test_genuine_bank_deposit_and_same_second_market_sale_remain_distinct(
    market_session, monkeypatch, tmp_path,
) -> None:
    """A ten-tonne bank deposit followed by a separate five-tonne sale increases stock by fifteen."""
    session = market_session
    session.dock(True)
    session.journal("Cargo", 40, timestamp="2026-11-08T17:00:02Z", Vessel="Ship", Count=40,
                    Inventory=[{"Name": "steel", "Count": 40}])
    drain(session.plugin)
    write_market_cargo_file(session, monkeypatch, tmp_path, 35)
    session.journal("MarketSell", 35, timestamp="2026-11-08T17:00:02Z", MarketID=101, Type="steel", Count=5)
    drain(session.plugin)
    assert session.remote[101] == {"steel": 90}
    assert session.ship == {"steel": 35}


def test_late_inventory_does_not_undo_a_carrier_correction_after_a_read_ahead_sale(market_session) -> None:
    """Pending sale attribution cannot turn a corrected 125 back into 75 on the next empty snapshot."""
    session = market_session
    session.dock(True)
    session.journal("Cargo", 0, Vessel="Ship", Count=0, Inventory=[])
    session.journal("MarketSell", 0, MarketID=101, Type="steel", Count=50)
    drain(session.plugin)
    handler = session.plugin.fc_handler
    reservation = handler.prepare_manual_manifest(101, {"steel": 125})
    assert handler.save_manual_manifest(101, {"steel": 125}, reservation) == {"steel": 125}
    handler.finish_manual_manifest(reservation)
    session.journal("Cargo", 0, Vessel="Ship", Count=0, Inventory=[])
    drain(session.plugin)
    assert session.remote[101] == {"steel": 125}


@pytest.mark.parametrize("invalid", ["stale", "future", "srv", "malformed"])
def test_unrelated_or_unreadable_cargo_file_cannot_replace_the_current_market_hold(
    market_session, monkeypatch, tmp_path, invalid,
) -> None:
    """Only a valid main-ship snapshot matching this trade may override the event's EDMC state."""
    session = market_session
    session.dock(True)
    fields = {"stale": {"timestamp": "2026-11-08T17:00:01Z"},
              "future": {"timestamp": "2026-11-08T17:00:03Z"}, "srv": {"Vessel": "SRV"}, "malformed": {}}
    write_market_cargo_file(session, monkeypatch, tmp_path, 0, **fields[invalid])
    if invalid == "malformed":
        (tmp_path / "Cargo.json").write_text('{"Inventory":')
    session.journal("MarketSell", 30, timestamp="2026-11-08T17:00:02Z", MarketID=101, Type="steel", Count=20)
    drain(session.plugin)
    assert session.remote[101] == {"steel": 95}
    assert session.ship == {"steel": 30}


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


def start_squadron_session(session, cargo, event="StartUp") -> None:
    """Deliver startup state without assuming EDMC has loaded Cargo.json."""
    state = {"Docked": True, "StationType": "FleetCarrier", "MarketID": 101,
             "ShipType": "python", "StationServices": ["squadronBank"]}
    if cargo is not None:
        state["Cargo"] = cargo
    session.load.journal_entry("Alpha", False, "Sol", "101", {"event": event}, state)
    settle_commander_links(session.plugin)


@pytest.mark.parametrize("initial_cargo", [None, {}, {"steel": 1323}], ids=["missing", "unloaded", "loaded"])
def test_startup_inventory_cannot_cancel_a_real_squadron_deposit(session, initial_cargo) -> None:
    """Learning about 1323 already aboard the ship cannot subtract it before its real deposit."""
    session.remote[101] = {"steel": 1383}
    start_squadron_session(session, initial_cargo)
    session.journal("Cargo", 1323, Vessel="Ship", Count=1323, Inventory=[{"Name": "steel", "Count": 1323}])
    drain(session.plugin)
    assert session.remote[101] == {"steel": 1383}
    session.journal("CargoTransfer", 0, Transfers=[{"Type": "steel", "Count": 1323, "Direction": "tocarrier"}])
    session.journal("Cargo", 0, Vessel="Ship", Count=0, Inventory=[])
    drain(session.plugin)
    assert session.remote[101] == {"steel": 2706}
    assert session.writes == [(101, {"steel": 1323})]


@pytest.mark.parametrize("inventory", [None, []], ids=["missing-breakdown", "empty-breakdown"])
def test_sparse_startup_cargo_does_not_establish_an_empty_inventory(session, inventory) -> None:
    """A positive count without a breakdown cannot turn unloaded state into a zero baseline."""
    session.remote[101] = {"steel": 1383}
    start_squadron_session(session, {})
    fields = {} if inventory is None else {"Inventory": inventory}
    session.journal("Cargo", 0, Vessel="Ship", Count=1323, **fields)
    session.journal("Cargo", 1323, Vessel="Ship", Count=1323, Inventory=[{"Name": "steel", "Count": 1323}])
    drain(session.plugin)
    assert session.remote[101] == {"steel": 1383}
    session.journal("Cargo", 0, Vessel="Ship", Count=0, Inventory=[])
    drain(session.plugin)
    assert session.remote[101] == {"steel": 2706}


def test_confirmed_empty_inventory_survives_location_and_tracks_bank_movements(session) -> None:
    """A real zero Cargo snapshot permits the next withdrawal, even after Location repeats the empty state."""
    session.remote[101] = {"steel": 1383}
    start_squadron_session(session, {})
    session.journal("Cargo", 0, Vessel="Ship", Count=0)
    session.journal("Location", 0, Docked=True, StationType="FleetCarrier", MarketID=101,
                    StationName="101", StationServices=["squadronBank"])
    session.journal("Cargo", 10, Vessel="Ship", Count=10, Inventory=[{"Name": "steel", "Count": 10}])
    drain(session.plugin)
    assert session.remote[101] == {"steel": 1373}
    session.journal("Cargo", 0, Vessel="Ship", Count=0, Inventory=[])
    drain(session.plugin)
    assert session.remote[101] == {"steel": 1383}
    assert session.writes == [(101, {"steel": -10}), (101, {"steel": 10})]


def test_preloaded_nonempty_inventory_tracks_the_first_bank_movement(session) -> None:
    """An already populated EDMC hold remains a usable baseline before the first Cargo event."""
    start_squadron_session(session, {"steel": 10})
    session.journal("Cargo", 5, Vessel="Ship", Count=5, Inventory=[{"Name": "steel", "Count": 5}])
    drain(session.plugin)
    assert session.remote[101] == {"steel": 80}


def test_zero_cargo_snapshot_overrides_stale_nonempty_edmc_state(session) -> None:
    """A confirmed empty ship permits the next bank withdrawal even if cached EDMC cargo still has fifty."""
    session.dock(True)
    session.journal("Cargo", 50, Vessel="Ship", Count=0, Inventory=[])
    drain(session.plugin)
    assert session.remote[101] == {"steel": 125}
    session.journal("Cargo", 10, Vessel="Ship", Count=10, Inventory=[{"Name": "steel", "Count": 10}])
    drain(session.plugin)
    assert session.remote[101] == {"steel": 115}


def test_new_game_cannot_reuse_a_previous_sessions_confirmed_empty_inventory(session) -> None:
    """A new LoadGame must learn its inventory before inferring any bank movement."""
    start_squadron_session(session, {})
    session.journal("Cargo", 0, Vessel="Ship", Count=0, Inventory=[])
    start_squadron_session(session, {}, event="LoadGame")
    session.journal("Cargo", 10, Vessel="Ship", Count=10, Inventory=[{"Name": "steel", "Count": 10}])
    drain(session.plugin)
    assert session.remote[101] == {"steel": 75}
    session.journal("Cargo", 0, Vessel="Ship", Count=0)
    drain(session.plugin)
    assert session.remote[101] == {"steel": 85}


@pytest.mark.parametrize("direction, after, expected", [("tocarrier", 0, 95), ("toship", 25, 55)])
def test_explicit_transfer_before_initial_inventory_is_counted_once(session, direction, after, expected) -> None:
    """Partial EDMC state must not duplicate early transfers when the first complete inventory arrives."""
    start_squadron_session(session, {})
    for transfer_number in (1, 2):
        # The withdrawal state includes new cargo but not five tonnes already aboard before startup.
        cached_count = transfer_number * 10 if direction == "toship" else 0
        session.journal("CargoTransfer", cached_count,
                        Transfers=[{"Type": "steel", "Count": 10, "Direction": direction}])
    session.journal("Cargo", after, Vessel="Ship", Count=after,
                    Inventory=[{"Name": "steel", "Count": after}] if after else [])
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
    editor._amount_vars = {"steel": entry_value(100)}
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


@pytest.fixture
def editor_session(session, monkeypatch) -> SimpleNamespace:
    """Capture only the editor's worker and UI scheduling boundaries."""
    session.dock(False)
    module = importlib.import_module(f"{session.load.__package__}.ui.fc_manifest_editor")
    editor = module.FleetCarrierManifestEditor(session.plugin)
    session.plugin.fc_manifest_editor = editor
    editor._fc_records = {101: {"marketId": 101, "cargo": {"steel": 75}}}
    editor._select_market(101)
    editor._amount_vars = {"steel": entry_value(100)}
    workers, callbacks = [], []
    monkeypatch.setattr(editor, "_schedule_on_main", callbacks.append)
    monkeypatch.setattr(module.threading, "Thread", lambda target, **kwargs: SimpleNamespace(
        start=lambda: workers.append(target),
    ))
    return SimpleNamespace(editor=editor, workers=workers, callbacks=callbacks, **vars(session))


def test_returning_commander_cannot_reseed_stale_capi_over_completed_movement(session) -> None:
    """A completed deposit remains protected when Alpha returns to EDMC's still-running session."""
    session.dock(False)
    session.journal("Undocked")
    stale = {"name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:39Z",
             "cargo": [{"commodity": "steel", "qty": 75}]}
    session.load.capi_fleetcarrier(stale)
    session.plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(session.plugin)
    for name in ("Bravo", "Alpha"):
        session.load.journal_entry(name, False, "Sol", "", {"event": "LoadGame"}, {})
        settle_commander_links(session.plugin)
    session.load.capi_fleetcarrier(stale)
    drain(session.plugin)
    assert session.remote[101] == {"steel": 80}


def test_manual_correction_resolves_existing_full_write_barrier(editor_session, monkeypatch, tmp_path) -> None:
    """Correcting an uncertain absolute 80 to 100 cannot strand the next +2 movement."""
    session = editor_session
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    request = plugin.api_client.session.request

    def lose_reply(method, url, **kwargs):
        result = request(method, url, **kwargs)
        if method == "POST" and url.endswith("/cargo"):
            raise requests.ReadTimeout("absolute result committed, reply lost")
        return result

    monkeypatch.setattr(plugin.api_client.session, "request", lose_reply)
    plugin.fc_handler._update_fc_cargo_async(101, {"steel": 80})
    drain(plugin)
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    session.editor._on_save()
    session.workers.pop()()
    session.callbacks.pop()()
    plugin.fc_handler._supply_fc_async(101, {"steel": 2})
    drain(plugin)
    assert session.remote[101] == {"steel": 102}
    restored = session.load.PendingCarrierDeliveries()
    restored.configure(str(tmp_path))
    assert restored.records() == []
    assert restored.replacements() == []


def test_deferred_editor_record_cannot_erase_a_later_deposit(editor_session) -> None:
    """The next edit retains an acknowledged +5 even when its predecessor's UI callback was delayed."""
    session = editor_session
    editor = session.editor
    editor._on_save()
    session.workers.pop()()
    session.plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(session.plugin)
    session.callbacks.pop()()
    assert editor._fc_records[101]["cargo"] == {"steel": 105}
    editor._select_market(101)
    editor._amount_vars = {"steel": SimpleNamespace(get=lambda: "105"), "copper": SimpleNamespace(get=lambda: "2")}
    editor._on_save()
    session.workers.pop()()
    session.callbacks.pop()()
    assert session.remote[101] == {"steel": 105, "copper": 2}


@pytest.mark.parametrize("event, after", [("BuyDrones", 30), ("SellDrones", 10)])
def test_limpet_service_trade_is_not_a_squadron_bank_transfer(session, event, after) -> None:
    """Buying or selling ten maintenance limpets cannot change bank drone stock."""
    session.dock(True)
    session.remote[101]["drones"] = 50
    session.plugin.fc_handler.ship_cargo_tracker.reset({"steel": 50, "drones": 20})
    session.journal(event, Count=10)
    session.journal("Cargo", Vessel="Ship", Count=50 + after,
                    Inventory=[{"Name": "steel", "Count": 50}, {"Name": "drones", "Count": after}])
    drain(session.plugin)
    assert session.remote[101] == {"steel": 75, "drones": 50}
    assert session.writes == []


def test_commander_switch_invalidates_the_old_write_capable_editor(editor_session, monkeypatch) -> None:
    """Bravo cannot submit the Alpha editor's selected carrier or inherit it through a save acknowledgement."""
    session = editor_session
    plugin, editor = session.plugin, session.editor
    plugin.fc_manifest_editor = editor
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda name: [
        {"marketId": 303, "name": "303", "cargo": {"steel": 90}},
    ])
    session.load.journal_entry("Bravo", False, "Sol", "", {"event": "LoadGame"}, {})
    settle_commander_links(plugin)
    editor._on_save()
    for worker in session.workers:
        worker()
    for callback in session.callbacks:
        callback()
    assert session.remote[101] == {"steel": 75}
    assert set(plugin.fc_handler.linked_fcs) == {303}
    assert editor._selected_market_id is None
    assert editor._fc_records == {}


def test_accepted_read_and_handler_publication_cannot_straddle_a_new_write(session, monkeypatch) -> None:
    """An accepted 75 read cannot resume after a 90 acknowledgement and overwrite the visible manifest."""
    session.dock(False)
    plugin = session.plugin
    handler = plugin.fc_handler
    store = plugin.pending_carrier_deliveries
    revision = handler.cargo_read_revision()
    remember = store.remember_cargo
    entered, release = threading.Event(), threading.Event()

    def observe(mid, cargo, **kwargs):
        result = remember(mid, cargo, **kwargs)
        if cargo == {"steel": 75} and not kwargs.get("written"):
            entered.set()
            assert release.wait(timeout=2)
        return result

    monkeypatch.setattr(store, "remember_cargo", observe)
    reader = threading.Thread(target=lambda: handler.replace_fc_cargo_manifest(
        101, {"steel": 75}, source="raven_colonial_api", read_revision=revision,
    ))
    writer = threading.Thread(target=lambda: handler.replace_fc_cargo_manifest(
        101, {"steel": 90}, source="raven_colonial_api", written=True,
    ))
    try:
        reader.start()
        assert entered.wait(timeout=2)
        writer.start()
        writer.join(timeout=0.1)
    finally:
        release.set()
        reader.join(timeout=2)
        if writer.ident is not None:
            writer.join(timeout=2)
    assert not reader.is_alive() and not writer.is_alive()
    assert handler.linked_fcs[101]["cargo"] == {"steel": 90}


def test_full_snapshot_recovers_after_its_pre_http_checkpoint_becomes_writable(session, monkeypatch, tmp_path) -> None:
    """A transient storage failure cannot permanently consume the only initial CAPI seed."""
    session.dock(False)
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    session.journal("Undocked")
    replace = Path.replace

    def unavailable(path, target):
        raise OSError("temporary checkpoint failure")

    monkeypatch.setattr(Path, "replace", unavailable)
    data = {"name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:41Z",
            "cargo": [{"commodity": "steel", "qty": 80}]}
    session.load.capi_fleetcarrier(data)
    drain(plugin)
    assert session.remote[101] == {"steel": 75}
    monkeypatch.setattr(Path, "replace", replace)
    plugin.fc_handler.retry_pending_deliveries()
    session.load.capi_fleetcarrier(data)
    drain(plugin)
    assert session.remote[101] == {"steel": 80}
    assert plugin.pending_carrier_deliveries.replacements() == []


@pytest.mark.parametrize("failure", ["dns", "refused", "ambiguous"])
def test_proven_connection_establishment_failures_resume_but_ambiguous_errors_do_not(
    session, monkeypatch, failure,
) -> None:
    """Only structured urllib3 proof that no connection was established permits replay."""
    import socket
    import urllib3

    session.dock(False)
    plugin = session.plugin
    request = plugin.api_client.session.request
    connection = urllib3.connection.HTTPSConnection("carrier.test")
    reasons = {
        "dns": urllib3.exceptions.NameResolutionError("carrier.test", connection, socket.gaierror(-2, "no DNS")),
        "refused": urllib3.exceptions.NewConnectionError(connection, "connection refused"),
    }
    error = requests.ConnectionError("reply may have been lost")
    if failure in reasons:
        error = requests.ConnectionError(urllib3.exceptions.MaxRetryError(None, "/cargo", reasons[failure]))

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(plugin.api_client.session, "request", fail)
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    plugin.fc_handler.retry_pending_deliveries()
    assert session.remote[101] == {"steel": 75 if failure == "ambiguous" else 80}


def test_manual_save_reserves_its_position_before_later_journal_writes(editor_session) -> None:
    """A movement after Save belongs after the manual 100 even if its HTTP worker starts first."""
    session = editor_session
    session.editor._on_save()
    session.plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(session.plugin)
    session.workers.pop()()
    session.plugin.fc_handler.retry_pending_deliveries()
    session.callbacks.pop()()
    assert session.remote[101] == {"steel": 105}
    assert session.editor._fc_records[101]["cargo"] == {"steel": 105}


def test_earlier_queued_automatic_snapshot_cannot_supersede_manual_save(editor_session) -> None:
    """An older 80 seed still in the API queue cannot cancel the user's newer 100 correction."""
    session = editor_session
    session.plugin.fc_handler._update_fc_cargo_async(101, {"steel": 80})
    session.editor._on_save()
    drain(session.plugin)
    session.workers.pop()()
    session.callbacks.pop()()
    assert session.remote[101] == {"steel": 100}
    assert session.plugin.pending_carrier_deliveries.replacements() == []


def test_completed_movement_freshness_survives_restart(session, monkeypatch, tmp_path) -> None:
    """Retired transaction evidence still prevents a pre-deposit CAPI packet after process restart."""
    session.dock(False)
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    restored = session.load.RavencolonialPlugin()
    restored.configure_pending_carrier_deliveries(str(tmp_path))
    restored.api_client.session = plugin.api_client.session
    monkeypatch.setattr(restored, "_ensure_api_worker", lambda: None)
    for method in ("get_fc", "get_all_cmdr_fcs", "get_commander_projects"):
        monkeypatch.setattr(restored.api_client, method, getattr(plugin.api_client, method))
    session.load.this = restored
    session.load.journal_entry("Alpha", False, "Sol", "", {"event": "LoadGame"}, {})
    settle_commander_links(restored)
    session.load.capi_fleetcarrier({
        "name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:39Z",
        "cargo": [{"commodity": "steel", "qty": 75}],
    })
    drain(restored)
    assert session.remote[101] == {"steel": 80}


def test_retired_save_callback_cannot_finish_the_new_commanders_save(editor_session, monkeypatch) -> None:
    """An old save finishing on UI leaves a newer commander's in-progress form disabled until its own reply."""
    session = editor_session
    editor, plugin = session.editor, session.plugin
    plugin.fc_manifest_editor = editor
    editor._on_save()
    session.workers.pop()()
    old_callback = session.callbacks.pop()
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda name: [
        {"marketId": 303, "name": "303", "cargo": {"steel": 90}},
    ])
    session.load.journal_entry("Bravo", False, "Sol", "", {"event": "LoadGame"}, {})
    settle_commander_links(plugin)
    editor.refresh()
    editor._select_market(303)
    editor._amount_vars = {"steel": SimpleNamespace(get=lambda: "95")}
    editor._on_save()
    old_callback()
    assert editor._saving is True
    session.workers.pop()()
    session.callbacks.pop()()
    assert session.remote[303] == {"steel": 95}
    assert editor._working_manifest == {"steel": 95}


def test_editor_open_during_link_lookup_receives_discovered_carriers(session, monkeypatch) -> None:
    """The current commander's open editor fills itself when asynchronous discovery finishes."""
    plugin = session.plugin
    profiles = plugin.api_client.get_all_cmdr_fcs
    entered, release = threading.Event(), threading.Event()

    def delayed(name):
        entered.set()
        assert release.wait(timeout=2)
        return profiles(name)

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", delayed)
    session.load.journal_entry("Alpha", False, "Sol", "", {"event": "LoadGame"}, {})
    assert entered.wait(timeout=2)
    module = importlib.import_module(f"{session.load.__package__}.ui.fc_manifest_editor")
    editor = module.FleetCarrierManifestEditor(plugin)
    plugin.fc_manifest_editor = editor
    editor._window = SimpleNamespace(winfo_x=lambda: 0, winfo_y=lambda: 0, destroy=lambda: None)
    try:
        editor.refresh()
        assert editor._fc_records == {}
    finally:
        release.set()
    settle_commander_links(plugin)
    assert set(editor._fc_records) == {101, 303}
    assert editor._selected_market_id == 101


def test_manual_reservation_survives_an_older_automatic_preflight_get(editor_session, monkeypatch) -> None:
    """Saving 100 during the older 80 snapshot's GET must survive that GET's completion."""
    session = editor_session
    get_fc = session.plugin.api_client.get_fc
    entered = []

    def preflight(mid):
        if not entered:
            entered.append(True)
            session.editor._on_save()
        return get_fc(mid)

    monkeypatch.setattr(session.plugin.api_client, "get_fc", preflight)
    session.plugin.fc_handler._update_fc_cargo_async(101, {"steel": 80})
    drain(session.plugin)
    session.workers.pop()()
    session.callbacks.pop()()
    assert session.remote[101] == {"steel": 100}
    assert session.plugin.pending_carrier_deliveries.replacements() == []


def test_older_manual_preflight_cannot_promote_over_a_newer_manual_reservation(session, monkeypatch) -> None:
    """A newer manual 200 must survive an older manual 100 finishing its target-discovery GET."""
    session.dock(False)
    handler = session.plugin.fc_handler
    first = handler.prepare_manual_manifest(101, {"steel": 100})
    get_fc = session.plugin.api_client.get_fc
    newer = []

    def preflight(mid):
        if not newer:
            newer.append(handler.prepare_manual_manifest(101, {"steel": 200}))
        return get_fc(mid)

    monkeypatch.setattr(session.plugin.api_client, "get_fc", preflight)
    with pytest.raises(RuntimeError, match="superseded"):
        handler.save_manual_manifest(101, {"steel": 100}, first)
    assert session.remote[101] == {"steel": 75}
    handler.save_manual_manifest(101, {"steel": 200}, newer[0])
    assert session.remote[101] == {"steel": 200}
    assert session.plugin.pending_carrier_deliveries.replacements() == []


def test_copied_automatic_recovery_cannot_replay_after_manual_completion(editor_session, monkeypatch, tmp_path) -> None:
    """A stale recovery-list entry cannot replace a newer acknowledged manual 100 with 80."""
    session = editor_session
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    replace = Path.replace

    def unavailable(path, target):
        raise OSError("checkpoint unavailable")

    monkeypatch.setattr(Path, "replace", unavailable)
    plugin.fc_handler._update_fc_cargo_async(101, {"steel": 80})
    drain(plugin)
    captured, = plugin.pending_carrier_deliveries.replacements()
    monkeypatch.setattr(Path, "replace", replace)
    session.editor._on_save()
    session.workers.pop()()
    session.callbacks.pop()()
    plugin.fc_handler._reconcile_replacement(captured)
    assert session.remote[101] == {"steel": 100}
    assert plugin.pending_carrier_deliveries.replacements() == []


@pytest.mark.parametrize("failure", ["rejected", "connect", "uncertain", "committed"])
def test_failed_manual_save_can_recover_without_another_manual_submission(editor_session, monkeypatch, failure) -> None:
    """Known-unsent/rejected saves retry safely; a newer CAPI manifest resolves an uncertain manual outcome."""
    session = editor_session
    plugin = session.plugin
    request = plugin.api_client.session.request

    def fail(*args, **kwargs):
        if failure == "committed":
            request(*args, **kwargs)
            raise requests.ReadTimeout("committed, reply lost")
        if failure == "connect":
            raise requests.ConnectTimeout("not connected")
        if failure == "uncertain":
            raise requests.ReadTimeout("no response")
        response = requests.Response()
        response.status_code = 403
        response._content = b'{}'
        return response

    monkeypatch.setattr(plugin.api_client.session, "request", fail)
    session.editor._on_save()
    session.workers.pop()()
    session.callbacks.pop()()
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    if failure == "uncertain":
        session.journal("Undocked")
        session.load.capi_fleetcarrier({
            "name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:39Z",
            "cargo": [{"commodity": "steel", "qty": 75}],
        })
        drain(plugin)
        retained, = plugin.pending_carrier_deliveries.replacements()
        assert retained["cargo"] == {"steel": 100}
        assert session.remote[101] == {"steel": 75}
        session.load.capi_fleetcarrier({
            "name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:41Z",
            "cargo": [{"commodity": "steel", "qty": 75}],
        })
        drain(plugin)
    else:
        plugin.fc_handler.retry_pending_deliveries()
    plugin.fc_handler._supply_fc_async(101, {"steel": 2})
    drain(plugin)
    assert session.remote[101] == {"steel": 77 if failure == "uncertain" else 102}
    assert plugin.pending_carrier_deliveries.replacements() == []
    assert plugin.pending_carrier_deliveries.records() == []
    while session.callbacks:
        session.callbacks.pop(0)()
    assert session.editor._base_manifest == {"steel": 77 if failure == "uncertain" else 102}


def test_recovery_cannot_steal_a_live_manual_save_from_its_editor_worker(editor_session) -> None:
    """An earlier queued recovery cannot cause the editor to report failure for its own successful save."""
    session = editor_session
    session.editor._on_save()
    session.plugin.fc_handler.retry_pending_deliveries()
    session.workers.pop()()
    session.callbacks.pop()()
    assert session.remote[101] == {"steel": 100}
    assert session.editor._base_manifest == {"steel": 100}
    assert session.editor._working_manifest == {"steel": 100}


def test_reopened_native_manifest_editor_renders_retained_carrier_and_discards_cancelled_edits(session) -> None:
    """Closing an unsaved form and reopening it restores visible authoritative cargo and details."""
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Native manifest editor requires a Tk display")
    editor = None
    try:
        root.withdraw()
        session.dock(False)
        session.plugin.frame = tk.Frame(root)
        module = importlib.import_module(f"{session.load.__package__}.ui.fc_manifest_editor")
        editor = module.FleetCarrierManifestEditor(session.plugin)
        session.plugin.fc_manifest_editor = editor
        editor.open()
        root.update()
        editor._amount_vars["steel"].set("100")
        editor.close()
        editor.open()
        root.update()
        assert editor._selected_market_id == 101
        assert editor._amount_entries["steel"].winfo_exists() == 1
        assert editor._amount_vars["steel"].get() == "75"
        assert editor._detail_vars["market"].get() == "101"
    finally:
        if editor is not None:
            editor.close()
        root.destroy()


def test_manual_checkpoint_failure_recovery_updates_its_editor(editor_session, monkeypatch, tmp_path) -> None:
    """A manual save recovered after storage returns reconciles its own form with later acknowledged cargo."""
    session = editor_session
    plugin = session.plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    replace = Path.replace

    def unavailable(path, target):
        raise OSError("temporary storage failure")

    monkeypatch.setattr(Path, "replace", unavailable)
    session.editor._on_save()
    assert session.workers == []
    assert session.remote[101] == {"steel": 75}
    monkeypatch.setattr(Path, "replace", replace)
    plugin.fc_handler.retry_pending_deliveries()
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    while session.callbacks:
        session.callbacks.pop(0)()
    assert session.remote[101] == {"steel": 105}
    assert session.editor._base_manifest == {"steel": 105}
    assert plugin.pending_carrier_deliveries.replacements() == []


@pytest.mark.parametrize("invalid_copper", [False, True])
def test_recovery_merges_only_new_user_edits_into_the_latest_manifest(
    editor_session, monkeypatch, invalid_copper,
) -> None:
    """Adding copper after a failed save cannot pin untouched steel to an obsolete quantity."""
    session = editor_session
    plugin = session.plugin
    request = plugin.api_client.session.request

    def reject(*args, **kwargs):
        response = requests.Response()
        response.status_code = 403
        response._content = b'{}'
        return response

    monkeypatch.setattr(plugin.api_client.session, "request", reject)
    session.editor._on_save()
    session.workers.pop()()
    session.callbacks.pop()()
    session.editor._working_manifest["copper"] = 2
    session.editor._amount_vars = {"steel": entry_value(100), "copper": entry_value("invalid" if invalid_copper else 2)}
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    plugin.fc_handler.retry_pending_deliveries()
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    while session.callbacks:
        session.callbacks.pop(0)()
    assert session.editor._working_manifest == {"steel": 105, "copper": 2}
    assert session.editor._amount_vars["copper"].get() == ("invalid" if invalid_copper else "2")
    session.editor._amount_vars["copper"].set("2")
    session.editor._on_save()
    session.workers.pop()()
    session.callbacks.pop()()
    assert session.remote[101] == {"steel": 105, "copper": 2}


@pytest.mark.parametrize("reopen_first, edit_copper", [(False, False), (True, False), (True, True)])
def test_native_reopened_form_merges_recovery_with_only_its_new_edits(
    editor_session, monkeypatch, reopen_first, edit_copper,
) -> None:
    """Reopening changes the edit baseline; displayed old stock is not a new manual correction."""
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Native manifest editor requires a Tk display")
    session = editor_session
    plugin, editor = session.plugin, session.editor
    request = plugin.api_client.session.request

    def reject(*args, **kwargs):
        response = requests.Response()
        response.status_code = 403
        response._content = b'{}'
        return response

    try:
        root.withdraw()
        plugin.frame = tk.Frame(root)
        editor.open()
        editor._amount_vars["steel"].set("100")
        monkeypatch.setattr(plugin.api_client.session, "request", reject)
        editor._on_save()
        session.workers.pop()()
        session.callbacks.pop()()
        editor.close()
        if reopen_first:
            editor.open()
        if edit_copper:
            editor._working_manifest["copper"] = 2
            editor._render_manifest()
        monkeypatch.setattr(plugin.api_client.session, "request", request)
        plugin.fc_handler.retry_pending_deliveries()
        plugin.fc_handler._supply_fc_async(101, {"steel": 5})
        drain(plugin)
        while session.callbacks:
            session.callbacks.pop(0)()
        if not reopen_first:
            editor.open()
        expected = {"steel": 105, "copper": 2} if edit_copper else {"steel": 105}
        assert editor._working_manifest == expected
        assert editor._amount_vars["steel"].get() == "105"
        if edit_copper:
            assert editor._amount_vars["copper"].get() == "2"
            editor._on_save()
            session.workers.pop()()
            session.callbacks.pop()()
            assert session.remote[101] == {"steel": 105, "copper": 2}
    finally:
        editor.close()
        root.destroy()


def test_rejected_manual_write_does_not_retry_over_changed_remote_stock(editor_session, monkeypatch) -> None:
    """A definite rejection needs its saved before-state; another client's 85 cannot be overwritten with 100."""
    session = editor_session
    plugin = session.plugin
    request = plugin.api_client.session.request

    def reject(*args, **kwargs):
        response = requests.Response()
        response.status_code = 403
        response._content = b'{}'
        return response

    monkeypatch.setattr(plugin.api_client.session, "request", reject)
    session.editor._on_save()
    session.workers.pop()()
    session.callbacks.pop()()
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    session.remote[101] = {"steel": 85}
    plugin.fc_handler.retry_pending_deliveries()
    assert session.remote[101] == {"steel": 85}
    retained, = plugin.pending_carrier_deliveries.replacements()
    assert retained["cargo"] == {"steel": 100}


@pytest.mark.parametrize("later_failure", ["connect", "rejected"])
def test_ambiguous_full_write_cannot_become_safe_after_later_failures(
    editor_session, monkeypatch, later_failure,
) -> None:
    """A possibly committed 100 cannot replay over a subsequent external withdrawal back to 75."""
    session = editor_session
    plugin = session.plugin
    request = plugin.api_client.session.request
    attempts = []

    def mixed(method, url, **kwargs):
        attempts.append(method)
        if len(attempts) == 1:
            request(method, url, **kwargs)
            session.remote[101] = {"steel": 75}
            raise requests.ReadTimeout("committed 100, lost reply, then another client withdrew 25")
        if later_failure == "connect":
            raise requests.ConnectTimeout("later attempt could not connect")
        response = requests.Response()
        response.status_code = 403
        response._content = b'{}'
        return response

    monkeypatch.setattr(plugin.api_client.session, "request", mixed)
    session.editor._on_save()
    session.workers.pop()()
    session.callbacks.pop()()
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    plugin.fc_handler.retry_pending_deliveries()
    assert session.remote[101] == {"steel": 75}
    retained, = plugin.pending_carrier_deliveries.replacements()
    assert retained["uncertain"] is True


@pytest.mark.parametrize("manual", [False, True])
def test_recovery_aborts_if_its_second_get_observes_changed_stock(editor_session, monkeypatch, manual) -> None:
    """A validated before=75 cannot authorize 100 after preflight itself observes a newer 85."""
    session = editor_session
    plugin = session.plugin
    request = plugin.api_client.session.request

    def reject(*args, **kwargs):
        response = requests.Response()
        response.status_code = 403
        response._content = b'{}'
        return response

    monkeypatch.setattr(plugin.api_client.session, "request", reject)
    if manual:
        session.editor._on_save()
        session.workers.pop()()
        session.callbacks.pop()()
    else:
        plugin.fc_handler._update_fc_cargo_async(101, {"steel": 100})
        drain(plugin)
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    get_fc = plugin.api_client.get_fc
    reads = []

    def advancing(mid):
        reads.append(mid)
        if len(reads) == 2:
            session.remote[101] = {"steel": 85}
        return get_fc(mid)

    monkeypatch.setattr(plugin.api_client, "get_fc", advancing)
    plugin.fc_handler.retry_pending_deliveries()
    assert session.remote[101] == {"steel": 85}
    retained, = plugin.pending_carrier_deliveries.replacements()
    assert retained["cargo"] == {"steel": 100}


@pytest.mark.parametrize("select_before_recovery", [False, True])
def test_another_carriers_save_cannot_hide_recovered_manifest(
    editor_session, monkeypatch, select_before_recovery,
) -> None:
    """Carrier A's recovery refreshes its records after saving B, without replacing the active form's edits."""
    session = editor_session
    plugin, editor = session.plugin, session.editor
    editor.refresh()
    request = plugin.api_client.session.request

    def reject(*args, **kwargs):
        response = requests.Response()
        response.status_code = 403
        response._content = b'{}'
        return response

    monkeypatch.setattr(plugin.api_client.session, "request", reject)
    editor._on_save()
    session.workers.pop()()
    session.callbacks.pop()()
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    editor._select_market(303)
    editor._amount_vars = {"steel": entry_value(95)}
    editor._on_save()
    session.workers.pop()()
    session.callbacks.pop()()
    if select_before_recovery:
        editor._select_market(101)
        editor._working_manifest["copper"] = 2
        editor._amount_vars = {"steel": entry_value(75), "copper": entry_value(2)}
    plugin.fc_handler.retry_pending_deliveries()
    while session.callbacks:
        session.callbacks.pop(0)()
    if not select_before_recovery:
        editor._select_market(101)
        editor._working_manifest["copper"] = 2
        editor._amount_vars = {"steel": entry_value(editor._working_manifest["steel"]), "copper": entry_value(2)}
    assert editor._working_manifest == {"steel": 100, "copper": 2}
    editor._on_save()
    session.workers.pop()()
    session.callbacks.pop()()
    assert session.remote == {101: {"steel": 100, "copper": 2}, 303: {"steel": 95}}


@pytest.mark.parametrize("removal", ["zero", "remove"])
def test_recovery_preserves_user_removal_after_a_failed_save(editor_session, monkeypatch, removal) -> None:
    """Removing steel after failed 100 remains an edit when recovery and another deposit produce 105."""
    session = editor_session
    plugin, editor = session.plugin, session.editor
    request = plugin.api_client.session.request

    def reject(*args, **kwargs):
        response = requests.Response()
        response.status_code = 403
        response._content = b'{}'
        return response

    monkeypatch.setattr(plugin.api_client.session, "request", reject)
    editor._on_save()
    session.workers.pop()()
    session.callbacks.pop()()
    if removal == "zero":
        editor._amount_vars = {"steel": entry_value(0)}
    else:
        editor._working_manifest.pop("steel", None)
        editor._amount_vars = {}
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    plugin.fc_handler.retry_pending_deliveries()
    plugin.fc_handler._supply_fc_async(101, {"steel": 5})
    drain(plugin)
    while session.callbacks:
        session.callbacks.pop(0)()
    assert editor._working_manifest == {}
    editor._on_save()
    session.workers.pop()()
    session.callbacks.pop()()
    assert session.remote[101] == {}


@pytest.mark.parametrize("callback_after_new_failure", [False, True])
def test_superseded_recovery_preserves_newer_saves_explicit_values(
    editor_session, monkeypatch, callback_after_new_failure,
) -> None:
    """An older recovered 100 cannot undo a newer explicit reversion to 75, even after both saves recover."""
    session = editor_session
    plugin, editor = session.plugin, session.editor
    session.remote[101] = {"steel": 75, "copper": 10}
    editor._base_manifest = {"steel": 75, "copper": 10}
    editor._working_manifest = {"steel": 100, "copper": 10}
    editor._amount_vars = {"steel": entry_value(100), "copper": entry_value(10)}
    request = plugin.api_client.session.request

    def reject(*args, **kwargs):
        response = requests.Response()
        response.status_code = 403
        response._content = b'{}'
        return response

    monkeypatch.setattr(plugin.api_client.session, "request", reject)
    editor._on_save()
    session.workers.pop()()
    session.callbacks.pop()()
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    plugin.fc_handler.retry_pending_deliveries()
    recovered_first = session.callbacks.pop(0)
    editor._working_manifest = {"steel": 75, "copper": 20}
    editor._amount_vars = {"steel": entry_value(75), "copper": entry_value(20)}
    monkeypatch.setattr(plugin.api_client.session, "request", reject)
    editor._on_save()
    if not callback_after_new_failure:
        recovered_first()
    session.workers.pop()()
    session.callbacks.pop()()
    if callback_after_new_failure:
        recovered_first()
    assert editor._current_manifest_from_entries() == ({"steel": 75, "copper": 20}, True)
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    plugin.fc_handler.retry_pending_deliveries()
    while session.callbacks:
        session.callbacks.pop(0)()
    assert editor._working_manifest == {"steel": 75, "copper": 20}
    editor._working_manifest["copper"] = 21
    editor._amount_vars = {"steel": entry_value(75), "copper": entry_value(21)}
    editor._on_save()
    session.workers.pop()()
    session.callbacks.pop()()
    assert session.remote[101] == {"steel": 75, "copper": 21}


@pytest.mark.parametrize("selected_elsewhere", [False, True])
def test_completed_manual_save_cannot_block_a_later_automatic_recovery(
    editor_session, monkeypatch, selected_elsewhere,
) -> None:
    """After Save100 finishes, later CAPI105 recovery supplies the untouched steel in a copper-only save."""
    session = editor_session
    plugin, editor = session.plugin, session.editor
    editor.refresh()
    editor._on_save()
    session.workers.pop()()
    if selected_elsewhere:
        editor._select_market(303)
    session.callbacks.pop()()
    if selected_elsewhere:
        editor._select_market(101)
    session.journal("Undocked")
    request = plugin.api_client.session.request

    def reject(*args, **kwargs):
        response = requests.Response()
        response.status_code = 403
        response._content = b'{}'
        return response

    monkeypatch.setattr(plugin.api_client.session, "request", reject)
    session.load.capi_fleetcarrier({
        "name": {"callsign": "101"}, "timestamp": "1970-01-01T00:16:41Z",
        "cargo": [{"commodity": "steel", "qty": 105}],
    })
    drain(plugin)
    monkeypatch.setattr(plugin.api_client.session, "request", request)
    plugin.fc_handler.retry_pending_deliveries()
    while session.callbacks:
        session.callbacks.pop(0)()
    editor._working_manifest["copper"] = 2
    editor._amount_vars["copper"] = entry_value(2)
    editor._on_save()
    session.workers.pop()()
    session.callbacks.pop()()
    assert session.remote[101] == {"steel": 105, "copper": 2}
