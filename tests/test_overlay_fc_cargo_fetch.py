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


class DeferredFrame:
    def __init__(self) -> None:
        self.after_calls = []

    def after(self, delay, callback):
        self.after_calls.append((delay, callback))
        return f"after-{len(self.after_calls)}"


class FakeButton:
    def __init__(self) -> None:
        self.kwargs = {}

    def configure(self, **kwargs) -> None:
        self.kwargs.update(kwargs)


class FakeCombo:
    def __init__(self) -> None:
        self.data = {}
        self.state = None

    def __setitem__(self, key, value) -> None:
        self.data[key] = value

    def __getitem__(self, key):
        return self.data.get(key, ())

    def configure(self, **kwargs) -> None:
        if "state" in kwargs:
            self.state = kwargs["state"]

    def apply_theme_styling(self) -> None:
        pass

    def set_entry_width_for_text(self, _text) -> None:
        pass


class FakeVar:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value) -> None:
        self.value = value

    def get(self):
        return self.value


def test_search_refresh_result_populates_build_dropdown() -> None:
    plugin = SimpleNamespace(
        current_system_address=123,
        overlay_ui_enabled=True,
        overlay_build_site_rows=[],
        overlay_sites_system_key=None,
        overlay_sites_transient_message=None,
        selected_overlay_build_id=None,
        overlay_carrier_tracking_enabled=False,
        refresh_build_overlay=lambda: None,
        get_project=lambda *args: None,
    )
    controller = overlay_row.OverlayBuildRowController.__new__(
        overlay_row.OverlayBuildRowController
    )
    controller._ui = SimpleNamespace(plugin=plugin)
    controller.combo = FakeCombo()
    controller.combo_var = FakeVar()
    controller.fc_combo = None
    controller.build_label = None
    controller.system_search_entry = None
    controller.search_var = SimpleNamespace(get=lambda: True)
    controller._system_search_placeholder_active = False
    controller.system_search_var = SimpleNamespace(get=lambda: "HIP 53931")
    controller._display_to_build_id = {}
    controller.refresh_fc_combo_state = lambda: None
    controller._apply_widget_states = lambda: None
    controller.on_external_refresh_complete = lambda: None

    controller.apply_refresh_result(
        {
            "ok": True,
            "system_key": "hip 53931",
            "system_address": None,
            "build_rows": [
                {
                    "id": "x1763599501437",
                    "name": "Geller Gateway",
                    "buildType": "aletheia",
                    "status": "Building",
                    "buildId": "fc0907b2-d2fe-467a-aaca-5279f9de9c0e",
                }
            ],
        }
    )

    assert "Geller Gateway | aletheia" in controller.combo["values"]
    assert controller.combo.state == "readonly"


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


def test_selected_missing_fc_manifest_fetches_once() -> None:
    calls = []

    class Handler:
        linked_fcs = {
            123: {
                "marketId": 123,
                "cargoSource": "active_project_linked_fc",
            }
        }

        def can_refresh_fc_cargo_from_api(self, market_id, trigger):
            return False, "context_not_allowed", 0

        def replace_fc_cargo_manifest(self, market_id, cargo, source, timestamp=None):
            self.linked_fcs[int(market_id)] = {
                "marketId": int(market_id),
                "cargo": dict(cargo),
                "cargoSource": source,
                "cargoUpdatedAt": timestamp,
            }

    def get_fc(market_id):
        calls.append(market_id)
        return {"marketId": market_id, "cargo": {"steel": 10929}}

    original_thread = overlay_row.Thread
    overlay_row.Thread = ImmediateThread
    try:
        plugin = SimpleNamespace(
            frame=ImmediateFrame(),
            overlay_project_linked_fcs=[{"marketId": 123, "label": "G6H-47G"}],
            _overlay_fc_cargo_inflight=False,
            selected_overlay_build_id="build-1",
            overlay_carrier_tracking_enabled=True,
            overlay_fc_selection="123",
            overlay_fc_cargo_by_market={},
            fc_handler=Handler(),
            api_client=SimpleNamespace(get_fc=get_fc),
            refresh_build_overlay=lambda: None,
        )
        controller = overlay_row.OverlayBuildRowController.__new__(
            overlay_row.OverlayBuildRowController
        )
        controller._ui = SimpleNamespace(plugin=plugin)
        controller.refresh_fc_combo_state = lambda: None

        controller.fetch_fc_cargo_async(
            trigger="manual_fc_selection",
            allow_api_refresh=True,
        )
    finally:
        overlay_row.Thread = original_thread

    assert calls == [123]
    assert plugin.overlay_fc_cargo_by_market == {123: {"steel": 10929}}


def test_selected_missing_fc_manifest_failure_stays_missing() -> None:
    calls = []
    refreshes = []

    class Handler:
        linked_fcs = {
            123: {
                "marketId": 123,
                "cargoSource": "active_project_linked_fc",
            }
        }

        def can_refresh_fc_cargo_from_api(self, market_id, trigger):
            return False, "context_not_allowed", 0

    def get_fc(market_id):
        calls.append(market_id)
        return None

    original_thread = overlay_row.Thread
    overlay_row.Thread = ImmediateThread
    try:
        plugin = SimpleNamespace(
            frame=ImmediateFrame(),
            overlay_project_linked_fcs=[{"marketId": 123, "label": "G6H-47G"}],
            _overlay_fc_cargo_inflight=False,
            selected_overlay_build_id="build-1",
            overlay_carrier_tracking_enabled=True,
            overlay_fc_selection="123",
            overlay_fc_cargo_by_market={},
            fc_handler=Handler(),
            api_client=SimpleNamespace(get_fc=get_fc),
            refresh_build_overlay=lambda: refreshes.append(True),
        )
        controller = overlay_row.OverlayBuildRowController.__new__(
            overlay_row.OverlayBuildRowController
        )
        controller._ui = SimpleNamespace(plugin=plugin)
        controller.refresh_fc_combo_state = lambda: None

        controller.fetch_fc_cargo_async(
            trigger="manual_fc_selection",
            allow_api_refresh=True,
        )
        controller.fetch_fc_cargo_async(
            trigger="manual_fc_selection",
            allow_api_refresh=True,
        )
    finally:
        overlay_row.Thread = original_thread

    assert calls == [123]
    assert plugin.overlay_fc_cargo_by_market == {}
    assert len(refreshes) == 2


def test_manual_selected_fc_manifest_refresh_fetches_even_when_cached() -> None:
    calls = []

    class Handler:
        linked_fcs = {
            123: {
                "marketId": 123,
                "cargo": {"steel": 4300},
                "cargoSource": "raven_colonial_api",
            }
        }

        def can_refresh_fc_cargo_from_api(self, market_id, trigger):
            return False, "context_not_allowed", 0

        def replace_fc_cargo_manifest(self, market_id, cargo, source, timestamp=None):
            self.linked_fcs[int(market_id)] = {
                "marketId": int(market_id),
                "cargo": dict(cargo),
                "cargoSource": source,
                "cargoUpdatedAt": timestamp,
            }

    def get_fc(market_id):
        calls.append(market_id)
        return {"marketId": market_id, "cargo": {"steel": 5000}}

    original_thread = overlay_row.Thread
    overlay_row.Thread = ImmediateThread
    try:
        plugin = SimpleNamespace(
            frame=ImmediateFrame(),
            overlay_project_linked_fcs=[{"marketId": 123, "label": "G6H-47G"}],
            _overlay_fc_cargo_inflight=False,
            selected_overlay_build_id="build-1",
            overlay_carrier_tracking_enabled=True,
            overlay_fc_selection="123",
            overlay_fc_cargo_by_market={123: {"steel": 4300}},
            fc_handler=Handler(),
            api_client=SimpleNamespace(get_fc=get_fc),
            refresh_build_overlay=lambda: None,
        )
        controller = overlay_row.OverlayBuildRowController.__new__(
            overlay_row.OverlayBuildRowController
        )
        controller._ui = SimpleNamespace(plugin=plugin)
        controller.refresh_fc_combo_state = lambda: None

        controller.fetch_fc_cargo_async(
            trigger="manual_fc_manifest_refresh",
            allow_api_refresh=True,
        )
    finally:
        overlay_row.Thread = original_thread

    assert calls == [123]
    assert plugin.overlay_fc_cargo_by_market == {123: {"steel": 5000}}


def test_manual_all_fc_manifest_refresh_fetches_each_linked_carrier() -> None:
    calls = []

    class Handler:
        linked_fcs = {
            123: {
                "marketId": 123,
                "cargo": {"steel": 4300},
                "cargoSource": "raven_colonial_api",
            },
            456: {
                "marketId": 456,
                "cargo": {"water": 20},
                "cargoSource": "raven_colonial_api",
            },
        }

        def can_refresh_fc_cargo_from_api(self, market_id, trigger):
            return False, "context_not_allowed", 0

        def replace_fc_cargo_manifest(self, market_id, cargo, source, timestamp=None):
            self.linked_fcs[int(market_id)] = {
                "marketId": int(market_id),
                "cargo": dict(cargo),
                "cargoSource": source,
                "cargoUpdatedAt": timestamp,
            }

    def get_fc(market_id):
        calls.append(market_id)
        return {"marketId": market_id, "cargo": {"steel": market_id}}

    original_thread = overlay_row.Thread
    overlay_row.Thread = ImmediateThread
    try:
        plugin = SimpleNamespace(
            frame=ImmediateFrame(),
            overlay_project_linked_fcs=[
                {"marketId": 123, "label": "G6H-47G"},
                {"marketId": 456, "label": "N4W-T0Z"},
            ],
            _overlay_fc_cargo_inflight=False,
            selected_overlay_build_id="build-1",
            overlay_carrier_tracking_enabled=True,
            overlay_fc_selection="all",
            overlay_fc_cargo_by_market={},
            fc_handler=Handler(),
            api_client=SimpleNamespace(get_fc=get_fc),
            refresh_build_overlay=lambda: None,
        )
        controller = overlay_row.OverlayBuildRowController.__new__(
            overlay_row.OverlayBuildRowController
        )
        controller._ui = SimpleNamespace(plugin=plugin)
        controller.refresh_fc_combo_state = lambda: None

        controller.fetch_fc_cargo_async(
            trigger="manual_fc_manifest_refresh",
            allow_api_refresh=True,
        )
    finally:
        overlay_row.Thread = original_thread

    assert calls == [123, 456]
    assert plugin.overlay_fc_cargo_by_market == {
        123: {"steel": 123},
        456: {"steel": 456},
    }


def test_fc_manifest_refresh_button_starts_realtime_countdown() -> None:
    frame = DeferredFrame()
    calls = []
    plugin = SimpleNamespace(
        frame=frame,
        overlay_ui_enabled=True,
        overlay_carrier_tracking_enabled=True,
        selected_overlay_build_id="build-1",
        overlay_fc_selection="123",
        _overlay_fc_cargo_inflight=False,
    )
    controller = overlay_row.OverlayBuildRowController.__new__(
        overlay_row.OverlayBuildRowController
    )
    controller._ui = SimpleNamespace(plugin=plugin)
    controller.fc_refresh_btn = FakeButton()
    controller.fetch_fc_cargo_async = lambda **kwargs: calls.append(kwargs)

    controller.start_selected_fc_manifest_refresh()

    assert controller.fc_refresh_btn.kwargs["state"] == overlay_row.tk.DISABLED
    assert controller.fc_refresh_btn.kwargs["text"] in {"59", "60"}
    assert frame.after_calls and frame.after_calls[0][0] == 1000
    assert calls == [{"trigger": "manual_fc_manifest_refresh", "allow_api_refresh": True}]


def test_fc_manifest_refresh_button_all_selection_is_available() -> None:
    plugin = SimpleNamespace(
        overlay_ui_enabled=True,
        overlay_carrier_tracking_enabled=True,
        selected_overlay_build_id="build-1",
        overlay_fc_selection="all",
        overlay_project_linked_fcs=[{"marketId": 123, "label": "G6H-47G"}],
        _overlay_fc_cargo_inflight=False,
    )
    controller = overlay_row.OverlayBuildRowController.__new__(
        overlay_row.OverlayBuildRowController
    )
    controller._ui = SimpleNamespace(plugin=plugin)

    assert controller._fc_manifest_refresh_available() is True


if __name__ == "__main__":
    class _MonkeyPatch:
        def setattr(self, obj, name, value):
            setattr(obj, name, value)

    test_search_refresh_result_populates_build_dropdown()
    test_normal_overlay_fc_cargo_rebuild_does_not_call_api(_MonkeyPatch())
    test_selected_missing_fc_manifest_fetches_once()
    test_selected_missing_fc_manifest_failure_stays_missing()
    test_manual_selected_fc_manifest_refresh_fetches_even_when_cached()
    test_manual_all_fc_manifest_refresh_fetches_each_linked_carrier()
    test_fc_manifest_refresh_button_starts_realtime_countdown()
    test_fc_manifest_refresh_button_all_selection_is_available()
    print("test_overlay_fc_cargo_fetch: OK")
