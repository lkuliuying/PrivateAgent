# 私人助手 Agent · 第五阶段：安装包与更新机制

> 第五阶段产出**未签名 NSIS 安装包** + **Tauri updater 预研**。目标：把第四阶段验证可行的 Tauri + PyInstaller sidecar 方案封装为可分发的 Windows 安装器，并打通自动更新链路的设计（私钥生成、发布源、签名校验）。本阶段不强制落地发布源部署与代码签名证书。

---

## 1. 概述

| 项 | 状态 |
|---|---|
| NSIS 安装包（Windows x64） | 产出，未签名 |
| 安装模式 | `currentUser`（免 UAC，装到 `%LOCALAPPDATA%`） |
| Updater 机制 | 预研（keypair / endpoints / latest.json 设计完成，发布源未部署） |
| 代码签名 | 无证书（SmartScreen 会警告，见 §7） |
| 跨平台 | 仅 Windows x64（macOS/Linux 留后续） |

构建入口：`scripts/build-release.bat`（一键打包 sidecar + tauri build，见 §4）。

---

## 2. NSIS 安装包配置

当前 `apps/desktop/src-tauri/tauri.conf.json` 的 `bundle` 段为：

```json
"bundle": {
  "active": true,
  "targets": "all",
  "icon": ["icons/32x32.png", "icons/128x128.png", "icons/128x128@2x.png", "icons/icon.icns", "icons/icon.ico"],
  "externalBin": ["binaries/personal-assistant-server"]
}
```

为产出 NSIS 安装包并启用更新签名产物，需调整为：

```jsonc
"bundle": {
  "active": true,
  "targets": ["nsis"],                 // 仅生成 NSIS 安装器（默认 "all" 还会出 msi 等）
  "icon": ["icons/32x32.png", "icons/128x128.png", "icons/128x128@2x.png", "icons/icon.icns", "icons/icon.ico"],
  "externalBin": ["binaries/personal-assistant-server"],
  "publisher": "Personal Assistant",    // 控制面板“发布者”列
  "copyright": "© 2026 Personal Assistant",
  "category": "Productivity",           // 应用类别
  "createUpdaterArtifacts": true,       // 配合签名私钥生成 *.exe.sig（见 §3）
  "windows": {
    "nsis": {
      "installMode": "currentUser",     // 免 UAC，装到 %LOCALAPPDATA%（无管理员权限也能装/卸）
      "languages": ["SimpChinese", "English"],
      "displayLanguageSelector": false
    }
  }
}
```

关键点：

| 字段 | 说明 |
|---|---|
| `targets: ["nsis"]` | 只产 NSIS 安装器。dev 期保持 `"all"` 也可，发布前收紧。 |
| `windows.nsis.installMode` | `currentUser`（本阶段，免 UAC）/ `perMachine`（装到 Program Files，需 UAC）/ `both`（安装时选）。本阶段选 `currentUser` 降低首装门槛。 |
| `windows.nsis.languages` | 安装界面语言；`SimpChinese` 为简体中文。 |
| `createUpdaterArtifacts` | `true`：当构建时设置了 `TAURI_SIGNING_PRIVATE_KEY`，额外生成 `*.exe.sig` 供 updater 校验；无私钥时不生成。 |
| `publisher` / `copyright` / `category` | 元数据，显示在“添加/删除程序”与安装界面。 |

> 注意：`bundle.windows.nsis`（installMode/languages）与 `targets: ["nsis"]` 已写入 `tauri.conf.json`。`createUpdaterArtifacts` 与 `plugins.updater` 暂未写入——需先生成签名密钥对（§3.3）再启用，否则未签名构建会失败。

---

## 3. Updater 机制（Tauri v2）

### 3.1 依赖

`apps/desktop/src-tauri/Cargo.toml` 当前仅有 `tauri-plugin-shell`，需新增：

```toml
tauri-plugin-updater = "2"   # 检查/下载/校验/安装更新
tauri-plugin-process = "2"   # 更新后 relaunch() 重启应用
```

并在 `src/lib.rs` 注册插件（`tauri_plugin_updater::Builder::new().build()`、`tauri_plugin_process::init()`）与命令（`check_for_updates` / `download_and_install_update` / `relaunch_app`）；前端 `UpdateChecker.vue` 提供「检查更新 / 下载并安装 / 重启」交互。注意：`plugins.updater`（endpoints/pubkey）尚未写入 `tauri.conf.json`，需先生成签名密钥对（§3.3）并部署发布源后「检查更新」才真正可用；未配置时命令返回友好错误。

### 3.2 配置（tauri.conf.json `plugins.updater`）

```jsonc
"plugins": {
  "updater": {
    "active": true,
    "endpoints": [
      "https://example.com/personal-assistant/releases/{{target}}/{{current_version}}"
    ],
    "pubkey": "<此处填 §3.3 生成的公钥 base64>",
    "dialog": true          // 发现更新时弹内置对话框（也可前端自定义 UI，设 false）
  }
}
```

| 字段 | 说明 |
|---|---|
| `endpoints` | 拉取更新清单的 URL，支持 `{{target}}`、`{{current_version}}`、`{{arch}}` 占位符（见 §5）。 |
| `pubkey` | **公钥**（base64），用于校验下载包的 `.sig` 签名。私钥绝不入配置/仓库。 |
| `dialog` | `true` 用 Tauri 内置更新对话框；`false` 则由前端自行实现流程。 |

### 3.3 生成 keypair（签名密钥对）

```bat
cd /d F:\Program\Agent\apps\desktop
npm run tauri signer generate -- -w %USERPROFILE%\.tauri\personal-assistant.key
```

- 命令会**提示输入密码**（用于加密私钥），请记牢。
- 私钥写入 `%USERPROFILE%\.tauri\personal-assistant.key`。
- 公钥打印到**标准输出**（base64 字符串），复制后填入 `tauri.conf.json` 的 `plugins.updater.pubkey`。

### 3.4 构建时使用私钥

`tauri build` 通过环境变量读取私钥：

| 环境变量 | 说明 |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | 私钥内容（base64），由 `build-release.bat` 用 `set /p` 从 `.tauri\personal-assistant.key` 读入。 |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | 私钥密码。未设置则交互式提示（自动化构建会卡住），`build-release.bat` 会从可选的 `.tauri\personal-assistant.key.pwd` 读入。 |

二者齐备时，`tauri build` 会在 NSIS 产物旁生成 `*.exe.sig`。

### 3.5 私钥安全

- 私钥文件**严禁入 git**：在仓库根 `.gitignore` 加 `.tauri/` 或具体路径。
- 仅本地/构建机持有私钥；用户端只需公钥（已编译进应用）。
- 密码文件 `.pwd` 同样不入 git，仅用于本地自动化构建。

---

## 4. build-release.bat 用法与流程

**用途**：一键产出 Windows NSIS 安装包（及可选 `.sig`）。项目根执行。

**流程**：

| 步骤 | 动作 | 失败处理 |
|---|---|---|
| [1/4] 打包 sidecar | `call scripts\build-sidecar.bat`（PyInstaller onefile → 复制到 `binaries/`） | `exit /b 1` |
| [2/4] 设置 MSVC 环境 | `call vcvars64.bat >nul 2>&1`；`set PATH=%USERPROFILE%\.cargo\bin;%PATH%` | `exit /b 1` |
| [3/4] 可选 updater 签名 | 若存在 `%USERPROFILE%\.tauri\personal-assistant.key` 则 `set /p` 读入私钥（+ 可选 `.pwd` 读密码）；否则跳过 | 不阻断 |
| [4/4] tauri build | `cd apps\desktop && npm run tauri build` | `exit /b 1` |

**用法**：

```bat
:: 项目根执行（双击或 cmd）
scripts\build-release.bat
```

**产物**：

```
apps\desktop\src-tauri\target\release\bundle\nsis\
├── 私人助手_0.1.0_x64-setup.exe        # NSIS 安装包
└── 私人助手_0.1.0_x64-setup.exe.sig    # 更新签名（仅当提供私钥）
```

> 风格与 `build-sidecar.bat` / `run-tauri-dev.bat` 一致：`@echo off`、`setlocal`、`call vcvars64.bat`、`set PATH` cargo、`if errorlevel 1 exit /b 1`、`endlocal`。

---

## 5. 发布源设计

### 5.1 endpoints 占位符

`plugins.updater.endpoints` 中的 URL 在运行时被替换后请求：

| 占位符 | 含义 | 示例值（Windows x64） |
|---|---|---|
| `{{target}}` | 目标三元组组合 | `windows-x86_64` |
| `{{current_version}}` | 当前应用版本（`tauri.conf.json` version） | `0.1.0` |
| `{{arch}}` | 架构 | `x86_64` |

替换后形如：`https://example.com/personal-assistant/releases/windows-x86_64/0.1.0`。

### 5.2 latest.json 格式

updater 请求 endpoint 后，期望返回如下 JSON（即“最新版本清单”）：

```json
{
  "version": "0.2.0",
  "pub_date": "2026-07-04T12:00:00Z",
  "platforms": {
    "windows-x86_64": {
      "signature": "<.exe.sig 文件内容，即 Minisign 签名串>",
      "url": "https://example.com/personal-assistant/releases/0.2.0/私人助手_0.2.0_x64-setup.exe"
    }
  }
}
```

| 字段 | 说明 |
|---|---|
| `version` | 最新版本号（语义化）。比当前版本**高**才触发更新。 |
| `pub_date` | RFC 3339 时间戳。 |
| `platforms.<target>.signature` | 对应平台安装包的 `.sig` 文件内容（构建产物里那份）。 |
| `platforms.<target>.url` | 该平台安装包下载地址。 |

> 简化方案：endpoint 可直接指向一个**静态 `latest.json`**（含所有平台），URL 不带占位符即可；占位符仅用于服务端按 target/版本动态返回的场景。

### 5.3 部署建议

| 方案 | 说明 |
|---|---|
| **GitHub Releases raw** | 把 `latest.json` + `*-setup.exe` + `.sig` 作为 Release 资产，endpoint 指向 `raw.githubusercontent.com` 或 `github.com/.../releases/latest/download/latest.json`。零运维，适合个人/小项目。 |
| **静态托管** | Nginx/对象存储托管 `latest.json` 与安装包，endpoint 指向静态 URL。需自行保证 HTTPS 与 CORS（若 webview 校验）。 |

- `latest.json` 与安装包必须走 **HTTPS**。
- 每次发版：递增版本 → 跑 `build-release.bat`（带私钥）→ 上传 `*.exe`、`*.sig` → 更新 `latest.json` 的 `version`/`pub_date`/`signature`/`url`。
- 本阶段**未实际部署**发布源，updater 为预研状态。

---

## 6. 版本号递增规则

- 版本唯一来源：`apps/desktop/src-tauri/tauri.conf.json` 的顶层 `version` 字段（当前 `0.1.0`）。
- 采用**语义化版本** `MAJOR.MINOR.PATCH`：
  - `PATCH`：缺陷修复、小调整（`0.1.0` → `0.1.1`）。
  - `MINOR`：向后兼容的新功能（`0.1.0` → `0.2.0`）。
  - `MAJOR`：不兼容变更（`0.x` 阶段可灵活，正式 `1.0` 后严格）。
- `Cargo.toml` 的 `version` 与 Tauri 打包无关（Tauri 读 `tauri.conf.json`），但建议保持一致。
- 每次发版同步更新 `latest.json` 的 `version`，且必须**高于**当前用户端版本才会触发更新。

---

## 7. SmartScreen 风险与对策

本阶段产物**未签名**，分发时存在 Windows SmartScreen 风险。

| 现象 | 说明 |
|---|---|
| 首次运行警告 | 未签名 exe 触发“Windows 已保护你的电脑”蓝色 SmartScreen 拦截。 |
| 安装免 UAC | `installMode: currentUser` 装到 `%LOCALAPPDATA%`，安装过程**无需**管理员权限/UAC（但仍会被 SmartScreen 扫描）。 |

**用户绕过步骤**（未签名时引导用户）：

1. SmartScreen 蓝屏点“更多信息”。
2. 点“仍要运行”。
3. 继续 NSIS 安装流程。

**长期对策**：

| 对策 | 效果 |
|---|---|
| 向 Microsoft 提交信誉 | 通过 [Windows Defender 安全智能](https://www.microsoft.com/wdsi) / Partner Center 提交样本积累信誉，需时间与一定下载量。 |
| OV 代码签名证书 | 标准代码签名；SmartScreen 仍会警告，直到信誉建立。 |
| **EV 代码签名证书** | 硬件令牌签名；通常**立即**通过 SmartScreen（无警告），成本最高但体验最好。 |

> 建议：早期内测可接受用户手动绕过；面向非技术用户分发前至少上 OV 证书，追求无感安装上 EV 证书。EV/OV 签名与 updater 的 `.sig` 是两套机制（前者认证发行者，后者校验更新包完整性），不冲突。

---

## 8. 体积优化路线

当前 sidecar 为 PyInstaller **onefile**，产物约 80 MB（chromadb + onnxruntime + langchain + sqlalchemy + fastapi + uvicorn，见 `phase4-sidecar-research.md` §4.1）。

| 方向 | 做法 | 收益 / 风险 |
|---|---|---|
| **onefile → onedir** | onefile 首启解压到 `_MEIPASS` 略慢；切 onedir 启动更快。但 Tauri `externalBin` 要求单文件，需改用 Tauri `resources` 打包整个目录，sidecar 用绝对路径调起（phase4 §9.4 已建议）。 | 首启更快；需改 sidecar 调起逻辑。 |
| **排除 onnxruntime** | spec 目前打包 `onnxruntime`（chromadb 默认 embedding 依赖，见 `personal_assistant.spec` 注释）。**若运行时确认 chromadb 用 Ollama embedding 不触发默认 embedding**，可移除 `collect_submodules("onnxruntime")` 与 `collect_data_files("onnxruntime")`。 | 显著减小体积；**必须运行时验证**（用 Ollama embedding 跑一遍 RAG，确认无 `ImportError` 且检索正常）。 |
| **UPX 压缩** | spec 当前 `upx=False`。UPX 可压缩体积。 | **杀软（尤其国内）易误报为病毒**，得不偿失，**不推荐**。 |

> 优先级：先验证排除 onnxruntime（收益大、风险可控），再评估 onedir 切换。

---

## 9. WebView2 依赖

Tauri on Windows 依赖 **WebView2 Runtime**（基于 Edge 内核渲染前端）。安装包需处理其存在性。

| `bundle.windows.webviewInstallMode` | 说明 | 代价 |
|---|---|---|
| `downloadBootstrapper`（默认） | 首装时联网下载 WebView2 引导程序并安装。 | 首装**需联网**；用户已装则跳过。 |
| `embedBootstrapper` | 把引导程序内嵌进安装包，仍需联网下载运行时。 | 安装包略增。 |
| `offlineInstaller` | 内嵌完整 WebView2 离线安装器。 | 安装包**+约 150 MB**，可完全离线。 |
| `disable` | 不处理，要求用户已自带 WebView2（Win11 默认有）。 | 体积最小；缺失则应用无法启动。 |

- 本阶段沿用默认 `downloadBootstrapper`：**首装需联网**，Win11 多数已自带 WebView2，影响有限。
- 离线/内网场景可切 `offlineInstaller`，代价是安装包增约 150 MB。

---

## 10. 已知限制与后续

| 项 | 现状 | 后续 |
|---|---|---|
| 代码签名 | 无证书，SmartScreen 警告 | 上 OV/EV 证书（见 §7） |
| 更新粒度 | 全量更新（每次下载完整安装包） | Tauri v2 暂无官方 delta；可接受 |
| 发布源 | endpoints/latest.json 设计完成，**未部署** | 部署 GitHub Releases 或静态托管（见 §5.3） |
| Updater 前端 | 命令与 UI 已实现，发布源未部署 | 生成密钥对 + 写入 `plugins.updater` + 部署 `latest.json` |
| 平台 | 仅 Windows x64 | macOS/Linux sidecar target triple + PyInstaller 产物 |
| sidecar 模式 | onefile，首启略慢 | onedir + Tauri resources（见 §8） |
| onnxruntime | 打包进 sidecar | 验证可移除后减小体积（见 §8） |

---

## 附：本阶段交付物

- `apps/desktop/src-tauri/src/lib.rs` —— sidecar 生命周期、端口协商、配置读写、依赖检测、updater 命令。
- `apps/desktop/src-tauri/tauri.conf.json` —— NSIS 安装包配置（targets/nsis/installMode）。
- `apps/desktop/src-tauri/Cargo.toml` / `capabilities/default.json` —— updater/process 依赖与权限。
- `apps/desktop/src/api.ts` —— 上述命令的 TS 包装与类型。
- `apps/desktop/src/components/ConfigWizard.vue` —— 首启/重配连接向导。
- `apps/desktop/src/components/UpdateChecker.vue` —— 检查更新 UI。
- `apps/desktop/src/App.vue` —— 启动引导状态机（checking/wizard/starting/done/dev/error）。
- `scripts/build-release.bat` —— 一键构建 NSIS 安装包（含可选 updater 签名）。
- `docs/phase5-installer-updater.md` —— 本文档。
