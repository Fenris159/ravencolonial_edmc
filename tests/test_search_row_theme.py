"""Lazy search controls must use the main-window palette before opening preferences."""

from __future__ import annotations

import sys
import tkinter as tk
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from test_overlay_fc_cargo_fetch import overlay_row


def test_search_row_has_the_active_palette_on_first_open(monkeypatch: Any) -> None:
    """Opening settings cannot be required to theme a newly created search row."""
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    root.withdraw()
    background = "#0e0e0e"
    config = SimpleNamespace(get_int=lambda _key: 1, get_bool=lambda _key, default=False: default,
                             get_str=lambda _key: "")
    monkeypatch.setattr(sys.modules["config"], "config", config, raising=False)
    theme_module = ModuleType("theme")
    theme_module.theme = SimpleNamespace(
        current={"background": background, "foreground": "orange"},
        update=lambda widget: widget.configure(bg=background) if isinstance(widget, tk.Frame) else None,
    )
    monkeypatch.setitem(sys.modules, "theme", theme_module)
    try:
        parent = tk.Frame(root, bg=background)
        parent.pack()
        plugin = SimpleNamespace(
            frame=parent, overlay_ui_enabled=True, overlay_modern_enabled=True, overlay_popout_enabled=False,
            overlay_build_site_rows=[], selected_overlay_build_id=None, overlay_carrier_tracking_enabled=False,
            overlay_project_linked_fcs=[], overlay_fc_selection="all", overlay_fc_cargo_by_market={},
        )
        controller = overlay_row.OverlayBuildRowController(SimpleNamespace(plugin=plugin, plan_sites_row=None))
        controller._row_parent = parent
        controller.row = tk.Frame(parent, bg=background)
        controller.row.pack()
        controller._ensure_details_built()
        controller.search_var.set(True)
        controller._apply_widget_states()
        root.update_idletasks()
        entry = controller.system_search_entry
        assert entry.cget("background") == background
        assert controller.system_search_row.cget("background") == background
        initial = (entry.cget("background"), entry.cget("highlightbackground"), entry.cget("highlightcolor"))
        controller.refresh_theme()
        assert (entry.cget("background"), entry.cget("highlightbackground"), entry.cget("highlightcolor")) == initial
    finally:
        root.destroy()
