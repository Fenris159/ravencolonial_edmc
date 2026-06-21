"""Tests for shared exception group helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_spec = importlib.util.spec_from_file_location("ravencolonial_exc_utils", _ROOT / "exc_utils.py")
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)


def test_config_read_errors_include_import_and_attribute_errors() -> None:
    assert ImportError in _mod.CONFIG_READ_ERRORS
    assert AttributeError in _mod.CONFIG_READ_ERRORS
    assert ValueError in _mod.CONFIG_READ_ERRORS


def test_update_path_errors_cover_os_and_shutil_failures() -> None:
    assert OSError in _mod.UPDATE_PATH_ERRORS
    assert _mod.shutil.Error in _mod.UPDATE_PATH_ERRORS
