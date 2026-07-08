# 私人助手 Agent · 第五阶段开发计划书

> 对应 `docs/phase5-requirements.md`。第五阶段定位为“安装包、自动更新与发布工程化”。当前仓库已经有第五阶段的一部分实现：NSIS、配置向导、sidecar 生命周期和 updater 命令接线；本计划书以当前代码为基础，继续补齐签名、发布源、可复现构建、发布 QA、体积优化和跨平台准备。

---

## 1. 阶段判断

当前项目已经具备完整的个人 Agent 能力闭环：

1. **产品能力**
   - 聊天、知识库、项目、学习、任务、记忆、设置七入口。
   - 长期记忆、复习、文档集合、patch set、任务计划 2.0、Provider、备份恢复预览。

2. **本地运行**
   - FastAPI + MySQL + ChromaDB + Ollama。
   - Alembic 迁移到 `0008 (head)`。
   - 测试、前端构建、Tauri 校验已有通过记录。

3. **打包基础**
   - PyInstaller sidecar onefile 已存在。
   - Tauri `externalBin` 已配置。
   - NSIS 安装包配置已存在。
   - 首启配置向导已存在。
   - updater 命令和 UI 已接线。

第五阶段不需要重写产品架构，而是把交付链路做实：

- 构建要可复现。
- 安装要可验证。
- 更新要能从真实发布源跑通。
- 签名和密钥要安全。
- 失败要能排查和回滚。
- 体积和跨平台要有明确路线。

---

## 2. 总体目标

第五阶段交付后，应能跑通两个代表场景：

### 场景 A：新用户安装

1. 用户下载 Windows 安装包。
2. 安装后启动应用。
3. 首启向导检测 MySQL/Ollama/模型。
4. 用户保存连接配置。
5. Tauri 启动 sidecar，前端连接动态端口。
6. 状态页显示 API/Ollama/MySQL/ChromaDB 全绿。
7. 用户能发起聊天并导入一份文档。

### 场景 B：旧用户升级

1. 用户已安装 v0.1.0。
2. 发布 v0.1.1，上传安装包、`.sig`、`latest.json`。
3. 用户在设置页点击检查更新。
4. 应用发现新版本并安装。
5. 更新前 sidecar 被终止。
6. 应用重启后旧配置和数据仍可使用。

---

## 3. 当前事实基线

### 3.1 已实现

- `scripts/build-sidecar.bat`
  - 通过 PyInstaller 构建 `personal-assistant-server.exe`。
  - 复制到 `apps/desktop/src-tauri/binaries/personal-assistant-server-x86_64-pc-windows-msvc.exe`。

- `scripts/build-release.bat`
  - 串联 sidecar 构建、MSVC 环境、可选 updater 私钥、`npm run tauri build`。
  - 输出 NSIS 安装包和可选 `.sig`。

- `apps/desktop/src-tauri/tauri.conf.json`
  - `bundle.targets = ["nsis"]`。
  - `installMode = "currentUser"`。
  - `externalBin = ["binaries/personal-assistant-server"]`。
  - `createUpdaterArtifacts = true`。
  - updater endpoint 指向 GitHub Release 的 `latest.json`。

- `apps/desktop/src-tauri/src/lib.rs`
  - `config_exists/read_config/write_config`。
  - `check_dependencies/test_connections`。
  - `start_sidecar/get_api_port`。
  - `check_for_updates/download_and_install_update/relaunch_app`。
  - 退出和更新前终止 sidecar。

- `apps/desktop/src/components/ConfigWizard.vue`
  - 两步向导：环境检测、填写连接。
  - MySQL/Ollama/模型检测。

- `apps/desktop/src/components/UpdateChecker.vue`
  - 检查更新、展示新版本、下载安装。

- `docs/updater-latest.json` 与 `.example`
  - 已有 Tauri updater manifest 样例和当前版本清单。

### 3.2 主要缺口

| 缺口 | 影响 | 对应里程碑 |
|---|---|---|
| 发布源未端到端验证 | 用户无法确认自动更新可用 | M2 |
| 安装包未代码签名 | SmartScreen 警告，信任成本高 | M3 |
| 构建脚本硬编码本机路径 | 新机器复现困难 | M1 |
| 缺少发布清单 | 无法追踪某个版本的产物和验证结果 | M1/M4 |
| 缺少干净机安装/升级 smoke | 发布风险不可见 | M4 |
| onefile 首启慢、体积大 | 首次体验不稳定 | M5 |
| macOS/Linux 未验证 | 跨平台只是预留 | M6 |

---

## 4. 里程碑

### M0 · 第五阶段文档与发布边界

目标：把第五阶段从零散“安装包与更新预研”整理成可执行计划。

任务：

- [x] 新增 `docs/phase5-requirements.md`。
- [x] 新增 `docs/phase5-plan.md`。
- [x] 更新 README 第五阶段引用。
- [x] 更新 usage-guide 第五阶段引用和过时描述。
- [x] 更新 UI/脚本中的旧文档路径提示。
- [x] 明确“已实现”和“尚未实现”的状态。

验收：

- 文档中不再引用不存在的第五阶段文档。
- README、usage-guide、代码提示指向同一套第五阶段文档。
- 第五阶段需求和计划是两份独立文档。

### M1 · 可复现 Windows 发布构建

目标：让 Windows 安装包构建能在新机器按文档复现。

任务：

- [x] 调整 `scripts/build-release.bat`，减少硬编码路径：
  - 项目根从脚本位置推导。
  - `uv.exe` 优先从 PATH 查找，找不到再提示安装。
  - MSVC `vcvars64.bat` 支持常见路径检测。
- [x] 增加 `scripts/release-check.bat`：
  - `pytest -q`
  - `npm run build`
  - `cargo check`
  - `alembic current`
- [x] 增加发布清单模板：
  - version
  - git commit
  - installer path
  - installer sha256
  - sig path
  - latest.json path
  - validation result
- [x] 在 README 和 usage-guide 写清依赖准备与构建顺序。

验收：

- 新 Windows 开发机按文档准备依赖后能跑 `scripts\build-release.bat`。
- 构建失败能看出是 uv、MSVC、Node、Rust、PyInstaller 还是 Tauri 问题。
- 每次 release build 都能产出可归档清单。

### M2 · Updater 发布源端到端

目标：让应用内自动更新从真实发布源跑通。

任务：

- [x] 确认 GitHub Release 资产命名规则。
- [x] 生成或复核 updater 私钥/公钥。
- [x] 确认 `tauri.conf.json` pubkey 与私钥匹配。
- [x] 自动生成 `latest.json`：
  - version 来自 `tauri.conf.json` 或 package metadata。
  - url 指向 GitHub Release 安装包。
  - signature 来自 `.sig` 文件。
  - pub_date 使用 UTC ISO 时间。
- [x] 上传 Release 资产：
  - NSIS installer。
  - installer `.sig`。
  - `latest.json`。
- [x] 准备 v0.1.0 -> v0.1.1 的升级 smoke。
- [x] 更新 `UpdateChecker.vue` 错误提示，区分网络失败、清单错误、签名失败、无更新。

验收：

- 旧版本点击“检查更新”能发现新版本。
- 点击“下载并安装”后应用完成更新并重启。
- 签名错误的 `latest.json` 被拒绝。
- 无更新时显示最新状态。

### M3 · 签名、信任与密钥治理

目标：明确 updater 签名和 Windows 代码签名边界，避免密钥和发布信任混乱。

任务：

- [x] 确认 updater 私钥保存策略：
  - 本地 `%USERPROFILE%\.tauri\personal-assistant.key` 仅用于个人发布；或
  - GitHub Actions secret 用于 CI 发布。
- [x] 将私钥路径、密码文件、轮换策略写入发布文档。
- [x] 检查仓库 `.gitignore` 覆盖私钥和构建密钥产物。
- [x] 评估 Windows 代码签名：
  - OV/EV 证书成本。
  - signtool 调用方式。
  - timestamp server。
  - 签名前后文件 hash 和 updater signature 顺序。
- [x] 未接入代码签名前，在安装说明保留 SmartScreen 风险提示。
- [x] 接入后在 release checklist 中加入 signtool 验证。

验收：

- 仓库不包含私钥。
- updater 签名密钥和 Windows 代码签名证书职责清晰。
- 未签名/已签名两种发布状态文档都准确。

### M4 · 安装、升级、卸载 QA 矩阵

目标：发布前能系统验证“真实用户会遇到的路径”。

任务：

- [x] 建立 Windows 发布 QA checklist：
  - 干净安装。
  - 已安装覆盖安装。
  - 首启向导。
  - 重新配置连接。
  - MySQL 不可达。
  - Ollama 不可达。
  - 模型未拉取。
  - 普通聊天。
  - 文档导入。
  - 退出清理 sidecar。
  - 自动更新。
  - 卸载。
- [x] 记录用户数据目录行为：
  - `.env` 是否保留。
  - Chroma 数据是否保留。
  - logs/backup 是否保留。
- [x] 增加升级迁移测试说明：
  - 旧版本数据库 schema。
  - 新版本启动后 Alembic upgrade。
  - 失败回退策略。
- [x] 把 QA checklist 放入 `docs/phase5-plan.md` 或单独 `docs/release-checklist.md`。

验收：

- 每次发版可以按 checklist 留存结果。
- 安装/升级/卸载的用户数据策略明确。
- 数据迁移失败时有备份和排查路径。

### M5 · Sidecar 体积与启动性能优化

目标：降低安装包体积和首启延迟，同时保持稳定。

任务：

- [x] 记录当前基线（`scripts/measure_sidecar_baseline.py --startup`）：
  - sidecar exe 大小。
  - NSIS 安装包大小。
  - 首次启动到 `/health` 可用耗时。
  - 第二次启动耗时。
- [x] 评估 PyInstaller onedir：
  - 新增 `personal_assistant_onedir.spec`。
  - Tauri resources/sidecar 调用路径方案（见下）。
  - 安装包体积和启动时间对比（onefile 已测；onedir 待构建后补测，见下）。
- [x] 评估依赖裁剪：
  - `onnxruntime` 是否可排除（见下）。
  - ChromaDB 默认 embedding 是否会被触发（见下）。
  - LangChain 相关 hiddenimports 是否可缩小（见下）。
- [x] 保留 onefile 作为稳定路径，只有 smoke 全通过才切换默认。

#### 基线与评估结果（2026-07-08 实测）

| 指标 | onefile（当前默认） | 说明 |
|---|---|---|
| sidecar exe | 88.6 MB（92,915,395 B） | `personal-assistant-server-x86_64-pc-windows-msvc.exe`，v0.1.1 rebuild |
| NSIS 安装包 | 92.0 MB（96,437,285 B） | `私人助手_0.1.1_x64-setup.exe` |
| updater `.sig` | 424 B | |
| 启动到 `/health`（OS 缓存命中） | 冷 ≈ 5.4s / 热 ≈ 5.6s | `measure_sidecar_baseline.py --startup`，dev .env 配置 |
| 启动到 `/health`（真冷：重启后首次） | 更高且不稳定（≈20–25s 观测） | 主要成本：`_MEIPASS` 解压 + ChromaDB lifespan 初始化 |

> 启动耗时主导因素**不是** `_MEIPASS` 解压（OS 缓存命中时仅几秒），而是 **ChromaDB lifespan 初始化**（onnxruntime 加载 + chroma 迁移/telemetry + SQLite）。真冷启动还叠加首次解压与杀软扫描，波动较大。

#### onedir 评估

- 已提供 `personal_assistant_onedir.spec`（`EXE(exclude_binaries=True)` + `COLLECT`），供评估构建。
- **Tauri 集成障碍**：`externalBin` 要求单个二进制，与 onedir 目录产物不兼容。切 onedir 需改用 Tauri `resources` 打包整个目录，并在 `lib.rs` 用 `app.path().resource_dir()` 解析后以 `tauri_plugin_shell::process::Command` 启动目录内 exe（替换 `app.shell().sidecar()`）-- 即需改动 `start_sidecar` 路径逻辑，**当前未实现**。
- **预期收益**：onedir 免去 `_MEIPASS` 解压，真冷首启应明显变快；但 onedir 目录体积通常与 onefile 相近甚至略大（无单文件压缩收益），且 Tauri 集成复杂度上升。
- **结论**：暂不切换。onefile 已稳定且 `externalBin` 集成简单；onedir 收益主要在真冷首启，但需 lib.rs 改动 + 完整打包 smoke 验证，风险高于收益。待 onefile 体积/启动成为真实瓶颈再评估。

#### 依赖裁剪评估

- **`onnxruntime`**：是 chromadb 默认 embedding 函数的依赖。本项目用 Ollama (`bge-m3`) embedding，不触发 chromadb 默认 ONNX embedding，但 `import chromadb` 仍可能引用 onnxruntime 子模块（spec 已 `collect_submodules("onnxruntime")` 防运行时 ImportError）。**可尝试** `excludes=["onnxruntime"]` 并实测 chroma add/query 不报错--若可行可减小数十 MB 并显著缩短 lifespan 初始化。需运行时验证（导入 + 增删查向量）后才能启用。
- **ChromaDB 默认 embedding**：只在未指定 embedding function 时触发。本项目 `store_chroma.py` 用 Ollama embedding，不触发默认。裁剪 onnxruntime 的前提是确认 chromadb 不在 import 时强制加载默认 embedding。
- **LangChain hiddenimports**：`collect_submodules("langchain" / "langchain_ollama" / "langchain_chroma" / "langgraph")` 收集较全，体积可观但难以精确裁剪（动态 import 多）。可评估只保留实际使用的子包，但风险高，暂不动。

#### 发现的打包缺陷（已修复并重新构建验证）

实测 sidecar 独立启动时，alembic 迁移报 `'cryptography' package is required for sha256_password or caching_sha2_password auth methods`。原因：MySQL 8 默认 `caching_sha2_password` 认证需要 `cryptography`，而 aiomysql 在 `try/except` 内动态 import，PyInstaller 静态分析看不到，未打入 sidecar。**后果**：打包模式连 MySQL 8 会认证失败（状态页 MySQL 红；Phase 4 的 "/health 200" 掩盖了此问题，因 /health 即使 MySQL 红也返回 200）。

**修复**：已在 `personal_assistant.spec` 与 `personal_assistant_onedir.spec` 的 `hiddenimports` 显式加入 `"cryptography"`。2026-07-08 已重新运行 `scripts/build-sidecar.bat` 与 `scripts/build-release.bat`，并直接启动打包 sidecar 访问 `/health`，确认 API / Ollama / MySQL / ChromaDB 全绿。后续每次发布仍需按 `docs/release-checklist.md` §5.2 / §9 复测。

验收：

- ✅ 有体积和启动时间基线表（上）。
- ⏳ onedir/裁剪优化方案需构建后补测；当前结论是**暂不切换 onefile 默认**，收益不明显且风险高。
- ✅ onefile 基线通过 `pytest`/`npm build`/`cargo check`（见阶段总验收）；打包 smoke 待发布前按 `docs/release-checklist.md` 执行。

### M6 · 跨平台打包预研

目标：为 macOS/Linux 后续发布扫清未知项，但不阻塞 Windows 正式发布。

任务：

- [x] 梳理 macOS：
  - target triple。
  - `.app`/`.dmg`。
  - 代码签名和 notarization。
  - 配置目录。
  - Ollama/MySQL 安装说明。
- [x] 梳理 Linux：
  - AppImage/deb/rpm。
  - WebKitGTK 依赖。
  - system library 依赖。
  - 配置目录。
- [x] 设计跨平台 build-sidecar 脚本：
  - Windows `.bat` 保留。
  - macOS/Linux 用 shell 脚本。
  - 产物按 Tauri target triple 命名。
- [x] 文档注明 Windows 是第五阶段硬验收，macOS/Linux 是预研或后续阶段。

验收：

- 有跨平台差异清单。
- 有初版构建命令草案。
- 没有把未验证的 macOS/Linux 写成已支持。

---

## 5. 推荐开发顺序

1. M0：先补齐第五阶段文档和引用，避免继续引用不存在的文件。
2. M1：让 Windows 构建可复现，这是后续发布和 updater 的基础。
3. M2：跑通真实 updater，这是第五阶段最关键的闭环。
4. M3：处理签名和密钥，降低发布信任风险。
5. M4：建立安装/升级/卸载 QA，让每次发版可验证。
6. M5：再优化体积和启动速度，避免过早改动打包结构。
7. M6：最后做跨平台预研，不阻塞 Windows 首发。

---

## 6. 测试计划

### M0

- `rg "phase5-installer-updater" README.md docs apps scripts`
- 确认第五阶段文档路径一致。

### M1

- `scripts\release-check.bat`
- `scripts\build-release.bat`
- 检查 installer、`.sig`、manifest。

### M2

- 发布 v0.1.1 测试 Release。
- 从 v0.1.0 安装版点击检查更新。
- 验证签名失败场景。

### M3

- 检查 `.gitignore` 和 git status 中没有私钥。
- 运行 updater 签名构建。
- 若接入代码签名，运行 `signtool verify`。

### M4

- 干净机安装 smoke。
- 覆盖安装 smoke。
- 自动更新 smoke。
- 卸载 smoke。
- 迁移 smoke。

### M5

- onefile baseline。
- onedir prototype。
- 体积和启动时间对比。
- 打包 smoke。

### M6

- macOS/Linux 构建环境清单审阅。
- 不宣称未验证平台可用。

### 阶段总验收

- `pytest -q`
- `npm run build`
- `cargo check`
- `alembic current`
- `/health`
- `scripts\build-release.bat`
- 干净安装 smoke
- vN -> vN+1 updater smoke

---

## 7. 发布清单草案

每次发布至少记录：

```text
version:
date:
git_commit:
branch:

backend_tests:
frontend_build:
cargo_check:
alembic_current:
health_check:

sidecar_path:
sidecar_sha256:
installer_path:
installer_sha256:
signature_path:
latest_json_path:

release_url:
updater_smoke:
install_smoke:
upgrade_smoke:
known_issues:
rollback_plan:
```

---

## 8. 风险与控制

| 风险 | 控制方式 |
|---|---|
| updater 清单错误导致用户无法升级 | 先在测试 Release 验证；latest.json 发布前校验 URL、version、signature |
| 签名私钥泄漏 | 私钥不进仓库；使用本地安全目录或 CI secret；定期轮换 |
| 更新时 sidecar 占用文件 | 安装更新前主动 kill sidecar |
| 数据迁移破坏用户数据 | 发布前备份；升级 smoke；重大迁移前提示用户备份 |
| 构建脚本只适合单机 | 移除硬编码路径；缺依赖时输出安装提示 |
| onefile 首启慢 | 记录基线；评估 onedir；不牺牲稳定性 |
| 未签名安装包被拦截 | 文档透明提示；规划代码签名接入 |
| 跨平台承诺过早 | Windows 先硬验收；其他平台只写预研状态 |

---

## 9. 文档交付

第五阶段完成时至少更新：

- `README.md`
  - 第五阶段状态。
  - 安装包构建与发布流程。
  - 自动更新说明。
- `docs/usage-guide.md`
  - 最终用户安装、配置、更新、卸载。
  - 开发者发布流程。
  - 故障排查。
- `docs/phase5-requirements.md`
  - 勾选验收清单。
- `docs/phase5-plan.md`
  - 勾选里程碑任务。
- 可选新增：
  - `docs/release-checklist.md`
  - `docs/release-manifest.example.md`

---

## 10. 阶段结论

第五阶段的价值是“把能力送到用户手里，并且以后还能安全地更新它”。

当前项目已经不是缺功能，而是缺一条让普通用户稳定安装、让开发者稳定发布、让升级失败可回退的工程链路。先把 Windows 发布闭环做扎实，再谈跨平台和进一步依赖内置化，收益最大也最稳。
