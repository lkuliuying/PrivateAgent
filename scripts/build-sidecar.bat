@echo off
REM Package Python backend as Tauri sidecar binary. Run from project root.
REM Output copied to apps/desktop/src-tauri/binaries/ with target-triple suffix (Tauri externalBin).
setlocal
cd /d "F:\Program\Agent"
set PYTHONUTF8=1
set UV=%USERPROFILE%\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe

echo === [1/2] PyInstaller ===
"%UV%" run pyinstaller personal_assistant.spec --noconfirm
if errorlevel 1 (
    echo [build-sidecar] pyinstaller failed
    exit /b 1
)

echo === [2/2] Copy artifact to Tauri binaries ===
set OUT=apps\desktop\src-tauri\binaries\personal-assistant-server-x86_64-pc-windows-msvc.exe
copy /Y dist\personal-assistant-server.exe "%OUT%" >nul
if errorlevel 1 (
    echo [build-sidecar] copy failed
    exit /b 1
)

echo === Done: %OUT% ===
endlocal
