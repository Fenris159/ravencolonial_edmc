"""Unit tests for legacy site marketId repair matching (run: python3 tests/test_market_id_repair.py)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from site_market_id_repair import (  # noqa: E402
    dock_context_skips_market_id_repair,
    market_id_is_player_colony_station,
    market_id_repair_candidates,
    site_name_repair_candidates,
    site_market_id_missing,
    site_market_id_needs_repair,
    site_status_allows_market_id_repair,
)

_SYNUEFAI_SITES = [
    {
        "id": "&4310842115",
        "name": "Gold Enterprise",
        "bodyNum": 36,
        "buildType": "dec_truss",
        "status": "complete",
        "marketId": 4310842115,
    },
    {
        "id": "x1777344410147",
        "name": "Aristotle's Folly",
        "bodyNum": 36,
        "buildType": "silenus",
        "status": "complete",
    },
    {
        "id": "x1777344555521",
        "name": "Saez Synthetics Facility",
        "bodyNum": 36,
        "buildType": "gaea",
        "status": "complete",
    },
    {
        "id": "x1779674929762",
        "name": "Dampier Gateway",
        "bodyNum": 60,
        "buildType": "enodia",
        "status": "build",
        "buildId": "2a61c682-f789-4e6a-b0cc-1b67779c24f3",
    },
]


def test_site_market_id_missing() -> None:
    assert site_market_id_missing(None) is True
    assert site_market_id_missing("") is True
    assert site_market_id_missing(0) is True
    assert site_market_id_missing(4310842115) is False


def test_status_allows_only_complete_or_blank() -> None:
    assert site_status_allows_market_id_repair({"status": "complete"}) is True
    assert site_status_allows_market_id_repair({}) is True
    assert site_status_allows_market_id_repair({"status": "build"}) is False
    assert site_status_allows_market_id_repair({"status": "plan"}) is False


def test_player_colony_market_id_prefixes() -> None:
    assert market_id_is_player_colony_station(4310842115) is True
    assert market_id_is_player_colony_station(3963024386) is True
    assert market_id_is_player_colony_station(3950000001) is True
    assert market_id_is_player_colony_station(4200000001) is True
    assert market_id_is_player_colony_station(128666762) is False
    assert market_id_is_player_colony_station(3710879232) is False


def test_match_by_name_only() -> None:
    matches = market_id_repair_candidates(
        _SYNUEFAI_SITES,
        station_name="Saez Synthetics Facility",
        dock_market_id=4310555555,
    )
    assert len(matches) == 1
    assert matches[0]["name"] == "Saez Synthetics Facility"


def test_repair_when_stored_depot_market_id_differs_from_finished_dock() -> None:
    sites = [
        {
            "id": "x1",
            "name": "Dampier Gateway",
            "bodyNum": 60,
            "status": "complete",
            "marketId": 3963024386,
        },
    ]
    matches = market_id_repair_candidates(
        sites,
        station_name="Dampier Gateway",
        dock_market_id=4310999999,
    )
    assert len(matches) == 1
    assert matches[0]["marketId"] == 3963024386


def test_site_market_id_needs_repair() -> None:
    assert site_market_id_needs_repair(None, 4310842115) is True
    assert site_market_id_needs_repair(3963024386, 4310999999) is True
    assert site_market_id_needs_repair(4310842115, 4310842115) is False


def test_skip_when_market_id_already_present() -> None:
    matches = market_id_repair_candidates(
        _SYNUEFAI_SITES,
        station_name="Gold Enterprise",
        dock_market_id=4310842115,
    )
    assert matches == []


def test_orbital_construction_prefix_normalizes() -> None:
    matches = market_id_repair_candidates(
        _SYNUEFAI_SITES,
        station_name="Orbital Construction Site: Dampier Gateway",
        dock_market_id=3963024386,
    )
    assert matches == []


def test_skip_when_duplicate_normalized_name_in_sites() -> None:
    sites = [
        {
            "id": "a",
            "name": "Duplicate Port",
            "bodyNum": 10,
            "status": "complete",
        },
        {
            "id": "b",
            "name": "Duplicate Port",
            "bodyNum": 20,
            "status": "plan",
        },
    ]
    matches = market_id_repair_candidates(sites, station_name="Duplicate Port")
    assert matches == []


def test_skip_when_duplicate_name_even_if_only_one_eligible() -> None:
    sites = [
        {
            "id": "a",
            "name": "Twin Hub",
            "bodyNum": 10,
            "status": "complete",
            "marketId": 100,
        },
        {
            "id": "b",
            "name": "Twin Hub",
            "bodyNum": 20,
            "status": "complete",
        },
    ]
    matches = market_id_repair_candidates(sites, station_name="Twin Hub")
    assert matches == []


def test_name_repair_when_market_id_matches_but_name_differs() -> None:
    sites = [
        {
            "id": "x1",
            "name": "Generic Outpost",
            "status": "complete",
            "marketId": 4310999999,
        },
    ]
    matches = site_name_repair_candidates(
        sites,
        station_name="Dampier Gateway",
        dock_market_id=4310999999,
    )
    assert len(matches) == 1
    assert matches[0]["id"] == "x1"


def test_name_repair_skips_when_market_id_duplicates() -> None:
    sites = [
        {
            "id": "x1",
            "name": "Generic Outpost",
            "status": "complete",
            "marketId": 4310999999,
        },
        {
            "id": "x2",
            "name": "Other Outpost",
            "status": "complete",
            "marketId": 4310999999,
        },
    ]
    matches = site_name_repair_candidates(
        sites,
        station_name="Dampier Gateway",
        dock_market_id=4310999999,
    )
    assert matches == []


def test_name_repair_skips_when_name_already_matches() -> None:
    sites = [
        {
            "id": "x1",
            "name": "Dampier Gateway",
            "status": "complete",
            "marketId": 4310999999,
        },
    ]
    matches = site_name_repair_candidates(
        sites,
        station_name="Dampier Gateway",
        dock_market_id=4310999999,
    )
    assert matches == []


def test_name_repair_skips_active_rows() -> None:
    sites = [
        {
            "id": "x1",
            "name": "Generic Outpost",
            "status": "build",
            "marketId": 4310999999,
        },
    ]
    matches = site_name_repair_candidates(
        sites,
        station_name="Dampier Gateway",
        dock_market_id=4310999999,
    )
    assert matches == []


def test_dock_context_skips_fleet_carrier() -> None:
    assert dock_context_skips_market_id_repair(
        station_type="FleetCarrier",
        station_name="N4W-T0Z",
    )


def test_dock_context_skips_space_construction_depot() -> None:
    assert dock_context_skips_market_id_repair(
        station_type="SpaceConstructionDepot",
        station_name="Orbital Construction Site: Dampier Gateway",
    )


def test_dock_context_skips_construction_depot_name_without_type() -> None:
    assert dock_context_skips_market_id_repair(
        station_type=None,
        station_name="Planetary Construction Site: Example Base",
    )


def test_dock_context_skips_colonisation_ship() -> None:
    assert dock_context_skips_market_id_repair(
        station_type="SurfaceStation",
        station_name="Some ColonisationShip Pad",
        is_construction_ship=True,
    )


def test_dock_context_allows_completed_player_station() -> None:
    assert not dock_context_skips_market_id_repair(
        station_type="Dodec",
        station_name="Gold Enterprise",
    )


if __name__ == "__main__":
    test_site_market_id_missing()
    test_status_allows_only_complete_or_blank()
    test_player_colony_market_id_prefixes()
    test_match_by_name_only()
    test_repair_when_stored_depot_market_id_differs_from_finished_dock()
    test_site_market_id_needs_repair()
    test_orbital_construction_prefix_normalizes()
    test_skip_when_market_id_already_present()
    test_skip_when_duplicate_normalized_name_in_sites()
    test_skip_when_duplicate_name_even_if_only_one_eligible()
    test_name_repair_when_market_id_matches_but_name_differs()
    test_name_repair_skips_when_market_id_duplicates()
    test_name_repair_skips_when_name_already_matches()
    test_name_repair_skips_active_rows()
    test_dock_context_skips_fleet_carrier()
    test_dock_context_skips_space_construction_depot()
    test_dock_context_skips_construction_depot_name_without_type()
    test_dock_context_skips_colonisation_ship()
    test_dock_context_allows_completed_player_station()
    print("test_market_id_repair: OK")
