"""Tests for collision-safe output filename construction."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from portrait_cropper.file_manager import build_output_path
from portrait_cropper.settings import AppSettings


class FileManagerTests(unittest.TestCase):
    """Verify naming modes never overwrite inputs or reserved destinations."""

    def test_suffix_naming_and_collision(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            source = tmp_path / "photo.jpg"
            source.write_bytes(b"source")
            settings = AppSettings()
            first = build_output_path(source, tmp_path, settings, 1)
            self.assertEqual(first.name, "photo_cropped.jpg")
            first.write_bytes(b"existing")
            second = build_output_path(source, tmp_path, settings, 1)
            self.assertEqual(second.name, "photo_cropped_1.jpg")

    def test_original_is_never_selected_as_destination(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            source = tmp_path / "photo.png"
            source.write_bytes(b"source")
            settings = AppSettings(naming_mode="Keep original filename", overwrite_existing=True)
            destination = build_output_path(source, tmp_path, settings, 1)
            self.assertNotEqual(destination, source)

    def test_batch_reservations_prevent_same_name_collision(self) -> None:
        with TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            first_source = tmp_path / "one" / "photo.jpg"
            second_source = tmp_path / "two" / "photo.jpg"
            first_source.parent.mkdir()
            second_source.parent.mkdir()
            first_source.write_bytes(b"one")
            second_source.write_bytes(b"two")
            reserved: set[Path] = set()
            first = build_output_path(first_source, tmp_path, AppSettings(), 1, reserved)
            reserved.add(first)
            second = build_output_path(second_source, tmp_path, AppSettings(), 2, reserved)
            self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
