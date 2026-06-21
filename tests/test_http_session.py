"""Tests for http_session.new_http_session fallback behavior."""

from __future__ import annotations

import sys
import types

import http_session


def test_new_http_session_uses_timeout_session_when_available(monkeypatch):
    calls: list[int] = []

    fake_mod = types.ModuleType("timeout_session")

    def _new_session(timeout=10):
        calls.append(timeout)
        return object()

    fake_mod.new_session = _new_session
    monkeypatch.setitem(sys.modules, "timeout_session", fake_mod)

    session = http_session.new_http_session(timeout=15)

    assert session is not None
    assert calls == [15]


def test_new_http_session_falls_back_to_requests_without_edmc(monkeypatch):
    monkeypatch.delitem(sys.modules, "timeout_session", raising=False)

    session = http_session.new_http_session(timeout=12)

    assert session.__class__.__name__ == "Session"
