@echo off
REM Opt-in real Ollama/MySQL/Chroma endurance and large-document stress harness.
setlocal
set "PROJECT_ROOT=%~dp0.."
cd /d "%PROJECT_ROOT%"
call "%~dp0_find-uv.bat" >nul 2>&1
if errorlevel 1 (
    echo [stress] uv not found
    exit /b 1
)
"%UV_EXE%" run python "%~dp0stress_process_supervisor.py" %*
exit /b %errorlevel%
