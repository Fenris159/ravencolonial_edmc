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
        *(p.get("commodities") for p in valid if isinstance(p.get("commodities"), Mapping)),
        include_completed=True,
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
        "complete": bool(valid) and not any(needs.values()),
    }


def _register_authoritative_project_fcs(
    plugin: Any,
    projects: Optional[List[Mapping[str, Any]]],
    *,
    request_epoch: Optional[int] = None,
) -> None:
    if not projects:
        return
    fc_handler = getattr(plugin, "fc_handler", None)
    register = getattr(fc_handler, "register_project_linked_fcs", None)
    if not callable(register):
        return
    try:
        register(projects, request_epoch=request_epoch)
    except TypeError:
        register(projects)


def remember_all_projects(
    plugin: Any,
    projects: List[Mapping[str, Any]],
    *,
    authoritative_projects: Optional[List[Mapping[str, Any]]] = None,
    request_epoch: Optional[int] = None,
) -> Dict[str, Any]:
    """Store a Track All aggregate without depending on either renderer existing."""
    plugin.overlay_project_cache_by_build_id = {
        str(resolve_build_id(project)): dict(project)
        for project in projects
        if isinstance(project, Mapping) and resolve_build_id(project)
    }
    aggregate = aggregate_project_cache(projects)
    plugin.overlay_project_cache = aggregate
    plugin.overlay_project_linked_fcs = parse_project_linked_fcs(aggregate)
    _register_authoritative_project_fcs(plugin, authoritative_projects, request_epoch=request_epoch)
    return aggregate


def _base_for_project_cache_update(
    plugin: Any, build_id: str, by_id: Mapping[str, Any], project_view: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    if isinstance(project_view, Mapping):
        return dict(project_view)
    if build_id in by_id and isinstance(by_id[build_id], dict):
        return dict(by_id[build_id])
    cached = getattr(plugin, "overlay_project_cache", None)
    if isinstance(cached, dict) and resolve_build_id(cached) == build_id:
        return dict(cached)
    return {}


def apply_project_cache_update(
    plugin: Any,
    build_id: str,
    *,
    remaining_need: Optional[Mapping[str, int]] = None,
    project_view: Optional[Mapping[str, Any]] = None,
    complete: Optional[bool] = None,
    request_epoch: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Merge depot truth into one build without clobbering another selection."""
    bid = str(build_id or "").strip()
    if not bid:
        return None

    by_id = dict(getattr(plugin, "overlay_project_cache_by_build_id", None) or {})
    base = _base_for_project_cache_update(plugin, bid, by_id, project_view)

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
    has_authoritative_links = isinstance(project_view, Mapping) and (
        isinstance(project_view.get("linkedFC"), list) or bool(project_view.get("complete"))
    )
    fresh = [base] if has_authoritative_links else None
    if selected == OVERLAY_TRACK_ALL_KEY:
        remember_all_projects(
            plugin, list(by_id.values()), authoritative_projects=fresh, request_epoch=request_epoch,
        )
    elif selected and str(selected).strip() == bid:
        plugin.overlay_project_cache = dict(base)
        plugin.overlay_project_linked_fcs = parse_project_linked_fcs(base)
        _register_authoritative_project_fcs(plugin, fresh, request_epoch=request_epoch)

    return base
