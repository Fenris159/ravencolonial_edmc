"""Themed multi-layer overlay rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Tuple

try:
    from ..api.client import normalize_commodity_key
    from ..i18n import tr
except ImportError:
    from api.client import normalize_commodity_key
    from i18n import tr  # type: ignore[no-redef]

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
    format_overlay_ship_cell,
)
from .layers import (
    COLUMN_DIVIDER_COLOR,
    LINE_HEIGHT,
    MAX_COLUMN_DIVIDER_SEGMENTS,
    MSG_COL_DIVIDER_PREFIX,
    MSG_COL_LABELS,
    MSG_COL_VALUES,
    MSG_FOOTER,
    MSG_HDR_BUILD,
    MSG_HDR_SYSTEM,
    MSG_ROW_STRIPE_PREFIX,
    MAX_ROW_STRIPES,
    OVERLAY_X,
    OVERLAY_Y,
    FOOTER_TOP_PADDING,
    OverlayRectLayer,
    OverlayTextLayer,
    OverlayVectorLayer,
    ROW_STRIPE_FILL,
    ROW_STRIPE_HEIGHT,
    ROW_STRIPE_Y_OFFSET,
    TABLE_TOP_PADDING,
    VALUE_COL_FC_CHARS,
    VALUE_COL_GAP_CHARS,
    VALUE_COL_NEED_CHARS,
    VALUE_COL_SHIP_CHARS,
    MSG_TABLE_LABEL_PREFIX,
    MSG_TABLE_NEED_PREFIX,
    MSG_TABLE_SHIP_PREFIX,
    MSG_TABLE_FC_PREFIX,
    MSG_TABLE_VALUE_PREFIX,
    estimate_value_text_width,
    table_content_width,
    value_column_divider_x_positions,
    value_column_right_edges,
    values_column_x,
)
from .font_weights import (
    WEIGHT_BODY,
    WEIGHT_COLUMN_HEADER,
    WEIGHT_EMPHASIS,
    WEIGHT_FOOTER,
    WEIGHT_HEADER_PRIMARY,
    WEIGHT_HEADER_SECONDARY,
)
from .themes import OverlayTheme, get_overlay_theme


@dataclass(frozen=True)
class OverlayRenderBundle:
    text_layers: List[OverlayTextLayer]
    rect_layers: List[OverlayRectLayer] = field(default_factory=list)
    vector_layers: List[OverlayVectorLayer] = field(default_factory=list)


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
    fc_capacity_line: Optional[str] = None,
    theme: Optional[OverlayTheme] = None,
    row_stripes: bool = True,
    column_dividers: bool = True,
) -> OverlayRenderBundle:
    """Build themed overlay layers (separate colors per HUD role)."""
    pal = theme or get_overlay_theme(None)
    y = OVERLAY_Y
    layers: List[OverlayTextLayer] = []
    rects: List[OverlayRectLayer] = []
    vectors: List[OverlayVectorLayer] = []

    if header:
        layers.append(
            OverlayTextLayer(MSG_HDR_BUILD, header.strip(), pal.header_primary, OVERLAY_X, y, weight=WEIGHT_HEADER_PRIMARY)
        )
        y += LINE_HEIGHT
    if subheader:
        layers.append(
            OverlayTextLayer(MSG_HDR_SYSTEM, subheader.strip(), pal.header_secondary, OVERLAY_X, y, weight=WEIGHT_HEADER_SECONDARY)
        )
        y += LINE_HEIGHT

    if complete:
        layers.append(
            OverlayTextLayer(MSG_HDR_BUILD, tr("Construction complete"), pal.header_primary, OVERLAY_X, y, weight=WEIGHT_HEADER_PRIMARY)
        )
        return OverlayRenderBundle(layers, rects, vectors)

    if not needs:
        layers.append(
            OverlayTextLayer(MSG_HDR_BUILD, tr("No remaining commodities"), pal.commodity, OVERLAY_X, y, weight=WEIGHT_BODY)
        )
        return OverlayRenderBundle(layers, rects, vectors)

    label_lines, value_lines, value_cells, footer_lines, commodity_row_indices, show_fc_column = _build_split_table_lines(
        needs=needs,
        cargo=cargo,
        assignments=assignments,
        fc_deltas=fc_deltas,
        fc_column_title=fc_column_title,
        ship_cargo_capacity=ship_cargo_capacity,
        show_fc_trip_summary=show_fc_trip_summary,
        fc_deficit_total=fc_deficit_total,
        fc_summary_label=fc_summary_label,
        fc_capacity_line=fc_capacity_line,
    )

    if not label_lines:
        layers.append(
            OverlayTextLayer(MSG_HDR_BUILD, tr("No remaining commodities"), pal.commodity, OVERLAY_X, y, weight=WEIGHT_BODY)
        )
        return OverlayRenderBundle(layers, rects, vectors)

    table_y = y + TABLE_TOP_PADDING
    val_x = values_column_x(label_lines)
    if row_stripes and commodity_row_indices:
        table_w = table_content_width(label_lines, value_lines)
        rects = _build_row_stripe_rects(
            commodity_row_indices=commodity_row_indices,
            table_x=OVERLAY_X,
            table_y=table_y,
            table_width=table_w,
        )
    if column_dividers and commodity_row_indices:
        vectors = _build_column_divider_vectors(
            value_block_x=val_x,
            table_y=table_y,
            commodity_row_indices=commodity_row_indices,
            include_fc_column=show_fc_column,
        )

    line_count = max(len(label_lines), len(value_lines))
    value_right_edges = value_column_right_edges(val_x, include_fc_column=show_fc_column)
    for line_index in range(line_count):
        row_y = table_y + line_index * LINE_HEIGHT
        label_text = label_lines[line_index] if line_index < len(label_lines) else ""
        value_text = value_lines[line_index] if line_index < len(value_lines) else ""
        if label_text:
            layers.append(
                OverlayTextLayer(
                    f"{MSG_TABLE_LABEL_PREFIX}{line_index:03d}",
                    label_text,
                    pal.commodity,
                    OVERLAY_X,
                    row_y,
                    weight=WEIGHT_COLUMN_HEADER,
                )
            )
        cells = value_cells[line_index] if line_index < len(value_cells) else ()
        if cells:
            prefixes = (MSG_TABLE_NEED_PREFIX, MSG_TABLE_SHIP_PREFIX, MSG_TABLE_FC_PREFIX)
            for cell_index, cell_text in enumerate(cells[: len(value_right_edges)]):
                text = str(cell_text or "")
                if not text.strip():
                    continue
                text_x = value_right_edges[cell_index] - estimate_value_text_width(text)
                layers.append(
                    OverlayTextLayer(
                        f"{prefixes[cell_index]}{line_index:03d}",
                        text,
                        pal.values,
                        text_x,
                        row_y,
                        weight=WEIGHT_EMPHASIS,
                    )
                )
        elif value_text:
            layers.append(
                OverlayTextLayer(
                    f"{MSG_TABLE_VALUE_PREFIX}{line_index:03d}",
                    value_text,
                    pal.values,
                    val_x,
                    row_y,
                    weight=WEIGHT_EMPHASIS,
                )
            )
    y = table_y + LINE_HEIGHT * line_count + FOOTER_TOP_PADDING

    if footer_lines:
        visible_footer_lines = [line for line in footer_lines if line is not None]
        while visible_footer_lines and not str(visible_footer_lines[0]).strip():
            visible_footer_lines.pop(0)
        footer_text = "\n".join(visible_footer_lines)
        if footer_text.strip():
            layers.append(
                OverlayTextLayer(MSG_FOOTER, footer_text, pal.header_primary, OVERLAY_X, y, weight=WEIGHT_FOOTER)
            )

    return OverlayRenderBundle(layers, rects, vectors)


def _contiguous_line_index_runs(indices: List[int]) -> List[Tuple[int, int]]:
    """Group sorted table line indices into contiguous runs (skips category/header gaps)."""
    if not indices:
        return []
    sorted_idx = sorted(indices)
    runs: List[Tuple[int, int]] = []
    start = end = sorted_idx[0]
    for line_index in sorted_idx[1:]:
        if line_index == end + 1:
            end = line_index
            continue
        runs.append((start, end))
        start = end = line_index
    runs.append((start, end))
    return runs


def _build_column_divider_vectors(
    *,
    value_block_x: int,
    table_y: int,
    commodity_row_indices: List[int],
    include_fc_column: bool,
) -> List[OverlayVectorLayer]:
    """Vertical rules between value columns, only across commodity data rows."""
    divider_xs = value_column_divider_x_positions(value_block_x, include_fc_column=include_fc_column)
    runs = _contiguous_line_index_runs(commodity_row_indices)
    vectors: List[OverlayVectorLayer] = []
    segment = 0
    for x_pos in divider_xs:
        for run_start, run_end in runs:
            if segment >= MAX_COLUMN_DIVIDER_SEGMENTS:
                return vectors
            y1 = table_y + run_start * LINE_HEIGHT
            y2 = table_y + (run_end + 1) * LINE_HEIGHT
            vectors.append(
                OverlayVectorLayer(
                    msg_id=f"{MSG_COL_DIVIDER_PREFIX}{segment:02d}",
                    x=x_pos,
                    y1=y1,
                    y2=y2,
                    color=COLUMN_DIVIDER_COLOR,
                )
            )
            segment += 1
    return vectors


def _build_row_stripe_rects(
    *,
    commodity_row_indices: List[int],
    table_x: int,
    table_y: int,
    table_width: int,
) -> List[OverlayRectLayer]:
    """Alternating semi-transparent bands behind commodity data rows."""
    if table_width <= 0:
        return []
    rects: List[OverlayRectLayer] = []
    for stripe_index, line_index in enumerate(commodity_row_indices):
        if stripe_index % 2 == 0:
            continue
        if len(rects) >= MAX_ROW_STRIPES:
            break
        rects.append(
            OverlayRectLayer(
                msg_id=f"{MSG_ROW_STRIPE_PREFIX}{len(rects):02d}",
                x=table_x,
                y=table_y + line_index * LINE_HEIGHT + ROW_STRIPE_Y_OFFSET,
                w=table_width,
                h=ROW_STRIPE_HEIGHT,
                fill=ROW_STRIPE_FILL,
            )
        )
    return rects


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
    fc_capacity_line: Optional[str] = None,
) -> tuple[List[str], List[str], List[Tuple[str, ...]], List[str], List[int], bool]:
    """Return split table text, value cells, footer lines, row indices, and FC visibility."""
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
        return [], [], [], [], [], False

    name_w = max(len(tr("Commodity")), max(len(r[0]) for r in rows))
    fc_hdr = fc_column_title if len(fc_column_title) <= 8 else fc_column_title[:8]
    rule_w = name_w + 8 + (12 if show_fc else 0) + (6 if show_assign else 0)

    label_lines: List[str] = []
    value_lines: List[str] = []
    value_cells: List[Tuple[str, ...]] = []
    commodity_row_indices: List[int] = []

    def _pair(label_part: str, value_part: str, cells: Tuple[str, ...] = ()) -> None:
        label_lines.append(label_part)
        value_lines.append(value_part)
        value_cells.append(cells)

    lp: List[str] = []
    vp: List[str] = []
    if show_assign:
        lp.append(tr(ASSIGN_COLUMN_HEADER))
        vp.append("")
    lp.append(tr("Commodity").ljust(name_w))
    vp.append(f"{tr('Need'):>{VALUE_COL_NEED_CHARS}}")
    vp.append(f"{tr('Ship'):>{VALUE_COL_SHIP_CHARS}}")
    if show_fc:
        vp.append(f"{fc_hdr[:VALUE_COL_FC_CHARS]:>{VALUE_COL_FC_CHARS}}")
    header_cells = (tr("Need"), tr("Ship"), fc_hdr[:VALUE_COL_FC_CHARS]) if show_fc else (tr("Need"), tr("Ship"))
    _pair("  ".join(lp), "  ".join(vp), header_cells)
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
            ship_text = format_overlay_ship_cell(ship)
            vp = [f"{need:5d}", ship_text]
            row_cells: List[str] = [str(need), ship_text.strip()]
            if show_fc:
                if fc_val is None:
                    fc_text = "sync"
                    vp.append(f"{fc_text:>{VALUE_COL_FC_CHARS}}")
                else:
                    fc_text = format_fc_delta(int(fc_val))
                    vp.append(f"{fc_text:>{VALUE_COL_FC_CHARS}}")
                row_cells.append(fc_text)
            _pair("  ".join(lp), "  ".join(vp), tuple(row_cells))
            commodity_row_indices.append(len(label_lines) - 1)

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

    # Optional per-carrier owner capacity line (placed directly under the FC deficit footer line
    # when the user has selected a specific carrier (not All) and a matching local CAPI capacity
    # (freeSpace) is cached for that marketId). It uses the positive surplus (sum of + values
    # from the current FC column) vs the cached freeSpace.
    if fc_capacity_line:
        footer_lines.append(str(fc_capacity_line))

    return label_lines, value_lines, value_cells, footer_lines, commodity_row_indices, show_fc
