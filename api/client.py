"""
Ravencolonial API Client

Handles all communication with the Ravencolonial API endpoints.
"""

import json
import logging
import urllib.parse
from typing import Optional, Dict, Any, List, Union
import os

import requests
import timeout_session
from config import appname

# Use EDMC-compliant logger namespace
plugin_name = os.path.basename(os.path.dirname(os.path.dirname(__file__)))
logger = logging.getLogger(f'{appname}.{plugin_name}.api')
# Disable propagation to avoid inheriting EDMC's osthreadid formatter
logger.propagate = False
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(name)s: %(levelname)s - %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

# Route parity with docs/RavenColonial_API_Reference.md (methods / verbs / paths):
#   get_project            GET    /api/system/{id64}/{marketId}  (lowercase paths; match SrvSurvey / typical host routing)
#   contribute_cargo       POST   /api/project/{buildId}/contribute/{cmdr}   body: Cargo map
#   update_project_supply  POST   /api/project/{buildId}                     body: ProjectUpdate (buildId, commodities, maxNeed, …)
#   get_commander_projects GET    /api/cmdr/{cmdr}/active
#   get_system_sites       GET    /api/v2/system/{nameOrNum}/sites   (nameOrNum = system name or id64)
#   get_system_bodies      GET    /api/v2/system/{nameOrNum}/bodies
#   create_project         PUT    /api/project                               body: ProjectCreate
#   get_system_architect   GET    /api/v2/system/{nameOrNum}/architect       response: string (or wrapped dict handled in code)
#   update_project_name    PATCH  /api/project/{buildId}                     body: ProjectUpdate
#   mark_project_complete  POST   /api/project/{buildId}/complete            bodyless
#   get_fc                 GET    /api/fc/{marketId}
#   update_fc_cargo        POST   /api/fc/{marketId}/cargo   + header rcc-key only (SrvSurvey `updateCargoFC`; key scopes commander)
#   supply_fc              PATCH  /api/fc/{marketId}/cargo   + rcc-key only (SrvSurvey `supplyFC`; signed deltas)
#   get_all_cmdr_fcs       GET    /api/cmdr/{cmdr}/fc/all
#   publish_current_ship   POST   /api/cmdr/currentShip      + rcc-key only (SrvSurvey ``publishCurrentShip``)
# OpenAPI does not declare FC auth headers; plugin matches RavenColonialWeb/SrvSurvey behavior.


def normalize_commodity_key(name: str) -> str:
    """
    RavenColonial `Cargo` maps use lowercase commodity keys (see docs/RavenColonial_API_Reference.md).
    Journal/CAPI names may include $ prefix and _name / _name; suffixes.
    """
    if not name:
        return ""
    s = str(name).replace("$", "").replace("_name;", "").replace("_name", "").strip().lower()
    return s


def _normalize_cargo_map(cargo: Dict[str, int]) -> Dict[str, int]:
    """Merge keys that normalize to the same commodity (sums values)."""
    out: Dict[str, int] = {}
    for k, v in cargo.items():
        nk = normalize_commodity_key(k) if k is not None else ""
        if not nk:
            continue
        try:
            out[nk] = out.get(nk, 0) + int(v)
        except (TypeError, ValueError):
            logger.warning("Skipping non-numeric cargo quantity for key %r", k)
    return out


def _v2_system_path_segment(name_or_num: Union[str, int]) -> str:
    """URL path segment for ``/api/v2/system/{nameOrNum}/…`` (matches SrvSurvey escaping)."""
    return urllib.parse.quote(str(name_or_num), safe="")


class RavencolonialAPIClient:
    """Client for interacting with Ravencolonial API"""
    
    def __init__(self, api_base: str, user_agent: str):
        """
        Initialize the API client
        
        :param api_base: Base URL for the API
        :param user_agent: User agent string for requests
        """
        self.api_base = api_base
        self.cmdr_name = None
        self.api_key = None
        self.session = timeout_session.new_session(timeout=10)
        self.session.headers['User-Agent'] = user_agent
        self.session.headers['Content-Type'] = 'application/json'
        logger.info("API client initialized (timeout_session, default HTTP timeout 10s)")
    
    def set_credentials(self, cmdr_name: str, api_key: str):
        """
        Set commander context and Ravencolonial API key.
        FC cargo mutations use ``rcc-key`` only (same as SrvSurvey); cmdr is used
        for URLs such as ``/contribute/{cmdr}``, not as an ``rcc-cmdr`` header.
        """
        self.cmdr_name = cmdr_name
        self.api_key = api_key
        logger.debug(f"Set credentials for commander: {cmdr_name}")
    
    def get_project(self, system_address: int, market_id: int) -> Optional[Dict]:
        """Get project details for a specific system/station (GET /api/system/{id64}/{marketId}; lowercase like SrvSurvey)."""
        try:
            url = f"{self.api_base}/api/system/{system_address}/{market_id}"
            response = self.session.get(url, timeout=10)
            
            if response.status_code == 404:
                return None
            
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get project: {e}")
            return None
    
    def contribute_cargo(self, build_id: str, cmdr: str, cargo_diff: Dict[str, int]) -> bool:
        """Submit cargo contribution to Ravencolonial (for commander attribution)"""
        try:
            bid = urllib.parse.quote(build_id, safe="")
            url = f"{self.api_base}/api/project/{bid}/contribute/{urllib.parse.quote(cmdr, safe='')}"
            logger.debug(f"Contribution URL: {url}")
            body = _normalize_cargo_map(cargo_diff)
            logger.debug(f"Contribution payload: {body}")
            response = self.session.post(url, json=body, timeout=10)
            logger.debug(f"Contribution response status: {response.status_code}")
            response.raise_for_status()
            logger.info("Contributed cargo to project %s: %s", build_id, body)
            return True
        except Exception as e:
            logger.error("Failed to contribute cargo: %s", e, exc_info=True)
            return False
    
    def update_project_supply(self, build_id: str, payload: Dict) -> bool:
        """Update project supply totals (for the 'Need' column)"""
        try:
            bid = urllib.parse.quote(build_id, safe="")
            url = f"{self.api_base}/api/project/{bid}"
            body = dict(payload)
            if isinstance(body.get("commodities"), dict):
                body["commodities"] = _normalize_cargo_map(body["commodities"])
            logger.debug(f"Update supply URL: {url}")
            logger.debug(f"Update supply payload: {json.dumps(body)}")
            response = self.session.post(url, json=body, timeout=10)
            logger.debug(f"Update supply response status: {response.status_code}")
            logger.debug(f"Update supply response body: {response.text}")
            response.raise_for_status()
            logger.info(f"Updated project supply for {build_id}")
            return True
        except Exception as e:
            logger.error("Failed to update project supply: %s", e, exc_info=True)
            return False
    
    def get_commander_projects(self, cmdr: str) -> list:
        """Get active projects for a commander (GET /api/cmdr/{cmdr}/active)."""
        try:
            url = f"{self.api_base}/api/cmdr/{urllib.parse.quote(cmdr, safe='')}/active"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get commander projects: {e}")
            return []
    
    def get_system_sites(self, name_or_num: Union[str, int]) -> List[Dict]:
        """GET /api/v2/system/{nameOrNum}/sites — ``name_or_num`` is system name or id64."""
        seg = _v2_system_path_segment(name_or_num)
        logger.debug("get_system_sites nameOrNum=%r segment=%s", name_or_num, seg)
        
        try:
            url = f"{self.api_base}/api/v2/system/{seg}/sites"
            logger.debug(f"Fetching sites from URL: {url}")
            response = self.session.get(url, timeout=10)
            logger.debug(f"Sites API response status: {response.status_code}")
            if response.status_code != 200:
                logger.debug(f"Sites API response body: {response.text}")
            response.raise_for_status()
            sites = response.json()
            logger.debug(f"Successfully fetched {len(sites)} sites: {sites}")
            return sites
        except Exception as e:
            logger.error("Failed to get system sites: %s", e, exc_info=True)
            return []
    
    def get_system_bodies(self, name_or_num: Union[str, int]) -> List[Dict]:
        """GET /api/v2/system/{nameOrNum}/bodies — system name or id64."""
        seg = _v2_system_path_segment(name_or_num)
        try:
            url = f"{self.api_base}/api/v2/system/{seg}/bodies"
            logger.debug(f"Bodies URL: {url}")
            response = self.session.get(url, timeout=10)
            logger.debug(f"Bodies response status: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            
            # Ravencolonial returns an array of body objects
            bodies = data if isinstance(data, list) else []
            logger.debug(f"Extracted {len(bodies)} bodies from response")
            
            return bodies
        except Exception as e:
            logger.error(f"Failed to get system bodies: {e}")
            return []
    
    def create_project(self, project_data: Dict[str, Any]) -> Optional[Dict]:
        """Create a new colonization project (OpenAPI: PUT /api/project)"""
        url = f"{self.api_base}/api/project"
        body = dict(project_data)
        if isinstance(body.get("commodities"), dict):
            body["commodities"] = _normalize_cargo_map(body["commodities"])
        
        try:
            body_preview = json.dumps(body, default=str)[:8000]
        except Exception:
            body_preview = repr(body)[:8000]
        logger.debug("create_project PUT %s body=%s", url, body_preview)
        
        try:
            response = self.session.put(url, json=body, timeout=10)
            if not response.ok:
                logger.error(
                    "create_project failed: HTTP %s %s\n%s",
                    response.status_code,
                    response.reason,
                    response.text[:4000],
                )
                return None
            
            logger.debug("create_project response HTTP %s", response.status_code)
            result = response.json()
            logger.info("Created project buildId=%s", result.get("buildId"))
            return result
            
        except Exception as e:
            logger.error(f"EXCEPTION while creating project: {e}", exc_info=True)
            return None
    
    def get_system_architect(self, name_or_num: Union[str, int]) -> Optional[str]:
        """GET /api/v2/system/{nameOrNum}/architect — system name or id64."""
        seg = _v2_system_path_segment(name_or_num)
        try:
            url = f"{self.api_base}/api/v2/system/{seg}/architect"
            logger.debug(f"Getting system architect from URL: {url}")
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            # Response schema is plain string; some stacks may still wrap — normalize
            if isinstance(data, str):
                architect = data.strip() or None
            elif isinstance(data, dict):
                architect = data.get('architect')
            else:
                architect = None
            logger.debug(f"System architect response: {architect}")
            return architect
        except Exception as e:
            logger.error(f"Failed to get system architect: {e}")
            return None
    
    def update_project_name(self, build_id: str, new_name: str) -> bool:
        """Update a project's buildName via PATCH
        
        :param build_id: The project build ID
        :param new_name: The new build name (without prefix)
        :return: True if successful, False otherwise
        """
        logger.debug("=" * 80)
        logger.debug("API CLIENT - update_project_name START")
        logger.debug(f"BuildID: {build_id}")
        logger.debug(f"New name: {new_name}")
        logger.debug(f"API Base: {self.api_base}")
        
        try:
            url = f"{self.api_base}/api/project/{urllib.parse.quote(build_id)}"
            # ProjectUpdate requires buildId; only buildName is changed
            payload = {"buildId": build_id, "buildName": new_name}
            
            logger.debug(f"PATCH URL: {url}")
            logger.debug(f"Payload: {payload}")
            logger.debug("Sending PATCH request...")
            
            response = self.session.patch(url, json=payload, timeout=10)
            
            logger.debug(f"Response received - Status: {response.status_code}")
            logger.debug(f"Response body: {response.text}")
            
            response.raise_for_status()
            
            logger.info(f"✓ Successfully updated project {build_id} name to: {new_name}")
            logger.debug("API CLIENT - update_project_name END (success)")
            logger.debug("=" * 80)
            return True
            
        except Exception as e:
            logger.error(f"✗ Error updating project name: {e}", exc_info=True)
            logger.debug("API CLIENT - update_project_name END (error)")
            logger.debug("=" * 80)
            return False
    
    def mark_project_complete(self, build_id: str) -> bool:
        """Mark a project as complete in Ravencolonial"""
        logger.debug("=" * 80)
        logger.debug("API CLIENT - mark_project_complete START")
        logger.debug(f"BuildID: {build_id}")
        logger.debug(f"API Base: {self.api_base}")
        
        try:
            url = f"{self.api_base}/api/project/{urllib.parse.quote(build_id)}/complete"
            logger.debug(f"POST URL: {url}")
            logger.debug(f"Request timeout: 10s")
            logger.debug("Sending POST request...")
            
            response = self.session.post(url, timeout=10)
            
            logger.debug(f"Response received - Status: {response.status_code}")
            logger.debug(f"Response headers: {dict(response.headers)}")
            logger.debug(f"Response body: {response.text}")
            
            response.raise_for_status()
            
            logger.info(f"✓ Successfully marked project {build_id} as complete")
            logger.debug("API CLIENT - mark_project_complete END (success)")
            logger.debug("=" * 80)
            return True
            
        except requests.exceptions.Timeout as e:
            logger.error(f"✗ Timeout marking project complete: {e}")
            logger.error(f"Request timed out after 10 seconds")
            logger.debug("API CLIENT - mark_project_complete END (timeout)")
            logger.debug("=" * 80)
            return False
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"✗ HTTP error marking project complete: {e}")
            logger.error(f"Status code: {e.response.status_code if e.response else 'N/A'}")
            logger.error(f"Response body: {e.response.text if e.response else 'N/A'}")
            logger.debug("API CLIENT - mark_project_complete END (HTTP error)")
            logger.debug("=" * 80)
            return False
            
        except Exception as e:
            logger.error(f"✗ Unexpected error marking project complete: {e}")
            logger.error(f"Exception type: {type(e).__name__}")
            logger.error(f"Exception details: {str(e)}", exc_info=True)
            logger.debug("API CLIENT - mark_project_complete END (exception)")
            logger.debug("=" * 80)
            return False
    
    # Fleet Carrier methods
    def get_fc(self, market_id: int) -> Optional[Dict[str, Any]]:
        """Get Fleet Carrier data (GET /api/fc/{marketId}; lowercase like SrvSurvey)."""
        try:
            url = f"{self.api_base}/api/fc/{market_id}"
            logger.debug(f"Getting FC data from URL: {url}")
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            fc_data = response.json()
            logger.debug(f"FC data response: {fc_data}")
            return fc_data
        except Exception as e:
            logger.error(f"Failed to get FC data: {e}")
            return None
    
    def update_fc_cargo(self, market_id: int, cargo: Dict[str, int]) -> Optional[Dict[str, int]]:
        """Fully replace Fleet Carrier cargo with new totals"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                url = f"{self.api_base}/api/fc/{market_id}/cargo"
                if attempt > 0:
                    logger.warning(f"Retry attempt {attempt}/{max_attempts - 1} for FC cargo update")
                logger.debug(f"Updating FC cargo at URL: {url}")
                body = _normalize_cargo_map(cargo)
                logger.debug(f"New cargo: {body}")
                
                # Auth: SrvSurvey (njthomson/SrvSurvey) sends rcc-key only for FC cargo; API key identifies the account.
                headers = {}
                if getattr(self, "api_key", None):
                    headers["rcc-key"] = self.api_key
                
                response = self.session.post(url, json=body, headers=headers, timeout=15)
                logger.debug(f"Update FC cargo response status: {response.status_code}")
                logger.debug(f"Update FC cargo response body: {response.text}")
                response.raise_for_status()
                
                updated_cargo = response.json()
                logger.info(f"Successfully updated FC {market_id} cargo")
                return updated_cargo
            except requests.exceptions.Timeout as e:
                if attempt < max_attempts - 1:
                    logger.warning(f"Timeout on attempt {attempt + 1}/{max_attempts}: {e}")
                    continue  # Retry
                else:
                    logger.error(f"Failed to update FC cargo after {max_attempts} attempts (timeout): {e}")
                    return None
            except Exception as e:
                logger.error(f"Failed to update FC cargo: {e}")
                logger.error(f"Exception details: {type(e).__name__}: {str(e)}")
                return None
    
    def supply_fc(self, market_id: int, cargo_diff: Dict[str, int]) -> Optional[Dict[str, int]]:
        """Incrementally update Fleet Carrier cargo (add/remove specific quantities)"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                url = f"{self.api_base}/api/fc/{market_id}/cargo"
                if attempt > 0:
                    logger.warning(f"Retry attempt {attempt}/{max_attempts - 1} for FC cargo supply")
                logger.debug(f"Supplying FC cargo at URL: {url}")
                body = _normalize_cargo_map(cargo_diff)
                logger.debug(f"Cargo diff: {body}")
                
                headers = {}
                if getattr(self, "api_key", None):
                    headers["rcc-key"] = self.api_key
                
                response = self.session.patch(url, json=body, headers=headers, timeout=15)
                logger.debug(f"Supply FC response status: {response.status_code}")
                logger.debug(f"Supply FC response body: {response.text}")
                response.raise_for_status()
                
                updated_cargo = response.json()
                logger.info(f"Successfully supplied FC {market_id} with cargo diff")
                return updated_cargo
            except requests.exceptions.Timeout as e:
                if attempt < max_attempts - 1:
                    logger.warning(f"Timeout on attempt {attempt + 1}/{max_attempts}: {e}")
                    continue  # Retry
                else:
                    logger.error(f"Failed to supply FC cargo after {max_attempts} attempts (timeout): {e}")
                    return None
            except Exception as e:
                logger.error(f"Failed to supply FC cargo: {e}")
                logger.error(f"Exception details: {type(e).__name__}: {str(e)}")
                return None

    def publish_current_ship(self, payload: Dict[str, Any]) -> bool:
        """
        POST /api/cmdr/currentShip with Cmdr-shaped JSON body (``cmdr``, ``name``, ``type``,
        ``maxCargo``, ``cargo`` map). Auth: ``rcc-key`` only, matching SrvSurvey
        ``RavenColonial.publishCurrentShip``.
        """
        if not getattr(self, "api_key", None):
            logger.debug("publish_current_ship skipped: no API key")
            return False
        try:
            url = f"{self.api_base}/api/cmdr/currentShip"
            headers = {"rcc-key": self.api_key}
            body = dict(payload)
            body["cargo"] = _normalize_cargo_map(body.get("cargo") or {})
            response = self.session.post(url, json=body, headers=headers, timeout=15)
            if not response.ok:
                logger.warning(
                    "publish_current_ship HTTP %s: %s",
                    response.status_code,
                    (response.text or "")[:500],
                )
                return False
            logger.info("Published commander ship snapshot to RavenColonial")
            return True
        except Exception as e:
            logger.error("publish_current_ship failed: %s", e)
            return False

    def get_all_cmdr_fcs(self, cmdr_name: str) -> List[Dict[str, Any]]:
        """Get all Fleet Carriers linked to a commander
        
        Returns a list of FC objects with marketId, name, displayName, and cargo dict
        """
        try:
            url = f"{self.api_base}/api/cmdr/{urllib.parse.quote(cmdr_name, safe='')}/fc/all"
            logger.debug(f"Getting all CMDR FCs from URL: {url}")
            response = self.session.get(url, timeout=10)
            
            # 404 means no FCs linked yet - this is normal, not an error
            if response.status_code == 404:
                logger.info(f"No Fleet Carriers linked for commander {cmdr_name}")
                return []
            
            response.raise_for_status()
            fcs = response.json()
            logger.debug(f"CMDR FCs response: {fcs}")
            return fcs if isinstance(fcs, list) else []
        except Exception as e:
            logger.error(f"Failed to get CMDR FCs: {e}")
            return []
