"""Shared exception groups for intentional best-effort plugin fallbacks."""

from __future__ import annotations

import json
import shutil

try:
    import tkinter as tk
except ImportError:  # pragma: no cover - EDMC provides tkinter at runtime
    tk = None  # type: ignore[assignment]

try:
    import requests

    HTTP_CLIENT_ERRORS = (
        requests.RequestException,
        RuntimeError,
        TypeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
    )
except ImportError:  # pragma: no cover - local tests without requests
    HTTP_CLIENT_ERRORS = (
        RuntimeError,
        TypeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
    )

# EDMC ``config`` reads during startup/prefs when the host app or key is unavailable.
CONFIG_READ_ERRORS = (ImportError, AttributeError, TypeError, ValueError)

# Local filesystem, path, and journal/market file reads.
FILE_IO_ERRORS = (OSError, UnicodeError)

# JSON envelope / mapping coercion in journal and cache paths.
JSON_LOAD_ERRORS = (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError)

# Mapping/state copies when EDMC passes non-plain dict-like objects.
STATE_COPY_ERRORS = (TypeError, ValueError)

# Folder promotion/rollback during auto-update.
UPDATE_PATH_ERRORS = (OSError, shutil.Error, ValueError)

# Optional dependency shutdown before update install.
OPTIONAL_SHUTDOWN_ERRORS = (ImportError, AttributeError, OSError, RuntimeError, TypeError)

# Overlay refresh and other Tk-scheduled UI nudges.
if tk is not None:
    OVERLAY_UI_ERRORS = (ImportError, AttributeError, RuntimeError, TypeError, tk.TclError)
    TK_UI_ERRORS = (tk.TclError, RuntimeError)
else:
    OVERLAY_UI_ERRORS = (ImportError, AttributeError, RuntimeError, TypeError)
    TK_UI_ERRORS = (RuntimeError,)
