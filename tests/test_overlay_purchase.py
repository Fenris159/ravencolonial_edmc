"""Simplified tracker purchase calculations and carrier selection."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

for name in ("timeout_session", "config"):
    if name not in sys.modules:
        module = types.ModuleType(name)
        if name == "config":
            module.appname = "test"
        sys.modules[name] = module

from overlay.build_project import BuildProjectOverlay
from overlay.format_mode import (
    OVERLAY_FORMAT_BREAKDOWN,
    OVERLAY_FORMAT_SIMPLIFIED,
    normalize_overlay_format,
    purchase_amounts,
)
from overlay.layers import (
    MSG_TABLE_FC_PREFIX,
    MSG_TABLE_NEED_PREFIX,
    MSG_TABLE_SHIP_PREFIX,
)
from overlay.popout import BuildProjectPopout
from overlay.project_cache import aggregate_project_cache


def _tracker_plugin(project: dict, **changes: object) -> SimpleNamespace:
    state = {
        "overlay_ui_enabled": True,
        "selected_overlay_build_id": project["buildId"],
        "overlay_project_cache": project,
        "overlay_format": OVERLAY_FORMAT_SIMPLIFIED,
        "overlay_carrier_tracking_enabled": True,
        "overlay_project_linked_fcs": project.get("linkedFC", []),
        "overlay_fc_cargo_by_market": {},
        "overlay_fc_selection": "all",
        "is_docked": False,
        "cargo": {},
        "ship_cargo_capacity": 100,
    }
    state.update(changes)
    return SimpleNamespace(**state)


def _purchase_cells(plugin: SimpleNamespace) -> tuple[list[str], object]:
    bundle = BuildProjectOverlay(plugin).compose_layers()
    cells = [layer.text for layer in bundle.text_layers if layer.msg_id.startswith(MSG_TABLE_NEED_PREFIX)]
    return cells, bundle


def test_overlay_format_defaults_to_breakdown() -> None:
    """Verify overlay format defaults to breakdown."""
    assert normalize_overlay_format(None) == OVERLAY_FORMAT_BREAKDOWN
    assert normalize_overlay_format("obsolete") == OVERLAY_FORMAT_BREAKDOWN
    assert normalize_overlay_format("Simplified") == OVERLAY_FORMAT_SIMPLIFIED


def test_simplified_uses_selected_carrier_and_one_purchase_column() -> None:
    """Verify simplified uses selected carrier and one purchase column."""
    project = {
        "buildId": "build-1",
        "buildName": "Port",
        "commodities": {"steel": 100},
        "linkedFC": [{"marketId": 123, "name": "FC-A"}, {"marketId": 456, "name": "FC-B"}],
    }
    plugin = _tracker_plugin(
        project,
        overlay_fc_selection="123",
        overlay_fc_cargo_by_market={123: {"steel": 30}, 456: {"steel": 70}},
        cargo={"steel": 20},
    )

    cells, bundle = _purchase_cells(plugin)

    assert cells == ["Purchase", "50"]
    assert not any(
        layer.msg_id.startswith((MSG_TABLE_SHIP_PREFIX, MSG_TABLE_FC_PREFIX))
        for layer in bundle.text_layers
    )
    assert bundle.vector_layers == []
    assert "Purchase" in BuildProjectPopout._discord_payload_from_bundle(bundle)


def test_track_all_subtracts_ship_and_all_carriers_once() -> None:
    """Verify track all subtracts ship and all carriers once."""
    project = aggregate_project_cache([
        {
            "buildId": "build-1",
            "commodities": {"steel": 100},
            "linkedFC": [{"marketId": 123, "name": "FC-A"}],
        },
        {
            "buildId": "build-2",
            "commodities": {"steel": 50},
            "linkedFC": [{"marketId": 123, "name": "FC-A"}, {"marketId": 456, "name": "FC-B"}],
        },
    ])
    plugin = _tracker_plugin(
        project,
        cargo={"steel": 20},
        overlay_fc_cargo_by_market={123: {"steel": 30}, 456: {"steel": 40}},
    )

    cells, _bundle = _purchase_cells(plugin)

    assert cells == ["Purchase", "60"]


def test_missing_selected_manifest_shows_sync_until_purchase_is_known() -> None:
    """Verify missing selected manifest shows sync until purchase is known."""
    project = {
        "buildId": "build-1",
        "buildName": "Port",
        "commodities": {"steel": 100},
        "linkedFC": [{"marketId": 123, "name": "FC-A"}],
    }
    plugin = _tracker_plugin(project, overlay_fc_selection="123", cargo={"steel": 20})

    cells, _bundle = _purchase_cells(plugin)

    assert cells == ["Purchase", "sync"]
    assert purchase_amounts(
        {"steel": 100}, {"steel": 100}, {}, carrier_known=False,
    ) == {"steel": 0}


def test_all_carriers_requires_every_linked_manifest() -> None:
    """Verify all carriers requires every linked manifest."""
    project = {
        "buildId": "build-1",
        "buildName": "Port",
        "commodities": {"steel": 100},
        "linkedFC": [{"marketId": 123, "name": "FC-A"}, {"marketId": 456, "name": "FC-B"}],
    }
    plugin = _tracker_plugin(project, overlay_fc_cargo_by_market={123: {"steel": 30}})

    cells, _bundle = _purchase_cells(plugin)

    assert cells == ["Purchase", "sync"]


def test_purchase_is_clamped_when_cargo_exceeds_need() -> None:
    """Verify purchase is clamped when cargo exceeds need."""
    assert purchase_amounts(
        {"steel": 100}, {"steel": 20}, {"steel": 90}, carrier_known=True,
    ) == {"steel": 0}


def test_simplified_without_carrier_tracking_uses_ship_cargo() -> None:
    """Verify simplified without carrier tracking uses ship cargo."""
    project = {"buildId": "build-1", "buildName": "Port", "commodities": {"steel": 100}}
    plugin = _tracker_plugin(project, overlay_carrier_tracking_enabled=False, cargo={"steel": 20})

    cells, _bundle = _purchase_cells(plugin)

    assert cells == ["Purchase", "80"]
