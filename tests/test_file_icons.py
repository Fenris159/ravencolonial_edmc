"""Portable file icons retain native button geometry, colors, and countdown behavior."""

from __future__ import annotations

import gc
import importlib.util
import time
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("raven_file_icons_test", _ROOT / "ui" / "file_icons.py")
assert _spec and _spec.loader
_icons = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_icons)
IconButton = _icons.IconButton


@pytest.fixture
def icon_root() -> Any:
    """Create isolated native Tk controls without touching the running EDMC window."""
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk display unavailable")
    root.withdraw()
    yield root
    root.destroy()


@pytest.mark.parametrize("point_size", [9, 12, 18, 24])
def test_icon_only_buttons_keep_the_previous_text_button_size(icon_root: tk.Tk, point_size: int) -> None:
    """Replacing font glyphs must preserve the same refresh and dropdown hit targets."""
    for icon, glyph, width in (("refresh", "\u27f3", 3), ("dropdown", "\u25bc", 2)):
        font = ("DejaVu Sans", point_size)
        old = tk.Button(icon_root, text=glyph, width=width, font=font)
        new = IconButton(icon_root, icon=icon, width=width, font=font)
        assert (new.winfo_reqwidth(), new.winfo_reqheight()) == (old.winfo_reqwidth(), old.winfo_reqheight())
        assert new.cget("image")


@pytest.mark.parametrize("point_size", [9, 18])
def test_action_captions_keep_the_previous_button_layout(icon_root: tk.Tk, point_size: int) -> None:
    """Image prefixes must not expand rows or clip the remaining translated caption."""
    actions = (("open", "\U0001f310 ", "Open Build Page"), ("build", "\U0001f6a7", "Create Build Project"),
               ("link", "\U0001f517 ", "Link Build Site"), ("download", "\U0001f4e5 ", "Go to Download"),
               ("update", "\u26a1 ", "Auto-Update"), ("close", "\u2716 ", "Dismiss"))
    for icon, prefix, caption in actions:
        font = ("DejaVu Sans", point_size)
        old = tk.Button(icon_root, text=prefix + caption, font=font)
        new = IconButton(icon_root, icon=icon, text=caption, font=font)
        assert new.winfo_reqheight() == old.winfo_reqheight()
        assert abs(new.winfo_reqwidth() - old.winfo_reqwidth()) <= 1
        assert new.cget("text") == caption


def test_file_icons_survive_collection_and_follow_theme_state(icon_root: tk.Tk) -> None:
    """Bitmap assets stay alive and recolor for normal, disabled, hover, and font changes."""
    for name in _icons.ICON_NAMES:
        for size in _icons.ICON_SIZES:
            image = tk.BitmapImage(master=icon_root, file=str(_icons.ICON_DIRECTORY / f"{name}-{size}.xbm"))
            assert (image.width(), image.height()) == (size, size)
    invoked: list[bool] = []
    button = IconButton(icon_root, icon="refresh", width=3, command=lambda: invoked.append(True))
    gc.collect()
    assert str(button.cget("image")) in icon_root.tk.call("image", "names")
    button.configure(foreground="orange", disabledforeground="gray", activeforeground="white")
    assert icon_root.tk.splitlist(button._icon_images[0]["foreground"])[-1] == "orange"
    button.configure(state=tk.DISABLED)
    assert str(button.cget("image")) == str(button._icon_images[1])
    button.configure(state=tk.NORMAL)
    button._on_enter(tk.Event())
    assert str(button.cget("image")) == str(button._icon_images[2])
    button._on_leave(tk.Event())
    button.configure(font=("DejaVu Sans", 24), foreground="black")
    assert icon_root.tk.splitlist(button._icon_images[0]["foreground"])[-1] == "black"
    button.invoke()
    assert invoked == [True]


def test_carrier_countdown_does_not_collapse_the_icon_button(icon_root: tk.Tk) -> None:
    """Run the real carrier refresh state path through image, countdown, and image again."""
    from test_overlay_fc_cargo_fetch import overlay_row

    plugin = SimpleNamespace(
        frame=icon_root, schedule_after=lambda *_args: "pending", overlay_ui_enabled=True,
        overlay_carrier_tracking_enabled=True, selected_overlay_build_id="port", _overlay_fc_cargo_inflight=False,
        overlay_project_linked_fcs=[{"marketId": 123}], overlay_fc_selection="all",
    )
    controller = overlay_row.OverlayBuildRowController(SimpleNamespace(plugin=plugin))
    controller.fc_refresh_btn = IconButton(icon_root, icon="refresh", width=3, font=("DejaVu Sans", 18))
    button = controller.fc_refresh_btn
    original = (button.winfo_reqwidth(), button.winfo_reqheight())
    controller._fc_refresh_cooldown_until = time.monotonic() + 60
    controller._refresh_fc_manifest_button_state()
    assert button.cget("text") in {"59", "60"}
    assert not button.cget("image")
    assert (button.winfo_reqwidth(), button.winfo_reqheight()) == original
    controller._fc_refresh_cooldown_until = 0
    controller._refresh_fc_manifest_button_state()
    assert button.cget("image")
    assert (button.winfo_reqwidth(), button.winfo_reqheight()) == original
