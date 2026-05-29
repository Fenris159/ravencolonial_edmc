"""Tests for opening EDMC settings on the plugin tab."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_spec = importlib.util.spec_from_file_location(
    "ravencolonial_open_edmc_settings",
    _ROOT / "ui" / "open_edmc_settings.py",
)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

select_plugin_prefs_tab = _mod.select_plugin_prefs_tab


def test_select_plugin_prefs_tab_exact_match() -> None:
    notebook = MagicMock()
    notebook.tabs.return_value = ("tab1", "tab2")
    notebook.tab.side_effect = lambda tab_id, key: {
        ("tab1", "text"): "Other",
        ("tab2", "text"): "RavenColonial_EDMC",
    }[(tab_id, key)]

    assert select_plugin_prefs_tab(notebook, "RavenColonial_EDMC") is True
    notebook.select.assert_called_once_with("tab2")
    notebook.see.assert_called_once_with("tab2")


def test_select_plugin_prefs_tab_case_insensitive() -> None:
    notebook = MagicMock()
    notebook.tabs.return_value = ("tab1",)
    notebook.tab.return_value = "ravencolonial_edmc"

    assert select_plugin_prefs_tab(notebook, "RavenColonial_EDMC") is True
    notebook.select.assert_called_once_with("tab1")


def test_select_plugin_prefs_tab_missing() -> None:
    notebook = MagicMock()
    notebook.tabs.return_value = ("tab1",)
    notebook.tab.return_value = "Other Plugin"

    assert select_plugin_prefs_tab(notebook, "RavenColonial_EDMC") is False
    notebook.select.assert_not_called()
