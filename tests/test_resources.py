"""Tests for development and PyInstaller resource resolution."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import patch

from portrait_cropper.resources import resource_path, resource_root


class ResourcePathTests(unittest.TestCase):
    """Verify required assets resolve in source and bundled layouts."""

    def test_development_resource_path_finds_bundled_model(self) -> None:
        model = resource_path("assets/models/face_detection_yunet.onnx")
        self.assertTrue(model.is_file())
        self.assertGreater(model.stat().st_size, 200_000)

    def test_pyinstaller_resource_path_uses_meipass(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            expected = root / "assets" / "models" / "face_detection_yunet.onnx"
            expected.parent.mkdir(parents=True)
            expected.write_bytes(b"offline-model")
            with patch.object(sys, "_MEIPASS", str(root), create=True):
                self.assertEqual(resource_root(), root)
                self.assertEqual(resource_path("assets/models/face_detection_yunet.onnx"), expected)


if __name__ == "__main__":
    unittest.main()
