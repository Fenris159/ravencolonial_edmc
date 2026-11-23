"""Cover old raw cargo attribution without discarding later physical movement."""

from types import SimpleNamespace

import pytest
import requests

from test_carrier_cargo_parity import (
    drain, market_session as _market_fixture, session as _session_fixture,
)
from carrier_test_support import journal


def cargo(active: SimpleNamespace, key: str, amount: int, second: int) -> None:
    """Deliver a full ship inventory at the game-file boundary."""
    journal(active, "Cargo", {key: amount}, timestamp=f"2026-11-08T17:00:0{second}Z", Vessel="Ship",
            Count=amount, Inventory=[{"Name": key, "Count": amount}])


def setup_ship(edmc_plugin, monkeypatch: pytest.MonkeyPatch, key: str, stock: int) -> SimpleNamespace:
    """Establish the initial carrier and ship inventories before introducing raw inference."""
    active = _session_fixture.__wrapped__(edmc_plugin, monkeypatch)
    active.remote[101] = {key: stock}
    _market_fixture.__wrapped__(active)
    journal(active, "Location", {key: 20 if key == "drones" else 50}, Docked=True,
            StationType="FleetCarrier", MarketID=101, StationServices=["squadronBank"])
    cargo(active, key, 20 if key == "drones" else 50, 0)
    drain(active.plugin)
    return active


@pytest.mark.parametrize("initial, target, new_ship_only, expected", [
    (0, 10, False, 15), (20, 20, False, 25), (0, 10, True, 10),
])
def test_new_physical_evidence_survives_the_manual_http_completion(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, initial: int, target: int, new_ship_only: bool, expected: int,
) -> None:
    """The next bank5 survives, and a later journal can still classify evidence observed during the write."""
    active = setup_ship(edmc_plugin, monkeypatch, "steel", initial)
    cargo(active, "steel", 40, 1)
    drain(active.plugin)
    handler = active.plugin.fc_handler
    identity = handler.prepare_manual_manifest(101, {"steel": target})
    request = active.plugin.api_client.session.request

    def reply_after_new_cargo(method: str, url: str, **kwargs) -> requests.Response:
        response = request(method, url, **kwargs)
        if method == "POST" and url.endswith("/cargo"):
            cargo(active, "steel", 35, 2)
        return response

    monkeypatch.setattr(active.plugin.api_client.session, "request", reply_after_new_cargo)
    assert handler.save_manual_manifest(101, {"steel": target}, identity) == {"steel": target}
    handler.finish_manual_manifest(identity)
    drain(active.plugin)
    if new_ship_only:
        journal(active, "EjectCargo", {"steel": 30}, timestamp="2026-11-08T17:00:02Z", Type="steel", Count=5)
        cargo(active, "steel", 35, 3)
        drain(active.plugin)
    assert active.remote[101] == {"steel": expected}
    assert active.plugin.pending_carrier_deliveries.records() == []
