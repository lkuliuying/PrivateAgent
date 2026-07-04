@echo off
REM 打包 Python 后端为 Tauri sidecar 二进制。项目根执行。
REM 产物复制到 apps/desktop/src-tauri/binaries/，文件名带 target triple 后缀（Tauri externalBin 要求）。
setlocal
cd /d "F:\Program\Agent"
set PYTHONUTF8=1
set UV=%USERPROFILE%\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe

echo === [1/2] PyInstaller 打包 ===
"%UV%" run pyinstaller personal_assistant.spec --noconfirm
if errorlevel 1 (
    echo [build-sidecar] pyinstaller 失败
    exit /b 1
)

echo === [2/2] 复制产物到 Tauri binaries ===
set OUT=apps\desktop\src-tauri\binaries\personal-assistant-server-x86_64-pc-windows-msvc.exe
copy /Y dist\personal-assistant-server.exe "%OUT%" >nul
if errorlevel 1 (
    echo [build-sidecar] 复制失败
    exit /b 1
)

echo === 完成: %OUT% ===
endlocal
