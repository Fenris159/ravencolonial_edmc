"""Multi-color overlay layers (one EDMCModernOverlay message per role)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from .bridge import OVERLAY_MESSAGE_PREFIX
from .row_shading import DEFAULT_ROW_HIGHLIGHT_OPACITY, row_highlight_fill

OVERLAY_X = 28
OVERLAY_Y = 140
# Modern Overlay renders multiline payloads using Qt font metrics; keep our
# layer offsets in the same ballpark so independent text blocks do not overlap.
LINE_HEIGHT = 20
TABLE_TOP_PADDING = 8
FOOTER_TOP_PADDING = 0
CHAR_WIDTH_EST = 7.2
LABEL_CHAR_WIDTH_EST = CHAR_WIDTH_EST
VALUE_COLUMN_GAP_PX = 20
PURCHASE_COLUMN_GAP_PX = 12
PANEL_RIGHT_PADDING = 8

# Value block column widths (must match ``render_layers._build_split_table_lines``).
VALUE_COL_NEED_CHARS = 5
VALUE_COL_SHIP_CHARS = 5
VALUE_COL_FC_CHARS = 7
VALUE_COL_GAP_CHARS = 2
NUMERIC_COLUMN_GAP_PX = 20

# 8% opaque space grey band for alternating commodity rows (#AARRGGBB).
ROW_STRIPE_FILL = row_highlight_fill(DEFAULT_ROW_HIGHLIGHT_OPACITY)
ROW_STRIPE_BORDER = "none"
ROW_STRIPE_HEIGHT = 16
ROW_STRIPE_Y_OFFSET = 2
MAX_ROW_STRIPES = 48
MAX_TABLE_LINES = 160
MAX_CATEGORY_RULES = 32

# Vertical rules between Need / Ship / FC (#AARRGGBB).
COLUMN_DIVIDER_COLOR = "#70F0D0A0"
MAX_COLUMN_DIVIDER_SEGMENTS = 32

MSG_HDR_BUILD = f"{OVERLAY_MESSAGE_PREFIX}hdr-build"
MSG_HDR_SYSTEM = f"{OVERLAY_MESSAGE_PREFIX}hdr-system"
MSG_COL_LABELS = f"{OVERLAY_MESSAGE_PREFIX}col-labels"
MSG_COL_VALUES = f"{OVERLAY_MESSAGE_PREFIX}col-values"
MSG_FOOTER = f"{OVERLAY_MESSAGE_PREFIX}footer"
MSG_MAIN_LEGACY = f"{OVERLAY_MESSAGE_PREFIX}main"
MSG_ROW_STRIPE_PREFIX = f"{OVERLAY_MESSAGE_PREFIX}row-"
MSG_COL_DIVIDER_PREFIX = f"{OVERLAY_MESSAGE_PREFIX}coldiv-"
MSG_TABLE_LABEL_PREFIX = f"{OVERLAY_MESSAGE_PREFIX}table-label-"
MSG_TABLE_VALUE_PREFIX = f"{OVERLAY_MESSAGE_PREFIX}table-value-"
MSG_TABLE_NEED_PREFIX = f"{OVERLAY_MESSAGE_PREFIX}table-need-"
MSG_TABLE_SHIP_PREFIX = f"{OVERLAY_MESSAGE_PREFIX}table-ship-"
MSG_TABLE_FC_PREFIX = f"{OVERLAY_MESSAGE_PREFIX}table-fc-"
MSG_TABLE_HEADER_RULE = f"{OVERLAY_MESSAGE_PREFIX}table-header-rule"
MSG_CATEGORY_RULE_PREFIX = f"{OVERLAY_MESSAGE_PREFIX}category-rule-"
MSG_CATEGORY_OVERLINE_PREFIX = f"{OVERLAY_MESSAGE_PREFIX}category-overline-"


def row_stripe_message_ids() -> Tuple[str, ...]:
    """Return row stripe message ids."""
    return tuple(f"{MSG_ROW_STRIPE_PREFIX}{index:02d}" for index in range(MAX_ROW_STRIPES))


def column_divider_message_ids() -> Tuple[str, ...]:
    """Return column divider message ids."""
    return tuple(f"{MSG_COL_DIVIDER_PREFIX}{index:02d}" for index in range(MAX_COLUMN_DIVIDER_SEGMENTS))


def category_rule_message_ids() -> Tuple[str, ...]:
    """Return stable category rule ids for stale-layer cleanup."""
    return tuple(f"{prefix}{index:02d}" for prefix in (MSG_CATEGORY_RULE_PREFIX, MSG_CATEGORY_OVERLINE_PREFIX)
                 for index in range(MAX_CATEGORY_RULES))


def table_text_message_ids() -> Tuple[str, ...]:
    """Return table text message ids."""
    ids: list[str] = []
    for index in range(MAX_TABLE_LINES):
        ids.append(f"{MSG_TABLE_LABEL_PREFIX}{index:03d}")
        ids.append(f"{MSG_TABLE_VALUE_PREFIX}{index:03d}")
        ids.append(f"{MSG_TABLE_NEED_PREFIX}{index:03d}")
        ids.append(f"{MSG_TABLE_SHIP_PREFIX}{index:03d}")
        ids.append(f"{MSG_TABLE_FC_PREFIX}{index:03d}")
    return tuple(ids)


ALL_OVERLAY_MESSAGE_IDS: tuple[str, ...] = (
    MSG_MAIN_LEGACY,
    MSG_HDR_BUILD,
    MSG_HDR_SYSTEM,
    MSG_COL_LABELS,
    MSG_COL_VALUES,
    MSG_FOOTER,
    MSG_TABLE_HEADER_RULE,
) + row_stripe_message_ids() + column_divider_message_ids() + category_rule_message_ids() + table_text_message_ids()


@dataclass(frozen=True)
class OverlayTextLayer:
    """Describe a positioned text layer in the overlay."""

    msg_id: str
    text: str
    color: str
    x: int
    y: int
    weight: int = 400
    size: str = "normal"


@dataclass(frozen=True)
class OverlayRectLayer:
    """Filled rectangle behind commodity rows (LegacyOverlay shape)."""

    msg_id: str
    x: int
    y: int
    w: int
    h: int
    fill: str = ROW_STRIPE_FILL
    border_color: str = ROW_STRIPE_BORDER


@dataclass(frozen=True)
class OverlayVectorLayer:
    """Vertical line segment between value columns (LegacyOverlay vect)."""

    msg_id: str
    x: int
    y1: int
    y2: int
    color: str = COLUMN_DIVIDER_COLOR


def values_column_x(label_lines: List[str], *, gap: int = VALUE_COLUMN_GAP_PX) -> int:
    """Legacy-canvas X for the numeric column block (monospace estimate)."""
    if not label_lines:
        return OVERLAY_X
    content_lines = [
        line.rstrip()
        for line in label_lines
        if line.strip() and not line.strip().startswith("-")
    ]
    width = max((len(line) for line in content_lines), default=0)
    return OVERLAY_X + int(width * LABEL_CHAR_WIDTH_EST) + gap


def value_column_divider_x_positions(
    value_block_x: int, *, include_fc_column: bool, column_width: int = 36,
) -> List[int]:
    """Center vertical rules in the equal gaps between numeric columns."""
    edges = value_column_right_edges(value_block_x, include_fc_column=include_fc_column, column_width=column_width)
    return [edge + NUMERIC_COLUMN_GAP_PX // 2 for edge in edges[:-1]]


def value_column_right_edges(
    value_block_x: int, *, include_fc_column: bool, column_width: int = 36,
) -> List[int]:
    """Right-edge coordinates for equally sized Need, Ship, and optional FC columns."""
    count = 3 if include_fc_column else 2
    return [value_block_x + column_width + index * (column_width + NUMERIC_COLUMN_GAP_PX)
            for index in range(count)]


def estimate_value_text_width(text: str) -> int:
    """Approximate rendered value/header width for separate column placement."""
    return int(max(0, len(str(text))) * CHAR_WIDTH_EST)


def table_content_width(
    label_lines: List[str], value_lines: List[str], *, gap: int = VALUE_COLUMN_GAP_PX,
) -> int:
    """Estimated pixel width spanning label + value columns."""
    if not label_lines:
        return 0
    content_lines = [
        line.rstrip()
        for line in label_lines
        if line.strip() and not line.strip().startswith("-")
    ]
    label_w = int(max((len(line) for line in content_lines), default=0) * LABEL_CHAR_WIDTH_EST)
    value_w = int(max((len(line) for line in value_lines), default=0) * CHAR_WIDTH_EST)
    return label_w + gap + value_w
