#!/usr/bin/env python3
"""
Cross-platform Release Package Script for RavenColonial_EDMC
Creates a distributable .zip file with correct versioning

ZIP Structure:
    RavenColonial_EDMC-vX.Y.Z.zip
    └── RavenColonial_EDMC/
        ├── load.py
        ├── api/
        ├── plugin_config/
        └── ... (all plugin files)

This subdirectory structure is the STANDARD format and should be maintained
for all future releases. The auto-update code is designed to handle this structure.

All root-level *.py files except make_release.py are packed automatically
so runtime modules (e.g. i18n) cannot be omitted by mistake.

The docs/ directory (manual install, auto-update notes, API reference, etc.)
is bundled so the zip matches the repository layout.

Output: ``build/release/RavenColonial_EDMC-v{version}.zip`` under the repository
root (paths are resolved from this script's location, not the process cwd).
"""

import os
import re
import zipfile
from pathlib import Path

# Repository root (directory containing this script).
ROOT = Path(__file__).resolve().parent
# Release artifacts always land here, regardless of cwd when invoking this script.
RELEASE_DIR = ROOT / "build" / "release"


def get_version() -> str:
    """Extract version from load.py."""
    load_py = ROOT / "load.py"
    if not load_py.is_file():
        raise FileNotFoundError(f"load.py not found at {load_py}")

    content = load_py.read_text(encoding="utf-8")
    match = re.search(r'plugin_version\s*=\s*"([^"]+)"', content)
    if not match:
        raise ValueError("Could not find plugin_version in load.py")

    return match.group(1)


def main() -> None:
    print("=== RavenColonial_EDMC Release Packager ===\n")
    print(f"Repository root: {ROOT}")
    print(f"Release output dir: {RELEASE_DIR}\n")

    version = get_version()
    print(f"Found version: {version}")

    plugin_folder_name = "RavenColonial_EDMC"
    zip_filename = f"{plugin_folder_name}-v{version}.zip"
    zip_path = RELEASE_DIR / zip_filename

    other_root_files = [
        "LICENSE",
        "README.md",
        "pyproject.toml",
        "requirements.txt",
    ]
    root_plugin_py = sorted(
        p.name
        for p in ROOT.iterdir()
        if p.is_file() and p.suffix == ".py" and p.name != "make_release.py"
    )
    files_to_include = [f for f in other_root_files if (ROOT / f).is_file()] + root_plugin_py

    dirs_to_include = [
        "api",
        "docs",
        "handlers",
        "L10n",
        "models",
        "overlay",
        "ui",
        "plugin_config",
    ]

    print(f"\nPackage details:")
    print(f"  Plugin folder: {plugin_folder_name}")
    print(f"  Version: {version}")
    print(f"  Output file: {zip_path}\n")

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)

    if zip_path.is_file():
        print(f"WARNING: {zip_path.name} already exists - overwriting")
        zip_path.unlink()

    print("Creating zip archive...\n")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        print("Adding files:")
        for file in files_to_include:
            src = ROOT / file
            if src.is_file():
                arcname = f"{plugin_folder_name}/{file}"
                zipf.write(src, arcname)
                print(f"  + {file}")
            else:
                print(f"  ! {file} not found (skipping)")

        print("\nAdding directories:")
        for dir_name in dirs_to_include:
            dir_path = ROOT / dir_name
            if dir_path.is_dir():
                file_count = 0
                for walk_root, dirs, files in os.walk(dir_path):
                    if "__pycache__" in dirs:
                        dirs.remove("__pycache__")

                    for file in files:
                        if file.endswith(".pyc"):
                            continue

                        file_path = Path(walk_root) / file
                        rel = file_path.relative_to(ROOT)
                        arcname = f"{plugin_folder_name}/{rel.as_posix()}"
                        zipf.write(file_path, arcname)
                        file_count += 1

                print(f"  + {dir_name} ({file_count} files)")
            else:
                print(f"  ! {dir_name} not found (skipping)")

    zip_size = zip_path.stat().st_size
    zip_size_kb = round(zip_size / 1024, 2)

    print(f"\nSUCCESS: Release package created!")
    print(f"  File: {zip_path}")
    print(f"  Size: {zip_size_kb} KB")
    print(f"\nNext steps:")
    print(f"  1. Test the plugin by extracting to EDMC plugins folder")
    print(f"  2. Create a GitHub release with tag v{version}")
    print(f"  3. Upload {zip_path.name} from build/release/ to the release")


if __name__ == "__main__":
    main()
