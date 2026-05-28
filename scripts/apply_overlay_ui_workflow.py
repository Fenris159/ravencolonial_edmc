#!/usr/bin/env python3
"""One-shot patch: overlay row on main tab + build project picker workflow."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch_api_client(text: str) -> str:
    if "def get_project_by_build_id" in text:
        return text
    insert = '''
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


'''
    anchor = "def active_project_from_system_location_json"
    if anchor not in text:
        raise SystemExit("api/client anchor missing for resolve_build_id_from_site")
    text = text.replace(anchor, insert + anchor, 1)

    if "def get_project_by_build_id" not in text:
        block = '''
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

'''
        text = text.replace(
            "    def contribute_cargo(self, build_id: str, cmdr: str, cargo_diff: Dict[str, int]) -> bool:",
            block + "    def contribute_cargo(self, build_id: str, cmdr: str, cargo_diff: Dict[str, int]) -> bool:",
            1,
        )
    return text


def patch_load(text: str) -> str:
    if "overlay_build_site_rows" in text:
        pass
    else:
        text = text.replace(
            "        self.selected_plan_site_obj: Optional[Dict[str, Any]] = None\n"
            "        # Piggyback CAPI refresh",
            "        self.selected_plan_site_obj: Optional[Dict[str, Any]] = None\n"
            "        self.overlay_build_site_rows: List[Dict[str, Any]] = []\n"
            "        self.selected_overlay_build_id: Optional[str] = None\n"
            "        self.overlay_ui_enabled: bool = False\n"
            "        self.overlay_project_fetch_inflight: bool = False\n"
            "        # Piggyback CAPI refresh",
            1,
        )

    old = '''    def refresh_plan_sites_ui(self) -> None:
        """Reconcile plan-site combobox with current system vs cached fetch (main thread)."""
        if getattr(self, "ui_manager", None):
            self.ui_manager.refresh_plan_site_row_state()
'''
    new = '''    def refresh_plan_sites_ui(self) -> None:
        """Reconcile plan-site and overlay build comboboxes (main thread)."""
        if getattr(self, "ui_manager", None):
            self.ui_manager.refresh_plan_site_row_state()
            self.ui_manager.refresh_overlay_build_row_state()

    def get_project_by_build_id(self, build_id: str) -> Optional[Dict]:
        """GET /api/project/{buildId} for overlay display."""
        return self.api_client.get_project_by_build_id(build_id)
'''
    if old in text:
        text = text.replace(old, new, 1)

    # Remove settings-page overlay controls
    import re

    text = re.sub(
        r"\n    try:\n        overlay_enabled = config\.get_bool\('ravencolonial_overlay_enabled'.*?"
        r"\.grid\(row=11, column=1, sticky=tk\.W, padx=10, pady=\(0, 10\)\)\n",
        "\n",
        text,
        count=1,
        flags=re.DOTALL,
    )
    text = text.replace(
        "    config.set('ravencolonial_overlay_enabled', frame.overlay_enabled_var.get())\n",
        "",
    )
    # Fix prefs grid rows if still at 12+
    text = text.replace(".grid(row=12, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 5))", ".grid(row=10, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(10, 5))", 1)
    text = text.replace("check_updates_check.grid(row=13,", "check_updates_check.grid(row=11,", 1)
    text = text.replace("autoupdate_check.grid(row=14,", "autoupdate_check.grid(row=12,", 1)
    text = text.replace("prerelease_check.grid(row=15,", "prerelease_check.grid(row=13,", 1)
    text = text.replace("update_help.grid(row=16,", "update_help.grid(row=14,", 1)
    text = text.replace("frame.version_label.grid(row=17,", "frame.version_label.grid(row=15,", 1)
    text = text.replace("github_link.grid(row=18,", "github_link.grid(row=16,", 1)
    text = text.replace("save_button.grid(row=19,", "save_button.grid(row=17,", 1)
    return text


def patch_overlay_build_project(text: str) -> str:
    if "overlay_ui_enabled" in text:
        return text
    return text.replace(
        '''    def enabled(self) -> bool:
        try:
            from config import config

            return bool(config.get_bool("ravencolonial_overlay_enabled", default=True))
        except Exception:
            return True
''',
        '''    def enabled(self) -> bool:
        plugin = self._plugin
        if not getattr(plugin, "overlay_ui_enabled", False):
            return False
        return bool(getattr(plugin, "selected_overlay_build_id", None))
''',
    ).replace(
        '''    def _resolve_tracked_project(self) -> Optional[Dict[str, Any]]:
        plugin = self._plugin
        cached = getattr(plugin, "overlay_project_cache", None)
        if isinstance(cached, dict) and resolve_build_id(cached):
            return cached
        if (
            plugin.is_docked
            and plugin.is_construction_ship
            and plugin.current_system_address is not None
            and plugin.current_market_id is not None
        ):
            project = plugin.check_existing_project(
                int(plugin.current_system_address), int(plugin.current_market_id)
            )
            if isinstance(project, dict) and resolve_build_id(project):
                plugin.overlay_project_cache = project
                return project
        return None
''',
        '''    def _resolve_tracked_project(self) -> Optional[Dict[str, Any]]:
        plugin = self._plugin
        if not self.enabled():
            return None
        cached = getattr(plugin, "overlay_project_cache", None)
        sel = getattr(plugin, "selected_overlay_build_id", None)
        if isinstance(cached, dict) and sel and resolve_build_id(cached) == str(sel).strip():
            return cached
        return None
''',
    ).replace(
        '''        if not depot_remaining:
            depot_remaining = dict(getattr(plugin, "last_depot_remaining_need", None) or {})

        needs = resolve_project_needs(project, depot_remaining=depot_remaining)
''',
        '''        if not depot_remaining and project and self._at_selected_project_depot(plugin, project):
            depot_remaining = dict(getattr(plugin, "last_depot_remaining_need", None) or {})

        needs = resolve_project_needs(project, depot_remaining=depot_remaining)
''',
    ) + '''

    @staticmethod
    def _at_selected_project_depot(plugin: Any, project: Dict[str, Any]) -> bool:
        """Use live journal depot only when docked at the selected build's market."""
        if not plugin.is_docked or plugin.current_market_id is None:
            return False
        proj_mid = project.get("marketId") if project.get("marketId") is not None else project.get("MarketID")
        if proj_mid is None:
            return False
        try:
            return int(plugin.current_market_id) == int(proj_mid)
        except (TypeError, ValueError):
            return False
'''


def write_ui_manager_overlay_section() -> str:
    return r'''
# --- overlay build row (injected by apply_overlay_ui_workflow.py) ---
OVERLAY_BUILD_PLACEHOLDER_KEY = "__OVERLAY_PLACEHOLDER__"


def _build_status_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        s
        for s in rows
        if isinstance(s, dict) and str(s.get("status", "")).lower() == "build"
    ]
'''


def main() -> None:
    api_path = ROOT / "api" / "client.py"
    api_path.write_text(patch_api_client(api_path.read_text(encoding="utf-8")), encoding="utf-8")

    load_path = ROOT / "load.py"
    load_path.write_text(patch_load(load_path.read_text(encoding="utf-8")), encoding="utf-8")

    ov_path = ROOT / "overlay" / "build_project.py"
    content = patch_overlay_build_project(ov_path.read_text(encoding="utf-8"))
    if "_at_selected_project_depot" not in content:
        content = content.rstrip() + '''

    @staticmethod
    def _at_selected_project_depot(plugin: Any, project: Dict[str, Any]) -> bool:
        if not plugin.is_docked or plugin.current_market_id is None:
            return False
        proj_mid = project.get("marketId") if project.get("marketId") is not None else project.get("MarketID")
        if proj_mid is None:
            return False
        try:
            return int(plugin.current_market_id) == int(proj_mid)
        except (TypeError, ValueError):
            return False
'''
    ov_path.write_text(content, encoding="utf-8")
    print("Patched api/client.py, load.py, overlay/build_project.py — edit ui/manager.py manually next")


if __name__ == "__main__":
    main()
