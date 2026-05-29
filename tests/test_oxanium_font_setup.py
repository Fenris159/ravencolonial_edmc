"""Oxanium font bundling and Modern Overlay install helpers."""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY_DIR = ROOT / "overlay"
ASSETS = ROOT / "assets" / "fonts" / "oxanium"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_font_setup = _load_module("ravencolonial_font_setup", OVERLAY_DIR / "font_setup.py")
_font_weights = _load_module("ravencolonial_font_weights", OVERLAY_DIR / "font_weights.py")
_weight_patch = _load_module("ravencolonial_weight_patch", OVERLAY_DIR / "modern_overlay_weight_patch.py")

OXANIUM_VARIABLE_FILE = _font_setup.OXANIUM_VARIABLE_FILE
find_modern_overlay_plugin_dir = _font_setup.find_modern_overlay_plugin_dir
install_oxanium_to_modern_overlay = _font_setup.install_oxanium_to_modern_overlay
WEIGHT_BOLD = _font_weights.WEIGHT_BOLD
clamp_font_weight = _font_weights.clamp_font_weight
PATCH_MARKER = _weight_patch.PATCH_MARKER


def test_bundled_oxanium_assets_present() -> None:
    assert (ASSETS / OXANIUM_VARIABLE_FILE).is_file()
    assert (ASSETS / "OFL.txt").is_file()


def test_clamp_font_weight() -> None:
    assert clamp_font_weight(700) == WEIGHT_BOLD
    assert clamp_font_weight(999) == 400
    assert clamp_font_weight("bad") == 400


def test_install_oxanium_to_modern_overlay(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "RavenColonial_EDMC"
    plugin_dir.mkdir()
    assets_dest = plugin_dir / "assets" / "fonts" / "oxanium"
    assets_dest.mkdir(parents=True)
    shutil.copy2(ASSETS / OXANIUM_VARIABLE_FILE, assets_dest / OXANIUM_VARIABLE_FILE)
    shutil.copy2(ASSETS / "OFL.txt", assets_dest / "OFL.txt")

    mo = tmp_path / "EDMCModernOverlay"
    fonts_dir = mo / "overlay_client" / "fonts"
    fonts_dir.mkdir(parents=True)
    (mo / "EDMCOverlay").mkdir()
    edmc = mo / "EDMCOverlay" / "edmcoverlay.py"
    edmc.write_text(
        '        payload = {\n'
        '            "type": "message",\n'
        '            "id": item_id or "",\n'
        '            "text": str(text),\n'
        '            "color": _lookup("color", "Color") or "white",\n'
        '            "size": _lookup("size", "Size") or "normal",\n'
        '            "x": _legacy_coerce_int(_lookup("x", "X"), 0),\n'
        '            "y": _legacy_coerce_int(_lookup("y", "Y"), 0),\n'
        '            "ttl": ttl,\n'
        '        }\n'
        '        if plugin:\n'
        '            payload["plugin"] = plugin\n'
        '        return payload\n',
        encoding="utf-8",
    )
    render = mo / "overlay_client" / "render_surface.py"
    render.write_text(
        'size = str(item.get("size", "normal")).lower()\n'
        "        state = self._viewport_state()\n"
        "metrics_font.setWeight(QFont.Weight.Normal)\n"
        "metrics_font.setWeight(QFont.Weight.Normal)\n"
        "point_size=scaled_point_size,\n            x=x,\n",
        encoding="utf-8",
    )
    paint = mo / "overlay_client" / "paint_commands.py"
    paint.write_text(
        "    point_size: float = 12.0\n    x: int = 0\n"
        "        font.setWeight(QFont.Weight.Normal)\n        painter.setFont(font)\n",
        encoding="utf-8",
    )

    assert install_oxanium_to_modern_overlay(str(plugin_dir), force=True)
    assert (fonts_dir / OXANIUM_VARIABLE_FILE).is_file()
    preferred = (fonts_dir / "preferred_fonts.txt").read_text(encoding="utf-8")
    assert preferred.splitlines()[0].strip() == OXANIUM_VARIABLE_FILE
    assert PATCH_MARKER in edmc.read_text(encoding="utf-8")


def test_find_modern_overlay_monorepo_layout() -> None:
    if not (ROOT / "EDMCModernOverlay" / "overlay_client" / "fonts").is_dir():
        pytest.skip("EDMCModernOverlay not present in workspace")
    found = find_modern_overlay_plugin_dir(str(ROOT))
    assert found is not None
    assert found.name == "EDMCModernOverlay"
