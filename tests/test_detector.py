"""Unit and opt-in integration tests for local face detection."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image, ImageOps

from portrait_cropper.crop_math import select_primary_face
from portrait_cropper.detector import (
    DETECTION_MAX_DIMENSION,
    FaceDetector,
    intersection_over_union,
    mirrored_rect,
    suppress_duplicate_faces,
    yunet_rows_to_faces,
)
from portrait_cropper.models import DetectedFace, Rect


class DetectorPostProcessingTests(unittest.TestCase):
    """Verify detector coordinate conversion and result post-processing."""

    def test_duplicate_overlapping_detections_are_reduced_to_one(self) -> None:
        faces = [
            DetectedFace(Rect(100, 100, 120, 120), 0.91),
            DetectedFace(Rect(108, 106, 112, 114), 0.96),
            DetectedFace(Rect(102, 110, 118, 116), 0.88),
        ]
        filtered = suppress_duplicate_faces(faces)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].rect, faces[0].rect)

    def test_separate_nearby_faces_are_preserved(self) -> None:
        first = DetectedFace(Rect(20, 30, 100, 100), 0.9)
        second = DetectedFace(Rect(115, 35, 100, 100), 0.9)
        self.assertLess(intersection_over_union(first.rect, second.rect), 0.40)
        self.assertEqual(len(suppress_duplicate_faces([first, second])), 2)

    def test_yunet_rows_convert_confidence_and_source_scaling(self) -> None:
        rows = np.asarray(
            [
                [10, 20, 30, 40, *([0] * 10), 0.91],
                [50, 60, 20, 25, *([0] * 10), 0.40],
            ],
            dtype=np.float32,
        )
        faces = yunet_rows_to_faces(rows, scale_x=2.0, scale_y=3.0, confidence_threshold=0.75)
        self.assertEqual(len(faces), 1)
        self.assertEqual(faces[0].rect, Rect(20, 60, 60, 120))
        self.assertAlmostEqual(faces[0].confidence, 0.91, places=5)

    def test_mirrored_profile_coordinates_map_back_to_source(self) -> None:
        self.assertEqual(mirrored_rect(Rect(15, 20, 30, 40), 200), Rect(155, 20, 30, 40))

    def test_detection_copy_bounds_large_high_resolution_input(self) -> None:
        image = Image.new("RGB", (6000, 4000), "gray")
        bgr, gray, scale_x, scale_y = FaceDetector._detection_copy(image)
        self.assertEqual(max(bgr.shape[:2]), DETECTION_MAX_DIMENSION)
        self.assertEqual(gray.shape, bgr.shape[:2])
        self.assertAlmostEqual(scale_x, 6000 / 960)
        self.assertAlmostEqual(scale_y, 4000 / 640)

    def test_largest_face_selection_is_unchanged(self) -> None:
        faces = [
            DetectedFace(Rect(0, 0, 30, 30), 0.99),
            DetectedFace(Rect(100, 100, 90, 80), 0.80),
        ]
        self.assertEqual(select_primary_face(faces), 1)


class DetectorFallbackTests(unittest.TestCase):
    """Verify YuNet-to-Haar fallback ordering and terminal behavior."""

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.image_path = Path(self.temporary.name) / "test.jpg"
        Image.new("RGB", (320, 480), "white").save(self.image_path)
        self.detector = FaceDetector(model_path=Path(self.temporary.name) / "missing.onnx")
        self.face = DetectedFace(Rect(80, 70, 100, 120), 0.85)

    def test_yunet_result_avoids_unnecessary_fallbacks(self) -> None:
        with (
            patch.object(self.detector, "_run_yunet", return_value=[self.face]),
            patch.object(self.detector, "_run_profile_fallback") as profile,
            patch.object(self.detector, "_run_frontal_fallback") as frontal,
        ):
            _, faces = self.detector.detect(self.image_path)
        self.assertEqual(faces, [self.face])
        profile.assert_not_called()
        frontal.assert_not_called()

    def test_yunet_failure_falls_back_to_profile_cleanly(self) -> None:
        with (
            patch.object(self.detector, "_run_yunet", side_effect=cv2.error("inference failed")),
            patch.object(self.detector, "_run_profile_fallback", return_value=[self.face]),
            patch.object(self.detector, "_run_frontal_fallback") as frontal,
        ):
            _, faces = self.detector.detect(self.image_path)
        self.assertEqual(faces, [self.face])
        frontal.assert_not_called()

    def test_empty_yunet_and_profile_use_frontal_fallback(self) -> None:
        with (
            patch.object(self.detector, "_run_yunet", return_value=[]),
            patch.object(self.detector, "_run_profile_fallback", return_value=[]),
            patch.object(self.detector, "_run_frontal_fallback", return_value=[self.face]),
        ):
            _, faces = self.detector.detect(self.image_path)
        self.assertEqual(faces, [self.face])

    def test_no_detector_result_returns_empty_for_manual_review(self) -> None:
        with (
            patch.object(self.detector, "_run_yunet", return_value=[]),
            patch.object(self.detector, "_run_profile_fallback", return_value=[]),
            patch.object(self.detector, "_run_frontal_fallback", return_value=[]),
        ):
            image_size, faces = self.detector.detect(self.image_path)
        self.assertEqual(image_size, (320, 480))
        self.assertEqual(faces, [])


@unittest.skipUnless(
    os.environ.get("PORTRAIT_CROPPER_ANGLED_TEST"),
    "set PORTRAIT_CROPPER_ANGLED_TEST to a real turned portrait",
)
class RealAngledPortraitTests(unittest.TestCase):
    """Exercise YuNet against an operator-supplied turned portrait."""

    def test_yunet_detects_turned_portrait_in_both_directions(self) -> None:
        source = Path(os.environ["PORTRAIT_CROPPER_ANGLED_TEST"])
        detector = FaceDetector()
        _, faces = detector.detect(source)
        self.assertEqual(len(faces), 1)
        self.assertGreaterEqual(faces[0].confidence, detector.confidence_threshold)

        with TemporaryDirectory() as directory:
            mirrored_path = Path(directory) / "mirrored.jpg"
            with Image.open(source) as raw:
                ImageOps.mirror(ImageOps.exif_transpose(raw).convert("RGB")).save(mirrored_path)
            _, mirrored_faces = detector.detect(mirrored_path)
        self.assertEqual(len(mirrored_faces), 1)
        self.assertGreaterEqual(mirrored_faces[0].confidence, detector.confidence_threshold)


if __name__ == "__main__":
    unittest.main()
