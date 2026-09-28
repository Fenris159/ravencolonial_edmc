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
    MSG_TABLE_LABEL_PREFIX,
    MSG_FOOTER,
    OVERLAY_X,
    estimate_value_text_width,
)
from overlay.popout import BuildProjectPopout
from overlay.project_cache import aggregate_project_cache
from overlay.render_layers import build_overlay_layers, _wrap_footer_lines
from overlay.text_metrics import text_cell_width


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


def test_simplified_hides_only_fully_stocked_categories() -> None:
    """Stocked categories disappear while mixed categories keep their complete context."""
    bundle = build_overlay_layers(
        header="Port", needs={"steel": 10, "fruitandvegetables": 20, "grain": 30}, cargo={},
        purchase_amounts={"steel": 0, "fruitandvegetables": 0, "grain": 5},
    )
    labels = [layer.text for layer in bundle.text_layers if layer.msg_id.startswith(MSG_TABLE_LABEL_PREFIX)]
    assert "Metals" not in labels
    assert "Steel" not in labels
    assert "Foods" in labels
    assert "Fruitandvegetables" in labels
    assert "Grain" in labels
    assert [layer.text for layer in bundle.text_layers if layer.msg_id.startswith(MSG_TABLE_NEED_PREFIX)] == [
        "Purchase", "0", "5",
    ]


def test_simplified_keeps_categories_with_unknown_cargo() -> None:
    """A pending manifest cannot make an unresolved category disappear."""
    bundle = build_overlay_layers(
        header="Port", needs={"steel": 10}, cargo={}, purchase_amounts={"steel": None},
    )
    assert any(layer.text == "Metals" for layer in bundle.text_layers)
    assert any(layer.text == "sync" for layer in bundle.text_layers)


def test_all_stocked_categories_collapse_to_purchase_status() -> None:
    """Having all cargo aboard does not imply that construction is complete."""
    bundle = build_overlay_layers(
        header="Port", needs={"steel": 10, "water": 20}, cargo={},
        purchase_amounts={"steel": 0, "water": 0},
    )
    assert [layer.text for layer in bundle.text_layers[:2]] == ["Port", "No purchases needed"]
    assert len({layer.msg_id for layer in bundle.text_layers}) == len(bundle.text_layers)
    assert bundle.rect_layers == []
    assert bundle.vector_layers == []


def test_compact_purchase_alignment_adapts_to_large_values() -> None:
    """The numeric column fits its widest header/value and retains one right edge."""
    bundle = build_overlay_layers(
        header="Port", needs={"steel": 123456789, "copper": 5}, cargo={},
        purchase_amounts={"steel": 123456789, "copper": 5},
    )
    values = [layer for layer in bundle.text_layers if layer.msg_id.startswith(MSG_TABLE_NEED_PREFIX)]
    right_edges = {layer.x + estimate_value_text_width(layer.text) for layer in values}
    assert len(right_edges) == 1
    assert max(right_edges) - OVERLAY_X < 160
    assert not any(layer.text.strip().startswith("-") for layer in bundle.text_layers)


def test_section_style_is_uniform_across_formats() -> None:
    """Both layouts use left-aligned accent headings and plain commodity rows."""
    for purchase in [None, {"steel": 10, "grain": 20}]:
        bundle = build_overlay_layers(
            header="Port", needs={"steel": 10, "grain": 20}, cargo={}, purchase_amounts=purchase,
        )
        headings = [layer for layer in bundle.text_layers if layer.text in {"Metals", "Foods"}]
        assert len(headings) == 2
        assert all(layer.x == OVERLAY_X and layer.weight == 600 for layer in headings)
        assert len({layer.color for layer in headings}) == 1
        assert not any(layer.text.strip().startswith("-") for layer in bundle.text_layers)


def test_footers_wrap_at_arrow_boundaries_in_both_formats() -> None:
    """Remaining quantities and trip estimates stay intact on their own lines."""
    for purchase in [None, {"steel": 9922}]:
        bundle = build_overlay_layers(
            header="Port", needs={"steel": 9922}, cargo={}, purchase_amounts=purchase,
        )
        footer = next(layer.text for layer in bundle.text_layers if layer.msg_id == MSG_FOOTER)
        assert footer.splitlines() == ["> 9,922 remaining", "> ? trips in this ship"]


def test_completed_checkbox_restores_stocked_and_delivered_rows_in_both_formats() -> None:
    """The full list includes zero remaining needs without inventing sync values."""
    project = {
        "buildId": "build-1", "buildName": "Port",
        "commodities": {"steel": 10, "grain": 0, "water": 5},
        "linkedFC": [{"marketId": 123, "name": "FC-A"}],
    }
    for mode in [OVERLAY_FORMAT_BREAKDOWN, OVERLAY_FORMAT_SIMPLIFIED]:
        plugin = _tracker_plugin(
            project, overlay_format=mode, overlay_fc_cargo_by_market={123: {"steel": 10}},
        )
        compact = BuildProjectOverlay(plugin).compose_layers()
        assert not any(layer.text in {"Steel", "Metals", "Foods", "Grain"} for layer in compact.text_layers)
        plugin.overlay_show_completed_commodities = True
        full = BuildProjectOverlay(plugin).compose_layers()
        assert all(any(layer.text == text for layer in full.text_layers)
                   for text in {"Steel", "Metals", "Foods", "Grain"})
        assert not any(layer.text == "sync" for layer in full.text_layers)
        assert max(layer.y for layer in full.text_layers) > max(layer.y for layer in compact.text_layers)


def test_breakdown_keeps_categories_until_all_carrier_manifests_are_known() -> None:
    """The category rule uses the same manifest completeness check as Purchase."""
    project = {
        "buildId": "build-1", "buildName": "Port", "commodities": {"steel": 10},
        "linkedFC": [{"marketId": 123, "name": "FC-A"}, {"marketId": 456, "name": "FC-B"}],
    }
    plugin = _tracker_plugin(
        project, overlay_format=OVERLAY_FORMAT_BREAKDOWN, overlay_fc_cargo_by_market={123: {"steel": 10}},
    )
    assert any(layer.text == "Metals" for layer in BuildProjectOverlay(plugin).compose_layers().text_layers)
    plugin.overlay_fc_cargo_by_market[456] = {}
    assert not any(layer.text == "Metals" for layer in BuildProjectOverlay(plugin).compose_layers().text_layers)


def test_ship_and_carrier_stock_jointly_hide_breakdown_category() -> None:
    """The ship is subtracted once alongside the selected carrier's cargo."""
    project = {
        "buildId": "build-1", "buildName": "Port", "commodities": {"steel": 10},
        "linkedFC": [{"marketId": 123, "name": "FC-A"}],
    }
    plugin = _tracker_plugin(
        project, overlay_format=OVERLAY_FORMAT_BREAKDOWN, cargo={"steel": 4},
        overlay_fc_cargo_by_market={123: {"steel": 6}},
    )
    layers = BuildProjectOverlay(plugin).compose_layers().text_layers
    assert any(layer.text == "No purchases needed" for layer in layers)


def test_long_footer_clauses_wrap_after_arrow_break() -> None:
    """Respect semantic breaks and wrap a long clause without splitting its words."""
    lines = _wrap_footer_lines(["> 100 remaining > many trips in this very large ship"], width=22)
    assert lines == ["> 100 remaining", "> many trips in this", "  very large ship"]


def test_wide_footer_wraps_using_display_width() -> None:
    """A short character count must not hide an overflowing localized footer."""
    lines = _wrap_footer_lines(["> 化学品 remaining > 2 trips"], width=22)
    assert lines == ["> 化学品 remaining", "> 2 trips"]
    assert all(text_cell_width(line) <= 22 for line in lines)
