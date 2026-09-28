"""Settings controls retain the native preferences palette and fit translated labels."""

from __future__ import annotations

import ast
import importlib
import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import ttk
from types import ModuleType, SimpleNamespace
from typing import Any, Optional

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _settings_functions(monkeypatch: Any, translate: Any) -> dict[str, Any]:
    """Load the real preferences section without starting EDMC's network workers."""
    package_name = "raven_settings_test"
    for name, directory in ((package_name, _ROOT), (f"{package_name}.ui", _ROOT / "ui")):
        package = ModuleType(name)
        package.__path__ = [str(directory)]
        monkeypatch.setitem(sys.modules, name, package)
    config = SimpleNamespace(get_str=lambda _key: "", get_int=lambda _key: 1)
    config_module = sys.modules.get("config", ModuleType("config"))
    monkeypatch.setitem(sys.modules, "config", config_module)
    monkeypatch.setattr(config_module, "config", config, raising=False)
    combo_module = importlib.import_module(f"{package_name}.ui.themed_combobox")
    monkeypatch.setattr(combo_module, "edmc_theme", None)
    shading_module = importlib.import_module(f"{package_name}.overlay.row_shading")
    tree = ast.parse((_ROOT / "load.py").read_text(encoding="utf-8"))
    names = {"_add_overlay_format_section", "_autosize_settings_combobox", "_add_row_highlight_section",
             "_persist_ravencolonial_prefs_from_frame"}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {
        "__package__": package_name,
        "tk": tk,
        "ttk": ttk,
        "myNotebook": SimpleNamespace(Frame=ttk.Frame, Label=ttk.Label),
        "config": config,
        "i18n": SimpleNamespace(tr=translate),
        "CONFIG_READ_ERRORS": (AttributeError, TypeError, ValueError),
        "OVERLAY_FORMAT_BREAKDOWN": "breakdown",
        "OVERLAY_FORMAT_SIMPLIFIED": "simplified",
        "normalize_overlay_format": lambda _value: "breakdown",
        "Optional": Optional,
        "read_row_highlight_opacity": shading_module.read_row_highlight_opacity,
        "normalize_row_highlight_opacity": shading_module.normalize_row_highlight_opacity,
        "ROW_HIGHLIGHT_OPACITY_KEY": shading_module.ROW_HIGHLIGHT_OPACITY_KEY,
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "load.py", "exec"), namespace)
    return namespace


@pytest.fixture
def settings_root() -> Any:
    """Provide real Tk widgets when a display is available."""
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    ttk.Style(root).theme_use("clam")
    root.withdraw()
    yield root
    root.destroy()


def test_overlay_format_uses_preferences_colors(settings_root: tk.Tk, monkeypatch: Any) -> None:
    """A dark main window must not turn a neutral preferences control orange."""
    namespace = _settings_functions(monkeypatch, lambda text: text)
    frame = ttk.Frame(settings_root)
    namespace["_add_overlay_format_section"](frame, 1)
    combo = frame.overlay_format_combo
    style = ttk.Style(settings_root)
    if hasattr(combo, "entry"):
        foreground = combo.entry.cget("foreground")
        background = combo.entry.cget("readonlybackground")
    else:
        combo_style = combo.cget("style") or "TCombobox"
        foreground = style.lookup(combo_style, "foreground", ("readonly",))
        background = style.lookup(combo_style, "fieldbackground", ("readonly",))
    assert settings_root.winfo_rgb(foreground) == settings_root.winfo_rgb(
        style.lookup("TCombobox", "foreground", ("readonly",)),
    )
    assert settings_root.winfo_rgb(background) == settings_root.winfo_rgb(
        style.lookup("TCombobox", "fieldbackground", ("readonly",)),
    )


def test_overlay_format_fits_the_selected_translation(settings_root: tk.Tk, monkeypatch: Any) -> None:
    """Switching to a longer translated choice grows the visible entry."""
    translated = "Simplified with a considerably longer translated label"
    namespace = _settings_functions(
        monkeypatch, lambda text: translated if text == "Simplified" else text,
    )
    frame = ttk.Frame(settings_root)
    frame.pack()
    namespace["_add_overlay_format_section"](frame, 1)
    settings_root.deiconify()
    settings_root.update()
    combo = frame.overlay_format_combo
    entry = getattr(combo, "entry", combo)
    initial_width = int(entry.cget("width"))
    frame.overlay_format_var.set(translated)
    entry.event_generate("<<ComboboxSelected>>")
    font = tkfont.Font(root=settings_root, font=entry.cget("font"))
    assert int(entry.cget("width")) > initial_width
    assert int(entry.cget("width")) * font.measure("0") >= font.measure(translated)


def test_row_highlight_slider_saves_zero_and_repaints_both_surfaces(settings_root: tk.Tk, monkeypatch: Any) -> None:
    """The percentage readout, Save path, and reopening preserve the chosen opacity."""
    namespace = _settings_functions(monkeypatch, lambda text: text)
    saved: dict[str, Any] = {}
    config = namespace["config"]
    config.get_int = lambda key, default=0: saved.get(key, default)
    config.set = lambda key, value: saved.update({key: value})
    frame = ttk.Frame(settings_root)
    namespace["_add_row_highlight_section"](frame, 1)
    assert frame.row_highlight_percent_var.get() == "8%"
    assert float(frame.row_highlight_scale.cget("from")) == 0
    assert float(frame.row_highlight_scale.cget("to")) == 100
    for value in (50, 100, 0):
        frame.row_highlight_scale.set(value)
        assert frame.row_highlight_percent_var.get() == f"{value}%"
    for name in ("api_key", "stealth", "stealth_ship_cargo", "stealth_construction", "check_updates", "autoupdate",
                 "prerelease", "overlay_theme"):
        setattr(frame, f"{name}_var", SimpleNamespace(get=lambda: "", set=lambda _value: None))
    frame.overlay_theme_combo = SimpleNamespace(get=lambda: "Elite Orange")
    frame._theme_display_to_id = {"Elite Orange": "elite_orange"}
    frame.overlay_format_combo = SimpleNamespace(get=lambda: "Breakdown")
    frame._format_display_to_id = {"Breakdown": "breakdown"}
    refreshed: list[str] = []
    namespace["this"] = SimpleNamespace(
        cmdr_name="", build_overlay=SimpleNamespace(refresh=lambda **_kwargs: refreshed.append("hud")),
        build_popout=SimpleNamespace(refresh=lambda **_kwargs: refreshed.append("popout")),
    )
    namespace["PluginConfig"] = SimpleNamespace(
        set_check_updates=lambda _value: None, set_autoupdate=lambda _value: None,
        set_check_prerelease=lambda _value: None,
    )
    namespace["_persist_ravencolonial_prefs_from_frame"](frame, "")
    assert saved[namespace["ROW_HIGHLIGHT_OPACITY_KEY"]] == 0
    assert namespace["this"].overlay_row_highlight_opacity == 0
    assert refreshed == ["hud", "popout"]
    reopened = ttk.Frame(settings_root)
    namespace["_add_row_highlight_section"](reopened, 1)
    assert reopened.row_highlight_percent_var.get() == "0%"
