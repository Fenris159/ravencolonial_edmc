"""DejaVu-derived bitmap buttons without platform font or emoji dependencies."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from typing import Any, Optional

ICON_DIRECTORY = Path(__file__).resolve().parents[1] / "assets" / "icons" / "dejavu"
ICON_SIZES = (12, 16, 20, 24, 32, 48)
ICON_NAMES = ("refresh", "open", "build", "link", "download", "update", "close", "dropdown")
# Measure the previous caption prefix only to preserve its space; these glyphs are never drawn.
_CAPTION_PREFIXES = {"open": "\U0001f310 ", "build": "\U0001f6a7", "link": "\U0001f517 ",
                     "download": "\U0001f4e5 ", "update": "\u26a1 ", "close": "\u2716 "}


class IconButton(tk.Button):
    """Classic EDMC-themed button with portable image, disabled, and hover colors."""

    def __init__(self, parent: tk.Misc, *, icon: Optional[str] = None, **kwargs: Any) -> None:
        self._icon_name = icon
        self._caption_width = int(kwargs.get("width", 0))
        self._hovered = False
        self._icon_signature: Optional[tuple[Any, ...]] = None
        self._icon_images: tuple[tk.BitmapImage, ...] = ()
        super().__init__(parent, **kwargs)
        self._base_padx = self.cget("padx")
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        self._refresh_icon()

    def configure(self, cnf: Any = None, **kwargs: Any) -> Any:
        """Retint images after EDMC changes colors, font, caption, or button state."""
        if isinstance(cnf, str):
            return super().configure(cnf, **kwargs)
        options = dict(cnf or {})
        options.update(kwargs)
        if not options:
            return super().configure()
        if "icon" in options:
            self._icon_name = options.pop("icon")
        if "width" in options:
            self._caption_width = int(options["width"])
        if "padx" in options:
            self._base_padx = options["padx"]
        result = super().configure(**options)
        self._refresh_icon()
        return result

    config = configure

    def _on_enter(self, _event: tk.Event) -> None:
        self._hovered = True
        self._refresh_icon()

    def _on_leave(self, _event: tk.Event) -> None:
        self._hovered = False
        self._refresh_icon()

    def _refresh_icon(self) -> None:
        if not self._icon_name:
            super().configure(image="", width=self._caption_width, height=0, padx=self._base_padx)
            return
        if self._icon_name not in ICON_NAMES:
            raise ValueError(f"Unknown button icon: {self._icon_name}")
        font = tkfont.Font(root=self, font=self.cget("font"))
        line_height = int(font.metrics("linespace"))
        caption = str(self.cget("text")).strip()
        content_width = font.measure("0") * self._caption_width
        available = line_height if caption or not content_width else min(line_height, content_width)
        size = max((pixels for pixels in ICON_SIZES if pixels <= available), default=ICON_SIZES[0])
        path = ICON_DIRECTORY / f"{self._icon_name}-{size}.xbm"
        signature = (self._icon_name, size, self.cget("foreground"), self.cget("disabledforeground"),
                     self.cget("activeforeground"))
        if signature != self._icon_signature:
            self._icon_images = tuple(tk.BitmapImage(master=self, file=str(path), foreground=color)
                                      for color in signature[2:])
            self._icon_signature = signature
        image = self._icon_images[1 if self.cget("state") == tk.DISABLED else 2 if self._hovered else 0]
        padding = self.winfo_pixels(str(self._base_padx))
        if caption:
            prefix = _CAPTION_PREFIXES.get(self._icon_name, "")
            if prefix:
                padding = max(0, round((font.measure(prefix) + 2 * padding - size) / 3))
            super().configure(image=image, compound=tk.LEFT, width=0, height=0, padx=padding)
        else:
            # A blank text slot retains native text-button padding and line height.
            # Image buttons interpret width as pixels; preserve the old character width explicitly.
            super().configure(image=image, text=" ", compound=tk.CENTER, width=max(size, content_width),
                              height=0, padx=self._base_padx)
