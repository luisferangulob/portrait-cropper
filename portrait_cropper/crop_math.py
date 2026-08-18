"""Pure functions for calculating and constraining portrait crops."""

from __future__ import annotations

from .models import DetectedFace, Rect


class CropCalculationError(ValueError):
    """Raised when a valid crop cannot be calculated."""


def select_primary_face(faces: list[DetectedFace]) -> int | None:
    """Return the index of the largest face, or ``None`` when none exist."""

    if not faces:
        return None
    return max(range(len(faces)), key=lambda index: faces[index].rect.area)


def clamp(value: float, minimum: float, maximum: float) -> float:
    """Constrain ``value`` to the inclusive numeric interval."""

    return max(minimum, min(value, maximum))


def calculate_crop(
    image_size: tuple[int, int],
    face: Rect,
    aspect_ratio: float,
    target_face_fraction: float = 0.30,
    headroom_fraction: float = 0.05,
    allow_padding: bool = False,
    head_extension_fraction: float = 0.35,
) -> Rect:
    """Calculate a face-guided crop in source-image coordinates.

    The face height defines the crop height. ``head_extension_fraction``
    estimates the forehead, hair, and skull above the detector box, and
    ``headroom_fraction`` adds visible margin above that estimated head top.
    Without padding, an oversized crop is reduced proportionally and then
    shifted inside the source bounds.

    Args:
        image_size: Oriented source width and height in pixels.
        face: Selected face reference rectangle.
        aspect_ratio: Required crop width divided by height.
        target_face_fraction: Desired fraction of crop height occupied by the
            detector's face box.
        headroom_fraction: Extra crop-height margin above the estimated head.
        allow_padding: Whether crop coordinates may extend beyond the source.
        head_extension_fraction: Estimated head height above the face box.

    Returns:
        A crop rectangle, constrained to the image unless padding is enabled.

    Raises:
        CropCalculationError: If dimensions or fractional settings are invalid.
    """

    image_width, image_height = image_size
    if image_width <= 0 or image_height <= 0:
        raise CropCalculationError("The source image has invalid dimensions.")
    if face.width <= 0 or face.height <= 0:
        raise CropCalculationError("The face reference box has invalid dimensions.")
    if not 0 < target_face_fraction <= 1:
        raise CropCalculationError("Target face fraction must be between 0 and 1.")
    if not 0 <= headroom_fraction <= 1:
        raise CropCalculationError("Headroom fraction must be between 0 and 1.")
    if not 0 <= head_extension_fraction <= 1:
        raise CropCalculationError("Head extension fraction must be between 0 and 1.")
    if aspect_ratio <= 0:
        raise CropCalculationError("Aspect ratio must be positive.")

    # Establish the ideal crop from face scale before applying source limits;
    # scaling both dimensions together preserves the requested aspect ratio.
    crop_height = face.height / target_face_fraction
    crop_width = crop_height * aspect_ratio

    if not allow_padding:
        fit_scale = min(1.0, image_width / crop_width, image_height / crop_height)
        crop_width *= fit_scale
        crop_height *= fit_scale

    crop_x = face.center_x - crop_width / 2
    # YuNet/Haar boxes frame the face rather than the full head, so vertical
    # placement combines a face-relative head estimate with crop-relative space.
    estimated_head_top = face.y - head_extension_fraction * face.height
    crop_y = estimated_head_top - headroom_fraction * crop_height

    if not allow_padding:
        crop_x = clamp(crop_x, 0.0, image_width - crop_width)
        crop_y = clamp(crop_y, 0.0, image_height - crop_height)

    return Rect(crop_x, crop_y, crop_width, crop_height)


def move_crop(crop: Rect, dx: float, dy: float, image_size: tuple[int, int]) -> Rect:
    """Move a crop without changing its size, constrained to the source image.

    Returns:
        The translated crop rectangle in source-image coordinates.
    """

    image_width, image_height = image_size
    return Rect(
        clamp(crop.x + dx, 0, max(0.0, image_width - crop.width)),
        clamp(crop.y + dy, 0, max(0.0, image_height - crop.height)),
        crop.width,
        crop.height,
    )


def resize_crop_from_center(
    crop: Rect,
    new_width: float,
    aspect_ratio: float,
    image_size: tuple[int, int],
) -> Rect:
    """Resize around the crop center while retaining aspect ratio and bounds.

    Returns:
        A centered crop scaled and shifted to fit the source image.
    """

    image_width, image_height = image_size
    new_width = max(20.0, new_width)
    new_height = new_width / aspect_ratio
    scale = min(1.0, image_width / new_width, image_height / new_height)
    new_width *= scale
    new_height *= scale
    x = clamp(crop.center_x - new_width / 2, 0, image_width - new_width)
    y = clamp(crop.center_y - new_height / 2, 0, image_height - new_height)
    return Rect(x, y, new_width, new_height)
