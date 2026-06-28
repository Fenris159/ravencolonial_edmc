"""Shutdown-aware Tk after scheduling helper."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PARENT = _ROOT.parent
_PACKAGE_NAME = "RavenColonail_EDMC"


def _install_edmc_stubs() -> None:
    import tkinter as tk

    config_mod = types.ModuleType("config")
    config_mod.appname = "test"
    config_mod.config = SimpleNamespace(shutting_down=False)
    sys.modules["config"] = config_mod

    companion_mod = types.ModuleType("companion")
    companion_mod.CAPIData = object
    sys.modules["companion"] = companion_mod

    l10n_mod = types.ModuleType("l10n")

    class _Translations:
        @staticmethod
        def tl(*args, **kwargs):
            return args[0] if args else ""

    l10n_mod.translations = _Translations()
    sys.modules["l10n"] = l10n_mod

    plug_mod = types.ModuleType("plug")
    plug_mod.show_error = lambda message: None
    sys.modules["plug"] = plug_mod

    my_nb = types.ModuleType("myNotebook")
    my_nb.Frame = tk.Frame
    my_nb.Notebook = tk.Frame
    sys.modules["myNotebook"] = my_nb
    sys.modules.setdefault("timeout_session", types.ModuleType("timeout_session"))


def _import_fresh_load_module():
    if str(_PARENT) not in sys.path:
        sys.path.insert(0, str(_PARENT))
    for name in list(sys.modules):
        if name == _PACKAGE_NAME or name.startswith(f"{_PACKAGE_NAME}."):
            del sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        _PACKAGE_NAME,
        _ROOT / "__init__.py",
        submodule_search_locations=[str(_ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not create package spec for {_PACKAGE_NAME}")
    package = importlib.util.module_from_spec(spec)
    sys.modules[_PACKAGE_NAME] = package
    spec.loader.exec_module(package)
    _install_edmc_stubs()
    return importlib.import_module(f"{_PACKAGE_NAME}.load")


@pytest.fixture
def load_module():
    mod = _import_fresh_load_module()
    original_this = mod.this
    yield mod
    mod.this = original_this


def test_schedule_after_returns_none_when_shutting_down(load_module) -> None:
    load_module.this = SimpleNamespace(frame=mock.Mock())
    with mock.patch.object(load_module, "_edmc_is_shutting_down", return_value=True):
        assert load_module.schedule_after(0, lambda: None) is None
    load_module.this.frame.after.assert_not_called()


def test_schedule_after_returns_none_when_plugin_frame_missing(load_module) -> None:
    load_module.this = SimpleNamespace(frame=None)
    with mock.patch.object(load_module, "_edmc_is_shutting_down", return_value=False):
        assert load_module.schedule_after(0, lambda: None) is None


def test_schedule_after_skips_destroyed_widget(load_module) -> None:
    frame = mock.Mock()
    frame.winfo_exists.return_value = True
    frame.after.return_value = "after-id"
    widget = mock.Mock()
    widget.winfo_exists.return_value = False
    load_module.this = SimpleNamespace(frame=frame)
    with mock.patch.object(load_module, "_edmc_is_shutting_down", return_value=False):
        assert load_module.schedule_after(0, lambda: None, widget=widget) is None
    frame.after.assert_not_called()


def test_schedule_after_schedules_on_plugin_frame(load_module) -> None:
    frame = mock.Mock()
    frame.winfo_exists.return_value = True
    frame.after.return_value = "after-id"
    callback = mock.Mock()
    load_module.this = SimpleNamespace(frame=frame)
    with mock.patch.object(load_module, "_edmc_is_shutting_down", return_value=False):
        after_id = load_module.schedule_after(50, callback)
    assert after_id == "after-id"
    frame.after.assert_called_once_with(50, callback)


def test_schedule_after_returns_none_on_tcl_error(load_module) -> None:
    import tkinter as tk

    frame = mock.Mock()
    frame.winfo_exists.return_value = True
    frame.after.side_effect = tk.TclError("destroyed")
    load_module.this = SimpleNamespace(frame=frame)
    with mock.patch.object(load_module, "_edmc_is_shutting_down", return_value=False):
        assert load_module.schedule_after(0, lambda: None) is None
