"""
Journal Event Handlers

Handles processing of Elite Dangerous journal events for colonization tracking.
"""

import json
import logging
from typing import Any, Dict, Optional

from ..api.client import normalize_commodity_key
from ..i18n import trf
from ..overlay.project_cache import apply_project_cache_update

logger = logging.getLogger(__name__)


class JournalEventHandler:
    """Handles journal events for the Ravencolonial plugin"""

    def __init__(self, plugin_instance):
        """
        Initialize the journal event handler

        :param plugin_instance: The main plugin instance
        """
        self.plugin = plugin_instance

    def _apply_depot_overlay_cache(
        self,
        build_id: str,
        project: Dict[str, Any],
        remaining_need: Dict[str, int],
    ) -> None:
        """Apply journal truth to the matching build and refresh tracker outputs."""
        apply_project_cache_update(
            self.plugin,
            str(build_id),
            remaining_need=remaining_need,
            project_view=project,
        )
        try:
            self.plugin.refresh_build_overlay()
        except Exception as exc:  # noqa: BLE001 - overlay refresh is best-effort
            logger.debug("Overlay refresh after depot cache update skipped: %s", exc)

    def _resolve_depot_project(self) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Return the project/build id matching the current depot location."""
        if not self.plugin.current_system_address or not self.plugin.current_market_id:
            return None, None
        project = self.plugin.get_project(
            self.plugin.current_system_address,
            self.plugin.current_market_id,
            use_location_cache=False,
        )
        build_id = project.get("buildId") if isinstance(project, dict) else None
        return project, build_id

    def _queue_depot_patch(
        self,
        build_id: Optional[str],
        project: Optional[Dict[str, Any]],
        depot_fields: Dict[str, Any],
        remaining_changed: bool,
    ) -> None:
        """Queue a changed depot snapshot while suppressing duplicate payloads."""
        if not remaining_changed:
            logger.debug("Depot remaining need unchanged — skipping depot PATCH")
            return
        if not build_id:
            return
        logger.debug("Depot remaining need changed — queueing PATCH with depot snapshot")
        self.plugin.maybe_clear_phantom_commodities(build_id, project)
        payload = self.plugin.build_depot_patch_payload(build_id, depot_fields)
        sig = json.dumps(payload, sort_keys=True, default=str)
        if sig == self.plugin._last_depot_patch_payload_sig:
            logger.debug("Depot PATCH payload unchanged — skip")
            return
        logger.info("Patching project %s with depot state changes", build_id)
        self.plugin.queue_api_call(self.plugin.patch_project_depot_state, build_id, payload, sig)

    def handle_cargo_depot(self, entry: Dict[str, Any]):
        """Handle CargoDepot journal event.

        RavenColonial contribution attribution should be sourced from
        ColonisationContribution to avoid duplicate commander credit when both
        events are emitted for the same delivery.
        """
        if not self.plugin.cmdr_name or not self.plugin.current_market_id or not self.plugin.current_system_address:
            return

        # Cached lookup — status line only; avoids GET per CargoDepot when depot ticks are noisy
        project = self.plugin.get_project(
            self.plugin.current_system_address,
            self.plugin.current_market_id,
            use_location_cache=True,
        )
        if not project:
            logger.debug("No project found for cargo depot delivery")
            return

        build_id = project.get('buildId')
        if not build_id:
            logger.debug("Project found but no buildId")
            return

        # Check if this is a construction depot delivery
        cargo_type = normalize_commodity_key(entry.get('Type', ''))
        count = entry.get('Count', 0)

        # Do not post /contribute here. ColonisationContribution is authoritative
        # for commander attribution and prevents duplicate contribution rows.
        if entry.get('SubType') == 'Deliver' and cargo_type:
            self.plugin.update_status(
                trf("Delivered {count}x {cargo_type}", count=count, cargo_type=cargo_type)
            )

    def handle_colonisation_construction_depot(self, entry: Dict[str, Any]):
        """Handle ColonisationConstructionDepot journal event (status update)"""
        logger.debug(
            "ColonisationConstructionDepot - cmdr: %s, market: %s, system: %s",
            self.plugin.cmdr_name,
            self.plugin.current_market_id,
            self.plugin.current_system_address,
        )
        logger.debug(f"Event keys: {list(entry.keys())}")

        # Extract MarketID from the event if we don't have it yet
        # This handles the case where EDMC starts while already docked
        event_market_id = entry.get('MarketID')
        if event_market_id and not self.plugin.current_market_id:
            logger.debug(f"Extracting MarketID from event: {event_market_id}")
            self.plugin.current_market_id = event_market_id

        # Try to get SystemAddress from event if we don't have it
        event_system_address = entry.get('SystemAddress')
        if event_system_address and not self.plugin.current_system_address:
            logger.debug(f"Extracting SystemAddress from event: {event_system_address}")
            self.plugin.set_current_system_address(event_system_address)

        # If we still don't have system address, fetch from journal
        if not self.plugin.current_system_address:
            logger.debug("No SystemAddress in event or state, fetching from journal")
            self.plugin.set_current_system_address(self.plugin.get_system_address_from_journal())
            if self.plugin.current_system_address:
                logger.debug(f"Got system address from journal: {self.plugin.current_system_address}")

        if not self.plugin.cmdr_name:
            logger.warning("Missing commander name, cannot process ColonisationConstructionDepot event")
            return

        # Store the full construction depot data for project creation
        self.plugin.construction_depot_data = entry
        self.plugin._track_all_refresh_on_qualifying_undock = True
        logger.info(f"Captured ColonisationConstructionDepot data for {self.plugin.current_station}")

        # Check if construction is complete and handle it
        if self.plugin.completion_handler.handle_construction_complete(entry):
            return

        depot_fields = self.plugin.build_depot_project_fields(refresh=False)
        if not depot_fields:
            logger.debug("ColonisationConstructionDepot has no readable commodity requirements")
            return

        remaining_need = depot_fields["remaining_need"]
        remaining_changed = remaining_need != self.plugin.last_depot_remaining_need

        project, build_id = self._resolve_depot_project()

        # Always fold journal remaining-need into the matching project cache so the
        # overlay/popout keep reading selected-from-cache (docked is visibility only).
        if build_id:
            self._apply_depot_overlay_cache(build_id, project, remaining_need)

        self._queue_depot_patch(build_id, project, depot_fields, remaining_changed)

        # Remaining need is remembered only after a successful depot PATCH (see patch_project_depot_state).

        # If we're receiving this event, we're definitely at a colonization ship
        # Update construction ship status and button state
        logger.debug(
            "State before update - is_docked: %s, market_id: %s, is_construction_ship: %s",
            self.plugin.is_docked,
            self.plugin.current_market_id,
            self.plugin.is_construction_ship,
        )

        if not self.plugin.is_docked:
            self.plugin.is_docked = True
        if not self.plugin.is_construction_ship:
            self.plugin.is_construction_ship = True

        logger.debug("Set is_construction_ship and is_docked to True")
        self.plugin.update_create_button()

    def handle_colonisation_contribution(self, entry: Dict[str, Any]):
        """Handle ColonisationContribution journal event (actual cargo deliveries)"""
        if not self.plugin.cmdr_name or not self.plugin.current_market_id:
            logger.warning(
                "Missing state for contribution - cmdr: %s, market: %s",
                self.plugin.cmdr_name,
                self.plugin.current_market_id,
            )
            return

        # Get system address if we don't have it
        if not self.plugin.current_system_address:
            logger.debug("No system address, fetching from journal")
            self.plugin.set_current_system_address(self.plugin.get_system_address_from_journal())
            if not self.plugin.current_system_address:
                logger.warning("Could not get system address from journal, aborting contribution")
                return
            logger.debug(f"Got system address from journal: {self.plugin.current_system_address}")

        # Get current project to get buildId
        project = self.plugin.get_project(
            self.plugin.current_system_address,
            self.plugin.current_market_id,
            use_location_cache=True,
        )
        if not project:
            logger.warning(f"No project found for market {self.plugin.current_market_id}")
            return

        build_id = project.get('buildId')
        if not build_id:
            logger.warning("Project found but no buildId")
            return

        # Extract delivered commodities from Contributions
        contributions = entry.get('Contributions', [])
        if not contributions:
            logger.debug("No contributions in this event")
            return

        # Build cargo diff from contributions
        cargo_diff = {}
        for contribution in contributions:
            commodity_name = normalize_commodity_key(contribution.get('Name', ''))
            delivered_amount = contribution.get('Amount', 0)
            if commodity_name and delivered_amount > 0:
                cargo_diff[commodity_name] = cargo_diff.get(commodity_name, 0) + delivered_amount

        if cargo_diff:
            total_delivered = sum(cargo_diff.values())
            logger.info(f"Submitting {total_delivered} units to project {build_id}: {cargo_diff}")
            # Update commander contribution (for bar graph)
            # Note: Project supply totals are updated via ColonisationConstructionDepot diffs
            self.plugin.queue_api_call(self.plugin.api_client.contribute_cargo,
                                       build_id, self.plugin.cmdr_name, cargo_diff)
            self.plugin.update_status(
                trf("Delivered {total} units to colonization", total=total_delivered)
            )
            self.plugin.refresh_build_overlay()

    def handle_market(self, entry: Dict[str, Any]):
        """Handle Market journal event"""
        # Market data could be used to sync current needs
        pass
