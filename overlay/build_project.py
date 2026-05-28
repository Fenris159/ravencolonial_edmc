"""Build commodity overlay via EDMCModernOverlay."""

from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

try:
    from ..api.client import resolve_build_id
except ImportError:  # pragma: no cover
    from api.client import resolve_build_id

from .bridge import OVERLAY_MESSAGE_PREFIX, get_overlay_client, register_build_tracker_group
from .formatting import (
    build_overlay_text,
    normalize_cargo_hold,
    project_header_line,
    resolve_project_needs,
)

logger = logging.getLogger(__name__)

OVERLAY_MAIN_ID = f"{OVERLAY_MESSAGE_PREFIX}main"
OVERLAY_X = 28
OVERLAY_Y = 140
OVERLAY_COLOR = "#E8E8E8"
OVERLAY_HEADER_COLOR = "#FFD27F"


class BuildProjectOverlay:
    def __init__(self, plugin: Any) -> None:
        self._plugin = plugin
        self._last_text: Optional[str] = None
        self._group_attempted = False

    def enabled(self) -> bool:
        try:
            from config import config

            return bool(config.get_bool("ravencolonial_overlay_enabled", default=True))
        except Exception:
            return True

    def clear(self) -> None:
        self._last_text = None
        get_overlay_client().send_raw({"id": OVERLAY_MAIN_ID, "text": "", "ttl": 0})

    def refresh(self, *, force: bool = False) -> None:
        if not self.enabled():
            self.clear()
            return
        if not self._group_attempted:
            register_build_tracker_group()
            self._group_attempted = True
        text, color = self._compose()
        if not text:
            self.clear()
            return
        if not force and text == self._last_text:
            return
        get_overlay_client().send_message(
            OVERLAY_MAIN_ID, text, color, OVERLAY_X, OVERLAY_Y, ttl=0, size="normal"
        )
        self._last_text = text

    def _compose(self) -> tuple[Optional[str], str]:
        plugin = self._plugin
        project = self._resolve_tracked_project()
        if project is None and not self._has_live_depot_needs():
            return None, OVERLAY_COLOR

        depot_remaining: Dict[str, int] = {}
        try:
            depot_fields = plugin.build_depot_project_fields(refresh=False)
            if depot_fields:
                depot_remaining = dict(depot_fields.get("remaining_need") or {})
        except Exception:
            pass
        if not depot_remaining:
            depot_remaining = dict(getattr(plugin, "last_depot_remaining_need", None) or {})

        needs = resolve_project_needs(project, depot_remaining=depot_remaining)
        if not needs and project is None:
            return None, OVERLAY_COLOR

        cargo = normalize_cargo_hold(getattr(plugin, "cargo", None))
        complete = bool(project and project.get("complete")) or self._depot_construction_complete()

        if project:
            header = project_header_line(project)
            system = str(project.get("systemName") or "").strip()
            subheader = system if system else None
        elif plugin.is_docked and getattr(plugin, "current_station", None):
            header = str(plugin.current_station)
            subheader = "Colonization site"
        else:
            header = "Colonization build"
            subheader = None

        body = build_overlay_text(
            header=header, subheader=subheader, needs=needs, cargo=cargo, complete=complete
        )
        return body, OVERLAY_HEADER_COLOR if complete else OVERLAY_COLOR

    def _resolve_tracked_project(self) -> Optional[Dict[str, Any]]:
        plugin = self._plugin
        cached = getattr(plugin, "overlay_project_cache", None)
        if isinstance(cached, dict) and resolve_build_id(cached):
            return cached
        if (
            plugin.is_docked
            and plugin.is_construction_ship
            and plugin.current_system_address is not None
            and plugin.current_market_id is not None
        ):
            project = plugin.check_existing_project(
                int(plugin.current_system_address), int(plugin.current_market_id)
            )
            if isinstance(project, dict) and resolve_build_id(project):
                plugin.overlay_project_cache = project
                return project
        return None

    def _has_live_depot_needs(self) -> bool:
        remaining = getattr(self._plugin, "last_depot_remaining_need", None) or {}
        return any(int(v) > 0 for v in remaining.values() if v is not None)

    def _depot_construction_complete(self) -> bool:
        entry = getattr(self._plugin, "construction_depot_data", None)
        return isinstance(entry, dict) and bool(entry.get("ConstructionComplete"))

    def remember_project(self, project: Optional[Mapping[str, Any]]) -> None:
        if isinstance(project, dict) and resolve_build_id(project):
            self._plugin.overlay_project_cache = dict(project)
        elif project is None:
            self._plugin.overlay_project_cache = None
