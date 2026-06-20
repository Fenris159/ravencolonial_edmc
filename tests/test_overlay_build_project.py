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

from overlay.build_project import BuildProjectOverlay, aggregate_project_cache
from overlay.popout import BuildProjectPopout


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


def test_aggregate_project_cache_sums_commodities_and_fcs() -> None:
    aggregate = aggregate_project_cache(
        [
            {
                "buildId": "build-1",
                "systemName": "Alpha",
                "commodities": {"steel": 100, "aluminium": 50},
                "linkedFC": [{"marketId": 1, "name": "fc-a"}],
            },
            {
                "buildId": "build-2",
                "systemName": "Beta",
                "commodities": {"steel": 25, "titanium": 5},
                "linkedFC": [
                    {"marketId": 1, "name": "fc-a"},
                    {"marketId": 2, "name": "fc-b"},
                ],
            },
        ]
    )

    assert aggregate["buildId"] == "__OVERLAY_TRACK_ALL__"
    assert aggregate["buildName"] == "Track All"
    assert aggregate["commodities"] == {"steel": 125, "aluminium": 50, "titanium": 5}
    assert len(aggregate["linkedFC"]) == 2


def test_aggregate_project_cache_skips_completed_projects() -> None:
    aggregate = aggregate_project_cache(
        [
            {
                "buildId": "build-1",
                "buildName": "Done",
                "complete": True,
                "commodities": {"steel": 999},
                "linkedFC": [{"marketId": 1, "name": "fc-done"}],
            },
            {
                "buildId": "build-2",
                "buildName": "Active",
                "commodities": {"steel": 25},
                "linkedFC": [{"marketId": 2, "name": "fc-active"}],
            },
        ]
    )

    assert aggregate["buildType"] == "1 builds"
    assert aggregate["commodities"] == {"steel": 25}
    assert [fc["marketId"] for fc in aggregate["linkedFC"]] == [2]


def test_track_all_refresh_renders_aggregate_without_live_depot_override() -> None:
    plugin = SimpleNamespace(
        overlay_ui_enabled=True,
        selected_overlay_build_id="__OVERLAY_TRACK_ALL__",
        overlay_project_cache=aggregate_project_cache(
            [
                {
                    "buildId": "build-1",
                    "buildName": "A",
                    "commodities": {"steel": 100},
                },
                {
                    "buildId": "build-2",
                    "buildName": "B",
                    "commodities": {"steel": 50},
                },
            ]
        ),
        construction_depot_data=None,
        overlay_carrier_tracking_enabled=False,
        overlay_decorative_shapes_enabled=False,
        overlay_always_on=True,
        is_docked=True,
        current_market_id=123,
        cargo={},
        ship_cargo_capacity=None,
        build_depot_project_fields=lambda refresh=False: {"remaining_need": {"steel": 1}},
    )
    client = _FakeOverlayClient()

    with (
        patch("overlay.build_project.get_overlay_client", return_value=client),
        patch("overlay.build_project.register_build_tracker_group"),
    ):
        BuildProjectOverlay(plugin).refresh(force=True)

    text = "\n".join(str(msg.get("text", "")) for msg in client.raw)
    assert "Track All (2 builds)" in text
    assert "150" in text
    assert "> 150 remaining" in text


def test_track_all_ignores_live_depot_completion_snapshot() -> None:
    plugin = SimpleNamespace(
        overlay_ui_enabled=True,
        selected_overlay_build_id="__OVERLAY_TRACK_ALL__",
        overlay_project_cache=aggregate_project_cache(
            [
                {
                    "buildId": "build-1",
                    "buildName": "A",
                    "commodities": {"steel": 100},
                },
            ]
        ),
        construction_depot_data={"ConstructionComplete": True},
        overlay_carrier_tracking_enabled=False,
        overlay_decorative_shapes_enabled=False,
        overlay_always_on=True,
        is_docked=True,
        current_market_id=123,
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

    text = "\n".join(str(msg.get("text", "")) for msg in client.raw)
    assert "Construction complete" not in text
    assert "> 100 remaining" in text


def test_remember_all_projects_rebuilds_after_one_project_updates() -> None:
    plugin = SimpleNamespace(
        overlay_project_cache_by_build_id={
            "build-1": {"buildId": "build-1", "commodities": {"steel": 100}},
            "build-2": {"buildId": "build-2", "commodities": {"steel": 50}},
        },
        overlay_fc_cargo_by_market={},
    )
    overlay = BuildProjectOverlay(plugin)

    plugin.overlay_project_cache_by_build_id["build-1"] = {
        "buildId": "build-1",
        "commodities": {"steel": 25},
    }
    overlay.remember_all_projects(list(plugin.overlay_project_cache_by_build_id.values()))

    assert plugin.overlay_project_cache["buildId"] == "__OVERLAY_TRACK_ALL__"
    assert plugin.overlay_project_cache["commodities"] == {"steel": 75}


def test_specific_fc_selection_renders_owner_capacity_line() -> None:
    fc_handler = SimpleNamespace(
        get_owner_capacity=lambda market_id: {
            "freeSpace": 10000,
            "callsign": "N4W-T0Z",
        }
        if int(market_id) == 123
        else None
    )
    plugin = SimpleNamespace(
        overlay_ui_enabled=True,
        selected_overlay_build_id="build-1",
        overlay_project_cache={
            "buildId": "build-1",
            "buildName": "Damper Gateway",
            "systemName": "Synuefai CX-V C18-6",
            "commodities": {"ceramiccomposites": 98},
            "linkedFC": [{"marketId": 123, "name": "N4W-T0Z"}],
        },
        construction_depot_data=None,
        overlay_carrier_tracking_enabled=True,
        overlay_project_linked_fcs=[{"marketId": 123, "label": "N4W-T0Z"}],
        overlay_fc_cargo_by_market={123: {"ceramiccomposites": 653}},
        overlay_fc_selection="123",
        overlay_decorative_shapes_enabled=False,
        overlay_always_on=True,
        is_docked=False,
        cargo={},
        ship_cargo_capacity=100,
        fc_handler=fc_handler,
        build_depot_project_fields=lambda refresh=False: None,
    )

    bundle = BuildProjectOverlay(plugin)._compose_layers()
    text = "\n".join(layer.text for layer in bundle.text_layers)

    assert "+555" in text
    assert ">N4W-T0Z Capacity: 555/10,000" in text


def test_specific_fc_selection_missing_manifest_renders_sync() -> None:
    plugin = SimpleNamespace(
        overlay_ui_enabled=True,
        selected_overlay_build_id="build-1",
        overlay_project_cache={
            "buildId": "build-1",
            "buildName": "Geller Gateway",
            "systemName": "HIP 53931",
            "commodities": {"steel": 761},
            "linkedFC": [{"marketId": 123, "name": "G6H-47G"}],
        },
        construction_depot_data=None,
        overlay_carrier_tracking_enabled=True,
        overlay_project_linked_fcs=[{"marketId": 123, "label": "G6H-47G"}],
        overlay_fc_cargo_by_market={},
        overlay_fc_selection="123",
        overlay_decorative_shapes_enabled=False,
        overlay_always_on=True,
        is_docked=False,
        cargo={},
        ship_cargo_capacity=100,
        fc_handler=SimpleNamespace(get_owner_capacity=lambda market_id: None),
        build_depot_project_fields=lambda refresh=False: None,
    )

    bundle = BuildProjectOverlay(plugin)._compose_layers()
    text = "\n".join(layer.text for layer in bundle.text_layers)

    assert "sync" in text
    assert "-761" not in text


def test_track_all_fc_selection_does_not_render_owner_capacity_line() -> None:
    fc_handler = SimpleNamespace(
        get_owner_capacity=lambda market_id: {
            "freeSpace": 10000,
            "callsign": "N4W-T0Z",
        }
    )
    plugin = SimpleNamespace(
        overlay_ui_enabled=True,
        selected_overlay_build_id="build-1",
        overlay_project_cache={
            "buildId": "build-1",
            "buildName": "Damper Gateway",
            "systemName": "Synuefai CX-V C18-6",
            "commodities": {"ceramiccomposites": 98},
            "linkedFC": [{"marketId": 123, "name": "N4W-T0Z"}],
        },
        construction_depot_data=None,
        overlay_carrier_tracking_enabled=True,
        overlay_project_linked_fcs=[{"marketId": 123, "label": "N4W-T0Z"}],
        overlay_fc_cargo_by_market={123: {"ceramiccomposites": 653}},
        overlay_fc_selection="all",
        overlay_decorative_shapes_enabled=False,
        overlay_always_on=True,
        is_docked=False,
        cargo={},
        ship_cargo_capacity=100,
        fc_handler=fc_handler,
        build_depot_project_fields=lambda refresh=False: None,
    )

    bundle = BuildProjectOverlay(plugin)._compose_layers()
    text = "\n".join(layer.text for layer in bundle.text_layers)

    assert "+555" in text
    assert "Capacity:" not in text


def test_popout_discord_copy_omits_ship_and_jump_timer_lines() -> None:
    plugin = SimpleNamespace(
        overlay_ui_enabled=True,
        selected_overlay_build_id="build-1",
        overlay_project_cache={
            "buildId": "build-1",
            "buildName": "Discord Test",
            "systemName": "HIP 53931",
            "commodities": {"steel": 100, "aluminium": 50},
            "linkedFC": [{"marketId": 123, "name": "G6H-47G"}],
        },
        construction_depot_data=None,
        overlay_carrier_tracking_enabled=True,
        overlay_project_linked_fcs=[{"marketId": 123, "label": "G6H-47G"}],
        overlay_fc_cargo_by_market={123: {"steel": 40}},
        overlay_fc_selection="123",
        overlay_decorative_shapes_enabled=False,
        overlay_always_on=True,
        is_docked=False,
        cargo={"steel": 5},
        ship_cargo_capacity=100,
        fc_handler=SimpleNamespace(
            get_owner_capacity=lambda market_id: None,
            overlay_jump_footer_lines=lambda prefer_market_id=None: ["Carrier jumps in 12:34", "HIP 123"],
        ),
        build_depot_project_fields=lambda refresh=False: None,
    )

    bundle = BuildProjectOverlay(plugin)._compose_layers()
    payload = BuildProjectPopout._discord_payload_from_bundle(bundle)

    assert payload.startswith("```\n")
    assert payload.endswith("\n```")
    assert "Discord Test" in payload
    assert "Need" in payload
    assert "G6H-47G" in payload
    assert "Ship" not in payload
    assert "trips in this ship" not in payload
    assert "deficit" in payload
    assert "deficit >" not in payload
    assert "? trips" not in payload
    assert "Carrier jumps" not in payload


def test_popout_uses_fixed_dark_theme_colors() -> None:
    class _Widget:
        def winfo_rgb(self, color: str) -> tuple[int, int, int]:
            value = color.lstrip("#")
            return tuple(int(value[i : i + 2], 16) * 257 for i in (0, 2, 4))

    assert BuildProjectPopout._theme_colors(_Widget()) == ("#000000", "#ff8000")
    assert BuildProjectPopout._accent_color(_Widget(), fallback="#ffffff") == "#ff8000"
