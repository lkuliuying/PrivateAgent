@echo off
REM Locate vcvars64.bat for Visual Studio 2022 (BuildTools/Community/Professional/Enterprise).
REM Sets VCVARS to the found path on success; exits 1 if not found.
REM Called by build-release.bat / release-check.bat.
REM
REM Deliberately flat: NO multi-line if/for blocks and NO setlocal, so that
REM paths containing "(x86)" (C:\Program Files (x86)\...) never appear inside
REM parenthesised blocks where cmd's block paren-matching would break. VCVARS
REM set here propagates directly to the calling script.
set "VCVARS="

REM Probe common VS 2022 install locations (single-line `if exist ... set`, no blocks).
if not defined VCVARS if exist "%ProgramFiles%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%ProgramFiles%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if not defined VCVARS if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%ProgramFiles(x86)%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
if not defined VCVARS if exist "%ProgramFiles%\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%ProgramFiles%\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not defined VCVARS if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not defined VCVARS if exist "%ProgramFiles%\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%ProgramFiles%\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"
if not defined VCVARS if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"
if not defined VCVARS if exist "%ProgramFiles%\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%ProgramFiles%\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat"
if not defined VCVARS if exist "%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%ProgramFiles(x86)%\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat"

REM Optional: vswhere catches non-standard install locations. Run it only if the
REM explicit probes above missed, and capture its output via a temp file to keep
REM any "(x86)" path out of a for-loop backtick command.
if defined VCVARS goto :found
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" set "VSWHERE=%ProgramFiles%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" goto :notfound
REM Capture vswhere output to a temp file, then read it back -- keeps any "(x86)"
REM path (from the VS install root) out of a for-loop backtick command.
set "VSWHERE_OUT=%TEMP%\_pa_vswhere.txt"
"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath > "%VSWHERE_OUT%" 2>nul
for /f "usebackq delims=" %%i in ("%VSWHERE_OUT%") do if exist "%%i\VC\Auxiliary\Build\vcvars64.bat" set "VCVARS=%%i\VC\Auxiliary\Build\vcvars64.bat"
del "%VSWHERE_OUT%" >nul 2>&1

:found
if not defined VCVARS goto :notfound
exit /b 0

:notfound
echo [ERROR] vcvars64.bat not found (looked for VS 2022 BuildTools/Community/Professional/Enterprise, and vswhere).
echo         Install MSVC Build Tools:
echo         winget install --id Microsoft.VisualStudio.2022.BuildTools --override "--quiet --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
echo         See README "依赖准备" section.
exit /b 1
