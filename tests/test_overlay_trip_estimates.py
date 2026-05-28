"""Unit tests for overlay trip estimate helpers."""

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

_api_spec = importlib.util.spec_from_file_location(
    "ravencolonial_api_client_stub",
    _ROOT / "api" / "client.py",
)
# Minimal normalize only — load trip_estimates without full api client
_norm_spec = importlib.util.spec_from_file_location(
    "ravencolonial_normalize",
    _ROOT / "api" / "client.py",
)
# Instead stub normalize in sys.modules
_api_stub = types.ModuleType("api.client")
_api_stub.normalize_commodity_key = lambda name: (
    str(name).replace("$", "").replace("_name;", "").replace("_name", "").strip().lower()
)
_pkg = types.ModuleType("api")
_pkg.client = _api_stub
sys.modules["api"] = _pkg
sys.modules["api.client"] = _api_stub

_te_spec = importlib.util.spec_from_file_location(
    "ravencolonial_trip_estimates",
    _ROOT / "overlay" / "trip_estimates.py",
)
assert _te_spec and _te_spec.loader
_te = importlib.util.module_from_spec(_te_spec)
_te_spec.loader.exec_module(_te)

trips_for_units = _te.trips_for_units
total_fc_deficit = _te.total_fc_deficit
format_trip_footer_lines = _te.format_trip_footer_lines
fc_summary_label = _te.fc_summary_label


def test_trips_for_units_ceil() -> None:
    assert trips_for_units(0, 100) == 0
    assert trips_for_units(100, 0) is None
    assert trips_for_units(100, None) is None
    assert trips_for_units(269924, 1316) == 206
    assert trips_for_units(1316, 1316) == 1


def test_total_fc_deficit_respects_selection_cargo() -> None:
    needs = {"steel": 100, "grain": 50}
    fc_all = {"steel": 10, "grain": 40}
    assert total_fc_deficit(needs, fc_all) == 100
    fc_one = {"steel": 100, "grain": 0}
    assert total_fc_deficit(needs, fc_one) == 50


def test_format_trip_footer_lines() -> None:
    lines = format_trip_footer_lines(
        total_remaining=1000,
        ship_cargo_capacity=250,
        show_fc_line=True,
        fc_deficit_total=800,
        fc_summary_label="UAPF",
    )
    joined = "\n".join(lines)
    assert "1,000 remaining" in joined
    assert "4 trips in this ship" in joined
    assert "UAPF: 800 deficit" in joined
    assert "4 trips" in joined.split("deficit")[-1]


def test_fc_summary_label() -> None:
    linked = [{"marketId": 1, "label": "UAPF", "name": "uapf"}]
    assert fc_summary_label("all", linked) == "1 FC"
    assert fc_summary_label("1", linked) == "UAPF"
    assert fc_summary_label("all", linked * 2) == "2 FCs"
