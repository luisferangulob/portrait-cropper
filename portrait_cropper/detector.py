"""Offline YuNet face detection with profile and frontal Haar fallbacks."""

from __future__ import annotations

import math
import logging
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

from .models import DetectedFace, Rect
from .resources import resource_path


LOGGER = logging.getLogger(__name__)

YUNET_MODEL_RESOURCE = Path("assets/models/face_detection_yunet.onnx")
DETECTION_MAX_DIMENSION = 960
YUNET_NMS_THRESHOLD = 0.30
YUNET_TOP_K = 5000


def intersection_over_union(first: Rect, second: Rect) -> float:
    """Return overlap divided by union for two rectangles."""

    intersection_width = max(0.0, min(first.right, second.right) - max(first.x, second.x))
    intersection_height = max(0.0, min(first.bottom, second.bottom) - max(first.y, second.y))
    intersection = intersection_width * intersection_height
    union = first.area + second.area - intersection
    return intersection / union if union > 0 else 0.0


def suppress_duplicate_faces(faces: list[DetectedFace], iou_threshold: float = 0.40) -> list[DetectedFace]:
    """Remove strongly overlapping cascade results while preserving real neighbors.

    Larger boxes win because they give the crop calculation a stable reference.
    A 0.40 threshold collapses near-identical cascade detections without combining
    adjacent people whose face boxes merely touch.
    """

    kept: list[DetectedFace] = []
    for candidate in sorted(faces, key=lambda face: face.rect.area, reverse=True):
        if all(intersection_over_union(candidate.rect, existing.rect) <= iou_threshold for existing in kept):
            kept.append(candidate)
    return kept


def mirrored_rect(rect: Rect, image_width: float) -> Rect:
    """Map a rectangle from a horizontally flipped image back to the source."""

    return Rect(image_width - rect.right, rect.y, rect.width, rect.height)


def yunet_rows_to_faces(
    rows: np.ndarray | None,
    scale_x: float,
    scale_y: float,
    confidence_threshold: float,
) -> list[DetectedFace]:
    """Convert YuNet's ``x,y,w,h,...,score`` rows to shared face models."""

    if rows is None:
        return []
    faces: list[DetectedFace] = []
    for row in np.asarray(rows):
        if row.size < 5:
            continue
        confidence = float(row[-1])
        if confidence < confidence_threshold:
            continue
        x, y, width, height = (float(value) for value in row[:4])
        if width <= 0 or height <= 0:
            continue
        faces.append(
            DetectedFace(
                Rect(x * scale_x, y * scale_y, width * scale_x, height * scale_y),
                confidence,
            )
        )
    return suppress_duplicate_faces(faces)


class FaceDetector:
    """Detect faces locally, preferring YuNet for pose robustness."""

    def __init__(self, confidence_threshold: float = 0.75, model_path: Path | None = None) -> None:
        """Initialize YuNet and local Haar cascade fallbacks.

        Args:
            confidence_threshold: Minimum YuNet confidence in the 0..1 range.
            model_path: Optional override for the bundled YuNet model.

        Raises:
            RuntimeError: If no supported local detector can be initialized.
        """

        self.confidence_threshold = min(1.0, max(0.0, float(confidence_threshold)))
        cascade_root = Path(cv2.data.haarcascades)
        self._profile_cascade = cv2.CascadeClassifier(str(cascade_root / "haarcascade_profileface.xml"))
        self._frontal_cascade = cv2.CascadeClassifier(str(cascade_root / "haarcascade_frontalface_default.xml"))
        self.model_path = model_path if model_path is not None else resource_path(YUNET_MODEL_RESOURCE)
        self._yunet: object | None = None

        if self.model_path.is_file() and hasattr(cv2, "FaceDetectorYN"):
            try:
                self._yunet = cv2.FaceDetectorYN.create(
                    str(self.model_path),
                    "",
                    (320, 320),
                    self.confidence_threshold,
                    YUNET_NMS_THRESHOLD,
                    YUNET_TOP_K,
                )
                LOGGER.info("YuNet initialized: model=%s threshold=%.2f", self.model_path, self.confidence_threshold)
            except Exception:
                LOGGER.exception("YuNet initialization failed; Haar fallbacks remain available: %s", self.model_path)
        else:
            LOGGER.warning("YuNet model or API is unavailable; using Haar fallbacks: %s", self.model_path)

        if self._yunet is None and self._profile_cascade.empty() and self._frontal_cascade.empty():
            raise RuntimeError("No local face detector could be initialized.")

    @staticmethod
    def _confidence(level_weight: float) -> float:
        """Map OpenCV cascade weights to a stable, editable 0..1 score."""

        return 1.0 / (1.0 + math.exp(-0.65 * (float(level_weight) - 1.0)))

    @staticmethod
    def _detection_copy(image: Image.Image) -> tuple[np.ndarray, np.ndarray, float, float]:
        """Build bounded BGR/grayscale inputs and exact source-coordinate scales."""

        resize_scale = min(1.0, DETECTION_MAX_DIMENSION / max(image.size))
        if resize_scale < 1.0:
            scan_size = (
                max(1, round(image.width * resize_scale)),
                max(1, round(image.height * resize_scale)),
            )
            scan = image.resize(scan_size, Image.Resampling.LANCZOS)
        else:
            scan = image
        rgb = np.asarray(scan)
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        gray = cv2.equalizeHist(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY))
        return bgr, gray, image.width / scan.width, image.height / scan.height

    def _run_yunet(self, bgr: np.ndarray, scale_x: float, scale_y: float) -> list[DetectedFace]:
        """Run YuNet on a BGR scan image and restore source coordinates."""

        if self._yunet is None:
            return []
        height, width = bgr.shape[:2]
        self._yunet.setInputSize((width, height))  # type: ignore[attr-defined]
        _, rows = self._yunet.detect(bgr)  # type: ignore[attr-defined]
        return yunet_rows_to_faces(rows, scale_x, scale_y, self.confidence_threshold)

    def _cascade_faces(
        self,
        cascade: cv2.CascadeClassifier,
        gray: np.ndarray,
        scale_x: float,
        scale_y: float,
        mirrored: bool = False,
    ) -> list[DetectedFace]:
        """Run one Haar cascade and convert detections to source coordinates.

        Args:
            cascade: Configured OpenCV cascade classifier.
            gray: Equalized grayscale detection image.
            scale_x: Horizontal scale from detection to source pixels.
            scale_y: Vertical scale from detection to source pixels.
            mirrored: Whether results came from a horizontally flipped image.

        Returns:
            Detected faces with cascade weights mapped to confidence scores.
        """

        if cascade.empty():
            return []
        rectangles, _, weights = cascade.detectMultiScale3(
            gray,
            scaleFactor=1.08,
            minNeighbors=4,
            flags=cv2.CASCADE_SCALE_IMAGE,
            minSize=(24, 24),
            outputRejectLevels=True,
        )
        scan_width = float(gray.shape[1])
        faces: list[DetectedFace] = []
        for (x, y, width, height), weight in zip(rectangles, weights):
            scan_rect = Rect(float(x), float(y), float(width), float(height))
            if mirrored:
                # Right-facing profiles are found by scanning a flipped copy;
                # restore the box before scaling it to source-image pixels.
                scan_rect = mirrored_rect(scan_rect, scan_width)
            faces.append(
                DetectedFace(
                    Rect(
                        scan_rect.x * scale_x,
                        scan_rect.y * scale_y,
                        scan_rect.width * scale_x,
                        scan_rect.height * scale_y,
                    ),
                    self._confidence(float(weight)),
                )
            )
        return faces

    def _run_profile_fallback(self, gray: np.ndarray, scale_x: float, scale_y: float) -> list[DetectedFace]:
        """Detect left- and right-facing profiles and remove duplicates."""

        original = self._cascade_faces(self._profile_cascade, gray, scale_x, scale_y)
        flipped = self._cascade_faces(
            self._profile_cascade,
            cv2.flip(gray, 1),
            scale_x,
            scale_y,
            mirrored=True,
        )
        return suppress_duplicate_faces(original + flipped)

    def _run_frontal_fallback(self, gray: np.ndarray, scale_x: float, scale_y: float) -> list[DetectedFace]:
        """Run the frontal Haar cascade and remove duplicate detections."""

        return suppress_duplicate_faces(self._cascade_faces(self._frontal_cascade, gray, scale_x, scale_y))

    def detect(self, path: Path) -> tuple[tuple[int, int], list[DetectedFace]]:
        """Load one oriented image and return its size and accepted faces.

        YuNet is attempted first, followed by profile and frontal Haar
        fallbacks. Decode and detector errors propagate when no local fallback
        can complete the operation.
        """

        with Image.open(path) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
            image_size = image.size
            bgr, gray, scale_x, scale_y = self._detection_copy(image)

        try:
            faces = self._run_yunet(bgr, scale_x, scale_y)
        except Exception:
            LOGGER.exception("YuNet inference failed for %s; trying profile Haar fallback", path)
            faces = []
        if faces:
            LOGGER.info("Detected %s face(s) with YuNet: %s", len(faces), path)
            return image_size, faces

        faces = self._run_profile_fallback(gray, scale_x, scale_y)
        if faces:
            LOGGER.info("Detected %s face(s) with profile Haar fallback: %s", len(faces), path)
            return image_size, faces

        faces = self._run_frontal_fallback(gray, scale_x, scale_y)
        LOGGER.info("Detected %s face(s) with frontal Haar fallback: %s", len(faces), path)
        return image_size, faces
