"""Background all-projects fetch for Track All overlay mode."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List

from ..api.client import resolve_build_id
from .overlay_site_rows import combined_project_linked_fcs

if TYPE_CHECKING:
    from .plugin_protocol import PluginProtocol

logger = logging.getLogger(__name__)

OVERLAY_TRACK_ALL_KEY = "__OVERLAY_TRACK_ALL__"


def fetch_all_overlay_projects_worker(
    plugin: "PluginProtocol",
    build_ids: List[str],
) -> Dict[str, Any]:
    cache = dict(getattr(plugin, "overlay_project_cache_by_build_id", None) or {})
    projects: List[Dict[str, Any]] = []
    failed: List[str] = []
    for bid in build_ids:
        cached = cache.get(bid)
        project = plugin.get_project_by_build_id(bid)
        if not isinstance(project, dict) and isinstance(cached, dict):
            project = cached
        if isinstance(project, dict):
            resolved = resolve_build_id(project) or bid
            cache[str(resolved)] = dict(project)
            projects.append(dict(project))
        else:
            failed.append(bid)
    return {
        "build_ids": list(build_ids),
        "projects": projects,
        "cache": cache,
        "failed": failed,
    }


def worker_error_result(plugin: Any, build_ids: List[str]) -> Dict[str, Any]:
    return {
        "build_ids": list(build_ids),
        "projects": [],
        "cache": getattr(plugin, "overlay_project_cache_by_build_id", None) or {},
        "failed": list(build_ids),
    }


def apply_all_projects_fetch_result(
    plugin: "PluginProtocol",
    res: Dict[str, Any],
    *,
    fetch_fc_cargo: Any,
    refresh_fc_combo_state: Any,
    refresh_build_overlay: Any,
) -> None:
    if getattr(plugin, "selected_overlay_build_id", None) != OVERLAY_TRACK_ALL_KEY:
        logger.debug(
            "Overlay all-project fetch ignored: selected_now=%s",
            getattr(plugin, "selected_overlay_build_id", None),
        )
        return
    projects = [x for x in res.get("projects", []) if isinstance(x, dict)]
    plugin.overlay_project_cache_by_build_id = dict(res.get("cache") or {})
    if not projects:
        if getattr(plugin, "build_overlay", None):
            plugin.build_overlay.remember_project(None)
        else:
            plugin.overlay_project_cache = None
            plugin.overlay_project_linked_fcs = []
            plugin.overlay_fc_cargo_by_market = {}
    elif getattr(plugin, "build_overlay", None):
        plugin.build_overlay.remember_all_projects(projects)
    else:
        plugin.overlay_project_cache = None
        plugin.overlay_project_linked_fcs = combined_project_linked_fcs(projects)
    logger.debug(
        "Overlay all-project fetch finish: requested=%d loaded=%d failed=%d",
        len(res.get("build_ids") or []),
        len(projects),
        len(res.get("failed") or []),
    )
    refresh_fc_combo_state()
    if plugin.overlay_carrier_tracking_enabled and projects:
        fetch_fc_cargo(trigger="all_projects_refresh")
    else:
        refresh_build_overlay()
