#!/usr/bin/env python
from __future__ import annotations

import argparse
import re
from pathlib import Path


def strip_version(value: str) -> str:
    version = value.strip()
    if version.startswith("v"):
        version = version[1:]
    if not version:
        raise ValueError("Version cannot be empty.")
    return version


def update_file(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"Failed to update version in {path}")
    path.write_text(new_text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("version", help="Version to set (leading 'v' optional)")
    args = parser.parse_args()

    version = strip_version(args.version)

    pyproject = Path("pyproject.toml")
    update_file(pyproject, r'^version\s*=\s*"[^"]+"', f'version = "{version}"')

    init_path = Path("src/trailgen/__init__.py")
    update_file(init_path, r'^__version__\s*=\s*"[^"]+"', f'__version__ = "{version}"')

    print(f"Bumped version to {version}")


if __name__ == "__main__":
    main()
