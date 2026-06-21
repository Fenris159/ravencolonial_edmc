"""Canvas variant that tolerates EDMC theme updates."""

from __future__ import annotations

import tkinter as tk
from typing import Any


class ThemeSafeCanvas(tk.Canvas):
    """Drop unsupported options applied by EDMC's theme walker."""

    def _supported_options(self) -> set[str]:
        return set(super().keys())

    def _without_unsupported_options(self, cnf: Any = None, **kw: Any) -> tuple[Any, dict[str, Any]]:
        supported = self._supported_options()
        if isinstance(cnf, dict):
            cnf = {k: v for k, v in cnf.items() if k in supported}
        elif isinstance(cnf, str) and cnf not in supported:
            cnf = None
        kw = {k: v for k, v in kw.items() if k in supported}
        return cnf, kw

    def configure(self, cnf: Any = None, **kw: Any) -> Any:
        cnf, kw = self._without_unsupported_options(cnf, **kw)
        if cnf is None and not kw:
            return super().configure()
        return super().configure(cnf, **kw)

    config = configure
