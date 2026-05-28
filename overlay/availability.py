"""Detect whether EDMC Modern Overlay is installed and accepting messages."""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

MODERN_OVERLAY_REPO_URL = "https://github.com/SweetJonnySauce/EDMCModernOverlay"

_PROBE_MESSAGE_ID = "ravencolonial-overlay-dependency-probe"


class OverlayDependencyStatus(str, Enum):
    OK = "ok"
    PACKAGE_MISSING = "package_missing"
    PLUGIN_NOT_RUNNING = "plugin_not_running"


def _probe_payload() -> Mapping[str, Any]:
    return {
        "event": "LegacyOverlay",
        "type": "legacy_clear",
        "id": _PROBE_MESSAGE_ID,
        "ttl": 0,
    }


def get_overlay_dependency_status() -> OverlayDependencyStatus:
    """
    Return whether the Modern Overlay compatibility stack is present and live.

    ``PACKAGE_MISSING`` — ``overlay_plugin`` / EDMCModernOverlay not on the path.
    ``PLUGIN_NOT_RUNNING`` — package importable but the overlay plugin is not publishing.
    """
    try:
        from overlay_plugin import overlay_api  # type: ignore[import-untyped]
    except ImportError:
        return OverlayDependencyStatus.PACKAGE_MISSING

    try:
        accepted = bool(overlay_api.send_overlay_message(_probe_payload()))
    except Exception:
        return OverlayDependencyStatus.PLUGIN_NOT_RUNNING

    if accepted:
        return OverlayDependencyStatus.OK
    return OverlayDependencyStatus.PLUGIN_NOT_RUNNING


def overlay_dependency_satisfied() -> bool:
    return get_overlay_dependency_status() == OverlayDependencyStatus.OK
