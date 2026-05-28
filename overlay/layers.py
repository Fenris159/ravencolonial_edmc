"""Multi-color overlay layers (one EDMCModernOverlay message per role)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from .bridge import OVERLAY_MESSAGE_PREFIX

OVERLAY_X = 28
OVERLAY_Y = 140
LINE_HEIGHT = 14
CHAR_WIDTH_EST = 7.2

# Semi-transparent gray band for alternating commodity rows (#AARRGGBB).
ROW_STRIPE_FILL = "#50333333"
ROW_STRIPE_BORDER = "none"
MAX_ROW_STRIPES = 48

MSG_HDR_BUILD = f"{OVERLAY_MESSAGE_PREFIX}hdr-build"
MSG_HDR_SYSTEM = f"{OVERLAY_MESSAGE_PREFIX}hdr-system"
MSG_COL_LABELS = f"{OVERLAY_MESSAGE_PREFIX}col-labels"
MSG_COL_VALUES = f"{OVERLAY_MESSAGE_PREFIX}col-values"
MSG_FOOTER = f"{OVERLAY_MESSAGE_PREFIX}footer"
MSG_MAIN_LEGACY = f"{OVERLAY_MESSAGE_PREFIX}main"
MSG_ROW_STRIPE_PREFIX = f"{OVERLAY_MESSAGE_PREFIX}row-"


def row_stripe_message_ids() -> Tuple[str, ...]:
    return tuple(f"{MSG_ROW_STRIPE_PREFIX}{index:02d}" for index in range(MAX_ROW_STRIPES))


ALL_OVERLAY_MESSAGE_IDS: tuple[str, ...] = (
    MSG_MAIN_LEGACY,
    MSG_HDR_BUILD,
    MSG_HDR_SYSTEM,
    MSG_COL_LABELS,
    MSG_COL_VALUES,
    MSG_FOOTER,
) + row_stripe_message_ids()


@dataclass(frozen=True)
class OverlayTextLayer:
    msg_id: str
    text: str
    color: str
    x: int
    y: int


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


def values_column_x(label_lines: List[str]) -> int:
    """Legacy-canvas X for the numeric column block (monospace estimate)."""
    if not label_lines:
        return OVERLAY_X
    width = max(len(line) for line in label_lines)
    return OVERLAY_X + int(width * CHAR_WIDTH_EST)


def table_content_width(label_lines: List[str], value_lines: List[str]) -> int:
    """Estimated pixel width spanning label + value columns."""
    if not label_lines:
        return 0
    label_w = int(max(len(line) for line in label_lines) * CHAR_WIDTH_EST)
    value_w = int(max((len(line) for line in value_lines), default=0) * CHAR_WIDTH_EST)
    gap = max(0, values_column_x(label_lines) - OVERLAY_X - label_w)
    return label_w + gap + value_w
