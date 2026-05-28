"""Unit tests for overlay text formatting (run: python3 tests/test_overlay_formatting.py)."""

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



_cat_spec = importlib.util.spec_from_file_location(
    "ravencolonial_overlay_commodity_categories",
    _ROOT / "overlay" / "commodity_categories.py",
)
assert _cat_spec and _cat_spec.loader
_cat = importlib.util.module_from_spec(_cat_spec)
_cat_spec.loader.exec_module(_cat)
sys.modules["commodity_categories"] = _cat

_te_spec = importlib.util.spec_from_file_location(
    "ravencolonial_trip_estimates",
    _ROOT / "overlay" / "trip_estimates.py",
)
assert _te_spec and _te_spec.loader
_te = importlib.util.module_from_spec(_te_spec)
_te_spec.loader.exec_module(_te)
sys.modules["trip_estimates"] = _te

_fc_spec = importlib.util.spec_from_file_location(
    "ravencolonial_overlay_fc_cargo",
    _ROOT / "overlay" / "fc_cargo.py",
)
_fc_mod = importlib.util.module_from_spec(_fc_spec)
assert _fc_spec and _fc_spec.loader
sys.modules["fc_cargo"] = _fc_mod
_fc_spec.loader.exec_module(_fc_mod)

_spec = importlib.util.spec_from_file_location(
    "ravencolonial_overlay_formatting",
    _ROOT / "overlay" / "formatting.py",
)
assert _spec and _spec.loader
_fmt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fmt)

build_overlay_text = _fmt.build_overlay_text
format_commodity_label = _fmt.format_commodity_label
resolve_project_needs = _fmt.resolve_project_needs
format_overlay_ship_cell = _fmt.format_overlay_ship_cell
resolve_assignments_for_needs = _fmt.resolve_assignments_for_needs
ASSIGN_SYMBOL_ME = _fmt.ASSIGN_SYMBOL_ME
ASSIGN_SYMBOL_OTHER = _fmt.ASSIGN_SYMBOL_OTHER


def test_format_commodity_label() -> None:
    assert format_commodity_label("steel") == "Steel"


def test_build_overlay_text_table() -> None:
    text = build_overlay_text(
        header="Orilnik (Starport)",
        needs={"steel": 100, "aluminium": 50},
        cargo={"steel": 20},
    )
    assert "Ship" in text
    assert "150 remaining" in text
    assert "trips in this ship" in text


def test_resolve_project_needs_prefers_depot() -> None:
    assert resolve_project_needs(
        {"commodities": {"steel": 999}}, depot_remaining={"steel": 10}
    ) == {"steel": 10}




def test_resolve_assignments_for_needs() -> None:
    project = {
        "commanders": {
            "Test Cmdr": ["steel"],
            "Other Pilot": ["aluminium"],
        }
    }
    needs = {"steel": 10, "aluminium": 5, "titanium": 1}
    got = resolve_assignments_for_needs(needs, project, "Test Cmdr")
    assert got["steel"] == "me"
    assert got["aluminium"] == "other"
    assert "titanium" not in got


def test_build_overlay_text_shows_assignment_column() -> None:
    text = build_overlay_text(
        header="Test Build",
        needs={"steel": 10, "aluminium": 5},
        cargo={},
        assignments={"steel": "me", "aluminium": "other"},
    )
    assert "Asg" in text
    assert ASSIGN_SYMBOL_ME in text
    assert ASSIGN_SYMBOL_OTHER in text
    assert "yours" in text


def test_build_overlay_text_fc_column() -> None:
    text = build_overlay_text(
        header="Test",
        needs={"steel": 100},
        cargo={"steel": 5},
        fc_deltas={"steel": -95},
        fc_column_title="UAPF",
    )
    assert "Ship" in text
    assert "UAPF" in text
    assert "-95" in text




category_for_commodity_key = _cat.category_for_commodity_key


def test_category_for_fdev_keys() -> None:
    assert category_for_commodity_key("liquidoxygen") == "Chemicals"
    assert category_for_commodity_key("steel") == "Metals"
    assert category_for_commodity_key("ceramic_composites") == "Industrial Materials"
    assert category_for_commodity_key("unknown_commodity") == "Other"


def test_build_overlay_text_groups_by_market_category() -> None:
    text = build_overlay_text(
        header="Port",
        needs={"steel": 10, "liquidoxygen": 20, "grain": 5},
        cargo={},
    )
    chem = text.index("Chemicals")
    food = text.index("Foods")
    metal = text.index("Metals")
    assert chem < food < metal
    assert "Liquidoxygen" in text



def test_build_overlay_text_trip_footer() -> None:
    text = build_overlay_text(
        header="Build",
        needs={"steel": 1000},
        cargo={},
        ship_cargo_capacity=250,
        show_fc_trip_summary=True,
        fc_deficit_total=400,
        fc_summary_label="UAPF",
    )
    assert "1,000 remaining" in text
    assert "4 trips in this ship" in text
    assert "UAPF: 400 deficit" in text

if __name__ == "__main__":
    test_format_commodity_label()
    test_build_overlay_text_table()
    test_resolve_project_needs_prefers_depot()
    test_resolve_assignments_for_needs()
    test_build_overlay_text_shows_assignment_column()
    test_build_overlay_text_fc_column()
    test_category_for_fdev_keys()
    test_build_overlay_text_groups_by_market_category()
    test_build_overlay_text_trip_footer()
    print("ok")

def test_format_overlay_ship_cell_hides_zero() -> None:
    assert format_overlay_ship_cell(0) == "     "
    assert format_overlay_ship_cell(40) == "   40"


def test_build_overlay_text_hides_zero_ship() -> None:
    text = build_overlay_text(
        header="Port",
        needs={"steel": 100},
        cargo={"steel": 0, "aluminium": 25},
    )
    assert "Steel" in text
    # steel row: need shown, ship blank (no "    0" adjacent pattern for steel ship col)
    lines = [ln for ln in text.splitlines() if "Steel" in ln and "100" in ln]
    assert len(lines) == 1
    assert "    0" not in lines[0].split("100")[1][:8]


def test_resolve_project_needs_depot_all_fulfilled_empty() -> None:
    """When depot says zero remaining, do not fall back to stale project commodities."""
    got = resolve_project_needs(
        {"commodities": {"steel": 500, "aluminium": 200}},
        depot_remaining={"steel": 0, "aluminium": 0},
        depot_authoritative=True,
    )
    assert got == {}


def test_resolve_project_needs_skips_zero_in_merge() -> None:
    assert resolve_project_needs(
        {"commodities": {"steel": 100, "titanium": 50}},
        depot_remaining={"steel": 10, "titanium": 0},
    ) == {"steel": 10}

