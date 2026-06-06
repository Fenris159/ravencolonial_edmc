"""
Ravencolonial API Client

Handles all communication with the Ravencolonial API endpoints.
"""

import json
import logging
import time
import urllib.parse
from typing import Optional, Dict, Any, List, Union
import os

import requests
import timeout_session
from config import appname

# Transient failures: retry GET/PATCH/full ship snapshots on read timeout; POST /contribute
# retries connection errors only (read timeout may mean the server already applied the body).
_API_RETRY_ATTEMPTS = 3
_API_RETRY_BACKOFF_S = 1.5

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
#   contribute_cargo       POST   /api/project/{buildId}/contribute/{cmdr}   body: Cargo map — commander delivery history ONLY; does not change project remaining need
#   patch_project_update   PATCH  /api/project/{buildId}                     body: ProjectUpdate (+ colonisationConstructionDepot) — authoritative remaining need from journal
#   (POST /api/project/{buildId}/supply/{cmdr} subtracts remaining need then contributes; journal-aware clients use PATCH depot + /contribute instead — this plugin never calls /supply)
#   get_commander_projects GET    /api/cmdr/{cmdr}/active
#   get_system_sites       GET    /api/v2/system/{nameOrNum}/sites   (nameOrNum = system name or id64)
#   update_system_sites    PUT    /api/v2/system/{nameOrNum}/sites   body: SitesPut + rcc-key
#   patch_system_site      PATCH  /api/v2/system/{nameOrNum}/sites/{siteId}   body: partial Site + rcc-key
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


def _http_request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    max_attempts: int = _API_RETRY_ATTEMPTS,
    retry_read_timeout: bool = True,
    **kwargs: Any,
) -> requests.Response:
    """
    Retry transient HTTP failures with bounded backoff.

    ``retry_read_timeout=False`` for non-idempotent POSTs (e.g. ``/contribute``) where
    a read timeout may mean the server already recorded the payload.
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(max_attempts):
        try:
            if attempt > 0:
                logger.warning("Retry %s/%s %s %s", attempt + 1, max_attempts, method, url)
            return session.request(method, url, **kwargs)
        except requests.exceptions.ReadTimeout as e:
            last_exc = e
            if not retry_read_timeout:
                logger.warning(
                    "Read timeout on %s %s — not retrying (avoid duplicate side effects)",
                    method,
                    url,
                )
                raise
            if attempt >= max_attempts - 1:
                raise
            logger.warning(
                "Read timeout attempt %s/%s for %s %s: %s",
                attempt + 1,
                max_attempts,
                method,
                url,
                e,
            )
            time.sleep(_API_RETRY_BACKOFF_S * attempt + 0.5)
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            if attempt >= max_attempts - 1:
                raise
            logger.warning(
                "Connection error attempt %s/%s for %s %s: %s",
                attempt + 1,
                max_attempts,
                method,
                url,
                e,
            )
            time.sleep(_API_RETRY_BACKOFF_S * attempt + 0.5)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("_http_request_with_retry exhausted without response")


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


def _normalize_project_need_map(cargo: Dict[str, int]) -> Dict[str, int]:
    """Normalize project need/supply commodity maps (non-negative totals for the Need column)."""
    return {k: max(0, v) for k, v in _normalize_cargo_map(cargo).items()}


def plan_site_body_num(site: Dict[str, Any]) -> Optional[int]:
    """``bodyNum`` from a ``GET /api/v2/system/.../sites`` row (``0`` is valid)."""
    if not isinstance(site, dict):
        return None
    for key in ("bodyNum", "body_id", "bodyId", "body_num"):
        if key not in site or site[key] is None:
            continue
        try:
            return int(site[key])
        except (TypeError, ValueError):
            continue
    return None


def body_name_for_num(body_num: int, bodies: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    """Resolve a body display name from ``GET /api/v2/system/.../bodies``."""
    try:
        target = int(body_num)
    except (TypeError, ValueError):
        return None
    for body in bodies or []:
        if not isinstance(body, dict):
            continue
        for key in ("num", "id", "bodyId", "body_id"):
            if key not in body or body[key] is None:
                continue
            try:
                if int(body[key]) != target:
                    continue
            except (TypeError, ValueError):
                continue
            name = body.get("name")
            if name is not None and str(name).strip():
                return str(name).strip()
            break
    return None


def plan_site_put_body_fields(
    site: Dict[str, Any],
    bodies: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    ``bodyNum`` / ``bodyName`` for ``PUT /api/project`` from a v2 plan-site row.

    Site rows always carry ``bodyNum``; ``bodyName`` is resolved from the row when
    present, otherwise from the system bodies list (same data the create dialog uses).
    """
    body_num = plan_site_body_num(site)
    if body_num is None:
        return {}
    out: Dict[str, Any] = {"bodyNum": body_num}
    for key in ("bodyName", "body_name"):
        name = site.get(key)
        if name is not None and str(name).strip():
            out["bodyName"] = str(name).strip()
            return out
    resolved = body_name_for_num(body_num, bodies)
    if resolved:
        out["bodyName"] = resolved
    return out


def prepare_put_project_body(
    base: Dict[str, Any],
    depot_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Merge depot snapshot fields and normalize a ``PUT /api/project`` body.

    Callers supply flow-specific keys (create-dialog fields or link ``systemSiteId``).
    When ``depot_fields`` is provided (from ``build_depot_project_fields()``), the
    ``commodities``, ``maxNeed``, and ``colonisationConstructionDepot`` keys are set
    from that snapshot. Commodity maps are always normalized for outbound PUT.
    """
    body = dict(base)
    if depot_fields:
        body["commodities"] = depot_fields["commodities"]
        body["maxNeed"] = depot_fields["maxNeed"]
        body["colonisationConstructionDepot"] = depot_fields["colonisationConstructionDepot"]
    commodities = body.get("commodities")
    if isinstance(commodities, dict):
        body["commodities"] = _normalize_project_need_map(commodities)
    return body


def phantom_commodity_zero_patch_map(server_commodities: Dict[str, Any]) -> Dict[str, int]:
    """
    Build a PATCH ``commodities`` map that clears server template placeholders (e.g. ``-1``).

    Ravencolonial may seed build-type template slots on link; unset keys stay at ``-1`` and
    render as ``?`` on the website until explicitly zeroed.
    """
    zeroes: Dict[str, int] = {}
    for k, v in (server_commodities or {}).items():
        nk = normalize_commodity_key(k)
        if not nk:
            continue
        try:
            n = int(v)
        except (TypeError, ValueError):
            continue
        if n < 0:
            zeroes[nk] = 0
    return zeroes


def _v2_system_path_segment(name_or_num: Union[str, int]) -> str:
    """URL path segment for ``/api/v2/system/{nameOrNum}/…`` (matches SrvSurvey escaping)."""
    return urllib.parse.quote(str(name_or_num), safe="")


def _strip_wrapping_json_quotes(value: str) -> str:
    """Unwrap host responses that double-encode plain strings as ``'"Name"'``."""
    s = value.strip()
    for _ in range(3):
        if len(s) >= 2 and s[0] == s[-1] == '"':
            try:
                decoded = json.loads(s)
            except (ValueError, TypeError):
                s = s[1:-1].strip()
                continue
            if isinstance(decoded, str):
                s = decoded.strip()
                continue
        break
    return s


def parse_system_architect_response(data: Any) -> Optional[str]:
    """Normalize ``GET /api/v2/system/.../architect`` JSON (string or object) to a commander name."""
    if data is None:
        return None
    if isinstance(data, dict):
        for k in ("architect", "architectName", "name", "cmdr", "commander"):
            v = data.get(k)
            if v is not None and str(v).strip():
                return _strip_wrapping_json_quotes(str(v).strip()) or None
        return None
    if isinstance(data, str):
        s = _strip_wrapping_json_quotes(data.strip())
        return s or None
    return None


def _truthy_build_id_from_mapping(d: dict) -> Optional[str]:
    """Return stripped build id string if present (camelCase / PascalCase / snake)."""
    for key in ("buildId", "BuildId", "build_id"):
        v = d.get(key)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return None


def resolve_build_id(project: Optional[Dict[str, Any]]) -> Optional[str]:
    """Stable build id string from a project dict (any supported key spelling)."""
    if not isinstance(project, dict):
        return None
    return _truthy_build_id_from_mapping(project)



def resolve_build_id_from_site(
    site: Optional[Dict[str, Any]],
    *,
    system_address: Optional[int] = None,
    get_project_at_location: Optional[Any] = None,
) -> Optional[str]:
    """Resolve build id from a v2 ``/sites`` row (status ``build``)."""
    if not isinstance(site, dict):
        return None
    bid = resolve_build_id(site)
    if bid:
        return bid
    mid = site.get("marketId") if site.get("marketId") is not None else site.get("MarketID")
    if mid is not None and system_address is not None and get_project_at_location is not None:
        try:
            proj = get_project_at_location(int(system_address), int(mid))
        except (TypeError, ValueError):
            proj = None
        if isinstance(proj, dict):
            return resolve_build_id(proj)
    sid = site.get("id")
    if sid is not None and str(sid).strip():
        return str(sid).strip()
    return None


def active_project_from_system_location_json(data: Any) -> Optional[Dict]:
    """
    Interpret JSON (or string) from ``GET /api/system/{id64}/{marketId}``.

    Some API deployments return **HTTP 200** with a ProblemDetails-style body or a
    plain message such as *No active project found by systemAddress…* instead of 404.
    Those must **not** be treated as a project: there is no ``buildId``.

    Some deployments wrap the project in ``data`` / ``project`` / etc., or use
    ``BuildId``; we unwrap one level and accept common key spellings.
    """
    if data is None:
        return None
    if isinstance(data, str):
        if "no active project" in data.lower():
            return None
        s = data.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                data = json.loads(s)
            except (TypeError, ValueError):
                return None
        else:
            return None
    if not isinstance(data, dict):
        return None
    if _truthy_build_id_from_mapping(data):
        return data
    for wrap in ("data", "project", "result", "value", "payload", "body"):
        inner = data.get(wrap)
        if isinstance(inner, dict) and _truthy_build_id_from_mapping(inner):
            return inner
        if isinstance(inner, str):
            inner_s = inner.strip()
            if inner_s.startswith("{") and inner_s.endswith("}"):
                try:
                    inner_d = json.loads(inner_s)
                except (TypeError, ValueError):
                    inner_d = None
                if isinstance(inner_d, dict) and _truthy_build_id_from_mapping(inner_d):
                    return inner_d
    parts: List[str] = []
    for k in ("detail", "title", "message"):
        v = data.get(k)
        if isinstance(v, str):
            parts.append(v)
    err_blob = " ".join(parts).lower()
    if "no active project" in err_blob:
        return None
    errs = data.get("errors")
    if isinstance(errs, dict):
        try:
            err_blob = f"{err_blob} {json.dumps(errs)}".lower()
        except (TypeError, ValueError):
            pass
        if "no active project" in err_blob:
            return None
    logger.debug("GET /api/system/.../... returned no buildId; treating as no project: %s", str(data)[:400])
    return None


def completed_project_hint_from_system_location_json(data: Any) -> Optional[Dict]:
    """
    Surface 404/ProblemDetails payloads that still indicate a completed project.

    Some server deployments can return 404 while including a completion status
    payload. We expose that dict so callers can avoid creating duplicates.
    """
    if not isinstance(data, dict):
        return None
    complete_raw = data.get("complete")
    if isinstance(complete_raw, bool) and complete_raw:
        return data

    status_raw = data.get("status")
    build_status_raw = data.get("buildStatus")
    for raw in (status_raw, build_status_raw):
        if raw is None:
            continue
        s = str(raw).strip().lower()
        if s in ("complete", "completed", "finished"):
            return data
    return None


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
            response = _http_request_with_retry(
                self.session, "GET", url, timeout=10, retry_read_timeout=True
            )
            try:
                payload = response.json()
            except ValueError:
                payload = (response.text or "").strip() or None

            project = active_project_from_system_location_json(payload)
            if project is not None:
                return project

            if response.status_code == 404:
                completed_hint = completed_project_hint_from_system_location_json(payload)
                if completed_hint is not None:
                    logger.info(
                        "GET /api/system returned 404 with completion payload; exposing data to caller: %s",
                        str(completed_hint)[:400],
                    )
                    return completed_hint
                return None

            response.raise_for_status()
            return None
        except Exception as e:
            logger.error(f"Failed to get project: {e}")
            return None


    def get_project_by_build_id(self, build_id: str) -> Optional[Dict]:
        """GET /api/project/{buildId} — full project view for overlay / UI."""
        bid = (build_id or "").strip()
        if not bid:
            return None
        try:
            url = f"{self.api_base}/api/project/{urllib.parse.quote(bid, safe='')}"
            response = _http_request_with_retry(
                self.session, "GET", url, timeout=12, retry_read_timeout=True
            )
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                if resolve_build_id(payload):
                    return payload
                for wrap in ("data", "project", "result", "value"):
                    inner = payload.get(wrap)
                    if isinstance(inner, dict) and resolve_build_id(inner):
                        return inner
            logger.debug(
                "GET /api/project/%s returned no buildId: %s", bid, str(payload)[:400]
            )
            return None
        except Exception as e:
            logger.error("Failed to get project by buildId %s: %s", bid, e)
            return None

    def contribute_cargo(self, build_id: str, cmdr: str, cargo_diff: Dict[str, int]) -> bool:
        """Record commander delivery history (``ColonisationContribution``); does not alter remaining need."""
        try:
            bid = urllib.parse.quote(build_id, safe="")
            url = f"{self.api_base}/api/project/{bid}/contribute/{urllib.parse.quote(cmdr, safe='')}"
            logger.debug(f"Contribution URL: {url}")
            body = _normalize_cargo_map(cargo_diff)
            logger.debug(f"Contribution payload: {body}")
            response = _http_request_with_retry(
                self.session,
                "POST",
                url,
                json=body,
                timeout=10,
                retry_read_timeout=False,
            )
            logger.debug(f"Contribution response status: {response.status_code}")
            response.raise_for_status()
            logger.info("Contributed cargo to project %s: %s", build_id, body)
            return True
        except Exception as e:
            logger.error("Failed to contribute cargo: %s", e, exc_info=True)
            return False
    
    def patch_project_update(self, build_id: str, payload: Dict) -> Optional[Dict]:
        """Merge-style PATCH /api/project/{buildId} (depot snapshot, commodities, buildName, …).

        Returns the parsed response body (often a project view) on success, ``None`` on failure.
        """
        try:
            bid = urllib.parse.quote(build_id, safe="")
            url = f"{self.api_base}/api/project/{bid}"
            body = dict(payload)
            body.setdefault("buildId", build_id)
            if isinstance(body.get("commodities"), dict):
                body["commodities"] = _normalize_project_need_map(body["commodities"])
            logger.debug("PATCH project URL: %s", url)
            logger.debug("PATCH project payload: %s", json.dumps(body, default=str)[:8000])
            response = _http_request_with_retry(
                self.session,
                "PATCH",
                url,
                json=body,
                timeout=10,
                retry_read_timeout=True,
            )
            logger.debug("PATCH project response status: %s", response.status_code)
            logger.debug("PATCH project response body: %s", (response.text or "")[:4000])
            response.raise_for_status()
            logger.info("Patched project %s", build_id)
            if not (response.text or "").strip():
                return {}
            try:
                data = response.json()
            except ValueError:
                return {}
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error("Failed to patch project %s: %s", build_id, e, exc_info=True)
            return None
    
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
    
    def fetch_system_sites(self, name_or_num: Union[str, int]) -> Optional[List[Dict]]:
        """GET /api/v2/system/{nameOrNum}/sites; ``None`` when the request fails."""
        seg = _v2_system_path_segment(name_or_num)
        logger.debug("fetch_system_sites nameOrNum=%r segment=%s", name_or_num, seg)

        try:
            url = f"{self.api_base}/api/v2/system/{seg}/sites"
            logger.debug(f"Fetching sites from URL: {url}")
            response = _http_request_with_retry(
                self.session,
                "GET",
                url,
                timeout=10,
                retry_read_timeout=True,
            )
            logger.debug(f"Sites API response status: {response.status_code}")
            if response.status_code != 200:
                logger.debug(f"Sites API response body: {response.text}")
            response.raise_for_status()
            sites = response.json()
            if isinstance(sites, list):
                logger.debug("Successfully fetched %s site row(s)", len(sites))
                return sites
            logger.error("Sites API returned non-list JSON for nameOrNum=%r", name_or_num)
            return None
        except Exception as e:
            logger.error("Failed to get system sites: %s", e, exc_info=True)
            return None

    def get_system_sites(self, name_or_num: Union[str, int]) -> List[Dict]:
        """GET /api/v2/system/{nameOrNum}/sites — ``name_or_num`` is system name or id64."""
        sites = self.fetch_system_sites(name_or_num)
        return sites if sites is not None else []

    def update_system_sites(
        self,
        name_or_num: Union[str, int],
        update_rows: List[Dict[str, Any]],
        delete_ids: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """PUT /api/v2/system/{nameOrNum}/sites with ``SitesPut`` body and ``rcc-key`` auth."""
        if not getattr(self, "api_key", None):
            logger.debug("update_system_sites skipped: no API key")
            return None
        seg = _v2_system_path_segment(name_or_num)
        url = f"{self.api_base}/api/v2/system/{seg}/sites"
        body: Dict[str, Any] = {
            "update": update_rows,
            "delete": delete_ids or [],
        }
        try:
            logger.debug("PUT system sites URL: %s", url)
            logger.debug("PUT system sites payload: %s", json.dumps(body, default=str)[:4000])
            response = _http_request_with_retry(
                self.session,
                "PUT",
                url,
                json=body,
                headers={"rcc-key": self.api_key},
                timeout=15,
                retry_read_timeout=True,
            )
            logger.debug("PUT system sites response status: %s", response.status_code)
            logger.debug("PUT system sites response body: %s", (response.text or "")[:4000])
            response.raise_for_status()
            if not (response.text or "").strip():
                return {}
            try:
                data = response.json()
            except ValueError:
                return {}
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error("Failed to update system sites for %s: %s", name_or_num, e, exc_info=True)
            return None

    def patch_system_site(
        self,
        name_or_num: Union[str, int],
        site_id: Union[str, int],
        *,
        market_id: Optional[int] = None,
        name: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """PATCH /api/v2/system/{nameOrNum}/sites/{siteId} with partial site fields."""
        if not getattr(self, "api_key", None):
            logger.debug("patch_system_site skipped: no API key")
            return None
        body: Dict[str, Any] = {}
        if market_id is not None:
            body["marketId"] = int(market_id)
        if name is not None:
            body["name"] = str(name)
        if not body:
            logger.debug("patch_system_site skipped: empty payload for siteId=%r", site_id)
            return None

        seg = _v2_system_path_segment(name_or_num)
        site_seg = urllib.parse.quote(str(site_id), safe="")
        url = f"{self.api_base}/api/v2/system/{seg}/sites/{site_seg}"
        try:
            logger.debug("PATCH system site URL: %s", url)
            logger.debug("PATCH system site payload: %s", json.dumps(body, default=str)[:4000])
            response = _http_request_with_retry(
                self.session,
                "PATCH",
                url,
                json=body,
                headers={"rcc-key": self.api_key},
                timeout=15,
                retry_read_timeout=True,
            )
            logger.debug("PATCH system site response status: %s", response.status_code)
            logger.debug("PATCH system site response body: %s", (response.text or "")[:4000])
            response.raise_for_status()
            if not (response.text or "").strip():
                return {}
            try:
                data = response.json()
            except ValueError:
                return {}
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error("Failed to patch system site %s for %s: %s", site_id, name_or_num, e, exc_info=True)
            return None
    
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
        body = prepare_put_project_body(project_data)
        
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
            try:
                data = response.json()
            except ValueError:
                data = (response.text or "").strip()
            architect = parse_system_architect_response(data)
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
            response = _http_request_with_retry(
                self.session,
                "POST",
                url,
                json=body,
                headers=headers,
                timeout=15,
                retry_read_timeout=True,
            )
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
