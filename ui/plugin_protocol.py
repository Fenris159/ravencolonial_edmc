"""Light typing protocol for plugin objects accessed from extracted UI workers."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class PluginProtocol(Protocol):
    """Subset of RavenColonialPlugin attributes used by overlay/plan-site workers."""

    cmdr_name: Optional[str]
    current_market_id: Optional[int]
    current_station: Optional[str]
    current_system_address: Optional[int]
    overlay_carrier_tracking_enabled: bool
    overlay_modern_enabled: bool
    overlay_popout_enabled: bool
    overlay_ui_enabled: bool
    selected_overlay_build_id: Any
    construction_depot_data: Any
    fc_handler: Any
    api_client: Any

    def get_project_by_build_id(self, bid: str) -> Any:
        ...
