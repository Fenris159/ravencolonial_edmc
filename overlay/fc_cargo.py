"""Fleet carrier cargo helpers for the build overlay."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

try:
    from ..api.client import normalize_commodity_key
except ImportError:  # pragma: no cover
    from api.client import normalize_commodity_key

OVERLAY_FC_ALL = "all"


def fc_callsign_label(fc: Mapping[str, Any]) -> str:
    """Display label for an FC row in the carrier combo (callsign preferred)."""
    name = str(fc.get("name") or "").strip()
    if name:
        return name.upper()
    display = str(fc.get("displayName") or "").strip()
    if display:
        return display
    mid = fc.get("marketId")
    return str(mid) if mid is not None else "FC"


def parse_project_linked_fcs(project: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize ``linkedFC`` entries from a project view."""
    if not project:
        return []
    raw = project.get("linkedFC")
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    seen: set[int] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        mid = entry.get("marketId")
        if mid is None:
            continue
        try:
            mid_i = int(mid)
        except (TypeError, ValueError):
            continue
        if mid_i in seen:
            continue
        seen.add(mid_i)
        out.append(
            {
                "marketId": mid_i,
                "name": entry.get("name"),
                "displayName": entry.get("displayName"),
                "label": fc_callsign_label(entry),
            }
        )
    out.sort(key=lambda x: str(x.get("label", "")).lower())
    return out


def cargo_from_fc_record(fc_data: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    if not fc_data:
        return {}
    cargo = fc_data.get("cargo")
    if not isinstance(cargo, dict):
        return {}
    out: Dict[str, int] = {}
    for raw_k, raw_v in cargo.items():
        nk = normalize_commodity_key(str(raw_k))
        if not nk:
            continue
        try:
            count = int(raw_v)
        except (TypeError, ValueError):
            continue
        if count > 0:
            out[nk] = out.get(nk, 0) + count
    return out


def sum_fc_cargo_maps(maps: List[Mapping[str, int]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for m in maps:
        for k, v in m.items():
            nk = normalize_commodity_key(str(k))
            if not nk:
                continue
            try:
                count = int(v)
            except (TypeError, ValueError):
                continue
            if count > 0:
                out[nk] = out.get(nk, 0) + count
    return out


def resolve_fc_cargo_for_selection(
    *,
    linked_fcs: List[Dict[str, Any]],
    cargo_by_market: Mapping[Any, Mapping[str, int]],
    selection: str,
) -> Tuple[Dict[str, int], str]:
    """
    Return aggregated cargo and overlay column title for the current FC selection.

    ``selection`` is ``all`` or a market id string.
    """
    if not linked_fcs:
        return {}, "FC's"

    if selection != OVERLAY_FC_ALL:
        try:
            mid = int(selection)
        except (TypeError, ValueError):
            mid = None
        if mid is not None:
            label = OVERLAY_FC_ALL
            for fc in linked_fcs:
                if int(fc["marketId"]) == mid:
                    label = str(fc.get("label") or fc_callsign_label(fc))
                    break
            cargo = dict(cargo_by_market.get(mid) or cargo_by_market.get(str(mid)) or {})
            return cargo, label

    maps: List[Mapping[str, int]] = []
    for fc in linked_fcs:
        mid = fc["marketId"]
        maps.append(cargo_by_market.get(mid) or cargo_by_market.get(str(mid)) or {})
    return sum_fc_cargo_maps(maps), "FC's"


def compute_fc_deltas(
    needs: Mapping[str, int],
    fc_cargo: Mapping[str, int],
) -> Dict[str, int]:
    """Per-commodity ``fc_amount - need`` (SrvSurvey delta mode)."""
    out: Dict[str, int] = {}
    for key, need_raw in needs.items():
        need = int(need_raw)
        if need <= 0:
            continue
        nk = normalize_commodity_key(str(key))
        if not nk:
            continue
        fc_amt = int(fc_cargo.get(nk, 0))
        out[nk] = fc_amt - need
    return out


def format_fc_delta(delta: int) -> str:
    if delta > 0:
        return f"+{delta}"
    return str(delta)


def sum_positive_fc_surplus(deltas: Mapping[str, int]) -> int:
    """Sum of positive (fc_amt - need) entries. Used for owner 'Capacity: <surplus>/<freeSpace>' line."""
    total = 0
    for v in (deltas or {}).values():
        try:
            vi = int(v)
        except (TypeError, ValueError):
            continue
        if vi > 0:
            total += vi
    return total
