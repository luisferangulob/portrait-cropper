"""Automated tests for pure crop geometry, using only the standard library."""

from __future__ import annotations

import math
import unittest

from portrait_cropper.crop_math import CropCalculationError, calculate_crop, select_primary_face
from portrait_cropper.models import DetectedFace, Rect


class CropMathTests(unittest.TestCase):
    """Verify crop geometry, bounds, headroom, and face selection."""

    def assert_in_bounds(self, crop: Rect, image_size: tuple[int, int]) -> None:
        self.assertGreaterEqual(crop.x, -1e-7)
        self.assertGreaterEqual(crop.y, -1e-7)
        self.assertLessEqual(crop.right, image_size[0] + 1e-7)
        self.assertLessEqual(crop.bottom, image_size[1] + 1e-7)

    def assert_aspect(self, crop: Rect, expected: float = 0.8) -> None:
        self.assertTrue(math.isclose(crop.width / crop.height, expected, rel_tol=1e-7))

    def test_centered_face_matches_target_and_headroom(self) -> None:
        face = Rect(800, 400, 300, 300)
        crop = calculate_crop((2400, 3000), face, 0.8)
        self.assertAlmostEqual(crop.height, 1000)
        self.assertAlmostEqual(crop.width, 800)
        self.assertAlmostEqual(face.height / crop.height, 0.30)
        estimated_head_top = face.y - face.height * 0.35
        self.assertAlmostEqual(estimated_head_top - crop.y, crop.height * 0.05)
        self.assertAlmostEqual(face.y - crop.y, 155)
        self.assertAlmostEqual(crop.center_x, face.center_x)

    def test_head_extension_and_headroom_are_separate_offsets(self) -> None:
        face = Rect(900, 600, 240, 300)
        crop = calculate_crop(
            (2400, 3000),
            face,
            0.8,
            target_face_fraction=0.30,
            headroom_fraction=0.05,
            head_extension_fraction=0.25,
        )
        estimated_head_top = face.y - 0.25 * face.height
        self.assertAlmostEqual(crop.y, estimated_head_top - 0.05 * crop.height)
        self.assertAlmostEqual(face.y - crop.y, 125)
        self.assertGreater(face.y - crop.y, crop.height * 0.05)

    def test_top_boundary_shifts_crop_without_distortion(self) -> None:
        face = Rect(400, 25, 180, 180)
        crop = calculate_crop((1200, 1600), face, 0.8)
        self.assertEqual(crop.y, 0)
        self.assertAlmostEqual(crop.height, 600)
        self.assertAlmostEqual(crop.width, 480)
        self.assertAlmostEqual(face.height / crop.height, 0.30)
        self.assert_aspect(crop)
        self.assert_in_bounds(crop, (1200, 1600))

    def test_faces_near_edges_shift_crop_inside(self) -> None:
        cases = [
            (Rect(0, 500, 180, 180), "left"),
            (Rect(1820, 500, 180, 180), "right"),
            (Rect(800, 0, 180, 180), "top"),
            (Rect(800, 1820, 180, 180), "bottom"),
        ]
        for face, expected_edge in cases:
            with self.subTest(edge=expected_edge):
                crop = calculate_crop((2000, 2000), face, 0.8)
                self.assert_in_bounds(crop, (2000, 2000))
                if expected_edge == "left":
                    self.assertEqual(crop.x, 0)
                elif expected_edge == "right":
                    self.assertAlmostEqual(crop.right, 2000)
                elif expected_edge == "top":
                    self.assertEqual(crop.y, 0)
                else:
                    self.assertLessEqual(crop.bottom, 2000)

    def test_very_large_face_reduces_crop_proportionally(self) -> None:
        crop = calculate_crop((1000, 1200), Rect(150, 100, 700, 900), 0.8)
        self.assert_in_bounds(crop, (1000, 1200))
        self.assert_aspect(crop)

    def test_very_small_face_keeps_requested_proportion(self) -> None:
        face = Rect(990, 500, 20, 20)
        crop = calculate_crop((2000, 2500), face, 0.8)
        self.assertAlmostEqual(face.height / crop.height, 0.30)
        self.assert_in_bounds(crop, (2000, 2500))

    def test_landscape_portrait_and_square_sources(self) -> None:
        for image_size in ((3000, 2000), (2000, 3000), (2400, 2400)):
            with self.subTest(image_size=image_size):
                crop = calculate_crop(image_size, Rect(image_size[0] / 2 - 100, 300, 200, 200), 0.8)
                self.assert_in_bounds(crop, image_size)
                self.assert_aspect(crop)

    def test_multiple_faces_selects_largest_area(self) -> None:
        faces = [
            DetectedFace(Rect(10, 10, 50, 50)),
            DetectedFace(Rect(100, 100, 120, 100)),
            DetectedFace(Rect(300, 200, 80, 90)),
        ]
        self.assertEqual(select_primary_face(faces), 1)

    def test_no_face_returns_no_selection(self) -> None:
        self.assertIsNone(select_primary_face([]))

    def test_crop_exceeding_boundaries_is_scaled_and_constrained(self) -> None:
        crop = calculate_crop((500, 400), Rect(220, 180, 60, 60), 0.8, 0.05)
        self.assert_in_bounds(crop, (500, 400))
        self.assert_aspect(crop)

    def test_padding_keeps_ideal_crop_even_outside_image(self) -> None:
        crop = calculate_crop((500, 400), Rect(0, 0, 150, 150), 0.8, allow_padding=True)
        self.assertTrue(crop.x < 0 or crop.y < 0)
        self.assertAlmostEqual(crop.height, 500)

    def test_invalid_inputs_raise_friendly_geometry_error(self) -> None:
        with self.assertRaises(CropCalculationError):
            calculate_crop((0, 100), Rect(1, 1, 10, 10), 0.8)
        with self.assertRaises(CropCalculationError):
            calculate_crop((100, 100), Rect(1, 1, 0, 10), 0.8)
        with self.assertRaises(CropCalculationError):
            calculate_crop((100, 100), Rect(1, 1, 10, 10), 0.8, head_extension_fraction=1.1)


if __name__ == "__main__":
    unittest.main()
