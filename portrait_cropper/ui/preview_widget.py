"""Interactive before-and-after image preview widgets."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QWidget
from PIL import Image, ImageOps

from ..models import DetectedFace, Rect


LOGGER = logging.getLogger(__name__)


class PreviewImageError(RuntimeError):
    """Raised when neither Qt nor Pillow can decode a preview image."""


def load_oriented_qimage(path: Path) -> QImage:
    """Return an owned, correctly oriented image, with Pillow as a Qt fallback.

    Some PySide installations contain the JPEG plugin on disk but fail to load it.
    Pillow is already a runtime dependency and gives the preview the same EXIF
    orientation used by detection and final image processing.
    """

    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image = reader.read()
    if not image.isNull():
        LOGGER.info("Preview decoded with Qt: path=%s size=%sx%s", path, image.width(), image.height())
        return image.copy()

    qt_error = reader.errorString()
    LOGGER.warning("Qt could not decode preview; trying Pillow: path=%s error=%s", path, qt_error)
    try:
        with Image.open(path) as raw:
            oriented = ImageOps.exif_transpose(raw).convert("RGBA")
            oriented.load()
            width, height = oriented.size
            data = oriented.tobytes("raw", "RGBA")
        # copy() detaches from the temporary Python byte buffer.
        fallback = QImage(data, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()
        if fallback.isNull():
            raise PreviewImageError("Pillow decoded the file but Qt could not create a preview image.")
        LOGGER.info("Preview decoded with Pillow: path=%s size=%sx%s", path, width, height)
        return fallback
    except PreviewImageError:
        raise
    except Exception as exc:
        raise PreviewImageError(f"{exc} (Qt reader: {qt_error})") from exc


class OriginalPreview(QWidget):
    """Original-image canvas with selectable faces and editable crop overlay."""

    face_selected = Signal(int)
    crop_edited = Signal(object)
    manual_face_created = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(360, 380)
        self.setMouseTracking(True)
        self._image = QImage()
        self._faces: list[DetectedFace] = []
        self._selected_face: int | None = None
        self._crop: Rect | None = None
        self._zoom = 1.0
        self._drag_mode: str | None = None
        self._last_image_point = QPointF()
        self._draw_start: QPointF | None = None
        self._draw_current: QPointF | None = None
        self._placeholder = "Select photos to begin"
        self._load_error = ""

    def set_content(
        self,
        path: Path | None,
        faces: list[DetectedFace] | None = None,
        selected_face: int | None = None,
        crop: Rect | None = None,
        placeholder: str | None = None,
    ) -> bool:
        """Load an image and replace all displayed detection and crop state.

        Returns:
            ``True`` when the source image was decoded successfully.
        """

        self._load_error = ""
        self._placeholder = placeholder if placeholder is not None else ("Select photos to begin" if path is None else "")
        try:
            self._image = load_oriented_qimage(path) if path else QImage()
        except Exception as exc:
            self._image = QImage()
            self._load_error = str(exc)
            self._placeholder = f"Could not load preview: {exc}"
            LOGGER.exception("Could not load original preview: %s", path)
        self._faces = faces or []
        self._selected_face = selected_face
        self._crop = crop
        self._zoom = 1.0
        self.update()
        return not self._image.isNull()

    @property
    def has_image(self) -> bool:
        return not self._image.isNull()

    @property
    def placeholder_text(self) -> str:
        return self._placeholder

    @property
    def load_error(self) -> str:
        return self._load_error

    def set_crop(self, crop: Rect | None) -> None:
        self._crop = crop
        self.update()

    def _image_rect(self) -> QRectF:
        """Return the scaled image bounds centered in widget coordinates."""

        if self._image.isNull():
            return QRectF()
        fit = min(self.width() / self._image.width(), self.height() / self._image.height())
        scale = fit * self._zoom
        width = self._image.width() * scale
        height = self._image.height() * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)

    def _to_widget_rect(self, rect: Rect) -> QRectF:
        """Transform a source-image rectangle into widget coordinates."""

        image_rect = self._image_rect()
        scale = image_rect.width() / self._image.width()
        return QRectF(
            image_rect.x() + rect.x * scale,
            image_rect.y() + rect.y * scale,
            rect.width * scale,
            rect.height * scale,
        )

    def _to_image_point(self, point: QPointF) -> QPointF:
        """Transform a widget point into source-image coordinates."""

        image_rect = self._image_rect()
        if image_rect.isEmpty():
            return QPointF()
        scale = self._image.width() / image_rect.width()
        return QPointF((point.x() - image_rect.x()) * scale, (point.y() - image_rect.y()) * scale)

    def paintEvent(self, event: object) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#171a21"))
        if self._image.isNull():
            painter.setPen(QColor("#aeb5c4"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._placeholder)
            return
        target = self._image_rect()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(target, self._image)

        for index, face in enumerate(self._faces):
            selected = index == self._selected_face
            pen = QPen(QColor("#42d392") if selected else QColor("#ffd166"), 3 if selected else 2)
            painter.setPen(pen)
            painter.drawRect(self._to_widget_rect(face.rect))
            label_rect = self._to_widget_rect(face.rect)
            painter.fillRect(QRectF(label_rect.x(), label_rect.y(), 28, 20), pen.color())
            painter.setPen(QColor("#101217"))
            painter.drawText(QRectF(label_rect.x(), label_rect.y(), 28, 20), Qt.AlignmentFlag.AlignCenter, str(index + 1))

        if self._crop:
            crop_rect = self._to_widget_rect(self._crop)
            painter.setPen(QPen(QColor("#4aa8ff"), 3, Qt.PenStyle.DashLine))
            painter.drawRect(crop_rect)
            painter.fillRect(QRectF(crop_rect.right() - 8, crop_rect.bottom() - 8, 16, 16), QColor("#4aa8ff"))

        if self._draw_start and self._draw_current:
            manual = QRectF(self._draw_start, self._draw_current).normalized()
            painter.setPen(QPen(QColor("#ff7a90"), 3, Qt.PenStyle.DashLine))
            painter.drawRect(self._to_widget_rect(Rect(manual.x(), manual.y(), manual.width(), manual.height())))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Select a face or begin crop movement, resizing, or face drawing."""

        if self._image.isNull() or event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        image_point = self._to_image_point(point)
        for index, face in enumerate(self._faces):
            if self._to_widget_rect(face.rect).contains(point):
                self.face_selected.emit(index)
                return
        if self._crop:
            crop_widget = self._to_widget_rect(self._crop)
            handle = QPointF(crop_widget.right(), crop_widget.bottom())
            if (handle - point).manhattanLength() <= 24:
                self._drag_mode = "resize"
                self._last_image_point = image_point
                return
            if crop_widget.contains(point):
                self._drag_mode = "move"
                self._last_image_point = image_point
                return
        if not self._faces and self._image_rect().contains(point):
            self._drag_mode = "manual"
            self._draw_start = image_point
            self._draw_current = image_point

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Update the active manual face box or emit an edited crop."""

        if not self._drag_mode:
            return
        point = self._to_image_point(event.position())
        if self._drag_mode == "manual":
            self._draw_current = point
            self.update()
            return
        if not self._crop:
            return
        if self._drag_mode == "move":
            dx = point.x() - self._last_image_point.x()
            dy = point.y() - self._last_image_point.y()
            crop = Rect(self._crop.x + dx, self._crop.y + dy, self._crop.width, self._crop.height)
        else:
            new_width = max(20.0, point.x() - self._crop.x)
            new_height = new_width * self._crop.height / self._crop.width
            crop = Rect(self._crop.x, self._crop.y, new_width, new_height)
        self._last_image_point = point
        self.crop_edited.emit(crop)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Finish the active gesture and emit a valid manual face box."""

        del event
        if self._drag_mode == "manual" and self._draw_start and self._draw_current:
            box = QRectF(self._draw_start, self._draw_current).normalized()
            if box.width() >= 10 and box.height() >= 10:
                self.manual_face_created.emit(Rect(box.x(), box.y(), box.width(), box.height()))
        self._drag_mode = None
        self._draw_start = None
        self._draw_current = None
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        factor = 1.12 if event.angleDelta().y() > 0 else 1 / 1.12
        self._zoom = max(0.5, min(4.0, self._zoom * factor))
        self.update()


class CroppedPreview(QWidget):
    """Read-only live rendering of the proposed cropped result."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(300, 380)
        self._image = QImage()
        self._crop: Rect | None = None
        self._placeholder = "Crop preview"
        self._load_error = ""

    def set_content(self, path: Path | None, crop: Rect | None, placeholder: str | None = None) -> bool:
        """Load a source image and crop rectangle for rendering.

        Returns:
            ``True`` when both a decoded image and crop rectangle are present.
        """

        self._load_error = ""
        self._placeholder = placeholder or "Crop preview"
        try:
            self._image = load_oriented_qimage(path) if path else QImage()
        except Exception as exc:
            self._image = QImage()
            self._load_error = str(exc)
            self._placeholder = f"Could not load preview: {exc}"
            LOGGER.exception("Could not load cropped preview source: %s", path)
        self._crop = crop
        self.update()
        return not self._image.isNull() and crop is not None

    @property
    def has_image(self) -> bool:
        return not self._image.isNull() and self._crop is not None

    @property
    def placeholder_text(self) -> str:
        return self._placeholder

    @property
    def load_error(self) -> str:
        return self._load_error

    def set_crop(self, crop: Rect | None) -> None:
        self._crop = crop
        self.update()

    def paintEvent(self, event: object) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#171a21"))
        if self._image.isNull() or not self._crop:
            painter.setPen(QColor("#aeb5c4"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._placeholder)
            return
        source = QRectF(self._crop.x, self._crop.y, self._crop.width, self._crop.height)
        scale = min(self.width() / source.width(), self.height() / source.height())
        target = QRectF(
            (self.width() - source.width() * scale) / 2,
            (self.height() - source.height() * scale) / 2,
            source.width() * scale,
            source.height() * scale,
        )
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(target, self._image, source)
