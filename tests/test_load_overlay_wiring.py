"""Regression: load.py must wire BuildProjectOverlay (no accidental removal)."""

from __future__ import annotations

from pathlib import Path

_LOAD_PY = Path(__file__).resolve().parents[1] / "load.py"


def test_load_py_wires_build_overlay() -> None:
    text = _LOAD_PY.read_text(encoding="utf-8")
    assert "self.build_overlay = None" in text
    assert "from .overlay import BuildProjectOverlay" in text
    assert "self.build_overlay = BuildProjectOverlay(self)" in text
    assert "def refresh_build_overlay(self)" in text
    assert "def get_project_by_build_id(self" in text
    assert "self.overlay_build_site_rows" in text
    assert "def refresh_track_all_projects_if_selected(self" in text
    assert "self._track_all_refresh_on_qualifying_undock" in text
    assert 'refresh_track_all_projects_if_selected("qualifying undock")' in text
    assert "this.build_overlay.clear()" in text


def test_journal_marks_track_all_refresh_after_depot_event() -> None:
    text = (Path(__file__).resolve().parents[1] / "handlers" / "journal.py").read_text(
        encoding="utf-8"
    )
    assert "def handle_colonisation_construction_depot" in text
    assert "self.plugin._track_all_refresh_on_qualifying_undock = True" in text
