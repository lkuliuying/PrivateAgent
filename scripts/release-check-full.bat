@echo off
REM Release gate 2.0 (full evidence pipeline). Run from anywhere; project root
REM is derived from this script's location. Chains pytest / ruff / compileall /
REM npm build+test / e2e / cargo check+test / sidecar smoke / alembic current /
REM git diff / diagnostic redaction / Compose config / latest.json validation,
REM writing dist/release-check-<version>.json + .md. Exits non-zero if any
REM non-skipped step fails. Quick check: scripts/release-check.bat.
setlocal
set "PROJECT_ROOT=%~dp0.."
cd /d "%PROJECT_ROOT%"
call "%~dp0_find-uv.bat" >nul 2>&1
if errorlevel 1 (
    echo [release-check-full] uv not found
    exit /b 1
)
"%UV_EXE%" run python "%~dp0run_release_checks.py" %*
exit /b %errorlevel%