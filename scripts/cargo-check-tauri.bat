@echo off
REM Tauri Rust formatting, compile, and unit-test gate. Requires MSVC.
setlocal
set "PROJECT_ROOT=%~dp0.."

call "%~dp0_find-msvc.bat"
if errorlevel 1 exit /b 1
call "%VCVARS%" >nul 2>&1
if errorlevel 1 exit /b 1

set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
pushd "%PROJECT_ROOT%\apps\desktop\src-tauri"
if errorlevel 1 exit /b 1

echo === cargo fmt check (tauri) ===
cargo fmt -- --check
if errorlevel 1 goto :failed

echo === cargo check (tauri) ===
cargo check --message-format=short
if errorlevel 1 goto :failed

echo === cargo test --lib (tauri) ===
cargo test --lib --message-format=short
if errorlevel 1 goto :failed

set "CARGO_EXIT=0"
goto :done

:failed
set "CARGO_EXIT=%ERRORLEVEL%"

:done
echo === tauri rust checks exit %CARGO_EXIT% ===
popd

endlocal & exit /b %CARGO_EXIT%
