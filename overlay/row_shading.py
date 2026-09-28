"""Shared preference and color conversion for alternating commodity row highlights."""

from __future__ import annotations

try:
    from ..exc_utils import CONFIG_READ_ERRORS
except ImportError:  # pragma: no cover - standalone tests
    from exc_utils import CONFIG_READ_ERRORS

ROW_HIGHLIGHT_OPACITY_KEY = "ravencolonial_overlay_row_highlight_opacity"
DEFAULT_ROW_HIGHLIGHT_OPACITY = 8


def normalize_row_highlight_opacity(value: object) -> int:
    """Convert a slider or stored value to a whole percentage in the supported range."""
    try:
        return max(0, min(100, round(float(value))))
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_ROW_HIGHLIGHT_OPACITY


def read_row_highlight_opacity(fallback: object = DEFAULT_ROW_HIGHLIGHT_OPACITY) -> int:
    """Read the saved percentage while retaining the current default for existing users."""
    try:
        from config import config

        value = config.get_int(ROW_HIGHLIGHT_OPACITY_KEY, default=DEFAULT_ROW_HIGHLIGHT_OPACITY)
    except CONFIG_READ_ERRORS:
        value = fallback
    return normalize_row_highlight_opacity(value)


def row_highlight_fill(opacity: object) -> str:
    """Return Modern Overlay's ARGB gray fill, also blended by the Tk popout."""
    alpha = round(normalize_row_highlight_opacity(opacity) * 255 / 100)
    return f"#{alpha:02X}4B4F54"
