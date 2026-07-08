@echo off
REM Locate the uv executable. Sets UV_EXE on success; exits 1 if not found.
REM Called by build-sidecar.bat / build-release.bat / release-check.bat.
REM Search order: 1) uv on PATH (where uv)  2) winget default install path.
set "UV_EXE="

REM 1) uv reachable on PATH
for /f "delims=" %%i in ('where uv 2^>nul') do (
    set "UV_EXE=%%i"
    goto :uv_found
)

REM 2) winget default install path (uv installed via `winget install astral-sh.uv`)
set "UV_WINGET=%USERPROFILE%\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe"
if exist "%UV_WINGET%" set "UV_EXE=%UV_WINGET%"

:uv_found
if not defined UV_EXE (
    echo [ERROR] uv not found on PATH or in the winget install path.
    echo         Install uv:  winget install --id astral-sh.uv -e
    echo         See README "依赖准备" section.
    exit /b 1
)
exit /b 0
