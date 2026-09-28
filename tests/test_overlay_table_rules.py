"""Tracker rules and numeric columns align in both the HUD and measured Tk canvas."""

from __future__ import annotations

import tkinter as tk
from types import SimpleNamespace

import pytest

from test_overlay_purchase import BuildProjectPopout, build_overlay_layers
from overlay.layers import (
    ALL_OVERLAY_MESSAGE_IDS,
    MSG_CATEGORY_RULE_PREFIX,
    MSG_TABLE_FC_PREFIX,
    MSG_TABLE_HEADER_RULE,
    MSG_TABLE_LABEL_PREFIX,
    MSG_TABLE_NEED_PREFIX,
    MSG_TABLE_SHIP_PREFIX,
    OVERLAY_X,
    estimate_value_text_width,
)


@pytest.mark.parametrize("simplified", [False, True])
def test_underlines_span_the_header_and_stop_at_the_commodity_edge(simplified: bool) -> None:
    """Both formats give every category the same solid rule and leave a column gap."""
    bundle = build_overlay_layers(
        header="Port", needs={"steel": 100, "water": 10}, cargo={},
        purchase_amounts={"steel": 100, "water": 10} if simplified else None,
    )
    header = next(rect for rect in bundle.rect_layers if rect.msg_id == MSG_TABLE_HEADER_RULE)
    categories = [rect for rect in bundle.rect_layers if rect.msg_id.startswith(MSG_CATEGORY_RULE_PREFIX)]
    values = [layer for layer in bundle.text_layers
              if layer.msg_id.startswith((MSG_TABLE_NEED_PREFIX, MSG_TABLE_SHIP_PREFIX, MSG_TABLE_FC_PREFIX))]
    assert header.x == OVERLAY_X
    assert header.x + header.w == max(layer.x + estimate_value_text_width(layer.text) for layer in values)
    assert len(categories) == 2
    assert len({(rect.x, rect.w) for rect in categories}) == 1
    assert categories[0].x + categories[0].w < min(layer.x for layer in values)
    for rect in [header, *categories]:
        assert rect.h == 1 and rect.border_color == "none"
        assert rect.msg_id in ALL_OVERLAY_MESSAGE_IDS


@pytest.mark.parametrize("carrier_title", ["FC's", "N4W-T0Z"])
def test_numeric_headers_and_values_have_evenly_spaced_right_edges(carrier_title: str) -> None:
    """Large quantities and a callsign cannot give Ship an uneven column interval."""
    bundle = build_overlay_layers(
        header="Port", needs={"steel": 123456, "water": 10}, cargo={"water": 2},
        fc_deltas={"steel": -123456, "water": 17}, fc_column_title=carrier_title,
    )
    right_edges = []
    for prefix in (MSG_TABLE_NEED_PREFIX, MSG_TABLE_SHIP_PREFIX, MSG_TABLE_FC_PREFIX):
        cells = [layer for layer in bundle.text_layers if layer.msg_id.startswith(prefix)]
        edges = {layer.x + estimate_value_text_width(layer.text) for layer in cells}
        assert len(edges) == 1
        right_edges.append(edges.pop())
    assert right_edges[1] - right_edges[0] == right_edges[2] - right_edges[1]


@pytest.mark.parametrize("simplified", [False, True])
def test_popout_rules_stay_below_headings_and_match_measured_columns(simplified: bool) -> None:
    """Tk rules must fit actual fonts and remain between heading and commodity rows."""
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    root.withdraw()
    try:
        canvas = tk.Canvas(root)
        popout = BuildProjectPopout(SimpleNamespace(frame=root))
        bundle = build_overlay_layers(
            header="Port", needs={"steel": 12345, "water": 10}, cargo={},
            fc_deltas={"steel": -12345, "water": 10}, fc_column_title="N4W-T0Z",
            purchase_amounts={"steel": 12345, "water": 10} if simplified else None,
        )
        popout._draw_bundle(canvas, bundle)
        rectangles = [item for item in canvas.find_all() if canvas.type(item) == "rectangle"]
        rules = {rect.msg_id: canvas.coords(item) for rect, item in zip(bundle.rect_layers, rectangles)}
        columns, _left = popout._popout_column_layout(bundle)
        header = rules[MSG_TABLE_HEADER_RULE]
        assert header[2] == max(columns.values())
        categories = [coords for msg_id, coords in rules.items() if msg_id.startswith(MSG_CATEGORY_RULE_PREFIX)]
        assert len({coords[2] for coords in categories}) == 1
        assert categories[0][2] == popout._popout_label_right_edge(bundle)
        text_items = [item for item in canvas.find_all() if canvas.type(item) == "text"]
        row_boxes = {layer.msg_id: canvas.bbox(item) for layer, item in zip(bundle.text_layers, text_items)}
        for coords in [header, *categories]:
            previous = max(box[3] for msg_id, box in row_boxes.items()
                           if msg_id.startswith(MSG_TABLE_LABEL_PREFIX) and box[1] < coords[1])
            following = min(box[1] for msg_id, box in row_boxes.items()
                            if msg_id.startswith(MSG_TABLE_LABEL_PREFIX) and box[1] > coords[1])
            assert previous <= coords[1] < coords[3] <= following
        if not simplified:
            edges = list(columns.values())
            assert edges[1] - edges[0] == edges[2] - edges[1]
    finally:
        root.destroy()
