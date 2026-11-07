"""Commander changes through EDMC's real journal hook, without an EDMC restart."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest
from conftest import settle_commander_links


@pytest.fixture
def commander_plugin(monkeypatch: pytest.MonkeyPatch):
    """Provide the shared EDMC boundary fixture for commander scenarios."""
    from conftest import edmc_plugin_context

    yield from edmc_plugin_context(monkeypatch)


def _journal(
    load: ModuleType, commander: str | None, event: str = "LoadGame", state: dict | None = None,
) -> None:
    load.journal_entry(commander, False, "Sol", "", {"event": event}, state or {})
    settle_commander_links(load.this)


@pytest.mark.parametrize("event", ["Commander", "LoadGame", "StartUp", "Music"])
def test_switch_loads_new_commanders_profile_and_project_links(commander_plugin, event: str) -> None:
    """Switching identities replaces both kinds of links and API attribution."""
    load, plugin = commander_plugin
    _journal(load, "Alpha", "StartUp")
    assert set(plugin.fc_handler.linked_fcs) == {101, 303}

    _journal(load, "Bravo", event)

    assert plugin.cmdr_name == "Bravo"
    assert plugin.api_client.cmdr_name == "Bravo"
    assert plugin.api_client.api_key == "test-key"
    assert set(plugin.fc_handler.linked_fcs) == {202, 404}
    assert plugin.fc_handler.is_update_eligible_fc(404) is True
    assert plugin.fc_handler.is_update_eligible_fc(101) is False
    assert plugin.fc_handler.get_market_id_by_callsign("AAA-111") is None
    assert plugin.fc_handler.get_market_id_by_callsign("BBB-222") == 202

    _journal(load, "Alpha", event)
    assert plugin.api_client.cmdr_name == "Alpha"
    assert set(plugin.fc_handler.linked_fcs) == {101, 303}


def test_unchanged_or_missing_identity_keeps_current_links(commander_plugin) -> None:
    """Repeated session events and missing names do not reload healthy links."""
    load, plugin = commander_plugin
    _journal(load, "Alpha")
    plugin.api_client.get_all_cmdr_fcs = lambda name: []
    plugin.api_client.get_commander_projects = lambda name: []

    for name in ("Alpha", " Alpha ", None, "", "   "):
        _journal(load, name, "StartUp")

    assert plugin.cmdr_name == "Alpha"
    assert plugin.api_client.cmdr_name == "Alpha"
    assert set(plugin.fc_handler.linked_fcs) == {101, 303}


def test_switch_to_unlinked_commander_revokes_previous_links(commander_plugin) -> None:
    """An unlinked commander cannot update carriers belonging to the last one."""
    load, plugin = commander_plugin
    _journal(load, "Alpha")

    _journal(load, "Unlinked")

    assert plugin.api_client.cmdr_name == "Unlinked"
    assert plugin.fc_handler.linked_fcs == {}
    assert plugin.fc_handler.is_update_eligible_fc(303) is False


def test_delayed_capi_cannot_restore_previous_commander(commander_plugin) -> None:
    """A late profile response cannot undo an authoritative journal switch."""
    load, plugin = commander_plugin
    _journal(load, "Alpha")
    _journal(load, "Bravo")

    load.cmdr_data({"commander": {"name": "Alpha"}}, False)

    assert plugin.cmdr_name == "Bravo"
    assert plugin.api_client.cmdr_name == "Bravo"
    assert set(plugin.fc_handler.linked_fcs) == {202, 404}


def test_failed_initialization_discards_old_links_and_retries(
    commander_plugin, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid carrier response leaves no old eligibility and can recover later."""
    load, plugin = commander_plugin
    _journal(load, "Alpha")
    original = plugin.api_client.get_all_cmdr_fcs

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda name: [{"marketId": "invalid"}])
    _journal(load, "Bravo")
    assert plugin.fc_handler.linked_fcs == {}
    assert plugin.fc_handler.is_update_eligible_fc(101) is False

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", original)
    _journal(load, "Bravo", "Music")
    assert set(plugin.fc_handler.linked_fcs) == {202, 404}


def test_switch_clears_old_ship_and_dock_before_applying_new_state(commander_plugin) -> None:
    """Sparse login state cannot inherit the previous ship or dock location."""
    load, plugin = commander_plugin
    _journal(load, "Alpha", state={
        "ShipName": "Alpha ship", "ShipType": "python", "ShipIdent": "A-1", "CargoCapacity": 128,
        "StationType": "FleetCarrier", "MarketID": 101, "StationName": "AAA-111", "SystemAddress": 42,
    })
    plugin.cargo = {"steel": 12}
    plugin.last_cargo = {"steel": 12}
    plugin.plan_sites_system_key = 42
    plugin.plan_sites_rows = [{"id": "alpha-plan"}]
    plugin.selected_plan_site_id = "alpha-plan"

    _journal(load, "Bravo", state={"ShipType": "sidewinder"})

    assert plugin.ship_type == "sidewinder"
    assert plugin.ship_display_name is None
    assert plugin.ship_ident is None
    assert plugin.ship_cargo_capacity is None
    assert plugin.cargo == {}
    assert plugin.last_cargo == {}
    assert plugin.is_docked is False
    assert plugin.current_market_id is None
    assert plugin.current_system_address is None
    assert plugin.fc_handler.current_market_id is None
    assert plugin.plan_sites_rows == []
    assert plugin.selected_plan_site_id is None


def test_new_commander_can_refresh_a_shared_carrier_immediately(commander_plugin) -> None:
    """A previous commander's cooldown cannot delay a shared carrier's cargo refresh."""
    load, plugin = commander_plugin
    dock = {"StationType": "FleetCarrier", "MarketID": 101, "StationName": "AAA-111"}
    _journal(load, "Alpha", state=dock)
    assert plugin.fc_handler.can_refresh_fc_cargo_from_api(101, "dock") == (True, "allowed", 0)

    plugin.api_client.get_all_cmdr_fcs = lambda name: [{"marketId": 101, "name": "AAA-111"}]
    _journal(load, "Bravo", state=dock)

    assert plugin.fc_handler.is_update_eligible_fc(101) is True
    assert plugin.fc_handler.current_market_id == 101
    assert plugin.fc_handler.can_refresh_fc_cargo_from_api(101, "dock") == (True, "allowed", 0)


@pytest.mark.parametrize("switch_commander", [False, True])
def test_plan_permissions_apply_only_to_requesting_commander(
    commander_plugin, monkeypatch: pytest.MonkeyPatch, switch_commander: bool,
) -> None:
    """A queued plan-site result cannot restore the previous architect's permissions."""
    load, plugin = commander_plugin
    manager_module = sys.modules[f"{load.__package__}.ui.manager"]
    worker_module = sys.modules[f"{load.__package__}.ui.plan_sites_refresh"]
    row = {"id": "alpha-plan", "status": "plan", "buildType": "outpost"}

    def get(url: str, **kwargs) -> SimpleNamespace:
        payload = "Alpha" if url.endswith("/architect") else [row]
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)

    monkeypatch.setattr(worker_module, "new_http_session", lambda **kwargs: SimpleNamespace(get=get))
    monkeypatch.setattr(manager_module, "Thread", lambda target, **kwargs: SimpleNamespace(start=target))
    completions = []
    plugin.schedule_after = lambda delay, callback: completions.append(callback) or "scheduled"
    plugin.frame = object()
    _journal(load, "Alpha", state={"SystemAddress": 42})
    plugin.ui_manager.start_plan_sites_refresh()

    if switch_commander:
        _journal(load, "Bravo", state={"SystemAddress": 42})
    while completions:
        completions.pop(0)()

    assert plugin.plan_sites_rows == ([] if switch_commander else [row])
