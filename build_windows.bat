@echo off
setlocal
cd /d "%~dp0"

py -3 -m venv .venv-build
if errorlevel 1 goto :error
call .venv-build\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
if errorlevel 1 goto :error
python -m unittest discover -s tests -v
if errorlevel 1 goto :error
python -m PyInstaller --noconfirm --clean PortraitCropper.spec
if errorlevel 1 goto :error

echo Build complete: dist\Portrait Cropper\Portrait Cropper.exe
echo Zip the entire "dist\Portrait Cropper" folder for distribution.
exit /b 0

:error
echo Build failed. Review the messages above.
exit /b 1
