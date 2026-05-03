"""Central access to EDMC l10n for the Ravencolonial plugin."""

from __future__ import annotations

from typing import Any, Callable, Optional

_translate: Optional[Callable[[str], str]] = None


def set_translate(fn: Callable[[str], str]) -> None:
    """Register EDMC's translation function (from ``l10n.translations.tl``)."""
    global _translate
    _translate = fn


def tr(message: str) -> str:
    """Translate a static UI string."""
    if not message:
        return message
    if _translate is None:
        return message
    return _translate(message)


def trf(message: str, **kwargs: Any) -> str:
    """Translate then substitute ``{placeholders}`` (Python ``str.format``)."""
    translated = tr(message)
    if not kwargs:
        return translated
    try:
        return translated.format(**kwargs)
    except (KeyError, ValueError):
        return translated
