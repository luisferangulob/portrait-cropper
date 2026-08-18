"""Tests for Qt preview decoding and the Pillow fallback path."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image
from PySide6.QtGui import QImage

from portrait_cropper.ui.preview_widget import load_oriented_qimage


class _FailedQtReader:
    """Minimal QImageReader substitute that always reports decode failure."""

    def __init__(self, path: str) -> None:
        self.path = path

    def setAutoTransform(self, enabled: bool) -> None:  # noqa: N802
        del enabled

    def read(self) -> QImage:
        return QImage()

    def errorString(self) -> str:  # noqa: N802
        return "JPEG plugin unavailable"


class PreviewLoadingTests(unittest.TestCase):
    """Verify fallback previews own their converted pixel buffers."""

    def test_pillow_fallback_returns_owned_oriented_qimage(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "portrait.jpg"
            Image.new("RGB", (37, 53), (120, 80, 40)).save(path)
            with patch("portrait_cropper.ui.preview_widget.QImageReader", _FailedQtReader):
                image = load_oriented_qimage(path)

            self.assertFalse(image.isNull())
            self.assertEqual((image.width(), image.height()), (37, 53))
            # Access after the Pillow image and bytes buffer have gone out of scope.
            self.assertTrue(image.pixelColor(0, 0).isValid())


if __name__ == "__main__":
    unittest.main()
