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
    _require_contains(text, "def get_project_by_build_id(self")
    _require_contains(text, "self.overlay_build_site_rows")
    _require_contains(text, "def refresh_track_all_projects_if_selected(self")
    _require_contains(text, "self._track_all_refresh_on_qualifying_undock")
    _require_contains(text, 'refresh_track_all_projects_if_selected("qualifying undock")')
    _require_contains(text, "this.build_overlay.clear()")
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

    _require_contains(overlay_text, 'text=tr("Enable Popout")')
    _require_contains(overlay_text, 'tr("Popout Tracker")')
    _require_contains(overlay_text, "def _on_popout_toggle(self)")
    _require_contains(overlay_text, "p.overlay_modern_enabled = False")
    _require_contains(overlay_text, "p.overlay_popout_enabled = enabled")
    _require_contains(overlay_text, "disable_popout_from_window")
    _require_contains(popout_text, "class BuildProjectPopout")
    _require_contains(popout_text, "ensure_bundled_oxanium_font_registered")
    _require_contains(l10n_text, '"Enable Popout" = "Enable Popout";')
    _require_contains(l10n_text, '"Popout Tracker" = "Popout Tracker";')


def test_journal_marks_track_all_refresh_after_depot_event() -> None:
    text = (Path(__file__).resolve().parents[1] / "handlers" / "journal.py").read_text(
        encoding="utf-8"
    )
    _require_contains(text, "def handle_colonisation_construction_depot")
    _require_contains(text, "self.plugin._track_all_refresh_on_qualifying_undock = True")


def test_track_all_dropdown_order_and_uncapped_height() -> None:
    root = Path(__file__).resolve().parents[1]
    overlay_text = (root / "ui" / "overlay_row.py").read_text(encoding="utf-8")
    combo_text = (root / "ui" / "themed_combobox.py").read_text(encoding="utf-8")
    _require_contains(overlay_text, "labels = [placeholder, track_all_label]")
    _require_contains(combo_text, "self.listbox.configure(height=len(self.values))")
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
