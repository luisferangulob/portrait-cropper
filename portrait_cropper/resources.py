"""Locate bundled application resources in development and PyInstaller builds."""

from __future__ import annotations

from pathlib import Path
import sys


def resource_root() -> Path:
    """Return the directory containing packaged project resources."""

    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root)
    return Path(__file__).resolve().parent.parent


def resource_path(relative_path: str | Path) -> Path:
    """Resolve a project-relative resource without machine-specific paths."""

    relative = Path(relative_path)
    return relative if relative.is_absolute() else resource_root() / relative
