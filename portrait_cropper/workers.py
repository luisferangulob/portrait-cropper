"""Background threads for analysis and batch saving."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from .detector import FaceDetector
from .image_processing import process_image
from .models import DetectedFace, Rect
from .settings import AppSettings


LOGGER = logging.getLogger(__name__)


class AnalysisThread(QThread):
    """Analyze images one at a time to keep memory use bounded."""

    item_analyzed = Signal(int, object, object, str)
    progress_changed = Signal(int, str)
    analysis_finished = Signal(bool)

    def __init__(self, paths: list[Path], settings: AppSettings) -> None:
        """Initialize a cancellable analysis worker for ordered source paths."""

        super().__init__()
        self.paths = paths
        self.settings = settings
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation after the current image operation finishes."""

        self._cancelled = True

    def run(self) -> None:
        """Detect faces sequentially and emit per-item progress and results."""

        try:
            detector = FaceDetector(self.settings.detection_confidence)
        except Exception as exc:
            LOGGER.exception("Could not initialize face detector")
            for index in range(len(self.paths)):
                self.item_analyzed.emit(index, None, [], str(exc))
            self.analysis_finished.emit(False)
            return

        total = len(self.paths)
        for index, path in enumerate(self.paths):
            if self._cancelled:
                self.analysis_finished.emit(True)
                return
            self.progress_changed.emit(round(index * 100 / max(1, total)), path.name)
            try:
                image_size, faces = detector.detect(path)
                self.item_analyzed.emit(index, image_size, faces, "")
            except Exception as exc:
                LOGGER.exception("Analysis failed for %s", path)
                self.item_analyzed.emit(index, None, [], str(exc))
        self.progress_changed.emit(100, "Analysis complete")
        self.analysis_finished.emit(False)


class ProcessingThread(QThread):
    """Crop and save selected images sequentially in the background."""

    item_processed = Signal(int, object, str)
    progress_changed = Signal(int, str)
    processing_finished = Signal(bool)

    def __init__(
        self,
        jobs: list[tuple[int, Path, Path, Rect]],
        settings: AppSettings,
    ) -> None:
        """Initialize a cancellable worker with prepared crop/save jobs."""

        super().__init__()
        self.jobs = jobs
        self.settings = settings
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation after the current save operation finishes."""

        self._cancelled = True

    def run(self) -> None:
        """Process jobs sequentially and emit per-item progress and results."""

        total = len(self.jobs)
        for position, (index, source, destination, crop) in enumerate(self.jobs):
            if self._cancelled:
                self.processing_finished.emit(True)
                return
            self.progress_changed.emit(round(position * 100 / max(1, total)), source.name)
            try:
                process_image(source, destination, crop, self.settings)
                self.item_processed.emit(index, destination, "")
            except Exception as exc:
                LOGGER.exception("Processing failed for %s", source)
                self.item_processed.emit(index, None, str(exc))
        self.progress_changed.emit(100, "Processing complete")
        self.processing_finished.emit(False)
