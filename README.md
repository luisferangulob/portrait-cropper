# Portrait Cropper

Portrait Cropper is an offline Python desktop application for producing
consistent, face-guided portrait crops from individual images or folders. It
combines automatic local face detection with a review workflow, interactive
crop adjustment, collision-safe output naming, and CSV reporting.

## Demo / Screenshot

The repository reserves [`assets/screenshots/`](assets/screenshots/README.md)
for an approved application screenshot using non-private imagery.

## Key Capabilities

- Imports JPG, JPEG, PNG, TIFF, WebP, and recursively discovered folder images.
- Detects faces locally with YuNet and profile/frontal Haar fallbacks.
- Selects the largest detected face by default while retaining multiple-face
  review and subject selection.
- Calculates configurable aspect-ratio crops with face scale, estimated head
  extension, headroom, and source-boundary correction.
- Supports manual face-box creation, crop movement, crop resizing, and reset to
  the automatic crop.
- Shows original and proposed-crop previews without retaining full images in
  the batch model.
- Processes analysis and output on cancellable Qt worker threads.
- Preserves originals, avoids output collisions, optionally preserves metadata,
  and exports a per-image CSV report.
- Includes source-level PyInstaller configurations for macOS and Windows.

## Application Workflow

1. Select image files, select a folder, or drag local images into the window.
2. Analyze the batch. The application detects faces and proposes a crop for the
   initially selected subject.
3. Review warnings and previews. Choose among multiple faces, draw a reference
   box when detection misses a face, or adjust the proposed crop directly.
4. Approve individual crops when required, or use the default automatic mode to
   process all ready images.
5. Choose an output folder and run **Crop and Save**.
6. Review the summary, open the output folder, or export a CSV report.

## Installation

Python 3.10 or later is recommended.

```bash
git clone https://github.com/luisferangulob/portrait-cropper.git
cd portrait-cropper
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On Windows PowerShell, activate the environment with:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run the Application

From the repository root:

```bash
python main.py
```

To start with a JSON configuration:

```bash
python main.py --config example_config.json
```

The package entry point is equivalent:

```bash
python -m portrait_cropper
```

## Technical Architecture

`MainWindow` coordinates batch models, previews, settings, worker lifecycles,
and user actions. `AnalysisThread` performs sequential offline face detection;
`ProcessingThread` performs crop/save jobs. Pure geometry, file naming, resource
lookup, settings, and reporting remain in focused modules that can be tested
without running the event loop.

See [`docs/architecture.md`](docs/architecture.md) for the module interactions,
data flow, threading boundaries, and packaging model.

## Crop Geometry / Image Processing

The selected detector box defines the crop scale: by default its height occupies
30% of the crop height. The algorithm estimates the head above the detector box
using a 35% face-height extension, then adds headroom equal to 5% of crop height.
Crop width follows the configured width-to-height ratio. Unless optional padding
is enabled, crops that exceed the image are proportionally scaled and shifted
inside oriented source bounds.

Pillow applies EXIF orientation before crop coordinates are used, resizes with
Lanczos resampling, and writes through a temporary file before replacing the
destination. JPEG quality, ICC/EXIF retention, PNG text retention, maximum
output dimensions, and overwrite behavior are configurable.

## Privacy / Offline Processing

All image decoding, face detection, preview rendering, crop calculation, and
output processing occur locally. The source contains no network client and does
not send photographs to an external image or face-detection service.

## Output

The default destination is a `Cropped Portraits` folder beside the selected
source. Originals are not modified. Output filenames can use an `_cropped`
suffix, retain the original base name, use a numeric sequence, or use a custom
prefix; source and batch collisions receive a numeric suffix. JPG/JPEG and PNG
extensions are preserved, while TIFF and WebP sources are written as JPEG.

The optional CSV report contains the original and output filenames, face count,
selected face and crop coordinates, status, and warning/error text. A synthetic
schema example is available in [`sample_report.csv`](sample_report.csv).

## Testing

Install development dependencies and run the complete default suite:

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

The synthetic offscreen GUI workflow tests are opt-in because Qt platform
plugins vary by environment:

```bash
QT_QPA_PLATFORM=offscreen PORTRAIT_CROPPER_GUI_TESTS=1 \
  python -m unittest discover -s tests -v
```

Two real-image detector/preview integration cases remain opt-in through
`PORTRAIT_CROPPER_ANGLED_TEST` and `PORTRAIT_CROPPER_TEST_PORTRAIT`. They are not
required for the deterministic suite and no portrait image is stored in this
repository.

## Packaging

The platform build scripts create `.venv-build`, install development
dependencies, run tests, and invoke `PortraitCropper.spec`:

```bash
./build_macos.sh
```

```bat
build_windows.bat
```

Public macOS distribution requires an appropriate signing and notarization
plan in addition to the source-level build.

## Repository Structure

```text
portrait-cropper/
├── assets/
│   ├── app_icon.svg
│   ├── models/
│   │   ├── YUNET_LICENSE.txt
│   │   └── face_detection_yunet.onnx
│   └── screenshots/
│       └── README.md
├── docs/
│   └── architecture.md
├── portrait_cropper/
│   ├── ui/
│   │   ├── main_window.py
│   │   └── preview_widget.py
│   ├── app.py
│   ├── crop_math.py
│   ├── detector.py
│   ├── file_manager.py
│   ├── image_processing.py
│   ├── logging_setup.py
│   ├── models.py
│   ├── reporting.py
│   ├── resources.py
│   ├── settings.py
│   └── workers.py
├── tests/
├── .gitignore
├── PortraitCropper.spec
├── README.md
├── build_macos.sh
├── build_windows.bat
├── example_config.json
├── main.py
├── requirements-dev.txt
├── requirements.txt
└── sample_report.csv
```

The synthetic CSV example documents the report schema without including user
data.

## Technical Stack

- Python
- PySide6 / Qt
- OpenCV (YuNet and Haar face detection)
- Pillow
- NumPy
- PyInstaller
- `unittest`

## Limitations

- Automatic detection can miss extreme poses, occluded faces, or very small
  subjects; manual face-box creation is the intended fallback.
- Multiple-face images require review when the automatically selected largest
  face is not the intended subject.
- Images with insufficient space around the subject may force a smaller crop or
  require optional padding.
- TIFF and WebP outputs are converted to JPEG rather than retaining their source
  container.
- The included macOS build is not configured for Developer ID signing or Apple
  notarization.

## Author

Luis Angulo
