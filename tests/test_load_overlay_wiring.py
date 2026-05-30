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
    assert "this.build_overlay.clear()" in text
