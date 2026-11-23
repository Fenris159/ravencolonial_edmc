"""Recover refused startup withdrawals after temporary or stale carrier baseline reads."""

from pathlib import Path
from typing import Optional

import pytest
import requests

from test_carrier_cargo_parity import drain
from carrier_test_support import placement_session
from carrier_test_support import journal


@pytest.mark.parametrize("initial", [None, {"marketId": 101, "cargo": {"drones": 4, "steel": 0}}])
def test_recovery_refreshes_refused_stock_and_releases_the_original_ordered_deliveries(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, initial: Optional[dict[str, object]],
) -> None:
    """Retry an unfunded debit after a valid read, then deliver the following deposit without another GET."""
    monkeypatch.setattr("time.time", lambda: 1000.0)
    active = placement_session(edmc_plugin, monkeypatch, tmp_path, 20, 75, unknown=True)
    monkeypatch.setattr("time.monotonic", lambda: -1.0)
    active.plugin.pending_carrier_deliveries.configure(str(tmp_path))
    replies = [initial, {"marketId": 303, "cargo": {"drones": 75, "steel": 0}},
               {"marketId": 101, "cargo": {"drones": 75, "steel": 0}}]

    def get_carrier(mid: int) -> Optional[dict[str, object]]:
        if not replies:
            raise requests.ConnectionError("baseline endpoint unavailable again")
        return replies.pop(0)

    monkeypatch.setattr(active.plugin.api_client, "get_fc", get_carrier)
    journal(active, "MarketBuy", {"drones": 25, "steel": 10}, timestamp="2026-11-08T17:00:01Z",
            MarketID=101, Type="drones", Count=5)
    journal(active, "MarketSell", {"drones": 23, "steel": 10}, timestamp="2026-11-08T17:00:02Z",
            MarketID=101, Type="drones", Count=2)
    drain(active.plugin)
    store = active.plugin.pending_carrier_deliveries
    original = store.records("Alpha", 101)
    assert [record["cargo"] for record in original] == [{"drones": -5}, {"drones": 2}]
    assert [record["attempted"] for record in original] == [False, False]
    assert active.remote[101] == {"drones": 75, "steel": 0}

    active.plugin.fc_handler.retry_pending_deliveries()
    drain(active.plugin)
    assert active.remote[101] == {"drones": 75, "steel": 0}
    assert store.records("Alpha", 101) == original
    active.plugin.fc_handler.retry_pending_deliveries()
    drain(active.plugin)
    assert active.remote[101] == {"drones": 72, "steel": 0}
    assert store.records("Alpha", 101) == []
    restored = active.load.PendingCarrierDeliveries()
    restored.configure(str(tmp_path))
    assert restored.records("Alpha", 101) == []
