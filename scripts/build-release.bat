@echo off
REM Build Windows NSIS installer. Run from project root.
REM Flow: build sidecar -> setup MSVC -> optional updater signing -> tauri build.
REM Output: apps\desktop\src-tauri\target\release\bundle\nsis\*.exe (+ *.sig if signed).
REM
REM Optional updater signing: private key at %USERPROFILE%\.tauri\personal-assistant.key
REM (generated via: npx tauri signer generate -w ^<path^>). See docs/phase5-installer-updater.md.
REM If the key has a password, place it at %USERPROFILE%\.tauri\personal-assistant.key.pwd,
REM otherwise tauri build will prompt interactively (blocks automated builds).
setlocal
cd /d "F:\Program\Agent"

echo === [1/4] Build sidecar (PyInstaller) ===
call scripts\build-sidecar.bat
if errorlevel 1 (
    echo [build-release] sidecar build failed
    exit /b 1
)

echo === [2/4] Setup MSVC environment ===
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
if errorlevel 1 (
    echo [build-release] vcvars64.bat failed
    exit /b 1
)
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

echo === [3/4] Optional updater signing key ===
if exist "%USERPROFILE%\.tauri\personal-assistant.key" (
    set /p TAURI_SIGNING_PRIVATE_KEY=<"%USERPROFILE%\.tauri\personal-assistant.key"
    if exist "%USERPROFILE%\.tauri\personal-assistant.key.pwd" set /p TAURI_SIGNING_PRIVATE_KEY_PASSWORD=<"%USERPROFILE%\.tauri\personal-assistant.key.pwd"
    echo [INFO] Signing key loaded; .sig will be generated
) else (
    echo [INFO] No signing key found; skipping .sig
)

echo === [4/4] tauri build (NSIS) ===
cd apps\desktop
npm run tauri build
if errorlevel 1 (
    echo [build-release] tauri build failed
    exit /b 1
)

echo.
echo === Done ===
echo Output: apps\desktop\src-tauri\target\release\bundle\nsis\
echo   *.exe          NSIS installer
if exist "%USERPROFILE%\.tauri\personal-assistant.key" echo   *.exe.sig       Update signature
endlocal
