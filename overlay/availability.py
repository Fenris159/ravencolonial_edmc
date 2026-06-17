"""Detect whether EDMC Modern Overlay is installed and accepting messages."""

from __future__ import annotations

import logging
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

MODERN_OVERLAY_REPO_URL = "https://github.com/SweetJonnySauce/EDMCModernOverlay"

_PROBE_MESSAGE_ID = "ravencolonial-overlay-dependency-probe"
logger = logging.getLogger(__name__)


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


def import_overlay_api() -> Any:
    """Import EDMCModernOverlay's API, discovering Linux/sibling plugin layouts if needed."""
    try:
        from overlay_plugin import overlay_api  # type: ignore[import-untyped]

        return overlay_api
    except ImportError as first_error:
        _add_discovered_modern_overlay_paths()
        try:
            from overlay_plugin import overlay_api  # type: ignore[import-untyped]

            return overlay_api
        except ImportError:
            raise first_error


def _add_discovered_modern_overlay_paths() -> None:
    for path in _discover_modern_overlay_package_roots():
        path_text = str(path)
        if path_text not in sys.path:
            sys.path.append(path_text)
            logger.info("Discovered EDMCModernOverlay API path: %s", path_text)


def _discover_modern_overlay_package_roots() -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()

    for parent in _candidate_plugin_parents():
        for candidate in (parent, *_safe_children(parent)):
            try:
                root = candidate.resolve()
            except OSError:
                continue
            if root in seen:
                continue
            seen.add(root)
            if _has_overlay_api_package(root):
                found.append(root)

    return found


def _candidate_plugin_parents() -> list[Path]:
    candidates: list[Path] = []

    try:
        from config import config

        for attr in ("plugin_dir_path", "default_plugin_dir_path"):
            value = getattr(config, attr, None)
            if value:
                candidates.append(Path(value))
        for key in ("plugin_dir",):
            try:
                value = config.get_str(key)
            except Exception:
                value = None
            if value:
                candidates.append(Path(value))
    except Exception:  # nosec B110
        pass

    try:
        candidates.append(Path(__file__).resolve().parents[2])
    except IndexError:
        pass

    home = Path.home()
    candidates.extend(
        [
            home / ".local" / "share" / "EDMarketConnector" / "plugins",
            home / ".var" / "app" / "io.edcd.EDMarketConnector" / "data" / "EDMarketConnector" / "plugins",
        ]
    )

    for entry in sys.path:
        if entry:
            candidates.append(Path(entry))

    out: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved not in seen:
            out.append(resolved)
            seen.add(resolved)
    return out


def _safe_children(path: Path) -> list[Path]:
    try:
        if not path.is_dir():
            return []
        return [child for child in path.iterdir() if child.is_dir() and not child.name.startswith((".", "_"))]
    except OSError:
        return []


def _has_overlay_api_package(path: Path) -> bool:
    overlay_plugin = path / "overlay_plugin"
    return (
        (overlay_plugin / "overlay_api.py").is_file()
        or (overlay_plugin / "overlay_api" / "__init__.py").is_file()
    )


def get_overlay_dependency_status() -> OverlayDependencyStatus:
    """
    Return whether the Modern Overlay compatibility stack is present and live.

    ``PACKAGE_MISSING`` — ``overlay_plugin`` / EDMCModernOverlay not on the path.
    ``PLUGIN_NOT_RUNNING`` — package importable but the overlay plugin is not publishing.
    """
    try:
        overlay_api = import_overlay_api()
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
    return get_overlay_dependency_status() != OverlayDependencyStatus.PACKAGE_MISSING
