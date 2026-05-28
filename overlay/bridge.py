"""EDMCModernOverlay bridge (optional dependency)."""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)

OVERLAY_MESSAGE_PREFIX = "ravencolonial-overlay-"


class _OverlayClient(Protocol):
    def connect(self) -> None: ...

    def send_message(
        self,
        msgid: str,
        text: str,
        color: str,
        x: int,
        y: int,
        ttl: int = 4,
        size: str = "normal",
    ) -> None: ...

    def send_raw(self, msg: dict[str, Any]) -> None: ...

    def send_shape(
        self,
        shapeid: str,
        shape: str,
        color: str,
        fill: str,
        x: int,
        y: int,
        w: int,
        h: int,
        ttl: int,
    ) -> None: ...


class _NoOpOverlay:
    def connect(self) -> None:
        return None

    def send_message(
        self,
        msgid: str,
        text: str,
        color: str,
        x: int,
        y: int,
        ttl: int = 4,
        size: str = "normal",
    ) -> None:
        return None

    def send_raw(self, msg: dict[str, Any]) -> None:
        return None

    def send_shape(
        self,
        shapeid: str,
        shape: str,
        color: str,
        fill: str,
        x: int,
        y: int,
        w: int,
        h: int,
        ttl: int,
    ) -> None:
        return None


_overlay_singleton: Optional[_OverlayClient] = None
_group_registered = False


def get_overlay_client() -> _OverlayClient:
    global _overlay_singleton
    if _overlay_singleton is not None:
        return _overlay_singleton
    try:
        from EDMCOverlay import edmcoverlay  # type: ignore[import-untyped]

        client = edmcoverlay.Overlay()
        client.connect()
        _overlay_singleton = client
        logger.info("EDMCModernOverlay compatibility layer loaded")
        return client
    except ImportError:
        logger.debug("EDMCOverlay not installed — overlay output disabled")
        _overlay_singleton = _NoOpOverlay()
        return _overlay_singleton


def register_build_tracker_group() -> None:
    global _group_registered
    if _group_registered:
        return
    try:
        from overlay_plugin.overlay_api import define_plugin_group  # type: ignore[import-untyped]

        define_plugin_group(
            plugin_name="Ravencolonial",
            plugin_matching_prefixes=["ravencolonial-"],
            plugin_group_name="build-tracker",
            plugin_group_prefixes=[OVERLAY_MESSAGE_PREFIX],
            plugin_group_anchor="nw",
            payload_justification="left",
            plugin_group_background_color="#141414CC",
            plugin_group_border_width=1,
        )
        _group_registered = True
        logger.info("Registered Ravencolonial overlay plugin group with EDMCModernOverlay")
    except Exception as exc:
        logger.debug("Overlay plugin group not registered: %s", exc)
