#!/usr/bin/env python3
"""
Remove local Python / setuptools build outputs and bytecode caches.

Does not touch plugin source, L10n, docs, ``make_release.py``, virtualenvs
(``.venv`` / ``venv``), or **``build/release/``** (release zips from
``make_release.py`` are always left intact).

Under ``build/``, only setuptools-style outputs are removed (e.g. ``lib/``,
``bdist.*``); ``build/release/`` is never deleted or trimmed by this script.

From repo root::

    python scripts/clean_build_artifacts.py
    python scripts/clean_build_artifacts.py --dry-run
    python scripts/clean_build_artifacts.py --include-stray-root-zips
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Top-level directories to remove entirely if present (repo root only).
# Note: ``build`` is handled separately so ``build/release/`` is preserved.
REMOVE_TOP_DIRS = (
    "dist",
    ".eggs",
    ".pytest_cache",
    "htmlcov",
    "temp_release",
)

# Never remove this directory under ``build/`` (make_release.py output).
RELEASE_SUBDIR = "release"

SKIP_DIR_NAMES = frozenset({"_compare_SrvSurvey", ".venv", "venv", "ENV", "env", ".git"})


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def should_skip_path(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return True
    return any(part in SKIP_DIR_NAMES for part in rel.parts)


def rm_tree(path: Path, dry: bool) -> bool:
    if not path.exists():
        return False
    if dry:
        print(f"would remove: {path}")
        return True
    shutil.rmtree(path)
    print(f"removed: {path}")
    return True


def clean_build_dir_preserving_releases(root: Path, dry: bool) -> int:
    """Remove setuptools outputs under ``build/`` but keep ``build/release/``."""
    build_dir = root / "build"
    if not build_dir.is_dir():
        return 0
    removed = 0
    for child in sorted(build_dir.iterdir()):
        if child.name == RELEASE_SUBDIR:
            continue
        if child.is_dir():
            if rm_tree(child, dry):
                removed += 1
        elif child.is_file():
            if _rm_file(child, dry):
                removed += 1
    return removed


def _rm_file(path: Path, dry: bool) -> bool:
    if not path.is_file():
        return False
    if dry:
        print(f"would remove: {path}")
        return True
    path.unlink()
    print(f"removed: {path}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print actions only.")
    parser.add_argument(
        "--include-stray-root-zips",
        action="store_true",
        help=(
            "Also delete RavenColonial_EDMC-v*.zip in the repo root only "
            "(does not touch build/release/)."
        ),
    )
    args = parser.parse_args()
    root = repo_root()
    dry = args.dry_run
    removed = 0

    removed += clean_build_dir_preserving_releases(root, dry)

    for name in REMOVE_TOP_DIRS:
        p = root / name
        if p.is_dir() and rm_tree(p, dry):
            removed += 1

    for p in root.iterdir():
        if p.is_dir() and p.name.endswith(".egg-info"):
            if rm_tree(p, dry):
                removed += 1

    pycaches = sorted(
        {p for p in root.rglob("__pycache__") if p.is_dir() and not should_skip_path(p, root)},
        key=lambda p: len(p.parts),
        reverse=True,
    )
    for p in pycaches:
        if rm_tree(p, dry):
            removed += 1

    for fname in (".coverage",):
        fp = root / fname
        if fp.is_file():
            if dry:
                print(f"would remove: {fp}")
            else:
                fp.unlink()
                print(f"removed: {fp}")
            removed += 1

    if args.include_stray_root_zips:
        for p in root.glob("RavenColonial_EDMC-v*.zip"):
            if p.is_file():
                if dry:
                    print(f"would remove: {p}")
                else:
                    p.unlink()
                    print(f"removed: {p}")
                removed += 1

    if removed == 0 and not dry:
        print("Nothing to clean (no matching build/cache paths found).")
    elif dry and removed == 0:
        print("Nothing would be removed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
