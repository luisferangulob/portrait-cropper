"""Tests for settings validation and JSON serialization compatibility."""

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from portrait_cropper.settings import AppSettings


class SettingsTests(unittest.TestCase):
    """Verify settings bounds and stable JSON round trips."""

    def test_save_and_load_round_trip_preserves_settings(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            settings = AppSettings(
                aspect_name="Custom",
                aspect_width=5,
                aspect_height=7,
                custom_prefix="staff",
                head_extension_percent=42.0,
                allow_padding=True,
            )
            settings.save(path)
            self.assertEqual(AppSettings.load(path), settings)

    def test_load_ignores_unknown_keys_and_uses_missing_defaults(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(
                json.dumps({"output_width": 1200, "future_setting": "ignored"}),
                encoding="utf-8",
            )
            loaded = AppSettings.load(path)
            self.assertEqual(loaded.output_width, 1200)
            self.assertEqual(loaded.head_extension_percent, AppSettings().head_extension_percent)

    def test_validation_clamps_numeric_values(self) -> None:
        settings = AppSettings(
            aspect_width=0,
            aspect_height=-4,
            target_face_percent=1000,
            head_extension_percent=-1,
            headroom_percent=90,
            detection_confidence=4,
            jpeg_quality=0,
        ).validated()
        self.assertEqual((settings.aspect_width, settings.aspect_height), (1, 1))
        self.assertEqual(settings.target_face_percent, 90.0)
        self.assertEqual(settings.head_extension_percent, 0.0)
        self.assertEqual(settings.headroom_percent, 40.0)
        self.assertEqual(settings.detection_confidence, 1.0)
        self.assertEqual(settings.jpeg_quality, 1)


if __name__ == "__main__":
    unittest.main()
