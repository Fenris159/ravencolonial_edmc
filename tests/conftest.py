"""Shared pytest bootstrap for checkout-path-independent package imports."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from pathlib import Path

PACKAGE_NAME = "RavenColonail_EDMC"
ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT.parent

if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

if PACKAGE_NAME not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not create package spec for {PACKAGE_NAME}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)


def edmc_plugin_context(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[ModuleType, Any]]:
    """Load an isolated plugin with only EDMC and remote I/O replaced."""
    import tkinter as tk

    original_tk_root = tk._default_root
    settings = SimpleNamespace(
        get_str=lambda key: "test-key" if key == "ravencolonial_api_key" else "",
        get_bool=lambda key, **kwargs: False,
        shutting_down=False,
    )
    stubs = {
        "config": {"appname": "test", "config": settings},
        "companion": {"CAPIData": object},
        "l10n": {"translations": SimpleNamespace(tl=lambda text, **kwargs: text)},
        "plug": {"show_error": lambda message: None},
        "myNotebook": {"Frame": tk.Frame, "Notebook": tk.Frame},
        "timeout_session": {"new_session": lambda **kwargs: SimpleNamespace(headers={})},
    }
    for name, attributes in stubs.items():
        module = ModuleType(name)
        module.__dict__.update(attributes)
        monkeypatch.setitem(sys.modules, name, module)

    root = Path(__file__).resolve().parents[1]
    package_name = "_commander_switch_plugin"
    spec = importlib.util.spec_from_file_location(
        package_name, root / "__init__.py", submodule_search_locations=[str(root)],
    )
    package = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, package_name, package)
    spec.loader.exec_module(package)
    load = importlib.import_module(f"{package_name}.load")
    plugin = load.RavencolonialPlugin()
    profiles = {
        "Alpha": [{"marketId": 101, "name": "AAA-111"}],
        "Bravo": [{"marketId": 202, "name": "BBB-222"}],
        "Unlinked": [],
    }
    projects = {
        "Alpha": [{"buildId": "alpha-build", "linkedFC": [{"marketId": 303}]}],
        "Bravo": [{"buildId": "bravo-build", "linkedFC": [{"marketId": 404}]}],
        "Unlinked": [],
    }
    monkeypatch.setattr(plugin.api_client, "get_all_cmdr_fcs", lambda name: profiles[name])
    monkeypatch.setattr(plugin.api_client, "get_commander_projects", lambda name: projects[name])
    monkeypatch.setattr(load.capi_cache, "write", lambda *args: None)
    monkeypatch.setattr(load.time, "time", lambda: 1000.0)
    monkeypatch.setattr(load.time, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(load.time, "sleep", lambda duration: None)
    load.this = plugin
    yield load, plugin
    for thread in getattr(plugin, "_fc_initialization_threads", []):
        if thread.ident is not None:
            thread.join(timeout=2)
    load._close_ui_surfaces_on_stop()
    if tk._default_root is not None and tk._default_root is not original_tk_root:
        tk._default_root.destroy()
    for name in list(sys.modules):
        if name.startswith(f"{package_name}."):
            del sys.modules[name]


@pytest.fixture
def edmc_plugin(monkeypatch: pytest.MonkeyPatch):
    """Provide an isolated plugin with EDMC and HTTP boundaries replaced."""
    yield from edmc_plugin_context(monkeypatch)


def settle_commander_links(plugin: Any) -> None:
    """Wait for the real network worker and apply its result on the test's main thread."""
    thread = getattr(plugin.fc_handler, "initialization_thread", None)
    if thread is not None:
        thread.join(timeout=2)
        assert not thread.is_alive(), "Commander lookup worker did not finish"
        plugin._apply_fc_initialization_results()
