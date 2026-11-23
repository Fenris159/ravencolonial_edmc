"""Require confirmed stock before a queued withdrawal can begin its HTTP attempt."""

from pathlib import Path

import pytest


@pytest.mark.parametrize("before, confirmed, amount, allowed", [
    (None, None, -5, False), ({}, None, -5, False), ({"steel": 4}, None, -5, False),
    ({"steel": 5}, None, -5, True), ({"steel": 15}, {"steel": 4}, -5, False),
    ({"steel": 0}, {"steel": 5}, -5, True), (None, None, 5, True),
])
def test_a_queued_withdrawal_waits_for_sufficient_confirmed_stock_without_losing_its_identity(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    before, confirmed, amount: int, allowed: bool,
) -> None:
    """Keep unfundable debits unattempted across restart, while allowing exact funding and startup deposits."""
    load, _ = edmc_plugin
    monkeypatch.setattr("time.time", lambda: 1000.0)
    store = load.PendingCarrierDeliveries()
    store.configure(str(tmp_path))
    identity = store.record("Alpha", 101, {"steel": amount})
    if confirmed is not None:
        store.remember_cargo(101, confirmed, written=True)
    assert store.begin(identity, before) is allowed
    record, = store.records("Alpha", 101)
    assert record["id"] == identity
    assert record["cargo"] == {"steel": amount}
    assert record["attempted"] is allowed
    assert record["uncertain"] is allowed
    assert record["before"] == ((confirmed if confirmed is not None else before) if allowed else None)
    restored = load.PendingCarrierDeliveries()
    restored.configure(str(tmp_path))
    assert restored.records("Alpha", 101) == [record]
    if not allowed:
        assert restored.begin(identity, {"steel": 5}) is True
        retained, = restored.records("Alpha", 101)
        assert retained["id"] == identity
        assert retained["before"] == {"steel": 5}
