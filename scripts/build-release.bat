@echo off
REM Build the Windows NSIS installer. Run from anywhere; project root is derived
REM from this script's location.
REM Flow: build sidecar -> setup MSVC -> updater signing -> tauri build ->
REM Authenticode sign/verify -> release manifest.
REM Production (fail-closed): scripts\build-release.bat --production
REM   Requires TAURI_SIGNING_PRIVATE_KEY + TAURI_SIGNING_PRIVATE_KEY_PASSWORD and
REM   PA_CODESIGN_THUMBPRINT, or PA_CODESIGN_PFX + PA_CODESIGN_PASSWORD.
REM   Production passwords come only from the process environment.
REM Output: apps\desktop\src-tauri\target\release\bundle\nsis\*.exe (+ *.sig if signed).
REM
REM Optional updater signing: private key at %USERPROFILE%\.tauri\personal-assistant.key
REM   (generated via: npx tauri signer generate -w ^<path^>). See docs/signing-and-keys.md.
REM   If the key has a password, place it at %USERPROFILE%\.tauri\personal-assistant.key.pwd,
REM   otherwise tauri build will prompt interactively (blocks automated builds).
REM
REM GitHub reachability: the first `tauri build` downloads the NSIS toolchain from GitHub.
REM   If GitHub is unreachable, set HTTPS_PROXY before running this script, e.g.
REM     set HTTPS_PROXY=http://127.0.0.1:10808
setlocal
set "PA_PRODUCTION=0"
if /i "%~1"=="--production" set "PA_PRODUCTION=1"
if /i "%PA_RELEASE_MODE%"=="production" set "PA_PRODUCTION=1"

if "%PA_PRODUCTION%"=="1" (
    set "PA_REQUIRE_CODESIGN=1"
    echo [build-release] production mode: signing and verification gates are REQUIRED
) else (
    echo [build-release] development mode: unsigned artifacts must not be published
)

REM Derive project root from script location.
set "PROJECT_ROOT=%~dp0.."
cd /d "%PROJECT_ROOT%"
set "PROJECT_ROOT=%CD%"
set "SCRIPTS_DIR=%~dp0"

echo === [1/5] Build sidecar (PyInstaller) ===
call "%SCRIPTS_DIR%build-sidecar.bat"
if errorlevel 1 (
    echo [build-release] sidecar build failed
    exit /b 1
)

echo === [2/5] Setup MSVC environment ===
call "%SCRIPTS_DIR%_find-msvc.bat"
if errorlevel 1 exit /b 1
call "%VCVARS%" >nul 2>&1
if errorlevel 1 (
    echo [build-release] vcvars64.bat failed
    exit /b 1
)
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

echo === [3/5] Updater signing key ===
if defined TAURI_SIGNING_PRIVATE_KEY (
    echo [INFO] Updater signing key provided by the process environment
) else if "%PA_PRODUCTION%"=="1" (
    echo [build-release] TAURI_SIGNING_PRIVATE_KEY is required in production
    exit /b 1
) else if exist "%USERPROFILE%\.tauri\personal-assistant.key" (
    set /p TAURI_SIGNING_PRIVATE_KEY=<"%USERPROFILE%\.tauri\personal-assistant.key"
    if exist "%USERPROFILE%\.tauri\personal-assistant.key.pwd" set /p TAURI_SIGNING_PRIVATE_KEY_PASSWORD=<"%USERPROFILE%\.tauri\personal-assistant.key.pwd"
    echo [INFO] Development updater key loaded from the local user profile
) else (
    echo [INFO] No updater key; this development artifact cannot be published
)
if "%PA_PRODUCTION%"=="1" if not defined TAURI_SIGNING_PRIVATE_KEY_PASSWORD (
    echo [build-release] TAURI_SIGNING_PRIVATE_KEY_PASSWORD is required in production
    exit /b 1
)
if "%PA_PRODUCTION%"=="1" if not defined PA_CODESIGN_THUMBPRINT if not defined PA_CODESIGN_PFX (
    echo [build-release] PA_CODESIGN_THUMBPRINT or PA_CODESIGN_PFX is required in production
    exit /b 1
)
if "%PA_PRODUCTION%"=="1" if not defined PA_CODESIGN_EXPECTED_SUBJECT (
    echo [build-release] PA_CODESIGN_EXPECTED_SUBJECT is required in production
    exit /b 1
)

echo === [4/5] tauri build (NSIS) ===
REM Remove stale NSIS installers so version-match selection in generate-latest-json.py /
REM generate_release_manifest.py can never pick an old build across a digit boundary
REM (e.g. 0.1.9 vs 0.1.10). tauri build writes the new versioned filename fresh.
del /q "apps\desktop\src-tauri\target\release\bundle\nsis\*-setup.exe" >nul 2>&1
del /q "apps\desktop\src-tauri\target\release\bundle\nsis\*-setup.exe.sig" >nul 2>&1
pushd apps\desktop
REM npm is a .cmd shim on Windows; CALL is required or this parent batch exits
REM immediately after npm finishes and skips code-signing/manifest steps.
call npm run tauri build
if errorlevel 1 (
    popd
    echo [build-release] tauri build failed
    exit /b 1
)
popd

echo === [4.5/5] Code signing (Authenticode) ===
REM Certificate config: PA_CODESIGN_THUMBPRINT, or PA_CODESIGN_PFX +
REM PA_CODESIGN_PASSWORD. Production rejects password files and unsigned output.
call "%SCRIPTS_DIR%_find-uv.bat" >nul 2>&1
if errorlevel 1 (
    if "%PA_PRODUCTION%"=="1" (
        echo [build-release] uv is required for production code signing
        exit /b 1
    )
    echo [INFO] uv not found; skipping development-only code signing
) else (
    if "%PA_PRODUCTION%"=="1" (
        "%UV_EXE%" run python "%SCRIPTS_DIR%sign_installer.py" --require-signing
    ) else (
        "%UV_EXE%" run python "%SCRIPTS_DIR%sign_installer.py"
    )
    if errorlevel 1 (
        echo [build-release] code signing failed
        exit /b 1
    )
)

echo === [5/5] Release manifest ===
call "%SCRIPTS_DIR%_find-uv.bat" >nul 2>&1
if errorlevel 1 (
    if "%PA_PRODUCTION%"=="1" (
        echo [build-release] uv is required for the production release manifest
        exit /b 1
    )
    echo [INFO] uv not found; skipping development release manifest generation
) else (
    "%UV_EXE%" run python "%SCRIPTS_DIR%generate_release_manifest.py" --write
    if errorlevel 1 (
        if "%PA_PRODUCTION%"=="1" (
            echo [build-release] manifest generation failed
            exit /b 1
        )
        echo [build-release] manifest generation failed ^(development-only non-fatal^)
    )
)

echo.
echo === Done ===
echo Output: apps\desktop\src-tauri\target\release\bundle\nsis\
echo   *.exe                   NSIS installer
if defined TAURI_SIGNING_PRIVATE_KEY echo   *.exe.sig                Update signature
echo   dist\release-manifest-*.md  release manifest (when uv available)
echo Next: generate latest.json with scripts\generate-latest-json.py, then upload to GitHub Release.
endlocal
