"""HUD estimates for localized labels and semantic footer wrapping."""

from __future__ import annotations

import pytest

from overlay.layers import OVERLAY_X, estimate_value_text_width, values_column_x
from overlay.text_metrics import text_cell_width


@pytest.mark.parametrize(("text", "cells"), [
    ("Surface stabilisers", 19),
    ("Chemicals", 9),
    ("化学品", 6),
    ("ＡＢＣ", 6),
    ("Cafe\u0301", 4),
    ("Café", 4),
    ("Ship\u200b cargo", 10),
])
def test_localized_text_display_cells(text: str, cells: int) -> None:
    """Wide fallback glyphs need extra space while accent/format marks need none."""
    assert text_cell_width(text) == cells


def test_localized_column_estimates_preserve_ascii_and_equivalent_accents() -> None:
    """Keep the established ASCII grid and avoid overlap from wide localized glyphs."""
    assert values_column_x(["Commodity", "Steel"], gap=12) == OVERLAY_X + int(9 * 7.2) + 12
    assert values_column_x(["Cafe\u0301"]) == values_column_x(["Café"])
    assert values_column_x(["化学品"]) == values_column_x(["ABCDEF"])
    assert estimate_value_text_width("化学品") == estimate_value_text_width("ABCDEF")
