"""Unit tests for targeted v2 system-site PATCH (run: python tests/test_api_client_patch_site.py)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if "timeout_session" not in sys.modules:
    timeout_session = types.ModuleType("timeout_session")

    class _FakeSession:
        def __init__(self) -> None:
            self.headers = {}

    timeout_session.new_session = lambda timeout=10: _FakeSession()
    sys.modules["timeout_session"] = timeout_session

if "config" not in sys.modules:
    config = types.ModuleType("config")
    config.appname = "EDMC"
    sys.modules["config"] = config

from api import client as api_client  # noqa: E402


class _FakeResponse:
    status_code = 200
    text = "{}"

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {}


def test_patch_system_site_market_id_only() -> None:
    calls = []

    def fake_request(session, method, url, **kwargs):
        calls.append((session, method, url, kwargs))
        return _FakeResponse()

    original = api_client._http_request_with_retry
    api_client._http_request_with_retry = fake_request
    try:
        client = api_client.RavencolonialAPIClient("https://example.invalid", "ua")
        client.api_key = "secret"
        result = client.patch_system_site(123456789, "x1777344555521", market_id=4310555555)
    finally:
        api_client._http_request_with_retry = original

    assert result == {}
    assert len(calls) == 1
    _session, method, url, kwargs = calls[0]
    assert method == "PATCH"
    assert url == "https://example.invalid/api/v2/system/123456789/sites/x1777344555521"
    assert kwargs["json"] == {"marketId": 4310555555}
    assert "name" not in kwargs["json"]
    assert kwargs["headers"] == {"rcc-key": "secret"}


def test_patch_system_site_escapes_site_id() -> None:
    calls = []

    def fake_request(session, method, url, **kwargs):
        calls.append(url)
        return _FakeResponse()

    original = api_client._http_request_with_retry
    api_client._http_request_with_retry = fake_request
    try:
        client = api_client.RavencolonialAPIClient("https://example.invalid", "ua")
        client.api_key = "secret"
        client.patch_system_site(123456789, "&4310842115", market_id=4310842115)
    finally:
        api_client._http_request_with_retry = original

    assert calls == ["https://example.invalid/api/v2/system/123456789/sites/%264310842115"]


def test_patch_system_site_name_only() -> None:
    calls = []

    def fake_request(session, method, url, **kwargs):
        calls.append(kwargs)
        return _FakeResponse()

    original = api_client._http_request_with_retry
    api_client._http_request_with_retry = fake_request
    try:
        client = api_client.RavencolonialAPIClient("https://example.invalid", "ua")
        client.api_key = "secret"
        client.patch_system_site(123456789, "x1777344555521", name="Dampier Gateway")
    finally:
        api_client._http_request_with_retry = original

    assert len(calls) == 1
    assert calls[0]["json"] == {"name": "Dampier Gateway"}
    assert "marketId" not in calls[0]["json"]


if __name__ == "__main__":
    test_patch_system_site_market_id_only()
    test_patch_system_site_escapes_site_id()
    test_patch_system_site_name_only()
    print("test_api_client_patch_site: OK")
