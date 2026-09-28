"""Themed multi-layer overlay rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

try:
    from ..api.client import normalize_commodity_key
    from ..i18n import tr
except ImportError:
    from api.client import normalize_commodity_key
    from i18n import tr  # type: ignore[no-redef]

from .commodity_categories import category_for_commodity_key, category_sort_key, format_category_header
from .fc_cargo import format_fc_delta
from .formatting import (
    ASSIGN_COLUMN_HEADER,
    ASSIGN_SYMBOL_ME,
    ASSIGN_SYMBOL_OTHER,
    AssignmentKind,
    OverlayNeedRow,
    format_commodity_label,
    format_trip_footer_lines,
    _format_assignment_cell,
    format_overlay_ship_cell,
)
from .layers import (
    COLUMN_DIVIDER_COLOR,
    LINE_HEIGHT,
    MAX_COLUMN_DIVIDER_SEGMENTS,
    MAX_CATEGORY_RULES,
    MSG_CATEGORY_RULE_PREFIX,
    MSG_CATEGORY_OVERLINE_PREFIX,
    MSG_TABLE_HEADER_RULE,
    MSG_COL_DIVIDER_PREFIX,
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
    ROW_STRIPE_HEIGHT,
    ROW_STRIPE_Y_OFFSET,
    TABLE_TOP_PADDING,
    VALUE_COL_FC_CHARS,
    VALUE_COL_NEED_CHARS,
    PURCHASE_COLUMN_GAP_PX,
    PANEL_RIGHT_PADDING,
    VALUE_COL_SHIP_CHARS,
    MSG_TABLE_LABEL_PREFIX,
    MSG_TABLE_NEED_PREFIX,
    MSG_TABLE_SHIP_PREFIX,
    MSG_TABLE_FC_PREFIX,
    MSG_TABLE_VALUE_PREFIX,
    estimate_value_text_width,
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
from .row_shading import DEFAULT_ROW_HIGHLIGHT_OPACITY, normalize_row_highlight_opacity, row_highlight_fill
from .text_metrics import text_cell_width, wrap_display_text


@dataclass(frozen=True)
class OverlayRenderBundle:
    """Group text, rectangle, and vector layers for one overlay frame."""

    text_layers: List[OverlayTextLayer]
    rect_layers: List[OverlayRectLayer] = field(default_factory=list)
    vector_layers: List[OverlayVectorLayer] = field(default_factory=list)


def _append_fc_jump_footer_layers(
    layers: List[OverlayTextLayer],
    y: int,
    fc_jump_footer_lines: Optional[List[str]],
    pal: OverlayTheme,
) -> None:
    """Render FC jump countdown as the always-last overlay footer block."""
    if not fc_jump_footer_lines:
        return
    visible = [str(line) for line in fc_jump_footer_lines if line]
    if not visible:
        return
    layers.append(
        OverlayTextLayer(
            MSG_FOOTER,
            "\n".join(visible),
            pal.header_primary,
            OVERLAY_X,
            y + FOOTER_TOP_PADDING,
            weight=WEIGHT_FOOTER,
        )
    )


def _append_overlay_header_layers(
    layers: List[OverlayTextLayer],
    *,
    header: str,
    subheader: Optional[str],
    pal: OverlayTheme,
) -> int:
    """Append build/system header text layers; return next Y offset."""
    y = OVERLAY_Y
    if header:
        layers.append(
            OverlayTextLayer(MSG_HDR_BUILD, header.strip(), pal.header_primary,
                             OVERLAY_X, y, weight=WEIGHT_HEADER_PRIMARY)
        )
        y += LINE_HEIGHT
    if subheader:
        layers.append(
            OverlayTextLayer(MSG_HDR_SYSTEM, subheader.strip(), pal.header_secondary,
                             OVERLAY_X, y, weight=WEIGHT_HEADER_SECONDARY)
        )
        y += LINE_HEIGHT
    return y


def _overlay_status_bundle(
    layers: List[OverlayTextLayer],
    y: int,
    message: str,
    *,
    pal: OverlayTheme,
    fc_jump_footer_lines: Optional[List[str]],
    weight: int = WEIGHT_BODY,
    msg_id: str = MSG_HDR_BUILD,
    color: Optional[str] = None,
) -> OverlayRenderBundle:
    layers.append(
        OverlayTextLayer(
            msg_id, message, color or pal.commodity, OVERLAY_X, y, weight=weight,
        )
    )
    y += LINE_HEIGHT
    _append_fc_jump_footer_layers(layers, y, fc_jump_footer_lines, pal)
    return OverlayRenderBundle(layers, [], [])


def _append_row_value_cells(
    layers: List[OverlayTextLayer],
    cells: Tuple[str, ...],
    right_edges: List[int],
    line_index: int,
    row_y: int,
    pal: OverlayTheme,
) -> None:
    prefixes = (MSG_TABLE_NEED_PREFIX, MSG_TABLE_SHIP_PREFIX, MSG_TABLE_FC_PREFIX)
    for cell_index, cell_text in enumerate(cells[: len(right_edges)]):
        value = str(cell_text or "")
        if not value.strip():
            continue
        text_x = right_edges[cell_index] - estimate_value_text_width(value)
        layers.append(
            OverlayTextLayer(
                f"{prefixes[cell_index]}{line_index:03d}",
                value,
                pal.values,
                text_x,
                row_y,
                weight=WEIGHT_EMPHASIS,
            )
        )


def _append_overlay_table_row_layers(
    layers: List[OverlayTextLayer],
    *,
    label_lines: List[str],
    value_lines: List[str],
    value_cells: List[Tuple[str, ...]],
    table_y: int,
    val_x: int,
    value_right_edges: List[int],
    commodity_row_indices: List[int],
    pal: OverlayTheme,
) -> int:
    line_count = max(len(label_lines), len(value_lines))
    commodity_rows = set(commodity_row_indices)
    for line_index in range(line_count):
        row_y = table_y + line_index * LINE_HEIGHT
        label_text = label_lines[line_index] if line_index < len(label_lines) else ""
        value_text = value_lines[line_index] if line_index < len(value_lines) else ""
        category_heading = line_index > 0 and line_index not in commodity_rows
        _append_table_label(layers, label_text, line_index, row_y, pal,
                            category_heading=category_heading, commodity_row=line_index in commodity_rows)
        cells = value_cells[line_index] if line_index < len(value_cells) else ()
        if cells:
            _append_row_value_cells(layers, cells, value_right_edges, line_index, row_y, pal)
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
    return table_y + LINE_HEIGHT * line_count + FOOTER_TOP_PADDING


def _append_table_label(
    layers: List[OverlayTextLayer], text: str, line_index: int, y: int, pal: OverlayTheme,
    *, category_heading: bool, commodity_row: bool,
) -> None:
    if not text:
        return
    layers.append(OverlayTextLayer(
        f"{MSG_TABLE_LABEL_PREFIX}{line_index:03d}", text,
        pal.header_primary if category_heading else pal.commodity, OVERLAY_X, y,
        weight=WEIGHT_BODY if commodity_row else WEIGHT_COLUMN_HEADER,
    ))


def _append_table_footer(
    layers: List[OverlayTextLayer], footer_lines: List[str], pal: OverlayTheme, y: int, *, width: int,
) -> None:
    visible = [line for line in footer_lines if line is not None]
    while visible and not str(visible[0]).strip():
        visible.pop(0)
    footer_text = "\n".join(_wrap_footer_lines(visible, width=width))
    if footer_text.strip():
        layers.append(
            OverlayTextLayer(MSG_FOOTER, footer_text, pal.header_primary, OVERLAY_X, y, weight=WEIGHT_FOOTER)
        )


def _wrap_footer_lines(lines: List[str], *, width: int) -> List[str]:
    """Prefer semantic arrow boundaries, then spaces within unusually long clauses."""
    wrapped: List[str] = []
    for line in lines:
        if text_cell_width(line) <= width:
            wrapped.append(line)
            continue
        clauses = line.split(" > ")
        for index, clause in enumerate(clauses):
            text = f"> {clause}" if index else clause
            # Keep short summary phrases intact even on a narrow Purchase table.
            wrap_width = max(24, width) if len(clauses) > 1 else width
            wrapped.extend(wrap_display_text(text, width=wrap_width))
    return wrapped


def build_overlay_layers(
    *,
    header: str,
    needs: Mapping[str, int],
    cargo: Mapping[str, int],
    subheader: Optional[str] = None,
    complete: bool = False,
    assignments: Optional[Mapping[str, AssignmentKind]] = None,
    fc_deltas: Optional[Mapping[str, int]] = None,
    purchase_amounts: Optional[Mapping[str, Optional[int]]] = None,
    category_purchase_amounts: Optional[Mapping[str, Optional[int]]] = None,
    show_completed_commodities: bool = False,
    fc_column_title: str = "FC's",
    ship_cargo_capacity: Optional[int] = None,
    show_fc_trip_summary: bool = False,
    fc_deficit_total: Optional[int] = None,
    fc_summary_label: str = "FC's",
    fc_capacity_line: Optional[str] = None,
    fc_jump_footer_lines: Optional[List[str]] = None,
    theme: Optional[OverlayTheme] = None,
    row_stripes: bool = True,
    row_highlight_opacity: int = DEFAULT_ROW_HIGHLIGHT_OPACITY,
    column_dividers: bool = True,
) -> OverlayRenderBundle:
    """Build themed overlay layers (separate colors per HUD role)."""
    pal = theme or get_overlay_theme(None)
    layers: List[OverlayTextLayer] = []
    rects: List[OverlayRectLayer] = []
    vectors: List[OverlayVectorLayer] = []

    y = _append_overlay_header_layers(layers, header=header, subheader=subheader, pal=pal)

    if complete and not show_completed_commodities:
        layers.append(
            OverlayTextLayer(MSG_HDR_BUILD, tr("Construction complete"),
                             pal.header_primary, OVERLAY_X, y, weight=WEIGHT_HEADER_PRIMARY)
        )
        y += LINE_HEIGHT
        _append_fc_jump_footer_layers(layers, y, fc_jump_footer_lines, pal)
        return OverlayRenderBundle(layers, rects, vectors)

    if not needs:
        return _overlay_status_bundle(
            layers, y, tr("No remaining commodities"),
            pal=pal, fc_jump_footer_lines=fc_jump_footer_lines,
        )

    if purchase_amounts is not None:
        table = _build_purchase_table_lines(
            needs=needs,
            assignments=assignments,
            purchase=purchase_amounts,
            show_completed=show_completed_commodities,
            ship_cargo_capacity=ship_cargo_capacity,
            fc_jump_footer_lines=fc_jump_footer_lines,
        )
    else:
        table = _build_split_table_lines(
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
            fc_jump_footer_lines=fc_jump_footer_lines,
            category_purchase_amounts=category_purchase_amounts,
            show_completed=show_completed_commodities,
        )
    (
        label_lines,
        value_lines,
        value_cells,
        footer_lines,
        commodity_row_indices,
        show_fc_column,
    ) = table

    if not label_lines:
        bundle = _overlay_status_bundle(
            layers, y, tr("No purchases needed"),
            pal=pal, fc_jump_footer_lines=None,
            msg_id=f"{MSG_TABLE_LABEL_PREFIX}000",
        )
        _append_table_footer(layers, footer_lines, pal, y + LINE_HEIGHT, width=max(24, text_cell_width(header)))
        return bundle

    table_y = y + TABLE_TOP_PADDING
    gap_options = {"gap": PURCHASE_COLUMN_GAP_PX} if purchase_amounts is not None else {}
    val_x = values_column_x(label_lines, **gap_options)
    column_width = max(estimate_value_text_width(cell) for cells in value_cells for cell in cells)
    value_right_edges = (
        [val_x + column_width] if purchase_amounts is not None
        else value_column_right_edges(val_x, include_fc_column=show_fc_column, column_width=column_width)
    )
    table_w = value_right_edges[-1] - OVERLAY_X
    opacity = normalize_row_highlight_opacity(row_highlight_opacity)
    if row_stripes and opacity and commodity_row_indices:
        rects = _build_row_stripe_rects(
            commodity_row_indices=commodity_row_indices,
            table_x=OVERLAY_X,
            table_y=table_y,
            table_width=table_w,
            fill=row_highlight_fill(opacity),
        )
    if column_dividers and commodity_row_indices and purchase_amounts is None:
        vectors = _build_column_divider_vectors(
            value_block_x=val_x,
            table_y=table_y,
            commodity_row_indices=commodity_row_indices,
            include_fc_column=show_fc_column,
            column_width=column_width,
        )
    y = _append_overlay_table_row_layers(
        layers,
        label_lines=label_lines,
        value_lines=value_lines,
        value_cells=value_cells,
        table_y=table_y,
        val_x=val_x,
        value_right_edges=value_right_edges,
        commodity_row_indices=commodity_row_indices,
        pal=pal,
    )

    if footer_lines:
        _append_table_footer(layers, footer_lines, pal, y, width=_compact_footer_width(label_lines, value_lines))

    label_right = values_column_x(label_lines, gap=0)
    panel_width = _panel_rule_width(layers, value_right_edges[-1])
    rects.extend(_build_table_rules(label_lines, commodity_row_indices, table_y, panel_width, label_right, pal))
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


def _panel_rule_width(layers: List[OverlayTextLayer], table_right: int) -> int:
    """Span the whole content block, including longer headers, footers, and a right gutter."""
    text_right = max(layer.x + estimate_value_text_width(line)
                     for layer in layers for line in layer.text.splitlines())
    return max(table_right, text_right) + PANEL_RIGHT_PADDING - OVERLAY_X


def _build_table_rules(
    labels: List[str], commodity_rows: List[int], table_y: int, table_width: int,
    label_right: int, pal: OverlayTheme,
) -> List[OverlayRectLayer]:
    """Span the header and enclose category headings with matching commodity-width rules."""
    rules = [OverlayRectLayer(MSG_TABLE_HEADER_RULE, OVERLAY_X, table_y + LINE_HEIGHT - 3,
                              table_width, 1, fill=pal.commodity)]
    row_indices = set(commodity_rows)
    categories = [index for index, label in enumerate(labels) if index > 0 and label and index not in row_indices]
    for rule_index, line_index in enumerate(categories[:MAX_CATEGORY_RULES]):
        rules.append(OverlayRectLayer(
            f"{MSG_CATEGORY_RULE_PREFIX}{rule_index:02d}", OVERLAY_X,
            table_y + (line_index + 1) * LINE_HEIGHT - 3,
            label_right - OVERLAY_X, 1, fill=pal.header_primary,
        ))
        rules.append(OverlayRectLayer(
            f"{MSG_CATEGORY_OVERLINE_PREFIX}{rule_index:02d}", OVERLAY_X,
            table_y + line_index * LINE_HEIGHT - 2,
            label_right - OVERLAY_X, 1, fill=pal.header_primary,
        ))
    return rules


def _build_column_divider_vectors(
    *,
    value_block_x: int,
    table_y: int,
    commodity_row_indices: List[int],
    include_fc_column: bool,
    column_width: int,
) -> List[OverlayVectorLayer]:
    """Vertical rules between value columns, only across commodity data rows."""
    divider_xs = value_column_divider_x_positions(
        value_block_x, include_fc_column=include_fc_column, column_width=column_width,
    )
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
    fill: str,
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
                fill=fill,
            )
        )
    return rects


def _split_table_need_rows(
    needs: Mapping[str, int],
    cargo: Mapping[str, int],
    *,
    assign_map: Mapping[str, AssignmentKind],
    show_assign: bool,
    show_fc: bool,
    delta_map: Mapping[str, int],
    show_completed: bool = False,
) -> Tuple[List[Tuple[str, str, str, int, int, Optional[int]]], int]:
    row_type = Tuple[str, str, str, int, int, Optional[int]]
    rows: List[row_type] = []
    total_need = 0
    for key, raw_need in needs.items():
        need = int(raw_need)
        if need < 0 or (need == 0 and not show_completed):
            continue
        nk = normalize_commodity_key(str(key))
        ship = int(cargo.get(key, 0) or cargo.get(nk, 0))
        asg = _format_assignment_cell(assign_map.get(nk) if show_assign else None)
        fc_val: Optional[int] = delta_map.get(nk) if show_fc else None
        rows.append((format_commodity_label(key), asg, nk, need, ship, fc_val))
        total_need += need
    return rows, total_need


def _append_split_table_header_rows(
    pair: Any,
    *,
    show_assign: bool,
    show_fc: bool,
    fc_hdr: str,
) -> None:
    lp: List[str] = []
    vp: List[str] = []
    if show_assign:
        lp.append(tr(ASSIGN_COLUMN_HEADER))
        vp.append("")
    lp.append(tr("Commodity"))
    vp.append(f"{tr('Need'):>{VALUE_COL_NEED_CHARS}}")
    vp.append(f"{tr('Ship'):>{VALUE_COL_SHIP_CHARS}}")
    if show_fc:
        vp.append(f"{fc_hdr[:VALUE_COL_FC_CHARS]:>{VALUE_COL_FC_CHARS}}")
    header_cells = (tr("Need"), tr("Ship"), fc_hdr[:VALUE_COL_FC_CHARS]) if show_fc else (tr("Need"), tr("Ship"))
    pair("  ".join(lp), "  ".join(vp), header_cells)


def _append_split_table_category_rows(
    pair: Any,
    rows: List[Tuple[str, str, str, int, int, Optional[int]]],
    commodity_row_indices: List[int],
    label_lines: List[str],
    *,
    show_assign: bool,
    show_fc: bool,
    category_purchase_amounts: Optional[Mapping[str, Optional[int]]],
    show_completed: bool,
) -> None:
    buckets: Dict[str, List[Tuple[str, str, str, int, int, Optional[int]]]] = {}
    for row in rows:
        buckets.setdefault(category_for_commodity_key(row[2]), []).append(row)
    for cat in sorted(buckets.keys(), key=category_sort_key):
        cat_rows = buckets[cat]
        if not show_completed and not _breakdown_category_needs_purchase(
            cat_rows, show_fc=show_fc, purchase=category_purchase_amounts,
        ):
            continue
        cat_rows.sort(key=lambda r: r[0].lower())
        sep = format_category_header(cat)
        pair(sep, "")
        for row in cat_rows:
            _append_split_table_commodity_row(pair, row, show_assign=show_assign, show_fc=show_fc)
            commodity_row_indices.append(len(label_lines) - 1)


def _append_split_table_commodity_row(pair: Any, row: OverlayNeedRow, *, show_assign: bool, show_fc: bool) -> None:
    name, assignment, _key, need, ship, fc_val = row
    labels = ([f"{assignment:>3}"] if show_assign else []) + [name]
    ship_text = format_overlay_ship_cell(ship)
    values = [f"{need:5d}", ship_text]
    cells = [str(need), ship_text.strip()]
    if show_fc:
        fc_text = tr("sync") if fc_val is None else format_fc_delta(int(fc_val))
        values.append(f"{fc_text:>{VALUE_COL_FC_CHARS}}")
        cells.append(fc_text)
    pair("  ".join(labels), "  ".join(values), tuple(cells))


def _purchase_footer_lines(
    *, show_assign: bool, total_need: int, ship_cargo_capacity: Optional[int],
    fc_jump_footer_lines: Optional[List[str]],
) -> List[str]:
    footer_lines: List[str] = []
    if show_assign:
        footer_lines.extend(["", f"{ASSIGN_SYMBOL_ME} = yours   {ASSIGN_SYMBOL_OTHER} = other CMDR"])
    footer_lines.extend(
        format_trip_footer_lines(total_remaining=total_need, ship_cargo_capacity=ship_cargo_capacity)
    )
    if fc_jump_footer_lines:
        footer_lines.extend(str(line) for line in fc_jump_footer_lines if line)
    return footer_lines


def _build_purchase_table_lines(
    *,
    needs: Mapping[str, int],
    assignments: Optional[Mapping[str, AssignmentKind]],
    purchase: Mapping[str, Optional[int]],
    show_completed: bool,
    ship_cargo_capacity: Optional[int],
    fc_jump_footer_lines: Optional[List[str]],
) -> tuple[List[str], List[str], List[Tuple[str, ...]], List[str], List[int], bool]:
    """One Purchase column, retaining category rows and assignment hints."""
    assign_map = dict(assignments or {})
    show_assign = bool(assign_map)
    rows, total_need = _split_table_need_rows(
        needs, {}, assign_map=assign_map, show_assign=show_assign,
        show_fc=True, delta_map=purchase,
        show_completed=show_completed,
    )
    if not rows:
        return [], [], [], [], [], False

    label_lines: List[str] = []
    value_lines: List[str] = []
    value_cells: List[Tuple[str, ...]] = []
    commodity_row_indices: List[int] = []

    def pair(label: str, value: str, cells: Tuple[str, ...] = ()) -> None:
        label_lines.append(label)
        value_lines.append(value)
        value_cells.append(cells)

    label_header = "  ".join(([tr(ASSIGN_COLUMN_HEADER)] if show_assign else []) + [tr("Commodity")])
    purchase_header = tr("Purchase")
    pair(label_header, purchase_header, (purchase_header,))

    buckets: Dict[str, List[Tuple[str, str, str, int, int, Optional[int]]]] = {}
    for row in rows:
        buckets.setdefault(category_for_commodity_key(row[2]), []).append(row)
    for category in sorted(buckets, key=category_sort_key):
        if not show_completed and not _category_needs_purchase(buckets[category]):
            continue
        pair(format_category_header(category), "")
        for row in sorted(buckets[category], key=lambda row: row[0].lower()):
            label, value = _purchase_row_cells(row, show_assign=show_assign)
            pair(label, value, (value,))
            commodity_row_indices.append(len(label_lines) - 1)

    footer_lines = _purchase_footer_lines(
        show_assign=show_assign,
        total_need=total_need,
        ship_cargo_capacity=ship_cargo_capacity,
        fc_jump_footer_lines=fc_jump_footer_lines,
    )
    if not commodity_row_indices:
        return [], [], [], footer_lines, [], False
    return label_lines, value_lines, value_cells, footer_lines, commodity_row_indices, False


def _compact_footer_width(label_lines: List[str], value_lines: List[str]) -> int:
    return max(map(text_cell_width, label_lines)) + 2 + max(map(text_cell_width, value_lines))


def _category_needs_purchase(rows: List[OverlayNeedRow]) -> bool:
    """Keep unknown manifests visible as well as positive purchase amounts."""
    return any(row[5] != 0 for row in rows)


def _breakdown_category_needs_purchase(
    rows: List[OverlayNeedRow], *, show_fc: bool, purchase: Optional[Mapping[str, Optional[int]]],
) -> bool:
    """FC deltas already subtract construction needs, so include ship cargo once."""
    if purchase is not None:
        return any(purchase.get(row[2]) != 0 for row in rows)
    for _name, _assignment, _key, need, ship, delta in rows:
        if ship >= need:
            continue
        if show_fc:
            if delta is None or -delta > ship:
                return True
        elif need > ship:
            return True
    return False


def _purchase_row_cells(row: OverlayNeedRow, *, show_assign: bool) -> Tuple[str, str]:
    name, assignment, _key, _need, _ship, amount = row
    label = "  ".join(([f"{assignment:>3}"] if show_assign else []) + [name])
    return label, tr("sync") if amount is None else str(amount)


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
    fc_jump_footer_lines: Optional[List[str]] = None,
    category_purchase_amounts: Optional[Mapping[str, Optional[int]]] = None,
    show_completed: bool = False,
) -> tuple[List[str], List[str], List[Tuple[str, ...]], List[str], List[int], bool]:
    """Return split table text, value cells, footer lines, row indices, and FC visibility."""
    assign_map = dict(assignments or {})
    show_assign = bool(assign_map)
    show_fc = fc_deltas is not None
    delta_map = dict(fc_deltas or {})

    rows, total_need = _split_table_need_rows(
        needs, cargo,
        assign_map=assign_map, show_assign=show_assign, show_fc=show_fc, delta_map=delta_map,
        show_completed=show_completed,
    )
    if not rows:
        return [], [], [], [], [], False

    fc_hdr = fc_column_title if len(fc_column_title) <= 8 else fc_column_title[:8]

    label_lines: List[str] = []
    value_lines: List[str] = []
    value_cells: List[Tuple[str, ...]] = []
    commodity_row_indices: List[int] = []

    def _pair(label_part: str, value_part: str, cells: Tuple[str, ...] = ()) -> None:
        label_lines.append(label_part)
        value_lines.append(value_part)
        value_cells.append(cells)

    _append_split_table_header_rows(
        _pair, show_assign=show_assign, show_fc=show_fc, fc_hdr=fc_hdr,
    )
    _append_split_table_category_rows(
        _pair, rows, commodity_row_indices, label_lines,
        show_assign=show_assign, show_fc=show_fc,
        category_purchase_amounts=category_purchase_amounts,
        show_completed=show_completed,
    )

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
    if fc_jump_footer_lines:
        footer_lines.extend(str(line) for line in fc_jump_footer_lines if line)

    if not commodity_row_indices:
        return [], [], [], footer_lines, [], False
    return label_lines, value_lines, value_cells, footer_lines, commodity_row_indices, show_fc
