# Portable DejaVu icons

These XBM bitmap files contain monochrome DejaVu Sans glyphs for refresh, open, build, link, download, update, dismiss, and dropdown controls. The link glyph is rotated to form a diagonal chain. Files are supplied at 12, 16, 20, 24, 32, and 48 pixels.

Tk loads the committed files directly on Windows and Linux. Users do not need to install DejaVu or Pillow. The button supplies the theme's normal, disabled, or hover foreground color; the bitmap background stays transparent.

`ui/file_icons.py` keeps image references alive, selects a size that fits the button's font, and retains native text-button spacing. Icon-only controls keep their original character-width allocation and font height, including the carrier refresh countdown. Caption buttons account for the space occupied by the previous prefix without rendering its Unicode glyph.

## Regeneration

For development only, use Pillow and a DejaVu Sans font file, such as EDMC's bundled `fonts/DejaVuSans.ttf`:

```sh
python scripts/generate_file_icons.py --font "/path/to/DejaVuSans.ttf"
```

The source font's copyright and license notices are included in [LICENSE](LICENSE). The release packager includes this directory automatically.
