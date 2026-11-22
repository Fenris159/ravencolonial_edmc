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
    remember_all_projects(plugin, [project])
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

    # Separate manifest editor worker finishes an acknowledged save to 60 before api_queue drains.
    plugin.fc_handler.replace_fc_cargo_manifest(
        303, {"steel": 60}, source="manual_manifest_editor", timestamp=time.time(), written=True,
    )
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


def test_link_refresh_preserves_overlay_registered_carrier_eligibility(
    edmc_plugin: tuple[Any, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Refreshing links on an unknown carrier preserves overlay-registered project carriers."""
    load, plugin = _prepare_plugin(edmc_plugin, monkeypatch, tmp_path)
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda _cmdr: [
        {"marketId": 101, "name": "OWN-101", "cargo": {"steel": 500}},
    ])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda _cmdr: [])

    load.journal_entry("Rempanda", False, "Sol", "", {"event": "LoadGame"}, {"ShipType": "type9"})
    _drain_threads_and_results(plugin)

    remember_all_projects(plugin, [{
        "buildId": "overlay-only",
        "linkedFC": [{"marketId": 505, "name": "OVL-505"}],
    }])
    assert plugin.fc_handler.is_update_eligible_fc(505) is True

    load.journal_entry(
        "Rempanda", False, "Mynoaw", "UNL-999",
        {"event": "Docked", "StationType": "FleetCarrier", "StationName": "UNL-999", "MarketID": 999},
        {"StationType": "FleetCarrier", "MarketID": 999, "IsDocked": True, "ShipType": "type9"},
    )
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
