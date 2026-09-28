"""Bake DejaVu glyphs into portable, theme-colored Tk bitmap icon files."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ICON_GLYPHS = {
    "refresh": "\u27f3",
    "open": "\u2197",
    "build": "\u2692",
    "link": "\u26ad",
    "download": "\u21e9",
    "update": "\u26a1",
    "close": "\u00d7",
    "dropdown": "\u25be",
}
ICON_SIZES = (12, 16, 20, 24, 32, 48)


def render_icon(font_path: Path, glyph: str, size: int) -> Image.Image:
    """Center a supported glyph with enough padding to avoid clipped strokes."""
    font = ImageFont.truetype(str(font_path), size)
    if bytes(font.getmask(glyph)) == bytes(font.getmask(chr(0x10FFFF))):
        raise ValueError(f"Font lacks U+{ord(glyph):04X}")
    left, top, right, bottom = font.getbbox(glyph)
    glyph_image = Image.new("L", (right - left + 2, bottom - top + 2))
    ImageDraw.Draw(glyph_image).text((1 - left, 1 - top), glyph, font=font, fill=255)
    if glyph == ICON_GLYPHS["link"]:
        glyph_image = glyph_image.rotate(45, resample=Image.Resampling.BICUBIC, expand=True)
    available = size - max(4, size // 5)
    glyph_image.thumbnail((available, available), Image.Resampling.LANCZOS)
    image = Image.new("L", (size, size))
    image.paste(glyph_image, ((size - glyph_image.width) // 2, (size - glyph_image.height) // 2))
    return image.point(lambda value: 255 if value >= 96 else 0, "1")


def main() -> None:
    """Generate committed XBM assets; Pillow is only needed for this development step."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, required=True, help="Path to DejaVuSans.ttf")
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / "assets" / "icons" / "dejavu"
    output.mkdir(parents=True, exist_ok=True)
    for name, glyph in ICON_GLYPHS.items():
        for size in ICON_SIZES:
            render_icon(args.font, glyph, size).save(output / f"{name}-{size}.xbm")
    print(f"Generated {len(ICON_GLYPHS) * len(ICON_SIZES)} DejaVu bitmap assets in {output}")


if __name__ == "__main__":
    main()
