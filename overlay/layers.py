"""Multi-color overlay layers (one EDMCModernOverlay message per role)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .bridge import OVERLAY_MESSAGE_PREFIX

OVERLAY_X = 28
OVERLAY_Y = 140
LINE_HEIGHT = 14
CHAR_WIDTH_EST = 7.2

MSG_HDR_BUILD = f"{OVERLAY_MESSAGE_PREFIX}hdr-build"
MSG_HDR_SYSTEM = f"{OVERLAY_MESSAGE_PREFIX}hdr-system"
MSG_COL_LABELS = f"{OVERLAY_MESSAGE_PREFIX}col-labels"
MSG_COL_VALUES = f"{OVERLAY_MESSAGE_PREFIX}col-values"
MSG_FOOTER = f"{OVERLAY_MESSAGE_PREFIX}footer"
MSG_MAIN_LEGACY = f"{OVERLAY_MESSAGE_PREFIX}main"

ALL_OVERLAY_MESSAGE_IDS: tuple[str, ...] = (
    MSG_MAIN_LEGACY,
    MSG_HDR_BUILD,
    MSG_HDR_SYSTEM,
    MSG_COL_LABELS,
    MSG_COL_VALUES,
    MSG_FOOTER,
)


@dataclass(frozen=True)
class OverlayTextLayer:
    msg_id: str
    text: str
    color: str
    x: int
    y: int


def values_column_x(label_lines: List[str]) -> int:
    """Legacy-canvas X for the numeric column block (monospace estimate)."""
    if not label_lines:
        return OVERLAY_X
    width = max(len(line) for line in label_lines)
    return OVERLAY_X + int(width * CHAR_WIDTH_EST)
