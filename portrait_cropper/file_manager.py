"""Input discovery, safe output naming, and folder helpers."""

from __future__ import annotations

from pathlib import Path

from .settings import AppSettings


SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


def discover_images(paths: list[Path]) -> list[Path]:
    """Return unique supported images from a mix of files and folders."""

    discovered: list[Path] = []
    seen: set[Path] = set()
    for supplied in paths:
        candidates = supplied.rglob("*") if supplied.is_dir() else (supplied,)
        for candidate in candidates:
            if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTENSIONS:
                resolved = candidate.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    discovered.append(resolved)
    return sorted(discovered, key=lambda path: path.name.casefold())


def default_output_folder(source: Path) -> Path:
    """Choose a sibling 'Cropped Portraits' folder."""

    parent = source if source.is_dir() else source.parent
    return parent / "Cropped Portraits"


def output_extension(source: Path) -> str:
    """Preserve JPEG/PNG when possible; convert other formats to JPEG."""

    suffix = source.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png"}:
        return suffix
    return ".jpg"


def build_output_path(
    source: Path,
    output_folder: Path,
    settings: AppSettings,
    sequence: int,
    reserved: set[Path] | None = None,
) -> Path:
    """Build a collision-safe output path without touching the source."""

    extension = output_extension(source)
    if settings.naming_mode == "Keep original filename":
        base = source.stem
    elif settings.naming_mode == "Sequential filenames":
        base = f"portrait_{sequence:03d}"
    elif settings.naming_mode == "Custom prefix":
        prefix = settings.custom_prefix.strip() or "portrait"
        base = f"{prefix}_{sequence:03d}"
    else:
        base = f"{source.stem}{settings.filename_suffix}"

    reserved = reserved or set()
    candidate = output_folder / f"{base}{extension}"
    # Never select the source itself when the output folder is its parent.
    if candidate.resolve() == source.resolve():
        candidate = output_folder / f"{base}_1{extension}"
    if candidate not in reserved and (settings.overwrite_existing or not candidate.exists()):
        return candidate
    counter = 1
    while True:
        numbered = output_folder / f"{base}_{counter}{extension}"
        available_on_disk = settings.overwrite_existing or not numbered.exists()
        if numbered not in reserved and available_on_disk and numbered.resolve() != source.resolve():
            return numbered
        counter += 1
