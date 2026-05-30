"""Trip estimates for overlay footer (remaining units / ship cargo capacity)."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional

try:
    from ..api.client import normalize_commodity_key
except ImportError:  # pragma: no cover
    from api.client import normalize_commodity_key

OVERLAY_FC_ALL = "all"


def total_remaining_units(needs: Mapping[str, int]) -> int:
    total = 0
    for raw in needs.values():
        try:
            n = int(raw)
        except (TypeError, ValueError):
            continue
        if n > 0:
            total += n
    return total


def trips_for_units(units: int, cargo_capacity: Optional[int]) -> Optional[int]:
    """Full loads required to move ``units`` tons; ``None`` if capacity unknown or zero."""
    if units <= 0:
        return 0
    if cargo_capacity is None:
        return None
    try:
        cap = int(cargo_capacity)
    except (TypeError, ValueError):
        return None
    if cap <= 0:
        return None
    return int(math.ceil(units / cap))


def total_fc_deficit(needs: Mapping[str, int], fc_cargo: Mapping[str, int]) -> int:
    """
    Sum of per-commodity shortfall (need − FC stock) where FC stock is below need.

    Uses the same ``fc_cargo`` aggregation as the overlay FC column (All or one carrier).
    """
    deficit = 0
    for key, need_raw in needs.items():
        try:
            need = int(need_raw)
        except (TypeError, ValueError):
            continue
        if need <= 0:
            continue
        nk = normalize_commodity_key(str(key))
        if not nk:
            continue
        fc_amt = int(fc_cargo.get(nk, 0) or 0)
        if fc_amt < need:
            deficit += need - fc_amt
    return deficit


def fc_summary_label(selection: str, linked_fcs: List[Dict[str, Any]]) -> str:
    """Footer label for FC deficit line (matches carrier dropdown selection)."""
    sel = (selection or OVERLAY_FC_ALL).strip().lower()
    if sel != OVERLAY_FC_ALL:
        for fc in linked_fcs:
            try:
                if int(fc.get("marketId")) == int(selection):
                    return str(fc.get("label") or fc.get("name") or "FC").strip() or "FC"
            except (TypeError, ValueError):
                continue
        return "FC"
    n = len(linked_fcs)
    if n <= 0:
        return "FC's"
    if n == 1:
        return "1 FC"
    return f"{n} FCs"


def _format_trips_phrase(trips: Optional[int]) -> str:
    if trips is None:
        return "? trips"
    if trips == 1:
        return "1 trip"
    return f"{trips:,} trips"


def format_trip_footer_lines(
    *,
    total_remaining: int,
    ship_cargo_capacity: Optional[int],
    show_fc_line: bool = False,
    fc_deficit_total: Optional[int] = None,
    fc_summary_label: str = "FC's",
) -> List[str]:
    """Footer lines: remaining + ship trips; optional FC deficit + trips."""
    lines: List[str] = ["", ""]
    ship_trips = trips_for_units(total_remaining, ship_cargo_capacity)
    lines.append(
        f"> {total_remaining:,} remaining > {_format_trips_phrase(ship_trips)} in this ship"
    )

    if not show_fc_line:
        return lines

    deficit = int(fc_deficit_total or 0)
    fc_trips = trips_for_units(deficit, ship_cargo_capacity)
    label = (fc_summary_label or "FC's").strip() or "FC's"
    lines.append(
        f"> {label}: {deficit:,} deficit > {_format_trips_phrase(fc_trips)}"
    )
    return lines
