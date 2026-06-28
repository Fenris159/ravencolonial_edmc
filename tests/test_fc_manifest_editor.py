"""Tests for Fleet Carrier manifest editor helpers."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


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
    assert module.normalize_manifest(
        {
            "microcontrollers": "32",
            "$evacuationshelter_name;": 0,
            "steel": -1,
            "bad": "x",
        }
    ) == {"microcontrollers": 32}


def test_available_commodity_options_excludes_present_manifest_keys() -> None:
    options = module.available_commodity_options({"microcontrollers": 91})
    keys = {opt.key for opt in options}

    assert "microcontrollers" not in keys
    assert "steel" in keys


def test_available_commodity_options_limited_to_manifest_editor_categories() -> None:
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
    payload = module.manifest_update_payload(
        {"microcontrollers": 91, "steel": 0},
        {"microcontrollers": 90, "steel": 1, "indite": 1},
    )

    assert payload == {"microcontrollers": 91, "steel": 0, "indite": 0}


def test_manifest_update_payload_omits_removed_unsaved_rows() -> None:
    payload = module.manifest_update_payload(
        {"microcontrollers": 91},
        {"microcontrollers": 90},
    )

    assert payload == {"microcontrollers": 91}


def test_format_manifest_total_includes_free_space_when_available() -> None:
    assert module.format_manifest_total(3788, 10000) == "Total: 3,788/10,000"


def test_format_manifest_total_hides_missing_or_invalid_free_space() -> None:
    assert module.format_manifest_total(3788) == "Total: 3,788"
    assert module.format_manifest_total(3788, None) == "Total: 3,788"
    assert module.format_manifest_total(3788, "unknown") == "Total: 3,788"


def test_linked_fc_options_uses_callsigns_and_disambiguates_duplicates() -> None:
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
    original = config_mod.config

    class Config:
        def get_str(self, _key):
            return "not,a-position"

    try:
        config_mod.config = Config()
        assert module.FleetCarrierManifestEditor._saved_window_position() is None
    finally:
        config_mod.config = original


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
