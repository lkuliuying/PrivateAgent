@echo off
REM Pre-release verification. Run from anywhere; project root is derived from
REM this script's location. Runs pytest, frontend build, the full Rust gate, and
REM alembic current. Exits non-zero if any mandatory step fails.
setlocal

set "PROJECT_ROOT=%~dp0.."
cd /d "%PROJECT_ROOT%"
set "SCRIPTS_DIR=%~dp0"
set "FAIL=0"

call "%SCRIPTS_DIR%_find-uv.bat"
if errorlevel 1 exit /b 1

echo === [1/4] pytest -q ===
"%UV_EXE%" run pytest -q
if errorlevel 1 (echo [release-check] FAIL pytest & set "FAIL=1") else echo [release-check] OK pytest

echo === [2/4] npm run build (frontend) ===
pushd apps\desktop
call npm run build
set "NPM_RC=%ERRORLEVEL%"
popd
if "%NPM_RC%"=="0" (echo [release-check] OK npm build) else (echo [release-check] FAIL npm build & set "FAIL=1")

echo === [3/4] Tauri Rust gate (fmt/check/test; needs MSVC) ===
call "%SCRIPTS_DIR%cargo-check-tauri.bat"
if errorlevel 1 (echo [release-check] FAIL Tauri Rust gate & set "FAIL=1") else echo [release-check] OK Tauri Rust gate

echo === [4/4] alembic current ===
"%UV_EXE%" run alembic current
if errorlevel 1 (echo [release-check] FAIL alembic current & set "FAIL=1") else echo [release-check] OK alembic current

echo.
if "%FAIL%"=="1" (
    echo === release-check: FAILED -- see above ===
    exit /b 1
)
echo === release-check: ALL PASSED ===
endlocal
