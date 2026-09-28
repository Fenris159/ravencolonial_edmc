"""Compatibility patches must not break Modern Overlay's shared text measurement."""

from __future__ import annotations

import importlib.util
from enum import IntEnum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "raven_weight_patch_test", _ROOT / "overlay" / "modern_overlay_weight_patch.py",
)
assert _spec and _spec.loader
_patch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_patch)


class _Font:
    class Weight(IntEnum):
        """Represent the Qt weights used by this regression fixture."""

        Normal = 400
        Bold = 700

    def __init__(self, family: str) -> None:
        self.family = family
        self.weight = self.Weight.Normal

    def setPointSizeF(self, point_size: float) -> None:  # noqa: N802 - matches Qt's interface
        self.point_size = point_size

    def setWeight(self, weight: IntEnum) -> None:  # noqa: N802 - matches Qt's interface
        self.weight = weight


class _Metrics:
    def __init__(self, font: _Font) -> None:
        self.font = font

    def horizontalAdvance(self, text: str) -> int:  # noqa: N802 - matches Qt's interface
        return len(text) * int(self.font.weight)

    def ascent(self) -> int:
        return 10

    def descent(self) -> int:
        return 2


def _overlay_fixture(root: Path) -> Path:
    """Create a minimal overlay with the real v0.9.2 method boundaries."""
    (root / "EDMCOverlay").mkdir()
    (root / "overlay_client").mkdir()
    (root / "EDMCOverlay" / "edmcoverlay.py").write_text(
        "def message():\n" + _patch._EDMCOVERLAY_MESSAGE_BLOCK,
        encoding="utf-8",
    )
    render = root / "overlay_client" / "render_surface.py"
    render.write_text(
        (_ROOT / "tests" / "fixtures" / "modern_overlay_weight_render.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (root / "overlay_client" / "paint_commands.py").write_text(
        "class _MessagePaintCommand:\n"
        "    point_size: float = 12.0\n    x: int = 0\n"
        "    def paint(self, painter):\n"
        "        font.setWeight(QFont.Weight.Normal)\n        painter.setFont(font)\n",
        encoding="utf-8",
    )
    return render


def _renderer(source: str) -> Any:
    """Execute the patched rendering methods with deterministic font measurements."""
    namespace = {
        "Optional": Optional,
        "Tuple": Tuple,
        "QFont": _Font,
        "QFontMetrics": _Metrics,
        "_MessagePaintCommand": lambda **kwargs: SimpleNamespace(**kwargs),
    }
    exec(source, namespace)
    renderer = namespace["RenderSurfaceMixin"]()
    renderer._font_family = "Oxanium"
    renderer._text_cache = {}
    renderer._apply_font_fallbacks = lambda _font: None
    renderer._viewport_state = lambda: {"normal": 12.0}
    return renderer


def test_patch_renders_default_and_bold_text_without_undefined_weight(tmp_path: Path) -> None:
    """Measurements and drawing use the payload weight and keep separate cache entries."""
    render = _overlay_fixture(tmp_path)
    assert _patch.apply_modern_overlay_weight_patch(tmp_path)
    renderer = _renderer(render.read_text(encoding="utf-8"))

    assert renderer._measure_text("Test", 12.0) == (1600, 10, 2)
    regular = renderer._build_message_command({"text": "Test"})
    bold = renderer._build_message_command({"text": "Test", "weight": 700})
    assert (regular.weight, regular.text_width) == (400, 1600)
    assert (bold.weight, bold.text_width) == (700, 2800)
    assert renderer.unrelated_font_operation().weight == _Font.Weight.Normal


def test_patch_repairs_the_previous_unsafe_patch_and_is_idempotent(tmp_path: Path) -> None:
    """A previous marker cannot hide an undefined weight in the shared measuring method."""
    render = _overlay_fixture(tmp_path)
    source = render.read_text(encoding="utf-8")
    source = source.replace(
        '        size = str(item.get("size", "normal")).lower()\n',
        '        size = str(item.get("size", "normal")).lower()\n'
        '        weight = max(100, min(900, int(item.get("weight", 400))))\n',
    ).replace("metrics_font.setWeight(QFont.Weight.Normal)", "metrics_font.setWeight(QFont.Weight(weight))", 2)
    source = source.replace(
        "point_size=scaled_point_size,\n            x=x,",
        "point_size=scaled_point_size,\n            weight=weight,\n            x=x,",
    )
    render.write_text(source + f"\n{_patch.PATCH_MARKER}\n", encoding="utf-8")

    assert _patch.apply_modern_overlay_weight_patch(tmp_path)
    repaired = render.read_text(encoding="utf-8")
    assert _renderer(repaired)._measure_text("Test", 12.0) == (1600, 10, 2)
    assert _patch.apply_modern_overlay_weight_patch(tmp_path)
    assert render.read_text(encoding="utf-8") == repaired


def test_unknown_renderer_layout_is_left_untouched(tmp_path: Path) -> None:
    """Unsupported source layouts cannot receive a partial compatibility patch."""
    render = _overlay_fixture(tmp_path)
    render.write_text("# A newer renderer with a different interface\n", encoding="utf-8")
    paths = [render, tmp_path / "EDMCOverlay" / "edmcoverlay.py", tmp_path / "overlay_client" / "paint_commands.py"]
    before = [path.read_bytes() for path in paths]
    assert _patch.apply_modern_overlay_weight_patch(tmp_path) is False
    assert [path.read_bytes() for path in paths] == before
