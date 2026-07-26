# Windows 签名、密钥与干净机发布门禁

PrivateAgent 使用两套独立签名：Windows Authenticode 证明安装包发布者并参与
SmartScreen/Windows 信任判断；Tauri updater `.sig` 防止更新包被替换。生产发布必须
同时通过两套签名，任何凭据、工具、证书链、时间戳或验证步骤缺失都必须终止构建。

## 1. 生产 Authenticode 配置

证书必须由受信任 CA 签发、包含 Code Signing EKU、当前有效且私钥可访问。推荐将证书
安装到发布机 `Cert:\CurrentUser\My`，按 SHA-1 指纹选择：

```powershell
$env:PA_CODESIGN_THUMBPRINT = '<40 位证书指纹>'
$env:PA_CODESIGN_EXPECTED_SUBJECT = 'CN=<证书中的完整 Subject>'
$env:PA_CODESIGN_TIMESTAMP = 'http://timestamp.digicert.com'
```

CI 可使用 PFX，但 PFX 只写入 runner 的临时目录，密码只能通过进程环境提供：

```powershell
$env:PA_CODESIGN_PFX = "$env:RUNNER_TEMP\private-agent-production.pfx"
$env:PA_CODESIGN_PASSWORD = '<secret environment value>'
$env:PA_CODESIGN_EXPECTED_SUBJECT = 'CN=<证书中的完整 Subject>'
```

`PA_CODESIGN_PASSWORD_FILE` 被明确拒绝。签名工具把 PFX 临时导入当前用户证书库后仅按
指纹调用 SignTool，因此密码不会进入命令行、日志或状态文件；若证书原先不在证书库，
脚本会在结束时删除本次导入的证书。

本地生产预检与构建：

```powershell
uv run python scripts/sign_installer.py --preflight --require-signing
scripts\build-release.bat --production
```

生产入口只从 Windows SDK 目录解析 SignTool，并要求其 Microsoft Authenticode 有效；
PowerShell 固定使用 `%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe`。预检会
拒绝自签证书并在线构建受信证书链，updater 则只调用锁文件安装的本地 Tauri CLI 2.11.4，
不允许 `npx` 下载回退。

生产模式还要求 `TAURI_SIGNING_PRIVATE_KEY` 与
`TAURI_SIGNING_PRIVATE_KEY_PASSWORD` 直接存在于进程环境。它不会读取本地密码文件。

签名顺序不可调整：

1. Tauri 构建 NSIS 安装包。
2. SignTool 使用 SHA-256 和 RFC 3161 时间戳签名安装包。
3. `signtool verify /pa /all /v` 验证 Windows 策略与完整证书链。
4. `Get-AuthenticodeSignature` 再次验证签名状态、预期证书指纹和可信时间戳。
5. 删除旧 `.sig`，重新对 Authenticode 签名后的字节生成 Tauri updater `.sig`。
6. 使用与 Tauri runtime 相同的 `minisign-verify 0.2.5` 算法，把 `.sig` 对安装包字节和
   `tauri.conf.json` 内嵌公钥做实际验签；密钥不匹配会阻断。
7. 生成 release manifest / `latest.json`。

只有第 3–6 步全部通过后，`dist/codesign-status-<version>.json` 才会写入
`code_signed: true`。

## 2. GitHub Actions 机密配置

在仓库创建名为 `windows-production-signing` 的 GitHub Environment，并把以下值配置成
**Environment secrets**（不要使用普通 repository secrets）：

| Secret | 内容 |
|---|---|
| `WINDOWS_CODESIGN_PFX_BASE64` | 生产 PFX 的 Base64 内容 |
| `WINDOWS_CODESIGN_PASSWORD` | PFX 密码 |
| `WINDOWS_CODESIGN_EXPECTED_SUBJECT` | 证书完整 Subject，防止选错身份 |
| `TAURI_SIGNING_PRIVATE_KEY` | Tauri updater 私钥 |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | updater 私钥密码 |

该 Environment 必须配置 required reviewers，并把 deployment branches/tags 限制为受保护的
默认分支与 `v*` 发布标签；仓库同时应启用 protected tag rules，禁止发布标签被移动。
Workflow 还会在运行时强制要求 `github.ref == refs/tags/v<候选版本>`，分支、PR ref、任意
SHA 或标签与应用版本不一致都会在签名前失败。

手动运行 `.github/workflows/windows-release-assurance.yml`：

- `production`：缺少任一 secret 会立即失败；使用受信 CA 证书签名两个版本，并在
  GitHub 托管的全新 `windows-2025` VM 中执行安装、覆盖升级、卸载。
- `self-signed-mechanism`：生成名称带 `SELF-SIGNED TEST ONLY` 的短期自签证书，仅验证
  签名编排和安装器生命周期自动化。它不是生产签名，证据中固定记录
  `production_identity: false`，不得发布其安装包。该 lane 用临时 updater 密钥验证“签名后
  字节可生成并通过 `.sig` 验签”的机制，证据标记为 `ephemeral-mechanism`；由于已经构建的
  可执行文件没有内嵌这把临时公钥，它不冒充 Tauri runtime 的生产更新验收。

  Authenticode 自签名 lane 同样不伪造 CA 信任：它核对精确签名证书、可信 RFC3161
  时间戳，并复制安装包翻转受保护字节，要求 Windows 返回 `HashMismatch`。证据固定记录
  `trust_verified: false` 与 `verification_scope: self-signed-mechanism`。只有 production lane
  才允许记录 `trust_verified: true`，且必须同时通过 `signtool verify /pa /all /v`。

Workflow 把秘密域严格拆开：Authenticode 步骤只能读取 PFX/密码/Subject，完成后必须删除
证书与 PFX；updater 步骤随后只能读取 Tauri 私钥，完成后必须删除临时 key。候选仓库的
Rust/PowerShell verifier 与生命周期脚本只会在两个秘密步骤都清理完成后执行。首次把新
workflow 推到默认分支前，受限的 feature-branch `push` 触发只运行 self-signed lane；合并后
使用 `workflow_dispatch`。`windows-2025` 每次提供全新 hosted VM，但标签本身会随微软镜像
更新，`windows-lifecycle.json` 会记录实际 image/version。

生产 lane 会先证明旧版与候选版内嵌的 updater 公钥非空且完全一致，再用对应生产私钥
生成并验签两个 `.sig`，证据标记为 `embedded-production`。只有这个范围可以作为运行时
更新签名兼容性证据。

无秘密构建 job 会用 1 天保留期传递两份**未签名**安装包到隔离签名 job；签名后的安装包
不会上传。最终证据 artifact 只有 `windows-lifecycle.json`。PFX、证书私钥和 updater 私钥
在任何情况下都不会作为 artifact 上传。

## 3. 干净 Windows 生命周期自动化

Guest 执行器 `scripts/windows/install-lifecycle.ps1` 会 fail-closed 验证：

- 执行前不存在“私人助手”/兼容旧品牌注册项、残留进程或 `%APPDATA%\personal-assistant`；
- 旧、新安装包 Authenticode 状态均为 `Valid` 且有可信时间戳；
- 旧版 `/S` 安装后版本正确；
- 写入仅指向本机不可达端口的测试配置，启动旧版桌面进程并确认打包 sidecar 已拉起；
- 在桌面与 sidecar 仍运行时执行新版 `/S` 覆盖升级，确认安装器关闭旧进程、版本变化，
  且用户标记和配置哈希保持不变；
- 启动新版桌面与 sidecar 后执行 `/S` 卸载，确认注册项、程序目录以及两个运行进程均消失，
  用户数据仍保留。

Windows `productName` 保持为 v0.1.1 已使用的“私人助手”，因为它是 NSIS 卸载键、安装目录
与快捷方式的升级身份；仓库品牌 `PrivateAgent` 不应通过直接修改 `productName` 来迁移。
主进程名从 NSIS 注册表 `MainBinaryName`/`DisplayIcon` 解析，安装钩子使用 Tauri
`${MAINBINARYNAME}`，不再从展示名称猜测可执行文件名。

本机能力预检：

```powershell
scripts\windows\release-preflight.ps1 -Mode Signing
scripts\windows\release-preflight.ps1 -Mode Sandbox
scripts\windows\release-preflight.ps1 -Mode HyperV -VMName '<VM 名称>'
```

Windows Sandbox（每次天然为全新系统）：

```powershell
scripts\windows\run-windows-sandbox-lifecycle.ps1 `
  -OldInstaller '<旧版 setup.exe>' -NewInstaller '<新版 setup.exe>' `
  -UpdaterPublicKeyFile '<tauri.conf updater pubkey 文本文件>' `
  -ExpectedOldVersion '0.1.1' -ExpectedNewVersion '0.1.2' `
  -IdentityClass trusted-ca-production -ProductionIdentity `
  -UpdaterVerificationScope embedded-production
```

Hyper-V（必须提供专用干净 checkpoint；恢复会清除 guest 当前状态）：

```powershell
$credential = Get-Credential # 密码只保存在 SecureString 内存对象中
scripts\windows\run-hyperv-lifecycle.ps1 `
  -VMName 'PA-Windows-Clean' -CheckpointName 'clean' -Credential $credential `
  -OldInstaller '<旧版 setup.exe>' -NewInstaller '<新版 setup.exe>' `
  -UpdaterPublicKeyFile '<tauri.conf updater pubkey 文本文件>' `
  -ExpectedOldVersion '0.1.1' -ExpectedNewVersion '0.1.2' `
  -IdentityClass trusted-ca-production -ProductionIdentity `
  -UpdaterVerificationScope embedded-production `
  -ResultPath 'dist\windows-hyperv-lifecycle.json' -ConfirmRestore
```

## 4. 本地自签名机械验证

以下命令会生成临时测试证书、执行 PFX 导入/检查、SignTool 签名、可信时间戳与篡改检测，
然后清除临时证书和文件。外部签名命令有 180 秒硬超时。它不把测试证书导入 Root，
只验证密码学机制，不产生可发布资产：

```powershell
scripts\windows\self-signed-signing-smoke.ps1 `
  -InputExe '<已有 setup.exe>' `
  -ResultPath "$env:TEMP\private-agent-signing-smoke.json"
```

## 5. 当前环境状态

截至 2026-07-26，实际 0.1.2 NSIS 安装包已通过本地自签名机制测试：签名者、RFC3161
时间戳、篡改检测和证书/临时文件清理均通过，但证据明确为 `trust_verified: false`。
开发机没有生产 Code Signing 私钥证书，也没有 Windows Sandbox 或 Hyper-V PowerShell
能力。因此生产实签和本地干净 VM 生命周期不能在该机器上标记为完成；应在配置上述
GitHub secrets 后运行 `production` lane。自签名 lane 的通过只能作为自动化机制证据。
