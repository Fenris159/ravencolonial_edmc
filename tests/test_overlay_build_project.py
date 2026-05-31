"""Regression tests for BuildProjectOverlay runtime state helpers."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

for name in ("timeout_session", "config"):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        if name == "config":
            mod.appname = "test"
        sys.modules[name] = mod

from overlay.build_project import BuildProjectOverlay


class _FakeOverlayClient:
    def __init__(self) -> None:
        self.raw: list[dict] = []
        self.shapes: list[tuple] = []

    def send_raw(self, msg: dict) -> None:
        self.raw.append(dict(msg))

    def send_shape(
        self,
        shapeid: str,
        shape: str,
        color: str,
        fill: str,
        x: int,
        y: int,
        w: int,
        h: int,
        ttl: int,
    ) -> None:
        self.shapes.append((shapeid, shape, color, fill, x, y, w, h, ttl))


def test_depot_construction_complete_reads_live_journal_snapshot() -> None:
    plugin = SimpleNamespace(
        construction_depot_data={"ConstructionComplete": True},
    )

    assert BuildProjectOverlay(plugin)._depot_construction_complete() is True


def test_depot_construction_complete_defaults_false_without_snapshot() -> None:
    plugin = SimpleNamespace(construction_depot_data=None)

    assert BuildProjectOverlay(plugin)._depot_construction_complete() is False


def test_refresh_sends_text_shapes_and_vectors() -> None:
    plugin = SimpleNamespace(
        overlay_ui_enabled=True,
        selected_overlay_build_id="build-1",
        overlay_project_cache={
            "buildId": "build-1",
            "buildName": "Test Build",
            "commodities": {"steel": 100, "aluminium": 50},
        },
        construction_depot_data=None,
        overlay_carrier_tracking_enabled=False,
        overlay_decorative_shapes_enabled=True,
        overlay_always_on=True,
        is_docked=False,
        cargo={},
        ship_cargo_capacity=100,
        build_depot_project_fields=lambda refresh=False: None,
    )
    client = _FakeOverlayClient()

    with (
        patch("overlay.build_project.get_overlay_client", return_value=client),
        patch("overlay.build_project.register_build_tracker_group"),
    ):
        BuildProjectOverlay(plugin).refresh(force=True)

    assert any(msg.get("text") == "Test Build" for msg in client.raw)
    assert any(shape[1] == "rect" for shape in client.shapes)
    assert any(msg.get("shape") == "vect" for msg in client.raw)
    assert all(msg.get("ttl", 0) > 0 for msg in client.raw if msg.get("text"))
    assert all(shape[8] > 0 for shape in client.shapes)
    assert all(msg.get("ttl", 0) > 0 for msg in client.raw if msg.get("shape"))
