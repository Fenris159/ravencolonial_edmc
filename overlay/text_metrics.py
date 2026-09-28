"""Reference text width estimates without querying the overlay renderer."""

from __future__ import annotations

from textwrap import wrap
from unicodedata import category, east_asian_width


def text_cell_width(text: str) -> int:
    """Count display cells, allowing for wide glyphs and combining characters."""
    return sum(
        0 if category(char) in {"Mn", "Me", "Cf"} else 2 if east_asian_width(char) in {"W", "F"} else 1
        for char in str(text)
    )


def wrap_display_text(text: str, *, width: int, subsequent_indent: str = "  ") -> list[str]:
    """Wrap at word boundaries using estimated display width; keep words intact."""
    if text.isascii():
        return wrap(text, width=width, subsequent_indent=subsequent_indent,
                    break_long_words=False, break_on_hyphens=False) or [""]
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current.strip() else f"{current}{word}"
        if current.strip() and text_cell_width(candidate) > width:
            lines.append(current)
            current = f"{subsequent_indent}{word}"
        else:
            current = candidate
    return [*lines, current] if current else [""]
