"""Application settings and JSON configuration support."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ASPECT_PRESETS: dict[str, tuple[int, int]] = {
    "4:5 portrait": (4, 5),
    "1:1 square": (1, 1),
    "3:4 portrait": (3, 4),
    "2:3 portrait": (2, 3),
}


@dataclass
class AppSettings:
    """All editable processing settings with beginner-friendly defaults."""

    aspect_name: str = "4:5 portrait"
    aspect_width: int = 4
    aspect_height: int = 5
    output_width: int = 1600
    output_height: int = 2000
    naming_mode: str = "Add _cropped suffix"
    custom_prefix: str = "portrait"
    preserve_metadata: bool = True
    auto_process_all: bool = True
    target_face_percent: float = 30.0
    head_extension_percent: float = 35.0
    headroom_percent: float = 5.0
    detection_confidence: float = 0.75
    jpeg_quality: int = 95
    allow_padding: bool = False
    overwrite_existing: bool = False
    filename_suffix: str = "_cropped"
    maximum_output_width: int = 4000
    maximum_output_height: int = 5000
    preserve_orientation: bool = True
    preserve_exif: bool = True

    @property
    def aspect_ratio(self) -> float:
        return self.aspect_width / self.aspect_height

    @property
    def face_fraction(self) -> float:
        return self.target_face_percent / 100.0

    @property
    def headroom_fraction(self) -> float:
        return self.headroom_percent / 100.0

    @property
    def head_extension_fraction(self) -> float:
        return self.head_extension_percent / 100.0

    def validated(self) -> "AppSettings":
        """Clamp numeric fields to supported ranges and return this instance."""

        self.aspect_width = max(1, int(self.aspect_width))
        self.aspect_height = max(1, int(self.aspect_height))
        self.output_width = max(1, min(int(self.output_width), int(self.maximum_output_width)))
        self.output_height = max(1, min(int(self.output_height), int(self.maximum_output_height)))
        self.target_face_percent = min(90.0, max(5.0, float(self.target_face_percent)))
        self.head_extension_percent = min(100.0, max(0.0, float(self.head_extension_percent)))
        self.headroom_percent = min(40.0, max(0.0, float(self.headroom_percent)))
        self.detection_confidence = min(1.0, max(0.0, float(self.detection_confidence)))
        self.jpeg_quality = min(100, max(1, int(self.jpeg_quality)))
        return self

    def save(self, path: Path) -> None:
        """Serialize all settings to a human-readable JSON file."""

        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "AppSettings":
        """Load known settings from JSON, ignoring unknown compatibility keys.

        Missing keys retain dataclass defaults. JSON and file-system errors
        propagate to the caller.
        """

        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in data.items() if key in allowed}).validated()
