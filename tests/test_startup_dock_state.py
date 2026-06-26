"""Regression: plugin dock fields sync from EDMC state at startup."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dock_state_sync import (  # noqa: E402
    apply_plugin_dock_fields_from_edmc_state,
    edmc_state_indicates_docked,
)


def test_edmc_state_indicates_docked_for_fleet_carrier_snapshot() -> None:
    state = {
        "StationType": "FleetCarrier",
        "MarketID": 3710879232,
        "StationName": "N4W-T0Z",
    }

    assert edmc_state_indicates_docked(state) is True


def test_edmc_state_indicates_not_docked_when_explicitly_undocked() -> None:
    state = {
        "Docked": False,
        "StationType": "FleetCarrier",
        "MarketID": 3710879232,
    }

    assert edmc_state_indicates_docked(state) is False


def test_apply_plugin_dock_fields_sets_is_docked_and_refreshes_overlay() -> None:
    refreshes: list[bool] = []
    plugin = SimpleNamespace(
        is_docked=False,
        current_market_id=None,
        station_type=None,
        is_construction_ship=False,
        body_num=None,
        body_name=None,
        star_pos=None,
        update_create_button=lambda: refreshes.append(True),
    )

    applied = apply_plugin_dock_fields_from_edmc_state(
        plugin,
        {
            "StationType": "FleetCarrier",
            "MarketID": 3710879232,
            "StationName": "N4W-T0Z",
        },
        station="N4W-T0Z",
    )

    assert applied is True
    assert plugin.is_docked is True
    assert plugin.current_market_id == 3710879232
    assert plugin.station_type == "FleetCarrier"
    assert refreshes == [True]


def test_apply_plugin_dock_fields_skips_refresh_when_already_at_same_dock() -> None:
    refreshes: list[bool] = []
    plugin = SimpleNamespace(
        is_docked=True,
        current_market_id=3710879232,
        station_type="FleetCarrier",
        is_construction_ship=False,
        body_num=None,
        body_name=None,
        star_pos=None,
        update_create_button=lambda: refreshes.append(True),
    )

    applied = apply_plugin_dock_fields_from_edmc_state(
        plugin,
        {
            "StationType": "FleetCarrier",
            "MarketID": 3710879232,
            "StationName": "N4W-T0Z",
        },
    )

    assert applied is True
    assert refreshes == []