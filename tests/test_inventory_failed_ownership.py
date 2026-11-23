"""Retain ownership when a full carrier target is replaced in memory before a failed disk commit."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from conftest import settle_commander_links
from test_carrier_cargo_parity import drain
from test_inventory_frame_recovery import inventory_session as _inventory_fixture


@pytest.fixture
def failed_write_session(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Use the actual recovery store, journal hook, and HTTP boundary with a frozen clock."""
    return _inventory_fixture.__wrapped__(edmc_plugin, monkeypatch)


def fail_next_recovery_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail exactly one authoritative atomic filesystem commit, then restore storage availability."""
    replace = Path.replace
    unavailable = [True]

    def replace_once(path: Path, target: Any) -> Any:
        if Path(target).name == "RavenColonial.carrier-cargo-recovery.json" and unavailable[0]:
            unavailable[0] = False
            raise OSError("temporary recovery checkpoint failure")
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", replace_once)


def test_restored_retired_owner_recovers_a_successor_target_after_checkpoint_failure(
    failed_write_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A restored90 target promoted in memory must still finish90 plus its subsequent two-tonne delivery."""
    active = failed_write_session
    active.dock(False)
    store = active.plugin.pending_carrier_deliveries
    store.configure(str(tmp_path))
    store.begin_replacement("Alpha", 101, {"steel": 90}, [], attempted=False)
    store.begin_replacement("Alpha", 101, {"steel": 90}, [], attempted=False)
    store.record("Alpha", 101, {"steel": 2})
    active.plugin.configure_pending_carrier_deliveries(str(tmp_path))
    owner = active.plugin._pending_link_handlers[-1]
    assert owner.initialize_fcs("Alpha") is True
    fail_next_recovery_commit(monkeypatch)
    owner.retry_pending_deliveries()
    assert active.remote[101] == {"steel": 75}
    owner.retry_pending_deliveries()
    drain(active.plugin)
    assert active.remote[101] == {"steel": 92}
    assert store.replacements() == []
    assert store.records() == []


def test_frame_free_target_first_reserved_after_retirement_recovers_from_checkpoint_failure(
    failed_write_session: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A queued full write must retain recovery ownership even when its first reservation fails after retirement."""
    active = failed_write_session
    active.dock(False)
    active.plugin.configure_pending_carrier_deliveries(str(tmp_path))
    owner = active.plugin.fc_handler
    owner._update_fc_cargo_async(101, {"steel": 90})
    active.journal("MarketSell", 48, MarketID=101, Type="steel", Count=2)
    active.load.journal_entry("Bravo", False, "Sol", "", {"event": "LoadGame"}, {})
    settle_commander_links(active.plugin)
    fail_next_recovery_commit(monkeypatch)
    drain(active.plugin)
    owner.retry_pending_deliveries()
    drain(active.plugin)
    assert active.remote[101] == {"steel": 92}
    assert active.plugin.pending_carrier_deliveries.replacements() == []
    assert active.plugin.pending_carrier_deliveries.records() == []
