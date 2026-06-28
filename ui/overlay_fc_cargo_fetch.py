"""Background FC cargo map builder for overlay carrier tracking."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Set, Tuple

from ..exc_utils import HTTP_CLIENT_ERRORS
from ..overlay.fc_cargo import OVERLAY_FC_ALL, cargo_from_fc_record

logger = logging.getLogger(__name__)

_MANIFEST_SEED_TRIGGERS = frozenset({
    "manual_fc_selection",
    "manual_fc_manifest_refresh",
    "project_changed",
    "all_projects_refresh",
    "project_refresh",
})


def resolve_fc_api_refresh_decision(
    *,
    mid: int,
    trigger: str,
    allow_api_refresh: bool,
    fc_selection: str,
    handler: Any,
    client: Any,
    cached: Any,
    attempted: Set[int],
) -> Tuple[bool, str, int, Set[int]]:
    """Return (allowed, reason, cooldown, updated_attempted)."""
    manual_selected_refresh = (
        allow_api_refresh and
        str(trigger or "") == "manual_fc_manifest_refresh" and
        (fc_selection == OVERLAY_FC_ALL or fc_selection == str(mid))
    )
    if manual_selected_refresh:
        return True, "manual_fc_manifest_refresh", 0, attempted

    cached_source = str(cached.get("cargoSource") or "") if isinstance(cached, dict) else ""
    cached_cargo = cached.get("cargo") if isinstance(cached, dict) else None
    selected_specific_missing = (
        allow_api_refresh and
        fc_selection == str(mid) and
        (
            not isinstance(cached, dict) or
            (cached_source == "active_project_linked_fc" and not isinstance(cached_cargo, dict)) or
            (cached_source == "active_project_linked_fc" and not cached_cargo)
        )
    )
    if allow_api_refresh and str(trigger or "") in _MANIFEST_SEED_TRIGGERS and not selected_specific_missing:
        return False, "selected_manifest_seed_only", 0, attempted
    if selected_specific_missing:
        if mid in attempted:
            return False, "selected_manifest_missing_already_attempted", 0, attempted
        attempted = set(attempted)
        attempted.add(mid)
        return True, "selected_manifest_missing", 0, attempted
    if handler is None or client is None:
        return False, "no_handler_or_client", 0, attempted
    try:
        allowed, reason, cooldown = handler.can_refresh_fc_cargo_from_api(mid, trigger)
    except (TypeError, ValueError, AttributeError) as e:
        return False, f"guard_error_{e}", 0, attempted
    return allowed, reason, cooldown, attempted


def fetch_fc_cargo_from_api(
    *,
    mid: int,
    trigger: str,
    handler: Any,
    client: Any,
) -> Tuple[Dict[str, int], str, Any]:
    """GET /api/fc and update handler cache. Returns (cargo, source, cached_row)."""
    try:
        data = client.get_fc(mid)
    except HTTP_CLIENT_ERRORS as e:
        logger.warning("GET /api/fc/%s failed for trigger %s: %s", mid, trigger, e)
        return {}, "none", None
    if not isinstance(data, dict):
        logger.debug("GET /api/fc/%s returned no FC record for trigger %s", mid, trigger)
        return {}, "none", None
    cargo = cargo_from_fc_record(data)
    if hasattr(handler, "replace_fc_cargo_manifest"):
        handler.replace_fc_cargo_manifest(
            mid,
            cargo,
            source="raven_colonial_api",
            timestamp=(data or {}).get("lastRefresh") or
            (data or {}).get("cargoUpdatedAt") or
            (data or {}).get("cargoSnapshotTimestamp"),
        )
    handler_fcs = getattr(handler, "linked_fcs", None) or {}
    cached = handler_fcs.get(mid) or handler_fcs.get(str(mid)) or data
    return cargo, "raven_colonial_api", cached


def cargo_for_linked_fc(
    fc: Dict[str, Any],
    *,
    plugin: Any,
    trigger: str,
    allow_api_refresh: bool,
    handler_fcs: Dict[Any, Any],
    handler: Any,
    client: Any,
    attempted: Set[int],
    request_selection: Any,
) -> Tuple[int, Dict[str, int], Set[int]]:
    """Build one market_id → cargo entry; returns (mid, cargo_or_skip, updated_attempted)."""
    mid = int(fc["marketId"])
    fc_selection = str(getattr(plugin, "overlay_fc_selection", "") or "")
    cached = handler_fcs.get(mid) or handler_fcs.get(str(mid))
    cargo: Dict[str, int] = {}
    source = "none"

    if allow_api_refresh and handler is not None and client is not None:
        allowed, reason, cooldown, attempted = resolve_fc_api_refresh_decision(
            mid=mid,
            trigger=trigger,
            allow_api_refresh=allow_api_refresh,
            fc_selection=fc_selection,
            handler=handler,
            client=client,
            cached=cached,
            attempted=attempted,
        )
        if allowed:
            api_cargo, source, cached = fetch_fc_cargo_from_api(
                mid=mid,
                trigger=trigger,
                handler=handler,
                client=client,
            )
            if source == "raven_colonial_api":
                cargo = api_cargo
        else:
            logger.debug(
                "Overlay FC cargo API refresh skipped: market_id=%s trigger=%s reason=%s cooldown=%s",
                mid,
                trigger,
                reason,
                cooldown,
            )

    if isinstance(cached, dict):
        cargo = cargo_from_fc_record(cached)
        source = str(cached.get("cargoSource") or source or "local_cache")

    logger.debug(
        "Overlay FC cargo source: build=%s selected_fc=%s market_id=%s source=%s cargo=%s",
        request_selection,
        getattr(plugin, "overlay_fc_selection", None),
        mid,
        source,
        cargo,
    )

    manifest_known = source == "raven_colonial_api"
    if isinstance(cached, dict):
        known_source = str(cached.get("cargoSource") or "")
        manifest_known = manifest_known or (
            known_source not in {"", "active_project_linked_fc"} or bool(cargo)
        )
    if not manifest_known:
        return mid, {}, attempted
    return mid, cargo, attempted


def build_overlay_fc_cargo_map(
    plugin: Any,
    linked: List[Dict[str, Any]],
    *,
    trigger: str,
    allow_api_refresh: bool,
    request_selection: Any,
) -> Dict[int, Dict[str, int]]:
    out: Dict[int, Dict[str, int]] = {}
    handler = getattr(plugin, "fc_handler", None)
    handler_fcs: Dict[Any, Any] = {}
    if handler is not None:
        handler_fcs = getattr(handler, "linked_fcs", None) or {}
    client = getattr(plugin, "api_client", None)
    attempted = set(getattr(plugin, "_overlay_fc_manifest_fetch_attempted", set()) or set())

    for fc in linked:
        mid, cargo, attempted = cargo_for_linked_fc(
            fc,
            plugin=plugin,
            trigger=trigger,
            allow_api_refresh=allow_api_refresh,
            handler_fcs=handler_fcs,
            handler=handler,
            client=client,
            attempted=attempted,
            request_selection=request_selection,
        )
        if cargo:
            out[mid] = cargo

    plugin._overlay_fc_manifest_fetch_attempted = attempted
    return out
