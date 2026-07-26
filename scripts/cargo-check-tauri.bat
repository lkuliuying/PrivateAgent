@echo off
REM Tauri Rust compile check. Requires the MSVC toolchain.
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
set PATH=%USERPROFILE%\.cargo\bin;%PATH%
cd /d "F:\Program\Agent\apps\desktop\src-tauri"
echo === cargo check (tauri) ===
cargo check --message-format=short
set "CARGO_EXIT=%ERRORLEVEL%"
echo === cargo check exit %CARGO_EXIT% ===
exit /b %CARGO_EXIT%
