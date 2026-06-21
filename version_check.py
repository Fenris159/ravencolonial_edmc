"""
Version checking and auto-update module for RavenColonial_EDMC
Adapted from EDMC-RavenColonial plugin by CMDR-WDX
"""

import dataclasses
import errno
import hashlib
import importlib
import importlib.util
import re
import shutil
import sys
import time
import zipfile
from logging import Logger
import os
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

# Git tags that ship from ``main`` / production: vX.Y.Z only (no -rc / -dev suffixes).
_STABLE_SEMVER_TAG = re.compile(r"^v\d+\.\d+\.\d+$")

import timeout_session

from . import capi_cache
from . import plugin_file_log

# GitHub repo for releases / auto-update (browser + API)
GITHUB_REPO = "Fenris159/ravencolonial_edmc"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"


def is_stable_release_tag_name(tag: str) -> bool:
    """
    True only for production semver Git tags ``vMAJOR.MINOR.PATCH`` (no suffix).

    Excludes pre-release style tags (``v1.0.0-rc.1``, ``v1.0.0-dev``) and any
    non-matching name. Markers that do not start with ``v`` (e.g. ``dev-1.7.0``)
    are excluded and, with workflow ``on.push.tags: [v*]``, do not trigger the
    release build job at all.
    """
    return bool(tag and _STABLE_SEMVER_TAG.fullmatch(tag.strip()))


def _zip_asset_info_for_tag(release: dict, tag: str) -> Optional[Tuple[str, Optional[str]]]:
    """``(browser_download_url, digest)`` for ``RavenColonial_EDMC-v{version}.zip`` style asset."""
    assets = release.get("assets", [])
    for asset in assets:
        asset_name = asset.get("name", "")
        if asset_name.endswith(".zip") and tag.lstrip("v") in asset_name:
            asset_url = asset.get("browser_download_url")
            if not asset_url:
                return None
            return asset_url, asset.get("digest")
    return None


def _expected_sha256_from_digest(digest: Optional[str]) -> Optional[str]:
    """Normalize GitHub release asset ``digest`` metadata to a SHA-256 hex string."""
    if not digest:
        return None
    value = digest.strip().lower()
    if value.startswith("sha256:"):
        value = value.split(":", 1)[1].strip()
    if re.fullmatch(r"[0-9a-f]{64}", value):
        return value
    return None


def _verify_downloaded_zip_digest(
    content: bytes,
    expected_digest: Optional[str],
    logger: Optional[Logger] = None,
) -> None:
    """Verify downloaded release bytes against GitHub's SHA-256 asset digest when available."""
    expected_sha256 = _expected_sha256_from_digest(expected_digest)
    if expected_sha256 is None:
        if expected_digest:
            if logger:
                logger.warning("Ignoring unsupported GitHub release asset digest format: %r", expected_digest)
        else:
            if logger:
                logger.warning("GitHub release asset has no SHA-256 digest; continuing without checksum verification")
        return

    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(
            "Downloaded update ZIP failed SHA-256 verification "
            f"(expected {expected_sha256}, got {actual_sha256})"
        )
    if logger:
        logger.info("Verified update ZIP SHA-256 digest: %s", actual_sha256)


def stable_releases_with_zip_asset(
    releases: list,
    *,
    logger: Optional[Logger],
    allow_prerelease: bool,
) -> List[Tuple[dict, str, Optional[str]]]:
    """
    Filter GitHub ``/releases`` JSON to draft-stable tags with a matching plugin zip.

    Respects GitHub's ``prerelease`` flag only when ``allow_prerelease`` is True.
    """
    out: List[Tuple[dict, str, Optional[str]]] = []
    for release in releases:
        if release.get("draft"):
            continue
        tag = release.get("tag_name", "")
        if not tag:
            continue
        if not is_stable_release_tag_name(tag):
            if logger:
                logger.debug(
                    "Skipping release tag %r (not stable vX.Y.Z - dev/pre markers ignored)",
                    tag,
                )
            continue
        if release.get("prerelease", False) and not allow_prerelease:
            if logger:
                logger.debug("Skipping pre-release %s (pre-releases disabled)", tag)
            continue
        if release.get("prerelease", False) and allow_prerelease and logger:
            logger.debug("Considering pre-release %s (pre-releases enabled)", tag)
        asset_info = _zip_asset_info_for_tag(release, tag)
        if not asset_info:
            if logger:
                logger.warning("No ZIP asset found for release %s", tag)
            continue
        asset_url, asset_digest = asset_info
        out.append((release, asset_url, asset_digest))
    return out


def latest_stable_release_version_string(logger: Optional[Logger] = None) -> Optional[str]:
    """
    Newest stable ``vX.Y.Z`` that has a RavenColonial zip asset (for settings / banner).

    Ignores draft releases, GitHub ``prerelease`` releases, and tags that are not
    strict ``vMAJOR.MINOR.PATCH`` (same rules as in-app auto-update).
    """
    try:
        session = timeout_session.new_session(timeout=10)
        response = session.get(RELEASES_URL)
        if response.status_code != 200:
            if logger:
                logger.warning("GitHub API returned status %s", response.status_code)
            return None
        releases = response.json()
        pairs = stable_releases_with_zip_asset(releases, logger=logger, allow_prerelease=False)
        if not pairs:
            return None
        highest: Optional[str] = None
        for release, _url, _digest in pairs:
            tag = release.get("tag_name", "").lstrip("v")
            if highest is None or compare_versions(highest, tag, logger):
                highest = tag
        return highest
    except Exception as e:
        if logger:
            logger.debug("latest_stable_release_version_string failed: %s", e)
        return None


def _safe_extract_zip(zip_ref: zipfile.ZipFile, dest_dir: str) -> None:
    """Extract ZIP under ``dest_dir``, rejecting path traversal (Zip Slip)."""
    dest = Path(dest_dir).resolve()
    for name in zip_ref.namelist():
        target = (dest / name).resolve()
        try:
            target.relative_to(dest)
        except ValueError as e:
            raise ValueError(f"Unsafe path in update archive: {name!r}") from e
    zip_ref.extractall(os.fspath(dest))


def safe_remove_backup(backup_dir, logger):
    """Safely remove backup directory, handling symbolic links"""
    if os.path.exists(backup_dir):
        if os.path.islink(backup_dir):
            os.unlink(backup_dir)  # Remove symbolic link
            if logger:
                logger.debug(f"Removed symbolic link backup: {backup_dir}")
        elif os.path.isdir(backup_dir):
            shutil.rmtree(backup_dir)  # Remove directory
            if logger:
                logger.debug(f"Removed directory backup: {backup_dir}")


def _safe_backup_name_component(value: str) -> str:
    """Filesystem-safe, recognizable fragment for auto-update backup names."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "unknown"


def _backup_dir_for_current_version(live_file_dir: str, plugin_name: str, current_version: str) -> str:
    """
    Sibling backup path for rollback during auto-update.

    The ``.disabled`` suffix prevents EDMC from loading the backup as another plugin,
    while the plugin/version prefix keeps the folder recognizable if rollback fails
    and the user sees it in the plugins directory.
    """
    backup_name = (
        f"{_safe_backup_name_component(plugin_name)}"
        f"-v{_safe_backup_name_component(current_version.lstrip('v'))}"
        ".backup.disabled"
    )
    return os.path.normpath(os.path.join(live_file_dir, "..", backup_name))


def _staged_dir_for_target_version(live_file_dir: str, plugin_name: str, target_version: str) -> str:
    """
    Sibling staging path for an update that should be installed on shutdown.

    The ``.disabled`` suffix prevents EDMC from loading the staged package as a
    second plugin if the user opens the plugins directory or restarts before the
    old plugin has promoted it.
    """
    staged_name = (
        f"{_safe_backup_name_component(plugin_name)}"
        f"-v{_safe_backup_name_component(target_version.lstrip('v'))}"
        ".staged.disabled"
    )
    return os.path.normpath(os.path.join(live_file_dir, "..", staged_name))


def _release_bundled_oxanium_font_for_update() -> None:
    """Release bundled font handles from the live UI theme module."""
    if __package__:
        module_name = f"{__package__}.ui.edmc_theme"
        module = sys.modules.get(module_name)
        if module is None:
            module = importlib.import_module(".ui.edmc_theme", __package__)
        module.release_bundled_oxanium_font()
        return

    # Standalone fallback for direct script-style imports.
    theme_path = Path(__file__).resolve().parent / "ui" / "edmc_theme.py"
    spec = importlib.util.spec_from_file_location("_ravencolonial_edmc_theme_update", theme_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {theme_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.release_bundled_oxanium_font()


_RENAME_RETRY_DELAYS_S = (0.15, 0.35, 0.75)


def _rename_path_with_retries(
    src: str,
    dst: str,
    logger: Optional[Logger] = None,
    *,
    action: str,
) -> None:
    for attempt in range(len(_RENAME_RETRY_DELAYS_S) + 1):
        try:
            os.rename(src, dst)
            return
        except OSError as e:
            if getattr(e, "errno", None) == errno.EXDEV or attempt >= len(_RENAME_RETRY_DELAYS_S):
                raise
            delay = _RENAME_RETRY_DELAYS_S[attempt]
            if logger:
                logger.warning(
                    "%s failed on attempt %s; retrying in %.2fs: %s",
                    action,
                    attempt + 1,
                    delay,
                    e,
                )
            time.sleep(delay)


def _rename_live_plugin_to_backup(live_file_dir: str, backup_dir: str, logger: Optional[Logger] = None) -> None:
    """
    Rename the live plugin directory to its sibling backup path.

    The updater intentionally avoids ``shutil.move`` here. On Windows, when a
    file under the plugin directory is locked, ``shutil.move`` falls back to a
    copy-then-delete flow after ``os.rename`` fails. That fallback can leave the
    live plugin partially deleted, which is worse than a clean failed update.
    """
    if logger:
        logger.info(f"Backing up current version: {live_file_dir} -> {backup_dir}")
    _rename_path_with_retries(live_file_dir, backup_dir, logger, action="Backup rename")


def _install_staged_update(
    live_file_dir: str,
    staged_dir: str,
    backup_dir: str,
    logger: Optional[Logger] = None,
) -> None:
    """
    Promote a validated staged update into the live plugin folder.

    This runs during plugin shutdown after runtime resources have been released.
    The old live folder is renamed to a disabled backup first; only after the
    staged tree is promoted and validated is the backup deleted.
    """
    _validate_plugin_source_tree(staged_dir, logger)
    safe_remove_backup(backup_dir, logger)

    backup_moved = False
    try:
        _rename_live_plugin_to_backup(live_file_dir, backup_dir, logger)
        backup_moved = True

        if logger:
            logger.info("Promoting staged update: %s -> %s", staged_dir, live_file_dir)
        _rename_path_with_retries(staged_dir, live_file_dir, logger, action="Staged update promotion")
        _validate_plugin_source_tree(live_file_dir, logger)

        if logger:
            logger.info("Staged update installed; removing backup")
        try:
            safe_remove_backup(backup_dir, logger)
        except Exception as cleanup_ex:
            if logger:
                logger.warning(
                    "Update installed but backup cleanup failed: %s",
                    cleanup_ex,
                    exc_info=True,
                )
    except Exception:
        if logger:
            logger.error("Staged update install failed; attempting rollback", exc_info=True)
        if backup_moved and os.path.exists(backup_dir):
            if os.path.exists(live_file_dir):
                shutil.rmtree(live_file_dir)
            _rename_path_with_retries(backup_dir, live_file_dir, logger, action="Rollback restore")
            if logger:
                logger.info("Rollback restored previous plugin folder")
        raise


_REQUIRED_PLUGIN_PATHS = (
    ("load.py",),
    ("__init__.py",),
    ("create_project_dialog.py",),
    ("version_check.py",),
    ("api", "__init__.py"),
    ("api", "client.py"),
    ("plugin_config", "__init__.py"),
    ("plugin_config", "settings.py"),
    ("handlers", "__init__.py"),
    ("ui", "__init__.py"),
)


def _validate_plugin_source_tree(plugin_source_dir: str, logger: Optional[Logger] = None) -> None:
    """
    Ensure an extracted update contains the package files required for startup.

    The updater has to guard against incomplete release assets or malformed
    extraction results that would otherwise install a plugin which then fails
    on the next EDMC restart.
    """
    base = Path(plugin_source_dir)
    missing = ["/".join(parts) for parts in _REQUIRED_PLUGIN_PATHS if not (base.joinpath(*parts)).is_file()]
    if missing:
        if logger:
            logger.error(
                "Update package is missing required plugin files under %s: %s",
                plugin_source_dir,
                ", ".join(missing),
            )
        raise ValueError(
            "Update package is incomplete; missing required files: " + ", ".join(missing)
        )


def compare_versions(current: str, latest: str, logger=None) -> bool:
    """
    Compare version strings to see if latest is newer than current.
    Uses simple semantic versioning comparison (major.minor.patch).

    :param current: Current version string (e.g., "1.5.2")
    :param latest: Latest version string (e.g., "1.5.3")
    :return: True if latest is newer than current
    """
    try:
        # Remove 'v' prefix if present
        current = current.lstrip('v')
        latest = latest.lstrip('v')

        # Extract numeric parts and check for pre-release suffixes
        def parse_version(version: str):
            parts = version.split('.')
            numeric_parts = []
            is_prerelease = False

            for part in parts:
                # Extract only the leading digits from each part
                numeric_part = ''
                suffix_part = ''
                digit_collection_complete = False

                for char in part:
                    if char.isdigit() and not digit_collection_complete:
                        numeric_part += char
                    else:
                        digit_collection_complete = True
                        suffix_part += char.lower()

                if numeric_part:
                    numeric_parts.append(numeric_part)
                    # Check if this part has a pre-release suffix
                    if logger:
                        logger.debug(f"Checking part '{part}' - numeric: '{numeric_part}', suffix: '{suffix_part}'")
                    if any(suffix in suffix_part for suffix in ['alpha', 'beta', 'rc', 'pre']):
                        is_prerelease = True
                        if logger:
                            logger.debug(f"Found prerelease suffix in '{suffix_part}'")

            return numeric_parts, is_prerelease

        current_numeric, current_is_prerelease = parse_version(current)
        latest_numeric, latest_is_prerelease = parse_version(latest)

        if logger:
            logger.debug(
                "Parsed versions - Current: %s (prerelease: %s), Latest: %s (prerelease: %s)",
                current_numeric,
                current_is_prerelease,
                latest_numeric,
                latest_is_prerelease,
            )

        # Parse version strings into tuples of integers
        # e.g., "1.5.2" becomes (1, 5, 2)
        current_parts = tuple(int(x) for x in current_numeric[:3])
        latest_parts = tuple(int(x) for x in latest_numeric[:3])

        if logger:
            logger.debug(f"Version tuples - Current: {current_parts}, Latest: {latest_parts}")

        # Compare numeric versions
        if latest_parts > current_parts:
            if logger:
                logger.debug(f"Latest is newer numerically: {latest_parts} > {current_parts}")
            return True
        elif latest_parts < current_parts:
            if logger:
                logger.debug(f"Latest is older numerically: {latest_parts} < {current_parts}")
            return False
        else:
            # Same numeric version - stable release is newer than prerelease
            if logger:
                logger.debug(
                    "Same numeric version, checking prerelease status - "
                    "Latest prerelease: %s, Current prerelease: %s",
                    latest_is_prerelease,
                    current_is_prerelease,
                )
            if not latest_is_prerelease and current_is_prerelease:
                if logger:
                    logger.debug("Stable release is newer than prerelease")
                return True
            if logger:
                logger.debug("No update needed")
            return False

    except (ValueError, AttributeError):
        # If parsing fails, assume no update
        return False


def CURRENT_VERSION():
    """
    Get current plugin version
    This should match the plugin_version in load.py
    """
    from .plugin_config import PluginConfig
    return PluginConfig.VERSION


class UpdateInfo:
    """Handles version checking and auto-update functionality"""

    @dataclasses.dataclass
    class Data:
        """Release data from GitHub"""
        tag_name: str
        browser_link: str
        zip_link: str
        zip_digest: Optional[str] = None

    def __init__(self, logger: Logger, plugin_name: str, allow_prerelease=False):
        self._logger = logger
        self.plugin_name = plugin_name
        self._beta = allow_prerelease
        self._data: Optional[UpdateInfo.Data] = None
        self._staged_update_dir: Optional[str] = None
        self._staged_update_version: Optional[str] = None

    @property
    def remote_version(self):
        """Get the remote version tag"""
        if self._data is None:
            return None
        return self._data.tag_name

    def check(self) -> Optional[Data]:
        """
        Check GitHub for latest release
        Thread-safe - should be called from background thread

        :return: UpdateInfo.Data if release found, None otherwise
        """
        try:
            self._logger.info(f"Checking for updates at {RELEASES_URL}")
            session = timeout_session.new_session(timeout=10)
            response = session.get(RELEASES_URL)

            if response.status_code != 200:
                self._logger.warning(f"GitHub API returned status {response.status_code}")
                return None

            releases = response.json()

            suitable_releases = stable_releases_with_zip_asset(
                releases,
                logger=self._logger,
                allow_prerelease=self._beta,
            )

            if not suitable_releases:
                self._logger.info("No suitable releases found")
                return None

            # Pick the highest version from suitable releases
            suitable_release = None
            selected_asset_url = None
            selected_asset_digest = None
            highest_version = None

            for release, asset_url, asset_digest in suitable_releases:
                tag = release.get('tag_name', '').lstrip('v')

                if highest_version is None:
                    highest_version = tag
                    suitable_release = release
                    selected_asset_url = asset_url
                    selected_asset_digest = asset_digest
                else:
                    # Compare versions
                    if compare_versions(highest_version, tag, self._logger):
                        highest_version = tag
                        suitable_release = release
                        selected_asset_url = asset_url
                        selected_asset_digest = asset_digest
                        self._logger.debug(f"Found higher version: {tag}")

            self._logger.debug(f"Selected highest version: {highest_version}")

            if not suitable_release:
                self._logger.info("No suitable release found")
                return None

            # Get the HTML URL for the selected release
            tag = suitable_release.get('tag_name', '')
            html_url = suitable_release.get(
                'html_url',
                f"https://github.com/{GITHUB_REPO}/releases/tag/{tag}",
            )

            self._data = UpdateInfo.Data(tag, html_url, selected_asset_url, selected_asset_digest)
            self._logger.info(f"Found release: {tag}")
            return self._data

        except Exception as e:
            self._logger.error(f"Error checking for updates: {e}", exc_info=True)
            return None

    def is_current_version_outdated(self) -> bool:
        """
        Compare current version with remote version

        :return: True if remote version is newer
        """
        if self._data is None:
            return False

        try:
            current_ver = CURRENT_VERSION()
            remote_ver = self._data.tag_name

            is_outdated = compare_versions(current_ver, remote_ver, self._logger)
            self._logger.debug(f"Version comparison: {current_ver} vs {remote_ver} = outdated: {is_outdated}")
            return is_outdated

        except Exception as e:
            self._logger.error(f"Error comparing versions: {e}", exc_info=True)
            return False

    def run_autoupdate(self):
        """
        Download and install update
        Thread-safe - should be called from background thread

        :raises ValueError: If update data is missing or version is dev build
        :raises Exception: If update process fails
        """
        data = self._data
        if data is None:
            raise ValueError("Missing release info - call check() first")

        current_ver = CURRENT_VERSION()

        # Safety check: Don't update dev builds
        if current_ver in ["dev", "0.0.0", "0.0.0-DEV"]:
            raise ValueError(
                "Cannot auto-update dev build. "
                "Please update manually or use a release version."
            )

        self._logger.info(f"Starting auto-update from {current_ver} to {data.tag_name}")
        self._logger.info(f"Downloading update from {data.zip_link}")

        try:
            # Download the ZIP file (longer timeout for large assets)
            session = timeout_session.new_session(timeout=10)
            response = session.get(data.zip_link, timeout=30)

            if response.status_code != 200:
                raise ValueError(
                    f"Failed to download update: HTTP {response.status_code}"
                )
            _verify_downloaded_zip_digest(response.content, data.zip_digest, self._logger)

            # Create temporary directory for extraction
            with tempfile.TemporaryDirectory() as tmp_dir:
                self._logger.debug(f"Using temp directory: {tmp_dir}")

                # Save ZIP file
                zip_path = os.path.join(tmp_dir, "update.zip")
                with open(zip_path, "wb") as zip_file:
                    zip_file.write(response.content)

                self._logger.debug(f"Downloaded {len(response.content)} bytes")

                # Extract ZIP
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    _safe_extract_zip(zip_ref, tmp_dir)

                self._logger.info(f"Extracted to {tmp_dir}")
                os.remove(zip_path)

                # Determine ZIP structure
                # Standard format: files in subdirectory (load.py in tmp_dir/RavenColonial_EDMC/)
                # Legacy fallback: files at root (load.py in tmp_dir) - only for emergency fixes
                load_py_path = os.path.join(tmp_dir, "load.py")

                if os.path.exists(load_py_path):
                    # Legacy format: files at root (fallback only)
                    self._logger.debug("Detected legacy ZIP format (files at root)")
                    plugin_source_dir = tmp_dir
                else:
                    # Standard format: files in subdirectory
                    self._logger.debug("Detected standard ZIP format (files in subdirectory)")
                    zip_dirs = [
                        f for f in os.listdir(tmp_dir)
                        if os.path.isdir(os.path.join(tmp_dir, f))
                    ]

                    if len(zip_dirs) == 0:
                        raise ValueError("No directories found in ZIP and load.py not at root")

                    # Try to find directory with load.py
                    plugin_source_dir = None
                    for zip_dir in zip_dirs:
                        check_path = os.path.join(tmp_dir, zip_dir, "load.py")
                        if os.path.exists(check_path):
                            plugin_source_dir = os.path.join(tmp_dir, zip_dir)
                            self._logger.debug(f"Found plugin files in: {zip_dir}")
                            break

                    if not plugin_source_dir:
                        raise ValueError("Could not find load.py in extracted ZIP")

                self._logger.debug(f"Plugin source directory: {plugin_source_dir}")
                _validate_plugin_source_tree(plugin_source_dir, self._logger)

                # Get current plugin directory (parent of this file)
                live_file_dir = os.path.dirname(os.path.abspath(__file__))
                self._logger.debug(f"Current plugin dir: {live_file_dir}")

                # Create recognizable staging directory name (.disabled prevents EDMC loading it)
                staged_dir = _staged_dir_for_target_version(
                    live_file_dir,
                    self.plugin_name,
                    data.tag_name,
                )
                self._logger.debug(f"Staged update dir: {staged_dir}")

                # Clean up any stale staged update for the same target version.
                safe_remove_backup(staged_dir, self._logger)

                try:
                    self._logger.info("Staging new version: %s -> %s", plugin_source_dir, staged_dir)
                    shutil.copytree(
                        plugin_source_dir,
                        staged_dir,
                        ignore=shutil.ignore_patterns('update.zip', '*.pyc', '__pycache__'),
                    )
                    _validate_plugin_source_tree(staged_dir, self._logger)
                    self._staged_update_dir = staged_dir
                    self._staged_update_version = data.tag_name
                except Exception as ex:
                    self._logger.error("Update staging failed")
                    self._logger.exception(ex)
                    if os.path.exists(staged_dir):
                        self._logger.info("Removing failed staged update")
                        shutil.rmtree(staged_dir)
                    raise ex

                self._logger.info(f"Auto-update staged! Will install {data.tag_name} when EDMC shuts down")
                self._logger.info("Please restart EDMC to install the new version")
                return

        except Exception as e:
            self._logger.error(f"Auto-update failed: {e}", exc_info=True)
            raise

    def install_staged_update_on_shutdown(self) -> bool:
        """
        Install a staged update after EDMC has asked the plugin to stop.

        Returns True when a staged update was promoted into the live plugin
        folder. Returns False when there is nothing staged.
        """
        staged_dir = self._staged_update_dir
        if not staged_dir or not os.path.isdir(staged_dir):
            return False

        current_ver = CURRENT_VERSION()
        live_file_dir = os.path.dirname(os.path.abspath(__file__))
        backup_dir = _backup_dir_for_current_version(
            live_file_dir,
            self.plugin_name,
            current_ver,
        )

        self._logger.info(
            "Installing staged update%s during plugin shutdown",
            f" {self._staged_update_version}" if self._staged_update_version else "",
        )

        # Defensive releases for callers/tests that invoke this directly. In
        # normal EDMC shutdown, plugin_stop() has already released these.
        try:
            capi_cache.stop()
        except Exception as e:
            self._logger.warning("capi_cache.stop() before staged update install: %s", e, exc_info=True)
        try:
            plugin_file_log.stop_issue_log()
        except Exception as e:
            self._logger.warning("stop_issue_log() before staged update install: %s", e, exc_info=True)
        try:
            _release_bundled_oxanium_font_for_update()
        except Exception as e:
            self._logger.warning("release_bundled_oxanium_font() before staged update install: %s", e, exc_info=True)

        _install_staged_update(live_file_dir, staged_dir, backup_dir, self._logger)
        self._staged_update_dir = None
        self._staged_update_version = None
        self._logger.info("Staged update install complete")
        return True

    def open_download_page(self):
        """
        Open the release page in the user's browser
        """
        if self._data is None:
            return

        import webbrowser
        webbrowser.open(self._data.browser_link)
