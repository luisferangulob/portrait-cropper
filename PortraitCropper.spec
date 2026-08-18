# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for a self-contained Portrait Cropper application."""

from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

project_dir = Path(SPECPATH).resolve()
datas = collect_data_files("cv2")
datas += [
    (str(project_dir / "assets" / "app_icon.svg"), "assets"),
    (str(project_dir / "assets" / "models" / "face_detection_yunet.onnx"), "assets/models"),
    (str(project_dir / "assets" / "models" / "YUNET_LICENSE.txt"), "assets/models"),
    (str(project_dir / "example_config.json"), "."),
]
binaries = collect_dynamic_libs("cv2")

a = Analysis(
    [str(project_dir / "main.py")],
    pathex=[str(project_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=["PIL._tkinter_finder"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Portrait Cropper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Portrait Cropper",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Portrait Cropper.app",
        icon=None,
        bundle_identifier="com.luisangulo.portraitcropper",
        version="1.0.1",
        info_plist={
            "CFBundleShortVersionString": "1.0.1",
            "CFBundleVersion": "1.0.1",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "Portrait Cropper",
        },
    )
