@echo off
REM 启动 Tauri 开发模式：设置 MSVC 环境 + cargo PATH，然后 tauri dev。
REM Windows 下 Tauri 编译 Rust 壳需要 MSVC link.exe，故先 call vcvars64.bat。

REM 预清理可能残留的 1420 端口占用（上次 tauri dev 异常退出时 Vite 子进程可能残留）
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":1420" ^| findstr LISTENING') do (
  echo [INFO] killing PID %%a on port 1420
  taskkill /PID %%a /F >nul 2>&1
)

call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if errorlevel 1 (
  echo [ERROR] vcvars64.bat failed
  exit /b 1
)
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
cd /d F:\Program\Agent\apps\desktop
echo [INFO] starting tauri dev...
npm run tauri dev
