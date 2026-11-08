"""Order an automatic carrier correction before newly observed journal trades."""

import threading
from types import SimpleNamespace

import pytest

from test_carrier_cargo_parity import drain
from test_inventory_frame_recovery import defer_bank_evidence, inventory_session as _inventory_fixture
from conftest import settle_commander_links


@pytest.fixture
def promotion_session(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Use the actual journal, recovery store, and HTTP client at the promotion boundary."""
    return _inventory_fixture.__wrapped__(edmc_plugin, monkeypatch)


@pytest.mark.parametrize("trade_before_reply", [False, True])
def test_automatic_correction_owns_old_bank_evidence_before_a_new_sale(
    promotion_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, trade_before_reply: bool,
) -> None:
    """A full90 and a subsequent sale2 finish92 on either side of the HTTP response."""
    active = promotion_session
    defer_bank_evidence(active)
    handler = active.plugin.fc_handler
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    errors = []
    get_fc = active.plugin.api_client.get_fc

    def preflight(mid):
        result = get_fc(mid)
        entered.set()
        assert release.wait(timeout=3)
        return result

    def work() -> None:
        try:
            drain(active.plugin)
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    monkeypatch.setattr(active.plugin.api_client, "get_fc", preflight)
    handler.update_fc_cargo_from_capi(101, {"steel": 90}, "2026-11-08T17:00:04Z", was_docked=False)
    worker = threading.Thread(target=work)
    worker.start()
    try:
        assert entered.wait(timeout=3)
        if not trade_before_reply:
            release.set()
            assert finished.wait(timeout=3)
        active.journal("MarketSell", 33, timestamp="2026-11-08T17:00:05Z", MarketID=101,
                       Type="steel", Count=2)
    finally:
        release.set()
        worker.join(timeout=3)
    assert not worker.is_alive()
    assert errors == []
    drain(active.plugin)
    assert active.remote[101] == {"steel": 92}
    assert active.ship == {"steel": 33}
    assert active.plugin.pending_carrier_deliveries.records() == []
    assert active.plugin.pending_carrier_deliveries.replacements() == []
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_new_manual_correction_supersedes_the_queued_automatic_frame_owner(
    promotion_session: SimpleNamespace,
) -> None:
    """A user's125 correction wins over queued90 and retains a subsequent sale2."""
    active = promotion_session
    defer_bank_evidence(active)
    handler = active.plugin.fc_handler
    handler.update_fc_cargo_from_capi(101, {"steel": 90}, "2026-11-08T17:00:04Z", was_docked=False)
    reservation = handler.prepare_manual_manifest(101, {"steel": 125})
    assert handler.save_manual_manifest(101, {"steel": 125}, reservation) == {"steel": 125}
    handler.finish_manual_manifest(reservation)
    active.journal("MarketSell", 33, timestamp="2026-11-08T17:00:05Z", MarketID=101,
                   Type="steel", Count=2)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 127}
    assert active.plugin.pending_carrier_deliveries.records() == []
    assert active.plugin.pending_carrier_deliveries.replacements() == []
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_older_queued_snapshot_does_not_claim_later_bank_evidence(promotion_session: SimpleNamespace) -> None:
    """The90 snapshot cannot retire bank10 observed later, including its deferred sale5."""
    active = promotion_session
    active.dock(True)
    handler = active.plugin.fc_handler
    handler.update_fc_cargo_from_capi(101, {"steel": 90}, "2026-11-08T17:00:01Z", was_docked=False)
    active.journal("Cargo", 40, timestamp="2026-11-08T17:00:02Z", Vessel="Ship", Count=40,
                   Inventory=[{"Name": "steel", "Count": 40}])
    active.journal("MarketSell", 35, timestamp="2026-11-08T17:00:02Z", MarketID=101,
                   Type="steel", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 95}
    active.journal("Cargo", 35, timestamp="2026-11-08T17:00:03Z", Vessel="Ship", Count=35,
                   Inventory=[{"Name": "steel", "Count": 35}])
    drain(active.plugin)
    assert active.remote[101] == {"steel": 105}
    assert active.plugin.pending_carrier_deliveries.records() == []
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


@pytest.mark.parametrize("manual_correction, expected", [(False, 92), (True, 127)])
def test_capi_owns_old_frame_while_the_dock_baseline_is_pending(
    promotion_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, manual_correction: bool, expected: int,
) -> None:
    """A delayed baseline cannot add the old bank10 to CAPI90 plus a genuinely later sale2."""
    active = promotion_session
    active.remote[505] = {"steel": 75}
    monkeypatch.setattr(active.plugin.api_client, "get_all_cmdr_fcs", lambda name: [])
    monkeypatch.setattr(active.plugin.api_client, "get_commander_projects", lambda name: [
        {"linkedFC": [{"marketId": 505, "name": "505"}]},
    ])
    for name in ("Bravo", "Alpha"):
        active.load.journal_entry(name, False, "Sol", "", {"event": "LoadGame"}, {})
        settle_commander_links(active.plugin)

    def journal(event, amount, **fields) -> None:
        active.load.journal_entry("Alpha", False, "Sol", "505", {"event": event, **fields}, {
            "Docked": True, "StationType": "FleetCarrier", "MarketID": 505,
            "ShipType": "python", "Cargo": {"steel": amount},
        })
        settle_commander_links(active.plugin)

    journal("Location", 50, Docked=True, StationType="FleetCarrier", MarketID=505,
            StationName="505", StationServices=["squadronBank"])
    journal("Cargo", 50, timestamp="2026-11-08T17:00:01Z", Vessel="Ship", Count=50,
            Inventory=[{"Name": "steel", "Count": 50}])
    journal("Cargo", 40, timestamp="2026-11-08T17:00:02Z", Vessel="Ship", Count=40,
            Inventory=[{"Name": "steel", "Count": 40}])
    journal("MarketSell", 35, timestamp="2026-11-08T17:00:02Z", MarketID=505, Type="steel", Count=5)
    active.plugin.fc_handler.update_fc_cargo_from_capi(
        505, {"steel": 90}, "2026-11-08T17:00:04Z", was_docked=False,
    )
    active.plugin.fc_handler.retry_pending_deliveries()
    if manual_correction:
        handler = active.plugin.fc_handler
        reservation = handler.prepare_manual_manifest(505, {"steel": 125})
        assert handler.save_manual_manifest(505, {"steel": 125}, reservation) == {"steel": 125}
        handler.finish_manual_manifest(reservation)
    journal("MarketSell", 33, timestamp="2026-11-08T17:00:05Z", MarketID=505, Type="steel", Count=2)
    drain(active.plugin)
    assert active.remote[505] == {"steel": expected}
    assert active.plugin.pending_carrier_deliveries.records() == []
    assert active.plugin.pending_carrier_deliveries.replacements() == []
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
