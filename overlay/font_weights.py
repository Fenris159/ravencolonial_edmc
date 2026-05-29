"""Oxanium font weight constants (CSS-style 100–900) for overlay text layers."""

from __future__ import annotations

# Google Fonts Oxanium variable axis: 200–800
WEIGHT_EXTRA_LIGHT = 200
WEIGHT_LIGHT = 300
WEIGHT_REGULAR = 400
WEIGHT_MEDIUM = 500
WEIGHT_SEMIBOLD = 600
WEIGHT_BOLD = 700
WEIGHT_EXTRA_BOLD = 800

# HUD role defaults
WEIGHT_HEADER_PRIMARY = WEIGHT_BOLD
WEIGHT_HEADER_SECONDARY = WEIGHT_MEDIUM
WEIGHT_COLUMN_HEADER = WEIGHT_SEMIBOLD
WEIGHT_BODY = WEIGHT_REGULAR
WEIGHT_EMPHASIS = WEIGHT_SEMIBOLD
WEIGHT_FOOTER = WEIGHT_LIGHT

VALID_WEIGHTS = frozenset(range(100, 901, 100)) | frozenset(
    (WEIGHT_EXTRA_LIGHT, WEIGHT_LIGHT, WEIGHT_REGULAR, WEIGHT_MEDIUM, WEIGHT_SEMIBOLD, WEIGHT_BOLD, WEIGHT_EXTRA_BOLD)
)


def clamp_font_weight(weight: int, *, default: int = WEIGHT_REGULAR) -> int:
    try:
        value = int(weight)
    except (TypeError, ValueError):
        return default
    if value < 100 or value > 900:
        return default
    return value
