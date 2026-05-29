"""Multi-color overlay layers (one EDMCModernOverlay message per role)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from .bridge import OVERLAY_MESSAGE_PREFIX

OVERLAY_X = 28
OVERLAY_Y = 140
LINE_HEIGHT = 14
CHAR_WIDTH_EST = 7.2

# Value block column widths (must match ``render_layers._build_split_table_lines``).
VALUE_COL_NEED_CHARS = 5
VALUE_COL_SHIP_CHARS = 5
VALUE_COL_FC_CHARS = 6
VALUE_COL_GAP_CHARS = 2

# Semi-transparent gray band for alternating commodity rows (#AARRGGBB).
ROW_STRIPE_FILL = "#50333333"
ROW_STRIPE_BORDER = "none"
MAX_ROW_STRIPES = 48

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


def row_stripe_message_ids() -> Tuple[str, ...]:
    return tuple(f"{MSG_ROW_STRIPE_PREFIX}{index:02d}" for index in range(MAX_ROW_STRIPES))


def column_divider_message_ids() -> Tuple[str, ...]:
    return tuple(f"{MSG_COL_DIVIDER_PREFIX}{index:02d}" for index in range(MAX_COLUMN_DIVIDER_SEGMENTS))


ALL_OVERLAY_MESSAGE_IDS: tuple[str, ...] = (
    MSG_MAIN_LEGACY,
    MSG_HDR_BUILD,
    MSG_HDR_SYSTEM,
    MSG_COL_LABELS,
    MSG_COL_VALUES,
    MSG_FOOTER,
) + row_stripe_message_ids() + column_divider_message_ids()


@dataclass(frozen=True)
class OverlayTextLayer:
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


def values_column_x(label_lines: List[str]) -> int:
    """Legacy-canvas X for the numeric column block (monospace estimate)."""
    if not label_lines:
        return OVERLAY_X
    width = max(len(line) for line in label_lines)
    return OVERLAY_X + int(width * CHAR_WIDTH_EST)


def value_column_divider_x_positions(value_block_x: int, *, include_fc_column: bool) -> List[int]:
    """X coordinates for vertical rules between Need|Ship and Ship|FC (column edges)."""
    after_need = value_block_x + int(VALUE_COL_NEED_CHARS * CHAR_WIDTH_EST)
    if not include_fc_column:
        return [after_need]
    after_ship = value_block_x + int(
        (VALUE_COL_NEED_CHARS + VALUE_COL_GAP_CHARS + VALUE_COL_SHIP_CHARS) * CHAR_WIDTH_EST
    )
    return [after_need, after_ship]


def table_content_width(label_lines: List[str], value_lines: List[str]) -> int:
    """Estimated pixel width spanning label + value columns."""
    if not label_lines:
        return 0
    label_w = int(max(len(line) for line in label_lines) * CHAR_WIDTH_EST)
    value_w = int(max((len(line) for line in value_lines), default=0) * CHAR_WIDTH_EST)
    gap = max(0, values_column_x(label_lines) - OVERLAY_X - label_w)
    return label_w + gap + value_w
