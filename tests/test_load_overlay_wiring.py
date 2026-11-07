"""Executed integration checks for journal, tracker, and EDMC hook wiring."""

from __future__ import annotations

import importlib
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import requests
from packaging.specifiers import SpecifierSet

from conftest import settle_commander_links


class Frame:
    """Represent the Tk scheduling boundary with explicitly dispatched callbacks."""

    def __init__(self) -> None:
        self.callbacks = []

    def winfo_exists(self) -> bool:
        """Keep this test surface alive."""
        return True

    def after(self, delay: int, callback: Any) -> str:
        """Dispatch callbacks only when the test pumps the UI."""
        self.callbacks.append(callback)
        return "scheduled"

    def dispatch(self) -> None:
        """Apply queued UI callbacks on the test's main thread."""
        while self.callbacks:
            self.callbacks.pop(0)()


class Variable:
    """Store a control's value at the Tk boundary."""

    def __init__(self, value: Any) -> None:
        self.value = value

    def get(self) -> Any:
        """Return the control value."""
        return self.value

    def set(self, value: Any) -> None:
        """Update the control value."""
        self.value = value


class OverlayClient:
    """Capture the external HUD messages that a player would see."""

    def __init__(self) -> None:
        self.messages = []

    def send_raw(self, message: dict) -> None:
        """Publish a HUD payload."""
        self.messages.append(message)

    def send_shape(self, *args: Any, **kwargs: Any) -> None:
        """Accept decorative HUD geometry."""


def test_cargo_journal_repaints_the_tracker(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real Cargo hook updates the rendered Ship column for the selected build."""
    load, plugin = edmc_plugin
    overlay_module = importlib.import_module(f"{load.__package__}.overlay.build_project")
    client = OverlayClient()
    monkeypatch.setattr(overlay_module, "get_overlay_client", lambda: client)
    monkeypatch.setattr(overlay_module, "register_build_tracker_group", lambda: None)
    monkeypatch.setattr(overlay_module, "seed_preferred_overlay_group_defaults_once", lambda: None)
    monkeypatch.setattr(plugin, "_ensure_api_worker", lambda: None)
    plugin.overlay_ui_enabled = True
    plugin.overlay_modern_enabled = True
    plugin.overlay_always_on = True
    plugin.selected_overlay_build_id = "review-build"
    plugin.overlay_project_cache = {
        "buildId": "review-build", "buildName": "Review build", "commodities": {"steel": 100},
    }
    plugin.build_overlay = overlay_module.BuildProjectOverlay(plugin)

    load.journal_entry("Alpha", False, "Sol", "", {
        "event": "Cargo", "Vessel": "Ship", "Count": 25, "Inventory": [{"Name": "steel", "Count": 25}],
    }, {})
    text = "\n".join(message.get("text", "") for message in client.messages)

    assert plugin.cargo == {"steel": 25}
    assert "Review build" in text
    assert "Steel" in text
    assert "100" in text
    assert "25" in text


def test_popout_mode_disables_hud_and_clears_selection(edmc_plugin) -> None:
    """Enabling then closing the popout reconciles both mode controls and selection."""
    _load, plugin = edmc_plugin
    row = plugin.ui_manager._overlay_row
    row.popout_var, row.enabled_var = Variable(True), Variable(True)
    plugin.overlay_modern_enabled = True
    plugin.selected_overlay_build_id = "old-build"
    row._on_popout_toggle()

    assert plugin.overlay_popout_enabled is True
    assert plugin.overlay_modern_enabled is False
    assert plugin.selected_overlay_build_id is None
    row.disable_popout_from_window()
    assert plugin.overlay_ui_enabled is False
    assert row.popout_var.get() is False
    assert row.enabled_var.get() is False


def test_plan_cache_system_change_preserves_tracker_rows(edmc_plugin) -> None:
    """Moving systems invalidates plan permissions without erasing chosen tracker data."""
    _load, plugin = edmc_plugin
    plugin.set_current_system_address(42)
    plugin.plan_sites_system_key = 42
    plugin.plan_sites_rows = [{"id": "old-plan"}]
    plugin.selected_plan_site_id = "old-plan"
    plugin.overlay_build_site_rows = [{"buildId": "tracked-build"}]
    plugin.selected_overlay_build_id = "tracked-build"

    plugin.set_current_system_address(43)

    assert plugin.plan_sites_rows == []
    assert plugin.selected_plan_site_id is None
    assert plugin.overlay_build_site_rows == [{"buildId": "tracked-build"}]
    assert plugin.selected_overlay_build_id == "tracked-build"


def test_depot_journal_updates_only_its_project_cache(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    """Depot A's journal truth cannot overwrite selected build B."""
    load, plugin = edmc_plugin
    monkeypatch.setattr(plugin, "_ensure_api_worker", lambda: None)
    monkeypatch.setattr(plugin.api_client, "get_project", lambda *args: {"buildId": "build-a"})
    plugin.selected_overlay_build_id = "build-b"
    plugin.overlay_project_cache = {"buildId": "build-b", "commodities": {"steel": 80}}
    load.journal_entry("Alpha", False, "Sol", "", {
        "event": "ColonisationConstructionDepot", "MarketID": 101, "SystemAddress": 42,
        "ResourcesRequired": [{"Name": "steel", "RequiredAmount": 100, "ProvidedAmount": 25}],
    }, {"SystemAddress": 42})

    assert plugin.overlay_project_cache == {"buildId": "build-b", "commodities": {"steel": 80}}
    assert plugin.overlay_project_cache_by_build_id["build-a"]["commodities"] == {"steel": 75}
    assert plugin._track_all_refresh_on_qualifying_undock is True


def test_qualifying_undock_refreshes_track_all_totals(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    """Track All loads and aggregates fresh needs after a qualifying undock."""
    load, plugin = edmc_plugin
    load.journal_entry("Alpha", False, "Sol", "", {"event": "Music"}, {})
    settle_commander_links(plugin)
    row_module = importlib.import_module(f"{load.__package__}.ui.overlay_row")
    monkeypatch.setattr(row_module, "Thread", lambda target, **kwargs: SimpleNamespace(start=target))
    monkeypatch.setattr(plugin.api_client, "get_project_by_build_id", lambda bid: {
        "buildId": bid, "commodities": {"steel": 20 if bid == "build-a" else 30},
    })
    plugin.frame = Frame()
    plugin.overlay_ui_enabled = True
    plugin.selected_overlay_build_id = "__OVERLAY_TRACK_ALL__"
    plugin.overlay_build_site_rows = [
        {"status": "build", "buildId": "build-a"}, {"status": "build", "buildId": "build-b"},
    ]
    plugin._track_all_refresh_on_qualifying_undock = True

    load.journal_entry("Alpha", False, "Sol", "", {"event": "Undocked"}, {})
    plugin.frame.dispatch()

    assert plugin.overlay_project_cache["commodities"] == {"steel": 50}
    assert plugin.selected_overlay_build_id == "__OVERLAY_TRACK_ALL__"


def test_manual_update_failure_reaches_main_thread_feedback(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed download schedules visible failure feedback instead of losing recovery."""
    load, plugin = edmc_plugin
    frame = plugin.frame = Frame()
    errors = []
    monkeypatch.setattr(load.plug, "show_error", errors.append)
    update = plugin.update_info
    update._data = update.Data("v9.0.0", "https://example.invalid/release", "https://example.invalid/update.zip", None)
    monkeypatch.setattr(sys.modules["timeout_session"], "new_session", lambda **kwargs: SimpleNamespace(
        get=lambda *args, **kw: SimpleNamespace(status_code=503),
    ))

    plugin.ui_manager._run_manual_autoupdate()
    assert errors == []
    frame.dispatch()

    assert len(errors) == 1
    assert "Update failed" in errors[0]
    assert "503" in errors[0]


def test_api_worker_error_reaches_main_thread_feedback(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    """A worker failure is displayed only when the UI processes its callback."""
    load, plugin = edmc_plugin
    frame = plugin.frame = Frame()
    errors = []
    monkeypatch.setattr(load.plug, "show_error", errors.append)

    def failed_http_request() -> None:
        raise requests.HTTPError("HTTP 503")

    plugin.api_queue.put((failed_http_request, (), {}))
    plugin.api_queue.put(None)
    plugin._api_worker()
    assert errors == []
    frame.dispatch()
    assert errors == ["Ravencolonial API error: HTTP 503"]


@pytest.mark.parametrize("hook", ["cmdr_data", "cmdr_data_legacy"])
def test_supported_capi_profile_hooks_supply_initial_identity(edmc_plugin, hook: str) -> None:
    """Both profile hooks recognize a commander without reading EDMC monitor internals."""
    load, plugin = edmc_plugin
    getattr(load, hook)({"commander": {"name": "Bravo"}}, False)
    assert plugin.cmdr_name == "Bravo"


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_platform_journal_defaults_include_native_layout(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str,
) -> None:
    """Journal fallback recognizes native platform install locations."""
    load, _plugin = edmc_plugin
    monkeypatch.setattr(load.sys, "platform", platform)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    candidates = load._candidate_elite_journal_dirs()
    if platform == "darwin":
        expected = tmp_path / "Library/Application Support/Frontier Developments/Elite Dangerous"
    else:
        expected = tmp_path / ".local/share/Steam/steamapps/compatdata/359320/pfx/drive_c/users/steamuser"
        expected /= "Saved Games/Frontier Developments/Elite Dangerous"
    assert expected in candidates


def test_python_metadata_accepts_the_supported_edmc_versions() -> None:
    """Package metadata accepts supported Python versions and rejects adjacent unsupported ones."""
    metadata = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    versions = SpecifierSet(metadata["project"]["requires-python"])
    assert [version in versions for version in ("3.10", "3.11", "3.12", "3.13", "3.14")] == [
        False, True, True, True, False,
    ]


def test_shutdown_closes_all_visible_plugin_surfaces(edmc_plugin) -> None:
    """Stopping the plugin clears HUD/popout content and closes the manifest editor."""
    load, plugin = edmc_plugin
    visible = {"hud": True, "popout": True, "editor": True}
    plugin.build_overlay = SimpleNamespace(clear=lambda: visible.update(hud=False))
    plugin.build_popout = SimpleNamespace(clear=lambda: visible.update(popout=False))
    plugin.fc_manifest_editor = SimpleNamespace(close=lambda: visible.update(editor=False))

    load._close_ui_surfaces_on_stop()

    assert visible == {"hud": False, "popout": False, "editor": False}


def test_build_picker_places_track_all_before_individual_projects(edmc_plugin) -> None:
    """The user-facing build choices retain placeholder, aggregate, then project order."""
    _load, plugin = edmc_plugin

    class Combo:
        def __init__(self) -> None:
            self.values = ()
            self.state = ""

        def __setitem__(self, key, value):
            self.values = value

        def __getitem__(self, key):
            return self.values

        def configure(self, **kwargs):
            self.state = kwargs.get("state", self.state)

        def apply_theme_styling(self):
            pass

        def set_entry_width_for_text(self, text):
            pass

    row = plugin.ui_manager._overlay_row
    row._details_built = True
    row.combo, row.combo_var = Combo(), Variable("")
    plugin.overlay_ui_enabled = True
    plugin.overlay_build_site_rows = [{"status": "build", "buildId": "build-a", "name": "A", "buildType": "outpost"}]

    row.refresh_row_state()

    assert row.combo.values == ("Select Build Project", "Track All", "A | outpost")
    assert row.combo.state == "readonly"
