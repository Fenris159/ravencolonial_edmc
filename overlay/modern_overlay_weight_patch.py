"""Idempotent patches so EDMC Modern Overlay honours per-message font weight."""

from __future__ import annotations

import logging
import ast
from pathlib import Path
from typing import Optional, Sequence

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


def _replace_known_patterns(source: str, replacements: Sequence[tuple[str, str]]) -> Optional[str]:
    for old, new in replacements:
        if new in source:
            continue
        if old not in source:
            return None
        source = source.replace(old, new, 1)
    return source


def _rewrite_named_block(
    source: str,
    name: str,
    kind: type[ast.AST],
    replacements: Sequence[tuple[str, str]],
) -> Optional[str]:
    """Restrict compatibility edits to a known method or class, preserving other code."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    nodes = [node for node in ast.walk(tree) if isinstance(node, kind) and getattr(node, "name", None) == name]
    if len(nodes) != 1:
        return None
    node = nodes[0]
    lines = source.splitlines(keepends=True)
    start, end = node.lineno - 1, node.end_lineno
    block = _replace_known_patterns("".join(lines[start:end]), replacements)
    if block is None:
        return None
    return "".join(lines[:start]) + block + "".join(lines[end:])


def _patch_render_source(source: str) -> Optional[str]:
    """Pass explicit weights through measurements, cache keys, and message drawing."""
    font_weight = (
        "metrics_font.setWeight(QFont.Weight.Normal)",
        "metrics_font.setWeight(QFont.Weight(weight))",
    )
    measured = _rewrite_named_block(source, "_measure_text", ast.FunctionDef, (
        ("font_family: Optional[str] = None) -> Tuple[int, int, int]:",
         "font_family: Optional[str] = None, weight: int = 400) -> Tuple[int, int, int]:"),
        ("key = (text, point_size, family)", "key = (text, point_size, family, weight)"),
        font_weight,
    ))
    if measured is None:
        return None
    return _rewrite_named_block(measured, "_build_message_command", ast.FunctionDef, (
        ('        size = str(item.get("size", "normal")).lower()\n        state = self._viewport_state()',
         '        size = str(item.get("size", "normal")).lower()\n'
         '        weight = max(100, min(900, int(item.get("weight", 400))))\n'
         '        state = self._viewport_state()'),
        ("self._measure_text(text, scaled_point_size, self._font_family)",
         "self._measure_text(text, scaled_point_size, self._font_family, weight=weight)"),
        font_weight,
        ("point_size=scaled_point_size,\n            x=x,",
         "point_size=scaled_point_size,\n            weight=weight,\n            x=x,"),
    ))


def apply_modern_overlay_weight_patch(modern_overlay_dir: Path) -> bool:
    """
    Patch EDMCModernOverlay so legacy message payloads may include ``weight`` (100–900).

    Upgrade earlier patches safely and leave unknown source layouts untouched.
    """
    root = Path(modern_overlay_dir)
    paths = [root / "EDMCOverlay" / "edmcoverlay.py",
             root / "overlay_client" / "render_surface.py",
             root / "overlay_client" / "paint_commands.py"]
    if not all(path.is_file() for path in paths):
        logger.warning("Modern Overlay weight patch skipped: required source files are missing")
        return False
    original = [path.read_text(encoding="utf-8") for path in paths]
    updated = [
        _replace_known_patterns(original[0], [(_EDMCOVERLAY_MESSAGE_BLOCK, _EDMCOVERLAY_MESSAGE_BLOCK_PATCHED)]),
        _patch_render_source(original[1]),
        _rewrite_named_block(original[2], "_MessagePaintCommand", ast.ClassDef, (
            ("    point_size: float = 12.0\n    x: int = 0",
             "    point_size: float = 12.0\n    weight: int = 400\n    x: int = 0"),
            ("        font.setWeight(QFont.Weight.Normal)\n        painter.setFont(font)",
             "        font.setWeight(QFont.Weight(self.weight))\n        painter.setFont(font)"),
        )),
    ]
    if any(source is None for source in updated):
        logger.warning("Modern Overlay weight patch skipped: unsupported source layout; files left unchanged")
        return False
    for path, before, after in zip(paths, original, updated):
        if after == before:
            continue
        if PATCH_MARKER not in after:
            after += f"\n{PATCH_MARKER}\n"
        temporary = path.with_suffix(path.suffix + ".ravencolonial-tmp")
        temporary.write_text(after, encoding="utf-8")
        temporary.chmod(path.stat().st_mode)
        temporary.replace(path)
        logger.info("Applied Modern Overlay weight patch: %s", path.name)
    return True
