"""Themed multi-layer overlay rendering."""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Tuple

try:
    from ..api.client import normalize_commodity_key
except ImportError:
    from api.client import normalize_commodity_key

from .commodity_categories import category_for_commodity_key, category_sort_key, format_category_separator
from .fc_cargo import format_fc_delta
from .formatting import (
    ASSIGN_COLUMN_HEADER,
    ASSIGN_SYMBOL_ME,
    ASSIGN_SYMBOL_OTHER,
    AssignmentKind,
    format_commodity_label,
    format_trip_footer_lines,
    _format_assignment_cell,
)
from .layers import (
    LINE_HEIGHT,
    MSG_COL_LABELS,
    MSG_COL_VALUES,
    MSG_FOOTER,
    MSG_HDR_BUILD,
    MSG_HDR_SYSTEM,
    OVERLAY_X,
    OVERLAY_Y,
    OverlayTextLayer,
    values_column_x,
)
from .themes import OverlayTheme, get_overlay_theme



def build_overlay_layers(
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
    theme: Optional[OverlayTheme] = None,
) -> List[OverlayTextLayer]:
    """Build themed overlay layers (separate colors per HUD role)."""
    pal = theme or get_overlay_theme(None)
    y = OVERLAY_Y
    layers: List[OverlayTextLayer] = []

    if header:
        layers.append(
            OverlayTextLayer(MSG_HDR_BUILD, header.strip(), pal.header_primary, OVERLAY_X, y)
        )
        y += LINE_HEIGHT
    if subheader:
        layers.append(
            OverlayTextLayer(MSG_HDR_SYSTEM, subheader.strip(), pal.header_secondary, OVERLAY_X, y)
        )
        y += LINE_HEIGHT

    if complete:
        layers.append(
            OverlayTextLayer(MSG_HDR_BUILD, "Construction complete", pal.header_primary, OVERLAY_X, y)
        )
        return layers

    if not needs:
        layers.append(
            OverlayTextLayer(MSG_HDR_BUILD, "No remaining commodities", pal.commodity, OVERLAY_X, y)
        )
        return layers

    label_lines, value_lines, footer_lines = _build_split_table_lines(
        needs=needs,
        cargo=cargo,
        assignments=assignments,
        fc_deltas=fc_deltas,
        fc_column_title=fc_column_title,
        ship_cargo_capacity=ship_cargo_capacity,
        show_fc_trip_summary=show_fc_trip_summary,
        fc_deficit_total=fc_deficit_total,
        fc_summary_label=fc_summary_label,
    )

    if not label_lines:
        layers.append(
            OverlayTextLayer(MSG_HDR_BUILD, "No remaining commodities", pal.commodity, OVERLAY_X, y)
        )
        return layers

    table_y = y
    layers.append(
        OverlayTextLayer(
            MSG_COL_LABELS,
            "\n".join(label_lines),
            pal.commodity,
            OVERLAY_X,
            table_y,
        )
    )
    val_x = values_column_x(label_lines)
    layers.append(
        OverlayTextLayer(
            MSG_COL_VALUES,
            "\n".join(value_lines),
            pal.values,
            val_x,
            table_y,
        )
    )
    y = table_y + LINE_HEIGHT * len(label_lines)

    if footer_lines:
        footer_text = "\n".join(line for line in footer_lines if line is not None)
        if footer_text.strip():
            layers.append(
                OverlayTextLayer(MSG_FOOTER, footer_text, pal.header_primary, OVERLAY_X, y)
            )

    return layers


def _build_split_table_lines(
    *,
    needs: Mapping[str, int],
    cargo: Mapping[str, int],
    assignments: Optional[Mapping[str, AssignmentKind]],
    fc_deltas: Optional[Mapping[str, int]],
    fc_column_title: str,
    ship_cargo_capacity: Optional[int],
    show_fc_trip_summary: bool,
    fc_deficit_total: Optional[int],
    fc_summary_label: str,
) -> tuple[List[str], List[str], List[str]]:
    """Return ``(label_lines, value_lines, footer_lines)`` with matching line counts."""
    assign_map = dict(assignments or {})
    show_assign = bool(assign_map)
    show_fc = fc_deltas is not None
    delta_map = dict(fc_deltas or {})

    Row = Tuple[str, str, str, int, int, Optional[int]]
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
        return [], [], []

    name_w = max(len("Commodity"), max(len(r[0]) for r in rows))
    fc_hdr = fc_column_title if len(fc_column_title) <= 8 else fc_column_title[:8]
    rule_w = name_w + 8 + (12 if show_fc else 0) + (6 if show_assign else 0)

    label_lines: List[str] = []
    value_lines: List[str] = []

    def _pair(label_part: str, value_part: str) -> None:
        label_lines.append(label_part)
        value_lines.append(value_part)

    lp: List[str] = []
    vp: List[str] = []
    if show_assign:
        lp.append(ASSIGN_COLUMN_HEADER)
        vp.append("")
    lp.append("Commodity".ljust(name_w))
    vp.append("Need")
    vp.append("Ship")
    if show_fc:
        vp.append(fc_hdr)
    _pair("  ".join(lp), "  ".join(vp))
    _pair("-" * rule_w, "-" * (8 + (12 if show_fc else 0) + (6 if show_assign else 0)))

    buckets: Dict[str, List[Row]] = {}
    for row in rows:
        buckets.setdefault(category_for_commodity_key(row[2]), []).append(row)
    for cat in sorted(buckets.keys(), key=category_sort_key):
        cat_rows = buckets[cat]
        cat_rows.sort(key=lambda r: r[0].lower())
        sep = format_category_separator(cat, rule_w)
        _pair(sep, "")
        for name, asg, _nk, need, ship, fc_val in cat_rows:
            lp = []
            if show_assign:
                lp.append(f"{asg:>3}")
            lp.append(name.ljust(name_w))
            vp = [f"{need:5d}", f"{ship:5d}"]
            if show_fc:
                if fc_val is None:
                    vp.append("    …")
                else:
                    vp.append(f"{format_fc_delta(int(fc_val)):>6}")
            _pair("  ".join(lp), "  ".join(vp))

    footer_lines: List[str] = []
    if show_assign:
        footer_lines.extend(["", f"{ASSIGN_SYMBOL_ME} = yours   {ASSIGN_SYMBOL_OTHER} = other CMDR"])
    footer_lines.extend(
        format_trip_footer_lines(
            total_remaining=total_need,
            ship_cargo_capacity=ship_cargo_capacity,
            show_fc_line=show_fc_trip_summary,
            fc_deficit_total=fc_deficit_total,
            fc_summary_label=fc_summary_label,
        )
    )

    return label_lines, value_lines, footer_lines
