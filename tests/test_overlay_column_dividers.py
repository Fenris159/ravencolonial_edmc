"""Tests for vertical column divider vectors on the commodity overlay."""

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
value_column_divider_x_positions = _overlay.layers.value_column_divider_x_positions
MSG_TABLE_FC_PREFIX = _overlay.layers.MSG_TABLE_FC_PREFIX
_contiguous = _overlay.render_layers._contiguous_line_index_runs


def test_one_divider_without_fc_column() -> None:
    bundle = build_overlay_layers(
        header="Port",
        needs={"steel": 10, "aluminium": 20},
        cargo={},
    )
    assert len(bundle.vector_layers) == 1
    assert bundle.vector_layers[0].y1 < bundle.vector_layers[0].y2


def test_two_dividers_with_fc_column() -> None:
    bundle = build_overlay_layers(
        header="Port",
        needs={"steel": 10, "aluminium": 20, "copper": 30},
        cargo={},
        fc_deltas={"steel": 0, "aluminium": 0, "copper": 0},
    )
    xs = {v.x for v in bundle.vector_layers}
    assert len(xs) == 2
    assert len(bundle.vector_layers) == 2


def test_dividers_split_at_category_gap() -> None:
    bundle = build_overlay_layers(
        header="Port",
        needs={"steel": 10, "water": 20},
        cargo={},
    )
    # Metals + Foods => two categories => two contiguous runs => 2 segments for 1 divider
    assert len(bundle.vector_layers) == 2
    assert bundle.vector_layers[0].y2 <= bundle.vector_layers[1].y1


def test_divider_x_positions() -> None:
    positions = value_column_divider_x_positions(200, include_fc_column=True)
    assert len(positions) == 2
    assert positions[0] < positions[1]


def test_fc_callsign_header_gets_own_aligned_layer() -> None:
    bundle = build_overlay_layers(
        header="Port",
        needs={"steel": 2542},
        cargo={},
        fc_deltas={"steel": 3028},
        fc_column_title="G6H-47G",
    )
    fc_layers = [layer for layer in bundle.text_layers if layer.msg_id.startswith(MSG_TABLE_FC_PREFIX)]
    assert fc_layers[0].text == "G6H-47G"
    assert fc_layers[1].text == "+3028"
    assert fc_layers[0].x < fc_layers[1].x


def test_contiguous_runs() -> None:
    assert _contiguous([3, 4, 7, 8, 9]) == [(3, 4), (7, 9)]
