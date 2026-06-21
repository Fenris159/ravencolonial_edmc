"""Shared pytest bootstrap for checkout-path-independent package imports."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PACKAGE_NAME = "RavenColonail_EDMC"
ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT.parent

if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

if PACKAGE_NAME not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not create package spec for {PACKAGE_NAME}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
