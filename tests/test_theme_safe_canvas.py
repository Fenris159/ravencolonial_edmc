"""Theme-safe Canvas behavior."""

from __future__ import annotations

import tkinter as tk
import importlib.util
from pathlib import Path


def _load_theme_safe_canvas_class():
    path = Path(__file__).resolve().parents[1] / "ui" / "theme_safe_canvas.py"
    spec = importlib.util.spec_from_file_location("theme_safe_canvas_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load theme_safe_canvas.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ThemeSafeCanvas


def test_theme_safe_canvas_ignores_unsupported_theme_assignments() -> None:
    ThemeSafeCanvas = _load_theme_safe_canvas_class()
    root = tk.Tk()
    root.withdraw()
    try:
        canvas = ThemeSafeCanvas(root, width=1, height=1)

        canvas["foreground"] = "#ff8000"
        canvas.configure(fg="#ff8000")
        canvas.configure(font=("TkDefaultFont", 10))

        assert int(canvas.cget("width")) == 1
    finally:
        root.destroy()
