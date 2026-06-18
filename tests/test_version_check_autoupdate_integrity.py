"""Auto-update package integrity checks."""

from __future__ import annotations

import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PARENT = _ROOT.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

if "timeout_session" not in sys.modules:
    timeout_session = types.ModuleType("timeout_session")

    class _FakeSession:
        def __init__(self) -> None:
            self.headers = {}

        def get(self, *args, **kwargs):
            raise RuntimeError("network not available in unit test")

    timeout_session.new_session = lambda timeout=10: _FakeSession()
    sys.modules["timeout_session"] = timeout_session

from RavenColonail_EDMC.version_check import _validate_plugin_source_tree  # noqa: E402


def _write_required_tree(root: Path, *, include_client: bool) -> None:
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "load.py").write_text("", encoding="utf-8")
    (root / "create_project_dialog.py").write_text("", encoding="utf-8")
    (root / "version_check.py").write_text("", encoding="utf-8")
    (root / "api").mkdir()
    (root / "api" / "__init__.py").write_text("", encoding="utf-8")
    if include_client:
        (root / "api" / "client.py").write_text("", encoding="utf-8")
    (root / "plugin_config").mkdir()
    (root / "plugin_config" / "__init__.py").write_text("", encoding="utf-8")
    (root / "plugin_config" / "settings.py").write_text("", encoding="utf-8")
    (root / "handlers").mkdir()
    (root / "handlers" / "__init__.py").write_text("", encoding="utf-8")
    (root / "ui").mkdir()
    (root / "ui" / "__init__.py").write_text("", encoding="utf-8")


def test_validate_plugin_source_tree_accepts_complete_layout(tmp_path: Path) -> None:
    _write_required_tree(tmp_path, include_client=True)

    _validate_plugin_source_tree(str(tmp_path))


def test_validate_plugin_source_tree_rejects_missing_api_client(tmp_path: Path) -> None:
    _write_required_tree(tmp_path, include_client=False)

    try:
        _validate_plugin_source_tree(str(tmp_path))
    except ValueError as exc:
        assert "api/client.py" in str(exc)
    else:
        raise AssertionError("expected ValueError for missing api/client.py")
