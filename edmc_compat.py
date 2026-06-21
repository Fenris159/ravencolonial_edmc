"""Advisory EDMC core version compatibility checks (see EDMC PLUGINS.md)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

# Tested/supported floor documented in README ("Built for EDMC 6.1.2").
MIN_SUPPORTED_EDMC_VERSION = "6.1.2"

# Exact EDMC core versions known to break supported hooks/UI integrations.
# Leave empty until a specific bad release is confirmed.
KNOWN_INCOMPATIBLE_EDMC_VERSIONS: Tuple[str, ...] = ()


@dataclass(frozen=True)
class EdmcCompatResult:
    core_version: Optional[str] = None
    level: str = "ok"  # ok | advisory | blocking
    reason: Optional[str] = None  # below_minimum | known_incompatible | unresolved


def resolve_edmc_core_version():
    """Return EDMC ``config.appversion`` as ``semantic_version.Version``, if available."""
    try:
        import semantic_version
        from config import appversion
    except ImportError:
        return None

    try:
        if isinstance(appversion, str):
            return semantic_version.Version(appversion)
        if callable(appversion):
            return appversion()
    except (TypeError, ValueError):
        return None
    return None


def check_edmc_compatibility() -> EdmcCompatResult:
    """Compare the running EDMC core version against plugin support metadata."""
    try:
        import semantic_version
    except ImportError:
        return EdmcCompatResult(level="ok", reason="unresolved")

    core = resolve_edmc_core_version()
    if core is None:
        return EdmcCompatResult(level="ok", reason="unresolved")

    display = str(core)

    try:
        minimum = semantic_version.Version(MIN_SUPPORTED_EDMC_VERSION)
    except ValueError:
        return EdmcCompatResult(core_version=display, level="ok", reason="unresolved")

    for bad in KNOWN_INCOMPATIBLE_EDMC_VERSIONS:
        try:
            if core == semantic_version.Version(bad):
                return EdmcCompatResult(
                    core_version=display,
                    level="blocking",
                    reason="known_incompatible",
                )
        except ValueError:
            continue

    if core < minimum:
        return EdmcCompatResult(
            core_version=display,
            level="advisory",
            reason="below_minimum",
        )

    return EdmcCompatResult(core_version=display, level="ok")
