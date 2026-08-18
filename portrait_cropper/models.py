"""Shared data models used by the UI and processing layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


@dataclass(frozen=True)
class Rect:
    """A rectangle in source-image pixel coordinates."""

    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def as_int_tuple(self) -> tuple[int, int, int, int]:
        """Return rounded ``(x, y, width, height)`` coordinates."""

        return tuple(round(value) for value in (self.x, self.y, self.width, self.height))


@dataclass(frozen=True)
class DetectedFace:
    """A face bounding box and detector confidence."""

    rect: Rect
    confidence: float = 1.0


class PhotoStatus(str, Enum):
    """Lifecycle states displayed for an imported photograph."""

    PENDING = "Pending analysis"
    READY = "Ready"
    MULTIPLE = "Multiple faces detected"
    NEEDS_REVIEW = "Needs review"
    APPROVED = "Approved"
    SKIPPED = "Skipped"
    PROCESSED = "Processed"
    ERROR = "Error"


@dataclass
class PhotoItem:
    """Lightweight state for one source image; full pixels are never retained."""

    source_path: Path
    status: PhotoStatus = PhotoStatus.PENDING
    image_size: tuple[int, int] | None = None
    faces: list[DetectedFace] = field(default_factory=list)
    selected_face_index: int | None = None
    crop_rect: Rect | None = None
    output_path: Path | None = None
    warning: str = ""
    error: str = ""
    manually_adjusted: bool = False

    @property
    def selected_face(self) -> DetectedFace | None:
        """Return the selected detected face when its index is valid."""

        if self.selected_face_index is None:
            return None
        if 0 <= self.selected_face_index < len(self.faces):
            return self.faces[self.selected_face_index]
        return None
