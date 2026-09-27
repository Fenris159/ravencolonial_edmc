"""Custom title dragging remains accurate with asynchronous window movement."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

for name in ("timeout_session", "config"):
    if name not in sys.modules:
        module = ModuleType(name)
        if name == "config":
            module.appname = "test"
        sys.modules[name] = module

from overlay.popout import BuildProjectPopout
from overlay import popout as popout_module


def test_drag_uses_total_pointer_displacement_before_window_manager_catches_up() -> None:
    """Queued drag events must retain all movement when Tk still reports the old position."""
    bindings: dict[str, object] = {}
    title = SimpleNamespace(bind=lambda event, callback: bindings.update({event: callback}))
    window = SimpleNamespace(winfo_x=lambda: -500, winfo_y=lambda: 200, geometry=Mock())
    popout = BuildProjectPopout(SimpleNamespace(frame=None))
    popout._window = window
    popout._title_bar = title
    popout._bind_window_drag()

    bindings["<Button-1>"](SimpleNamespace(x_root=-450, y_root=210))
    bindings["<B1-Motion>"](SimpleNamespace(x_root=-450, y_root=210))
    bindings["<B1-Motion>"](SimpleNamespace(x_root=-440, y_root=220))
    bindings["<B1-Motion>"](SimpleNamespace(x_root=-425, y_root=245))

    assert [call.args[0] for call in window.geometry.call_args_list] == [
        "+-500+200", "+-490+210", "+-475+235",
    ]
    with patch.object(popout, "_save_window_position") as save:
        bindings["<ButtonRelease-1>"](SimpleNamespace())
        save.assert_called_once_with(window)
    window.geometry.reset_mock()
    bindings["<B1-Motion>"](SimpleNamespace(x_root=-410, y_root=255))
    window.geometry.assert_not_called()


def test_linux_popout_removes_decorations_and_keeps_window_management() -> None:
    """X11 decoration hints retain normal taskbar and window-manager behavior."""
    window = SimpleNamespace(attributes=Mock(), overrideredirect=Mock())
    with (
        patch.object(sys, "platform", "linux"),
        patch.object(popout_module, "hide_x11_decorations", return_value=True, create=True) as hide,
    ):
        BuildProjectPopout._configure_window_manager_hints(window)
    hide.assert_called_once_with(window)
    window.attributes.assert_called_once_with("-type", "normal")
    window.overrideredirect.assert_not_called()


def test_linux_popout_stays_borderless_when_x11_hints_are_unavailable() -> None:
    """A missing X11 display or library must not produce two title bars."""
    window = SimpleNamespace(attributes=Mock(), overrideredirect=Mock())
    with (
        patch.object(sys, "platform", "linux"),
        patch.object(popout_module, "hide_x11_decorations", return_value=False, create=True),
    ):
        BuildProjectPopout._configure_window_manager_hints(window)
    window.overrideredirect.assert_called_once_with(True)
