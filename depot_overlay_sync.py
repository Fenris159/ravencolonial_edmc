"""Scoped overlay-cache updates after a successful depot PATCH.

``load.py`` historically wrote ``overlay_project_cache = project_view`` for any
successful non-Track-All depot PATCH. That clobbered the *selected* tracker when
the patched build was a different market. Display is cache-driven; this helper
keeps writes matched to build id (and only refreshes the selected entry when it
matches).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_TRACK_ALL = "__OVERLAY_TRACK_ALL__"


def scoped_patch_project_depot_state(
    plugin: Any,
    build_id: str,
    payload: Dict[str, Any],
    depot_sig: Optional[str] = None,
) -> bool:
    """PATCH remaining need and merge the result into overlay caches by build id."""
    project_view = plugin.api_client.patch_project_update(build_id, payload)
    if project_view is None:
        logger.warning(
            "Depot PATCH failed for %s — local need unchanged; will retry on next depot event",
            build_id,
        )
        return False

    plugin.maybe_clear_phantom_commodities(build_id, project_view)
    commodities = payload.get("commodities")
    if isinstance(commodities, dict):
        plugin.remember_depot_remaining_need(commodities)
    if depot_sig is not None:
        plugin._last_depot_patch_payload_sig = depot_sig

    if isinstance(project_view, dict):
        remaining = commodities if isinstance(commodities, dict) else None
        build_overlay = getattr(plugin, "build_overlay", None)
        if build_overlay is not None and hasattr(build_overlay, "apply_depot_update_to_cache"):
            build_overlay.apply_depot_update_to_cache(
                str(build_id),
                remaining_need=remaining,
                project_view=project_view,
            )
        else:
            cache = dict(getattr(plugin, "overlay_project_cache_by_build_id", None) or {})
            cache[str(build_id)] = dict(project_view)
            plugin.overlay_project_cache_by_build_id = cache
            selected = getattr(plugin, "selected_overlay_build_id", None)
            if selected == _TRACK_ALL:
                if build_overlay is not None and hasattr(build_overlay, "remember_all_projects"):
                    build_overlay.remember_all_projects(list(cache.values()))
            elif selected and str(selected).strip() == str(build_id):
                plugin.overlay_project_cache = dict(project_view)

    plugin.refresh_build_overlay()
    return True


def install_scoped_depot_patch(plugin: Any) -> None:
    """Replace ``plugin.patch_project_depot_state`` with the scoped implementation."""
    if getattr(plugin, "_scoped_depot_patch_installed", False):
        return

    def _bound(
        build_id: str,
        payload: Dict[str, Any],
        depot_sig: Optional[str] = None,
    ) -> bool:
        return scoped_patch_project_depot_state(plugin, build_id, payload, depot_sig)

    plugin.patch_project_depot_state = _bound  # type: ignore[method-assign]
    plugin._scoped_depot_patch_installed = True
    logger.debug("Installed scoped depot PATCH overlay-cache sync")
