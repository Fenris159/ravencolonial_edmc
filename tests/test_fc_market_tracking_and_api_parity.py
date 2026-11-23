"""Tests for dynamic FC link refresh, StartUp dock sync, Market.json sync, and SrvSurvey-XP API parity."""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

for _mod_name in ("timeout_session", "config"):
    if _mod_name not in sys.modules:
        _mod = types.ModuleType(_mod_name)
        if _mod_name == "config":
            _mod.appname = "test"
            _mod.config = SimpleNamespace(get_str=lambda _k, default="": default, get_bool=lambda _k, **_kw: False)
        else:
            _mod.new_session = lambda **_kw: SimpleNamespace(headers={})
        sys.modules[_mod_name] = _mod

from dock_state_sync import edmc_state_indicates_docked  # noqa: E402
from fc_market_sync import (  # noqa: E402
    MarketItemSnapshot,
    compute_fc_market_replacements,
    read_fc_market_snapshot,
)
from overlay.project_cache import apply_project_cache_update, remember_all_projects  # noqa: E402
from plugin_config.settings import PluginConfig  # noqa: E402
from tests.test_carrier_cargo_parity import drain  # noqa: E402


def _write_market_json(
    journal_dir: Path,
    *,
    market_id: int,
    items: list[dict[str, Any]],
    timestamp: str = "2026-11-22T20:10:00Z",
    station_type: str = "FleetCarrier",
) -> None:
    payload = {
        "timestamp": timestamp,
        "event": "Market",
        "MarketID": market_id,
        "StationName": "B6W-34K",
        "StationType": station_type,
        "Items": items,
    }
    (journal_dir / "Market.json").write_text(json.dumps(payload), encoding="utf-8")


def _prepare_plugin(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> tuple[Any, Any]:
    load, plugin = edmc_plugin
    plugin.configure_pending_carrier_deliveries(str(tmp_path))
    monkeypatch.setattr(plugin, "_ensure_api_worker", lambda: None)
    monkeypatch.setattr(plugin.api_client, "publish_current_ship", lambda *_a, **_kw: True)
    return load, plugin


def _drain_threads_and_results(plugin: Any) -> None:
    for thread in list(plugin._fc_initialization_threads):
        thread.join(timeout=2)
    plugin._apply_fc_initialization_results()
    drain(plugin)


def test_default_api_base_matches_srvsurvey_xp_and_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default API base uses ravencolonial.net and normalizes trailing slashes."""
    assert PluginConfig.DEFAULT_API_BASE == "https://ravencolonial.net"
    import config as config_mod

    monkeypatch.setattr(
        config_mod.config,
        "get_str",
        lambda key, default="": " https://ravencolonial.net/ " if key == "ravencolonial_api_url" else default,
        raising=False,
    )
    assert PluginConfig.get_api_base() == "https://ravencolonial.net"

    monkeypatch.setattr(config_mod.config, "get_str", lambda key, default="": "", raising=False)
    assert PluginConfig.get_api_base() == "https://ravencolonial.net"


def test_api_client_trims_base_url_and_api_key_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """API client strips trailing slashes from api_base and whitespace from rcc-key."""
    from RavenColonail_EDMC.api import client as client_mod

    captured: dict[str, Any] = {}

    class _FakeResponse:
        status_code = 200

        @staticmethod
        def raise_for_status() -> None:
            return None

        @staticmethod
        def json() -> dict[str, int]:
            return {"steel": 10}

    def fake_request(_session: Any, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        return _FakeResponse()

    monkeypatch.setattr(client_mod, "_http_request_with_retry", fake_request)
    api = client_mod.RavencolonialAPIClient("https://ravencolonial.net/", "test-ua")
    api.set_credentials(" Rempanda ", "  my-secret-key \n")
    assert api.api_base == "https://ravencolonial.net"
    assert api.cmdr_name == "Rempanda"
    assert api.api_key == "my-secret-key"

    result = api.supply_fc(3714102272, {"steel": -10})
    assert result == {"steel": 10}
    assert captured["url"] == "https://ravencolonial.net/api/fc/3714102272/cargo"
    assert captured["headers"] == {"rcc-key": "my-secret-key"}


def test_compute_fc_market_replacements_matches_srvsurvey_xp_rules() -> None:
    """Partial Market.json diff updates differing Producer stocks and sold-out listings only."""
    items = [
        MarketItemSnapshot("steel", stock=2500, producer=True, consumer=False),
        MarketItemSnapshot("titanium", stock=400, producer=True, consumer=False),
        MarketItemSnapshot("aluminium", stock=0, producer=False, consumer=False),
        MarketItemSnapshot("copper", stock=0, producer=False, consumer=True),
        MarketItemSnapshot("water", stock=0, producer=False, consumer=False),
    ]
    server_cargo = {
        "steel": 0,
        "titanium": 400,
        "aluminium": 120,
        "copper": 80,
        "tritium": 5000,
    }
    replacements = compute_fc_market_replacements(items, server_cargo)
    assert replacements == {"steel": 2500, "aluminium": 0}


def test_read_fc_market_snapshot_validates_market_id_and_station_type(tmp_path: Path) -> None:
    """Market.json reader ignores mismatched MarketID or non-carrier stations."""
    _write_market_json(
        tmp_path,
        market_id=3714102272,
        items=[{"Name": "$Steel_name;", "Stock": 1200, "Producer": True, "Consumer": False}],
    )
    snap = read_fc_market_snapshot({"MarketID": 3714102272, "StationType": "FleetCarrier"}, str(tmp_path))
    assert snap is not None
    assert snap.market_id == 3714102272
    assert snap.items == (MarketItemSnapshot("steel", 1200, True, False),)

    assert read_fc_market_snapshot({"MarketID": 9999, "StationType": "FleetCarrier"}, str(tmp_path)) is None

    _write_market_json(
        tmp_path,
        market_id=3714102272,
        station_type="Coriolis",
        items=[{"Name": "$Steel_name;", "Stock": 1200, "Producer": True, "Consumer": False}],
    )
    assert read_fc_market_snapshot({"MarketID": 3714102272, "StationType": "FleetCarrier"}, str(tmp_path)) is None


def test_overlay_project_fetch_registers_newly_linked_other_cmdr_carrier(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Carriers discovered via overlay project fetches immediately become update-eligible."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    writes: list[tuple[int, dict[str, int]]] = []
    remote: Dict[int, Dict[str, int]] = {101: {"steel": 500}, 202: {"steel": 1000}}

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 101, "name": "OWN-101", "cargo": dict(remote[101])},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})

    def fake_supply(mid: int, diff: dict[str, int]) -> dict[str, int]:
        writes.append((mid, dict(diff)))
        for k, v in diff.items():
            remote[mid][k] = max(0, remote[mid].get(k, 0) + v)
        return dict(remote[mid])

    monkeypatch.setattr(plugin.api_client, "supply_fc", fake_supply)
    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)
    assert plugin.fc_handler.is_update_eligible_fc(202) is False

    project = {
        "buildId": "build-cerobi",
        "buildName": "Cerobi City",
        "commodities": {"steel": 2000},
        "linkedFC": [{"marketId": 202, "name": "B6W-34K", "displayName": "PANDA BEAR"}],
    }
    remember_all_projects(plugin, [project], authoritative_projects=[project])
    assert plugin.fc_handler.is_update_eligible_fc(202) is True

    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 202},
        {"StationType": "FleetCarrier", "MarketID": 202, "IsDocked": True, "ShipType": "type9"},
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:05Z", "MarketID": 202, "Type": "steel", "Count": 64},
        {"StationType": "FleetCarrier", "MarketID": 202, "IsDocked": True, "ShipType": "type9"},
    )
    drain(plugin)
    assert writes == [(202, {"steel": -64})]
    assert remote[202] == {"steel": 936}

    plugin.selected_overlay_build_id = "build-2"
    apply_project_cache_update(
        plugin,
        "build-2",
        project_view={
            "buildId": "build-2",
            "linkedFC": [{"marketId": 303, "name": "B6W-31J", "displayName": "SUN BEAR"}],
        },
    )
    assert plugin.fc_handler.is_update_eligible_fc(303) is True


def test_docking_at_newly_linked_carrier_refreshes_links_and_releases_deferred_buy(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Docking at an unknown FC refreshes links in background and preserves in-flight MarketBuy."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    remote: Dict[int, Dict[str, int]] = {101: {"steel": 500}, 303: {"steel": 2000}}
    writes: list[tuple[int, dict[str, int]]] = []
    projects_state: list[dict[str, Any]] = []
    refresh_gate = threading.Event()
    refresh_started = threading.Event()
    calls = 0

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 101, "name": "OWN-101", "cargo": dict(remote[101])},
    ])

    def fake_projects(_cmdr: str) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls >= 2:
            refresh_started.set()
            refresh_gate.wait(timeout=2)
        return list(projects_state)

    def fake_supply(mid: int, diff: dict[str, int]) -> dict[str, int]:
        writes.append((mid, dict(diff)))
        for k, v in diff.items():
            remote[mid][k] = max(0, remote[mid].get(k, 0) + v)
        return dict(remote[mid])

    monkeypatch.setattr(plugin.api_client, "get_commander_projects", fake_projects)
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "supply_fc", fake_supply)

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)
    assert plugin.fc_handler.is_update_eligible_fc(303) is False

    # Carrier 303 is now linked to an active project while EDMC is already running.
    projects_state.append({
        "buildId": "build-cerobi",
        "linkedFC": [{"marketId": 303, "name": "B6W-31J", "displayName": "SUN BEAR"}],
    })
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-31J",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-31J", "MarketID": 303},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    assert refresh_started.wait(timeout=2)

    # Buy happens while link refresh is still in flight.
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-31J",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:05Z", "MarketID": 303, "Type": "steel", "Count": 50},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    assert writes == []

    refresh_gate.set()
    _drain_threads_and_results(plugin)
    assert plugin.fc_handler.is_update_eligible_fc(303) is True
    assert writes == [(303, {"steel": -50})]
    assert remote[303] == {"steel": 1950}

    # Cooldown prevents spamming refreshes for a genuinely unlinked carrier.
    before_calls = calls
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "UNL-999",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "UNL-999", "MarketID": 999},
        {"StationType": "FleetCarrier", "MarketID": 999, "IsDocked": True, "ShipType": "type9"},
    )
    _drain_threads_and_results(plugin)
    assert calls == before_calls + 1
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "UNL-999",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "UNL-999", "MarketID": 999},
        {"StationType": "FleetCarrier", "MarketID": 999, "IsDocked": True, "ShipType": "type9"},
    )
    _drain_threads_and_results(plugin)
    assert calls == before_calls + 1


def test_startup_event_after_init_restores_fc_dock_context_and_tracks_buy(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """EDMC StartUp restores FleetCarrier dock context even after handler initialization."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    writes: list[tuple[int, dict[str, int]]] = []
    remote: Dict[int, Dict[str, int]] = {101: {"steel": 500}}

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 101, "name": "OWN-101", "cargo": dict(remote[101])},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(
        plugin.api_client,
        "supply_fc",
        lambda mid, diff: (writes.append((mid, dict(diff))), {"steel": 460})[1],
    )

    # Initial event while undocked.
    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9", "IsDocked": False})
    _drain_threads_and_results(plugin)
    assert plugin.fc_handler.current_station_type is None

    # Game restarted while docked at FC -> EDMC emits StartUp while fc_handler is already initialized.
    load.journal_entry(
        "Rempanda", False, "Sol", "OWN-101",
        {"event": "StartUp", "Docked": True, "StationType": "FleetCarrier", "StationName": "OWN-101", "MarketID": 101},
        {"StationType": "FleetCarrier", "MarketID": 101, "IsDocked": True, "ShipType": "type9"},
    )
    assert plugin.fc_handler.current_station_type == "FleetCarrier"
    assert plugin.fc_handler.current_market_id == 101

    load.journal_entry(
        "Rempanda", False, "Sol", "OWN-101",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:05Z", "MarketID": 101, "Type": "steel", "Count": 40},
        {"StationType": "FleetCarrier", "MarketID": 101, "IsDocked": True, "ShipType": "type9"},
    )
    drain(plugin)
    assert writes == [(101, {"steel": -40})]

    # StartUp with Docked=False clears dock context.
    load.journal_entry(
        "Rempanda", False, "Sol", "",
        {"event": "StartUp", "Docked": False},
        {"IsDocked": False, "ShipType": "type9"},
    )
    assert plugin.fc_handler.current_station_type is None
    assert plugin.fc_handler.current_market_id is None


def test_edmc_state_is_docked_false_overrides_stale_station_fields() -> None:
    """EDMC state IsDocked=False is respected just like Docked=False."""
    assert edmc_state_indicates_docked({"IsDocked": False, "StationType": "FleetCarrier", "MarketID": 101}) is False
    assert edmc_state_indicates_docked({"IsDocked": True, "StationType": "FleetCarrier", "MarketID": 101}) is True


def test_market_event_syncs_other_cmdr_carrier_stock_before_buy_and_preserves_unlisted(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Market event POSTs only differing Producer stocks so subsequent MarketBuy decrements live stock."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load.config, "default_journal_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 0, "tritium": 4000}}
    posts: list[tuple[int, dict[str, int]]] = []
    patches: list[tuple[int, dict[str, int]]] = []

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 303, "name": "B6W-34K", "cargo": dict(remote[303])},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})

    def fake_post(mid: int, cargo: dict[str, int]) -> dict[str, int]:
        posts.append((mid, dict(cargo)))
        remote[mid].update(cargo)
        return dict(remote[mid])

    def fake_patch(mid: int, diff: dict[str, int]) -> dict[str, int]:
        patches.append((mid, dict(diff)))
        for k, v in diff.items():
            remote[mid][k] = max(0, remote[mid].get(k, 0) + v)
        return dict(remote[mid])

    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", fake_post)
    monkeypatch.setattr(plugin.api_client, "supply_fc", fake_patch)

    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    _drain_threads_and_results(plugin)

    _write_market_json(
        tmp_path,
        market_id=303,
        timestamp="2026-11-22T20:10:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 2500, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    drain(plugin)

    # POST only sends differing market key, preserving unlisted tritium.
    assert posts == [(303, {"steel": 2500})]
    assert remote[303] == {"steel": 2500, "tritium": 4000}

    # Repeat Market event with same timestamp is deduplicated.
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    drain(plugin)
    assert len(posts) == 1

    # Buying now decrements from the synced 2500 stock.
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:05Z", "MarketID": 303, "Type": "steel", "Count": 784},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    drain(plugin)
    assert patches == [(303, {"steel": -784})]
    assert remote[303] == {"steel": 1716, "tritium": 4000}


def test_market_sync_skips_when_pending_writes_exist(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Market.json sync does not overwrite a carrier while unacknowledged deliveries are pending."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))
    posts: list[Any] = []
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 303, "name": "B6W-34K", "cargo": {"steel": 100}},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": {"steel": 100}})
    monkeypatch.setattr(plugin.api_client, "supply_fc", lambda _mid, _diff: None)
    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", lambda mid, cargo: posts.append((mid, cargo)))

    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    _drain_threads_and_results(plugin)

    # Record a pending unacknowledged delivery for 303.
    plugin.pending_carrier_deliveries.record("Rempanda", 303, {"steel": -50})
    _write_market_json(
        tmp_path,
        market_id=303,
        items=[{"Name": "$Steel_name;", "Stock": 2500, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    drain(plugin)
    assert posts == []


def test_prefs_save_trims_api_key_flushes_pending_deliveries_and_clears_when_emptied(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Saving a trimmed API key immediately flushes retained deliveries; emptying clears credentials."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    writes: list[tuple[int, dict[str, int]]] = []
    saved_cfg: dict[str, Any] = {"ravencolonial_api_key": ""}
    monkeypatch.setattr(load.config, "get_str", lambda key, default="": saved_cfg.get(key, default), raising=False)
    monkeypatch.setattr(load.config, "set", lambda key, val: saved_cfg.__setitem__(key, val), raising=False)
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 101, "name": "OWN-101", "cargo": {"steel": 500}},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": {"steel": 500}})
    monkeypatch.setattr(
        plugin.api_client,
        "supply_fc",
        lambda mid, diff: (writes.append((mid, dict(diff))), {"steel": 450})[1],
    )

    # Start with no API key: trade is retained for recovery.
    load.journal_entry(
        "Rempanda", False, "Sol", "OWN-101",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "OWN-101", "MarketID": 101},
        {"StationType": "FleetCarrier", "MarketID": 101, "IsDocked": True, "ShipType": "type9"},
    )
    _drain_threads_and_results(plugin)
    load.journal_entry(
        "Rempanda", False, "Sol", "OWN-101",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:05Z", "MarketID": 101, "Type": "steel", "Count": 50},
        {"StationType": "FleetCarrier", "MarketID": 101, "IsDocked": True, "ShipType": "type9"},
    )
    drain(plugin)
    assert writes == []

    # Simulate user pasting API key with surrounding whitespace in Settings and saving.
    plugin.fc_handler._next_delivery_recovery = time.monotonic() + 3600
    api_val = ["  trimmed-key \n"]
    frame = SimpleNamespace(
        api_key_var=SimpleNamespace(get=lambda: api_val[0], set=lambda v: api_val.__setitem__(0, v)),
        stealth_var=SimpleNamespace(get=lambda: False),
        stealth_ship_cargo_var=SimpleNamespace(get=lambda: False),
        stealth_construction_var=SimpleNamespace(get=lambda: False),
        overlay_theme_combo=SimpleNamespace(get=lambda: "Elite Orange"),
        _theme_display_to_id={"Elite Orange": "elite_orange"},
        overlay_theme_var=SimpleNamespace(get=lambda: "elite_orange", set=lambda _v: None),
        overlay_format_combo=SimpleNamespace(get=lambda: "Breakdown"),
        _format_display_to_id={"Breakdown": "breakdown"},
        row_highlight_opacity_var=SimpleNamespace(get=lambda: 8),
        check_updates_var=SimpleNamespace(get=lambda: True),
        autoupdate_var=SimpleNamespace(get=lambda: False),
        prerelease_var=SimpleNamespace(get=lambda: False),
    )
    load._persist_ravencolonial_prefs_from_frame(frame, "Rempanda")
    drain(plugin)

    assert api_val[0] == "trimmed-key"
    assert plugin.api_client.api_key == "trimmed-key"
    assert writes == [(101, {"steel": -50})]

    # Clearing API key clears in-memory credentials too.
    api_val[0] = "   "
    load._persist_ravencolonial_prefs_from_frame(frame, "Rempanda")
    assert plugin.api_client.api_key == ""


def test_skipped_fc_market_buy_logs_clear_reason(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    """Skipping a MarketBuy at an unlinked FC emits a diagnostic info log."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    # First dock triggers and completes refresh for 999 (still unlinked); cooldown active afterwards.
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "UNL-999",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "UNL-999", "MarketID": 999},
        {"StationType": "FleetCarrier", "MarketID": 999, "IsDocked": True, "ShipType": "type9"},
    )
    _drain_threads_and_results(plugin)

    with caplog.at_level(logging.INFO):
        load.journal_entry(
            "Rempanda", False, "Mynoaw", "UNL-999",
            {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:05Z", "MarketID": 999, "Type": "steel", "Count": 10},
            {"StationType": "FleetCarrier", "MarketID": 999, "IsDocked": True, "ShipType": "type9"},
        )

    assert any("Skipping FC MarketBuy for marketId=999" in rec.message for rec in caplog.records)


def test_quick_market_buy_after_market_event_runs_after_market_sync_funds_it(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Buying before api_queue drains does not block the earlier Market.json POST that funds the withdrawal."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load.config, "default_journal_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 0}}
    events_log: list[tuple[str, int, dict[str, int]]] = []

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 303, "name": "B6W-34K", "cargo": dict(remote[303])},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})

    def fake_post(mid: int, cargo: dict[str, int]) -> dict[str, int]:
        events_log.append(("POST", mid, dict(cargo)))
        remote[mid].update(cargo)
        return dict(remote[mid])

    def fake_patch(mid: int, diff: dict[str, int]) -> dict[str, int]:
        events_log.append(("PATCH", mid, dict(diff)))
        for k, v in diff.items():
            remote[mid][k] = max(0, remote[mid].get(k, 0) + v)
        return dict(remote[mid])

    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", fake_post)
    monkeypatch.setattr(plugin.api_client, "supply_fc", fake_patch)

    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    _drain_threads_and_results(plugin)

    _write_market_json(
        tmp_path,
        market_id=303,
        timestamp="2026-11-22T20:10:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 2500, "Producer": True, "Consumer": False}],
    )
    # Queue both Market and MarketBuy before draining the API worker.
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:02Z", "MarketID": 303, "Type": "steel", "Count": 784},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    drain(plugin)

    assert events_log == [("POST", 303, {"steel": 2500}), ("PATCH", 303, {"steel": -784})]
    assert remote[303] == {"steel": 1716}


def test_queued_market_snapshot_does_not_undo_newer_acknowledged_manual_save(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A queued Market.json snapshot skips POST if a newer acknowledged write happened first."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 60}}
    posts: list[tuple[int, dict[str, int]]] = []
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 303, "name": "B6W-34K", "cargo": {"steel": 100}},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", lambda mid, cargo: posts.append((mid, dict(cargo))))

    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    _drain_threads_and_results(plugin)

    _write_market_json(
        tmp_path,
        market_id=303,
        timestamp="2026-11-22T20:10:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 100, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )

    # Separate manifest editor worker prepares and saves a manual correction to 60 before api_queue drains.
    prepared = plugin.fc_handler.prepare_manual_manifest(303, {"steel": 60})
    monkeypatch.setattr(
        plugin.api_client,
        "update_fc_cargo",
        lambda mid, cargo: (posts.append((mid, dict(cargo))), remote.__setitem__(mid, dict(cargo)), dict(cargo))[2],
    )
    assert plugin.fc_handler.save_manual_manifest(303, {"steel": 60}, prepared) == {"steel": 60}
    posts.clear()
    drain(plugin)
    assert posts == []
    assert remote[303] == {"steel": 60}


def test_link_refresh_does_not_promote_optimistic_delta_on_project_only_carrier(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Link refresh must not confirm an unacknowledged optimistic local delta on a project-linked carrier."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [
        {"buildId": "b1", "linkedFC": [{"marketId": 202, "name": "B6W-34K"}]},
    ])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": {"steel": 100}})

    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 202},
        {"StationType": "FleetCarrier", "MarketID": 202, "IsDocked": True, "ShipType": "type9"},
    )
    _drain_threads_and_results(plugin)
    assert plugin.pending_carrier_deliveries.cargo_for_display(202, {}) == {"steel": 100}

    # Queue an optimistic sale of +20 (unacknowledged; api_queue not drained yet).
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "MarketSell", "timestamp": "2026-11-22T20:10:05Z", "MarketID": 202, "Type": "steel", "Count": 20},
        {"StationType": "FleetCarrier", "MarketID": 202, "IsDocked": True, "ShipType": "type9"},
    )
    assert plugin.fc_handler.linked_fcs[202]["cargo"] == {"steel": 120}

    # Run a link refresh returning 202 only as active-project metadata (no cargo manifest in all_fcs).
    plugin.fc_handler.finish_link_refresh(
        "Rempanda",
        [],
        {202: {"marketId": 202, "name": "B6W-34K", "cargo": {}, "cargoSource": "active_project_linked_fc"}},
        read_revision=plugin.fc_handler.cargo_read_revision(),
    )
    assert plugin.pending_carrier_deliveries.cargo_for_display(202, {}) == {"steel": 100}
    assert plugin.fc_handler._acknowledged_fc_cargo[202] == {"steel": 100}


def test_link_refresh_preserves_newer_overlay_registration_while_inflight(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An older in-flight link refresh does not wipe out a newer overlay registration discovered mid-flight."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    refresh_started = threading.Event()
    refresh_gate = threading.Event()
    calls = 0

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 101, "name": "OWN-101", "cargo": {"steel": 500}},
    ])

    def fake_projects(_cmdr: str) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls >= 2:
            refresh_started.set()
            refresh_gate.wait(timeout=2)
        return []

    monkeypatch.setattr(plugin.api_client, "get_commander_projects", fake_projects)

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    # Start link refresh #2 (will return [] without 505).
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "UNL-999",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "UNL-999", "MarketID": 999},
        {"StationType": "FleetCarrier", "MarketID": 999, "IsDocked": True, "ShipType": "type9"},
    )
    assert refresh_started.wait(timeout=2)

    # While refresh #2 is in flight, a newer fresh overlay fetch discovers 505.
    project = {"buildId": "overlay-only", "linkedFC": [{"marketId": 505, "name": "OVL-505"}]}
    remember_all_projects(plugin, [project], authoritative_projects=[project])
    assert plugin.fc_handler.is_update_eligible_fc(505) is True

    refresh_gate.set()
    _drain_threads_and_results(plugin)
    assert plugin.fc_handler.is_update_eligible_fc(505) is True


def test_second_carrier_refresh_does_not_lose_buffered_trade_when_first_finishes(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Docking a second unknown carrier during an active refresh triggers a follow-up without dropping its trade."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    remote: Dict[int, Dict[str, int]] = {303: {"steel": 1000}, 404: {"steel": 1000}}
    writes: list[tuple[int, dict[str, int]]] = []
    first_started = threading.Event()
    first_gate = threading.Event()
    call_count = 0

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])

    def fake_projects(_cmdr: str) -> list[dict[str, Any]]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return []
        if call_count == 2:
            first_started.set()
            first_gate.wait(timeout=2)
            return [{"buildId": "b1", "linkedFC": [{"marketId": 303, "name": "AAA-303"}]}]
        return [{
            "buildId": "b1",
            "linkedFC": [{"marketId": 303, "name": "AAA-303"}, {"marketId": 404, "name": "BBB-404"}],
        }]

    def fake_supply(mid: int, diff: dict[str, int]) -> dict[str, int]:
        writes.append((mid, dict(diff)))
        for k, v in diff.items():
            remote[mid][k] = max(0, remote[mid].get(k, 0) + v)
        return dict(remote[mid])

    monkeypatch.setattr(plugin.api_client, "get_commander_projects", fake_projects)
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "supply_fc", fake_supply)

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    # Dock at 303 -> starts refresh #1 (blocked on first_gate).
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "AAA-303",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "AAA-303", "MarketID": 303},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    assert first_started.wait(timeout=2)

    # While refresh #1 is in flight, dock at 404 and buy 25 steel.
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "BBB-404",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "BBB-404", "MarketID": 404},
        {"StationType": "FleetCarrier", "MarketID": 404, "IsDocked": True, "ShipType": "type9"},
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "BBB-404",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:05Z", "MarketID": 404, "Type": "steel", "Count": 25},
        {"StationType": "FleetCarrier", "MarketID": 404, "IsDocked": True, "ShipType": "type9"},
    )

    first_gate.set()
    _drain_threads_and_results(plugin)
    # Follow-up refresh #2 was spawned by finish_link_refresh; join and drain it too.
    _drain_threads_and_results(plugin)

    assert plugin.fc_handler.is_update_eligible_fc(404) is True
    assert writes == [(404, {"steel": -25})]


def test_deferred_market_event_retains_snapshot_and_validates_timestamp(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Market.json timestamp is validated against the Market event and retained across link-refresh deferral."""
    _write_market_json(
        tmp_path,
        market_id=303,
        timestamp="2026-11-22T20:10:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 2500, "Producer": True, "Consumer": False}],
    )
    assert read_fc_market_snapshot(
        {"MarketID": 303, "StationType": "FleetCarrier", "timestamp": "2026-11-22T20:15:00Z"},
        str(tmp_path),
    ) is None

    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))
    remote: Dict[int, Dict[str, int]] = {303: {"steel": 0}}
    posts: list[tuple[int, dict[str, int]]] = []
    refresh_started = threading.Event()
    refresh_gate = threading.Event()
    calls = 0

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])

    def fake_projects(_cmdr: str) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        refresh_started.set()
        refresh_gate.wait(timeout=2)
        return [{"buildId": "b1", "linkedFC": [{"marketId": 303, "name": "B6W-34K"}]}]

    monkeypatch.setattr(plugin.api_client, "get_commander_projects", fake_projects)
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(
        plugin.api_client,
        "update_fc_cargo",
        lambda mid, cargo: (posts.append((mid, dict(cargo))), remote[mid].update(cargo), dict(remote[mid]))[2],
    )

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    assert refresh_started.wait(timeout=2)

    # Market event arrives during in-flight link refresh; snapshot at T1 (2500) must be captured now.
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )

    # Overwrite Market.json on disk with a different opening before the refresh finishes.
    _write_market_json(
        tmp_path,
        market_id=303,
        timestamp="2026-11-22T20:11:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 900, "Producer": True, "Consumer": False}],
    )

    refresh_gate.set()
    _drain_threads_and_results(plugin)
    assert posts == [(303, {"steel": 2500})]


def test_market_sync_blocked_when_held_inventory_frame_exists(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Market.json sync is blocked when a squadron-bank inventory frame is already held (no double-counting)."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {}}
    posts: list[tuple[int, dict[str, int]]] = []
    patches: list[tuple[int, dict[str, int]]] = []
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 303, "name": "B6W-34K", "cargo": {}},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(
        plugin.api_client,
        "update_fc_cargo",
        lambda mid, cargo: (posts.append((mid, dict(cargo))), remote[mid].update(cargo), dict(remote[mid]))[2],
    )
    monkeypatch.setattr(
        plugin.api_client,
        "supply_fc",
        lambda mid, diff: (patches.append((mid, dict(diff))), dict(remote[mid]))[1],
    )

    state = {
        "StationType": "FleetCarrier",
        "MarketID": 303,
        "IsDocked": True,
        "ShipType": "type9",
        "Cargo": {},
    }
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {
            "event": "Docked",
            "StationType": "FleetCarrier",
            "StationName": "B6W-34K",
            "MarketID": 303,
            "StationServices": ["commodities", "squadronbank"],
        },
        state,
    )
    _drain_threads_and_results(plugin)

    # Create an unfunded squadron-bank withdrawal frame (ship gained 10 steel while Raven stock is 0).
    plugin.pending_carrier_deliveries.checkpoint_inventory(
        "Rempanda", 303, {}, {"before": {}, "cargo": {"steel": 10}, "inventory_time": time.time()},
    )
    assert len(plugin.pending_carrier_deliveries.inventory_frames(market_id=303)) == 1

    # Market.json now reports post-withdrawal stock 490; must not POST 490 or double-count the held -10.
    _write_market_json(
        tmp_path,
        market_id=303,
        timestamp="2026-11-22T20:10:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 490, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )
    drain(plugin)
    assert posts == []
    assert patches == []


def test_failed_market_post_retains_partial_recovery_barrier_and_blocks_later_buy(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Failed Market.json POST checkpoints a partial barrier that holds later buys until recovered."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 100, "tritium": 4000}}
    fail_post = [True]
    events_log: list[tuple[str, int, dict[str, int]]] = []

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 303, "name": "B6W-34K", "cargo": dict(remote[303])},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})

    def fake_post(mid: int, cargo: dict[str, int]) -> Any:
        events_log.append(("POST", mid, dict(cargo)))
        if fail_post[0]:
            plugin.api_client._fc_supply_failure.unsent = True
            return None
        plugin.api_client._fc_supply_failure.unsent = False
        remote[mid].update(cargo)
        return dict(remote[mid])

    def fake_patch(mid: int, diff: dict[str, int]) -> dict[str, int]:
        events_log.append(("PATCH", mid, dict(diff)))
        for k, v in diff.items():
            remote[mid][k] = max(0, remote[mid].get(k, 0) + v)
        return dict(remote[mid])

    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", fake_post)
    monkeypatch.setattr(plugin.api_client, "supply_fc", fake_patch)

    state = {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"}
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        state,
    )
    _drain_threads_and_results(plugin)

    _write_market_json(
        tmp_path,
        market_id=303,
        timestamp="2026-11-22T20:10:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 200, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:02Z", "MarketID": 303, "Type": "steel", "Count": 10},
        state,
    )
    drain(plugin)

    # First POST failed -> partial replacement barrier held MarketBuy (did not PATCH against old 100!).
    assert events_log == [("POST", 303, {"steel": 200})]
    assert remote[303] == {"steel": 100, "tritium": 4000}
    assert len(plugin.pending_carrier_deliveries.replacements(market_id=303)) == 1
    assert plugin.pending_carrier_deliveries.replacements(market_id=303)[0]["partial"] is True

    # Recovery retries partial POST (preserving unlisted tritium), then replays MarketBuy(-10) -> 190.
    fail_post[0] = False
    plugin.fc_handler.retry_pending_deliveries()
    drain(plugin)
    assert events_log == [
        ("POST", 303, {"steel": 200}),
        ("POST", 303, {"steel": 200}),
        ("PATCH", 303, {"steel": -10}),
    ]
    assert remote[303] == {"steel": 190, "tritium": 4000}
    assert plugin.pending_carrier_deliveries.replacements(market_id=303) == []
    assert plugin.pending_carrier_deliveries.records(market_id=303) == []


def test_market_sync_records_observation_protecting_against_older_capi_across_restart(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Market.json sync records persisted cargo_observed_at so older CAPI cannot overwrite it after undock/restart."""
    from RavenColonail_EDMC.pending_carrier_deliveries import PendingCarrierDeliveries

    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 0}}
    posts: list[tuple[int, dict[str, int]]] = []
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 303, "name": "B6W-34K", "cargo": dict(remote[303])},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(
        plugin.api_client,
        "update_fc_cargo",
        lambda mid, cargo: (posts.append((mid, dict(cargo))), remote[mid].update(cargo), dict(remote[mid]))[2],
    )

    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    _drain_threads_and_results(plugin)

    _write_market_json(
        tmp_path,
        market_id=303,
        timestamp="2026-11-22T20:10:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 500, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    drain(plugin)
    assert remote[303] == {"steel": 500}
    observed_at = plugin.pending_carrier_deliveries.cargo_observed_at(303)
    assert observed_at is not None

    # Undock and feed a delayed older owner CAPI snapshot (steel=0): must be rejected.
    posts.clear()
    load.journal_entry("Rempanda", False, "Mynoaw", "", {"event": "Undocked"}, {"IsDocked": False, "ShipType": "type9"})
    plugin.fc_handler.update_fc_cargo_from_capi(303, {}, capi_timestamp=observed_at - 60.0, was_docked=False)
    drain(plugin)
    assert posts == []
    assert remote[303] == {"steel": 500}

    # Verify observation timestamp persisted across restart.
    reloaded = PendingCarrierDeliveries()
    reloaded.configure(str(tmp_path))
    assert reloaded.cargo_observed_at(303) == pytest.approx(observed_at)


def test_backlogged_fifo_market_snapshots_and_prior_buy_do_not_supersede_later_market(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Earlier FIFO Market/PATCH completions do not falsely supersede later queued Market observations."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 50}}
    events_log: list[tuple[str, int, dict[str, int]]] = []
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 303, "name": "B6W-34K", "cargo": dict(remote[303])},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})

    def fake_post(mid: int, cargo: dict[str, int]) -> dict[str, int]:
        events_log.append(("POST", mid, dict(cargo)))
        remote[mid].update(cargo)
        return dict(remote[mid])

    def fake_patch(mid: int, diff: dict[str, int]) -> dict[str, int]:
        events_log.append(("PATCH", mid, dict(diff)))
        for k, v in diff.items():
            remote[mid][k] = max(0, remote[mid].get(k, 0) + v)
        return dict(remote[mid])

    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", fake_post)
    monkeypatch.setattr(plugin.api_client, "supply_fc", fake_patch)

    state = {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"}
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        state,
    )
    _drain_threads_and_results(plugin)

    # Queue Market(100), then Market(200), then MarketBuy(-10), then Market(250) before draining worker.
    _write_market_json(
        tmp_path, market_id=303, timestamp="2026-11-22T20:10:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 100, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )
    _write_market_json(
        tmp_path, market_id=303, timestamp="2026-11-22T20:11:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 200, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:11:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:11:10Z", "MarketID": 303, "Type": "steel", "Count": 10},
        state,
    )
    _write_market_json(
        tmp_path, market_id=303, timestamp="2026-11-22T20:12:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 250, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:12:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )
    drain(plugin)

    assert events_log == [
        ("POST", 303, {"steel": 100}),
        ("POST", 303, {"steel": 200}),
        ("PATCH", 303, {"steel": -10}),
        ("POST", 303, {"steel": 250}),
    ]
    assert remote[303] == {"steel": 250}


def test_deferred_buy_before_market_during_link_refresh_blocks_market_overtake(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A purchase deferred during link refresh records its ID so a subsequent Market(90) cannot overtake -10."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 100}}
    events_log: list[tuple[str, int, dict[str, int]]] = []
    refresh_started = threading.Event()
    refresh_gate = threading.Event()
    calls = 0

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])

    def fake_projects(_cmdr: str) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        refresh_started.set()
        refresh_gate.wait(timeout=2)
        return [{"buildId": "b1", "linkedFC": [{"marketId": 303, "name": "B6W-34K"}]}]

    def fake_post(mid: int, cargo: dict[str, int]) -> dict[str, int]:
        events_log.append(("POST", mid, dict(cargo)))
        remote[mid].update(cargo)
        return dict(remote[mid])

    def fake_patch(mid: int, diff: dict[str, int]) -> dict[str, int]:
        events_log.append(("PATCH", mid, dict(diff)))
        for k, v in diff.items():
            remote[mid][k] = max(0, remote[mid].get(k, 0) + v)
        return dict(remote[mid])

    monkeypatch.setattr(plugin.api_client, "get_commander_projects", fake_projects)
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", fake_post)
    monkeypatch.setattr(plugin.api_client, "supply_fc", fake_patch)

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    state = {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"}
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        state,
    )
    assert refresh_started.wait(timeout=2)

    # Buy -10 arrives first, then Market reports the post-buy stock 90 while Raven is still at 100.
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:05Z", "MarketID": 303, "Type": "steel", "Count": 10},
        state,
    )
    _write_market_json(
        tmp_path, market_id=303, timestamp="2026-11-22T20:10:06Z",
        items=[{"Name": "$Steel_name;", "Stock": 90, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:06Z", "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )

    refresh_gate.set()
    _drain_threads_and_results(plugin)
    assert events_log == [("PATCH", 303, {"steel": -10})]
    assert remote[303] == {"steel": 90}


def test_failed_link_refresh_and_commander_switch_preserve_deferred_trade(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Transient link-refresh failures and commander switches do not lose deferred trades."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    remote: Dict[int, Dict[str, int]] = {303: {"steel": 500}, 404: {"steel": 500}}
    writes: list[tuple[int, dict[str, int]]] = []
    phase = ["fail"]
    fail_started = threading.Event()
    fail_gate = threading.Event()
    second_started = threading.Event()
    second_gate = threading.Event()

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])

    def fake_projects(cmdr: str) -> list[dict[str, Any]]:
        if cmdr == "OtherCmdr":
            return []
        if phase[0] == "init":
            return []
        if phase[0] == "fail":
            fail_started.set()
            fail_gate.wait(timeout=2)
            raise ValueError("transient 503")
        if phase[0] == "switch":
            second_started.set()
            second_gate.wait(timeout=2)
            return [{"buildId": "b2", "linkedFC": [{"marketId": 404, "name": "SWI-404"}]}]
        return [{"buildId": "b1", "linkedFC": [{"marketId": 303, "name": "B6W-34K"}]}]

    def fake_supply(mid: int, diff: dict[str, int]) -> dict[str, int]:
        writes.append((mid, dict(diff)))
        for k, v in diff.items():
            remote[mid][k] = max(0, remote[mid].get(k, 0) + v)
        return dict(remote[mid])

    monkeypatch.setattr(plugin.api_client, "get_commander_projects", fake_projects)
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "supply_fc", fake_supply)

    phase[0] = "init"
    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    # Part A: Refresh fails while buy is deferred -> buy is retained and delivered on retry.
    phase[0] = "fail"
    state_303 = {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"}
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        state_303,
    )
    assert fail_started.wait(timeout=2)
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:05Z", "MarketID": 303, "Type": "steel", "Count": 30},
        state_303,
    )
    fail_gate.set()
    _drain_threads_and_results(plugin)
    assert writes == []
    assert len(plugin.pending_carrier_deliveries.records("Rempanda", 303)) == 1

    phase[0] = "ok"
    plugin.fc_handler._next_link_refresh_retry = 0.0
    plugin.fc_handler.retry_pending_deliveries()
    _drain_threads_and_results(plugin)
    assert writes == [(303, {"steel": -30})]
    assert remote[303] == {"steel": 470}

    # Part B: Commander switches while refresh for 404 is in flight -> originating trade still completes.
    phase[0] = "switch"
    state_404 = {"StationType": "FleetCarrier", "MarketID": 404, "IsDocked": True, "ShipType": "type9"}
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "SWI-404",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "SWI-404", "MarketID": 404},
        state_404,
    )
    assert second_started.wait(timeout=2)
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "SWI-404",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:08Z", "MarketID": 404, "Type": "steel", "Count": 15},
        state_404,
    )
    load.journal_entry("OtherCmdr", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    second_gate.set()
    _drain_threads_and_results(plugin)
    assert writes == [(303, {"steel": -30}), (404, {"steel": -15})]
    assert remote[404] == {"steel": 485}


def test_revoked_carrier_removed_from_callsign_map_and_blocked_from_capi(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Revoking a carrier via link refresh removes its callsign mapping and blocks subsequent CAPI POSTs."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    posts: list[tuple[int, dict[str, int]]] = []
    fcs_state: list[dict[str, Any]] = [{"marketId": 101, "name": "OWN-101", "cargo": {"steel": 500}}]

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: list(fcs_state))
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", lambda mid, cargo: posts.append((mid, dict(cargo))))

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)
    assert plugin.fc_handler.get_market_id_by_callsign("OWN-101") == 101

    # Unlink 101 and trigger a fresh link refresh.
    fcs_state.clear()
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "UNL-999",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "UNL-999", "MarketID": 999},
        {"StationType": "FleetCarrier", "MarketID": 999, "IsDocked": True, "ShipType": "type9"},
    )
    _drain_threads_and_results(plugin)

    assert plugin.fc_handler.is_update_eligible_fc(101) is False
    assert plugin.fc_handler.get_market_id_by_callsign("OWN-101") is None
    assert 101 not in plugin.fc_handler.linked_fcs

    load.journal_entry("Rempanda", False, "Mynoaw", "", {"event": "Undocked"}, {"IsDocked": False, "ShipType": "type9"})
    plugin.fc_handler.update_fc_cargo_from_capi(101, {"steel": 123}, capi_timestamp=time.time() + 60, was_docked=False)
    drain(plugin)
    assert posts == []


def test_stale_track_all_display_cache_fallback_does_not_resurrect_revoked_carrier(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Failed Track All GETs and cache-only updates never re-enable carriers revoked by fresh discovery."""
    from RavenColonail_EDMC.ui.overlay_projects_fetch import (
        apply_all_projects_fetch_result,
        fetch_all_overlay_projects_worker,
    )

    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    cached_project = {
        "buildId": "build-1",
        "commodities": {"steel": 100},
        "linkedFC": [{"marketId": 505, "name": "OLD-505"}],
    }
    plugin.selected_overlay_build_id = "__OVERLAY_TRACK_ALL__"
    plugin.overlay_project_cache_by_build_id = {"build-1": dict(cached_project)}
    plugin.overlay_carrier_tracking_enabled = False
    monkeypatch.setattr(plugin, "get_project_by_build_id", lambda _bid: None)

    res = fetch_all_overlay_projects_worker(plugin, ["build-1"], link_epoch=plugin.fc_handler.allocate_link_epoch())
    apply_all_projects_fetch_result(
        plugin,
        res,
        fetch_fc_cargo=lambda **_kw: None,
        refresh_fc_combo_state=lambda: None,
        refresh_build_overlay=lambda: None,
    )
    assert plugin.fc_handler.is_update_eligible_fc(505) is False

    # Display-only remaining_need update (no fresh project_view) must also not re-enable 505.
    apply_project_cache_update(plugin, "build-1", remaining_need={"steel": 50})
    assert plugin.fc_handler.is_update_eligible_fc(505) is False


def test_overlay_registered_carrier_can_be_revoked_by_newer_overlay_or_refresh(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Overlay-registered carriers are revoked by either a newer overlay unlink or a subsequent fresh refresh."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    # Register 505 via fresh overlay response, then revoke it via a newer fresh overlay response with empty linkedFC.
    p_linked = {"buildId": "build-1", "linkedFC": [{"marketId": 505, "name": "OVL-505"}]}
    p_unlinked = {"buildId": "build-1", "linkedFC": []}
    remember_all_projects(plugin, [p_linked], authoritative_projects=[p_linked])
    assert plugin.fc_handler.is_update_eligible_fc(505) is True

    remember_all_projects(plugin, [p_unlinked], authoritative_projects=[p_unlinked])
    assert plugin.fc_handler.is_update_eligible_fc(505) is False

    # Re-register 505, then run a LATER commander link refresh excluding 505 -> must revoke 505.
    remember_all_projects(plugin, [p_linked], authoritative_projects=[p_linked])
    assert plugin.fc_handler.is_update_eligible_fc(505) is True

    load.journal_entry(
        "Rempanda", False, "Mynoaw", "UNL-999",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "UNL-999", "MarketID": 999},
        {"StationType": "FleetCarrier", "MarketID": 999, "IsDocked": True, "ShipType": "type9"},
    )
    _drain_threads_and_results(plugin)
    assert plugin.fc_handler.is_update_eligible_fc(505) is False


def test_shutdown_during_follow_up_refresh_persists_queued_trade_for_restart_recovery(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Shutdown suppressing a follow-up refresh leaves carrier B's trade durably checkpointed for restart recovery."""
    from RavenColonail_EDMC.pending_carrier_deliveries import PendingCarrierDeliveries

    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    first_started = threading.Event()
    first_gate = threading.Event()
    calls = 0

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])

    def fake_projects(_cmdr: str) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        first_started.set()
        first_gate.wait(timeout=2)
        return [{"buildId": "b1", "linkedFC": [{"marketId": 303, "name": "AAA-303"}]}]

    monkeypatch.setattr(plugin.api_client, "get_commander_projects", fake_projects)

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    load.journal_entry(
        "Rempanda", False, "Mynoaw", "AAA-303",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "AAA-303", "MarketID": 303},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    assert first_started.wait(timeout=2)

    # Queue follow-up carrier 404 and a trade while refresh A is in flight.
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "BBB-404",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "BBB-404", "MarketID": 404},
        {"StationType": "FleetCarrier", "MarketID": 404, "IsDocked": True, "ShipType": "type9"},
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "BBB-404",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:05Z", "MarketID": 404, "Type": "steel", "Count": 25},
        {"StationType": "FleetCarrier", "MarketID": 404, "IsDocked": True, "ShipType": "type9"},
    )

    first_gate.set()
    plugin.finish_carrier_initialization()

    # Reload recovery file as a fresh process -> carrier 404's -25 steel trade is preserved on disk.
    reloaded = PendingCarrierDeliveries()
    reloaded.configure(str(tmp_path))
    records = reloaded.records("Rempanda", 404)
    assert len(records) == 1
    assert records[0]["cargo"] == {"steel": -25}
    assert records[0]["attempted"] is False


def test_empty_depot_patch_and_stale_epoch_do_not_revoke_linked_carriers(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Empty depot PATCH responses and older request epochs cannot wipe out newer project-linked carriers."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [
        {"buildId": "build-1", "linkedFC": [{"marketId": 505, "name": "OVL-505"}]},
    ])

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)
    assert plugin.fc_handler.is_update_eligible_fc(505) is True

    # Empty {} depot PATCH acknowledgement carries no linkedFC -> must NOT unlink 505.
    plugin.selected_overlay_build_id = "build-1"
    monkeypatch.setattr(plugin.api_client, "patch_project_update", lambda _bid, _payload: {})
    assert plugin.patch_project_depot_state("build-1", {"commodities": {"steel": 100}}) is True
    assert plugin.fc_handler.is_update_eligible_fc(505) is True

    # Older overlay GET (epoch 2, empty linkedFC) finishing while newer refresh (epoch 3, links 606) is in flight
    # must NOT store an application-time tombstone defeating epoch 3.
    stale_epoch = plugin.fc_handler.allocate_link_epoch()
    refresh_epoch = plugin.fc_handler.allocate_link_epoch()
    plugin.fc_handler.register_project_linked_fcs(
        [{"buildId": "build-2", "linkedFC": []}], request_epoch=stale_epoch,
    )
    plugin.fc_handler.finish_link_refresh(
        "Rempanda",
        [],
        {
            606: {
                "marketId": 606,
                "name": "NEW-606",
                "eligibleFromBuildId": "build-2",
                "eligibleFromBuildIds": {"build-2"},
            },
        },
        refresh_epoch=refresh_epoch,
    )
    assert plugin.fc_handler.is_update_eligible_fc(606) is True

    # Delayed depot PATCH started before refresh (with empty linkedFC) cannot revoke 606 either.
    apply_project_cache_update(
        plugin, "build-2", project_view={"buildId": "build-2", "linkedFC": []}, request_epoch=stale_epoch,
    )
    assert plugin.fc_handler.is_update_eligible_fc(606) is True


def test_queued_market_observation_blocks_older_capi_and_preserves_physical_timestamp(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Queued Market.json timestamps block older CAPI before worker drain and persist physical observation time."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 100}}
    posts: list[tuple[int, dict[str, int]]] = []
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 303, "name": "B6W-34K", "cargo": dict(remote[303])},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(
        plugin.api_client,
        "update_fc_cargo",
        lambda mid, cargo: (posts.append((mid, dict(cargo))), remote[mid].update(cargo), dict(remote[mid]))[2],
    )

    state = {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"}
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        state,
    )
    _drain_threads_and_results(plugin)

    market_ts = "2026-11-22T20:10:00Z"
    _write_market_json(
        tmp_path, market_id=303, timestamp=market_ts,
        items=[{"Name": "$Steel_name;", "Stock": 500, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": market_ts, "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )

    # Undock and receive an older CAPI snapshot BEFORE draining the queued Market job.
    load.journal_entry("Rempanda", False, "Mynoaw", "", {"event": "Undocked"}, {"IsDocked": False, "ShipType": "type9"})
    plugin.fc_handler.update_fc_cargo_from_capi(303, {}, capi_timestamp="2026-11-22T20:05:00Z", was_docked=False)
    drain(plugin)

    # Older CAPI was rejected; queued Market job still synced 500 and recorded the 20:10:00Z physical timestamp.
    assert posts == [(303, {"steel": 500})]
    assert remote[303] == {"steel": 500}
    from RavenColonail_EDMC.fleet_carrier_handler import _timestamp_to_epoch

    assert plugin.pending_carrier_deliveries.cargo_observed_at(303) == pytest.approx(_timestamp_to_epoch(market_ts))


def test_deferred_market_released_on_overlay_discovery_preserves_fifo_order_before_live_buy(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """When overlay discovery makes a carrier eligible mid-refresh, deferred Market(100) runs before live Buy(-10)."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 0}}
    events_log: list[tuple[str, int, dict[str, int]]] = []
    refresh_started = threading.Event()
    refresh_gate = threading.Event()
    calls = 0

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])

    def fake_projects(_cmdr: str) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        refresh_started.set()
        refresh_gate.wait(timeout=2)
        return [{"buildId": "b1", "linkedFC": [{"marketId": 303, "name": "B6W-34K"}]}]

    def fake_post(mid: int, cargo: dict[str, int]) -> dict[str, int]:
        events_log.append(("POST", mid, dict(cargo)))
        remote[mid].update(cargo)
        return dict(remote[mid])

    def fake_patch(mid: int, diff: dict[str, int]) -> dict[str, int]:
        events_log.append(("PATCH", mid, dict(diff)))
        for k, v in diff.items():
            remote[mid][k] = max(0, remote[mid].get(k, 0) + v)
        return dict(remote[mid])

    monkeypatch.setattr(plugin.api_client, "get_commander_projects", fake_projects)
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", fake_post)
    monkeypatch.setattr(plugin.api_client, "supply_fc", fake_patch)

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    state = {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"}
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        state,
    )
    assert refresh_started.wait(timeout=2)

    # Market(100) is deferred while refresh is running.
    _write_market_json(
        tmp_path, market_id=303, timestamp="2026-11-22T20:10:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 100, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )

    # Overlay makes 303 eligible before refresh finishes -> then live MarketBuy(-10) arrives.
    project = {"buildId": "b1", "linkedFC": [{"marketId": 303, "name": "B6W-34K"}]}
    remember_all_projects(plugin, [project], authoritative_projects=[project])
    drain(plugin)

    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:05Z", "MarketID": 303, "Type": "steel", "Count": 10},
        state,
    )
    drain(plugin)
    assert remote[303] == {"steel": 90}

    # Original refresh now completes -> must NOT replay Market(100) over the acknowledged 90!
    refresh_gate.set()
    _drain_threads_and_results(plugin)
    assert remote[303] == {"steel": 90}
    assert events_log == [("POST", 303, {"steel": 100}), ("PATCH", 303, {"steel": -10})]


def test_unattempted_partial_recovery_respects_saved_before_state(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An unattempted partial replacement does not overwrite intervening remote stock changes on retry."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    remote: Dict[int, Dict[str, int]] = {303: {"steel": 150}}
    posts: list[tuple[int, dict[str, int]]] = []

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 303, "name": "B6W-34K", "cargo": {"steel": 100}},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", lambda mid, cargo: posts.append((mid, dict(cargo))))

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    # Persist an unattempted partial replacement whose before-state was steel=100, while server moved to 150.
    plugin.pending_carrier_deliveries.begin_replacement(
        "Rempanda", 303, {"steel": 200}, [], attempted=False, before={"steel": 100}, partial=True,
    )
    plugin.fc_handler.retry_pending_deliveries()
    assert posts == []
    assert len(plugin.pending_carrier_deliveries.replacements(market_id=303)) == 1


def test_retired_handler_failed_link_refresh_honors_recovery_backoff(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A retired handler with a failed link refresh honors its own backoff without starving delivery recovery."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    refresh_calls = 0

    def fake_refresh(mid: int, *, handler: Any = None) -> bool:
        nonlocal refresh_calls
        refresh_calls += 1
        return True

    monkeypatch.setattr(plugin, "maybe_refresh_fc_links_for_carrier", fake_refresh)
    retired = plugin.fc_handler
    retired.commander_name = "Rempanda"
    retired.initialized_cmdr = "Rempanda"
    retired._link_refresh_failed_markets.add(303)
    retired._next_link_refresh_retry = time.monotonic() + 60
    retired.retire()
    plugin._pending_link_handlers.append(retired)

    plugin._retry_retired_link_lookups()
    assert refresh_calls == 0

    retired._next_link_refresh_retry = 0.0
    retired._next_delivery_recovery = 0.0
    plugin._retry_retired_link_lookups()
    assert refresh_calls == 1
    assert retired._next_link_refresh_retry > time.monotonic()
    assert retired._next_delivery_recovery == 0.0


def test_retired_failed_link_refresh_does_not_starve_eligible_carrier_delivery_recovery(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Failed link lookups for unknown carrier X must not block pending delivery recovery for eligible carrier Y."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    remote: Dict[int, Dict[str, int]] = {101: {"steel": 500}}
    patches: list[tuple[int, dict[str, int]]] = []
    refresh_calls: list[int] = []

    monkeypatch.setattr(plugin, "maybe_refresh_fc_links_for_carrier", lambda mid, *, handler=None: (
        refresh_calls.append(mid), True
    )[1])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "supply_fc", lambda mid, diff: (
        patches.append((mid, dict(diff))),
        remote[mid].update({"steel": remote[mid]["steel"] + diff["steel"]}),
        dict(remote[mid]),
    )[2])

    retired = plugin.fc_handler
    retired.commander_name = "Rempanda"
    retired.initialized_cmdr = "Rempanda"
    retired.update_eligible_fc_market_ids = {101}
    retired.linked_fcs[101] = {"marketId": 101, "name": "OWN-101", "cargo": {"steel": 500}}
    retired._acknowledged_fc_cargo[101] = {"steel": 500}
    record_id = plugin.pending_carrier_deliveries.record("Rempanda", 101, {"steel": -10})
    retired._inventory_lookup_record_ids.add(record_id)
    retired._link_refresh_failed_markets.add(303)
    retired._next_link_refresh_retry = 0.0
    retired._next_delivery_recovery = 0.0
    retired.retire()
    plugin._pending_link_handlers.append(retired)

    plugin.fc_handler = load.fleet_carrier_handler.FleetCarrierHandler(plugin)
    plugin.fc_handler.commander_name = "Bravo"
    plugin.fc_handler.initialized_cmdr = "Bravo"

    plugin._journal_maybe_init_fc_handler("Bravo", {})
    drain(plugin)

    assert 303 in refresh_calls
    assert patches == [(101, {"steel": -10})]
    assert remote[101] == {"steel": 490}
    assert plugin.pending_carrier_deliveries.records("Rempanda", 101) == []


def test_register_project_linked_fcs_serializes_deferred_market_before_live_trade(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Eligibility publication and deferred Market queueing stay serialized against concurrent journal trades."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 100}}
    events_log: list[tuple[str, int, dict[str, int]]] = []
    refresh_started = threading.Event()
    refresh_gate = threading.Event()
    calls = 0

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])

    def fake_projects(_cmdr: str) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        refresh_started.set()
        refresh_gate.wait(timeout=2)
        return []

    def fake_post(mid: int, cargo: dict[str, int]) -> dict[str, int]:
        events_log.append(("POST", mid, dict(cargo)))
        remote[mid].update(cargo)
        return dict(remote[mid])

    def fake_patch(mid: int, diff: dict[str, int]) -> dict[str, int]:
        events_log.append(("PATCH", mid, dict(diff)))
        for k, v in diff.items():
            remote[mid][k] = max(0, remote[mid].get(k, 0) + v)
        return dict(remote[mid])

    monkeypatch.setattr(plugin.api_client, "get_commander_projects", fake_projects)
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", fake_post)
    monkeypatch.setattr(plugin.api_client, "supply_fc", fake_patch)

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    state = {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"}
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        state,
    )
    assert refresh_started.wait(timeout=2)

    remote[303] = {"steel": 50}
    _write_market_json(
        tmp_path, market_id=303, timestamp="2026-11-22T20:10:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 100, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )

    in_release = threading.Event()
    release_trade_started = threading.Event()
    original_release = plugin.fc_handler._release_link_refresh_items_locked

    def paused_release(items: list[Any]) -> set[int]:
        in_release.set()
        release_trade_started.wait(timeout=0.3)
        return original_release(items)

    monkeypatch.setattr(plugin.fc_handler, "_release_link_refresh_items_locked", paused_release)

    errors: list[BaseException] = []
    project = {"buildId": "b1", "linkedFC": [{"marketId": 303, "name": "B6W-34K"}]}

    def register_worker() -> None:
        try:
            plugin.fc_handler.register_project_linked_fcs([project])
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=register_worker)
    worker.start()
    try:
        assert in_release.wait(timeout=2)
        trade_thread = threading.Thread(target=lambda: load.journal_entry(
            "Rempanda", False, "Mynoaw", "B6W-34K",
            {"event": "MarketSell", "timestamp": "2026-11-22T20:10:05Z", "MarketID": 303, "Type": "steel", "Count": 10},
            state,
        ))
        trade_thread.start()
        time.sleep(0.05)
        release_trade_started.set()
        trade_thread.join(timeout=2)
        worker.join(timeout=2)
    finally:
        refresh_gate.set()
    assert errors == []
    _drain_threads_and_results(plugin)
    assert remote[303] == {"steel": 110}
    assert events_log == [("POST", 303, {"steel": 100}), ("PATCH", 303, {"steel": 10})]


def test_read_ahead_same_second_buys_survive_link_discovery_completion(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Two same-second Buy10 callbacks with read-ahead Cargo.json=20 both count across link discovery."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load.config, "get_str", lambda key: (
        str(tmp_path) if key == "journaldir" else ("test-key" if key == "ravencolonial_api_key" else "")
    ))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 100}}
    refresh_started = threading.Event()
    refresh_gate = threading.Event()
    calls = 0

    def fake_fcs(_cmdr: str) -> list[dict[str, Any]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return []
        refresh_started.set()
        refresh_gate.wait(timeout=2)
        return [{"marketId": 303, "name": "B6W-34K", "cargo": {"steel": 100}}]

    def fake_patch(mid: int, diff: dict[str, int]) -> dict[str, int]:
        for k, v in diff.items():
            remote[mid][k] = max(0, remote[mid].get(k, 0) + v)
        return dict(remote[mid])

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", fake_fcs)
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "supply_fc", fake_patch)

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    dock_entry = {
        "event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K",
        "MarketID": 303, "StationServices": ["commodities", "squadronBank"],
    }
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K", dock_entry,
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9", "Cargo": {}},
    )
    assert refresh_started.wait(timeout=2)

    # Cargo.json already reflects both Buy10 callbacks at the same second T.
    (tmp_path / "Cargo.json").write_text(json.dumps({
        "timestamp": "2026-11-22T20:10:00Z", "event": "Cargo", "Vessel": "Ship",
        "Count": 20, "Inventory": [{"Name": "steel", "Count": 20}],
    }), encoding="utf-8")

    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:00Z", "MarketID": 303, "Type": "steel", "Count": 10},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9", "Cargo": {"steel": 10}},
    )

    # Discovery completes between Callback 1 and Callback 2.
    refresh_gate.set()
    _drain_threads_and_results(plugin)
    assert remote[303] == {"steel": 90}

    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:00Z", "MarketID": 303, "Type": "steel", "Count": 10},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9", "Cargo": {"steel": 20}},
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {
            "event": "Cargo", "timestamp": "2026-11-22T20:10:01Z", "Vessel": "Ship",
            "Count": 20, "Inventory": [{"Name": "steel", "Count": 20}],
        },
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9", "Cargo": {"steel": 20}},
    )
    drain(plugin)
    assert remote[303] == {"steel": 80}
    assert plugin.cargo == {"steel": 20}


def test_matching_newer_capi_supersedes_older_queued_market_snapshot(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A newer CAPI snapshot matching cache must still supersede an older queued Market sync."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 50}}
    posts: list[tuple[int, dict[str, int]]] = []

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 303, "name": "B6W-34K", "cargo": {"steel": 50}},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", lambda mid, cargo: (
        posts.append((mid, dict(cargo))), remote[mid].update(cargo), dict(remote[mid])
    )[2])

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    state = {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"}
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        state,
    )
    drain(plugin)

    # Queue older Market(T1, steel=100) without draining yet.
    _write_market_json(
        tmp_path, market_id=303, timestamp="2026-11-22T20:10:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 100, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "", {"event": "Undocked"},
        {"IsDocked": False, "ShipType": "type9"},
    )

    # Newer CAPI(T2, steel=50) matches cache and returns via the equality shortcut.
    plugin.fc_handler.update_fc_cargo_from_capi(303, {"steel": 50}, "2026-11-22T20:15:00Z", was_docked=False)
    drain(plugin)

    assert posts == []
    assert remote[303] == {"steel": 50}


def test_delayed_overlay_and_depot_fetches_do_not_register_across_commander_switch(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Link epochs belong to their originating handler and cannot leak stale links onto a new commander."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])

    load.journal_entry("Alpha", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)
    handler_a = plugin.fc_handler
    for _ in range(50):
        stale_epoch = handler_a.allocate_link_epoch()

    # Switch to Bravo -> new handler B starts at low epoch with no links.
    load.journal_entry("Bravo", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)
    assert plugin.fc_handler is not handler_a
    assert not plugin.fc_handler.is_update_eligible_fc(505)

    stale_project = {"buildId": "p1", "linkedFC": [{"marketId": 505, "name": "OLD-505"}]}
    plugin.selected_overlay_build_id = "p1"
    apply_project_cache_update(
        plugin, "p1", project_view=stale_project, request_epoch=stale_epoch, request_handler=handler_a,
    )
    assert not plugin.fc_handler.is_update_eligible_fc(505)

    plugin.selected_overlay_build_id = "__OVERLAY_TRACK_ALL__"
    remember_all_projects(
        plugin, [stale_project], authoritative_projects=[stale_project],
        request_epoch=stale_epoch, request_handler=handler_a,
    )
    assert not plugin.fc_handler.is_update_eligible_fc(505)

    overlay_row = plugin.ui_manager._overlay_row
    overlay_row._remember_fetched_project(
        stale_project, "p1", link_epoch=stale_epoch, link_handler=handler_a,
    )
    assert not plugin.fc_handler.is_update_eligible_fc(505)


@pytest.mark.parametrize("selected_id", ["other-build", None])
@pytest.mark.parametrize("revocation", [{"linkedFC": []}, {"complete": True}])
def test_depot_project_update_revokes_linked_fc_even_when_unselected(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    selected_id: Any, revocation: dict[str, Any],
) -> None:
    """Authoritative unlink/completion from apply_project_cache_update revokes eligibility regardless of selection."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    plugin.selected_overlay_build_id = "p1"
    apply_project_cache_update(
        plugin, "p1", project_view={"buildId": "p1", "linkedFC": [{"marketId": 505, "name": "PRJ-505"}]},
    )
    assert plugin.fc_handler.is_update_eligible_fc(505)

    plugin.selected_overlay_build_id = selected_id
    apply_project_cache_update(plugin, "p1", project_view={"buildId": "p1", **revocation})
    assert not plugin.fc_handler.is_update_eligible_fc(505)


@pytest.mark.parametrize("retire_before_retry", [False, True])
def test_deferred_market_survives_transient_discovery_failure_and_retirement(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    retire_before_retry: bool,
) -> None:
    """Market(1000) deferred ahead of Buy10 survives transient discovery failure and handler retirement."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 500}}
    events_log: list[tuple[str, int, dict[str, int]]] = []
    first_started = threading.Event()
    first_gate = threading.Event()
    attempts = 0

    def fake_fcs(cmdr: str) -> list[dict[str, Any]]:
        nonlocal attempts
        if cmdr != "Alpha":
            return []
        attempts += 1
        if attempts == 1:
            return []
        if attempts == 2:
            first_started.set()
            first_gate.wait(timeout=2)
            raise ValueError("transient discovery outage")
        return [{"marketId": 303, "name": "B6W-34K", "cargo": {"steel": 500}}]

    def fake_post(mid: int, cargo: dict[str, int]) -> dict[str, int]:
        events_log.append(("POST", mid, dict(cargo)))
        remote[mid].update(cargo)
        return dict(remote[mid])

    def fake_patch(mid: int, diff: dict[str, int]) -> dict[str, int]:
        events_log.append(("PATCH", mid, dict(diff)))
        for k, v in diff.items():
            remote[mid][k] = max(0, remote[mid].get(k, 0) + v)
        return dict(remote[mid])

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", fake_fcs)
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", fake_post)
    monkeypatch.setattr(plugin.api_client, "supply_fc", fake_patch)

    load.journal_entry("Alpha", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)
    alpha_handler = plugin.fc_handler

    state = {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"}
    load.journal_entry(
        "Alpha", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        state,
    )
    assert first_started.wait(timeout=2)

    _write_market_json(
        tmp_path, market_id=303, timestamp="2026-11-22T20:10:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 1000, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Alpha", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )
    load.journal_entry(
        "Alpha", False, "Mynoaw", "B6W-34K",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:05Z", "MarketID": 303, "Type": "steel", "Count": 10},
        state,
    )

    # First discovery fails -> both Market(1000) and Buy10 must remain queued in order.
    first_gate.set()
    _drain_threads_and_results(plugin)
    assert events_log == []
    assert 303 in alpha_handler._link_refresh_failed_markets

    if retire_before_retry:
        load.journal_entry("Bravo", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
        _drain_threads_and_results(plugin)
        assert alpha_handler._retired

    alpha_handler._next_link_refresh_retry = 0.0
    if retire_before_retry:
        plugin._retry_retired_link_lookups()
    else:
        alpha_handler.retry_pending_deliveries()
    _drain_threads_and_results(plugin)

    assert remote[303] == {"steel": 990}
    assert events_log == [("POST", 303, {"steel": 1000}), ("PATCH", 303, {"steel": -10})]


def test_nested_cached_baseline_mirror_runs_outside_cargo_state_lock_on_deferred_release(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Deferred trade release with cached baseline must not invoke UI mirror while holding _cargo_state_lock."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "supply_fc", lambda mid, diff: {"steel": 90})

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    handler = plugin.fc_handler
    # Pre-populate cached manifest without eligibility (as overlay reads can do).
    handler.replace_fc_cargo_manifest(303, {"steel": 100}, source="raven_colonial_api")

    mirror_lock_states: list[bool] = []
    orig_mirror = handler._maybe_mirror_selected_fc_cargo_and_refresh

    def checked_mirror(market_id: int) -> None:
        held_by_caller: list[bool] = []

        def probe() -> None:
            got = handler._cargo_state_lock.acquire(blocking=False)
            if got:
                handler._cargo_state_lock.release()
            held_by_caller.append(not got)

        t = threading.Thread(target=probe)
        t.start()
        t.join(timeout=2)
        mirror_lock_states.append(held_by_caller[0])
        orig_mirror(market_id)

    monkeypatch.setattr(handler, "_maybe_mirror_selected_fc_cargo_and_refresh", checked_mirror)

    # Dock at 303 while link refresh is pending and defer a MarketBuy.
    handler.current_station_type = "FleetCarrier"
    handler.current_market_id = 303
    handler._link_refresh_inflight = True
    handler._link_refresh_active_markets.add(303)
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:00Z", "MarketID": 303, "Type": "steel", "Count": 10},
        {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"},
    )
    handler.register_project_linked_fcs(
        [{"buildId": "p1", "linkedFC": [{"marketId": 303, "name": "B6W-34K"}]}],
    )
    assert mirror_lock_states and all(held is False for held in mirror_lock_states)


def test_deferred_market_survives_discovery_failure_before_following_trade(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Deferred Market(1000) survives link discovery failure even when MarketBuy10 arrives afterwards."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 500}}
    events_log: list[tuple[str, int, dict[str, int]]] = []
    first_started, first_gate = threading.Event(), threading.Event()
    attempts = 0

    def fake_fcs(_cmdr: str) -> list[dict[str, Any]]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return []
        if attempts == 2:
            first_started.set()
            first_gate.wait(timeout=2)
            raise ValueError("transient outage")
        return [{"marketId": 303, "name": "B6W-34K", "cargo": {"steel": 500}}]

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", fake_fcs)
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", lambda mid, cargo: (
        events_log.append(("POST", mid, dict(cargo))), remote[mid].update(cargo), dict(remote[mid])
    )[2])
    monkeypatch.setattr(plugin.api_client, "supply_fc", lambda mid, diff: (
        events_log.append(("PATCH", mid, dict(diff))),
        remote[mid].update({k: max(0, remote[mid].get(k, 0) + v) for k, v in diff.items()}),
        dict(remote[mid]),
    )[2])

    load.journal_entry("Alpha", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    state = {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"}
    load.journal_entry(
        "Alpha", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        state,
    )
    assert first_started.wait(timeout=2)

    _write_market_json(
        tmp_path, market_id=303, timestamp="2026-11-22T20:10:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 1000, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Alpha", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )
    # Fail discovery BEFORE MarketBuy arrives.
    first_gate.set()
    _drain_threads_and_results(plugin)
    assert events_log == []

    # Now MarketBuy arrives and triggers a fresh lookup that succeeds.
    load.journal_entry(
        "Alpha", False, "Mynoaw", "B6W-34K",
        {"event": "MarketBuy", "timestamp": "2026-11-22T20:10:05Z", "MarketID": 303, "Type": "steel", "Count": 10},
        state,
    )
    _drain_threads_and_results(plugin)
    assert remote[303] == {"steel": 990}
    assert events_log == [("POST", 303, {"steel": 1000}), ("PATCH", 303, {"steel": -10})]


def test_retired_orphan_market_and_cross_handler_completed_trade_cannot_overwrite_newer_stock(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """An orphan retired Market is dropped and never overwrites a newer commander's completed sale."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 500}}
    alpha_started, alpha_gate = threading.Event(), threading.Event()
    alpha_calls = 0

    def fake_fcs(cmdr: str) -> list[dict[str, Any]]:
        nonlocal alpha_calls
        if cmdr == "Alpha":
            alpha_calls += 1
            if alpha_calls == 1:
                return []
            alpha_started.set()
            alpha_gate.wait(timeout=2)
            return [{"marketId": 303, "name": "B6W-34K", "cargo": dict(remote[303])}]
        return [{"marketId": 303, "name": "B6W-34K", "cargo": dict(remote[303])}]

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", fake_fcs)
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", lambda mid, cargo: (
        remote[mid].update(cargo), dict(remote[mid])
    )[1])
    monkeypatch.setattr(plugin.api_client, "supply_fc", lambda mid, diff: (
        remote[mid].update({k: max(0, remote[mid].get(k, 0) + v) for k, v in diff.items()}),
        dict(remote[mid]),
    )[1])

    load.journal_entry("Alpha", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    state = {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"}
    load.journal_entry(
        "Alpha", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        state,
    )
    assert alpha_started.wait(timeout=2)

    _write_market_json(
        tmp_path, market_id=303, timestamp="2026-11-22T20:10:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 1000, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Alpha", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )

    # Switch to Bravo while Alpha's lookup is still in flight; Bravo sells 10 -> remote becomes 510.
    load.journal_entry("Bravo", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)
    load.journal_entry(
        "Bravo", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        state,
    )
    load.journal_entry(
        "Bravo", False, "Mynoaw", "B6W-34K",
        {"event": "MarketSell", "timestamp": "2026-11-22T20:10:05Z", "MarketID": 303, "Type": "steel", "Count": 10},
        state,
    )
    drain(plugin)
    assert remote[303] == {"steel": 510}

    # Release Alpha's stale lookup -> orphan retired Market(1000) must not overwrite 510.
    alpha_gate.set()
    _drain_threads_and_results(plugin)
    assert remote[303] == {"steel": 510}


def test_cancelling_unattempted_deposit_after_earlier_ack_rebuilds_cache(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Cancelling an unattempted deposit after an earlier ack rebuilds cache from confirmed stock."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    remote: Dict[int, Dict[str, int]] = {303: {"steel": 75}}
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 303, "name": "B6W-34K", "cargo": {"steel": 75}},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "supply_fc", lambda mid, diff: (
        remote[mid].update({k: max(0, remote[mid].get(k, 0) + v) for k, v in diff.items()}),
        dict(remote[mid]),
    )[1])

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    handler = plugin.fc_handler
    deliveries = plugin.pending_carrier_deliveries
    id_a = deliveries.record("Rempanda", 303, {"steel": 5})
    id_b = deliveries.record("Rempanda", 303, {"steel": 10})
    handler.linked_fcs[303]["cargo"] = {"steel": 90}

    # Acknowledge A -> confirmed cargo becomes 80 and cache is replaced with 80 (already dropping B's optimistic 10).
    deliveries.remember_cargo(303, {"steel": 80}, written=True)
    deliveries.acknowledge([id_a])
    handler.linked_fcs[303]["cargo"] = {"steel": 80}
    handler._last_inferred_deposit = (id_b, 303, 100.0)
    handler.ship_cargo_tracker._before = {"steel": 35}
    handler.ship_cargo_tracker._point_time = 100.0

    offset = handler._offset_unattempted_inferred_deposit(
        303,
        {"event": "EjectCargo", "timestamp": "1970-01-01T00:01:30Z", "Type": "steel", "Count": 10},
        {"ShipType": "type9"},
        complete=False,
        bank=True,
    )
    assert offset == {"steel": -10}
    assert handler.linked_fcs[303]["cargo"] == {"steel": 80}


def test_older_matching_capi_deferred_ahead_of_newer_market_does_not_drop_market(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """During initialization, an older matching CAPI snapshot does not supersede a newer deferred Market."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 50}}
    init_started, init_gate = threading.Event(), threading.Event()

    def slow_fcs(_cmdr: str) -> list[dict[str, Any]]:
        init_started.set()
        init_gate.wait(timeout=2)
        return [{"marketId": 303, "name": "B6W-34K", "cargo": {"steel": 50}}]

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", slow_fcs)
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", lambda mid, cargo: (
        remote[mid].update(cargo), dict(remote[mid])
    )[1])

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    assert init_started.wait(timeout=2)

    # Queue older CAPI(T1, 50) then dock and queue newer Market(T2, 100) while init is in progress.
    plugin.fc_handler.update_fc_cargo_from_capi(303, {"steel": 50}, "2026-11-22T20:10:00Z", was_docked=False)
    state = {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"}
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        state,
    )
    _write_market_json(
        tmp_path, market_id=303, timestamp="2026-11-22T20:15:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 100, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:15:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )

    init_gate.set()
    _drain_threads_and_results(plugin)
    assert remote[303] == {"steel": 100}


def test_retry_pending_deliveries_enforces_link_refresh_backoff(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """retry_pending_deliveries must respect _next_link_refresh_retry backoff after link failure."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    handler = plugin.fc_handler
    refresh_calls: list[int] = []
    monkeypatch.setattr(
        plugin,
        "maybe_refresh_fc_links_for_carrier",
        lambda mid, **_kw: (refresh_calls.append(mid), True)[1],
    )
    handler._link_refresh_failed_markets.add(303)
    handler._next_link_refresh_retry = time.monotonic() + 60.0

    handler.retry_pending_deliveries()
    assert refresh_calls == []

    handler._next_link_refresh_retry = 0.0
    handler.retry_pending_deliveries()
    assert refresh_calls == [303]


def test_fc_market_sync_handles_overflow_and_missing_stock_key(tmp_path: Path) -> None:
    """Out-of-range Stock (1e309) and rows omitting Stock/stock are skipped without aborting valid rows."""
    (tmp_path / "Market.json").write_text(
        '{"timestamp":"2026-11-22T20:10:00Z","MarketID":303,"StationType":"FleetCarrier","Items":['
        '{"Name":"$Aluminium_name;","Stock":1e309,"Producer":true,"Consumer":false},'
        '{"Name":"$Copper_name;","Producer":true,"Consumer":false},'
        '{"Name":"$Titanium_name;","Stock":0,"Producer":true,"Consumer":false},'
        '{"Name":"$Steel_name;","Stock":42,"Producer":true,"Consumer":false}'
        ']}',
        encoding="utf-8",
    )
    snap = read_fc_market_snapshot(
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "MarketID": 303, "StationType": "FleetCarrier"},
        str(tmp_path),
    )
    assert snap is not None
    assert sorted((item.commodity, item.stock) for item in snap.items) == [("steel", 42), ("titanium", 0)]


def test_market_worker_deduplicates_rechecks_eligibility_and_blocks_on_held_frames(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Serialized Market worker skips duplicate timestamps, revoked carriers, and held inventory frames."""
    from fc_market_sync import FleetCarrierMarketSnapshot

    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    remote: Dict[int, Dict[str, int]] = {303: {"steel": 50}}
    posts: list[tuple[int, dict[str, int]]] = []
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 303, "name": "B6W-34K", "cargo": {"steel": 50}},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", lambda mid, cargo: (
        posts.append((mid, dict(cargo))), remote[mid].update(cargo), dict(remote[mid])
    )[2])

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)
    handler = plugin.fc_handler

    snap_1 = FleetCarrierMarketSnapshot(
        market_id=303, timestamp="2026-11-22T20:10:00Z",
        items=(MarketItemSnapshot(commodity="steel", stock=100, producer=True, consumer=False),),
    )
    assert handler._sync_fc_from_market_snapshot(303, snap_1) is True
    # Identical timestamp queued again is deduplicated without another POST.
    assert handler._sync_fc_from_market_snapshot(303, snap_1) is True
    assert posts == [(303, {"steel": 100})]

    # Held inventory frame blocks partial Market POST.
    snap_2 = FleetCarrierMarketSnapshot(
        market_id=303, timestamp="2026-11-22T20:11:00Z",
        items=(MarketItemSnapshot(commodity="steel", stock=120, producer=True, consumer=False),),
    )
    plugin.pending_carrier_deliveries.checkpoint_inventory("Rempanda", 303, {}, {"reason": "ambiguous"})
    assert handler._sync_fc_from_market_snapshot(303, snap_2) is False
    assert posts == [(303, {"steel": 100})]
    plugin.pending_carrier_deliveries._inventory_frames.clear()

    # Revoking eligibility blocks Market POST.
    handler._commander_fc_ids.discard(303)
    handler.update_eligible_fc_market_ids.discard(303)
    handler.linked_fcs.pop(303, None)
    assert handler._sync_fc_from_market_snapshot(303, snap_2) is False
    assert posts == [(303, {"steel": 100})]


def test_ship_publish_worker_suppresses_duplicates_and_rechecks_stealth(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Ship publish worker drops duplicate payloads and skips sending if stealth is enabled before send."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    sent: list[dict[str, Any]] = []
    stealth = [False]
    monkeypatch.setattr(
        plugin.api_client,
        "publish_current_ship",
        lambda payload: (sent.append(dict(payload)), True)[1],
    )
    monkeypatch.setattr(
        load.config,
        "get_bool",
        lambda key, **kw: stealth[0] if key == "ravencolonial_stealth_ship_cargo" else False,
    )

    payload = {"cmdr": "Rempanda", "cargo": {"steel": 50}}
    sig = "sig-50"
    plugin._run_publish_current_ship_payload(sig, payload, "Cargo")
    plugin._run_publish_current_ship_payload(sig, payload, "Cargo")
    assert len(sent) == 1

    stealth[0] = True
    plugin._run_publish_current_ship_payload("sig-40", {"cmdr": "Rempanda", "cargo": {"steel": 40}}, "Cargo")
    assert len(sent) == 1


def test_queued_depot_patch_uses_originating_handler_across_commander_switch(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A depot PATCH queued before a commander switch must not register links onto the new commander's handler."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(
        plugin.api_client,
        "patch_project_update",
        lambda _bid, _diff: {"buildId": "p1", "linkedFC": [{"marketId": 505, "name": "OLD-505"}]},
    )

    load.journal_entry("Alpha", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)
    alpha_handler = plugin.fc_handler

    # Switch to Bravo before executing Alpha's queued depot patch.
    load.journal_entry("Bravo", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)
    assert plugin.fc_handler is not alpha_handler

    plugin.patch_project_depot_state("p1", {"steel": 10}, request_handler=alpha_handler)
    _drain_threads_and_results(plugin)
    assert not plugin.fc_handler.is_update_eligible_fc(505)


def test_later_held_withdrawal_frame_does_not_cancel_earlier_funding_market(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A funds frame created after Market(100) was queued must not cancel Market(100); retry finishes at 90."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {}}
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 303, "name": "B6W-34K", "cargo": {}},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", lambda mid, cargo: (
        remote[mid].update(cargo), dict(remote[mid])
    )[1])
    monkeypatch.setattr(plugin.api_client, "supply_fc", lambda mid, diff: (
        remote[mid].update({k: max(0, remote[mid].get(k, 0) + v) for k, v in diff.items()}),
        dict(remote[mid]),
    )[1])

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    state = {
        "StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True,
        "ShipType": "type9", "StationServices": ["commodities", "squadronBank"], "Cargo": {},
    }
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K",
         "MarketID": 303, "StationServices": ["commodities", "squadronBank"]},
        state,
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Cargo", "timestamp": "2026-11-22T20:10:00Z", "Vessel": "Ship", "Count": 0, "Inventory": []},
        state,
    )
    drain(plugin)

    # Queue Market(100)@T1, then receive Cargo10@T2 before draining so Cargo10 creates a later funds frame.
    _write_market_json(
        tmp_path, market_id=303, timestamp="2026-11-22T20:10:01Z",
        items=[{"Name": "$Steel_name;", "Stock": 100, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:01Z", "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Cargo", "timestamp": "2026-11-22T20:10:02Z", "Vessel": "Ship", "Count": 10,
         "Inventory": [{"Name": "steel", "Count": 10}]},
        {**state, "Cargo": {"steel": 10}},
    )
    assert len(plugin.pending_carrier_deliveries.inventory_frames("Rempanda", 303)) == 1

    # Draining runs Market(100) first, then retries the held Cargo10 withdrawal -> finishes at 90.
    drain(plugin)
    assert remote[303] == {"steel": 90}
    assert plugin.pending_carrier_deliveries.inventory_frames("Rempanda", 303) == []


def test_abandoned_init_market_does_not_leak_pending_market_timestamp_to_next_commander(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Abandoning Alpha after a failed init with a deferred Market leaves no leaked timestamp for Bravo."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    alpha_started, alpha_gate = threading.Event(), threading.Event()

    def fake_fcs(cmdr: str) -> list[dict[str, Any]]:
        if cmdr == "Alpha":
            alpha_started.set()
            alpha_gate.wait(timeout=2)
            raise ValueError("init failed")
        return [{"marketId": 303, "name": "B6W-34K", "cargo": {"steel": 50}}]

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", fake_fcs)
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])

    load.journal_entry("Alpha", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    assert alpha_started.wait(timeout=2)

    state = {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"}
    load.journal_entry(
        "Alpha", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        state,
    )
    _write_market_json(
        tmp_path, market_id=303, timestamp="2026-11-22T20:10:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 100, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Alpha", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:10:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )

    # Switch to Bravo before Alpha's init fails; Bravo must see no leaked pending Market timestamps.
    load.journal_entry("Bravo", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    alpha_gate.set()
    _drain_threads_and_results(plugin)
    assert plugin.fc_handler._pending_market_timestamps == {}
    assert not plugin.fc_handler._has_pending_inventory_target(303)


def test_full_deferred_capi_ahead_of_partial_market_during_init_preserves_unlisted_stock(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Deferred full CAPI(T1, steel=50, tritium=4000) ahead of partial Market(T2, steel=100) yields both."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))

    remote: Dict[int, Dict[str, int]] = {303: {"steel": 50}}
    init_started, init_gate = threading.Event(), threading.Event()

    def slow_fcs(_cmdr: str) -> list[dict[str, Any]]:
        init_started.set()
        init_gate.wait(timeout=2)
        return [{"marketId": 303, "name": "B6W-34K", "cargo": {"steel": 50}}]

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", slow_fcs)
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote[mid])})
    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", lambda mid, cargo: (
        remote[mid].update(cargo), dict(remote[mid])
    )[1])

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    assert init_started.wait(timeout=2)

    plugin.fc_handler.update_fc_cargo_from_capi(
        303, {"steel": 50, "tritium": 4000}, "2026-11-22T20:10:00Z", was_docked=False,
    )
    state = {"StationType": "FleetCarrier", "MarketID": 303, "IsDocked": True, "ShipType": "type9"}
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "B6W-34K", "MarketID": 303},
        state,
    )
    _write_market_json(
        tmp_path, market_id=303, timestamp="2026-11-22T20:15:00Z",
        items=[{"Name": "$Steel_name;", "Stock": 100, "Producer": True, "Consumer": False}],
    )
    load.journal_entry(
        "Rempanda", False, "Mynoaw", "B6W-34K",
        {"event": "Market", "timestamp": "2026-11-22T20:15:00Z", "StationType": "FleetCarrier", "MarketID": 303},
        state,
    )

    init_gate.set()
    _drain_threads_and_results(plugin)
    assert remote[303] == {"steel": 100, "tritium": 4000}


def test_uncertain_intervening_ship_publish_invalidates_duplicate_cache(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """A failed intervening ship publish clears _last_current_ship_sig so returning to 50 still sends."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    sent: list[dict[str, Any]] = []
    outcomes = [True, False, True]

    def fake_publish(payload: dict[str, Any]) -> bool:
        sent.append(dict(payload))
        return outcomes.pop(0)

    monkeypatch.setattr(plugin.api_client, "publish_current_ship", fake_publish)
    monkeypatch.setattr(load.config, "get_bool", lambda _key, **kw: False)

    plugin._run_publish_current_ship_payload("sig-50", {"cmdr": "Rempanda", "cargo": {"steel": 50}}, "Cargo")
    plugin._run_publish_current_ship_payload("sig-40", {"cmdr": "Rempanda", "cargo": {"steel": 40}}, "Cargo")
    plugin._run_publish_current_ship_payload("sig-50", {"cmdr": "Rempanda", "cargo": {"steel": 50}}, "Cargo")
    assert [item["cargo"] for item in sent] == [{"steel": 50}, {"steel": 40}, {"steel": 50}]
