"""Regression: load.py must wire BuildProjectOverlay (no accidental removal)."""

from __future__ import annotations

from pathlib import Path

_LOAD_PY = Path(__file__).resolve().parents[1] / "load.py"


def _require_contains(text: str, needle: str) -> None:
    if needle not in text:
        raise AssertionError(f"Expected to find {needle!r}")


def test_load_py_wires_build_overlay() -> None:
    text = _LOAD_PY.read_text(encoding="utf-8")
    _require_contains(text, "self.build_overlay = None")
    _require_contains(text, "self.build_popout = None")
    _require_contains(text, "from .overlay import BuildProjectOverlay")
    _require_contains(text, "self.build_overlay = BuildProjectOverlay(self)")
    _require_contains(text, "from .overlay.popout import BuildProjectPopout")
    _require_contains(text, "self.build_popout = BuildProjectPopout(self)")
    _require_contains(text, "def refresh_build_overlay(self, *, force: bool = False)")
    _require_contains(text, "def _sync_docked_state_from_edmc_state(")
    _require_contains(text, "this._sync_docked_state_from_edmc_state(state, station=station)")
    _require_contains(text, "from .dock_state_sync import apply_plugin_dock_fields_from_edmc_state")
    dock_sync_text = (_LOAD_PY.parent / "dock_state_sync.py").read_text(encoding="utf-8")
    _require_contains(dock_sync_text, "def apply_plugin_dock_fields_from_edmc_state(")
    _require_contains(text, "def get_project_by_build_id(self")
    _require_contains(text, "self.overlay_build_site_rows")
    _require_contains(text, "def refresh_track_all_projects_if_selected(self")
    _require_contains(text, "self._track_all_refresh_on_qualifying_undock")
    _require_contains(text, 'refresh_track_all_projects_if_selected("qualifying undock")')
    _require_contains(text, "def _close_ui_surfaces_on_stop()")
    _require_contains(text, '("build_overlay", "clear"')
    _require_contains(text, '("build_popout", "clear"')
    _require_contains(text, '("fc_manifest_editor", "close"')
    _require_contains(text, "_close_ui_surfaces_on_stop()")
    docked_pos = text.index("if event == 'Docked':")
    docked_update_pos = text.index("this.update_create_button()", docked_pos)
    carrier_stats_pos = text.index("elif event == 'CarrierStats'", docked_pos)
    if carrier_stats_pos < docked_update_pos:
        raise AssertionError("CarrierStats handling must not interrupt the Docked event block")


def test_overlay_row_wires_popout_tracker_mode() -> None:
    root = Path(__file__).resolve().parents[1]
    overlay_text = (root / "ui" / "overlay_row.py").read_text(encoding="utf-8")
    popout_text = (root / "overlay" / "popout.py").read_text(encoding="utf-8")
    l10n_text = (root / "L10n" / "en.template").read_text(encoding="utf-8")

    _require_contains(overlay_text, 'text=tr("Popout Tracker")')
    _require_contains(overlay_text, 'tr("Popout Tracker")')
    _require_contains(overlay_text, "visible=not modern_active")
    _require_contains(overlay_text, "p.selected_overlay_build_id = self._build_id_in_config() or None")
    _require_contains(overlay_text, "def _reset_build_selection_after_sites_refresh(self)")
    _require_contains(overlay_text, "self._reset_build_selection_after_sites_refresh()")
    _require_contains(overlay_text, "self.on_external_refresh_complete()")
    _require_contains(overlay_text, "self._schedule_tracker_refresh(force=True)")
    _require_contains(overlay_text, "def _on_popout_toggle(self)")
    _require_contains(overlay_text, "p.overlay_modern_enabled = False")
    _require_contains(overlay_text, "p.overlay_popout_enabled = enabled")
    _require_contains(overlay_text, "disable_popout_from_window")
    _require_contains(overlay_text, "def reset_and_show_popout(self) -> bool")
    _require_contains(overlay_text, "popout.reset_position()")
    _require_contains(overlay_text, "p.build_overlay.clear()")
    _require_contains(popout_text, "class BuildProjectPopout")
    _require_contains(popout_text, "POPOUT_TRACKER_TITLE_KEY")
    _require_contains(popout_text, "tr(POPOUT_TRACKER_TITLE_KEY)")
    _require_contains(popout_text, "def refresh_localized_text(self)")
    _require_contains(popout_text, "ensure_bundled_oxanium_font_registered")
    _require_contains(l10n_text, '"Popout Tracker" = "Popout Tracker";')


def test_settings_wires_popout_position_recovery() -> None:
    root = Path(__file__).resolve().parents[1]
    load_text = (root / "load.py").read_text(encoding="utf-8")
    l10n_text = (root / "L10n" / "en.template").read_text(encoding="utf-8")

    _require_contains(load_text, "def _prefs_reset_popout_position(frame: nb.Frame)")
    _require_contains(load_text, "def _add_popout_recovery_section(frame: nb.Frame")
    _require_contains(load_text, "overlay_row.reset_and_show_popout()")
    _require_contains(load_text, 'text=i18n.tr("Reset and show Popout Tracker")')
    _require_contains(l10n_text, '"Reset and show Popout Tracker" = "Reset and show Popout Tracker";')


def test_journal_marks_track_all_refresh_after_depot_event() -> None:
    text = (Path(__file__).resolve().parents[1] / "handlers" / "journal.py").read_text(
        encoding="utf-8"
    )
    _require_contains(text, "def handle_colonisation_construction_depot")
    _require_contains(text, "self.plugin._track_all_refresh_on_qualifying_undock = True")


def test_depot_patch_uses_direct_scoped_cache_update() -> None:
    root = Path(__file__).resolve().parents[1]
    load_text = (root / "load.py").read_text(encoding="utf-8")
    journal_text = (root / "handlers" / "journal.py").read_text(encoding="utf-8")

    _require_contains(load_text, "apply_project_cache_update(")
    _require_contains(journal_text, "apply_project_cache_update(")
    if "install_scoped_depot_patch" in load_text or "install_scoped_depot_patch" in journal_text:
        raise AssertionError("Depot cache scoping must not depend on a runtime method replacement")
    if (root / "depot_overlay_sync.py").exists():
        raise AssertionError("Temporary depot runtime-patch module should be removed")


def test_track_all_dropdown_order_and_uncapped_height() -> None:
    root = Path(__file__).resolve().parents[1]
    overlay_text = (root / "ui" / "overlay_row.py").read_text(encoding="utf-8")
    combo_text = (root / "ui" / "themed_combobox.py").read_text(encoding="utf-8")
    _require_contains(overlay_text, "labels = [placeholder, track_all_label]")
    _require_contains(combo_text, "listbox.configure(height=len(")
    _require_contains(combo_text, "listbox_height = max(measured_h, item_h, 28)")
    if ".see(idx)" in combo_text:
        raise AssertionError("ThemedCombobox popup must not auto-scroll to the current value")


def test_plan_site_cache_is_system_scoped_without_clearing_overlay_rows() -> None:
    root = Path(__file__).resolve().parents[1]
    load_text = (root / "load.py").read_text(encoding="utf-8")
    manager_text = (root / "ui" / "manager.py").read_text(encoding="utf-8")

    _require_contains(load_text, "def clear_plan_sites_cache(self)")
    _require_contains(load_text, "def set_current_system_address(self, system_address")
    _require_contains(load_text, "this.set_current_system_address(sa)")
    _require_contains(load_text, "this.set_current_system_address(entry.get('SystemAddress'))")
    _require_contains(manager_text, "p.clear_plan_sites_cache()")

    clear_start = load_text.index("def clear_plan_sites_cache(self)")
    clear_end = load_text.index("def set_current_system_address", clear_start)
    clear_body = load_text[clear_start:clear_end]
    if "overlay_build_site_rows" in clear_body:
        raise AssertionError("Plan-site cache clearing must not clear persistent overlay build rows")


def test_manual_autoupdate_failure_ui_is_scheduled_on_main_thread() -> None:
    root = Path(__file__).resolve().parents[1]
    manager_text = (root / "ui" / "manager.py").read_text(encoding="utf-8")
    load_text = (root / "load.py").read_text(encoding="utf-8")

    _require_contains(manager_text, "def show_failure():")
    _require_contains(manager_text, "self.plugin.schedule_after(0, show_failure)")
    _require_contains(load_text, "def schedule_after(")
    _require_contains(load_text, "self.schedule_after = schedule_after")


def test_startup_autoupdate_failure_ui_is_scheduled_on_main_thread() -> None:
    load_text = (Path(__file__).resolve().parents[1] / "load.py").read_text(encoding="utf-8")

    _require_contains(load_text, "def _show_plugin_error_main_thread")
    _require_contains(load_text, "_show_plugin_error_main_thread(")


def test_api_worker_errors_use_main_thread_error_helper() -> None:
    load_text = (Path(__file__).resolve().parents[1] / "load.py").read_text(encoding="utf-8")

    worker_start = load_text.index("def _api_worker(self):")
    worker_end = load_text.index("def queue_api_call", worker_start)
    worker_body = load_text[worker_start:worker_end]

    _require_contains(worker_body, "_show_plugin_error_main_thread(error_msg)")
    if "plug.show_error(error_msg)" in worker_body:
        raise AssertionError("API worker must not call plug.show_error directly from the worker thread")


def test_journal_fallbacks_cover_non_windows_platforms() -> None:
    load_text = (Path(__file__).resolve().parents[1] / "load.py").read_text(encoding="utf-8")

    _require_contains(load_text, "def _candidate_elite_journal_dirs()")
    _require_contains(load_text, 'sys.platform == "darwin"')
    _require_contains(load_text, "XDG_DATA_HOME")
    _require_contains(load_text, "compatdata")
    _require_contains(load_text, "def _recent_files(")


def test_python_metadata_supports_edmc_python_range() -> None:
    pyproject_text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )

    _require_contains(pyproject_text, 'requires-python = ">=3.11,<3.14"')


def test_commander_name_fallback_uses_supported_hooks_not_monitor_cmdr() -> None:
    root = Path(__file__).resolve().parents[1]
    load_text = (root / "load.py").read_text(encoding="utf-8")
    manager_text = (root / "ui" / "manager.py").read_text(encoding="utf-8")

    _require_contains(load_text, "def remember_commander_from_hook(")
    _require_contains(load_text, "this.remember_commander_from_hook(cmdr, source=\"journal_entry\"")
    _require_contains(load_text, "def _cmdr_name_from_capi_data(data")
    _require_contains(load_text, "getattr(data, \"request_cmdr\", None)")
    if "monitor.cmdr" in load_text or "from monitor import monitor" in load_text:
        raise AssertionError("Commander fallback must use supported hook data, not monitor.cmdr")
    if "cmdr_snapshot" in load_text or "cmdr_snapshot" in manager_text:
        raise AssertionError("Unsupported monitor-derived commander snapshot should not be used")


def test_capi_hooks_do_not_reach_into_companion_session_or_squadron_endpoint() -> None:
    root = Path(__file__).resolve().parents[1]
    load_text = (root / "load.py").read_text(encoding="utf-8")
    cache_text = (root / "capi_cache.py").read_text(encoding="utf-8")

    _require_contains(load_text, "from companion import CAPIData")
    _require_contains(load_text, 'capi_cache.write("cmdr_data"')
    _require_contains(load_text, 'capi_cache.write("cmdr_data_legacy"')
    _require_contains(load_text, 'capi_cache.write("fleetcarrier"')
    for forbidden in (
        "import companion",
        "companion.session",
        "requests_session",
        "/squadron",
        '"squadron"',
        "maybe_queue_squadron_cache_refresh",
        "_fetch_and_cache_squadron",
    ):
        if forbidden in load_text:
            raise AssertionError(f"Unsupported Companion /squadron path remains in load.py: {forbidden}")
    if '"squadron"' in cache_text:
        raise AssertionError("CAPI cache should only accept supported EDMC CAPI hook snapshot kinds")
