"""HTTP session factory for background workers (EDMC timeout_session with test fallback)."""

from __future__ import annotations

from typing import Any


def new_http_session(timeout: int = 15) -> Any:
    """Return EDMC ``timeout_session`` when available, else ``requests.Session`` for tests."""
    try:
        import timeout_session
    except ImportError:  # pragma: no cover - unit tests / IDE without EDMC runtime
        import requests

        return requests.Session()
    return timeout_session.new_session(timeout=timeout)
