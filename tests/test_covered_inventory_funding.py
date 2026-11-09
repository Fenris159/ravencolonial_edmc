"""Retry funded old ship-only corrections without reopening retired physical intervals."""

from types import SimpleNamespace

import pytest

from test_carrier_cargo_parity import drain, session as _session_fixture
from test_mixed_inventory_attribution import inventory, journal


def pending_trades(edmc_plugin, monkeypatch: pytest.MonkeyPatch, *, unknown_origin: bool = False) -> SimpleNamespace:
    """Queue a backing sale and reserved purchase after establishing one physical ten-tonne credit."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"steel": 0}
    active.journal("Loadout", Ship="python", CargoCapacity=100, Modules=[])
    active.dock(True)
    if unknown_origin:
        journal(active, "LoadGame", {})
    inventory(active, 50, 0, 0)
    inventory(active, 40, 0, 2)
    drain(active.plugin)
    active.journal("MarketSell", 30, timestamp="2026-11-08T17:00:03Z", MarketID=101, Type="steel", Count=10)
    active.journal("MarketBuy", 40, timestamp="2026-11-08T17:00:04Z", MarketID=101, Type="steel", Count=10)
    return active


@pytest.mark.parametrize("active_anchor, hold, expected, rearm", [
    (False, 40, 5, False), (True, 35, 10, False), (False, 40, 5, True),
])
def test_a_positive_acknowledgement_releases_a_reserved_ship_only_correction(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, active_anchor: bool, hold: int, expected: int, rearm: bool,
) -> None:
    """A reserved purchase defers the old debit; the preceding sale funds it without another inventory."""
    active = pending_trades(edmc_plugin, monkeypatch)
    if active_anchor:
        inventory(active, 35, 0, 5)
    journal(active, "EjectCargo", {"steel": hold - 5},
            timestamp=f"2026-11-08T17:00:0{4 if active_anchor else 1}Z", Type="steel", Count=5)
    if rearm:
        journal(active, "CollectCargo", {"steel": hold + 5}, timestamp="2026-11-08T17:00:01Z", Type="steel", Count=5)
        journal(active, "EjectCargo", {"steel": hold - 5}, timestamp="2026-11-08T17:00:01Z", Type="steel", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"steel": expected}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []
    inventory(active, hold, 0, 6)
    drain(active.plugin)
    assert active.remote[101] == {"steel": expected}
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


def test_releasing_mixed_age_corrections_consumes_only_the_active_anchor_portion(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retired five and active five cannot leave active credit that a later ejection debits again."""
    active = pending_trades(edmc_plugin, monkeypatch)
    inventory(active, 35, 0, 5)
    for second in (1, 4):
        journal(active, "EjectCargo", {"steel": 30}, timestamp=f"2026-11-08T17:00:0{second}Z",
                Type="steel", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 5}
    journal(active, "EjectCargo", {"steel": 30}, timestamp="2026-11-08T17:00:05Z", Type="steel", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 5}
    inventory(active, 30, 0, 6)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 5}


def test_releasing_a_retired_correction_updates_the_unknown_origin_credit_once(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later origin-time sale cannot retract the five-tonne correction already released after ACK."""
    active = pending_trades(edmc_plugin, monkeypatch, unknown_origin=True)
    journal(active, "EjectCargo", {"steel": 35}, timestamp="2026-11-08T17:00:01Z", Type="steel", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 5}
    active.journal("MarketSell", 35, timestamp="2026-11-08T17:00:00Z", MarketID=101, Type="steel", Count=5)
    drain(active.plugin)
    assert active.remote[101] == {"steel": 5}
