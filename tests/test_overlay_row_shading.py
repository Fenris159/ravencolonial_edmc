"""Saved row opacity controls both tracker layouts and Tk's alpha blending."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from test_overlay_purchase import BuildProjectOverlay, BuildProjectPopout, _tracker_plugin
from overlay.layers import MSG_ROW_STRIPE_PREFIX
from overlay.row_shading import (
    ROW_HIGHLIGHT_OPACITY_KEY,
    normalize_row_highlight_opacity,
    row_highlight_fill,
)


@pytest.mark.parametrize("mode", ["breakdown", "simplified"])
@pytest.mark.parametrize("opacity", [0, 50, 100])
def test_saved_opacity_reaches_alternating_rows_in_both_formats(mode: str, opacity: int, monkeypatch: Any) -> None:
    """The composed HUD/popout bundle reads config rather than using a fixed fill."""
    config = SimpleNamespace(get_int=lambda key, default=0: opacity if key == ROW_HIGHLIGHT_OPACITY_KEY else default)
    monkeypatch.setattr(sys.modules["config"], "config", config, raising=False)
    plugin = _tracker_plugin(
        {"buildId": "port", "buildName": "Port", "commodities": {"steel": 10, "copper": 20}},
        overlay_format=mode, overlay_carrier_tracking_enabled=False,
    )
    bundle = BuildProjectOverlay(plugin).compose_layers()
    stripes = [rect for rect in bundle.rect_layers if rect.msg_id.startswith(MSG_ROW_STRIPE_PREFIX)]
    if opacity == 0:
        assert stripes == []
    else:
        assert len(stripes) == 1
        assert stripes[0].fill == ("#804B4F54" if opacity == 50 else "#FF4B4F54")
        expected = "#26282a" if opacity == 50 else "#4b4f54"
        assert BuildProjectPopout._blend_argb(stripes[0].fill, "#000000") == expected


def test_opacity_defaults_and_invalid_values_remain_in_range() -> None:
    """Old installations retain their 8% shading and malformed values cannot break drawing."""
    assert row_highlight_fill(8) == "#144B4F54"
    assert normalize_row_highlight_opacity(-5) == 0
    assert normalize_row_highlight_opacity(200) == 100
    for invalid in (None, "invalid", float("nan"), float("inf")):
        assert normalize_row_highlight_opacity(invalid) == 8
