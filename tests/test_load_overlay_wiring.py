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
    _require_contains(text, "from .overlay import BuildProjectOverlay")
    _require_contains(text, "self.build_overlay = BuildProjectOverlay(self)")
    _require_contains(text, "def refresh_build_overlay(self)")
    _require_contains(text, "def get_project_by_build_id(self")
    _require_contains(text, "self.overlay_build_site_rows")
    _require_contains(text, "def refresh_track_all_projects_if_selected(self")
    _require_contains(text, "self._track_all_refresh_on_qualifying_undock")
    _require_contains(text, 'refresh_track_all_projects_if_selected("qualifying undock")')
    _require_contains(text, "this.build_overlay.clear()")


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
    _require_contains(combo_text, "listbox_height = max(measured_h, item_h, 28)")
