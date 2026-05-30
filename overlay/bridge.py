"""EDMCModernOverlay bridge (optional dependency)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol

logger = logging.getLogger(__name__)

OVERLAY_MESSAGE_PREFIX = "ravencolonial-overlay-"
OVERLAY_DEFAULTS_SEEDED_FLAG = "ravencolonial_modern_overlay_defaults_seeded"
OVERLAY_PLUGIN_NAME = "Ravencolonial"
OVERLAY_GROUP_NAME = "build-tracker"
PREFERRED_GROUP_DEFAULTS: dict[str, Any] = {
    "idPrefixGroupAnchor": "left",
    "offsetX": 992.0,
    "offsetY": 270.0,
    "backgroundColor": "#001414CC",
    "backgroundBorderWidth": 0,
}


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


class _ModernOverlayApiClient:
    """Small adapter for EDMCModernOverlay's public in-process publisher API."""

    def __init__(self, publisher: Callable[[Mapping[str, Any]], bool]) -> None:
        self._publisher = publisher

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
        self.send_raw(
            {
                "type": "message",
                "id": msgid,
                "text": text,
                "color": color,
                "x": int(x),
                "y": int(y),
                "ttl": int(ttl),
                "size": size,
            }
        )

    def send_raw(self, msg: dict[str, Any]) -> None:
        raw = dict(msg)
        raw.setdefault("type", self._infer_legacy_type(raw))
        payload = {
            "event": "LegacyOverlay",
            "plugin": "Ravencolonial",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **raw,
        }
        if not self._publisher(payload):
            logger.debug("EDMCModernOverlay publisher rejected payload id=%s", payload.get("id"))

    @staticmethod
    def _infer_legacy_type(raw: Mapping[str, Any]) -> str:
        if raw.get("shape"):
            return "shape"
        if "text" in raw:
            return "message"
        if raw.get("id"):
            return "legacy_clear"
        return "raw"

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
        self.send_raw(
            {
                "type": "shape",
                "shape": shape,
                "id": shapeid,
                "color": color,
                "fill": fill,
                "x": int(x),
                "y": int(y),
                "w": int(w),
                "h": int(h),
                "ttl": int(ttl),
            }
        )


_overlay_singleton: Optional[_OverlayClient] = None
_group_registered = False
_plugin_dir_for_fonts: Optional[str] = None


def configure_overlay_fonts(plugin_dir: str) -> None:
    """Install bundled Oxanium into Modern Overlay (once per process)."""
    global _plugin_dir_for_fonts
    _plugin_dir_for_fonts = None
    logger.info("Skipped Oxanium Modern Overlay font setup for compatibility test")


def send_overlay_text(
    client: _OverlayClient,
    msgid: str,
    text: str,
    color: str,
    x: int,
    y: int,
    *,
    ttl: int = 0,
    size: str = "normal",
    weight: int = 400,
) -> None:
    """Send HUD text through Modern Overlay's unmodified legacy message path."""
    send_raw = getattr(client, "send_raw", None)
    if callable(send_raw):
        send_raw(
            {
                "id": msgid,
                "text": text,
                "color": color,
                "x": int(x),
                "y": int(y),
                "ttl": int(ttl),
                "size": size,
            }
        )
        return
    client.send_message(msgid, text, color, x, y, ttl=ttl, size=size)


def get_overlay_client() -> _OverlayClient:
    global _overlay_singleton
    if _overlay_singleton is not None:
        return _overlay_singleton
    try:
        from .availability import import_overlay_api

        overlay_api = import_overlay_api()
        send_overlay_message = overlay_api.send_overlay_message

        _overlay_singleton = _ModernOverlayApiClient(send_overlay_message)
        logger.info("EDMCModernOverlay public API loaded")
        return _overlay_singleton
    except (AttributeError, ImportError):
        pass
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
        from .availability import import_overlay_api

        overlay_api = import_overlay_api()
        define_plugin_group = overlay_api.define_plugin_group

        define_plugin_group(
            plugin_name="Ravencolonial",
            plugin_matching_prefixes=["ravencolonial-"],
            plugin_group_name="build-tracker",
            plugin_group_prefixes=[OVERLAY_MESSAGE_PREFIX],
            plugin_group_anchor="nw",
            payload_justification="left",
            plugin_group_background_color="#141414CC",
        )
        _group_registered = True
        logger.info("Registered Ravencolonial overlay plugin group with EDMCModernOverlay")
    except Exception as exc:
        logger.debug("Overlay plugin group not registered: %s", exc)


def seed_preferred_overlay_group_defaults_once() -> None:
    """Apply preferred Modern Overlay placement once, without overwriting user overrides."""
    if _overlay_defaults_seeded():
        return
    try:
        from .availability import import_overlay_api

        overlay_api = import_overlay_api()
    except Exception as exc:
        logger.debug("Skipped Modern Overlay preferred defaults: API unavailable: %s", exc)
        return

    user_path = Path(overlay_api.__file__).resolve().parents[1] / "overlay_groupings.user.json"
    try:
        data = _read_json_object(user_path)
    except Exception as exc:
        logger.debug("Skipped Modern Overlay preferred defaults: unable to read %s: %s", user_path, exc)
        return

    if _has_build_tracker_override(data):
        _set_overlay_defaults_seeded(True)
        logger.debug("Modern Overlay preferred defaults already present; marked seeded")
        return

    _apply_build_tracker_defaults(data)
    try:
        user_path.parent.mkdir(parents=True, exist_ok=True)
        user_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.debug("Skipped Modern Overlay preferred defaults: unable to write %s: %s", user_path, exc)
        return

    _set_overlay_defaults_seeded(True)
    logger.info("Seeded preferred Ravencolonial Modern Overlay group defaults")


def _overlay_defaults_seeded() -> bool:
    try:
        from config import config

        return bool(config.get_bool(OVERLAY_DEFAULTS_SEEDED_FLAG, default=False))
    except Exception:
        return False


def _set_overlay_defaults_seeded(value: bool) -> None:
    try:
        from config import config

        config.set(OVERLAY_DEFAULTS_SEEDED_FLAG, bool(value))
    except Exception:
        return


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("overlay_groupings.user.json root must be an object")
    return data


def _has_build_tracker_override(data: Mapping[str, Any]) -> bool:
    if _group_override(data, OVERLAY_PLUGIN_NAME, OVERLAY_GROUP_NAME) is not None:
        return True
    profiles = data.get("_overlay_profile_overrides")
    if not isinstance(profiles, Mapping):
        return False
    for profile_data in profiles.values():
        if isinstance(profile_data, Mapping) and _group_override(profile_data, OVERLAY_PLUGIN_NAME, OVERLAY_GROUP_NAME) is not None:
            return True
    return False


def _group_override(data: Mapping[str, Any], plugin_name: str, group_name: str) -> Optional[Mapping[str, Any]]:
    plugin_block = data.get(plugin_name)
    if not isinstance(plugin_block, Mapping):
        return None
    groups = plugin_block.get("idPrefixGroups")
    if not isinstance(groups, Mapping):
        return None
    group = groups.get(group_name)
    return group if isinstance(group, Mapping) else None


def _apply_build_tracker_defaults(data: dict[str, Any]) -> None:
    _ensure_build_tracker_group(data).update(PREFERRED_GROUP_DEFAULTS)
    profiles = data.setdefault("_overlay_profile_overrides", {})
    if isinstance(profiles, dict):
        default_profile = profiles.setdefault("Default", {})
        if isinstance(default_profile, dict):
            _ensure_build_tracker_group(default_profile).update(PREFERRED_GROUP_DEFAULTS)


def _ensure_build_tracker_group(data: dict[str, Any]) -> dict[str, Any]:
    plugin_block = data.setdefault(OVERLAY_PLUGIN_NAME, {})
    if not isinstance(plugin_block, dict):
        plugin_block = {}
        data[OVERLAY_PLUGIN_NAME] = plugin_block
    groups = plugin_block.setdefault("idPrefixGroups", {})
    if not isinstance(groups, dict):
        groups = {}
        plugin_block["idPrefixGroups"] = groups
    group = groups.setdefault(OVERLAY_GROUP_NAME, {})
    if not isinstance(group, dict):
        group = {}
        groups[OVERLAY_GROUP_NAME] = group
    return group
