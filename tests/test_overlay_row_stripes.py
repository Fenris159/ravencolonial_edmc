"""Tests for alternating commodity row background stripes."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

for name in ("timeout_session", "config"):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        if name == "config":
            mod.appname = "test"
        sys.modules[name] = mod


def _load_overlay_package() -> types.ModuleType:
    overlay_pkg = types.ModuleType("overlay")
    overlay_pkg.__path__ = [str(_ROOT / "overlay")]  # type: ignore[attr-defined]
    sys.modules["overlay"] = overlay_pkg

    bridge_spec = importlib.util.spec_from_file_location(
        "overlay.bridge",
        _ROOT / "overlay" / "bridge.py",
    )
    assert bridge_spec and bridge_spec.loader
    bridge_mod = importlib.util.module_from_spec(bridge_spec)
    sys.modules["overlay.bridge"] = bridge_mod
    bridge_spec.loader.exec_module(bridge_mod)
    overlay_pkg.bridge = bridge_mod  # type: ignore[attr-defined]

    for rel in (
        "layers",
        "themes",
        "commodity_categories",
        "fc_cargo",
        "trip_estimates",
        "formatting",
    ):
        spec = importlib.util.spec_from_file_location(
            f"overlay.{rel}",
            _ROOT / "overlay" / f"{rel}.py",
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"overlay.{rel}"] = mod
        spec.loader.exec_module(mod)
        setattr(overlay_pkg, rel, mod)

    api_pkg = types.ModuleType("api")
    sys.modules["api"] = api_pkg
    api_spec = importlib.util.spec_from_file_location(
        "api.client",
        _ROOT / "api" / "client.py",
    )
    assert api_spec and api_spec.loader
    api_mod = importlib.util.module_from_spec(api_spec)
    sys.modules["api.client"] = api_mod
    api_spec.loader.exec_module(api_mod)
    api_pkg.client = api_mod  # type: ignore[attr-defined]

    render_spec = importlib.util.spec_from_file_location(
        "overlay.render_layers",
        _ROOT / "overlay" / "render_layers.py",
    )
    assert render_spec and render_spec.loader
    render_mod = importlib.util.module_from_spec(render_spec)
    sys.modules["overlay.render_layers"] = render_mod
    render_spec.loader.exec_module(render_mod)
    overlay_pkg.render_layers = render_mod  # type: ignore[attr-defined]
    return overlay_pkg


_overlay = _load_overlay_package()
build_overlay_layers = _overlay.render_layers.build_overlay_layers
ROW_STRIPE_FILL = _overlay.layers.ROW_STRIPE_FILL
ROW_STRIPE_HEIGHT = _overlay.layers.ROW_STRIPE_HEIGHT
MSG_ROW_STRIPE_PREFIX = _overlay.layers.MSG_ROW_STRIPE_PREFIX


def test_alternating_commodity_row_stripes() -> None:
    """Verify alternating commodity row stripes."""
    bundle = build_overlay_layers(
        header="Test Port",
        needs={"steel": 10, "aluminium": 20, "copper": 30},
        cargo={},
    )
    assert len(bundle.text_layers) >= 2
    stripes = [rect for rect in bundle.rect_layers if rect.msg_id.startswith(MSG_ROW_STRIPE_PREFIX)]
    assert len(stripes) == 1
    assert stripes[0].fill == ROW_STRIPE_FILL
    assert stripes[0].h == ROW_STRIPE_HEIGHT


def test_zero_need_row_omitted() -> None:
    """Verify zero need row omitted."""
    bundle = build_overlay_layers(
        header="Port",
        needs={"steel": 10, "aluminium": 0},
        cargo={},
    )
    labels = "\n".join(layer.text for layer in bundle.text_layers)
    assert "Steel" in labels
    assert "Aluminium" not in labels


def test_zero_ship_cell_blank_in_values() -> None:
    """Verify zero ship cell blank in values."""
    bundle = build_overlay_layers(
        header="Port",
        needs={"steel": 10},
        cargo={"steel": 0},
    )
    values = [layer.text.strip() for layer in bundle.text_layers]
    assert "10" in values
    assert "0" not in values


def test_no_stripes_when_table_empty() -> None:
    """Verify no stripes when table empty."""
    bundle = build_overlay_layers(header="X", needs={}, cargo={})
    assert bundle.rect_layers == []
