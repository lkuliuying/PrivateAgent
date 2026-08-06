@echo off
REM Tauri Rust 单元测试（需 MSVC 环境）。项目根执行。
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
set PATH=%USERPROFILE%\.cargo\bin;%PATH%
cd /d "F:\Program\Agent\apps\desktop\src-tauri"
echo === cargo test (tauri) ===
cargo test --message-format=short
echo === cargo test exit %ERRORLEVEL% ===