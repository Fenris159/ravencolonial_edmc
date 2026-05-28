"""Unit tests for overlay FC cargo helpers (run: python3 tests/test_overlay_fc_cargo.py)."""

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
    "ravencolonial_overlay_fc_cargo",
    _ROOT / "overlay" / "fc_cargo.py",
)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

parse_project_linked_fcs = _mod.parse_project_linked_fcs
compute_fc_deltas = _mod.compute_fc_deltas
resolve_fc_cargo_for_selection = _mod.resolve_fc_cargo_for_selection
OVERLAY_FC_ALL = _mod.OVERLAY_FC_ALL


def test_parse_project_linked_fcs() -> None:
    project = {
        "linkedFC": [
            {"marketId": 100, "name": "abcd-n0xw", "displayName": "My FC"},
            {"marketId": 200, "name": "wxyz-a1b2"},
        ]
    }
    fcs = parse_project_linked_fcs(project)
    assert len(fcs) == 2
    assert fcs[0]["label"] == "ABCD-N0XW" or fcs[0]["label"] == "ABCD-N0XW".upper()


def test_compute_fc_deltas() -> None:
    assert compute_fc_deltas({"steel": 100}, {"steel": 40})["steel"] == -60
    assert compute_fc_deltas({"steel": 100}, {"steel": 150})["steel"] == 50


def test_resolve_fc_cargo_all_vs_one() -> None:
    linked = [
        {"marketId": 1, "label": "FC-A"},
        {"marketId": 2, "label": "FC-B"},
    ]
    cargo_by = {1: {"steel": 10}, 2: {"steel": 30}}
    all_cargo, title = resolve_fc_cargo_for_selection(
        linked_fcs=linked, cargo_by_market=cargo_by, selection=OVERLAY_FC_ALL
    )
    assert title == "FC's"
    assert all_cargo["steel"] == 40
    one, title_b = resolve_fc_cargo_for_selection(
        linked_fcs=linked, cargo_by_market=cargo_by, selection="2"
    )
    assert title_b == "FC-B"
    assert one["steel"] == 30


if __name__ == "__main__":
    test_parse_project_linked_fcs()
    test_compute_fc_deltas()
    test_resolve_fc_cargo_all_vs_one()
    print("ok")
