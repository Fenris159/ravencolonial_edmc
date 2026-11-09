"""Keep one uncertain interval until fresh evidence or an authoritative correction resolves it."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import settle_commander_links
from test_carrier_cargo_parity import (
    drain, market_session as _market_fixture, session as _session_fixture, write_market_cargo_file,
)


@pytest.fixture
def market_session(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Use the existing real journal and HTTP fixture through its adapter."""
    return _market_fixture.__wrapped__(_session_fixture.__wrapped__(edmc_plugin, monkeypatch))


def cargo(active: SimpleNamespace, amount: int, second: int) -> None:
    """Deliver a complete main-ship point through the public journal hook."""
    active.journal('Cargo', amount, timestamp=f'2026-11-08T17:00:0{second}Z', Vessel='Ship', Count=amount,
                   Inventory=[{'Name': 'steel', 'Count': amount}] if amount else [])


def test_ambiguous_trade_waits_for_a_new_complete_point_without_double_publishing(
    market_session: SimpleNamespace,
) -> None:
    """Bank10 is already certain; a same-second sale5 waits, then reaches90 exactly once."""
    active = market_session
    active.dock(True)
    cargo(active, 40, 2)
    active.journal('MarketSell', 35, timestamp='2026-11-08T17:00:02Z', MarketID=101, Type='steel', Count=5)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 85}
    assert active.ship == {'steel': 40}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1
    cargo(active, 35, 3)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 90}
    assert active.ship == {'steel': 35}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_unknown_ship_activity_cannot_turn_an_unfunded_withdrawal_into_stock(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A collected ten explains ship50→60; an empty carrier neither clamps a debit nor receives a refund."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {'steel': 0}
    _market_fixture.__wrapped__(active)
    active.dock(True)
    cargo(active, 60, 2)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 0}
    assert active.writes == []
    assert active.ship == {'steel': 60}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1
    active.journal('CollectCargo', 70, timestamp='2026-11-08T17:00:01Z', Type='steel', Count=10)
    cargo(active, 60, 3)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 0}
    assert active.writes == []
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_context_changes_preserve_uncertainty_until_a_full_correction(
    market_session: SimpleNamespace, tmp_path: Path,
) -> None:
    """A restarted dock cannot replay old inference; full125 retires it and the next sale2 reaches127."""
    active = market_session
    active.plugin.configure_pending_carrier_deliveries(str(tmp_path))
    active.dock(True)
    cargo(active, 40, 2)
    active.journal('MarketSell', 35, timestamp='2026-11-08T17:00:02Z', MarketID=101, Type='steel', Count=5)
    drain(active.plugin)
    frame, = active.plugin.pending_carrier_deliveries.inventory_frames('Alpha', 101)
    restored = active.load.PendingCarrierDeliveries()
    restored.configure(str(tmp_path))
    assert restored.inventory_frames('Alpha', 101) == [frame]
    for commander in ('Bravo', 'Alpha'):
        active.load.journal_entry(commander, False, 'Sol', '', {'event': 'LoadGame'}, {})
        settle_commander_links(active.plugin)
    active.journal('Location', 35, Docked=True, StationType='FleetCarrier', MarketID=101,
                   StationServices=['squadronBank'])
    cargo(active, 35, 3)
    active.journal('MarketSell', 30, timestamp='2026-11-08T17:00:04Z', MarketID=101, Type='steel', Count=5)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 85}
    assert active.plugin.pending_carrier_deliveries.inventory_frames('Alpha', 101) == [frame]
    handler = active.plugin.fc_handler
    identity = handler.prepare_manual_manifest(101, {'steel': 125})
    assert handler.save_manual_manifest(101, {'steel': 125}, identity) == {'steel': 125}
    handler.finish_manual_manifest(identity)
    active.journal('MarketSell', 28, timestamp='2026-11-08T17:00:05Z', MarketID=101, Type='steel', Count=2)
    cargo(active, 28, 6)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 127}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
    assert active.plugin.pending_carrier_deliveries.records() == []


@pytest.mark.parametrize('event', ['EjectCargo', 'MarketSell'])
def test_ambiguous_manual_boundary_remains_a_barrier_until_authoritative_resync(
    market_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, event: str,
) -> None:
    """A same-second ship-only callback cannot undo125; a full resync resumes later bank deposits."""
    active = market_session
    active.dock(True)
    cargo(active, 40, 2)
    drain(active.plugin)
    handler = active.plugin.fc_handler
    identity = handler.prepare_manual_manifest(101, {'steel': 125})
    assert handler.save_manual_manifest(101, {'steel': 125}, identity) == {'steel': 125}
    handler.finish_manual_manifest(identity)
    if event == 'MarketSell':
        write_market_cargo_file(active, monkeypatch, tmp_path, 35)
    active.journal(event, 35, timestamp='2026-11-08T17:00:02Z', MarketID=101, Type='steel', Count=5)
    cargo(active, 35, 3)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 125}
    assert len(active.plugin.pending_carrier_deliveries.inventory_frames()) == 1
    identity = handler.prepare_manual_manifest(101, {'steel': 125})
    assert handler.save_manual_manifest(101, {'steel': 125}, identity) == {'steel': 125}
    handler.finish_manual_manifest(identity)
    cargo(active, 35, 4)
    cargo(active, 30, 5)
    drain(active.plugin)
    assert active.remote[101] == {'steel': 130}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
