"""Processing report generation."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from .models import PhotoItem


REPORT_COLUMNS = [
    "Original filename",
    "Output filename",
    "Number of faces detected",
    "Selected face coordinates (x,y,width,height)",
    "Crop coordinates (x,y,width,height)",
    "Status",
    "Warning or error message",
]


def item_to_row(item: PhotoItem) -> dict[str, object]:
    """Convert one photo's processing state to a report-column mapping."""

    face = item.selected_face.rect.as_int_tuple() if item.selected_face else ""
    crop = item.crop_rect.as_int_tuple() if item.crop_rect else ""
    message = item.error or item.warning
    return {
        REPORT_COLUMNS[0]: item.source_path.name,
        REPORT_COLUMNS[1]: item.output_path.name if item.output_path else "",
        REPORT_COLUMNS[2]: len(item.faces),
        REPORT_COLUMNS[3]: ",".join(map(str, face)) if face else "",
        REPORT_COLUMNS[4]: ",".join(map(str, crop)) if crop else "",
        REPORT_COLUMNS[5]: item.status.value,
        REPORT_COLUMNS[6]: message,
    }


def export_csv(items: Iterable[PhotoItem], path: Path) -> None:
    """Write photo results as a UTF-8 CSV compatible with spreadsheets.

    The UTF-8 byte-order mark helps common spreadsheet applications detect the
    encoding. File-system and encoding failures propagate to the caller.
    """

    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(item_to_row(item) for item in items)
