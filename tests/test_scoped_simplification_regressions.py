"""Protect the ordinary FIFO transitions identified in the scoped simplification review."""

from pathlib import Path

import pytest

from carrier_test_support import full_cargo, journal, placement_session
from test_carrier_cargo_parity import drain, start_squadron_session, write_market_cargo_file
from test_conservative_inventory_window import market_session as _market_fixture


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
