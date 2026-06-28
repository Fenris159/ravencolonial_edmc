"""Light typing protocol for plugin objects accessed from extracted UI workers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class PluginProtocol(Protocol):
    """RavenColonialPlugin surface used by overlay/plan-site worker modules."""

    cmdr_name: Optional[str]
    current_market_id: Optional[int]
    current_station: Optional[str]
    current_system_address: Optional[int]
    current_build_id: Any
    plan_sites_rows: List[Any]
    plan_sites_system_key: Any
    selected_plan_site_id: Any
    selected_plan_site_obj: Any
    overlay_carrier_tracking_enabled: bool
    overlay_modern_enabled: bool
    overlay_popout_enabled: bool
    overlay_ui_enabled: bool
    overlay_project_cache: Any
    overlay_project_cache_by_build_id: Dict[str, Any]
    overlay_project_linked_fcs: List[Any]
    overlay_fc_cargo_by_market: Dict[Any, Any]
    overlay_project_fetch_inflight: bool
    selected_overlay_build_id: Any
    construction_depot_data: Any
    fc_handler: Any
    api_client: Any
    build_overlay: Any

    def get_project_by_build_id(self, bid: str) -> Any:
        ...

    def get_system_bodies(self, system_address: int) -> Any:
        ...

    def set_current_system_address(self, system_address: int) -> None:
        ...

    def maybe_clear_phantom_commodities(self, build_id: str, project: Any) -> None:
        ...

    def queue_initial_project_supply_update(self, build_id: str, depot_fields: Dict[str, Any]) -> None:
        ...

    def invalidate_project_location_cache(self) -> None:
        ...
