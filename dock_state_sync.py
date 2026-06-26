"""Sync plugin dock fields from EDMC's merged journal state snapshot."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def edmc_state_indicates_docked(state: Any) -> bool:
    """True when EDMC's merged journal state snapshot shows the commander is docked."""
    if not isinstance(state, dict):
        return False
    if state.get("Docked") is False:
        return False
    station_type = state.get("StationType")
    market_id = state.get("MarketID")
    if station_type and market_id is not None:
        return True
    return bool(state.get("Docked"))


def apply_plugin_dock_fields_from_edmc_state(
    plugin: Any,
    state: Any,
    *,
    station: str = "",
) -> bool:
    """
    Mirror dock fields from EDMC state when the game is already docked at plugin startup.

    Fleet Carrier startup already initializes FC dock baselines from the same snapshot, but
    the overlay gate reads ``plugin.is_docked``, which journal Docked/Location events normally
    set. Without this sync, enabling the overlay while docked on startup stays hidden until
    the next dock event.
    """
    if not edmc_state_indicates_docked(state):
        return False
    try:
        market_id = int(state.get("MarketID"))
    except (TypeError, ValueError):
        return False

    was_docked = bool(getattr(plugin, "is_docked", False))
    prev_market_id = getattr(plugin, "current_market_id", None)
    station_name = str(state.get("StationName") or station or "").strip()
    station_type = state.get("StationType")

    plugin.is_docked = True
    plugin.current_market_id = market_id
    if station_type:
        plugin.station_type = station_type
    plugin.is_construction_ship = "ColonisationShip" in station_name
    if state.get("BodyID") is not None:
        plugin.body_num = state.get("BodyID")
    if state.get("Body") is not None:
        plugin.body_name = state.get("Body")
    if state.get("StarPos") is not None:
        plugin.star_pos = state.get("StarPos")

    if not was_docked or prev_market_id != market_id:
        logger.info(
            "Synced dock state from EDMC state: station=%s type=%s marketId=%s",
            station_name or station,
            station_type,
            market_id,
        )
        update_create_button = getattr(plugin, "update_create_button", None)
        if callable(update_create_button):
            update_create_button()
    return True