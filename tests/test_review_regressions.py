"""Behavior regressions found in the full plugin review."""

from __future__ import annotations

import importlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import requests
from conftest import settle_commander_links


def _journal(load: Any, name: str = "Alpha", event: str = "Music", **state: Any) -> None:
    load.journal_entry(name, False, "Sol", "", {"event": event}, state)
    settle_commander_links(load.this)


def _drain_api(plugin: Any) -> None:
    while not plugin.api_queue.empty():
        function, args, kwargs = plugin.api_queue.get_nowait()
        function(*args, **kwargs)
        plugin.api_queue.task_done()


class Value:
    """Represent a Tk variable without requiring a display."""

    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        """Return the visible value."""
        return self.value

    def set(self, value: str) -> None:
        """Update the visible value."""
        self.value = value


class Button:
    """Record a button's visible state."""

    def configure(self, **kwargs: Any) -> None:
        """Apply widget options."""
        self.state = kwargs.get("state")


def _editor(load: Any, plugin: Any) -> tuple[Any, Any]:
    module = importlib.import_module(f"{load.__package__}.ui.fc_manifest_editor")
    editor = module.FleetCarrierManifestEditor(plugin)
    editor._fc_records = {
        101: {"marketId": 101, "cargo": {"steel": 10}},
        202: {"marketId": 202, "cargo": {"gold": 20}},
    }
    editor._select_market(101)
    editor._amount_vars = {"steel": Value("11")}
    editor._save_btn = Button()
    editor._status_var = Value()
    return module, editor


def test_failed_manifest_save_remains_retryable(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    """An ordinary failed save reports an error and re-enables Save."""
    load, plugin = edmc_plugin
    module, editor = _editor(load, plugin)
    monkeypatch.setattr(plugin.api_client, "update_fc_cargo", lambda *args: None)
    monkeypatch.setattr(module.threading, "Thread", lambda target, **kwargs: SimpleNamespace(start=target))

    editor._on_save()

    assert editor._saving is False
    assert editor._save_btn.state == "normal"
    assert editor._status_var.get().startswith("Save failed:")


def test_delayed_manifest_save_keeps_other_carriers_form(edmc_plugin) -> None:
    """Completing A's save cannot replace B's cargo or B's next saved payload."""
    load, plugin = edmc_plugin
    _module, editor = _editor(load, plugin)
    editor._saving = True
    editor._select_market(202)

    editor._finish_save(101, {"steel": 11}, {"steel": 11}, None)

    assert editor._selected_market_id == 202
    assert editor._working_manifest == {"gold": 20}
    editor._select_market(101)
    assert editor._working_manifest == {"steel": 11}


@pytest.mark.parametrize("failure", [requests.ReadTimeout, requests.ConnectionError])
def test_ambiguous_cargo_delta_is_sent_once(edmc_plugin, failure: type[Exception]) -> None:
    """A lost reply after committing +10 must never become a second delivery."""
    _load, plugin = edmc_plugin
    remote = {"steel": 0}

    def request(method: str, url: str, **kwargs: Any) -> None:
        remote["steel"] += kwargs["json"]["steel"]
        raise failure("reply lost after commit")

    plugin.api_client.session = SimpleNamespace(request=request)
    result = plugin.api_client.supply_fc(101, {"steel": 10})

    assert remote == {"steel": 10}
    assert result is None


def test_depot_fallback_rejects_other_locations(
    edmc_plugin, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Journal fallback and cached snapshots must belong to the current dock."""
    load, plugin = edmc_plugin
    entry = {
        "event": "ColonisationConstructionDepot", "timestamp": "2026-11-01T00:00:00Z",
        "MarketID": 101, "SystemAddress": 11,
        "ResourcesRequired": [{"Name": "steel", "RequiredAmount": 100, "ProvidedAmount": 25}],
    }
    (tmp_path / "Journal.2026-11-01.log").write_text(json.dumps(entry) + "\n")
    monkeypatch.setattr(load, "_elite_journal_dir", lambda: str(tmp_path))
    plugin.current_market_id = 202
    plugin.current_system_address = 22
    plugin.construction_depot_data = entry

    assert plugin.build_depot_project_fields(refresh=True) is None
    assert plugin.build_depot_project_fields(refresh=False) is None


def test_old_project_reply_does_not_suppress_new_depot(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    """Identical needs at two different projects still produce both PATCHes."""
    load, plugin = edmc_plugin
    monkeypatch.setattr(plugin, "_ensure_api_worker", lambda: None)
    monkeypatch.setattr(plugin.api_client, "get_project", lambda sa, mid: {"buildId": f"project-{mid}"})
    updates = []

    def update(build_id: str, payload: dict) -> dict:
        updates.append((build_id, payload["commodities"]))
        return {"buildId": build_id, "commodities": payload["commodities"]}

    monkeypatch.setattr(plugin.api_client, "patch_project_update", update)

    def location(mid: int, address: int) -> None:
        state = {"SystemAddress": address, "StationType": "MegaShip", "MarketID": mid}
        entry = {"event": "Location", "Docked": True, **state}
        load.journal_entry("Alpha", False, "Sol", "ColonisationShip 1", entry, state)

    def depot(mid: int, address: int) -> None:
        entry = {
            "event": "ColonisationConstructionDepot", "MarketID": mid, "SystemAddress": address,
            "ResourcesRequired": [{"Name": "steel", "RequiredAmount": 100, "ProvidedAmount": 50}],
        }
        load.journal_entry("Alpha", False, "Sol", "ColonisationShip 1", entry, {"SystemAddress": address})

    location(101, 11)
    depot(101, 11)
    _journal(load, event="Undocked")
    location(202, 22)
    _drain_api(plugin)
    depot(202, 22)
    _drain_api(plugin)

    assert updates == [("project-101", {"steel": 50}), ("project-202", {"steel": 50})]


def test_synced_empty_manifest_is_known_zero_stock(edmc_plugin) -> None:
    """An empty synced carrier gives a -100 deficit rather than unknown cargo."""
    load, plugin = edmc_plugin
    _journal(load)
    worker = importlib.import_module(f"{load.__package__}.ui.overlay_fc_cargo_fetch")
    overlay_module = importlib.import_module(f"{load.__package__}.overlay.build_project")
    plugin.overlay_carrier_tracking_enabled = True
    plugin.overlay_fc_selection = "101"
    plugin.overlay_project_linked_fcs = [{"marketId": 101}]
    plugin.overlay_fc_cargo_by_market = worker.build_overlay_fc_cargo_map(
        plugin, plugin.overlay_project_linked_fcs,
        trigger="overlay_cache_rebuild", allow_api_refresh=False, request_selection="project-101",
    )
    state = overlay_module.BuildProjectOverlay(plugin)._resolve_fc_overlay_state(plugin, {"steel": 100}, False)

    assert state["manifest_known"] is True
    assert state["fc_deltas"] == {"steel": -100}


def test_cancelled_jump_callback_cannot_complete_new_jump(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    """A cancelled departure timer leaves a later jump's displayed countdown intact."""
    load, _plugin = edmc_plugin
    module = importlib.import_module(f"{load.__package__}.fc_jump_timer")
    clock = {"now": datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    monkeypatch.setattr(module, "datetime", Clock)
    callbacks = []
    tracker = module.FleetCarrierJumpTracker(
        schedule_after=lambda delay, callback: callbacks.append(callback) or str(len(callbacks)),
    )
    tracker.handle_jump_requested({"CarrierID": 123, "SystemName": "Alpha", "DepartureTime": "2026-11-01T12:15:00Z"})
    old_departure = callbacks[0]
    tracker.handle_jump_cancelled({"CarrierID": 123})
    clock["now"] = datetime(2026, 11, 1, 12, 1, tzinfo=timezone.utc)
    callbacks[1]()
    tracker.handle_jump_requested({"CarrierID": 123, "SystemName": "Beta", "DepartureTime": "2026-11-01T12:16:40Z"})
    clock["now"] = datetime(2026, 11, 1, 12, 15, tzinfo=timezone.utc)
    old_departure()

    assert tracker.overlay_footer_lines()[0] == "> 123: Departure to Beta in 01:40"


def test_link_initialization_uses_a_worker(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both HTTP lookups run off the journal/UI thread and load usable links."""
    load, plugin = edmc_plugin
    calls = []

    def request(method: str, url: str, **kwargs: Any) -> SimpleNamespace:
        calls.append(threading.current_thread())
        payload = [] if url.endswith("/fc/all") else [{"linkedFC": [{"marketId": 404}]}]
        return SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=lambda: payload)

    for name in ("get_all_cmdr_fcs", "get_commander_projects"):
        method = getattr(type(plugin.api_client), name).__get__(plugin.api_client)
        monkeypatch.setattr(plugin.api_client, name, method)
    plugin.api_client.session = SimpleNamespace(request=request)
    load.journal_entry("Alpha", False, "Sol", "", {"event": "Music"}, {})
    thread = getattr(plugin.fc_handler, "initialization_thread", None)
    if thread is not None and thread.ident is not None:
        thread.join(timeout=2)
        plugin._apply_fc_initialization_results()

    assert len(calls) == 2
    assert all(thread is not threading.current_thread() for thread in calls)
    assert plugin.fc_handler.is_update_eligible_fc(404) is True


def test_project_lookup_retries_after_network_recovery(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 503 is not a successful empty commander-project list."""
    load, plugin = edmc_plugin
    recovering = {"failed": True}

    def request(method: str, url: str, **kwargs: Any) -> SimpleNamespace:
        def raise_for_status() -> None:
            if recovering["failed"] and url.endswith("/active"):
                raise requests.HTTPError("HTTP 503")
        payload = [] if url.endswith("/fc/all") else [{"linkedFC": [{"marketId": 404}]}]
        return SimpleNamespace(status_code=200, raise_for_status=raise_for_status, json=lambda: payload)

    for name in ("get_all_cmdr_fcs", "get_commander_projects"):
        monkeypatch.setattr(plugin.api_client, name, getattr(type(plugin.api_client), name).__get__(plugin.api_client))
    plugin.api_client.session = SimpleNamespace(request=request)
    _journal(load)
    recovering["failed"] = False
    _journal(load)

    assert plugin.fc_handler.is_update_eligible_fc(404) is True


def test_commander_switch_preserves_observed_delivery(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    """A baseline completion after switching sends the old transfer exactly once."""
    load, plugin = edmc_plugin
    monkeypatch.setattr(plugin, "_ensure_api_worker", lambda: None)
    remote = {"steel": 100}
    writes = []
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote)})

    def supply(mid: int, delta: dict) -> dict:
        writes.append((mid, delta))
        remote["steel"] += delta["steel"]
        return dict(remote)

    monkeypatch.setattr(plugin.api_client, "supply_fc", supply)
    dock = {"StationType": "FleetCarrier", "MarketID": 303, "StationName": "CCC-333"}
    _journal(load, event="StartUp", **dock)
    entry = {"event": "CargoTransfer", "Transfers": [{"Type": "steel", "Count": 10, "Direction": "tocarrier"}]}
    load.journal_entry("Alpha", False, "Sol", "CCC-333", entry, dock)
    _journal(load, "Bravo", "LoadGame")
    plugin.overlay_carrier_tracking_enabled = True
    plugin.overlay_fc_selection = "303"
    plugin.overlay_project_linked_fcs = [{"marketId": 303}]
    plugin.overlay_fc_cargo_by_market = {303: {"steel": 500}}
    _drain_api(plugin)

    assert remote == {"steel": 110}
    assert writes == [(303, {"steel": 10})]
    assert set(plugin.fc_handler.linked_fcs) == {202, 404}
    assert plugin.overlay_fc_cargo_by_market == {303: {"steel": 500}}


@pytest.mark.parametrize("missing", ["dock_state_sync.py", "handlers/journal.py", "ui/overlay_row.py"])
def test_incomplete_update_keeps_the_working_plugin(edmc_plugin, tmp_path: Path, missing: str) -> None:
    """Reject a release missing an imported runtime module before replacing live files."""
    load, _plugin = edmc_plugin
    updater = importlib.import_module(f"{load.__package__}.version_check")
    root = Path(__file__).resolve().parents[1]
    live, staged, backup = (tmp_path / name for name in ("live", "staged", "backup"))
    live.mkdir()
    marker = live / "working-version.txt"
    marker.write_text("working version")
    for source in root.rglob("*.py"):
        relative = source.relative_to(root)
        if relative.parts[0] in {".venv", "tests", "scripts", "build", ".git"}:
            continue
        target = staged / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    (staged / missing).unlink()

    with pytest.raises(ValueError, match=missing):
        updater._install_staged_update(str(live), str(staged), str(backup))
    assert marker.read_text() == "working version"
    assert not backup.exists()


def test_transfers_during_superseded_link_lookup_are_preserved(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    """A loading commander's transfer finishes without polluting the next commander."""
    load, plugin = edmc_plugin
    monkeypatch.setattr(plugin, "_ensure_api_worker", lambda: None)
    started, release = threading.Event(), threading.Event()
    remote = {"steel": 100}

    def profiles(name: str) -> list:
        if name == "Alpha":
            started.set()
            assert release.wait(timeout=2), "Test did not release the Alpha lookup"
        return []

    def projects(name: str) -> list:
        return [{"linkedFC": [{"marketId": 303 if name == "Alpha" else 404}]}]

    def supply(mid: int, cargo: dict) -> dict:
        assert mid == 303
        remote["steel"] += cargo["steel"]
        return dict(remote)

    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", profiles)
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", projects)
    monkeypatch.setattr(plugin.api_client, "get_fc", lambda mid: {"marketId": mid, "cargo": dict(remote)})
    monkeypatch.setattr(plugin.api_client, "supply_fc", supply)
    dock = {"StationType": "FleetCarrier", "MarketID": 303}
    alpha = None
    try:
        load.journal_entry("Alpha", False, "Sol", "", {"event": "StartUp"}, dock)
        alpha = plugin.fc_handler
        assert started.wait(timeout=2), "Alpha lookup did not start"
        entry = {"event": "CargoTransfer", "Transfers": [{"Type": "steel", "Count": 10, "Direction": "tocarrier"}]}
        load.journal_entry("Alpha", False, "Sol", "", entry, dock)
        _journal(load, "Bravo", "LoadGame")
        assert set(plugin.fc_handler.linked_fcs) == {404}
    finally:
        release.set()
        if alpha is not None:
            alpha.initialization_thread.join(timeout=2)
    plugin._apply_fc_initialization_results()
    _drain_api(plugin)

    assert remote == {"steel": 110}
    assert set(plugin.fc_handler.linked_fcs) == {404}


def test_old_cancellation_cannot_end_a_new_cooldown(edmc_plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    """A delayed cancellation timer cannot clear a subsequent jump's cooldown display."""
    load, _plugin = edmc_plugin
    module = importlib.import_module(f"{load.__package__}.fc_jump_timer")
    clock = {"now": datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["now"]

    monkeypatch.setattr(module, "datetime", Clock)
    callbacks = []
    tracker = module.FleetCarrierJumpTracker(
        schedule_after=lambda delay, callback: callbacks.append(callback) or str(len(callbacks)),
    )
    tracker.handle_jump_requested({"CarrierID": 123, "DepartureTime": "2026-11-01T12:15:00Z"})
    tracker.handle_jump_cancelled({"CarrierID": 123})
    old_cancellation = callbacks[1]
    clock["now"] = datetime(2026, 11, 1, 12, 2, tzinfo=timezone.utc)
    tracker.handle_jump_requested({"CarrierID": 123, "DepartureTime": "2026-11-01T12:02:10Z"})
    clock["now"] = datetime(2026, 11, 1, 12, 2, 10, tzinfo=timezone.utc)
    callbacks[2]()
    old_cancellation()

    assert tracker.overlay_footer_lines() == ["> 123: Jump cooldown 04:50"]
