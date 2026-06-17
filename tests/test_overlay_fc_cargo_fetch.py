"""Regression tests for overlay FC cargo cache rebuilds."""

from __future__ import annotations

import sys
import types
import importlib.util
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
_PARENT = _ROOT.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

for name in ("timeout_session", "config"):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        if name == "config":
            mod.appname = "test"
        sys.modules[name] = mod

pkg = types.ModuleType("RavenColonail_EDMC")
pkg.__path__ = [str(_ROOT)]
sys.modules.setdefault("RavenColonail_EDMC", pkg)
ui_pkg = types.ModuleType("RavenColonail_EDMC.ui")
ui_pkg.__path__ = [str(_ROOT / "ui")]
sys.modules.setdefault("RavenColonail_EDMC.ui", ui_pkg)

_spec = importlib.util.spec_from_file_location(
    "RavenColonail_EDMC.ui.overlay_row",
    _ROOT / "ui" / "overlay_row.py",
)
assert _spec and _spec.loader
overlay_row = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = overlay_row
_spec.loader.exec_module(overlay_row)


class ImmediateThread:
    def __init__(self, target, daemon=False):
        self.target = target
        self.daemon = daemon

    def start(self) -> None:
        self.target()


class ImmediateFrame:
    def after(self, _delay, callback):
        callback()


def test_normal_overlay_fc_cargo_rebuild_does_not_call_api(monkeypatch) -> None:
    def fail_get_fc(_market_id):
        raise AssertionError("normal overlay cache rebuild must not call get_fc")

    monkeypatch.setattr(overlay_row, "Thread", ImmediateThread)
    plugin = SimpleNamespace(
        frame=ImmediateFrame(),
        overlay_project_linked_fcs=[{"marketId": 123, "label": "B9J-68T"}],
        _overlay_fc_cargo_inflight=False,
        selected_overlay_build_id="build-1",
        overlay_carrier_tracking_enabled=True,
        overlay_fc_selection="all",
        overlay_fc_cargo_by_market={123: {"steel": 999}},
        fc_handler=SimpleNamespace(
            linked_fcs={
                123: {
                    "marketId": 123,
                    "cargo": {"steel": 4300, "aluminium": 0},
                    "cargoSource": "raven_colonial_api",
                }
            }
        ),
        api_client=SimpleNamespace(get_fc=fail_get_fc),
        refresh_build_overlay=lambda: None,
    )
    controller = overlay_row.OverlayBuildRowController.__new__(
        overlay_row.OverlayBuildRowController
    )
    controller._ui = SimpleNamespace(plugin=plugin)
    controller.refresh_fc_combo_state = lambda: None

    controller.fetch_fc_cargo_async()

    assert plugin.overlay_fc_cargo_by_market == {123: {"steel": 4300}}
