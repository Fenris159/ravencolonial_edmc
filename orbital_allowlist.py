"""
Orbital-only Ravencolonial ``buildType`` allowlist.

Strings match RavenColonialWeb ``src/site-data.ts`` ``siteTypes`` rows where
``orbital`` is ``true`` (``subTypes`` + ``altTypes``), excluding the empty
placeholder ``''``. ``installation`` and ``outpost`` placeholder rows are
included because they appear in that table as orbital.

Sync this module when the website adds or reclassifies build types.

Lookup: ``normalize_build_type(s) in ORBITAL_BUILD_TYPES`` — ``frozenset``
membership is O(1).
"""

from __future__ import annotations

from typing import Optional

# Alphabetical for diff-friendly maintenance (generator-friendly one-time build).
_ORBITAL_BUILD_TYPE_TUPLE: tuple[str, ...] = (
    "alastor",
    "aletheia",
    "angelia",
    "apollo",
    "apate",
    "artemis",
    "asclepius",
    "asteroid",
    "astraeus",
    "bacchus",
    "coeus",
    "coriolis",
    "dec_truss",
    "demeter",
    "dicaeosyne",
    "dione",
    "dionysus",
    "dodona",
    "dodec",
    "dual_truss",
    "dysnomia",
    "enodia",
    "eirene",
    "eunomia",
    "euthenia",
    "eupraxia",
    "harmonia",
    "hedone",
    "hermes",
    "ichnaea",
    "installation",
    "laverna",
    "nemesis",
    "no truss",  # alt spelling (space) for Coriolis family
    "no_truss",
    "nomos",
    "ocellus",
    "orbis",
    "opora",
    "outpost",  # placeholder row in web table; kept for parity with site-data
    "pasithea",
    "phorcys",
    "pistis",
    "plutus",
    "poena",
    "prometheus",
    "quad_truss",
    "quint_truss",
    "soter",
    "vacuna",
    "vesta",
    "vulcan",
)

ORBITAL_BUILD_TYPES: frozenset[str] = frozenset(_ORBITAL_BUILD_TYPE_TUPLE)


def normalize_build_type(build_type: Optional[str]) -> str:
    """Strip and remove ``' (primary)'`` suffix (same convention as web ``getSiteType``)."""
    if build_type is None:
        return ""
    return str(build_type).replace(" (primary)", "").strip()


def is_orbital_build_type(build_type: Optional[str]) -> bool:
    """Return True if ``build_type`` is in the orbital allowlist (after normalization)."""
    key = normalize_build_type(build_type)
    return bool(key) and key in ORBITAL_BUILD_TYPES


__all__ = [
    "ORBITAL_BUILD_TYPES",
    "is_orbital_build_type",
    "normalize_build_type",
]
