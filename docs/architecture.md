# Architecture

Portrait Cropper is a single-process PySide6 desktop application. The window
owns the current batch state, while face analysis and file output run on Qt
worker threads so image work does not block the interface.

## Application entry and resources

`main.py` and `portrait_cropper.__main__` delegate to
`portrait_cropper.app.main`. The bootstrap configures file logging, creates the
Qt application, optionally loads JSON settings, resolves the application icon,
and opens `MainWindow`. `portrait_cropper.resources` resolves files relative to
the source tree or PyInstaller's temporary bundle root, so the same resource
calls work in development and packaged builds.

## Batch state and settings

`models.py` defines immutable rectangle and face records plus the mutable
`PhotoItem` model used for each imported image. A `PhotoItem` records the source
path, oriented dimensions, detections, current crop, lifecycle status, output
path, and review messages; source pixels are not retained in the batch model.

`settings.py` defines the editable settings and their supported ranges.
Settings can be loaded from or saved to JSON. Unknown JSON keys are ignored and
missing keys use current defaults, which permits compatible configuration files
to survive additions to the settings schema.

## Input and analysis flow

`file_manager.discover_images` expands selected files and folders, filters
supported extensions, resolves duplicates, and returns a stable filename-sorted
list. `MainWindow` creates a `PhotoItem` and sidebar row for every new path and
loads only the selected image into preview widgets.

When analysis starts, `AnalysisThread` creates one `FaceDetector` and processes
the batch sequentially. The detector uses a bounded-resolution, EXIF-oriented
copy of each source. YuNet is attempted first; if it returns no result or its
inference fails, profile and then frontal Haar cascades run locally. Detector
coordinates are scaled back to oriented source-image pixels. Qt signals carry
each result and progress update to the GUI thread, where the model and previews
are updated.

## Crop calculation and review

`crop_math.calculate_crop` derives crop height from the selected detector box
and target face percentage, then derives width from the requested aspect ratio.
It estimates the top of the head by extending above the detector box and adds
headroom as a fraction of total crop height. Unless padding is enabled, an
oversized crop scales proportionally and shifts inside the source bounds.

The largest detected face is selected initially. Multiple detections remain
visible so another subject can be chosen. If detection finds no face, the user
can draw a reference face box. `OriginalPreview` performs transformations
between image and widget coordinates and emits crop edits; `CroppedPreview`
renders the corresponding source rectangle. Crop movement and resizing are
constrained by `MainWindow` before the shared model is updated.

## Processing and output

`file_manager.build_output_path` applies the configured naming mode and avoids
collisions with source files, files already on disk, and destinations reserved
earlier in the batch. `ProcessingThread` processes prepared jobs sequentially.
`image_processing.process_image` applies EXIF orientation, crops and resizes
with Pillow, preserves configured metadata, saves to a temporary file, and
atomically replaces the destination. Originals are never written by the
processing pipeline.

JPEG and PNG inputs retain their extension. TIFF and WebP inputs are written as
JPEG. The GUI can export batch state through `reporting.export_csv`, using a
fixed column schema and UTF-8 encoding suitable for spreadsheet applications.

## Threading and cancellation

Analysis and processing each use a dedicated `QThread`. Work is deliberately
sequential within a thread to bound memory usage. Cancellation sets a flag that
is checked between images, so an in-progress decode, detector call, or save is
allowed to finish. Worker signals communicate results, progress, completion,
and cancellation state; UI widgets are changed only by the main Qt thread.

## Packaging

`PortraitCropper.spec` includes the icon, example configuration, YuNet model,
its upstream license notice, and OpenCV runtime data. Platform scripts create
an isolated build environment, run the test suite, and invoke PyInstaller. The
macOS bundle uses the identifier `com.luisangulo.portraitcropper`.
