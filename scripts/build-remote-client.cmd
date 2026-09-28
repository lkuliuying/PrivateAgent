@echo off
setlocal
call "%~dp0_find-msvc.bat"
if errorlevel 1 exit /b %errorlevel%
call "%VCVARS%" >nul
if errorlevel 1 exit /b %errorlevel%
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
node "%~dp0build-remote-client.cjs" %*
exit /b %errorlevel%
