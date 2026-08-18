#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

python3 -m venv .venv-build
source .venv-build/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m PyInstaller --noconfirm --clean PortraitCropper.spec

APP_BUNDLE="dist/Portrait Cropper.app"
if [[ -d "$APP_BUNDLE" ]]; then
    # Finder metadata inherited by nested frameworks can make codesign reject an
    # otherwise valid bundle. Clean, sign, clean metadata added during signing,
    # then verify the distributable tree.
    xattr -cr "$APP_BUNDLE"
    codesign --force --deep --sign - --timestamp=none "$APP_BUNDLE"
    xattr -cr "$APP_BUNDLE"
    codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE"
fi

echo "Build complete: dist/Portrait Cropper.app"
echo "Test it on a clean Mac before distribution. Sign and notarize for public sharing."
