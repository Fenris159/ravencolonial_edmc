"""Match legacy v2 system site rows missing ``marketId`` to dock journal context."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

try:
    from .station_names import is_construction_depot_dock_name, normalize_dock_station_name
except ImportError:  # pragma: no cover - standalone tests
    from station_names import is_construction_depot_dock_name, normalize_dock_station_name

# Player colonization station MarketIDs (installed builds, depots, colonisation ships).
_PLAYER_COLONY_MARKET_ID_PREFIXES = ("395", "396", "397", "42", "43")

# Never map these journal station types to legacy ``/sites`` repair.
_SKIP_STATION_TYPES = frozenset(
    {
        "FleetCarrier",
        "SpaceConstructionDepot",
        "MegaShip",
    }
)


def market_id_is_player_colony_station(market_id: Union[int, str]) -> bool:
    """True when the dock ``MarketID`` belongs to a player colonization facility."""
    try:
        mid = str(int(market_id))
    except (TypeError, ValueError):
        return False
    return any(mid.startswith(prefix) for prefix in _PLAYER_COLONY_MARKET_ID_PREFIXES)


def dock_context_skips_market_id_repair(
    *,
    station_type: Optional[str],
    station_name: Optional[str],
    is_construction_ship: bool = False,
) -> bool:
    """
    True when a dock/location event is part of link/create construction flows or
    other contexts that must not trigger legacy ``/sites`` repair lookups.
    """
    stype = str(station_type or "").strip()
    if stype in _SKIP_STATION_TYPES:
        return True
    name = str(station_name or "")
    if is_construction_ship or "ColonisationShip" in name:
        return True
    if is_construction_depot_dock_name(name):
        return True
    return False


def site_market_id_missing(value: Any) -> bool:
    """True when a v2 system site row has no meaningful ``marketId`` value."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in ("", "0")
    try:
        return int(value) == 0
    except (TypeError, ValueError):
        return False


def site_status_allows_market_id_repair(site: Dict[str, Any]) -> bool:
    """Only repair completed rows; statusless legacy rows are allowed by name match."""
    raw = site.get("status")
    if raw is None:
        return True
    status = str(raw).strip().lower()
    return status == "" or status == "complete"


def normalized_site_name_key(site: Dict[str, Any]) -> str:
    """Casefolded normalized ``name`` for duplicate detection across ``/sites`` rows."""
    return normalize_dock_station_name(site.get("name")).casefold()


def site_rows_with_normalized_name(
    sites: List[Dict[str, Any]],
    station_name: str,
) -> List[Dict[str, Any]]:
    """All ``/sites`` rows whose normalized ``name`` equals the dock station string."""
    dock_key = normalize_dock_station_name(station_name).casefold()
    if not dock_key:
        return []
    matches: List[Dict[str, Any]] = []
    for site in sites or []:
        if not isinstance(site, dict):
            continue
        if normalized_site_name_key(site) == dock_key:
            matches.append(site)
    return matches


def market_id_repair_candidates(
    sites: List[Dict[str, Any]],
    *,
    station_name: str,
) -> List[Dict[str, Any]]:
    """
    Completed/statusless site rows missing ``marketId`` that match the current dock.

    Matching uses normalized station name only. Repair is allowed when **exactly one**
    row in ``/sites`` shares that name **and** that row is eligible for repair.
    """
    same_name = site_rows_with_normalized_name(sites, station_name)
    if len(same_name) != 1:
        return []

    site = same_name[0]
    if not site_market_id_missing(site.get("marketId")):
        return []
    if not site_status_allows_market_id_repair(site):
        return []
    return [site]


def site_market_id_repair_retry_delay(attempt_index: int) -> float:
    """Short bounded backoff between failed ``/sites`` GET attempts (latency/timeouts)."""
    return 1.5 * (attempt_index + 1)
