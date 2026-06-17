"""Install bundled Oxanium into EDMC Modern Overlay and enable font-weight payloads."""

from __future__ import annotations

import importlib.util
import logging
import shutil
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)

OXANIUM_ASSET_DIR = "assets/fonts/oxanium"
OXANIUM_VARIABLE_FILE = "Oxanium[wght].ttf"
OXANIUM_LICENSE_FILE = "OFL.txt"
PREFERRED_FONTS_FILENAME = "preferred_fonts.txt"
_SETUP_MARKER = "ravencolonial-oxanium-installed"

_font_setup_done = False


def _plugin_assets_dir(plugin_dir: str) -> Path:
    return Path(plugin_dir).resolve() / OXANIUM_ASSET_DIR


def find_modern_overlay_plugin_dir(plugin_dir: str) -> Optional[Path]:
    """Locate the EDMCModernOverlay plugin folder next to this plugin."""
    plugin_root = Path(plugin_dir).resolve()
    plugins_root = plugin_root.parent
    candidates: list[Path] = []
    for name in ("EDMCModernOverlay", "EDMC Modern Overlay", "edmcmodernoverlay"):
        candidates.append(plugins_root / name)
    candidates.append(plugin_root / "EDMCModernOverlay")
    candidates.append(plugin_root.parent / "EDMCModernOverlay")
    for candidate in candidates:
        fonts_dir = candidate / "overlay_client" / "fonts"
        if fonts_dir.is_dir():
            return candidate
    try:
        import EDMCOverlay.edmcoverlay as edmc_mod  # type: ignore[import-untyped]

        mod_path = Path(getattr(edmc_mod, "__file__", "")).resolve()
        if mod_path.is_file():
            root = mod_path.parent.parent
            if (root / "overlay_client" / "fonts").is_dir():
                return root
    except Exception:  # nosec B110
        pass
    return None


def _ensure_preferred_fonts_entry(preferred_path: Path, font_filename: str) -> None:
    lines: list[str] = []
    if preferred_path.is_file():
        lines = preferred_path.read_text(encoding="utf-8").splitlines()
    target = font_filename.strip()
    if not target:
        return
    lowered = target.lower()
    filtered = [
        line
        for line in lines
        if line.strip() and not line.strip().startswith(("#", ";")) and line.strip().lower() != lowered
    ]
    new_lines = [target] + filtered
    preferred_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")



def _apply_modern_overlay_weight_patch(modern_overlay_dir: Path) -> bool:
    patch_path = Path(__file__).resolve().parent / "modern_overlay_weight_patch.py"
    spec = importlib.util.spec_from_file_location(
        "ravencolonial_modern_overlay_weight_patch", patch_path
    )
    if spec is None or spec.loader is None:
        return False
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return bool(mod.apply_modern_overlay_weight_patch(modern_overlay_dir))

def install_oxanium_to_modern_overlay(plugin_dir: str, *, force: bool = False) -> bool:
    """
    Copy bundled Oxanium variable font into Modern Overlay's fonts directory.

    Returns True when fonts are present in the overlay fonts folder (installed or already there).
    """
    assets = _plugin_assets_dir(plugin_dir)
    source_font = assets / OXANIUM_VARIABLE_FILE
    if not source_font.is_file():
        logger.warning("Bundled Oxanium font missing at %s", source_font)
        return False

    modern = find_modern_overlay_plugin_dir(plugin_dir)
    if modern is None:
        logger.debug("EDMCModernOverlay not found; Oxanium install deferred")
        return False

    fonts_dir = modern / "overlay_client" / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    dest_font = fonts_dir / OXANIUM_VARIABLE_FILE
    marker = fonts_dir / _SETUP_MARKER

    if force or not dest_font.is_file() or dest_font.stat().st_size != source_font.stat().st_size:
        shutil.copy2(source_font, dest_font)
        logger.info("Installed Oxanium variable font to %s", dest_font)

    license_src = assets / OXANIUM_LICENSE_FILE
    if license_src.is_file():
        shutil.copy2(license_src, fonts_dir / OXANIUM_LICENSE_FILE)

    preferred_path = fonts_dir / PREFERRED_FONTS_FILENAME
    _ensure_preferred_fonts_entry(preferred_path, OXANIUM_VARIABLE_FILE)
    marker.write_text("Oxanium via RavenColonial EDMC\n", encoding="utf-8")

    _apply_modern_overlay_weight_patch(modern)
    return True


def ensure_oxanium_overlay_font(plugin_dir: str) -> None:
    """Run once per process: install Oxanium and patch Modern Overlay when available."""
    global _font_setup_done
    if _font_setup_done:
        return
    try:
        ok = install_oxanium_to_modern_overlay(plugin_dir)
    except Exception as exc:
        logger.warning("Oxanium overlay font setup failed: %s", exc)
        return
    # Retry on later get_overlay_client() if Modern Overlay was not installed yet.
    if ok or find_modern_overlay_plugin_dir(plugin_dir) is not None:
        _font_setup_done = True

def retry_install_oxanium_font(plugin_dir: str) -> tuple[bool, str]:
    """
    Force Oxanium install into Modern Overlay (settings button / manual retry).

    Returns (success, message) suitable for a dialog.
    """
    assets = _plugin_assets_dir(plugin_dir)
    if not (assets / OXANIUM_VARIABLE_FILE).is_file():
        return False, (
            "Bundled Oxanium font files are missing from this plugin install. "
            "Reinstall RavenColonial_EDMC from the latest release."
        )
    try:
        ok = install_oxanium_to_modern_overlay(plugin_dir, force=True)
    except Exception as exc:
        logger.warning("Manual Oxanium font install failed: %s", exc)
        return False, f"Font install failed: {exc}"
    if ok:
        return True, (
            "Oxanium font installed into EDMC Modern Overlay. "
            "Restart EDMC so the overlay client reloads the font."
        )
    if find_modern_overlay_plugin_dir(plugin_dir) is None:
        return False, (
            "EDMC Modern Overlay was not found. Install and enable it in EDMC "
            "(File → Settings → Plugins), then try again."
        )
    return False, "Font install did not complete. Check the EDMC log for details."

