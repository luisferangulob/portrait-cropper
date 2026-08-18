"""Application bootstrap and command-line configuration loading."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .logging_setup import configure_logging
from .resources import resource_path
from .settings import AppSettings
from .ui.main_window import MainWindow


def parse_args(arguments: list[str]) -> argparse.Namespace:
    """Parse command-line options, including an optional JSON settings path."""

    parser = argparse.ArgumentParser(description="Face-guided batch portrait cropper")
    parser.add_argument("--config", type=Path, help="Optional JSON settings file")
    return parser.parse_args(arguments)


def main() -> int:
    """Configure and run the desktop application event loop.

    Returns:
        The Qt application exit code.
    """

    log_path = configure_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Portrait Cropper")
    app.setApplicationVersion("1.0.1")
    app.setOrganizationName("Portrait Cropper")
    icon_path = resource_path("assets/app_icon.svg")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    settings = AppSettings()
    args = parse_args(sys.argv[1:])
    if args.config:
        try:
            settings = AppSettings.load(args.config)
        except Exception:
            logging.exception("Could not load configuration: %s", args.config)
            QMessageBox.warning(
                None,
                "Configuration not loaded",
                f"The settings file could not be read. Defaults will be used.\n\nTechnical details are in {log_path}",
            )
    window = MainWindow(settings)
    window.show()
    return app.exec()
