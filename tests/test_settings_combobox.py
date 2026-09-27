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
from typing import Any

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
    tree = ast.parse((_ROOT / "load.py").read_text(encoding="utf-8"))
    names = {"_add_overlay_format_section", "_autosize_settings_combobox"}
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
