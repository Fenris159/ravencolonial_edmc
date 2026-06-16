"""Regression tests for owner fleet-carrier capacity caching."""

from __future__ import annotations

import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PARENT = _ROOT.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

for name in ("timeout_session", "config"):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        if name == "config":
            mod.appname = "test"
        sys.modules[name] = mod

from RavenColonail_EDMC.fleet_carrier_handler import FleetCarrierHandler


def test_carrier_stats_capacity_cache_accepts_carrier_id() -> None:
    handler = FleetCarrierHandler(object())

    handler.update_fc_capacity_from_journal_stats(
        {
            "event": "CarrierStats",
            "CarrierID": 123,
            "Callsign": "N4W-T0Z",
            "SpaceUsage": {
                "TotalCapacity": 25000,
                "FreeSpace": 10000,
            },
        }
    )

    assert handler.get_owner_capacity(123)["freeSpace"] == 10000
    assert handler.get_owner_capacity(123)["callsign"] == "N4W-T0Z"
