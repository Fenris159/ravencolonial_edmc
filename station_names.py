"""Normalize EDMC/journal dock station strings for Ravencolonial ``buildName``."""

from __future__ import annotations

from typing import Optional

_PLANETARY_PREFIX = "Planetary Construction Site: "
_ORBITAL_PREFIX = "Orbital Construction Site: "


def is_construction_depot_dock_name(station: Optional[str]) -> bool:
    """True for journal orbital/planetary construction depot names (link/create flows)."""
    if station is None:
        return False
    name = str(station).strip()
    if not name:
        return False
    if ";" in name:
        name = name.split(";", 1)[1].strip()
    return name.startswith(_PLANETARY_PREFIX) or name.startswith(_ORBITAL_PREFIX)


def normalize_dock_station_name(station: Optional[str]) -> str:
    """Strip localization tokens and construction-site prefixes from a dock station name."""
    if station is None:
        return ""
    name = str(station).strip()
    if not name:
        return ""
    if ";" in name:
        name = name.split(";", 1)[1].strip()
    if name.startswith(_PLANETARY_PREFIX):
        name = name[len(_PLANETARY_PREFIX) :]
    elif name.startswith(_ORBITAL_PREFIX):
        name = name[len(_ORBITAL_PREFIX) :]
    return name.strip()
