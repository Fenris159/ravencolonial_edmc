"""Protect the ordinary FIFO transitions identified in the scoped simplification review."""

from pathlib import Path
import threading

import pytest

from carrier_test_support import full_cargo, journal, placement_session
from test_carrier_cargo_parity import (
    drain, market_session as _parity_market_session, session as _session_fixture,
    start_squadron_session, write_market_cargo_file,
)
from test_conservative_inventory_window import market_session as _market_fixture
from test_held_inventory_lifecycle import complete_first_carrier_write


@pytest.fixture
def market_session(edmc_plugin, monkeypatch: pytest.MonkeyPatch):
    """Reuse the real journal/HTTP boundary fixture."""
    return _market_fixture.__wrapped__(edmc_plugin, monkeypatch)


def unknown_start(active) -> None:
    """Open a bank session before EDMC has loaded its first hold."""
    start_squadron_session(active, {})
    journal(active, 'Location', {}, Docked=True, StationType='FleetCarrier', MarketID=101,
            StationServices=['squadronBank'])


def test_stealth_inventory_rebase_consumes_previously_excluded_ship_activity(
    market_session, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ejecting five cannot later debit the carrier when stealth has consumed that ship interval."""
    active = market_session
    active.dock(True)
    journal(active, 'EjectCargo', {'steel': 45}, timestamp='2026-11-08T17:00:02Z', Type='steel', Count=5)
    monkeypatch.setattr(active.load.config, 'get_bool', lambda key, **kw: key == 'ravencolonial_stealth_mode')
    full_cargo(active, {'steel': 45}, 3)
    drain(active.plugin)
    monkeypatch.setattr(active.load.config, 'get_bool', lambda key, **kw: False)
    full_cargo(active, {'steel': 45}, 4)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 75}
    assert active.ship == {'steel': 45}
    assert active.writes == []


@pytest.mark.parametrize('newer_snapshot', [False, True])
def test_strictly_older_activity_remains_covered_after_manual_correction(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, newer_snapshot: bool,
) -> None:
    """A covered old limpet sale must neither undo carrier20 nor create a new unresolved frame."""
    active = placement_session(edmc_plugin, monkeypatch, tmp_path, 20, 10)
    full_cargo(active, {'drones': 10, 'steel': 10}, 2)
    drain(active.plugin)
    handler = active.plugin.fc_handler
    identity = handler.prepare_manual_manifest(101, {'drones': 20, 'steel': 0})
    assert handler.save_manual_manifest(101, {'drones': 20, 'steel': 0}, identity) == {'drones': 20}
    handler.finish_manual_manifest(identity)
    if newer_snapshot:
        full_cargo(active, {'drones': 10, 'steel': 10}, 3)
    journal(active, 'SellDrones', {'drones': 10, 'steel': 10}, timestamp='2026-11-08T17:00:01Z', Count=10)
    drain(active.plugin)
    assert active.remote[101] == {'drones': 20}
    assert active.ship == {'drones': 10, 'steel': 10}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_first_complete_trade_establishes_the_baseline_for_the_next_bank_deposit(
    market_session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Buy ten debits75 to65; the following bank deposit ten restores75 exactly once."""
    active = market_session
    unknown_start(active)
    write_market_cargo_file(active, monkeypatch, tmp_path, 60)
    journal(active, 'MarketBuy', {'steel': 60}, timestamp='2026-11-08T17:00:02Z',
            MarketID=101, Type='steel', Count=10)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 65}
    assert active.ship == {'steel': 60}
    full_cargo(active, {'steel': 50}, 3)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 75}
    assert active.ship == {'steel': 50}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_same_second_ship_activity_at_unknown_origin_retains_uncertainty(market_session) -> None:
    """A same-second ejection cannot become an invented five-unit carrier deposit."""
    active = market_session
    unknown_start(active)
    full_cargo(active, {'steel': 50}, 1)
    journal(active, 'EjectCargo', {'steel': 45}, timestamp='2026-11-08T17:00:01Z', Type='steel', Count=5)
    full_cargo(active, {'steel': 45}, 2)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 75}
    assert active.ship == {'steel': 45}
    assert active.writes == []
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1


def test_origin_credit_is_consumed_only_for_the_commodity_being_reported(market_session) -> None:
    """Two credited deposits and their delayed sales must each reach the carrier once."""
    active = market_session
    active.remote[101] = {'steel': 75, 'copper': 100}
    unknown_start(active)
    full_cargo(active, {'steel': 50, 'copper': 50}, 1)
    full_cargo(active, {'steel': 40, 'copper': 40}, 2)
    for key in ('steel', 'copper'):
        journal(active, 'MarketSell', {'steel': 30, 'copper': 30}, timestamp='2026-11-08T17:00:01Z',
                MarketID=101, Type=key, Count=10)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 85, 'copper': 110}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1


@pytest.mark.parametrize('matching_file', [False, True])
def test_later_explicit_transfer_survives_an_unresolved_origin(
    market_session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, matching_file: bool,
) -> None:
    """A known later five-unit deposit counts with or without its complete matching file."""
    active = market_session
    unknown_start(active)
    full_cargo(active, {'steel': 50}, 1)
    full_cargo(active, {'steel': 40}, 2)
    journal(active, 'MarketSell', {'steel': 30}, timestamp='2026-11-08T17:00:01Z',
            MarketID=101, Type='steel', Count=10)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 85}
    if matching_file:
        write_market_cargo_file(active, monkeypatch, tmp_path, 35, timestamp='2026-11-08T17:00:03Z')
    journal(active, 'CargoTransfer', {'steel': 35}, timestamp='2026-11-08T17:00:03Z',
            Transfers=[{'Type': 'steel', 'Count': 5, 'Direction': 'tocarrier'}])
    full_cargo(active, {'steel': 35}, 4)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 90}
    assert active.ship == {'steel': 35}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1


@pytest.mark.parametrize('inventory', [None, []])
def test_sparse_cargo_with_valid_state_updates_ship_but_waits_for_full_bank_evidence(
    market_session, inventory,
) -> None:
    """A valid forty-unit state updates the ship immediately, then full evidence credits the bank."""
    active = market_session
    active.dock(True)
    journal(active, 'Cargo', {'steel': 40}, timestamp='2026-11-08T17:00:02Z', Vessel='Ship',
            Count=40, Inventory=inventory)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 75}
    assert active.ship == {'steel': 40}
    full_cargo(active, {'steel': 40}, 3)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 85}
    assert active.ship == {'steel': 40}


def test_first_complete_trade_after_manual_ambiguity_preserves_the_barrier(
    market_session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A later known five counts against corrected125 while uncertain bank movements remain held."""
    active = market_session
    active.dock(True)
    full_cargo(active, {'steel': 40}, 2)
    journal(active, 'MarketSell', {'steel': 35}, timestamp='2026-11-08T17:00:02Z',
            MarketID=101, Type='steel', Count=5)
    drain(active.plugin)
    handler = active.plugin.fc_handler
    identity = handler.prepare_manual_manifest(101, {'steel': 125})
    assert handler.save_manual_manifest(101, {'steel': 125}, identity) == {'steel': 125}
    handler.finish_manual_manifest(identity)
    journal(active, 'EjectCargo', {'steel': 35}, timestamp='2026-11-08T17:00:02Z', Type='steel', Count=5)
    write_market_cargo_file(active, monkeypatch, tmp_path, 30, timestamp='2026-11-08T17:00:04Z')
    journal(active, 'MarketSell', {'steel': 30}, timestamp='2026-11-08T17:00:04Z',
            MarketID=101, Type='steel', Count=5)
    full_cargo(active, {'steel': 25}, 5)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 130}
    assert active.ship == {'steel': 25}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1


def test_later_complete_trade_cannot_weaken_an_older_manual_barrier(
    market_session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A known sale at the newer ship point counts once without retiring an older correction barrier."""
    active = market_session
    active.dock(True)
    full_cargo(active, {'steel': 40}, 1)
    drain(active.plugin)
    handler = active.plugin.fc_handler
    identity = handler.prepare_manual_manifest(101, {'steel': 125})
    assert handler.save_manual_manifest(101, {'steel': 125}, identity) == {'steel': 125}
    handler.finish_manual_manifest(identity)
    full_cargo(active, {'steel': 40}, 2)
    journal(active, 'EjectCargo', {'steel': 35}, timestamp='2026-11-08T17:00:01Z', Type='steel', Count=5)
    write_market_cargo_file(active, monkeypatch, tmp_path, 35)
    journal(active, 'MarketSell', {'steel': 35}, timestamp='2026-11-08T17:00:02Z',
            MarketID=101, Type='steel', Count=5)
    full_cargo(active, {'steel': 35}, 3)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 130}
    assert active.ship == {'steel': 35}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1


@pytest.mark.parametrize('undock_before_drain', [False, True])
def test_read_ahead_eject_cancels_unattempted_inferred_deposit_without_phantom_stock(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, undock_before_drain: bool,
) -> None:
    """A read-ahead Cargo before EjectCargo must not write phantom stock, even across immediate undock."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {'steel': 0}
    _parity_market_session.__wrapped__(active)
    active.dock(True)
    full_cargo(active, {'steel': 50}, 1)
    drain(active.plugin)
    full_cargo(active, {'steel': 45}, 3)
    journal(active, 'EjectCargo', {'steel': 40}, timestamp='2026-11-08T17:00:02Z', Type='steel', Count=5)
    full_cargo(active, {'steel': 45}, 3)
    if undock_before_drain:
        active.load.journal_entry('Alpha', False, 'Sol', '', {'event': 'Undocked'}, {
            'Docked': False, 'ShipType': 'python', 'Cargo': {'steel': 45},
        })
    drain(active.plugin)
    assert active.remote[101] == {'steel': 0}
    assert active.ship == {'steel': 45}
    assert active.writes == []
    assert active.plugin.pending_carrier_deliveries.records() == []
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_read_ahead_eject_shrinks_mixed_unattempted_deposit_to_the_real_bank_amount(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ejecting five alongside a five-unit bank deposit sends only the real five-unit deposit."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {'steel': 0}
    _parity_market_session.__wrapped__(active)
    active.dock(True)
    full_cargo(active, {'steel': 50}, 1)
    drain(active.plugin)
    full_cargo(active, {'steel': 40}, 3)
    journal(active, 'EjectCargo', {'steel': 35}, timestamp='2026-11-08T17:00:02Z', Type='steel', Count=5)
    full_cargo(active, {'steel': 40}, 3)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 5}
    assert active.ship == {'steel': 40}
    assert active.writes == [(101, {'steel': 5})]
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_read_ahead_eject_recovers_after_inferred_deposit_has_already_begun(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the inferred deposit is already in flight, the ejection retries once that deposit acknowledges."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {'steel': 0}
    _parity_market_session.__wrapped__(active)
    active.dock(True)
    full_cargo(active, {'steel': 50}, 1)
    drain(active.plugin)
    entered, release, first_done = threading.Event(), threading.Event(), threading.Event()
    ready = threading.Event()
    ready.set()
    errors = []
    original_request = active.plugin.api_client.session.request

    def paused_patch(method: str, url: str, **kwargs):
        if method == 'PATCH' and url.endswith('/101/cargo') and not entered.is_set():
            entered.set()
            assert release.wait(timeout=3)
        return original_request(method, url, **kwargs)

    monkeypatch.setattr(active.plugin.api_client.session, 'request', paused_patch)
    full_cargo(active, {'steel': 45}, 3)
    worker = threading.Thread(
        target=complete_first_carrier_write,
        args=(active.plugin, ready, first_done, errors),
        name='in-flight-inferred-deposit',
    )
    worker.start()
    try:
        assert entered.wait(timeout=3)
        journal(active, 'EjectCargo', {'steel': 40}, timestamp='2026-11-08T17:00:02Z', Type='steel', Count=5)
        full_cargo(active, {'steel': 45}, 3)
    finally:
        release.set()
        worker.join(timeout=4)
    assert not worker.is_alive()
    assert errors == []
    drain(active.plugin)
    assert active.remote[101] == {'steel': 0}
    assert active.ship == {'steel': 45}
    assert active.plugin.pending_carrier_deliveries.records() == []
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


@pytest.mark.parametrize('next_hold, expected_carrier', [(45, 125), (40, 130)])
def test_manual_correction_after_valid_sparse_ship_view_does_not_reapply_earlier_eject(
    market_session, next_hold: int, expected_carrier: int,
) -> None:
    """Manual rebase must not subtract an ejection already reflected in the accepted sparse ship view."""
    active = market_session
    active.dock(True)
    full_cargo(active, {'steel': 50}, 1)
    drain(active.plugin)
    journal(active, 'EjectCargo', {'steel': 45}, timestamp='2026-11-08T17:00:02Z', Type='steel', Count=5)
    journal(active, 'Cargo', {'steel': 45}, timestamp='2026-11-08T17:00:03Z', Vessel='Ship', Count=45)
    drain(active.plugin)
    handler = active.plugin.fc_handler
    identity = handler.prepare_manual_manifest(101, {'steel': 125})
    assert handler.save_manual_manifest(101, {'steel': 125}, identity) == {'steel': 125}
    handler.finish_manual_manifest(identity)
    full_cargo(active, {'steel': next_hold}, 4)
    drain(active.plugin)
    assert active.remote[101] == {'steel': expected_carrier}
    assert active.ship == {'steel': next_hold}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_matching_file_purchase_keeps_outbox_recovery_when_cached_stock_is_stale(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A matching Cargo.json confirms an explicit purchase without bypassing funding or losing retry."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {'steel': 4}
    _parity_market_session.__wrapped__(active)
    active.dock(True)
    full_cargo(active, {'steel': 50}, 1)
    drain(active.plugin)
    active.remote[101] = {'steel': 75}
    write_market_cargo_file(active, monkeypatch, tmp_path, 55, timestamp='2026-11-08T17:00:02Z')
    journal(active, 'MarketBuy', {'steel': 55}, timestamp='2026-11-08T17:00:02Z',
            MarketID=101, Type='steel', Count=5)
    drain(active.plugin)
    store = active.plugin.pending_carrier_deliveries
    assert active.remote[101] == {'steel': 75}
    assert active.ship == {'steel': 55}
    assert active.writes == []
    assert [record['cargo'] for record in store.records('Alpha', 101)] == [{'steel': -5}]
    assert store.inventory_frames() == []
    active.plugin.fc_handler.retry_pending_deliveries()
    drain(active.plugin)
    assert active.remote[101] == {'steel': 70}
    assert store.records() == []
    assert store.inventory_frames() == []


def test_trade_after_valid_sparse_ship_view_publishes_trustworthy_ship_while_bank_waits(
    market_session,
) -> None:
    """Ship freshness advances from a trusted sparse hold while bank attribution stays deferred."""
    active = market_session
    active.dock(True)
    full_cargo(active, {'steel': 50}, 1)
    drain(active.plugin)
    journal(active, 'Cargo', {'steel': 40}, timestamp='2026-11-08T17:00:02Z', Vessel='Ship', Count=40)
    drain(active.plugin)
    assert active.ship == {'steel': 40}
    assert active.remote[101] == {'steel': 75}
    journal(active, 'MarketSell', {'steel': 35}, timestamp='2026-11-08T17:00:03Z',
            MarketID=101, Type='steel', Count=5)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 80}
    assert active.ship == {'steel': 35}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1
    full_cargo(active, {'steel': 35}, 4)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 90}
    assert active.ship == {'steel': 35}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_promotion_preserves_trustworthy_bank_boundary_without_deferred_trades_and_on_relink(
    market_session,
) -> None:
    """Eligibility promotion without deferred trades or after relink preserves bank baseline and coverage."""
    active = market_session
    active.dock(True)
    full_cargo(active, {'steel': 50}, 1)
    drain(active.plugin)
    # Initial promotion with no deferred trades must keep ship=50 as the bank baseline.
    tracker = active.plugin.fc_handler.ship_cargo_tracker
    tracker.promote_to_bank(had_deferred_trades=False)
    full_cargo(active, {'steel': 40}, 2)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 85}

    # Even with had_deferred_trades=True, a trusted bank context must not drop coverage of prior Cargo40.
    tracker.promote_to_bank(had_deferred_trades=True)
    journal(active, 'MarketSell', {'steel': 40}, timestamp='2026-11-08T17:00:02Z',
            MarketID=101, Type='steel', Count=10)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 85}


def test_promoted_tracker_retains_ship_only_changes_for_manual_rebase_and_validates_partial_ship(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Promoted tracker keeps ship-only deltas for manual rebase and rejects inconsistent partial EDMC cargo."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    _parity_market_session.__wrapped__(active)
    active.dock(True)
    tracker = active.plugin.fc_handler.ship_cargo_tracker

    # Simulate discovery completing after a deferred MarketBuy10 with Cargo60, leaving _before=None and _ship=60.
    tracker.reset()
    tracker.process(
        {'event': 'MarketBuy', 'timestamp': '2026-11-08T17:00:01Z', 'MarketID': 101, 'Type': 'steel', 'Count': 10},
        {'ShipType': 'python', 'Cargo': {'steel': 60}},
        {'steel': 60},
        complete=True,
        carrier=False,
        bank=False,
        available=None,
    )
    tracker.promote_to_bank(had_deferred_trades=True)

    # EjectCargo5 without a matching file must be recorded in _ship_known for manual rebase.
    journal(active, 'EjectCargo', {'steel': 55}, timestamp='2026-11-08T17:00:02Z', Type='steel', Count=5)
    # Inconsistent EDMC fallback (40 instead of 50) on MarketSell5 must not be published.
    active.ship = {'steel': 60}
    journal(active, 'MarketSell', {'steel': 40}, timestamp='2026-11-08T17:00:03Z',
            MarketID=101, Type='steel', Count=5)
    drain(active.plugin)
    assert active.ship == {'steel': 60}

    # Manual correction rebases from physical 50 (60 - 5 eject - 5 sell); unchanged Cargo50 emits no phantom deposit.
    handler = active.plugin.fc_handler
    reservation = handler.prepare_manual_manifest(101, {'steel': 125})
    assert handler.save_manual_manifest(101, {'steel': 125}, reservation) == {'steel': 125}
    handler.finish_manual_manifest(reservation)
    full_cargo(active, {'steel': 50}, 4)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 125}


def test_older_collect_cargo_clears_ship_ambiguity_when_funding_window_resolves(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Older CollectCargo reconciled by retry_pending_inventory clears ship ambiguity before manual rebase."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {'steel': 0}
    _parity_market_session.__wrapped__(active)
    active.dock(True)
    full_cargo(active, {'steel': 50}, 1)
    drain(active.plugin)

    # Read-ahead Cargo60@t3 creates a funding window (carrier has 0); older CollectCargo10@t2 explains it.
    full_cargo(active, {'steel': 60}, 3)
    journal(active, 'CollectCargo', {'steel': 60}, timestamp='2026-11-08T17:00:02Z', Type='steel', Count=10)
    drain(active.plugin)
    assert active.plugin.fc_handler.ship_cargo_tracker.retry_pending_inventory(available={'steel': 0}).delta == {}

    # Manual correction to 125 keeps ship60 as the covered point; next real deposit5 credits 130.
    handler = active.plugin.fc_handler
    reservation = handler.prepare_manual_manifest(101, {'steel': 125})
    assert handler.save_manual_manifest(101, {'steel': 125}, reservation) == {'steel': 125}
    handler.finish_manual_manifest(reservation)
    full_cargo(active, {'steel': 55}, 4)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 130}


def test_already_covered_sale_stays_out_of_later_funds_window(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A delayed sale already covered by an accepted bank point does not double-count inside a later funds window."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {'steel': 50, 'copper': 0}
    _parity_market_session.__wrapped__(active)
    active.dock(True)
    full_cargo(active, {'steel': 50}, 1)
    drain(active.plugin)

    # Read-ahead Cargo40@t3 credits steel +10 before MarketSell10@t2 arrives.
    full_cargo(active, {'steel': 40}, 3)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 60, 'copper': 0}

    # Unfunded copper withdrawal opens a funds window at t4.
    full_cargo(active, {'steel': 40, 'copper': 5}, 4)
    drain(active.plugin)

    # Delayed MarketSell10@t2 is already covered by accepted point t3 and must not add another +10 steel.
    journal(active, 'MarketSell', {'steel': 40, 'copper': 5}, timestamp='2026-11-08T17:00:02Z',
            MarketID=101, Type='steel', Count=10)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 60, 'copper': 0}


def test_partial_ship_fallback_includes_intervening_ship_known_and_rejects_negative(
    market_session,
) -> None:
    """Missing state['Cargo'] projects from _ship + _ship_known + current event and rejects negative counts."""
    active = market_session
    active.dock(True)
    full_cargo(active, {'steel': 50}, 1)
    drain(active.plugin)

    # Sparse ship view 40 (no Inventory), then eject 10, then sell 5 with no state['Cargo'] mapping.
    journal(active, 'Cargo', {'steel': 40}, timestamp='2026-11-08T17:00:02Z', Vessel='Ship', Count=40)
    journal(active, 'EjectCargo', {'steel': 30}, timestamp='2026-11-08T17:00:03Z', Type='steel', Count=10)
    active.load.journal_entry(
        'Alpha', False, 'Sol', 'Carrier',
        {'event': 'MarketSell', 'timestamp': '2026-11-08T17:00:04Z', 'MarketID': 101, 'Type': 'steel', 'Count': 5},
        {'Docked': True, 'StationType': 'FleetCarrier', 'MarketID': 101, 'ShipType': 'python'},
    )
    drain(active.plugin)
    assert active.ship == {'steel': 25}

    # Selling more than remaining projected hold (30 > 25) without state['Cargo'] must not publish a negative fallback.
    active.load.journal_entry(
        'Alpha', False, 'Sol', 'Carrier',
        {'event': 'MarketSell', 'timestamp': '2026-11-08T17:00:05Z', 'MarketID': 101, 'Type': 'steel', 'Count': 30},
        {'Docked': True, 'StationType': 'FleetCarrier', 'MarketID': 101, 'ShipType': 'python'},
    )
    drain(active.plugin)
    assert active.ship == {'steel': 25}


def test_consecutive_same_second_station_buys_advance_ship_cargo_without_file(
    market_session,
) -> None:
    """Consecutive same-second non-bank station trades advance ship cargo when no Cargo.json file matches."""
    active = market_session
    active.load.journal_entry(
        'Alpha', False, 'Sol', 'Orbis',
        {'event': 'Docked', 'StationType': 'Orbis', 'StationName': 'Orbis', 'MarketID': 202},
        {'Docked': True, 'StationType': 'Orbis', 'MarketID': 202, 'ShipType': 'python', 'Cargo': {'steel': 10}},
    )
    for after in (11, 12):
        active.load.journal_entry(
            'Alpha', False, 'Sol', 'Orbis',
            {'event': 'MarketBuy', 'timestamp': '2026-11-08T17:00:10Z', 'MarketID': 202, 'Type': 'steel', 'Count': 1},
            {'Docked': True, 'StationType': 'Orbis', 'MarketID': 202, 'ShipType': 'python', 'Cargo': {'steel': after}},
        )
    drain(active.plugin)
    assert active.ship == {'steel': 12}


def test_same_second_collect_cargo_with_read_ahead_file_does_not_infer_carrier_withdrawal(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Two same-second CollectCargo events with read-ahead Cargo.json=12 must not debit carrier stock."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    _parity_market_session.__wrapped__(active)
    active.dock(True)
    full_cargo(active, {'steel': 50}, 1)
    drain(active.plugin)

    write_market_cargo_file(active, monkeypatch, tmp_path, 52, timestamp='2026-11-08T17:00:02Z')
    journal(active, 'CollectCargo', {'steel': 51}, timestamp='2026-11-08T17:00:02Z', Type='steel', Count=1)
    journal(active, 'CollectCargo', {'steel': 52}, timestamp='2026-11-08T17:00:02Z', Type='steel', Count=1)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 75}
    assert active.ship == {'steel': 52}


def test_duplicate_commodity_stacks_in_cargo_event_sum_and_validate_against_count(
    market_session,
) -> None:
    """Duplicate commodity stacks in Cargo Inventory sum cleanly and validate against Count."""
    active = market_session
    active.dock(True)
    active.load.journal_entry(
        'Alpha', False, 'Sol', 'Carrier',
        {
            'event': 'Cargo',
            'timestamp': '2026-11-08T17:00:01Z',
            'Vessel': 'Ship',
            'Count': 10,
            'Inventory': [{'Name': 'steel', 'Count': 4}, {'Name': 'steel', 'Count': 6}],
        },
        {'Docked': True, 'StationType': 'FleetCarrier', 'MarketID': 101, 'ShipType': 'python', 'Cargo': {'steel': 10}},
    )
    drain(active.plugin)
    assert active.ship == {'steel': 10}
    assert active.plugin.fc_handler.ship_cargo_tracker._before == {'steel': 10}


def test_funds_window_advancing_cargo_file_on_collect_cargo_does_not_emit_phantom_deposit(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Advancing Cargo.json from 51 to 52 during same-second CollectCargo in a funds window emits no phantom +1."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {'steel': 0}
    _parity_market_session.__wrapped__(active)
    active.dock(True)
    full_cargo(active, {'steel': 50}, 1)
    drain(active.plugin)

    # Read-ahead Cargo51@T opens a funds window because carrier has 0 steel.
    full_cargo(active, {'steel': 51}, 2)
    # Cargo.json advances to 52@T including two CollectCargo1 callbacks.
    write_market_cargo_file(active, monkeypatch, tmp_path, 52, timestamp='2026-11-08T17:00:02Z')
    journal(active, 'CollectCargo', {'steel': 51}, timestamp='2026-11-08T17:00:02Z', Type='steel', Count=1)
    journal(active, 'CollectCargo', {'steel': 52}, timestamp='2026-11-08T17:00:02Z', Type='steel', Count=1)
    drain(active.plugin)

    # Retry with carrier=0 must not compute 50 - 51 + 2 = +1 phantom deposit.
    assert active.plugin.fc_handler.ship_cargo_tracker.retry_pending_inventory(available={'steel': 0}) is None
    assert active.remote[101] == {'steel': 0}

    # Next fresh Cargo52@T+1 reconciles cleanly to zero.
    full_cargo(active, {'steel': 52}, 3)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 0}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_revoke_deferred_same_second_buy_relink_does_not_double_debit_and_keeps_prior_coverage(
    market_session,
) -> None:
    """Deferred same-second MarketBuy while link is revoked quarantines _before on relink without losing coverage."""
    active = market_session
    active.dock(True)
    full_cargo(active, {'steel': 50}, 1)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 75}

    handler = active.plugin.fc_handler
    tracker = handler.ship_cargo_tracker

    # Simulate link revocation without undocking and a same-second MarketBuy10 with no Cargo.json.
    tracker.process(
        {'event': 'MarketBuy', 'timestamp': '2026-11-08T17:00:01Z', 'MarketID': 101, 'Type': 'steel', 'Count': 10},
        {'ShipType': 'python', 'Cargo': {'steel': 60}},
        None,
        complete=False,
        carrier=False,
        bank=False,
        available=None,
    )
    # Relink releases deferred -10 (modeled by promote_to_bank(had_deferred_trades=True)).
    tracker.promote_to_bank(had_deferred_trades=True)

    # Prior covered sale at T1 must not re-credit; Cargo60@T+1 must seed baseline without inferring another -10.
    delayed = tracker.process(
        {'event': 'MarketSell', 'timestamp': '2026-11-08T17:00:01Z', 'MarketID': 101, 'Type': 'steel', 'Count': 10},
        {'ShipType': 'python', 'Cargo': {'steel': 50}},
        None,
        complete=False,
        carrier=True,
        bank=True,
        available={'steel': 65},
    )
    assert delayed.delta == {}
    next_snap = tracker.process(
        {'event': 'Cargo', 'timestamp': '2026-11-08T17:00:02Z', 'Vessel': 'Ship', 'Count': 60,
         'Inventory': [{'Name': 'steel', 'Count': 60}]},
        {'ShipType': 'python', 'Cargo': {'steel': 60}},
        {'steel': 60},
        complete=True,
        carrier=True,
        bank=True,
        available={'steel': 65},
    )
    assert next_snap.delta == {}


def test_partial_trade_and_unknown_origin_seed_do_not_falsely_cover_later_trades_after_promotion(
    market_session,
) -> None:
    """Partial points and _seed_baseline() must not suppress uncredited trades across revoke/relink promotion."""
    active = market_session
    active.dock(True)
    tracker = active.plugin.fc_handler.ship_cargo_tracker

    # Case 1: Partial Buy10@T -> revoke -> Buy10@T -> relink -> third Buy10@T must still report -10.
    tracker.reset({'steel': 50})
    first = tracker.process(
        {'event': 'MarketBuy', 'timestamp': '2026-11-08T17:00:01Z', 'MarketID': 101, 'Type': 'steel', 'Count': 10},
        {'ShipType': 'python', 'Cargo': {'steel': 60}},
        None,
        complete=False,
        carrier=True,
        bank=True,
        available={'steel': 100},
    )
    assert first.delta == {'steel': -10}
    tracker.process(
        {'event': 'MarketBuy', 'timestamp': '2026-11-08T17:00:01Z', 'MarketID': 101, 'Type': 'steel', 'Count': 10},
        {'ShipType': 'python', 'Cargo': {'steel': 70}},
        None,
        complete=False,
        carrier=False,
        bank=False,
        available=None,
    )
    tracker.promote_to_bank(had_deferred_trades=True)
    third = tracker.process(
        {'event': 'MarketBuy', 'timestamp': '2026-11-08T17:00:01Z', 'MarketID': 101, 'Type': 'steel', 'Count': 10},
        {'ShipType': 'python', 'Cargo': {'steel': 80}},
        None,
        complete=False,
        carrier=True,
        bank=True,
        available={'steel': 80},
    )
    assert third.delta == {'steel': -10}

    # Case 2: Unknown origin -> seed Cargo50@T3 -> revoke/Buy10@T1 -> relink -> Sell5@T2 must still report +5.
    tracker.reset(None)
    seed = tracker.process(
        {'event': 'Cargo', 'timestamp': '2026-11-08T17:00:03Z', 'Vessel': 'Ship', 'Count': 50,
         'Inventory': [{'Name': 'steel', 'Count': 50}]},
        {'ShipType': 'python', 'Cargo': {'steel': 50}},
        {'steel': 50},
        complete=True,
        carrier=True,
        bank=True,
        available={'steel': 100},
    )
    assert seed.delta == {}
    tracker.process(
        {'event': 'MarketBuy', 'timestamp': '2026-11-08T17:00:01Z', 'MarketID': 101, 'Type': 'steel', 'Count': 10},
        {'ShipType': 'python', 'Cargo': {'steel': 60}},
        None,
        complete=False,
        carrier=False,
        bank=False,
        available=None,
    )
    tracker.promote_to_bank(had_deferred_trades=True)
    sell = tracker.process(
        {'event': 'MarketSell', 'timestamp': '2026-11-08T17:00:02Z', 'MarketID': 101, 'Type': 'steel', 'Count': 5},
        {'ShipType': 'python', 'Cargo': {'steel': 45}},
        None,
        complete=False,
        carrier=True,
        bank=True,
        available={'steel': 90},
    )
    assert sell.delta == {'steel': 5}
