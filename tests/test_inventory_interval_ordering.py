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
