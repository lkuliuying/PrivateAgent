@echo off
REM 历史入口统一转到本机客户端构建，所有参数与签名保护由同一脚本处理。
call "%~dp0build-client.cmd" %*
exit /b %ERRORLEVEL%
