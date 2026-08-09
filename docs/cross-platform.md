# 跨平台打包预研（第五阶段 M6 / 第八阶段 M5 更新）

> 对应 `docs/archive/phases/phase5-plan.md` M6、`docs/archive/phases/phase8-plan.md` M5 与 `docs/archive/phases/phase8-requirements.md` 5.5。
>
> **状态边界**：Windows 为硬验收目标。macOS / Linux 在第八阶段 M5 已修正数据目录与多平台清单逻辑，但**仍未实机构建或 smoke**（本机无 macOS/Linux 环境）。本文不宣称 macOS/Linux 已可用。

## 第八阶段 M5 已落地（代码/配置/清单）

- **macOS 数据目录修正**：`config.py` 与 `src-tauri/src/lib.rs` 的 `config_dir` 在 macOS 打包模式改用 `~/Library/Application Support/personal-assistant`（原先误用 XDG `~/.local/share`）。
- **多平台 updater 清单**：`scripts/generate-latest-json.py` 支持 `--extra-platform KEY:INSTALLER_PATH`（可重复），为 darwin-aarch64 / darwin-x86_64 / linux-x86_64 生成独立 `{signature, url}` 条目；多平台清单逻辑有测试（`tests/test_phase8_release.py`）。
- **跨平台清单发现**：`scripts/_release_utils.py` 的 `find_cross_platform_installers` 与 `PLATFORM_BUNDLES` 覆盖三类 OS 的 bundle 子目录与安装包 glob。
- **bundle targets**：保留 `["nsis"]` 为 Windows 默认；macOS/Linux 用 CLI 覆盖：`tauri build --bundles app,dmg`（macOS）/ `--bundles appimage,deb`（Linux）。

## 待真实环境执行

- macOS/Linux 实机 `scripts/build-sidecar.sh` + `tauri build --bundles ...` + 首启配置 + `/health` + 聊天/文档导入 smoke。
- macOS Gatekeeper / codesign / notarization 状态记录。
- 未实测平台继续标注「未实测」，不写成已支持。

---

## 1. 目标

为 macOS / Linux 后续发布扫清未知项，但不阻塞 Windows 正式发布：
- 梳理三平台差异（target triple、配置目录、安装包格式、签名、外部依赖）。
- 提供跨平台 build-sidecar 脚本（Windows `.bat` + macOS/Linux `.sh`）。
- 明确待验证清单，避免把未验证平台写成已支持。

后端业务逻辑三平台共用（同一份 `src/personal_assistant/`），差异集中在 Tauri 配置、构建脚本与外部依赖。

---

## 2. Target triple 与 sidecar 命名

Tauri `externalBin` 要求 sidecar 命名为 `<name>-<target-triple>[.exe]`：

| 平台 | target triple | sidecar 文件名 |
|---|---|---|
| Windows x64 | `x86_64-pc-windows-msvc` | `personal-assistant-server-x86_64-pc-windows-msvc.exe` |
| macOS Apple Silicon | `aarch64-apple-darwin` | `personal-assistant-server-aarch64-apple-darwin` |
| macOS Intel | `x86_64-apple-darwin` | `personal-assistant-server-x86_64-apple-darwin` |
| Linux x64 | `x86_64-unknown-linux-gnu` | `personal-assistant-server-x86_64-unknown-linux-gnu` |

构建脚本：
- Windows：`scripts/build-sidecar.bat`（已验证）。
- macOS / Linux：`scripts/build-sidecar.sh`（用 `rustc -vV` 或 `uname` 检测 triple，PyInstaller 产物复制到 `binaries/` 并加 triple 后缀；**未实测**）。

---

## 3. macOS

### 3.1 构建产物
- Tauri 2 产出 `.app` 与 `.dmg`（`bundle.targets` 需新增 `app` / `dmg`，当前 `tauri.conf.json` 仅 `nsis`）。
- sidecar 经 `scripts/build-sidecar.sh` 打成 `personal-assistant-server-aarch64-apple-darwin`（或 x86_64）。

### 3.2 代码签名与公证（Notarization）
- **Developer ID Application 证书**（Apple，年费）签名 `.app`：`codesign --deep --options runtime --sign "Developer ID Application: <Name>" <app>.app`。
- **Notarization**：`xcrun notarytool submit <app>.zip --apple-id ... --team-id ... --wait` 提交 Apple 公证，通过后 `xcrun stapler staple <app>.app` 装订票据。
- 未签名/未公证的 macOS 应用首次运行会被 Gatekeeper 拦截（"无法打开，因为来自身份不明的开发者"），需右键"打开"或 `xattr -cr` 绕过。
- updater 签名（Tauri `.sig`）与 macOS 代码签名是两层独立机制（同 Windows），公钥仍用 `tauri.conf.json` 的 `plugins.updater.pubkey`。

### 3.3 配置目录
- `config.py` 打包模式（`sys.frozen`）类 Unix 路径：`~/.local/share/personal-assistant`（`XDG_DATA_HOME` 优先）。
- macOS 更规范的做法是 `~/Library/Application Support/personal-assistant`--若正式支持 macOS，建议 `config.py` 对 `darwin` 单独处理。**当前未做**（待 macOS 支持时改）。

### 3.4 外部依赖
- Ollama：`brew install ollama` 或官网安装；`ollama pull qwen2.5:14b-instruct-q4_K_M` / `bge-m3`。
- MySQL：`brew install mysql` 或 Docker；建库同 Windows。
- 首启向导（`ConfigWizard.vue`）与依赖检测（`check_dependencies`/`test_connections`）逻辑跨平台通用，但默认端口探测写死 `127.0.0.1:3306` / `127.0.0.1:11434`，macOS 同样适用。

---

## 4. Linux

### 4.1 构建产物
- Tauri 2 产出 `AppImage` / `deb` / `rpm`（`bundle.targets` 需新增对应项）。
- sidecar 经 `scripts/build-sidecar.sh` 打成 `personal-assistant-server-x86_64-unknown-linux-gnu`。

### 4.2 系统依赖（WebKitGTK）
- Tauri 在 Linux 依赖 **WebKitGTK 4.1**（`libwebkit2gtk-4.1-0`）+ `libgtk-3` + `librsvg` + `libayatana-appindicator3`（构建时还需 `build-essential`、`libssl-dev`、`librsvg2-dev`、`libwebkit2gtk-4.1-dev`）。
- AppImage 自包含部分库，但 WebKitGTK 仍需宿主提供（AppImage 的常见运行期依赖）。
- 发行版差异（Ubuntu/Debian 用 apt，Fedora 用 dnf，Arch 用 pacman）是 Linux 分发的主要复杂度。

### 4.3 配置目录
- `~/.local/share/personal-assistant`（`XDG_DATA_HOME` 优先）-- `config.py` 已支持。

### 4.4 外部依赖
- Ollama：`curl -fsSL https://ollama.com/install.sh | sh`。
- MySQL：发行版包管理器或 Docker。

---

## 5. 待验证清单（macOS / Linux）

正式支持前必须完成（当前均未做）：

- [ ] 在 macOS（Apple Silicon + Intel）跑 `scripts/build-sidecar.sh` + `npm run tauri build`，产出 `.dmg`。
- [ ] macOS 首启向导、sidecar 端口协商、`/health` 全绿、聊天与文档导入 smoke。
- [ ] macOS `config.py` 改用 `~/Library/Application Support`（可选）。
- [ ] macOS 代码签名 + Notarization 接入（或文档说明 Gatekeeper 绕过）。
- [ ] 在 Linux（Ubuntu 22.04+）安装 WebKitGTK 依赖后跑 `build-sidecar.sh` + `tauri build`，产出 AppImage。
- [ ] Linux smoke 同上。
- [ ] 跨平台 updater：发布源为 macOS/Linux 各自的安装包 + `.sig` + `latest.json`（`latest.json` 需按平台多 `platforms` 条目）。

> 当前 `scripts/generate-latest-json.py` 只产 `windows-x86_64` 条目；跨平台发布时需扩展为多平台 `platforms`（`darwin-aarch64` / `darwin-x86_64` / `linux-x86_64`）。

---

## 6. 当前结论

- Windows 是第五阶段硬验收目标，已完成（见 `docs/archive/phases/phase5-plan.md` M1–M5 与 `docs/release-checklist.md`）。
- macOS / Linux 有 `build-sidecar.sh` 与差异清单，但**未构建、未 smoke**，不宣称可用。
- 跨平台发布列入后续阶段；优先级低于 Windows 发布闭环稳定。
