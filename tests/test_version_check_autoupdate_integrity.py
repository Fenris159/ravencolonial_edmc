"""Auto-update package integrity checks."""

from __future__ import annotations

import io
import logging
import os
import sys
import types
import hashlib
import zipfile
from pathlib import Path

import pytest

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

from RavenColonail_EDMC import version_check as vc  # noqa: E402
from RavenColonail_EDMC.version_check import (  # noqa: E402
    _backup_dir_for_current_version,
    _expected_sha256_from_digest,
    _install_staged_update,
    _release_bundled_oxanium_font_for_update,
    _rename_live_plugin_to_backup,
    _rename_path_with_retries,
    _staged_dir_for_target_version,
    _verify_downloaded_zip_digest,
    stable_releases_with_zip_asset,
    _validate_plugin_source_tree,
)


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


def _required_tree_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        files = [
            "__init__.py",
            "load.py",
            "create_project_dialog.py",
            "version_check.py",
            "api/__init__.py",
            "api/client.py",
            "plugin_config/__init__.py",
            "plugin_config/settings.py",
            "handlers/__init__.py",
            "ui/__init__.py",
            "marker.txt",
        ]
        for name in files:
            zf.writestr(f"RavenColonial_EDMC/{name}", "new")
    return buf.getvalue()


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


def test_backup_dir_uses_plugin_name_and_current_version(tmp_path: Path) -> None:
    live_dir = tmp_path / "plugins" / "RavenColonial_EDMC"
    backup_dir = Path(
        _backup_dir_for_current_version(
            str(live_dir),
            "RavenColonial_EDMC",
            "1.8.0",
        )
    )

    assert backup_dir.parent == live_dir.parent
    assert backup_dir.name == "RavenColonial_EDMC-v1.8.0.backup.disabled"


def test_backup_dir_sanitizes_unusual_plugin_or_version_text(tmp_path: Path) -> None:
    live_dir = tmp_path / "plugins" / "RavenColonial_EDMC"
    backup_dir = Path(
        _backup_dir_for_current_version(
            str(live_dir),
            "RavenColonial EDMC!",
            "v1.8.0 beta",
        )
    )

    assert backup_dir.name == "RavenColonial_EDMC-v1.8.0_beta.backup.disabled"


def test_staged_dir_uses_plugin_name_and_target_version(tmp_path: Path) -> None:
    live_dir = tmp_path / "plugins" / "RavenColonial_EDMC"
    staged_dir = Path(
        _staged_dir_for_target_version(
            str(live_dir),
            "RavenColonial_EDMC",
            "v1.8.1",
        )
    )

    assert staged_dir.parent == live_dir.parent
    assert staged_dir.name == "RavenColonial_EDMC-v1.8.1.staged.disabled"


def test_stable_release_zip_asset_keeps_github_digest() -> None:
    releases = [
        {
            "tag_name": "v1.8.1",
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": "RavenColonial_EDMC-v1.8.1.zip",
                    "browser_download_url": "https://example.invalid/RavenColonial_EDMC-v1.8.1.zip",
                    "digest": "sha256:" + "a" * 64,
                }
            ],
        }
    ]

    pairs = stable_releases_with_zip_asset(releases, logger=None, allow_prerelease=False)

    assert pairs == [
        (
            releases[0],
            "https://example.invalid/RavenColonial_EDMC-v1.8.1.zip",
            "sha256:" + "a" * 64,
        )
    ]


def test_expected_sha256_from_github_digest_formats() -> None:
    sha = "A" * 64

    assert _expected_sha256_from_digest(f"sha256:{sha}") == "a" * 64
    assert _expected_sha256_from_digest(sha) == "a" * 64
    assert _expected_sha256_from_digest("sha512:" + "a" * 128) is None
    assert _expected_sha256_from_digest(None) is None


def test_verify_downloaded_zip_digest_accepts_matching_sha256() -> None:
    content = b"release zip bytes"
    digest = "sha256:" + hashlib.sha256(content).hexdigest()

    _verify_downloaded_zip_digest(content, digest)


def test_verify_downloaded_zip_digest_rejects_mismatch() -> None:
    with pytest.raises(ValueError, match="SHA-256 verification"):
        _verify_downloaded_zip_digest(b"release zip bytes", "sha256:" + "0" * 64)


def test_verify_downloaded_zip_digest_allows_missing_digest() -> None:
    _verify_downloaded_zip_digest(b"release zip bytes", None)


def test_run_autoupdate_stages_package_without_replacing_live_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_dir = tmp_path / "plugins" / "RavenColonial_EDMC"
    live_dir.mkdir(parents=True)
    _write_required_tree(live_dir, include_client=True)
    (live_dir / "marker.txt").write_text("old", encoding="utf-8")
    monkeypatch.setattr(vc, "__file__", str(live_dir / "version_check.py"))
    monkeypatch.setattr(vc, "CURRENT_VERSION", lambda: "1.8.0")

    content = _required_tree_zip_bytes()

    class FakeResponse:
        status_code = 200

    FakeResponse.content = content

    class FakeSession:
        def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(vc.timeout_session, "new_session", lambda timeout=10: FakeSession())
    update = vc.UpdateInfo(logging.getLogger("test"), "RavenColonial_EDMC")
    update._data = vc.UpdateInfo.Data(
        "v1.8.1",
        "https://example.invalid/release",
        "https://example.invalid/update.zip",
        "sha256:" + hashlib.sha256(content).hexdigest(),
    )

    update.run_autoupdate()

    staged_dir = tmp_path / "plugins" / "RavenColonial_EDMC-v1.8.1.staged.disabled"
    backup_dir = tmp_path / "plugins" / "RavenColonial_EDMC-v1.8.0.backup.disabled"
    assert (live_dir / "marker.txt").read_text(encoding="utf-8") == "old"
    assert (staged_dir / "marker.txt").read_text(encoding="utf-8") == "new"
    assert update._staged_update_dir == str(staged_dir)
    assert not backup_dir.exists()


def test_release_bundled_oxanium_uses_loaded_theme_module(monkeypatch: pytest.MonkeyPatch) -> None:
    called = []
    module_name = f"{vc.__package__}.ui.edmc_theme"
    fake_theme = types.SimpleNamespace(release_bundled_oxanium_font=lambda: called.append(True))
    monkeypatch.setitem(sys.modules, module_name, fake_theme)

    _release_bundled_oxanium_font_for_update()

    assert called == [True]


def test_backup_rename_moves_live_plugin_to_backup(tmp_path: Path) -> None:
    live_dir = tmp_path / "plugins" / "RavenColonial_EDMC"
    live_dir.mkdir(parents=True)
    (live_dir / "load.py").write_text("live", encoding="utf-8")
    backup_dir = tmp_path / "plugins" / "RavenColonial_EDMC-v1.8.0.backup.disabled"

    _rename_live_plugin_to_backup(str(live_dir), str(backup_dir))

    assert not live_dir.exists()
    assert (backup_dir / "load.py").read_text(encoding="utf-8") == "live"


def test_backup_rename_failure_leaves_live_plugin_intact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_dir = tmp_path / "plugins" / "RavenColonial_EDMC"
    live_dir.mkdir(parents=True)
    (live_dir / "load.py").write_text("live", encoding="utf-8")
    backup_dir = tmp_path / "plugins" / "RavenColonial_EDMC-v1.8.0.backup.disabled"

    def fail_rename(src: str, dst: str) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(os, "rename", fail_rename)

    with pytest.raises(PermissionError):
        _rename_live_plugin_to_backup(str(live_dir), str(backup_dir))

    assert (live_dir / "load.py").read_text(encoding="utf-8") == "live"
    assert not backup_dir.exists()


def test_rename_retries_transient_permission_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    (src / "load.py").write_text("live", encoding="utf-8")
    calls = []
    real_rename = os.rename

    def flaky_rename(from_path: str, to_path: str) -> None:
        calls.append((from_path, to_path))
        if len(calls) == 1:
            raise PermissionError("transient lock")
        real_rename(from_path, to_path)

    monkeypatch.setattr(os, "rename", flaky_rename)
    monkeypatch.setattr(vc, "_RENAME_RETRY_DELAYS_S", (0.0,))

    _rename_path_with_retries(str(src), str(dst), logging.getLogger("test"), action="test rename")

    assert len(calls) == 2
    assert not src.exists()
    assert (dst / "load.py").read_text(encoding="utf-8") == "live"


def test_install_staged_update_promotes_new_tree_and_deletes_backup(tmp_path: Path) -> None:
    live_dir = tmp_path / "plugins" / "RavenColonial_EDMC"
    staged_dir = tmp_path / "plugins" / "RavenColonial_EDMC-v1.8.1.staged.disabled"
    backup_dir = tmp_path / "plugins" / "RavenColonial_EDMC-v1.8.0.backup.disabled"
    live_dir.mkdir(parents=True)
    staged_dir.mkdir()
    _write_required_tree(live_dir, include_client=True)
    _write_required_tree(staged_dir, include_client=True)
    (live_dir / "marker.txt").write_text("old", encoding="utf-8")
    (staged_dir / "marker.txt").write_text("new", encoding="utf-8")

    _install_staged_update(str(live_dir), str(staged_dir), str(backup_dir))

    assert (live_dir / "marker.txt").read_text(encoding="utf-8") == "new"
    assert not staged_dir.exists()
    assert not backup_dir.exists()


def test_install_staged_update_rename_failure_leaves_live_and_staged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_dir = tmp_path / "plugins" / "RavenColonial_EDMC"
    staged_dir = tmp_path / "plugins" / "RavenColonial_EDMC-v1.8.1.staged.disabled"
    backup_dir = tmp_path / "plugins" / "RavenColonial_EDMC-v1.8.0.backup.disabled"
    live_dir.mkdir(parents=True)
    staged_dir.mkdir()
    _write_required_tree(live_dir, include_client=True)
    _write_required_tree(staged_dir, include_client=True)
    (live_dir / "marker.txt").write_text("old", encoding="utf-8")
    (staged_dir / "marker.txt").write_text("new", encoding="utf-8")

    def fail_rename(src: str, dst: str) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(os, "rename", fail_rename)

    with pytest.raises(PermissionError):
        _install_staged_update(str(live_dir), str(staged_dir), str(backup_dir))

    assert (live_dir / "marker.txt").read_text(encoding="utf-8") == "old"
    assert (staged_dir / "marker.txt").read_text(encoding="utf-8") == "new"
    assert not backup_dir.exists()
