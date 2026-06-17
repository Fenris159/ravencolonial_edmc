"""
Journal Event Handlers

Handles processing of Elite Dangerous journal events for colonization tracking.
"""

import json
import logging
from typing import Dict, Any

from ..api.client import normalize_commodity_key
from ..i18n import trf

logger = logging.getLogger(__name__)


class JournalEventHandler:
    """Handles journal events for the Ravencolonial plugin"""
    
    def __init__(self, plugin_instance):
        """
        Initialize the journal event handler
        
        :param plugin_instance: The main plugin instance
        """
        self.plugin = plugin_instance
    
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
        logger.debug(f"ColonisationConstructionDepot - cmdr: {self.plugin.cmdr_name}, market: {self.plugin.current_market_id}, system: {self.plugin.current_system_address}")
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

        if remaining_changed:
            if self.plugin.current_system_address and self.plugin.current_market_id:
                logger.debug("Depot remaining need changed — queueing PATCH with depot snapshot")
                project = self.plugin.get_project(
                    self.plugin.current_system_address,
                    self.plugin.current_market_id,
                    use_location_cache=False,
                )
                if project and project.get('buildId'):
                    build_id = project['buildId']
                    self.plugin.maybe_clear_phantom_commodities(build_id, project)
                    payload = self.plugin.build_depot_patch_payload(build_id, depot_fields)
                    sig = json.dumps(payload, sort_keys=True, default=str)
                    if sig == self.plugin._last_depot_patch_payload_sig:
                        logger.debug("Depot PATCH payload unchanged — skip")
                    else:
                        logger.info("Patching project %s with depot state changes", build_id)
                        self.plugin.queue_api_call(
                            self.plugin.patch_project_depot_state, build_id, payload, sig
                        )
        else:
            logger.debug("Depot remaining need unchanged — skipping depot PATCH")

        # Remaining need is remembered only after a successful depot PATCH (see patch_project_depot_state).
        
        # If we're receiving this event, we're definitely at a colonization ship
        # Update construction ship status and button state
        logger.debug(f"State before update - is_docked: {self.plugin.is_docked}, market_id: {self.plugin.current_market_id}, is_construction_ship: {self.plugin.is_construction_ship}")
        
        if not self.plugin.is_docked:
            self.plugin.is_docked = True
        if not self.plugin.is_construction_ship:
            self.plugin.is_construction_ship = True
        
        logger.debug("Set is_construction_ship and is_docked to True")
        self.plugin.update_create_button()
    
    def handle_colonisation_contribution(self, entry: Dict[str, Any]):
        """Handle ColonisationContribution journal event (actual cargo deliveries)"""
        if not self.plugin.cmdr_name or not self.plugin.current_market_id:
            logger.warning(f"Missing state for contribution - cmdr: {self.plugin.cmdr_name}, market: {self.plugin.current_market_id}")
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
            self.plugin.queue_api_call(self.plugin.api_client.contribute_cargo, build_id, self.plugin.cmdr_name, cargo_diff)
            self.plugin.update_status(
                trf("Delivered {total} units to colonization", total=total_delivered)
            )
            self.plugin.refresh_build_overlay()
    
    def handle_market(self, entry: Dict[str, Any]):
        """Handle Market journal event"""
        # Market data could be used to sync current needs
        pass
