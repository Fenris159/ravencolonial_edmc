"""Tests for EDMC Modern Overlay dependency detection."""

from __future__ import annotations

import builtins
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_spec = importlib.util.spec_from_file_location(
    "ravencolonial_overlay_availability",
    _ROOT / "overlay" / "availability.py",
)
assert _spec and _spec.loader
_av = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_av)

OverlayDependencyStatus = _av.OverlayDependencyStatus
get_overlay_dependency_status = _av.get_overlay_dependency_status
import_overlay_api = _av.import_overlay_api
overlay_dependency_satisfied = _av.overlay_dependency_satisfied


def test_package_missing_when_overlay_plugin_not_importable() -> None:
    real_import = builtins.__import__

    def mock_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "overlay_plugin":
            raise ImportError("overlay_plugin not available")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", mock_import):
        assert get_overlay_dependency_status() == OverlayDependencyStatus.PACKAGE_MISSING
        assert overlay_dependency_satisfied() is False


def test_plugin_not_running_when_publisher_rejects_probe() -> None:
    api = MagicMock()
    api.send_overlay_message.return_value = False
    mod = types.ModuleType("overlay_plugin")
    mod.overlay_api = api
    with patch.dict(sys.modules, {"overlay_plugin": mod}):
        assert get_overlay_dependency_status() == OverlayDependencyStatus.PLUGIN_NOT_RUNNING
        assert overlay_dependency_satisfied() is True


def test_ok_when_probe_accepted() -> None:
    api = MagicMock()
    api.send_overlay_message.return_value = True
    mod = types.ModuleType("overlay_plugin")
    mod.overlay_api = api
    with patch.dict(sys.modules, {"overlay_plugin": mod}):
        assert get_overlay_dependency_status() == OverlayDependencyStatus.OK
        assert overlay_dependency_satisfied() is True
        assert api.send_overlay_message.call_count >= 1
        payload = api.send_overlay_message.call_args[0][0]
        assert payload["type"] == "legacy_clear"
        assert "ravencolonial-overlay-dependency-probe" in payload["id"]


def test_discovers_nested_overlay_plugin_from_plugins_folder(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    overlay_api_dir = plugin_root / "EDMCModernOverlay" / "overlay_plugin"
    overlay_api_dir.mkdir(parents=True)
    (overlay_api_dir / "__init__.py").write_text("", encoding="utf-8")
    (overlay_api_dir / "overlay_api.py").write_text(
        "def send_overlay_message(payload):\n"
        "    return payload.get('id') == 'ravencolonial-overlay-dependency-probe'\n",
        encoding="utf-8",
    )

    original_path = list(sys.path)
    for name in ("overlay_plugin", "overlay_plugin.overlay_api"):
        sys.modules.pop(name, None)
    try:
        sys.path = [str(plugin_root)]
        api = import_overlay_api()
        assert api.send_overlay_message({"id": "ravencolonial-overlay-dependency-probe"}) is True
        assert str(plugin_root / "EDMCModernOverlay") in sys.path
    finally:
        sys.path = original_path
        for name in ("overlay_plugin", "overlay_plugin.overlay_api"):
            sys.modules.pop(name, None)


def test_includes_linux_edmc_plugin_defaults(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    home = tmp_path / "home" / "cmdr"
    expected = home / ".local" / "share" / "EDMarketConnector" / "plugins"
    expected.mkdir(parents=True)

    monkeypatch.setattr(Path, "home", lambda: home)

    candidates = _av._candidate_plugin_parents()
    assert expected.resolve() in candidates
