"""Main PySide6 window for the Portrait Cropper application."""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QColor, QDesktopServices, QDragEnterEvent, QDropEvent, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QDoubleSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..crop_math import calculate_crop, clamp, select_primary_face
from ..file_manager import build_output_path, default_output_folder, discover_images
from ..models import DetectedFace, PhotoItem, PhotoStatus, Rect
from ..reporting import export_csv
from ..settings import ASPECT_PRESETS, AppSettings
from ..workers import AnalysisThread, ProcessingThread
from .preview_widget import CroppedPreview, OriginalPreview, load_oriented_qimage


LOGGER = logging.getLogger(__name__)


STATUS_COLORS = {
    PhotoStatus.PENDING: "#aeb5c4",
    PhotoStatus.READY: "#58c98b",
    PhotoStatus.MULTIPLE: "#f3b64b",
    PhotoStatus.NEEDS_REVIEW: "#ff8a65",
    PhotoStatus.APPROVED: "#4aa8ff",
    PhotoStatus.SKIPPED: "#89909d",
    PhotoStatus.PROCESSED: "#42d392",
    PhotoStatus.ERROR: "#ff647c",
}


class MainWindow(QMainWindow):
    """A single-window, nontechnical workflow for portrait cropping."""

    def __init__(self, initial_settings: AppSettings | None = None) -> None:
        super().__init__()
        self.settings = initial_settings or AppSettings()
        self.photos: list[PhotoItem] = []
        self.output_folder: Path | None = None
        self.analysis_thread: AnalysisThread | None = None
        self.processing_thread: ProcessingThread | None = None
        self._updating_controls = False

        self.setWindowTitle("Portrait Cropper")
        self.resize(1320, 850)
        self.setMinimumSize(1050, 700)
        self.setAcceptDrops(True)
        self._build_ui()
        self._apply_style()
        self._load_settings_into_controls()
        self._update_counts()

    def _build_ui(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        header = QHBoxLayout()
        title_column = QVBoxLayout()
        title = QLabel("Portrait Cropper")
        title.setObjectName("title")
        subtitle = QLabel("Consistent, face-guided crops — entirely offline")
        subtitle.setObjectName("subtitle")
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header.addLayout(title_column)
        header.addStretch()
        self.select_photos_button = QPushButton("＋  Select Photos")
        self.select_folder_button = QPushButton("▣  Select Folder")
        self.start_new_batch_button = QPushButton("Start New Batch")
        self.select_photos_button.setObjectName("primary")
        self.select_folder_button.setObjectName("primary")
        self.select_photos_button.clicked.connect(self._select_photos)
        self.select_folder_button.clicked.connect(self._select_folder)
        self.start_new_batch_button.clicked.connect(self._start_new_batch)
        self.start_new_batch_button.setEnabled(False)
        header.addWidget(self.start_new_batch_button)
        header.addWidget(self.select_photos_button)
        header.addWidget(self.select_folder_button)
        outer.addLayout(header)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.setChildrenCollapsible(False)

        sidebar = QFrame()
        sidebar.setObjectName("panel")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_title = QLabel("Photos")
        sidebar_title.setObjectName("sectionTitle")
        sidebar_layout.addWidget(sidebar_title)
        self.photo_list = QListWidget()
        self.photo_list.setIconSize(QPixmap(70, 52).size())
        self.photo_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.photo_list.currentRowChanged.connect(self._show_photo)
        self.photo_list.itemClicked.connect(self._show_clicked_photo)
        sidebar_layout.addWidget(self.photo_list)
        self.counts_label = QLabel("No photos selected")
        self.counts_label.setWordWrap(True)
        sidebar_layout.addWidget(self.counts_label)
        main_splitter.addWidget(sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(9)

        self.status_banner = QLabel("Drop photos or a folder here, or use the buttons above.")
        self.status_banner.setObjectName("banner")
        self.status_banner.setWordWrap(True)
        right_layout.addWidget(self.status_banner)

        preview_labels = QHBoxLayout()
        original_label = QLabel("ORIGINAL  •  drag crop / scroll to zoom")
        result_label = QLabel("PROPOSED CROP")
        original_label.setObjectName("previewLabel")
        result_label.setObjectName("previewLabel")
        preview_labels.addWidget(original_label, 3)
        preview_labels.addWidget(result_label, 2)
        right_layout.addLayout(preview_labels)

        preview_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.original_preview = OriginalPreview()
        self.cropped_preview = CroppedPreview()
        self.original_preview.face_selected.connect(self._select_face)
        self.original_preview.crop_edited.connect(self._edit_crop)
        self.original_preview.manual_face_created.connect(self._create_manual_face)
        preview_splitter.addWidget(self.original_preview)
        preview_splitter.addWidget(self.cropped_preview)
        preview_splitter.setStretchFactor(0, 3)
        preview_splitter.setStretchFactor(1, 2)
        right_layout.addWidget(preview_splitter, 1)

        action_row = QHBoxLayout()
        self.reset_button = QPushButton("Reset Automatic Crop")
        self.approve_button = QPushButton("✓ Approve Crop")
        self.skip_button = QPushButton("Skip Image")
        self.reset_button.clicked.connect(self._reset_current_crop)
        self.approve_button.clicked.connect(self._approve_current)
        self.skip_button.clicked.connect(self._skip_current)
        self.reset_button.setEnabled(False)
        self.approve_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        action_row.addWidget(self.reset_button)
        action_row.addStretch()
        action_row.addWidget(self.skip_button)
        action_row.addWidget(self.approve_button)
        right_layout.addLayout(action_row)

        settings_scroll = QScrollArea()
        settings_scroll.setWidgetResizable(True)
        settings_scroll.setMaximumHeight(255)
        settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        settings_container = QWidget()
        settings_layout = QVBoxLayout(settings_container)
        settings_layout.setContentsMargins(0, 0, 4, 0)
        settings_layout.addWidget(self._create_simple_settings())
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Advanced Settings")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        settings_layout.addWidget(self.advanced_toggle)
        self.advanced_panel = self._create_advanced_settings()
        self.advanced_panel.hide()
        settings_layout.addWidget(self.advanced_panel)
        settings_scroll.setWidget(settings_container)
        right_layout.addWidget(settings_scroll)
        main_splitter.addWidget(right)
        main_splitter.setSizes([300, 1000])
        outer.addWidget(main_splitter, 1)

        processing = QFrame()
        processing.setObjectName("processing")
        process_layout = QGridLayout(processing)
        self.analyze_button = QPushButton("Analyze Photos")
        self.review_button = QPushButton("Review Crops")
        self.save_button = QPushButton("Crop and Save")
        self.cancel_button = QPushButton("Cancel")
        self.open_button = QPushButton("Open Output Folder")
        self.save_button.setObjectName("save")
        self.cancel_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.analyze_button.clicked.connect(self._analyze)
        self.review_button.clicked.connect(self._review_crops)
        self.save_button.clicked.connect(self._crop_and_save)
        self.cancel_button.clicked.connect(self._cancel_work)
        self.open_button.clicked.connect(self._open_output_folder)
        button_row = QHBoxLayout()
        for button in (self.analyze_button, self.review_button, self.save_button, self.cancel_button, self.open_button):
            button_row.addWidget(button)
        process_layout.addLayout(button_row, 0, 0, 1, 2)
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.current_file_label = QLabel("Ready")
        process_layout.addWidget(self.progress, 1, 0)
        process_layout.addWidget(self.current_file_label, 1, 1)
        outer.addWidget(processing)
        self.setCentralWidget(root)

    def _create_simple_settings(self) -> QGroupBox:
        group = QGroupBox("Output Settings")
        grid = QGridLayout(group)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Created beside your photos: Cropped Portraits")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_output)
        grid.addWidget(QLabel("Output folder"), 0, 0)
        grid.addWidget(self.output_edit, 0, 1, 1, 4)
        grid.addWidget(browse, 0, 5)

        self.aspect_combo = QComboBox()
        self.aspect_combo.addItems([*ASPECT_PRESETS.keys(), "Custom"])
        self.aspect_width = QSpinBox()
        self.aspect_height = QSpinBox()
        for spin in (self.aspect_width, self.aspect_height):
            spin.setRange(1, 100)
            spin.setFixedWidth(62)
        self.output_width = QSpinBox()
        self.output_height = QSpinBox()
        for spin in (self.output_width, self.output_height):
            spin.setRange(1, 20000)
            spin.setSingleStep(100)
            spin.setSuffix(" px")
        grid.addWidget(QLabel("Aspect ratio"), 1, 0)
        grid.addWidget(self.aspect_combo, 1, 1)
        grid.addWidget(self.aspect_width, 1, 2)
        grid.addWidget(QLabel(":"), 1, 3)
        grid.addWidget(self.aspect_height, 1, 4)
        grid.addWidget(QLabel("Output size"), 2, 0)
        grid.addWidget(self.output_width, 2, 1, 1, 2)
        grid.addWidget(self.output_height, 2, 3, 1, 2)

        self.naming_combo = QComboBox()
        self.naming_combo.addItems([
            "Add _cropped suffix",
            "Keep original filename",
            "Sequential filenames",
            "Custom prefix",
        ])
        self.custom_prefix = QLineEdit("portrait")
        self.custom_prefix.setPlaceholderText("Custom prefix")
        grid.addWidget(QLabel("File naming"), 3, 0)
        grid.addWidget(self.naming_combo, 3, 1, 1, 2)
        grid.addWidget(self.custom_prefix, 3, 3, 1, 2)
        self.preserve_metadata = QCheckBox("Preserve metadata")
        self.auto_process = QCheckBox("Process all ready images without approval")
        grid.addWidget(self.preserve_metadata, 4, 1, 1, 2)
        grid.addWidget(self.auto_process, 4, 3, 1, 3)

        self.aspect_combo.currentTextChanged.connect(self._aspect_preset_changed)
        for widget in (self.aspect_width, self.aspect_height, self.output_width, self.output_height):
            widget.valueChanged.connect(self._settings_changed)
        self.naming_combo.currentTextChanged.connect(self._settings_changed)
        self.custom_prefix.textChanged.connect(self._settings_changed)
        self.preserve_metadata.toggled.connect(self._settings_changed)
        self.auto_process.toggled.connect(self._settings_changed)
        return group

    def _create_advanced_settings(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("advanced")
        form = QFormLayout(panel)
        self.face_percent = QDoubleSpinBox()
        self.face_percent.setRange(5, 90)
        self.face_percent.setSuffix(" %")
        self.head_extension_percent = QDoubleSpinBox()
        self.head_extension_percent.setRange(0, 100)
        self.head_extension_percent.setSingleStep(5)
        self.head_extension_percent.setSuffix(" %")
        self.headroom_percent = QDoubleSpinBox()
        self.headroom_percent.setRange(0, 40)
        self.headroom_percent.setSuffix(" %")
        self.confidence = QDoubleSpinBox()
        self.confidence.setRange(0, 1)
        self.confidence.setSingleStep(0.05)
        self.jpeg_quality = QSpinBox()
        self.jpeg_quality.setRange(1, 100)
        self.allow_padding = QCheckBox("Allow black/transparent padding if the ideal crop is outside the photo")
        self.overwrite = QCheckBox("Allow replacing files in the output folder")
        self.suffix_edit = QLineEdit("_cropped")
        max_row = QWidget()
        max_layout = QHBoxLayout(max_row)
        max_layout.setContentsMargins(0, 0, 0, 0)
        self.max_width = QSpinBox()
        self.max_height = QSpinBox()
        for spin in (self.max_width, self.max_height):
            spin.setRange(100, 30000)
            spin.setSuffix(" px")
        max_layout.addWidget(self.max_width)
        max_layout.addWidget(QLabel("×"))
        max_layout.addWidget(self.max_height)
        self.preserve_orientation = QCheckBox("Apply camera/phone orientation")
        self.preserve_exif = QCheckBox("Preserve EXIF metadata")
        form.addRow("Target face height", self.face_percent)
        form.addRow("Head extension above face", self.head_extension_percent)
        form.addRow("Headroom above head", self.headroom_percent)
        form.addRow("Detection confidence", self.confidence)
        form.addRow("JPEG quality", self.jpeg_quality)
        form.addRow("Optional padding", self.allow_padding)
        form.addRow("Overwrite behavior", self.overwrite)
        form.addRow("Filename suffix", self.suffix_edit)
        form.addRow("Maximum output", max_row)
        form.addRow("Orientation", self.preserve_orientation)
        form.addRow("EXIF", self.preserve_exif)
        for widget in (self.face_percent, self.head_extension_percent, self.headroom_percent, self.confidence, self.jpeg_quality, self.max_width, self.max_height):
            widget.valueChanged.connect(self._settings_changed)
        for widget in (self.allow_padding, self.overwrite, self.preserve_orientation, self.preserve_exif):
            widget.toggled.connect(self._settings_changed)
        self.suffix_edit.textChanged.connect(self._settings_changed)
        return panel

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #20242d; color: #edf1f7; font-size: 13px; }
            QLabel#title { font-size: 25px; font-weight: 700; }
            QLabel#subtitle { color: #aeb5c4; }
            QLabel#sectionTitle { font-size: 16px; font-weight: 650; }
            QLabel#banner { background: #293140; border-left: 4px solid #4aa8ff; padding: 8px; border-radius: 3px; }
            QLabel#previewLabel { color: #aeb5c4; font-size: 11px; font-weight: 650; }
            QFrame#panel, QFrame#processing, QGroupBox, QFrame#advanced { background: #282d38; border: 1px solid #363d4b; border-radius: 8px; }
            QGroupBox { margin-top: 12px; padding-top: 12px; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QPushButton { background: #343b49; border: 1px solid #485164; border-radius: 6px; padding: 8px 12px; }
            QPushButton:hover { background: #414a5b; }
            QPushButton:disabled { color: #747b88; background: #2a2f38; }
            QPushButton#primary, QPushButton#save { background: #2f78c4; border-color: #4aa8ff; font-weight: 650; }
            QPushButton#primary:hover, QPushButton#save:hover { background: #3989db; }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #1e222a; border: 1px solid #454e60; border-radius: 5px; padding: 5px; }
            QListWidget { background: #20242d; border: none; outline: none; }
            QListWidget::item { border-bottom: 1px solid #303744; padding: 7px; }
            QListWidget::item:selected { background: #34445c; border-radius: 5px; }
            QProgressBar { background: #1e222a; border: 1px solid #454e60; border-radius: 5px; text-align: center; }
            QProgressBar::chunk { background: #42a5f5; border-radius: 4px; }
            QScrollArea { background: transparent; }
            QToolButton { background: transparent; border: none; font-weight: 650; padding: 5px; }
        """)

    def _load_settings_into_controls(self) -> None:
        self._updating_controls = True
        s = self.settings
        self.aspect_combo.setCurrentText(s.aspect_name if s.aspect_name in ASPECT_PRESETS else "Custom")
        self.aspect_width.setValue(s.aspect_width)
        self.aspect_height.setValue(s.aspect_height)
        self.output_width.setValue(s.output_width)
        self.output_height.setValue(s.output_height)
        self.naming_combo.setCurrentText(s.naming_mode)
        self.custom_prefix.setText(s.custom_prefix)
        self.preserve_metadata.setChecked(s.preserve_metadata)
        self.auto_process.setChecked(s.auto_process_all)
        self.face_percent.setValue(s.target_face_percent)
        self.head_extension_percent.setValue(s.head_extension_percent)
        self.headroom_percent.setValue(s.headroom_percent)
        self.confidence.setValue(s.detection_confidence)
        self.jpeg_quality.setValue(s.jpeg_quality)
        self.allow_padding.setChecked(s.allow_padding)
        self.overwrite.setChecked(s.overwrite_existing)
        self.suffix_edit.setText(s.filename_suffix)
        self.max_width.setValue(s.maximum_output_width)
        self.max_height.setValue(s.maximum_output_height)
        self.preserve_orientation.setChecked(s.preserve_orientation)
        self.preserve_exif.setChecked(s.preserve_exif)
        self._updating_controls = False

    def _read_settings(self) -> AppSettings:
        """Build validated application settings from the current controls."""

        return AppSettings(
            aspect_name=self.aspect_combo.currentText(),
            aspect_width=self.aspect_width.value(),
            aspect_height=self.aspect_height.value(),
            output_width=self.output_width.value(),
            output_height=self.output_height.value(),
            naming_mode=self.naming_combo.currentText(),
            custom_prefix=self.custom_prefix.text(),
            preserve_metadata=self.preserve_metadata.isChecked(),
            auto_process_all=self.auto_process.isChecked(),
            target_face_percent=self.face_percent.value(),
            head_extension_percent=self.head_extension_percent.value(),
            headroom_percent=self.headroom_percent.value(),
            detection_confidence=self.confidence.value(),
            jpeg_quality=self.jpeg_quality.value(),
            allow_padding=self.allow_padding.isChecked(),
            overwrite_existing=self.overwrite.isChecked(),
            filename_suffix=self.suffix_edit.text() or "_cropped",
            maximum_output_width=self.max_width.value(),
            maximum_output_height=self.max_height.value(),
            preserve_orientation=self.preserve_orientation.isChecked(),
            preserve_exif=self.preserve_exif.isChecked(),
        ).validated()

    def _toggle_advanced(self, checked: bool) -> None:
        self.advanced_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self.advanced_panel.setVisible(checked)

    def _aspect_preset_changed(self, name: str) -> None:
        """Apply a named aspect preset and recompute the linked output width."""

        if self._updating_controls:
            return
        if name in ASPECT_PRESETS:
            width, height = ASPECT_PRESETS[name]
            self._updating_controls = True
            self.aspect_width.setValue(width)
            self.aspect_height.setValue(height)
            output_height = self.output_height.value() or 2000
            self.output_width.setValue(round(output_height * width / height))
            self._updating_controls = False
        self._settings_changed()

    def _settings_changed(self, *args: object) -> None:
        """Persist control values and recalculate every eligible crop."""

        del args
        if self._updating_controls:
            return
        self.settings = self._read_settings()
        for photo in self.photos:
            if photo.selected_face and photo.image_size and photo.status not in {PhotoStatus.SKIPPED, PhotoStatus.PROCESSED, PhotoStatus.ERROR}:
                self._calculate_photo_crop(photo)
        self._show_photo(self.photo_list.currentRow())

    def _select_photos(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(
            self,
            "Select portrait photos",
            "",
            "Images (*.jpg *.jpeg *.png *.tif *.tiff *.webp)",
        )
        self._add_paths([Path(name) for name in names])

    def _select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select a folder of portrait photos")
        if folder:
            self._add_paths([Path(folder)])

    def _add_paths(self, paths: list[Path]) -> None:
        """Discover unique images, create batch models, and show previews."""

        images = discover_images(paths)
        existing = {photo.source_path.resolve() for photo in self.photos}
        new_images = [path for path in images if path.resolve() not in existing]
        if not new_images:
            self.status_banner.setText("No new supported images were found. Try JPG, PNG, TIFF, or WEBP files.")
            return
        if self.output_folder is None:
            self.output_folder = default_output_folder(paths[0])
            self.output_edit.setText(str(self.output_folder))
        for path in new_images:
            photo = PhotoItem(path)
            self.photos.append(photo)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, photo)
            try:
                preview_image = load_oriented_qimage(path)
                pixmap = QPixmap.fromImage(preview_image)
                if not pixmap.isNull():
                    item.setIcon(QIcon(pixmap.scaled(70, 52, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))
            except Exception:
                LOGGER.exception("Could not create sidebar thumbnail: %s", path)
            self.photo_list.addItem(item)
            self._refresh_list_item(len(self.photos) - 1)
        if self.photo_list.currentRow() < 0:
            self.photo_list.setCurrentRow(0)
        # The first row can already be current, so never rely on a selection signal.
        self._show_photo(self.photo_list.currentRow())
        self.status_banner.setText(f"Added {len(new_images)} photo(s). Choose Analyze Photos when ready.")
        self.start_new_batch_button.setEnabled(True)
        self._update_counts()

    def _batch_requires_confirmation(self) -> bool:
        """Return whether clearing the batch would discard meaningful work."""

        meaningful_statuses = {PhotoStatus.APPROVED, PhotoStatus.SKIPPED, PhotoStatus.PROCESSED}
        return any(
            photo.status in meaningful_statuses
            or photo.manually_adjusted
            or photo.output_path is not None
            or (photo.status == PhotoStatus.NEEDS_REVIEW and photo.selected_face is not None)
            for photo in self.photos
        )

    def _confirm_start_new_batch(self) -> bool:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Start a new batch?")
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setText("Start a new batch?")
        dialog.setInformativeText(
            "This will remove the current photos and crop adjustments from Portrait Cropper. "
            "Saved output files will not be deleted."
        )
        cancel_button = dialog.addButton(QMessageBox.StandardButton.Cancel)
        start_button = dialog.addButton("Start New Batch", QMessageBox.ButtonRole.AcceptRole)
        dialog.setDefaultButton(cancel_button)
        dialog.exec()
        return dialog.clickedButton() == start_button

    def _start_new_batch(self) -> None:
        """Clear an idle batch after obtaining confirmation when needed."""

        active = (self.analysis_thread and self.analysis_thread.isRunning()) or (
            self.processing_thread and self.processing_thread.isRunning()
        )
        if active or not self.photos:
            return
        if self._batch_requires_confirmation() and not self._confirm_start_new_batch():
            return
        self._clear_batch_session()

    def _clear_batch_session(self) -> None:
        """Clear only photo-session state while retaining all user settings."""

        self.photos.clear()
        self.photo_list.clear()
        self.original_preview.set_content(None)
        self.cropped_preview.set_content(None, None)
        self.analysis_thread = None
        self.processing_thread = None
        self.progress.setValue(0)
        self.current_file_label.setText("Ready")
        self.status_banner.setText("Ready for a new batch. Select photos or a folder.")
        self.reset_button.setEnabled(False)
        self.approve_button.setEnabled(False)
        self.skip_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.start_new_batch_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self._update_counts()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        self._add_paths(paths)
        event.acceptProposedAction()

    def _refresh_list_item(self, index: int) -> None:
        if not 0 <= index < len(self.photos):
            return
        photo = self.photos[index]
        item = self.photo_list.item(index)
        if item is None:
            return
        item.setData(Qt.ItemDataRole.UserRole, photo)
        item.setText(f"{photo.source_path.name}\n{photo.status.value}")
        item.setForeground(QColor(STATUS_COLORS[photo.status]))
        item.setToolTip(photo.error or photo.warning or str(photo.source_path))

    def _show_clicked_photo(self, item: QListWidgetItem) -> None:
        self._show_photo(self.photo_list.row(item))

    def _photo_for_row(self, index: int) -> PhotoItem | None:
        """Return the canonical model for a row and repair stale row data."""

        if not 0 <= index < len(self.photos):
            return None
        list_item = self.photo_list.item(index)
        if list_item is not None:
            linked = list_item.data(Qt.ItemDataRole.UserRole)
            if isinstance(linked, PhotoItem):
                if linked is not self.photos[index]:
                    LOGGER.warning("Sidebar model reference was stale at row=%s; restoring canonical model", index)
                    list_item.setData(Qt.ItemDataRole.UserRole, self.photos[index])
                else:
                    return linked
        return self.photos[index]

    @staticmethod
    def _crop_placeholder(photo: PhotoItem) -> str:
        if photo.status == PhotoStatus.PENDING:
            return "Analyze this image to create a crop."
        if photo.status == PhotoStatus.NEEDS_REVIEW and photo.crop_rect is None:
            return "No face detected — draw a face box in the original preview."
        if photo.status == PhotoStatus.SKIPPED:
            return "This image is skipped."
        if photo.status == PhotoStatus.ERROR:
            return "A crop is unavailable because analysis failed."
        if photo.status == PhotoStatus.PROCESSED:
            return "This image has already been processed."
        return "Crop preview"

    def _show_photo(self, index: int) -> None:
        """Load the selected photo into both previews and update actions."""

        if not 0 <= index < len(self.photos):
            self.original_preview.set_content(None)
            self.cropped_preview.set_content(None, None)
            LOGGER.info("Preview cleared: selected_row=%s", index)
            return
        photo = self._photo_for_row(index)
        if photo is None:
            return
        source_exists = photo.source_path.exists()
        selected_face = photo.selected_face
        LOGGER.info(
            "Preview refresh: row=%s filename=%s path=%s exists=%s status=%s faces=%s "
            "selected_face_index=%s selected_face_rect=%s crop_rect=%s",
            index,
            photo.source_path.name,
            photo.source_path,
            source_exists,
            photo.status.value,
            len(photo.faces),
            photo.selected_face_index,
            selected_face.rect.as_int_tuple() if selected_face else None,
            photo.crop_rect.as_int_tuple() if photo.crop_rect else None,
        )
        original_loaded = self.original_preview.set_content(
            photo.source_path,
            photo.faces,
            photo.selected_face_index,
            photo.crop_rect,
        )
        crop_loaded = self.cropped_preview.set_content(
            photo.source_path,
            photo.crop_rect,
            self._crop_placeholder(photo),
        )
        LOGGER.info(
            "Preview result: row=%s image_loaded=%s oriented_size=%sx%s original_qimage_created=%s "
            "crop_qimage_created=%s original_widget_received=%s crop_widget_received=%s",
            index,
            original_loaded,
            self.original_preview._image.width(),
            self.original_preview._image.height(),
            original_loaded,
            not self.cropped_preview._image.isNull(),
            self.original_preview.has_image,
            crop_loaded,
        )
        message = photo.status.value
        if photo.status == PhotoStatus.MULTIPLE:
            message += " — click a numbered face box to choose the subject."
        elif photo.status == PhotoStatus.NEEDS_REVIEW:
            message += " — drag a box around the face, then approve the crop."
        if photo.warning:
            message += f"  {photo.warning}"
        if photo.error:
            message += f"  {photo.error}"
        if self.original_preview.load_error:
            message += f"  Could not load preview: {self.original_preview.load_error}"
        self.status_banner.setText(message)
        enabled = photo.crop_rect is not None and photo.status not in {PhotoStatus.PROCESSED, PhotoStatus.ERROR}
        self.approve_button.setEnabled(enabled)
        self.reset_button.setEnabled(photo.selected_face is not None)
        self.skip_button.setEnabled(photo.status != PhotoStatus.PROCESSED)

    def _calculate_photo_crop(self, photo: PhotoItem) -> None:
        """Calculate and store the automatic crop for one selected face."""

        face = photo.selected_face
        if not face or not photo.image_size:
            photo.crop_rect = None
            return
        try:
            photo.crop_rect = calculate_crop(
                photo.image_size,
                face.rect,
                self.settings.aspect_ratio,
                target_face_fraction=self.settings.face_fraction,
                headroom_fraction=self.settings.headroom_fraction,
                allow_padding=self.settings.allow_padding,
                head_extension_fraction=self.settings.head_extension_fraction,
            )
            photo.manually_adjusted = False
        except Exception as exc:
            photo.crop_rect = None
            photo.status = PhotoStatus.NEEDS_REVIEW
            photo.warning = str(exc)

    def _analyze(self) -> None:
        """Reset analysis state and start the background detection worker."""

        if not self.photos:
            QMessageBox.information(self, "No photos", "Select photos or a folder first.")
            return
        if self.analysis_thread and self.analysis_thread.isRunning():
            return
        self.settings = self._read_settings()
        for index, photo in enumerate(self.photos):
            photo.status = PhotoStatus.PENDING
            photo.error = ""
            photo.warning = ""
            photo.faces.clear()
            photo.selected_face_index = None
            photo.crop_rect = None
            self._refresh_list_item(index)
        self._set_busy(True)
        self.analysis_thread = AnalysisThread([photo.source_path for photo in self.photos], replace(self.settings))
        self.analysis_thread.item_analyzed.connect(self._analysis_item_ready)
        self.analysis_thread.progress_changed.connect(self._progress_changed)
        self.analysis_thread.analysis_finished.connect(self._analysis_done)
        self.analysis_thread.start()

    def _analysis_item_ready(self, index: int, image_size: object, faces: object, error: str) -> None:
        """Apply one worker result to its photo model and refresh the UI."""

        photo = self.photos[index]
        if error:
            photo.status = PhotoStatus.ERROR
            photo.error = "The image could not be analyzed. See the log for technical details."
        else:
            photo.image_size = image_size  # type: ignore[assignment]
            photo.faces = list(faces)  # type: ignore[arg-type]
            if not photo.faces:
                photo.status = PhotoStatus.NEEDS_REVIEW
                photo.warning = "No face was detected. Draw a face reference box in the original preview."
            else:
                photo.selected_face_index = select_primary_face(photo.faces)
                photo.status = PhotoStatus.MULTIPLE if len(photo.faces) > 1 else PhotoStatus.READY
                if len(photo.faces) > 1:
                    photo.warning = f"{len(photo.faces)} faces found; the largest is selected."
                self._calculate_photo_crop(photo)
        self._refresh_list_item(index)
        if self.photo_list.currentRow() == index:
            self._show_photo(index)
        self._update_counts()

    def _analysis_done(self, cancelled: bool) -> None:
        """Restore idle controls and enter crop review after analysis."""

        self._set_busy(False)
        self.status_banner.setText("Analysis cancelled." if cancelled else "Analysis complete. Review any warnings, or crop and save.")
        if self.photo_list.currentRow() < 0 and self.photos:
            self.photo_list.setCurrentRow(0)
        if not cancelled:
            self._review_crops()
        else:
            self._show_photo(self.photo_list.currentRow())
        self.analysis_thread = None

    def _select_face(self, face_index: int) -> None:
        """Select a detected face and recalculate the current crop."""

        row = self.photo_list.currentRow()
        if not 0 <= row < len(self.photos):
            return
        photo = self.photos[row]
        photo.selected_face_index = face_index
        self._calculate_photo_crop(photo)
        photo.manually_adjusted = True
        self._show_photo(row)

    def _create_manual_face(self, rect: Rect) -> None:
        """Use a user-drawn reference box when automatic detection failed."""

        row = self.photo_list.currentRow()
        if not 0 <= row < len(self.photos):
            return
        photo = self.photos[row]
        photo.faces = [DetectedFace(rect, 1.0)]
        photo.selected_face_index = 0
        photo.status = PhotoStatus.NEEDS_REVIEW
        photo.warning = "Manual face reference created. Approve the crop when it looks right."
        self._calculate_photo_crop(photo)
        photo.manually_adjusted = True
        self._refresh_list_item(row)
        self._show_photo(row)

    def _edit_crop(self, proposed: Rect) -> None:
        """Constrain an interactive crop edit while preserving aspect ratio."""

        row = self.photo_list.currentRow()
        if not 0 <= row < len(self.photos):
            return
        photo = self.photos[row]
        if not photo.image_size or not photo.crop_rect:
            return
        image_width, image_height = photo.image_size
        if abs(proposed.width - photo.crop_rect.width) > 0.1:
            width = max(20.0, proposed.width)
            height = width / self.settings.aspect_ratio
            fit = min(1.0, image_width / width, image_height / height)
            width *= fit
            height *= fit
            x = clamp(proposed.x, 0, image_width - width)
            y = clamp(proposed.y, 0, image_height - height)
        else:
            width, height = proposed.width, proposed.height
            x = clamp(proposed.x, 0, max(0.0, image_width - width))
            y = clamp(proposed.y, 0, max(0.0, image_height - height))
        photo.crop_rect = Rect(x, y, width, height)
        photo.manually_adjusted = True
        self.original_preview.set_crop(photo.crop_rect)
        self.cropped_preview.set_crop(photo.crop_rect)

    def _reset_current_crop(self) -> None:
        row = self.photo_list.currentRow()
        if 0 <= row < len(self.photos):
            self._calculate_photo_crop(self.photos[row])
            self._show_photo(row)

    def _approve_current(self) -> None:
        row = self.photo_list.currentRow()
        if 0 <= row < len(self.photos) and self.photos[row].crop_rect:
            self.photos[row].status = PhotoStatus.APPROVED
            self._refresh_list_item(row)
            self._update_counts()
            self._advance_to_review_item(row)

    def _skip_current(self) -> None:
        row = self.photo_list.currentRow()
        if 0 <= row < len(self.photos):
            self.photos[row].status = PhotoStatus.SKIPPED
            self._refresh_list_item(row)
            self._update_counts()
            self._advance_to_review_item(row)

    def _advance_to_review_item(self, after: int = -1) -> None:
        """Select the next photo whose crop still merits review."""

        review_statuses = {PhotoStatus.MULTIPLE, PhotoStatus.NEEDS_REVIEW, PhotoStatus.READY}
        for offset in range(1, len(self.photos) + 1):
            index = (after + offset) % len(self.photos)
            if self.photos[index].status in review_statuses:
                self.photo_list.setCurrentRow(index)
                self.photo_list.scrollToItem(self.photo_list.item(index))
                self._show_photo(index)
                return

    def _review_crops(self) -> None:
        """Navigate to the most relevant crop-review row and refresh it."""

        if not self.photos:
            return
        review_statuses = {PhotoStatus.READY, PhotoStatus.MULTIPLE, PhotoStatus.NEEDS_REVIEW}
        index = next((row for row, photo in enumerate(self.photos) if photo.status in review_statuses), None)
        if index is None:
            index = next((row for row, photo in enumerate(self.photos) if photo.status == PhotoStatus.APPROVED), None)
        if index is None:
            index = self.photo_list.currentRow() if self.photo_list.currentRow() >= 0 else 0
        self.photo_list.setCurrentRow(index)
        item = self.photo_list.item(index)
        if item is not None:
            self.photo_list.scrollToItem(item)
        # setCurrentRow is a no-op when this row is already selected.
        self._show_photo(index)

    def _browse_output(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", self.output_edit.text())
        if folder:
            self.output_folder = Path(folder)
            self.output_edit.setText(folder)

    def _crop_and_save(self) -> None:
        """Validate output, prepare collision-safe jobs, and start processing."""

        if self.processing_thread and self.processing_thread.isRunning():
            return
        self.settings = self._read_settings()
        if not self.photos:
            QMessageBox.information(self, "No photos", "Select and analyze some photos first.")
            return
        folder_text = self.output_edit.text().strip()
        if folder_text:
            output_folder = Path(folder_text).expanduser()
        else:
            output_folder = default_output_folder(self.photos[0].source_path)
            self.output_edit.setText(str(output_folder))
        try:
            output_folder.mkdir(parents=True, exist_ok=True)
            probe = output_folder / ".portrait_cropper_write_test"
            probe.touch()
            probe.unlink()
        except Exception:
            LOGGER.exception("Output folder is unavailable: %s", output_folder)
            QMessageBox.critical(self, "Output folder unavailable", "Choose a folder where you have permission to save files.")
            return
        self.output_folder = output_folder

        allowed = {PhotoStatus.READY, PhotoStatus.MULTIPLE, PhotoStatus.APPROVED} if self.settings.auto_process_all else {PhotoStatus.APPROVED}
        jobs: list[tuple[int, Path, Path, Rect]] = []
        reserved_destinations: set[Path] = set()
        for index, photo in enumerate(self.photos):
            if photo.status in allowed and photo.crop_rect:
                # Reserve each proposed path immediately so same-name sources
                # cannot collide before the worker creates files on disk.
                destination = build_output_path(
                    photo.source_path,
                    output_folder,
                    self.settings,
                    len(jobs) + 1,
                    reserved_destinations,
                )
                reserved_destinations.add(destination)
                jobs.append((index, photo.source_path, destination, photo.crop_rect))
        if not jobs:
            message = "No ready crops are available." if self.settings.auto_process_all else "Approve at least one crop first."
            QMessageBox.information(self, "Nothing to process", message)
            return
        self._set_busy(True)
        self.processing_thread = ProcessingThread(jobs, replace(self.settings))
        self.processing_thread.item_processed.connect(self._processing_item_ready)
        self.processing_thread.progress_changed.connect(self._progress_changed)
        self.processing_thread.processing_finished.connect(self._processing_done)
        self.processing_thread.start()

    def _processing_item_ready(self, index: int, destination: object, error: str) -> None:
        """Apply one processing result to its photo model and sidebar row."""

        photo = self.photos[index]
        if error:
            photo.status = PhotoStatus.ERROR
            photo.error = error
        else:
            photo.status = PhotoStatus.PROCESSED
            photo.output_path = Path(destination)  # type: ignore[arg-type]
        self._refresh_list_item(index)
        if self.photo_list.currentRow() == index:
            self._show_photo(index)
        self._update_counts()

    def _processing_done(self, cancelled: bool) -> None:
        """Restore idle controls and show results after batch processing."""

        self._set_busy(False)
        self.processing_thread = None
        self.open_button.setEnabled(bool(self.output_folder and self.output_folder.exists()))
        if cancelled:
            self.status_banner.setText("Processing cancelled. Completed files were kept.")
        else:
            self.status_banner.setText("Finished. Your cropped portraits are ready.")
            self._show_report()

    def _show_report(self) -> None:
        processed = sum(photo.status == PhotoStatus.PROCESSED for photo in self.photos)
        skipped = sum(photo.status == PhotoStatus.SKIPPED for photo in self.photos)
        multiple = sum(len(photo.faces) > 1 for photo in self.photos)
        review = sum(photo.status == PhotoStatus.NEEDS_REVIEW for photo in self.photos)
        errors = sum(photo.status == PhotoStatus.ERROR for photo in self.photos)
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Processing report")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText("Portrait processing is complete")
        dialog.setInformativeText(
            f"Total images: {len(self.photos)}\nSuccessfully cropped: {processed}\nSkipped: {skipped}\n"
            f"Multiple-face images: {multiple}\nRequiring manual review: {review}\nFailed: {errors}\n\n"
            f"Output folder: {self.output_folder}"
        )
        export_button = dialog.addButton("Export CSV Report…", QMessageBox.ButtonRole.ActionRole)
        open_button = dialog.addButton("Open Output Folder", QMessageBox.ButtonRole.ActionRole)
        dialog.addButton(QMessageBox.StandardButton.Close)
        dialog.exec()
        if dialog.clickedButton() == export_button:
            self._export_report()
        elif dialog.clickedButton() == open_button:
            self._open_output_folder()

    def _export_report(self) -> None:
        suggested = str((self.output_folder or Path.cwd()) / "portrait_cropper_report.csv")
        name, _ = QFileDialog.getSaveFileName(self, "Export CSV report", suggested, "CSV files (*.csv)")
        if not name:
            return
        try:
            export_csv(self.photos, Path(name))
            self.status_banner.setText(f"Report saved to {name}")
        except Exception:
            LOGGER.exception("Could not export report")
            QMessageBox.critical(self, "Could not export report", "The CSV report could not be saved to that location.")

    def _open_output_folder(self) -> None:
        if self.output_folder and self.output_folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.output_folder)))

    def _progress_changed(self, value: int, filename: str) -> None:
        self.progress.setValue(value)
        self.current_file_label.setText(filename)

    def _set_busy(self, busy: bool) -> None:
        for widget in (self.select_photos_button, self.select_folder_button, self.analyze_button, self.save_button):
            widget.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.start_new_batch_button.setEnabled(not busy and bool(self.photos))
        if busy:
            self.progress.setValue(0)

    def _cancel_work(self) -> None:
        """Request cancellation from any active worker thread."""

        if self.analysis_thread and self.analysis_thread.isRunning():
            self.analysis_thread.cancel()
        if self.processing_thread and self.processing_thread.isRunning():
            self.processing_thread.cancel()
        self.current_file_label.setText("Cancelling after the current photo…")

    def _update_counts(self) -> None:
        if not self.photos:
            self.counts_label.setText("No photos selected")
            return
        completed = sum(photo.status == PhotoStatus.PROCESSED for photo in self.photos)
        skipped = sum(photo.status == PhotoStatus.SKIPPED for photo in self.photos)
        multiple = sum(photo.status == PhotoStatus.MULTIPLE for photo in self.photos)
        review = sum(photo.status == PhotoStatus.NEEDS_REVIEW for photo in self.photos)
        errors = sum(photo.status == PhotoStatus.ERROR for photo in self.photos)
        self.counts_label.setText(
            f"{len(self.photos)} total  •  {completed} completed  •  {skipped} skipped\n"
            f"{multiple} multiple faces  •  {review} need review  •  {errors} errors"
        )

    def closeEvent(self, event: object) -> None:  # noqa: N802
        """Confirm cancellation before closing while background work is active."""

        active = (self.analysis_thread and self.analysis_thread.isRunning()) or (self.processing_thread and self.processing_thread.isRunning())
        if active:
            answer = QMessageBox.question(self, "Work in progress", "Cancel the current work and close the app?")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()  # type: ignore[attr-defined]
                return
            self._cancel_work()
            if self.analysis_thread:
                self.analysis_thread.wait(3000)
            if self.processing_thread:
                self.processing_thread.wait(3000)
        event.accept()  # type: ignore[attr-defined]
