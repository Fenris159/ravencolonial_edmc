"""Tests for overlay color themes."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_spec = importlib.util.spec_from_file_location(
    "ravencolonial_overlay_themes",
    _ROOT / "overlay" / "themes.py",
)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

DEFAULT_OVERLAY_THEME_ID = _mod.DEFAULT_OVERLAY_THEME_ID
get_overlay_theme = _mod.get_overlay_theme
overlay_theme_choices = _mod.overlay_theme_choices


def test_default_theme_is_elite_orange() -> None:
    assert DEFAULT_OVERLAY_THEME_ID == "elite_orange"
    theme = get_overlay_theme(None)
    assert theme.display_name == "Elite Orange"
    assert theme.header_primary.upper().startswith("#FF")


def test_six_themes_available() -> None:
    choices = overlay_theme_choices()
    assert len(choices) == 6
    ids = [c[0] for c in choices]
    assert "elite_orange" in ids
    assert "nebula_cyan" in ids
    assert "toxic_green" in ids
    assert "crimson_wake" in ids
    assert "void_amethyst" in ids
    assert "cerulean_gold" in ids


def test_cerulean_gold_uses_blue_white_yellow() -> None:
    theme = get_overlay_theme("cerulean_gold")
    assert theme.display_name == "Cerulean Gold"
    assert theme.header_primary.upper() == "#3D9EE8"
    assert theme.header_secondary.upper() == "#F2F7FC"
    assert theme.commodity.upper() == "#C8E4FA"
    assert theme.values.upper() == "#FFCC33"


def test_unknown_theme_falls_back_to_default() -> None:
    theme = get_overlay_theme("not_a_theme")
    assert theme.id == "elite_orange"
