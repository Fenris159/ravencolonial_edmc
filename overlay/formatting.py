"""Pure helpers for build-project overlay text."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

try:
    from ..api.client import normalize_commodity_key
except ImportError:  # pragma: no cover
    from api.client import normalize_commodity_key

try:
    from ..i18n import tr, trf
except ImportError:  # pragma: no cover
    from i18n import tr, trf  # type: ignore[no-redef]

try:
    from .l10n_helpers import tr_assignment_legend
except ImportError:  # pragma: no cover
    try:
        from overlay.l10n_helpers import tr_assignment_legend  # type: ignore[no-redef]
    except ImportError:
        from l10n_helpers import tr_assignment_legend  # type: ignore[no-redef]

try:
    from .commodity_categories import (
        category_for_commodity_key,
        category_sort_key,
        format_category_separator,
    )
    from .fc_cargo import format_fc_delta
    from .trip_estimates import format_trip_footer_lines
except ImportError:  # pragma: no cover
    from commodity_categories import (  # type: ignore[no-redef]
        category_for_commodity_key,
        category_sort_key,
        format_category_separator,
    )
    from fc_cargo import format_fc_delta  # type: ignore[no-redef]
    from trip_estimates import format_trip_footer_lines  # type: ignore[no-redef]


def format_commodity_label(key: str) -> str:
    try:
        from .l10n_helpers import tr_commodity
    except ImportError:  # pragma: no cover
        try:
            from overlay.l10n_helpers import tr_commodity  # type: ignore[no-redef]
        except ImportError:
            from l10n_helpers import tr_commodity  # type: ignore[no-redef]
    return tr_commodity(key)


def merge_need_maps(*maps: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for m in maps:
        if not m:
            continue
        for raw_k, raw_v in m.items():
            nk = normalize_commodity_key(str(raw_k))
            if not nk:
                continue
            try:
                amount = int(raw_v)
            except (TypeError, ValueError):
                continue
            if amount <= 0:
                continue
            out[nk] = out.get(nk, 0) + amount
    return out


def normalize_cargo_hold(hold: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if not hold:
        return out
    for raw_k, raw_v in hold.items():
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


AssignmentKind = Optional[str]  # "me", "other", or None

ASSIGN_SYMBOL_ME = "\U0001f4cc"
ASSIGN_SYMBOL_OTHER = "x"
ASSIGN_COLUMN_HEADER = "Asg"

OVERLAY_VALUE_COL_WIDTH = 5


def format_overlay_ship_cell(ship: int, *, width: int = OVERLAY_VALUE_COL_WIDTH) -> str:
    """Ship column: blank when zero to reduce clutter."""
    if ship == 0:
        return " " * width
    return f"{ship:{width}d}"


def _commodity_assigned_to(commanders: Mapping[str, Any], commodity_key: str) -> List[str]:
    assigned: List[str] = []
    for raw_cmdr, raw_items in commanders.items():
        if raw_items is None:
            continue
        items: Any = raw_items
        if isinstance(items, dict):
            items = items.keys()
        if not isinstance(items, (list, tuple, set)):
            continue
        for raw_name in items:
            nk = normalize_commodity_key(str(raw_name))
            if nk == commodity_key:
                assigned.append(str(raw_cmdr).strip())
                break
    return assigned


def resolve_assignments_for_needs(
    needs: Mapping[str, int],
    project: Optional[Mapping[str, Any]],
    cmdr_name: Optional[str],
) -> Dict[str, AssignmentKind]:
    out: Dict[str, AssignmentKind] = {}
    if not project or not cmdr_name or not needs:
        return out
    commanders = project.get("commanders")
    if not isinstance(commanders, dict) or not commanders:
        return out
    me = str(cmdr_name).strip().lower()
    if not me:
        return out
    for key in needs:
        if int(needs.get(key, 0) or 0) <= 0:
            continue
        nk = normalize_commodity_key(str(key))
        if not nk:
            continue
        assigned_to = _commodity_assigned_to(commanders, nk)
        if not assigned_to:
            continue
        if any(c.lower() == me for c in assigned_to):
            out[nk] = "me"
        else:
            out[nk] = "other"
    return out


def _format_assignment_cell(kind: AssignmentKind) -> str:
    if kind == "me":
        return ASSIGN_SYMBOL_ME
    if kind == "other":
        return ASSIGN_SYMBOL_OTHER
    return " "


def build_overlay_text(
    *,
    header: str,
    needs: Mapping[str, int],
    cargo: Mapping[str, int],
    subheader: Optional[str] = None,
    complete: bool = False,
    assignments: Optional[Mapping[str, AssignmentKind]] = None,
    fc_deltas: Optional[Mapping[str, int]] = None,
    fc_column_title: str = "FC's",
    ship_cargo_capacity: Optional[int] = None,
    show_fc_trip_summary: bool = False,
    fc_deficit_total: Optional[int] = None,
    fc_summary_label: str = "FC's",
) -> str:
    lines: List[str] = []
    if header:
        lines.append(header.strip())
    if subheader:
        lines.append(subheader.strip())
    if complete:
        lines.append(tr("Construction complete"))
        return "\n".join(lines)
    if not needs:
        lines.append(tr("No remaining commodities"))
        return "\n".join(lines)

    assign_map = dict(assignments or {})
    show_assign = bool(assign_map)
    show_fc = fc_deltas is not None
    delta_map = dict(fc_deltas or {})

    Row = Tuple[str, str, str, int, int, Optional[int]]  # label, asg, nk, need, ship, fc
    rows: List[Row] = []
    total_need = 0
    for key, raw_need in needs.items():
        need = int(raw_need)
        if need <= 0:
            continue
        nk = normalize_commodity_key(str(key))
        ship = int(cargo.get(key, 0) or cargo.get(nk, 0))
        asg = _format_assignment_cell(assign_map.get(nk) if show_assign else None)
        fc_val: Optional[int] = delta_map.get(nk) if show_fc else None
        rows.append((format_commodity_label(key), asg, nk, need, ship, fc_val))
        total_need += need
    if not rows:
        lines.append(tr("No remaining commodities"))
        return "\n".join(lines)

    name_w = max(len(tr("Commodity")), max(len(r[0]) for r in rows))
    fc_hdr = fc_column_title if len(fc_column_title) <= 8 else fc_column_title[:8]

    parts: List[str] = []
    if show_assign:
        parts.append(tr(ASSIGN_COLUMN_HEADER))
    parts.append(tr("Commodity").ljust(name_w))
    parts.append(tr("Need"))
    parts.append(tr("Ship"))
    if show_fc:
        parts.append(fc_hdr)
    header_line = "  ".join(parts)
    rule_w = name_w + 8 + (12 if show_fc else 0) + (6 if show_assign else 0)
    rule_line = "-" * rule_w

    lines.append(header_line)
    lines.append(rule_line)

    def _append_row(name: str, asg: str, need: int, ship: int, fc_val: Optional[int]) -> None:
        cells: List[str] = []
        if show_assign:
            cells.append(f"{asg:>3}")
        cells.append(name.ljust(name_w))
        cells.append(f"{need:5d}")
        cells.append(format_overlay_ship_cell(ship))
        if show_fc:
            if fc_val is None:
                cells.append("    …")
            else:
                cells.append(f"{format_fc_delta(int(fc_val)):>6}")
        lines.append("  ".join(cells))

    buckets: Dict[str, List[Row]] = {}
    for row in rows:
        buckets.setdefault(category_for_commodity_key(row[2]), []).append(row)
    for cat in sorted(buckets.keys(), key=category_sort_key):
        cat_rows = buckets[cat]
        cat_rows.sort(key=lambda r: r[0].lower())
        lines.append(format_category_separator(cat, rule_w))
        for name, asg, _nk, need, ship, fc_val in cat_rows:
            _append_row(name, asg, need, ship, fc_val)

    if show_assign:
        lines.append("")
        lines.append(tr_assignment_legend(pin=ASSIGN_SYMBOL_ME, cross=ASSIGN_SYMBOL_OTHER))
    lines.extend(
        format_trip_footer_lines(
            total_remaining=total_need,
            ship_cargo_capacity=ship_cargo_capacity,
            show_fc_line=show_fc_trip_summary,
            fc_deficit_total=fc_deficit_total,
            fc_summary_label=fc_summary_label,
        )
    )
    return "\n".join(lines)


def project_header_line(project: Mapping[str, Any]) -> str:
    name = str(project.get("buildName") or project.get("name") or "Build").strip()
    build_type = str(project.get("buildType") or "").strip()
    if build_type:
        return f"{name} ({build_type})"
    return name


def resolve_project_needs(
    project: Optional[Mapping[str, Any]],
    *,
    depot_remaining: Optional[Mapping[str, int]] = None,
    depot_authoritative: bool = False,
) -> Dict[str, int]:
    if depot_authoritative:
        return merge_need_maps(depot_remaining)
    if depot_remaining:
        merged = merge_need_maps(depot_remaining)
        if merged:
            return merged
    if project:
        commodities = project.get("commodities")
        if isinstance(commodities, dict):
            return merge_need_maps(commodities)
    return {}
