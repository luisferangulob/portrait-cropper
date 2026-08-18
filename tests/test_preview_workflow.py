"""Opt-in offscreen tests for preview and batch-session UI workflows."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from portrait_cropper.detector import FaceDetector  # noqa: E402
from portrait_cropper.models import DetectedFace, PhotoItem, PhotoStatus, Rect  # noqa: E402
from portrait_cropper.ui.main_window import MainWindow  # noqa: E402


@unittest.skipUnless(
    os.environ.get("PORTRAIT_CROPPER_GUI_TESTS") == "1",
    "set PORTRAIT_CROPPER_GUI_TESTS=1 in a Qt runtime with a working platform plugin",
)
class PreviewWorkflowTests(unittest.TestCase):
    """Verify model-to-preview synchronization with synthetic photographs."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.first = Path(self.temporary.name) / "first.jpg"
        self.second = Path(self.temporary.name) / "second.jpg"
        Image.new("RGB", (600, 800), (70, 100, 140)).save(self.first)
        Image.new("RGB", (800, 600), (150, 110, 75)).save(self.second)
        self.window = MainWindow()
        self.addCleanup(self.window.close)

    def analyze_row(self, row: int = 0) -> None:
        """Inject a deterministic successful detection for one row."""

        face = DetectedFace(Rect(220, 120, 150, 150), 0.95)
        self.window._analysis_item_ready(row, (600, 800), [face], "")
        self.app.processEvents()

    def test_import_immediately_displays_original_before_analysis(self) -> None:
        self.window._add_paths([self.first])
        self.app.processEvents()
        self.assertTrue(self.window.original_preview.has_image)
        self.assertNotEqual(self.window.original_preview.placeholder_text, "Select photos to begin")
        self.assertFalse(self.window.cropped_preview.has_image)
        self.assertIn("Analyze this image", self.window.cropped_preview.placeholder_text)

    def test_analysis_populates_model_and_both_previews(self) -> None:
        self.window._add_paths([self.first])
        self.analyze_row()
        photo = self.window.photos[0]
        self.assertEqual(photo.status, PhotoStatus.READY)
        self.assertGreater(len(photo.faces), 0)
        self.assertEqual(photo.selected_face_index, 0)
        self.assertIsNotNone(photo.crop_rect)
        self.assertTrue(self.window.original_preview.has_image)
        self.assertTrue(self.window.cropped_preview.has_image)

    def test_review_crops_refreshes_an_already_selected_row(self) -> None:
        self.window._add_paths([self.first])
        self.analyze_row()
        self.assertEqual(self.window.photo_list.currentRow(), 0)
        self.window.original_preview.set_content(None)
        self.window.cropped_preview.set_content(None, None)
        self.window._review_crops()
        self.app.processEvents()
        self.assertEqual(self.window.photo_list.currentRow(), 0)
        self.assertTrue(self.window.original_preview.has_image)
        self.assertTrue(self.window.cropped_preview.has_image)

    def test_sidebar_rows_keep_model_and_source_path_references(self) -> None:
        self.window._add_paths([self.first, self.second])
        for row, photo in enumerate(self.window.photos):
            self.window._refresh_list_item(row)
            linked = self.window.photo_list.item(row).data(Qt.ItemDataRole.UserRole)
            self.assertIs(linked, photo)
            self.assertEqual(linked.source_path, photo.source_path)

    def test_selecting_rows_changes_the_displayed_source(self) -> None:
        self.window._add_paths([self.first, self.second])
        self.window.photo_list.setCurrentRow(1)
        self.app.processEvents()
        self.assertTrue(self.window.original_preview.has_image)
        self.assertEqual(
            (self.window.original_preview._image.width(), self.window.original_preview._image.height()),
            (800, 600),
        )

    def test_no_face_keeps_original_visible_for_manual_review(self) -> None:
        self.window._add_paths([self.first])
        self.window._analysis_item_ready(0, (600, 800), [], "")
        self.app.processEvents()
        self.assertEqual(self.window.photos[0].status, PhotoStatus.NEEDS_REVIEW)
        self.assertTrue(self.window.original_preview.has_image)
        self.assertFalse(self.window.cropped_preview.has_image)
        self.assertIn("draw a face box", self.window.cropped_preview.placeholder_text)

    def test_manual_face_box_still_creates_a_crop(self) -> None:
        self.window._add_paths([self.first])
        self.window._analysis_item_ready(0, (600, 800), [], "")
        self.window._create_manual_face(Rect(210, 110, 140, 160))
        self.app.processEvents()
        photo = self.window.photos[0]
        self.assertEqual(photo.status, PhotoStatus.NEEDS_REVIEW)
        self.assertEqual(photo.selected_face_index, 0)
        self.assertIsNotNone(photo.crop_rect)
        self.assertTrue(self.window.cropped_preview.has_image)

    def test_multiple_face_selection_still_recalculates_crop(self) -> None:
        self.window._add_paths([self.first])
        faces = [
            DetectedFace(Rect(60, 120, 80, 80), 0.90),
            DetectedFace(Rect(280, 130, 150, 150), 0.85),
        ]
        self.window._analysis_item_ready(0, (600, 800), faces, "")
        initial_crop = self.window.photos[0].crop_rect
        self.assertEqual(self.window.photos[0].status, PhotoStatus.MULTIPLE)
        self.assertEqual(self.window.photos[0].selected_face_index, 1)

        self.window._select_face(0)
        self.app.processEvents()
        self.assertEqual(self.window.photos[0].selected_face_index, 0)
        self.assertNotEqual(self.window.photos[0].crop_rect, initial_crop)
        self.assertTrue(self.window.cropped_preview.has_image)

    def test_manual_crop_adjustment_and_reset_still_work(self) -> None:
        self.window._add_paths([self.first])
        self.analyze_row()
        photo = self.window.photos[0]
        automatic = photo.crop_rect
        self.assertIsNotNone(automatic)
        assert automatic is not None

        self.window._edit_crop(Rect(automatic.x + 12, automatic.y + 18, automatic.width, automatic.height))
        self.assertTrue(photo.manually_adjusted)
        self.assertAlmostEqual(photo.crop_rect.width, automatic.width)  # type: ignore[union-attr]
        self.assertAlmostEqual(photo.crop_rect.height, automatic.height)  # type: ignore[union-attr]

        self.window._reset_current_crop()
        self.assertFalse(photo.manually_adjusted)
        self.assertEqual(photo.crop_rect, automatic)

    def test_start_new_batch_clears_session_but_preserves_settings_and_files(self) -> None:
        self.window.face_percent.setValue(32)
        self.window.head_extension_percent.setValue(40)
        self.window.headroom_percent.setValue(7)
        self.window.naming_combo.setCurrentText("Custom prefix")
        self.window.custom_prefix.setText("kept")
        chosen_output = Path(self.temporary.name) / "chosen-output"
        self.window.output_folder = chosen_output
        self.window.output_edit.setText(str(chosen_output))

        self.window._add_paths([self.first, self.second])
        self.analyze_row(0)
        second_face = DetectedFace(Rect(300, 100, 140, 140), 0.93)
        self.window._analysis_item_ready(1, (800, 600), [second_face], "")
        first_photo = self.window.photos[0]
        assert first_photo.crop_rect is not None
        self.window.photo_list.setCurrentRow(0)
        self.window._edit_crop(
            Rect(
                first_photo.crop_rect.x,
                first_photo.crop_rect.y + 10,
                first_photo.crop_rect.width,
                first_photo.crop_rect.height,
            )
        )
        first_photo.status = PhotoStatus.APPROVED
        saved_output = Path(self.temporary.name) / "already-saved.jpg"
        saved_output.write_bytes(b"saved crop remains")
        first_photo.output_path = saved_output
        self.window.photos[1].status = PhotoStatus.SKIPPED
        self.window.progress.setValue(83)
        self.window.current_file_label.setText("second.jpg")
        settings_before = self.window._read_settings()

        self.assertTrue(self.window._batch_requires_confirmation())
        self.window._clear_batch_session()
        self.app.processEvents()

        self.assertEqual(self.window.photos, [])
        self.assertEqual(self.window.photo_list.count(), 0)
        self.assertEqual(self.window.photo_list.currentRow(), -1)
        self.assertFalse(self.window.original_preview.has_image)
        self.assertFalse(self.window.cropped_preview.has_image)
        self.assertEqual(self.window.original_preview.placeholder_text, "Select photos to begin")
        self.assertEqual(self.window.cropped_preview.placeholder_text, "Crop preview")
        self.assertEqual(self.window.progress.value(), 0)
        self.assertEqual(self.window.current_file_label.text(), "Ready")
        self.assertEqual(self.window.counts_label.text(), "No photos selected")
        self.assertIsNone(self.window.analysis_thread)
        self.assertIsNone(self.window.processing_thread)
        self.assertFalse(self.window.start_new_batch_button.isEnabled())
        self.assertEqual(self.window._read_settings(), settings_before)
        self.assertEqual(self.window.output_folder, chosen_output)
        self.assertEqual(self.window.output_edit.text(), str(chosen_output))
        self.assertTrue(saved_output.exists())
        self.assertEqual(saved_output.read_bytes(), b"saved crop remains")

        self.window._add_paths([self.second])
        self.window._analysis_item_ready(0, (800, 600), [second_face], "")
        self.app.processEvents()
        self.assertEqual(len(self.window.photos), 1)
        self.assertEqual(self.window.photos[0].status, PhotoStatus.READY)
        self.assertIsNotNone(self.window.photos[0].crop_rect)
        self.assertTrue(self.window.original_preview.has_image)
        self.assertTrue(self.window.cropped_preview.has_image)

    def test_start_new_batch_is_immediate_before_processing(self) -> None:
        self.window._add_paths([self.first, self.second])
        self.assertFalse(self.window._batch_requires_confirmation())
        with patch.object(self.window, "_confirm_start_new_batch", side_effect=AssertionError("confirmation not expected")):
            self.window._start_new_batch()
        self.assertEqual(self.window.photos, [])

    def test_start_new_batch_confirmation_can_cancel_or_continue(self) -> None:
        self.window._add_paths([self.first])
        self.analyze_row()
        self.window.photos[0].status = PhotoStatus.APPROVED

        with patch.object(self.window, "_confirm_start_new_batch", return_value=False):
            self.window._start_new_batch()
        self.assertEqual(len(self.window.photos), 1)

        with patch.object(self.window, "_confirm_start_new_batch", return_value=True):
            self.window._start_new_batch()
        self.assertEqual(self.window.photos, [])

    @unittest.skipUnless(os.environ.get("PORTRAIT_CROPPER_TEST_PORTRAIT"), "set a real portrait path for detector integration")
    def test_real_portrait_detection_populates_crop_preview(self) -> None:
        path = Path(os.environ["PORTRAIT_CROPPER_TEST_PORTRAIT"])
        image_size, faces = FaceDetector().detect(path)
        self.assertGreater(len(faces), 0)
        window = MainWindow()
        self.addCleanup(window.close)
        window._add_paths([path])
        window._analysis_item_ready(0, image_size, faces, "")
        self.app.processEvents()
        photo: PhotoItem = window.photos[0]
        self.assertIsNotNone(photo.selected_face_index)
        self.assertIsNotNone(photo.crop_rect)
        self.assertTrue(window.original_preview.has_image)
        self.assertTrue(window.cropped_preview.has_image)


if __name__ == "__main__":
    unittest.main()
