"""Application logging configuration."""

from __future__ import annotations

import logging
from pathlib import Path
import tempfile


def configure_logging() -> Path:
    """Write technical diagnostics to a per-user log file."""

    log_dir = Path.home() / ".portrait_cropper"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Sandboxed or managed desktops may expose a read-only home directory.
        log_dir = Path(tempfile.gettempdir()) / "portrait_cropper"
        log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "portrait_cropper.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8")],
        force=True,
    )
    return log_path
