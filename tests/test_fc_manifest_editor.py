"""Tests for Fleet Carrier manifest editor helpers."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "RavenColonail_EDMC"

if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

for name in ("timeout_session", "config", "plug"):
    sys.modules.setdefault(name, types.ModuleType(name))

config_mod = sys.modules["config"]
config_mod.appname = getattr(config_mod, "appname", "test")


class _Config:
    def get_int(self, _key, default=0):
        return default


if not hasattr(config_mod, "config"):
    config_mod.config = _Config()

spec = importlib.util.spec_from_file_location(
    f"{PACKAGE}.ui.fc_manifest_editor",
    ROOT / "ui" / "fc_manifest_editor.py",
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_normalize_manifest_drops_zero_negative_and_invalid_values() -> None:
    """Verify normalize manifest drops zero negative and invalid values."""
    assert module.normalize_manifest(
        {
            "microcontrollers": "32",
            "$evacuationshelter_name;": 0,
            "steel": -1,
            "bad": "x",
        }
    ) == {"microcontrollers": 32}


def test_available_commodity_options_excludes_present_manifest_keys() -> None:
    """Verify available commodity options excludes present manifest keys."""
    options = module.available_commodity_options({"microcontrollers": 91})
    keys = {opt.key for opt in options}

    assert "microcontrollers" not in keys
    assert "steel" in keys


def test_available_commodity_options_limited_to_manifest_editor_categories() -> None:
    """Verify available commodity options limited to manifest editor categories."""
    options = module.available_commodity_options({})
    by_key = {opt.key: opt for opt in options}
    categories = {opt.category for opt in options}

    assert "steel" in by_key
    assert "basicmedicines" in by_key
    assert "battleweapons" in by_key
    assert "preciousgems" not in by_key
    assert "indite" not in by_key
    assert categories <= module.ADD_COMMODITY_CATEGORIES


def test_manifest_update_payload_sends_zero_for_removed_baseline_rows() -> None:
    """Verify manifest update payload sends zero for removed baseline rows."""
    payload = module.manifest_update_payload(
        {"microcontrollers": 91, "steel": 0},
        {"microcontrollers": 90, "steel": 1, "indite": 1},
    )

    assert payload == {"microcontrollers": 91, "steel": 0, "indite": 0}


def test_manifest_update_payload_omits_removed_unsaved_rows() -> None:
    """Verify manifest update payload omits removed unsaved rows."""
    payload = module.manifest_update_payload(
        {"microcontrollers": 91},
        {"microcontrollers": 90},
    )

    assert payload == {"microcontrollers": 91}


def test_format_manifest_total_includes_free_space_when_available() -> None:
    """Verify format manifest total includes free space when available."""
    assert module.format_manifest_total(3788, 10000) == "Total: 3,788/10,000"


def test_format_manifest_total_hides_missing_or_invalid_free_space() -> None:
    """Verify format manifest total hides missing or invalid free space."""
    assert module.format_manifest_total(3788) == "Total: 3,788"
    assert module.format_manifest_total(3788, None) == "Total: 3,788"
    assert module.format_manifest_total(3788, "unknown") == "Total: 3,788"


def test_linked_fc_options_uses_callsigns_and_disambiguates_duplicates() -> None:
    """Verify linked fc options uses callsigns and disambiguates duplicates."""
    rows = module.linked_fc_options(
        {
            2: {"marketId": 2, "name": "abc-123", "displayName": "Carrier B"},
            1: {"marketId": 1, "name": "abc-123", "displayName": "Carrier A"},
            3: {"marketId": 3, "displayName": "Named Only"},
        }
    )

    assert rows[0][0] == "ABC-123"
    assert rows[1][0] == "ABC-123 (2)"
    assert rows[2][0] == "Named Only"


def test_saved_window_position_reads_valid_config_value() -> None:
    """Verify saved window position reads valid config value."""
    original = config_mod.config

    class Config:
        def get_str(self, key):
            assert key == module.EDITOR_POSITION_CONFIG_KEY
            return "123,456"

    try:
        config_mod.config = Config()
        assert module.FleetCarrierManifestEditor._saved_window_position() == (123, 456)
    finally:
        config_mod.config = original


def test_saved_window_position_ignores_invalid_config_value() -> None:
    """Verify saved window position ignores invalid config value."""
    original = config_mod.config

    class Config:
        def get_str(self, _key):
            return "not,a-position"

    try:
        config_mod.config = Config()
        assert module.FleetCarrierManifestEditor._saved_window_position() is None
    finally:
        config_mod.config = original


def test_manifest_drag_retains_movement_before_window_manager_updates() -> None:
    """Queued pointer events must move from the original position without snapping."""
    bindings: dict[str, object] = {}
    title = SimpleNamespace(bind=lambda event, callback: bindings.update({event: callback}))
    window = SimpleNamespace(winfo_x=lambda: -500, winfo_y=lambda: 200, geometry=Mock())
    editor = module.FleetCarrierManifestEditor(SimpleNamespace())
    editor._window = window
    editor._title_bar = title
    editor._bind_window_drag()

    bindings["<Button-1>"](SimpleNamespace(x_root=-450, y_root=210))
    bindings["<B1-Motion>"](SimpleNamespace(x_root=-450, y_root=210))
    bindings["<B1-Motion>"](SimpleNamespace(x_root=-440, y_root=220))
    bindings["<B1-Motion>"](SimpleNamespace(x_root=-425, y_root=245))
    assert [call.args[0] for call in window.geometry.call_args_list] == [
        "+-500+200", "+-490+210", "+-475+235",
    ]
    with patch.object(editor, "_save_window_position") as save:
        bindings["<ButtonRelease-1>"](SimpleNamespace())
        save.assert_called_once_with(window)
    window.geometry.reset_mock()
    bindings["<B1-Motion>"](SimpleNamespace(x_root=-410, y_root=255))
    window.geometry.assert_not_called()


def test_linux_manifest_removes_native_decorations_and_keeps_management() -> None:
    """The custom manifest title bar must be the only one on an X11 window."""
    window = SimpleNamespace(attributes=Mock(), overrideredirect=Mock())
    with (
        patch.object(sys, "platform", "linux"),
        patch.object(module, "hide_x11_decorations", return_value=True, create=True) as hide,
    ):
        module.FleetCarrierManifestEditor._configure_window_manager_hints(window)
    hide.assert_called_once_with(window)
    window.attributes.assert_called_once_with("-type", "normal")
    window.overrideredirect.assert_not_called()


def test_linux_manifest_remains_borderless_without_x11_hints() -> None:
    """Failure to set X11 hints must not leave a duplicate native title bar."""
    window = SimpleNamespace(attributes=Mock(), overrideredirect=Mock())
    with (
        patch.object(sys, "platform", "linux"),
        patch.object(module, "hide_x11_decorations", return_value=False, create=True),
    ):
        module.FleetCarrierManifestEditor._configure_window_manager_hints(window)
    window.overrideredirect.assert_called_once_with(True)


if __name__ == "__main__":
    test_normalize_manifest_drops_zero_negative_and_invalid_values()
    test_available_commodity_options_excludes_present_manifest_keys()
    test_available_commodity_options_limited_to_manifest_editor_categories()
    test_manifest_update_payload_sends_zero_for_removed_baseline_rows()
    test_manifest_update_payload_omits_removed_unsaved_rows()
    test_format_manifest_total_includes_free_space_when_available()
    test_format_manifest_total_hides_missing_or_invalid_free_space()
    test_linked_fc_options_uses_callsigns_and_disambiguates_duplicates()
    test_saved_window_position_reads_valid_config_value()
    test_saved_window_position_ignores_invalid_config_value()
