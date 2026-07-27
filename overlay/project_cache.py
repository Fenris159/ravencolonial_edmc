"""Project-cache helpers shared by overlay, journal, and API update paths."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

try:
    from ..api.client import resolve_build_id
except ImportError:  # pragma: no cover
    from api.client import resolve_build_id
from .fc_cargo import parse_project_linked_fcs
from .formatting import merge_need_maps


OVERLAY_TRACK_ALL_KEY = "__OVERLAY_TRACK_ALL__"


def aggregate_project_cache(projects: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Build a synthetic project view whose commodities are all active project needs."""
    valid = [p for p in projects if isinstance(p, Mapping) and not p.get("complete")]
    needs = merge_need_maps(
        *(p.get("commodities") for p in valid if isinstance(p.get("commodities"), Mapping))
    )
    systems = sorted(
        {
            str(p.get("systemName") or "").strip()
            for p in valid
            if str(p.get("systemName") or "").strip()
        },
        key=str.casefold,
    )
    linked_fcs: List[Dict[str, Any]] = []
    seen_fcs: set[int] = set()
    for project in valid:
        for fc in parse_project_linked_fcs(project):
            try:
                mid = int(fc["marketId"])
            except (KeyError, TypeError, ValueError):
                continue
            if mid in seen_fcs:
                continue
            seen_fcs.add(mid)
            linked_fcs.append(dict(fc))
    linked_fcs.sort(key=lambda x: str(x.get("label", "")).lower())
    return {
        "buildId": OVERLAY_TRACK_ALL_KEY,
        "buildName": "Track All",
        "buildType": f"{len(valid)} builds",
        "systemName": ", ".join(systems[:3]) + (" ..." if len(systems) > 3 else ""),
        "commodities": needs,
        "linkedFC": linked_fcs,
        "complete": bool(valid) and not needs,
    }


def apply_project_cache_update(
    plugin: Any,
    build_id: str,
    *,
    remaining_need: Optional[Mapping[str, int]] = None,
    project_view: Optional[Mapping[str, Any]] = None,
    complete: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """Merge depot truth into one build without clobbering another selection."""
    bid = str(build_id or "").strip()
    if not bid:
        return None

    by_id = dict(getattr(plugin, "overlay_project_cache_by_build_id", None) or {})
    if isinstance(project_view, Mapping):
        base: Dict[str, Any] = dict(project_view)
    elif bid in by_id and isinstance(by_id[bid], dict):
        base = dict(by_id[bid])
    else:
        cached = getattr(plugin, "overlay_project_cache", None)
        if isinstance(cached, dict) and resolve_build_id(cached) == bid:
            base = dict(cached)
        else:
            base = {}

    # The endpoint/request identity is authoritative. A malformed or partial API
    # response must not leave the cache entry carrying another build's identity.
    base["buildId"] = bid
    if remaining_need is not None:
        base["commodities"] = dict(remaining_need)
    if complete is not None:
        base["complete"] = bool(complete)

    by_id[bid] = base
    plugin.overlay_project_cache_by_build_id = by_id

    selected = getattr(plugin, "selected_overlay_build_id", None)
    if selected == OVERLAY_TRACK_ALL_KEY:
        aggregate = aggregate_project_cache(list(by_id.values()))
        plugin.overlay_project_cache = aggregate
        plugin.overlay_project_linked_fcs = parse_project_linked_fcs(aggregate)
    elif selected and str(selected).strip() == bid:
        plugin.overlay_project_cache = dict(base)
        plugin.overlay_project_linked_fcs = parse_project_linked_fcs(base)

    return base
