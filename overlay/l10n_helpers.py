"""Overlay-specific localization helpers (commodities, categories, trip phrases)."""

from __future__ import annotations

try:
    from ..api.client import normalize_commodity_key
    from ..i18n import tr, trf
except ImportError:  # pragma: no cover
    from api.client import normalize_commodity_key  # type: ignore[no-redef]
    from i18n import tr, trf  # type: ignore[no-redef]


def tr_commodity(key: str) -> str:
    """Display name for a journal/API commodity key; falls back to title-case."""
    nk = normalize_commodity_key(str(key))
    if not nk:
        return ""
    lookup = f"commodity:{nk}"
    translated = tr(lookup)
    if translated != lookup:
        return translated
    # Legacy fallback when commodity template not merged yet
    parts = nk.replace("_", " ").split()
    return " ".join(p[:1].upper() + p[1:] if p else "" for p in parts)


def tr_category(category: str) -> str:
    """Market category label for overlay section headers."""
    label = (category or "Other").strip() or "Other"
    translated = tr(label)
    return translated if translated != label else label


def tr_trips_phrase(trips: int | None) -> str:
    if trips is None:
        return tr("? trips")
    if trips == 1:
        return tr("1 trip")
    return trf("{count} trips", count=f"{trips:,}")


def tr_trip_footer_ship_line(*, remaining: int, trips: int | None) -> str:
    return trf(
        "> {remaining} remaining > {trips} in this ship",
        remaining=f"{remaining:,}",
        trips=tr_trips_phrase(trips),
    )


def tr_trip_footer_fc_line(*, label: str, deficit: int, trips: int | None) -> str:
    return trf(
        "> {label}: {deficit} deficit > {trips}",
        label=(label or tr("FC's")).strip() or tr("FC's"),
        deficit=f"{deficit:,}",
        trips=tr_trips_phrase(trips),
    )


def tr_assignment_legend(*, pin: str, cross: str) -> str:
    return trf("{pin} = yours   {cross} = other CMDR", pin=pin, cross=cross)
