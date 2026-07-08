@echo off
REM Package Python backend as a Tauri sidecar binary (PyInstaller onefile).
REM Run from anywhere; project root is derived from this script's location.
REM Output: apps/desktop/src-tauri/binaries/personal-assistant-server-x86_64-pc-windows-msvc.exe
setlocal

REM Derive project root from script location (this script lives in scripts/).
set "PROJECT_ROOT=%~dp0.."
cd /d "%PROJECT_ROOT%"
set "PROJECT_ROOT=%CD%"

REM Python 3.13 on Windows: force UTF-8 so PyInstaller/chromadb don't trip on GBK.
set "PYTHONUTF8=1"

REM Locate uv (PATH first, then winget install path).
call "%~dp0_find-uv.bat"
if errorlevel 1 exit /b 1

echo === [1/2] PyInstaller ===
"%UV_EXE%" run pyinstaller personal_assistant.spec --noconfirm
if errorlevel 1 (
    echo [build-sidecar] pyinstaller failed
    exit /b 1
)

echo === [2/2] Copy artifact to Tauri binaries ===
set "OUT=%PROJECT_ROOT%\apps\desktop\src-tauri\binaries\personal-assistant-server-x86_64-pc-windows-msvc.exe"
copy /Y "dist\personal-assistant-server.exe" "%OUT%" >nul
if errorlevel 1 (
    echo [build-sidecar] copy failed
    exit /b 1
)

echo === Done: %OUT% ===
endlocal
