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
    assert "Remaining: 150 units" in text


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

if __name__ == "__main__":
    test_format_commodity_label()
    test_build_overlay_text_table()
    test_resolve_project_needs_prefers_depot()
    test_resolve_assignments_for_needs()
    test_build_overlay_text_shows_assignment_column()
    print("ok")
