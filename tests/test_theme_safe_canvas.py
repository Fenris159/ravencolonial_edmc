"""Theme-safe Canvas behavior."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch


def _load_theme_safe_canvas_class():
    path = Path(__file__).resolve().parents[1] / "ui" / "theme_safe_canvas.py"
    spec = importlib.util.spec_from_file_location("theme_safe_canvas_under_test", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load theme_safe_canvas.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ThemeSafeCanvas


def _bare_canvas(ThemeSafeCanvas, supported: set[str]):
    canvas = ThemeSafeCanvas.__new__(ThemeSafeCanvas)
    canvas._supported_options = lambda: supported
    return canvas


def test_without_unsupported_options_filters_theme_keys() -> None:
    ThemeSafeCanvas = _load_theme_safe_canvas_class()
    canvas = _bare_canvas(
        ThemeSafeCanvas,
        {"width", "height", "background", "fg"},
    )

    cnf, kw = canvas._without_unsupported_options(
        foreground="#ff8000",
        fg="#ff8000",
        font=("TkDefaultFont", 10),
        width=1,
    )
    assert cnf is None
    assert kw == {"fg": "#ff8000", "width": 1}

    cnf, kw = canvas._without_unsupported_options(
        {"foreground": "#ff8000", "width": 2, "font": ("TkDefaultFont", 10)},
    )
    assert cnf == {"width": 2}
    assert kw == {}


def test_configure_skips_unsupported_theme_assignments() -> None:
    ThemeSafeCanvas = _load_theme_safe_canvas_class()
    canvas = _bare_canvas(ThemeSafeCanvas, {"width", "height"})

    with patch("tkinter.Canvas.configure", return_value=None) as super_configure:
        canvas["foreground"] = "#ff8000"
        super_configure.assert_called_once_with({})

        super_configure.reset_mock()
        canvas.configure(fg="#ff8000", font=("TkDefaultFont", 10))
        super_configure.assert_called_once_with()

        super_configure.reset_mock()
        canvas.configure(width=1)
        super_configure.assert_called_once_with(None, width=1)
