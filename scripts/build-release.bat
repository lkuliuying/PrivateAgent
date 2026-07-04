@echo off
REM 一键构建 Windows NSIS 安装包。项目根执行。
REM 流程：打包 sidecar -> 设置 MSVC 环境 -> 可选 updater 签名 -> tauri build。
REM 产物：apps\desktop\src-tauri\target\release\bundle\nsis\*.exe（+ *.sig 若已签名）。
REM
REM 可选 updater 签名：将私钥放到 %USERPROFILE%\.tauri\personal-assistant.key
REM （由 `npm run tauri signer generate -- -w <path>` 生成，见 docs/phase5-installer-updater.md）。
REM 若私钥设了密码，可一并放 %USERPROFILE%\.tauri\personal-assistant.key.pwd，
REM 否则 tauri build 会交互式提示输入密码（自动化构建会卡住）。
setlocal
cd /d "F:\Program\Agent"

echo === [1/4] 打包 sidecar（PyInstaller） ===
call scripts\build-sidecar.bat
if errorlevel 1 (
    echo [build-release] sidecar 打包失败
    exit /b 1
)

echo === [2/4] 设置 MSVC 环境 ===
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
if errorlevel 1 (
    echo [build-release] vcvars64.bat 失败
    exit /b 1
)
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"

echo === [3/4] 可选 updater 签名私钥 ===
if exist "%USERPROFILE%\.tauri\personal-assistant.key" (
    set /p TAURI_SIGNING_PRIVATE_KEY=<"%USERPROFILE%\.tauri\personal-assistant.key"
    if exist "%USERPROFILE%\.tauri\personal-assistant.key.pwd" set /p TAURI_SIGNING_PRIVATE_KEY_PASSWORD=<"%USERPROFILE%\.tauri\personal-assistant.key.pwd"
    echo [INFO] 已加载签名私钥，若 tauri.conf.json 配置 updater 将生成 .sig 更新签名
) else (
    echo [INFO] 未找到签名私钥，跳过更新签名（不生成 .sig）
)

echo === [4/4] tauri build（NSIS 安装包） ===
cd apps\desktop
npm run tauri build
if errorlevel 1 (
    echo [build-release] tauri build 失败
    exit /b 1
)

echo.
echo === 完成 ===
echo 产物目录: apps\desktop\src-tauri\target\release\bundle\nsis\
echo   *.exe          NSIS 安装包（私人助手_<version>_x64-setup.exe）
if exist "%USERPROFILE%\.tauri\personal-assistant.key" echo   *.exe.sig       更新签名（供 updater 校验）
endlocal
