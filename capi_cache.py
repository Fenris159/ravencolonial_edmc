"""
Persist EDMC-delivered CAPI snapshots for offline analysis.

Queue + background thread: ``cmdr_data`` / ``cmdr_data_legacy`` / ``capi_fleetcarrier``
run on EDMC's main Tk thread — only a fast deep-copy and ``queue.put`` happen there;
JSON encoding and disk I/O run on a worker thread (see EDMC PLUGINS.md).
"""

from __future__ import annotations

import copy
import json
import logging
import os
import queue
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_CACHE_DIR: Optional[str] = None
_MAX_SNAPSHOT_FILES = 3

_work_queue: Optional[queue.SimpleQueue] = None
_worker_thread: Optional[threading.Thread] = None
_worker_lock = threading.Lock()


def _worker_loop() -> None:
    global _work_queue
    while True:
        q = _work_queue
        if q is None:
            return
        envelope = q.get()
        if envelope is None:
            return
        try:
            _flush_envelope(envelope)
        except Exception as e:
            logger.warning("CAPI cache worker failed: %s", e, exc_info=True)


def _flush_envelope(envelope: Dict[str, Any]) -> None:
    if not _CACHE_DIR:
        return
    kind = envelope.get("meta", {}).get("kind")
    if kind not in ("cmdr_data", "cmdr_data_legacy", "fleetcarrier", "squadron"):
        return
    text = json.dumps(envelope, indent=2, ensure_ascii=False, default=str)
    ts = envelope["meta"]["snapshot_id"]
    latest_name = f"latest_{kind}.json"
    snap_name = f"snapshot_{kind}_{ts}.json"
    latest_path = os.path.join(_CACHE_DIR, latest_name)
    snap_path = os.path.join(_CACHE_DIR, snap_name)
    with open(latest_path, "w", encoding="utf-8") as f:
        f.write(text)
    with open(snap_path, "w", encoding="utf-8") as f:
        f.write(text)
    _prune_snapshots(kind)
    logger.debug("CAPI cache worker wrote %s + %s", latest_name, snap_name)


def _prune_snapshots(kind: str) -> None:
    if not _CACHE_DIR:
        return
    prefix = f"snapshot_{kind}_"
    try:
        names = [
            n
            for n in os.listdir(_CACHE_DIR)
            if n.startswith(prefix) and n.endswith(".json")
        ]
    except OSError:
        return
    if len(names) <= _MAX_SNAPSHOT_FILES:
        return
    names.sort()
    for stale in names[: -_MAX_SNAPSHOT_FILES]:
        try:
            os.remove(os.path.join(_CACHE_DIR, stale))
        except OSError:
            pass


def init(plugin_dir: str) -> None:
    """Create cache directory and start the background writer thread."""
    global _CACHE_DIR, _work_queue, _worker_thread
    d = os.path.join(plugin_dir, "capi_cache")
    try:
        os.makedirs(d, exist_ok=True)
        _CACHE_DIR = d
        logger.info("CAPI cache directory: %s", d)
    except OSError as e:
        _CACHE_DIR = None
        logger.warning("Could not create CAPI cache directory %s: %s", d, e)
        return

    with _worker_lock:
        if _worker_thread is not None and _worker_thread.is_alive():
            return
        _work_queue = queue.SimpleQueue()
        _worker_thread = threading.Thread(
            target=_worker_loop,
            daemon=True,
            name="ravencolonial-capi-cache",
        )
        _worker_thread.start()


def stop() -> None:
    """Signal the cache worker to exit and wait briefly for pending writes."""
    global _work_queue, _worker_thread
    with _worker_lock:
        q = _work_queue
        t = _worker_thread
    if q is not None:
        try:
            q.put(None)
        except Exception:  # nosec B110
            pass
    if t is not None and t.is_alive():
        t.join(timeout=5.0)
    with _worker_lock:
        _work_queue = None
        _worker_thread = None


def write(
    kind: str,
    data: Any,
    is_beta: Optional[bool] = None,
    source_host: Optional[str] = None,
    request_cmdr: Optional[str] = None,
) -> None:
    """
    Queue a snapshot for async flush. Main thread: copy payload only, then return.

    ``data`` is typically ``CAPIData`` (``UserDict``). ``cmdr_data`` is not
    deep-copied by EDMC before the plugin hook, so we ``deepcopy`` here before
    enqueueing.
    """
    if not _CACHE_DIR or _work_queue is None:
        return
    if kind not in ("cmdr_data", "cmdr_data_legacy", "fleetcarrier", "squadron"):
        logger.warning("Unknown CAPI cache kind %r — skipping", kind)
        return

    try:
        payload: Dict[str, Any] = copy.deepcopy(dict(data))
    except Exception as e:
        logger.warning("CAPI cache could not copy payload for %s: %s", kind, e)
        return

    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%dT%H%M%S") + f"{now.microsecond:06d}Z"
    envelope: Dict[str, Any] = {
        "meta": {
            "kind": kind,
            "captured_at_utc": now.isoformat(),
            "snapshot_id": ts,
            "is_beta": is_beta,
            "source_host": source_host if source_host is not None else getattr(data, "source_host", None),
            "request_cmdr": request_cmdr if request_cmdr is not None else getattr(data, "request_cmdr", None),
        },
        "payload": payload,
    }

    try:
        _work_queue.put(envelope)
    except Exception as e:
        logger.warning("CAPI cache enqueue failed (%s): %s", kind, e)
