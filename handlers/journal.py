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
            self.plugin.current_system_address = event_system_address
        
        # If we still don't have system address, fetch from journal
        if not self.plugin.current_system_address:
            logger.debug("No SystemAddress in event or state, fetching from journal")
            self.plugin.current_system_address = self.plugin.get_system_address_from_journal()
            if self.plugin.current_system_address:
                logger.debug(f"Got system address from journal: {self.plugin.current_system_address}")
        
        if not self.plugin.cmdr_name:
            logger.warning("Missing commander name, cannot process ColonisationConstructionDepot event")
            return
        
        # Store the full construction depot data for project creation
        self.plugin.construction_depot_data = entry
        logger.info(f"Captured ColonisationConstructionDepot data for {self.plugin.current_station}")
        
        # Check if construction is complete and handle it
        if self.plugin.completion_handler.handle_construction_complete(entry):
            # Construction was complete and handled, skip supply updates
            return
        
        # Calculate current needed amounts (RequiredAmount - ProvidedAmount)
        resources = entry.get('ResourcesRequired', [])
        needed = {}
        max_need = 0
        for resource in resources:
            commodity_name = normalize_commodity_key(resource.get('Name', ''))
            required = resource.get('RequiredAmount', 0)
            provided = resource.get('ProvidedAmount', 0)
            still_needed = required - provided
            if commodity_name and required > 0:
                needed[commodity_name] = still_needed
                max_need += required
        
        # Check if totals changed since last time
        if self.plugin.last_depot_state != needed and needed:
            # Update the project with current needed amounts
            if self.plugin.current_system_address and self.plugin.current_market_id:
                logger.debug("Depot needs changed - updating project")
                logger.debug(f"Max need: {max_need}")
                project = self.plugin.get_project(
                    self.plugin.current_system_address,
                    self.plugin.current_market_id,
                    use_location_cache=False,
                )
                if project and project.get('buildId'):
                    build_id = project['buildId']
                    logger.info(f"Updating project {build_id} with depot state changes")
                    # Send full needed amounts with maxNeed (ProjectUpdate format)
                    payload = {
                        "buildId": build_id,
                        "commodities": needed,
                        "maxNeed": max_need
                    }
                    sig = json.dumps(payload, sort_keys=True, default=str)
                    if sig == getattr(self.plugin, "_last_supply_payload_sig", None):
                        logger.debug("Depot supply payload unchanged — skip POST")
                    else:
                        self.plugin._last_supply_payload_sig = sig
                        self.plugin.queue_api_call(self.plugin.api_client.update_project_supply, build_id, payload)
        else:
            if self.plugin.last_depot_state == needed:
                logger.debug("Depot state unchanged - skipping supply update")
        
        # Store current state for next comparison
        self.plugin.last_depot_state = needed
        
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
            self.plugin.current_system_address = self.plugin.get_system_address_from_journal()
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
    
    def handle_market(self, entry: Dict[str, Any]):
        """Handle Market journal event"""
        # Market data could be used to sync current needs
        pass
