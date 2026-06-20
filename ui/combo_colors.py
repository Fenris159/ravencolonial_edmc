"""
Contrast helpers for :class:`ui.themed_combobox.ThemedCombobox`.

EDMC's ``theme.update`` on Linux with the default (light) theme often sets the same
panel color for ``background`` and ``foreground``. Popup listboxes must not call
``theme.update``; closed entries need a readable foreground after theming.
"""

from __future__ import annotations

from typing import Optional, Tuple

# Minimum per-channel delta to treat fg/bg as distinct (Tk named colors may not parse).
_MIN_CHANNEL_DELTA = 24


def hex_to_rgb(color: str) -> Optional[Tuple[int, int, int]]:
    """Parse ``#rrggbb`` (6 hex digits). Returns ``None`` if not a hex color."""
    s = str(color).strip()
    if not s.startswith("#"):
        return None
    h = s[1:]
    if len(h) != 6:
        return None
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return None


def colors_too_similar(background: str, foreground: str) -> bool:
    """True when fg/bg are equal or too close to read (hex colors only)."""
    bg_n = str(background).strip().lower()
    fg_n = str(foreground).strip().lower()
    if bg_n == fg_n:
        return True
    brgb = hex_to_rgb(bg_n)
    frgb = hex_to_rgb(fg_n)
    if brgb is None or frgb is None:
        return False
    return (
        abs(brgb[0] - frgb[0]) < _MIN_CHANNEL_DELTA
        and abs(brgb[1] - frgb[1]) < _MIN_CHANNEL_DELTA
        and abs(brgb[2] - frgb[2]) < _MIN_CHANNEL_DELTA
    )


def edmc_theme_fg_bg() -> Optional[Tuple[str, str]]:
    """``(background, foreground)`` from EDMC's active theme, if loaded."""
    try:
        from theme import theme  # type: ignore[import-untyped]

        current = getattr(theme, "current", None)
        if current:
            bg = str(current.get("background", "")).strip()
            fg = str(current.get("foreground", "")).strip()
            if bg and fg:
                return bg, fg
    except ImportError:
        pass
    return None


def fallback_background(*, dark: bool) -> str:
    return "#1e1e1e" if dark else "#ffffff"


def fallback_foreground(*, dark: bool) -> str:
    return "orange" if dark else "black"


def ensure_readable_foreground(
    background: str,
    foreground: str,
    *,
    dark: bool,
) -> str:
    """Return ``foreground`` when it contrasts with ``background``; else a safe fallback."""
    if not colors_too_similar(background, foreground):
        return foreground
    palette = edmc_theme_fg_bg()
    if palette:
        _pal_bg, pal_fg = palette
        if not colors_too_similar(background, pal_fg):
            return pal_fg
    return fallback_foreground(dark=dark)


def preferred_entry_colors(
    panel_background: str,
    *,
    dark: bool,
) -> tuple[str, str]:
    """
    Initial ``(background, foreground)`` for combobox entry/button before ``theme.update``.

    Light/default EDMC theme: use the standard white entry surface and prefer
    ``theme.current`` foreground when it contrasts with it. Dark themes: orange
    on panel grey (GalaxyGPS convention).
    """
    if dark:
        bg = panel_background
        return bg, fallback_foreground(dark=True)
    bg = fallback_background(dark=False)
    palette = edmc_theme_fg_bg()
    if palette:
        _pal_bg, pal_fg = palette
        fg = ensure_readable_foreground(bg, pal_fg, dark=False)
        return bg, fg
    return bg, fallback_foreground(dark=False)


def highlight_color_for_background(bg: str) -> str:
    """Selection/hover fill for listbox rows derived from ``bg``."""
    try:
        if str(bg).startswith("#") and len(str(bg)) >= 7:
            r = int(bg[1:3], 16)
            g = int(bg[3:5], 16)
            b = int(bg[5:7], 16)
            if r + g + b < 384:
                r = min(255, r + 30)
                g = min(255, g + 30)
                b = min(255, b + 30)
            else:
                r = max(0, r - 30)
                g = max(0, g - 30)
                b = max(0, b - 30)
            return f"#{r:02x}{g:02x}{b:02x}"
    except (ValueError, TypeError):
        pass
    return "#3d3d3d" if str(bg).strip().lower() == "#1e1e1e" else "#e0e0e0"
