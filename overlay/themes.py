"""Color themes for the build-project overlay (multi-layer HUD text)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

DEFAULT_OVERLAY_THEME_ID = "elite_orange"


@dataclass(frozen=True)
class OverlayTheme:
    """Colors for each overlay text role (hex ``#RRGGBB``)."""

    id: str
    display_name: str
    header_primary: str  # build name, trip footer
    header_secondary: str  # system / location line
    commodity: str  # commodity names, category rules, left column headers
    values: str  # Need / Ship / FC numbers and column headers


OVERLAY_THEMES: Dict[str, OverlayTheme] = {
    "elite_orange": OverlayTheme(
        id="elite_orange",
        display_name="Elite Orange",
        header_primary="#FF8C00",
        header_secondary="#FFD27F",
        commodity="#E8E8E8",
        values="#9CD3FF",
    ),
    "nebula_cyan": OverlayTheme(
        id="nebula_cyan",
        display_name="Nebula Cyan",
        header_primary="#5EC8F2",
        header_secondary="#B8E8FF",
        commodity="#D6EEF9",
        values="#FFE8A3",
    ),
    "toxic_green": OverlayTheme(
        id="toxic_green",
        display_name="Toxic Green",
        header_primary="#5CFF9E",
        header_secondary="#A8FFCC",
        commodity="#D8FFE8",
        values="#FFF066",
    ),
    "crimson_wake": OverlayTheme(
        id="crimson_wake",
        display_name="Crimson Wake",
        header_primary="#FF6B6B",
        header_secondary="#FFB8B8",
        commodity="#FFE4E4",
        values="#FFD966",
    ),
    "void_amethyst": OverlayTheme(
        id="void_amethyst",
        display_name="Void Amethyst",
        header_primary="#C9A0FF",
        header_secondary="#E2CCFF",
        commodity="#E8E0F5",
        values="#7FFFD4",
    ),
}

OVERLAY_THEME_ORDER: List[str] = [
    "elite_orange",
    "nebula_cyan",
    "toxic_green",
    "crimson_wake",
    "void_amethyst",
]


def overlay_theme_choices() -> List[tuple[str, str]]:
    """``(config_id, display label)`` pairs for settings UI."""
    return [(tid, OVERLAY_THEMES[tid].display_name) for tid in OVERLAY_THEME_ORDER]


def get_overlay_theme(theme_id: Optional[str]) -> OverlayTheme:
    key = (theme_id or "").strip() or DEFAULT_OVERLAY_THEME_ID
    return OVERLAY_THEMES.get(key, OVERLAY_THEMES[DEFAULT_OVERLAY_THEME_ID])
