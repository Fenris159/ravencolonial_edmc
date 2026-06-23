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
    assert "evacuationshelter" in keys


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


if __name__ == "__main__":
    test_normalize_manifest_drops_zero_negative_and_invalid_values()
    test_available_commodity_options_excludes_present_manifest_keys()
    test_linked_fc_options_uses_callsigns_and_disambiguates_duplicates()
