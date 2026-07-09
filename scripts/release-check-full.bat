@echo off
REM 第八阶段 M2：发布检查 2.0（full evidence pipeline）。
REM 串联 pytest / npm build / npm test / e2e / cargo check / alembic current / git diff /
REM 诊断包脱敏 smoke / latest.json+.sig 校验，输出 dist/release-check-<version>.json + .md。
REM 任一非跳过步骤失败时退出码非 0。quick check 见 scripts/release-check.bat。
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
