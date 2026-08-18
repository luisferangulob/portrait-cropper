"""High-quality, metadata-aware image cropping and saving."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageOps, PngImagePlugin

from .models import Rect
from .settings import AppSettings


class ImageProcessingError(RuntimeError):
    """A user-presentable image processing failure."""


def _integer_box(rect: Rect) -> tuple[int, int, int, int]:
    """Convert a crop rectangle to a non-empty Pillow pixel box.

    Raises:
        ImageProcessingError: If rounding collapses either crop dimension.
    """

    left = round(rect.x)
    top = round(rect.y)
    right = round(rect.right)
    bottom = round(rect.bottom)
    if right <= left or bottom <= top:
        raise ImageProcessingError("The crop area is empty.")
    return left, top, right, bottom


def process_image(source: Path, destination: Path, crop: Rect, settings: AppSettings) -> None:
    """Orient, crop, resize, and atomically save one photograph.

    The destination format is inferred from its extension. Metadata is retained
    according to ``settings`` and the source file is never modified.

    Raises:
        ImageProcessingError: If the crop is invalid or the image cannot be
            decoded, transformed, or saved.
    """

    try:
        with Image.open(source) as raw:
            exif = raw.getexif()
            icc_profile = raw.info.get("icc_profile")
            png_text = {
                key: value for key, value in raw.info.items() if isinstance(value, str)
            }
            # Normalize camera orientation so detection, preview, and saved pixels
            # all share the same coordinate system. This preserves visual orientation.
            image = ImageOps.exif_transpose(raw)
            image.load()

        cropped = image.crop(_integer_box(crop))
        output_size = (
            min(settings.output_width, settings.maximum_output_width),
            min(settings.output_height, settings.maximum_output_height),
        )
        cropped = cropped.resize(output_size, Image.Resampling.LANCZOS)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")

        save_options: dict[str, object] = {}
        suffix = destination.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            if cropped.mode not in {"RGB", "L"}:
                background = Image.new("RGB", cropped.size, "white")
                if "A" in cropped.getbands():
                    background.paste(cropped, mask=cropped.getchannel("A"))
                else:
                    background.paste(cropped.convert("RGB"))
                cropped = background
            save_options.update(quality=settings.jpeg_quality, subsampling=0, optimize=True)
            if settings.preserve_metadata and settings.preserve_exif and exif:
                # Orientation is now physically applied, so do not re-rotate later.
                exif[274] = 1
                exif[40962] = output_size[0]
                exif[40963] = output_size[1]
                save_options["exif"] = exif.tobytes()
        elif suffix == ".png" and settings.preserve_metadata and png_text:
            png_info = PngImagePlugin.PngInfo()
            for key, value in png_text.items():
                png_info.add_text(key, value)
            save_options["pnginfo"] = png_info
        if settings.preserve_metadata and icc_profile:
            save_options["icc_profile"] = icc_profile

        format_name = "JPEG" if suffix in {".jpg", ".jpeg"} else "PNG"
        cropped.save(temporary, format=format_name, **save_options)
        temporary.replace(destination)
    except ImageProcessingError:
        raise
    except PermissionError as exc:
        raise ImageProcessingError("Permission was denied while saving the image.") from exc
    except Exception as exc:
        raise ImageProcessingError(f"Could not process this image: {exc}") from exc
