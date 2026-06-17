"""
Dedicated on-disk log for RavenColonial plugin diagnostics (separate from EDMC's main log).

API and FC modules use ``propagate=False`` with their own stream handlers, so the same
``RotatingFileHandler`` is attached to those loggers explicitly.
"""

from __future__ import annotations

import importlib
import logging
import logging.handlers
import os
from typing import List, Optional, Tuple

_attached: List[Tuple[logging.Logger, logging.Handler]] = []
_issue_log_path: Optional[str] = None


def issue_log_path() -> Optional[str]:
    """Absolute path to the issue log file, or ``None`` if not initialized."""
    return _issue_log_path


def init_issue_log(plugin_dir: str, appname: str, plugin_name: str) -> Optional[str]:
    """
    Create ``<plugin_dir>/logs/RavenColonial_EDMC.log`` and attach a rotating file handler
    to this plugin's loggers. Safe to call once per process; repeats are no-ops.
    """
    global _issue_log_path
    if _attached:
        return _issue_log_path

    log_dir = os.path.join(plugin_dir, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        return None

    path = os.path.join(log_dir, "RavenColonial_EDMC.log")
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    try:
        fh: logging.Handler = logging.handlers.RotatingFileHandler(
            path,
            maxBytes=5 * 1024 * 1024,
            backupCount=4,
            encoding="utf-8",
            delay=True,
        )
    except OSError:
        return None

    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    loggers: list[logging.Logger] = []
    root = logging.getLogger(f"{appname}.{plugin_name}")
    loggers.append(root)
    for suffix in (".api", ".fc"):
        loggers.append(logging.getLogger(f"{appname}.{plugin_name}{suffix}"))

    submodules = (
        f"{plugin_name}.handlers.journal",
        f"{plugin_name}.construction_completion",
        f"{plugin_name}.capi_cache",
        f"{plugin_name}.create_project_dialog",
        f"{plugin_name}.overlay.build_project",
        f"{plugin_name}.ui.manager",
        f"{plugin_name}.ui.overlay_row",
        f"{plugin_name}.plugin_config.settings",
    )
    for mod_name in submodules:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        lg = getattr(mod, "logger", None)
        if isinstance(lg, logging.Logger) and lg not in loggers:
            loggers.append(lg)

    for lg in loggers:
        if fh in lg.handlers:
            continue
        lg.addHandler(fh)
        _attached.append((lg, fh))

    _issue_log_path = path
    root.info("RavenColonial issue log (attach this for bug reports): %s", path)
    return path


def stop_issue_log() -> None:
    """Remove and close the issue log handler (plugin unload)."""
    global _issue_log_path
    handlers = {h for _, h in _attached}
    for lg, h in list(_attached):
        try:
            lg.removeHandler(h)
        except (ValueError, TypeError):
            pass
    for h in handlers:
        try:
            h.flush()
            h.close()
        except Exception:  # nosec B110
            pass
    _attached.clear()
    _issue_log_path = None
