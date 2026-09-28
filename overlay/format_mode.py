"""Display modes and purchase quantities for the build tracker."""

from __future__ import annotations

from typing import Mapping, Optional

try:
    from ..api.client import normalize_commodity_key
except ImportError:  # pragma: no cover - standalone tests
    from api.client import normalize_commodity_key


OVERLAY_FORMAT_BREAKDOWN = "breakdown"
OVERLAY_FORMAT_SIMPLIFIED = "simplified"


def normalize_overlay_format(value: object) -> str:
    """Use Breakdown for unset or obsolete configuration values."""
    if str(value or "").strip().lower() == OVERLAY_FORMAT_SIMPLIFIED:
        return OVERLAY_FORMAT_SIMPLIFIED
    return OVERLAY_FORMAT_BREAKDOWN


def purchase_amounts(
    needs: Mapping[str, int],
    ship_cargo: Mapping[str, int],
    carrier_cargo: Mapping[str, int],
    *,
    carrier_known: bool,
) -> dict[str, Optional[int]]:
    """Remaining units to buy after one ship hold and the selected carrier cargo."""
    amounts: dict[str, Optional[int]] = {}
    for key, raw_need in needs.items():
        need = int(raw_need)
        if need < 0:
            continue
        commodity = normalize_commodity_key(str(key))
        if not commodity:
            continue
        ship = max(0, int(ship_cargo.get(commodity, 0)))
        if ship >= need:
            amounts[commodity] = 0
        elif carrier_known:
            carrier = max(0, int(carrier_cargo.get(commodity, 0)))
            amounts[commodity] = max(0, need - ship - carrier)
        else:
            amounts[commodity] = None
    return amounts
