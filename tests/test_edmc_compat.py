"""Tests for advisory EDMC core version compatibility checks."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import semantic_version

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_spec = importlib.util.spec_from_file_location("ravencolonial_edmc_compat", _ROOT / "edmc_compat.py")
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

EdmcCompatResult = _mod.EdmcCompatResult
MIN_SUPPORTED_EDMC_VERSION = _mod.MIN_SUPPORTED_EDMC_VERSION
check_edmc_compatibility = _mod.check_edmc_compatibility
resolve_edmc_core_version = _mod.resolve_edmc_core_version


def test_resolve_edmc_core_version_from_callable(monkeypatch) -> None:
    version = semantic_version.Version("6.1.2")
    fake_config = types.ModuleType("config")
    fake_config.appversion = lambda: version
    monkeypatch.setitem(sys.modules, "config", fake_config)

    assert resolve_edmc_core_version() == version


def test_resolve_edmc_core_version_from_string(monkeypatch) -> None:
    fake_config = types.ModuleType("config")
    fake_config.appversion = "6.1.2"
    monkeypatch.setitem(sys.modules, "config", fake_config)

    resolved = resolve_edmc_core_version()
    assert resolved == semantic_version.Version("6.1.2")


def test_check_ok_at_minimum_supported_version() -> None:
    with patch.object(_mod, "resolve_edmc_core_version", return_value=semantic_version.Version("6.1.2")):
        result = check_edmc_compatibility()

    assert result == EdmcCompatResult(core_version="6.1.2", level="ok")


def test_check_ok_above_minimum_supported_version() -> None:
    with patch.object(_mod, "resolve_edmc_core_version", return_value=semantic_version.Version("6.2.0")):
        result = check_edmc_compatibility()

    assert result.level == "ok"
    assert result.core_version == "6.2.0"


def test_check_advisory_below_minimum_supported_version() -> None:
    with patch.object(_mod, "resolve_edmc_core_version", return_value=semantic_version.Version("6.1.1")):
        result = check_edmc_compatibility()

    assert result == EdmcCompatResult(
        core_version="6.1.1",
        level="advisory",
        reason="below_minimum",
    )


def test_check_blocking_for_known_incompatible_version() -> None:
    with patch.object(_mod, "KNOWN_INCOMPATIBLE_EDMC_VERSIONS", ("6.0.0",)):
        with patch.object(_mod, "resolve_edmc_core_version", return_value=semantic_version.Version("6.0.0")):
            result = check_edmc_compatibility()

    assert result == EdmcCompatResult(
        core_version="6.0.0",
        level="blocking",
        reason="known_incompatible",
    )


def test_check_ok_when_core_version_unresolved() -> None:
    with patch.object(_mod, "resolve_edmc_core_version", return_value=None):
        result = check_edmc_compatibility()

    assert result == EdmcCompatResult(level="ok", reason="unresolved")


def test_minimum_supported_version_matches_readme() -> None:
    assert MIN_SUPPORTED_EDMC_VERSION == "6.1.2"
