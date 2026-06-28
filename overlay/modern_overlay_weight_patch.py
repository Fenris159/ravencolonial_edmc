"""Idempotent patches so EDMC Modern Overlay honours per-message font weight."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PATCH_MARKER = "# ravencolonial: font-weight payload support"

_EDMCOVERLAY_MESSAGE_BLOCK = """        payload = {
            "type": "message",
            "id": item_id or "",
            "text": str(text),
            "color": _lookup("color", "Color") or "white",
            "size": _lookup("size", "Size") or "normal",
            "x": _legacy_coerce_int(_lookup("x", "X"), 0),
            "y": _legacy_coerce_int(_lookup("y", "Y"), 0),
            "ttl": ttl,
        }
        if plugin:
            payload["plugin"] = plugin
        return payload"""

_EDMCOVERLAY_MESSAGE_BLOCK_PATCHED = """        payload = {
            "type": "message",
            "id": item_id or "",
            "text": str(text),
            "color": _lookup("color", "Color") or "white",
            "size": _lookup("size", "Size") or "normal",
            "x": _legacy_coerce_int(_lookup("x", "X"), 0),
            "y": _legacy_coerce_int(_lookup("y", "Y"), 0),
            "ttl": ttl,
        }
        weight_val = _lookup("weight", "Weight", "font_weight", "FontWeight")
        if weight_val is not None:
            payload["weight"] = max(100, min(900, _legacy_coerce_int(weight_val, 400)))
        if plugin:
            payload["plugin"] = plugin
        return payload"""


def _patch_file(path: Path, old: str, new: str, *, label: str) -> bool:
    if not path.is_file():
        logger.debug("Weight patch skipped (%s missing): %s", label, path)
        return False
    text = path.read_text(encoding="utf-8")
    if PATCH_MARKER in text or "payload[\"weight\"]" in text:
        return True
    if old not in text:
        logger.warning("Weight patch pattern not found in %s (%s)", path, label)
        return False
    path.write_text(text.replace(old, new, 1) + f"\n{PATCH_MARKER}\n", encoding="utf-8")
    logger.info("Applied Modern Overlay weight patch: %s", path.name)
    return True


def apply_modern_overlay_weight_patch(modern_overlay_dir: Path) -> bool:
    """
    Patch EDMCModernOverlay so legacy message payloads may include ``weight`` (100–900).

    Safe to call repeatedly; skips when already patched.
    """
    root = Path(modern_overlay_dir)
    edmc_path = root / "EDMCOverlay" / "edmcoverlay.py"
    render_path = root / "overlay_client" / "render_surface.py"
    paint_path = root / "overlay_client" / "paint_commands.py"

    ok = True
    ok = _patch_file(edmc_path, _EDMCOVERLAY_MESSAGE_BLOCK,
                     _EDMCOVERLAY_MESSAGE_BLOCK_PATCHED, label="edmcoverlay") and ok

    render_old = "        size = str(item.get(\"size\", \"normal\")).lower()\n        state = self._viewport_state()"
    render_new = (
        "        size = str(item.get(\"size\", \"normal\")).lower()\n"
        "        weight = max(100, min(900, int(item.get(\"weight\", 400))))\n"
        "        state = self._viewport_state()"
    )
    if render_path.is_file():
        render_text = render_path.read_text(encoding="utf-8")
        if PATCH_MARKER not in render_text and "weight = max(100, min(900" not in render_text:
            if render_old in render_text:
                render_text = render_text.replace(render_old, render_new, 1)
                render_text = render_text.replace(
                    "metrics_font.setWeight(QFont.Weight.Normal)",
                    "metrics_font.setWeight(QFont.Weight(weight))",
                    2,
                )
                render_text = render_text.replace(
                    "point_size=scaled_point_size,\n            x=x,",
                    "point_size=scaled_point_size,\n            weight=weight,\n            x=x,",
                    1,
                )
                render_path.write_text(render_text + f"\n{PATCH_MARKER}\n", encoding="utf-8")
                logger.info("Applied Modern Overlay weight patch: render_surface.py")
            else:
                logger.warning("Weight patch pattern not found in render_surface.py")
                ok = False

    if paint_path.is_file():
        paint_text = paint_path.read_text(encoding="utf-8")
        if PATCH_MARKER not in paint_text and "weight: int = 400" not in paint_text:
            paint_text = paint_text.replace(
                "    point_size: float = 12.0\n    x: int = 0",
                "    point_size: float = 12.0\n    weight: int = 400\n    x: int = 0",
                1,
            )
            paint_text = paint_text.replace(
                "        font.setWeight(QFont.Weight.Normal)\n        painter.setFont(font)",
                "        font.setWeight(QFont.Weight(self.weight))\n        painter.setFont(font)",
                1,
            )
            paint_path.write_text(paint_text + f"\n{PATCH_MARKER}\n", encoding="utf-8")
            logger.info("Applied Modern Overlay weight patch: paint_commands.py")
        elif "weight: int = 400" in paint_text:
            pass
        else:
            ok = False

    return ok
