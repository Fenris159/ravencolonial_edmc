"""Keep accepted full targets and settled physical-interval credits in observation order."""

import threading
from types import SimpleNamespace

import pytest

from test_carrier_cargo_parity import drain, market_session as _market_fixture, session as _session_fixture


def prepare_session(edmc_plugin, monkeypatch: pytest.MonkeyPatch, stock: int) -> SimpleNamespace:
    """Set initial server stock before the first real commander lookup establishes its baseline."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {"steel": stock}
    return _market_fixture.__wrapped__(active)


@pytest.mark.parametrize("during_preflight", [False, True])
def test_new_reserved_snapshot_wins_over_an_older_frame_free_target(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, during_preflight: bool,
) -> None:
    """The older90 seed cannot replace newer105 or claim its bank-recovery coverage."""
    active = prepare_session(edmc_plugin, monkeypatch, 75)
    active.dock(True)
    handler = active.plugin.fc_handler
    handler.update_fc_cargo_from_capi(101, {"steel": 90}, "2026-11-08T17:00:01Z", was_docked=False)
    entered, release = threading.Event(), threading.Event()
    errors = []
    worker = None
    get_fc = active.plugin.api_client.get_fc

    def preflight(mid: int) -> dict:
        result = get_fc(mid)
        if not entered.is_set():
            entered.set()
            assert release.wait(timeout=3)
        return result

    def work() -> None:
        try:
            drain(active.plugin)
        except BaseException as error:
            errors.append(error)

    if during_preflight:
        monkeypatch.setattr(active.plugin.api_client, "get_fc", preflight)
        worker = threading.Thread(target=work)
        worker.start()
    try:
        if worker is not None:
            assert entered.wait(timeout=3)
        active.journal("Cargo", 40, timestamp="2026-11-08T17:00:02Z", Vessel="Ship", Count=40,
                       Inventory=[{"Name": "steel", "Count": 40}])
        active.journal("MarketSell", 35, timestamp="2026-11-08T17:00:02Z", MarketID=101, Type="steel", Count=5)
        handler.update_fc_cargo_from_capi(101, {"steel": 105}, "2026-11-08T17:00:04Z", was_docked=False)
    finally:
        release.set()
        if worker is not None:
            worker.join(timeout=3)
    assert worker is None or not worker.is_alive()
    assert errors == []
    drain(active.plugin)
    assert active.remote[101] == {"steel": 105}
    assert active.plugin.pending_carrier_deliveries.records() == []
    assert active.plugin.pending_carrier_deliveries.replacements() == []
    assert active.plugin.pending_carrier_deliveries.inventory_frames() == []


@pytest.mark.parametrize("stock, first, second, event, counts, final_hold, expected", [
    (20, 60, 55, "MarketBuy", (10,), 60, 10),
    (20, 60, 55, "MarketBuy", (6, 4), 60, 10),
    (0, 50, 45, "MarketSell", (5,), 50, 0),
])
def test_late_trade_uses_the_credit_from_its_own_physical_interval(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, stock: int, first: int, second: int,
    event: str, counts: tuple[int, ...], final_hold: int, expected: int,
) -> None:
    """A settled buy cannot enter the next anchor, while a zero-net earlier interval stays correct."""
    active = prepare_session(edmc_plugin, monkeypatch, stock)
    active.dock(True)
    for amount, stamp in ((first, 1), (second, 2)):
        active.journal("Cargo", amount, timestamp=f"2026-11-08T17:00:0{stamp}Z", Vessel="Ship", Count=amount,
                       Inventory=[{"Name": "steel", "Count": amount}])
        drain(active.plugin)
    for count in counts:
        active.journal(event, second, timestamp="2026-11-08T17:00:01Z", MarketID=101, Type="steel", Count=count)
    active.journal("MarketBuy", final_hold, timestamp="2026-11-08T17:00:02Z", MarketID=101,
                   Type="steel", Count=5)
    active.journal("Cargo", final_hold, timestamp="2026-11-08T17:00:03Z", Vessel="Ship", Count=final_hold,
                   Inventory=[{"Name": "steel", "Count": final_hold}])
    drain(active.plugin)
    assert active.remote[101] == {"steel": expected}
