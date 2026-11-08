"""Preserve known movements when speculative attribution reaches zero stock or changes interval."""

import pytest
from pathlib import Path
import json
import threading

from conftest import settle_commander_links
from test_carrier_cargo_parity import drain, session as _session_fixture
from test_inventory_interval_ordering import prepare_session
from test_mixed_inventory_attribution import inventory, journal


@pytest.mark.parametrize("stock, first, second, event, count, bought, final_hold, drones, expected", [
    (0, 40, 35, "MarketSell", 10, 15, 50, False, 0),
    (0, 50, 45, "MarketBuy", 10, 5, 50, False, 0),
    (20, 60, 55, "MarketBuy", 10, 5, 60, True, 10),
])
def test_transient_reconciliation_does_not_create_stock_after_reaching_zero(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stock: int, first: int, second: int,
    event: str, count: int, bought: int, final_hold: int, drones: bool, expected: int,
) -> None:
    """A fresh physical snapshot cannot create stock from a clamped rollback or forgotten earlier credit."""
    active = prepare_session(edmc_plugin, monkeypatch, stock)
    active.dock(True)
    active.plugin.configure_pending_carrier_deliveries(str(tmp_path))

    def cargo(amount: int, stamp: int, has_drones: bool = False) -> None:
        contents = [{"Name": "steel", "Count": amount}]
        if has_drones:
            contents.append({"Name": "drones", "Count": 1})
        active.journal("Cargo", amount, timestamp=f"2026-11-08T17:00:0{stamp}Z", Vessel="Ship",
                       Count=amount + int(has_drones), Inventory=contents)

    cargo(first, 1)
    drain(active.plugin)
    if drones:
        active.journal("BuyDrones", first, timestamp="2026-11-08T17:00:02Z", Count=1)
    cargo(second, 2, drones)
    drain(active.plugin)
    active.journal(event, second, timestamp="2026-11-08T17:00:01Z", MarketID=101, Type="steel", Count=count)
    active.journal("MarketBuy", final_hold, timestamp="2026-11-08T17:00:02Z", MarketID=101,
                   Type="steel", Count=bought)
    drain(active.plugin)
    if not drones:
        assert active.remote[101] == {"steel": 0}
        restored = active.load.PendingCarrierDeliveries()
        restored.configure(str(tmp_path))
        frame, = restored.inventory_frames("Alpha", 101)
        assert frame["state"]["before"] == {"steel": second}
        assert frame["state"]["accounted"] == {"steel": bought}
        assert restored.records() == []
    else:
        # Retain the settled buy10; defer only the newer bank5 while reporting buy5.
        assert active.remote[101] == {"steel": 5}
    cargo(final_hold, 3, drones)
    drain(active.plugin)
    assert active.remote[101] == {"steel": expected}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
    assert active.plugin.pending_carrier_deliveries.records() == []


def test_unrelated_origin_sale_survives_a_steel_only_transient_frame(edmc_plugin, monkeypatch) -> None:
    """An unchanged copper balance is not deferred by restoring steel's older baseline."""
    active = prepare_session(edmc_plugin, monkeypatch, 75)
    active.remote[101]["copper"] = 100
    journal(active, "Location", {}, Docked=True, StationType="FleetCarrier", MarketID=101,
            StationServices=["squadronBank"])
    inventory(active, 50, 10, 1)
    inventory(active, 40, 10, 2)
    journal(active, "MarketSell", {"steel": 35, "copper": 10}, timestamp="2026-11-08T17:00:02Z",
            MarketID=101, Type="steel", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 80, "copper": 100}
    journal(active, "MarketSell", {"steel": 35, "copper": 8}, timestamp="2026-11-08T17:00:01Z",
            MarketID=101, Type="copper", Count=2)
    inventory(active, 35, 10, 3)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 90, "copper": 102}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


@pytest.mark.parametrize("settled_sale, unchanged, expected", [
    (False, False, 10), (False, True, 10), (True, False, 15),
])
def test_untrusted_withdrawal_already_in_physical_stock_cannot_clamp_then_reappear(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, settled_sale: bool, unchanged: bool, expected: int,
) -> None:
    """An unverified buy20 cannot destroy a known10/15 and recreate twenty on the next unchanged inventory."""
    active = prepare_session(edmc_plugin, monkeypatch, 0)
    active.dock(True)
    active.journal("Cargo", 40, timestamp="2026-11-08T17:00:01Z", Vessel="Ship", Count=40,
                   Inventory=[{"Name": "steel", "Count": 40}])
    drain(active.plugin)
    hold = 35 if settled_sale else 40
    if settled_sale or unchanged:
        active.journal("Cargo", hold, timestamp="2026-11-08T17:00:02Z", Vessel="Ship", Count=hold,
                       Inventory=[{"Name": "steel", "Count": hold}])
        drain(active.plugin)
    if settled_sale:
        active.journal("MarketSell", hold, timestamp="2026-11-08T17:00:01Z", MarketID=101,
                       Type="steel", Count=10)
    stamp = "2026-11-08T17:00:02Z" if settled_sale or unchanged else "2026-11-08T17:00:01Z"
    active.journal("MarketBuy", hold + 20, timestamp=stamp, MarketID=101, Type="steel", Count=20)
    drain(active.plugin)
    assert active.remote[101] == {"steel": expected}
    active.journal("Cargo", hold, timestamp="2026-11-08T17:00:03Z", Vessel="Ship", Count=hold,
                   Inventory=[{"Name": "steel", "Count": hold}])
    drain(active.plugin)
    assert active.remote[101] == {"steel": expected}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


@pytest.mark.parametrize("read_ahead_copper", [False, True])
def test_mixed_transfer_omits_only_the_unverified_withdrawal(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, read_ahead_copper: bool,
) -> None:
    """Omitting steel20 leaves a safe copper2 counted once, including its read-ahead form."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"steel": 0, "copper": 100}
    active.journal("Loadout", Ship="python", CargoCapacity=100, Modules=[])
    journal(active, "Location", {"steel": 50, "copper": 10}, Docked=True, StationType="FleetCarrier",
            MarketID=101, StationServices=["squadronBank"])
    inventory(active, 50, 10, 0)
    inventory(active, 40, 8 if read_ahead_copper else 10, 1)
    drain(active.plugin)
    journal(active, "CargoTransfer", {"steel": 60, "copper": 6 if read_ahead_copper else 8},
            timestamp="2026-11-08T17:00:01Z", Transfers=[
                {"Type": "steel", "Count": 20, "Direction": "toship"},
                {"Type": "copper", "Count": 2, "Direction": "tocarrier"},
            ])
    drain(active.plugin)
    assert active.remote[101] == {"steel": 10, "copper": 102}
    inventory(active, 40, 8, 2)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 10, "copper": 102}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_trusted_additional_withdrawal_waits_for_a_full_carrier_correction(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A proved additional buy20 against Raven10 remains held rather than issuing a clamped relative write."""
    active = prepare_session(edmc_plugin, monkeypatch, 0)
    active.dock(True)
    active.journal("Cargo", 40, timestamp="2026-11-08T17:00:01Z", Vessel="Ship", Count=40,
                   Inventory=[{"Name": "steel", "Count": 40}])
    drain(active.plugin)
    monkeypatch.setattr(active.load.config, "default_journal_dir", str(tmp_path), raising=False)
    (tmp_path / "Cargo.json").write_text(json.dumps({
        "event": "Cargo", "timestamp": "2026-11-08T17:00:02Z", "Vessel": "Ship", "Count": 60,
        "Inventory": [{"Name": "steel", "Count": 60}],
    }))
    active.journal("MarketBuy", 60, timestamp="2026-11-08T17:00:02Z", MarketID=101, Type="steel", Count=20)
    active.journal("Cargo", 60, timestamp="2026-11-08T17:00:03Z", Vessel="Ship", Count=60,
                   Inventory=[{"Name": "steel", "Count": 60}])
    drain(active.plugin)
    assert active.remote[101] == {"steel": 10}
    assert active.writes == [(101, {"steel": 10})]
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames("Alpha", 101)) == 1
    handler = active.plugin.fc_handler
    reservation = handler.prepare_manual_manifest(101, {"steel": 35})
    assert handler.save_manual_manifest(101, {"steel": 35}, reservation) == {"steel": 35}
    handler.finish_manual_manifest(reservation)
    active.journal("Cargo", 60, timestamp="2026-11-08T17:00:04Z", Vessel="Ship", Count=60,
                   Inventory=[{"Name": "steel", "Count": 60}])
    drain(active.plugin)
    assert active.remote[101] == {"steel": 35}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


@pytest.mark.parametrize("commodity, before, after, event, count, expected, baseline_pending", [
    ("steel", 50, 40, "MarketBuy", 20, 10, False), ("drones", 20, 30, "BuyDrones", 10, 0, False),
    ("drones", 20, 10, "SellDrones", 10, 0, False), ("drones", 20, 10, "SellDrones", 10, 0, True),
])
def test_unknown_carrier_stock_cannot_queue_a_speculative_withdrawal_during_lookup(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, commodity: str, before: int, after: int,
    event: str, count: int, expected: int, baseline_pending: bool,
) -> None:
    """A real pending commander lookup cannot later release a negative/positive pair that creates stock."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {commodity: 0}
    entered, release = threading.Event(), threading.Event()

    def profiles(name: str) -> list:
        entered.set()
        assert release.wait(timeout=3)
        return [] if baseline_pending else [{"marketId": 101, "name": "101", "cargo": {commodity: 0}}]

    def raw(event_name: str, amount: int, **fields) -> None:
        active.load.journal_entry("Alpha", False, "Sol", "101", {"event": event_name, **fields}, {
            "Docked": True, "StationType": "FleetCarrier", "MarketID": 101,
            "ShipType": "python", "Cargo": {commodity: amount},
        })

    monkeypatch.setattr(active.plugin.api_client, "get_all_cmdr_fcs", profiles)
    if baseline_pending:
        monkeypatch.setattr(active.plugin.api_client, "get_commander_projects", lambda name: [
            {"linkedFC": [{"marketId": 101, "name": "101"}]},
        ])
    try:
        raw("Loadout", before, Ship="python", CargoCapacity=100, Modules=[])
        assert entered.wait(timeout=3)
        if baseline_pending:
            release.set()
            settle_commander_links(active.plugin)
        raw("Location", before, Docked=True, StationType="FleetCarrier", MarketID=101,
            StationServices=["squadronBank"])
        raw("Cargo", before, timestamp="2026-11-08T17:00:00Z", Vessel="Ship", Count=before,
            Inventory=[{"Name": commodity, "Count": before}])
        raw("Cargo", after, timestamp="2026-11-08T17:00:01Z", Vessel="Ship", Count=after,
            Inventory=[{"Name": commodity, "Count": after}])
        raw(event, after, timestamp="2026-11-08T17:00:01Z", MarketID=101, Type=commodity, Count=count)
        raw("Cargo", after, timestamp="2026-11-08T17:00:02Z", Vessel="Ship", Count=after,
            Inventory=[{"Name": commodity, "Count": after}])
    finally:
        release.set()
    settle_commander_links(active.plugin)
    drain(active.plugin)
    assert active.remote[101] == {commodity: expected}
    assert active.plugin.pending_carrier_deliveries.records() == []
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


@pytest.mark.parametrize("copper, expected", [(0, {"steel": 0}), (10, {"steel": 0, "copper": 100})])
def test_omitted_withdrawal_retains_its_first_validated_physical_point(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, copper: int, expected: dict,
) -> None:
    """The observed50-to60 net withdrawal still reconciles after an unknown-origin buy20 was omitted."""
    active = prepare_session(edmc_plugin, monkeypatch, 10)
    if copper:
        active.remote[101]["copper"] = 100
    journal(active, "Location", {}, Docked=True, StationType="FleetCarrier", MarketID=101,
            StationServices=["squadronBank"])
    inventory(active, 50, copper, 1)
    journal(active, "MarketBuy", {"steel": 60, "copper": copper}, timestamp="2026-11-08T17:00:01Z",
            MarketID=101, Type="steel", Count=20)
    inventory(active, 60, copper, 2)
    drain(active.plugin)
    assert active.remote[101] == expected
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
