"""Contrast helpers for ThemedCombobox (default vs dark EDMC theme)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_spec = importlib.util.spec_from_file_location(
    "ravencolonial_combo_colors",
    _ROOT / "ui" / "combo_colors.py",
)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

colors_too_similar = _mod.colors_too_similar
ensure_readable_foreground = _mod.ensure_readable_foreground
fallback_foreground = _mod.fallback_foreground
preferred_entry_colors = _mod.preferred_entry_colors
hex_to_rgb = _mod.hex_to_rgb
highlight_color_for_background = _mod.highlight_color_for_background


def test_hex_to_rgb() -> None:
    assert hex_to_rgb("#ffffff") == (255, 255, 255)
    assert hex_to_rgb("#000000") == (0, 0, 0)
    assert hex_to_rgb("white") is None


def test_colors_too_similar_identical_hex() -> None:
    assert colors_too_similar("#c0c0c0", "#c0c0c0") is True
    assert colors_too_similar("#ffffff", "#000000") is False


def test_ensure_readable_foreground_light_panel() -> None:
    # Linux default-theme failure mode: same grey for fg and bg after theme.update.
    fixed = ensure_readable_foreground("#c0c0c0", "#c0c0c0", dark=False)
    assert fixed == fallback_foreground(dark=False)
    assert not colors_too_similar("#c0c0c0", fixed)


def test_ensure_readable_foreground_keeps_orange_on_dark() -> None:
    fg = ensure_readable_foreground("#1e1e1e", "orange", dark=True)
    assert fg == "orange"


def test_preferred_entry_colors_light() -> None:
    bg, fg = preferred_entry_colors("#d9d9d9", dark=False)
    assert bg == "#ffffff"
    assert not colors_too_similar(bg, fg)


def test_preferred_entry_colors_dark() -> None:
    _bg, fg = preferred_entry_colors("grey4", dark=True)
    assert fg == "orange"


def test_highlight_color_for_background() -> None:
    light_hi = highlight_color_for_background("#ffffff")
    dark_hi = highlight_color_for_background("#1e1e1e")
    assert light_hi.startswith("#")
    assert dark_hi.startswith("#")
    assert light_hi != dark_hi
