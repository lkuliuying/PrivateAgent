# 私人助手 Agent · 第五阶段需求文档

> 第五阶段定位：把已经可本机开发运行、可用安装包启动的个人 Agent，打磨成可稳定分发、可升级、可诊断、可恢复的桌面产品。核心不是继续扩展 Agent 能力，而是补齐安装、更新、签名、发布验证和跨机器交付链路。

---

## 1. 背景

前四个产品阶段已经完成：

- 第一阶段：桌面端、FastAPI 后端、Ollama、MySQL、ChromaDB、聊天和知识库闭环。
- 第二阶段：受控工具调用、审批状态机、授权路径、活动流和工作台 UI。
- 第三阶段：项目工作区、学习系统、文档工作台、编码工具和多步任务。
- 第四阶段：长期记忆、学习复习、文档集合、patch set、任务计划 2.0、Provider 路由和备份恢复预览。

当前第五阶段已有基础：

- `scripts/build-sidecar.bat` 可用 PyInstaller 打包 Python 后端 sidecar。
- `scripts/build-release.bat` 可串联 sidecar 打包、MSVC 环境、可选 updater 签名和 Tauri NSIS 构建。
- `tauri.conf.json` 已配置 NSIS、`externalBin`、`createUpdaterArtifacts` 和 updater endpoint。
- `ConfigWizard.vue` 已实现首启依赖检测与连接配置。
- `lib.rs` 已实现 sidecar 按需启动、端口协商、配置读写、依赖探测、更新检查和安装命令。
- `UpdateChecker.vue` 已实现检查更新和下载安装入口。

但它还不能算一个可放心交给非开发者长期使用的发布版本：

1. 安装包未代码签名，Windows SmartScreen 仍会警告。
2. updater 的发布资产、签名清单和端到端升级路径仍需真实验证。
3. 构建脚本依赖本机固定路径和人工环境，不够可复现。
4. onefile sidecar 体积较大且首启需要解压，仍有优化空间。
5. 缺少干净机器安装、首次配置、升级、卸载、数据保留和回滚的系统测试矩阵。
6. macOS/Linux 只在路径逻辑上有预留，缺少实际产物、打包配置和验证。

第五阶段要解决的是：从“我这台机器能打包运行”升级为“可以发布、升级、排障和长期维护”。

---

## 2. 阶段目标

第五阶段完成后，产品应具备：

1. **可发布安装包**
   - Windows NSIS 安装包可在干净机器安装、启动、配置、卸载。
   - 安装包包含正确的 sidecar 二进制、桌面应用资源、updater 元数据。
   - 构建流程有明确命令、产物路径、版本号和发布清单。

2. **首启与运行时稳定**
   - 首次启动能检测 MySQL、Ollama 和模型可用性。
   - 用户填写连接后，应用能写入 `%APPDATA%\personal-assistant\.env` 并启动 sidecar。
   - sidecar 失败、端口冲突、依赖未启动、模型缺失时给出可执行提示。

3. **自动更新闭环**
   - 构建产物生成 updater 签名。
   - GitHub Release 或等价静态发布源提供 `latest.json`、安装包和 `.sig`。
   - 应用内“检查更新”能发现新版本、下载、安装并重启。
   - 更新前终止 sidecar，更新后保留本地数据和配置。

4. **签名与发布信任**
   - updater 签名密钥安全保存，不进入仓库。
   - Windows 代码签名方案明确，并接入发布流程或形成可执行采购/配置清单。
   - 安装包、签名文件、`latest.json`、版本号之间可校验。

5. **发布 QA 与回滚**
   - 发布前有固定验证矩阵：全量测试、前端构建、Rust 校验、安装包构建、干净机 smoke、升级 smoke。
   - 发布失败时能回滚 Release 资产或撤回 latest 指向。
   - 用户数据目录、数据库迁移和备份恢复路径有发布前检查。

6. **体积与跨平台准备**
   - Windows sidecar 体积、首启时间和启动日志可观测。
   - 评估 onefile 与 onedir 两种打包方式。
   - macOS/Linux 的打包差异、外部依赖和目标 triple 有明确计划。

---

## 3. 非目标

第五阶段不做：

- 不新增新的 Agent 业务能力，例如更多工具、更多学习功能或更强任务规划。
- 不做云同步账号体系。
- 不承诺完全无依赖安装。MySQL、Ollama 和模型仍作为本机外部依赖存在，除非后续另开“依赖内置化”阶段。
- 不把商业级 EV 证书、企业自动化发布平台作为硬性前置；可以先完成开源/个人项目可执行的发布闭环。
- 不把 macOS/Linux 作为 Windows 首个正式发布的阻塞项，但必须形成可追踪计划。

---

## 4. 用户场景

### 4.1 第一次安装

用户拿到 Windows 安装包：

1. 双击安装。
2. 首次启动进入连接配置向导。
3. 向导检测 MySQL 和 Ollama。
4. 用户填写数据库、Ollama 地址和模型名。
5. 点击测试连接，看到模型缺失或服务未启动提示。
6. 配置成功后进入主界面，状态页四项全绿。

### 4.2 普通升级

用户已经安装旧版本：

1. 在设置页点击检查更新。
2. 应用发现新版本，展示版本号、发布时间和更新说明。
3. 用户确认下载并安装。
4. 应用停止 sidecar，安装更新，重启。
5. 重启后旧会话、知识库、设置、记忆、任务仍可用。

### 4.3 发布维护

开发者准备发布新版本：

1. 更新版本号和 changelog。
2. 运行测试、构建和打包命令。
3. 生成安装包、`.sig` 和 `latest.json`。
4. 上传到 GitHub Release。
5. 在已安装旧版本的机器上验证应用内更新。
6. 如发现严重问题，撤回 Release 或把 `latest.json` 指回稳定版本。

### 4.4 故障排查

用户遇到安装或启动失败：

1. 状态页能说明是 API、Ollama、MySQL、ChromaDB 哪一项失败。
2. 打包模式日志能定位 sidecar spawn、迁移、端口监听或依赖连接错误。
3. 使用指南能给出常见问题处理步骤。
4. 用户可以重新打开连接配置向导修正配置。

---

## 5. 功能需求

### 5.1 Windows 安装包

需求：

- 使用 Tauri 2 NSIS 产出 Windows 安装包。
- 安装模式默认 currentUser，避免管理员权限成为初次使用障碍。
- 安装包包含：
  - Vue 前端构建产物。
  - Rust/Tauri 桌面壳。
  - PyInstaller sidecar 二进制。
  - updater 所需元数据。
- 安装后能创建开始菜单/桌面入口（按 Tauri 默认能力或显式配置）。
- 卸载时不默认删除用户数据目录，避免误删学习资料、知识库和配置。

验收：

- 干净 Windows 机器可安装成功。
- 安装后启动应用，进入向导或主界面。
- 卸载后应用程序文件被移除，用户数据目录保留或明确询问。

### 5.2 首启配置向导

需求：

- 首启或配置缺失时进入向导。
- 依赖检测包含：
  - MySQL 默认端口连通性。
  - Ollama `/api/tags` 连通性。
  - LLM 模型是否已拉取。
  - Embedding 模型是否已拉取。
- 连接配置包含：
  - MySQL host/port/user/password/database。
  - Ollama base URL。
  - LLM 模型名。
  - Embedding 模型名。
- 配置写入 `%APPDATA%\personal-assistant\.env`。
- 保存后启动 sidecar 并轮询 `/health`。

验收：

- 未配置时不会直接启动一个必然失败的 sidecar。
- 模型缺失时能提示 `ollama pull <model>`。
- 配置错误时用户能返回修改。
- 已配置用户可在设置页重新配置。

### 5.3 Sidecar 生命周期

需求：

- Tauri 负责按需启动 Python sidecar。
- 每次启动由 OS 分配本地空闲端口，并通过 `PA_API_PORT` 注入 sidecar。
- 前端动态读取端口，开发模式回退到手动后端 `127.0.0.1:8000`。
- 重试或重新配置时先终止旧 sidecar，避免孤儿进程。
- 应用退出和安装更新前必须终止 sidecar。
- sidecar 启动时执行 Alembic 迁移到 head；迁移失败不能导致桌面壳崩溃，但要在状态页暴露。

验收：

- 打包模式端口不固定占用 8000。
- 连续启动/退出三次不留下旧 sidecar 进程。
- 更新安装前 sidecar 被终止。
- 后端不可用时 UI 有明确错误。

### 5.4 自动更新

需求：

- Tauri updater active。
- `tauri.conf.json` 配置稳定 endpoint。
- 发布源提供符合 Tauri v2 updater 格式的 `latest.json`。
- 每个发布版本上传：
  - NSIS 安装包。
  - 安装包 `.sig`。
  - `latest.json`。
- 应用设置页提供检查更新、展示新版本、下载并安装、重启入口。
- 更新失败时保留当前版本可继续使用。

验收：

- 从 v0.1.0 升级到测试 v0.1.1 能成功。
- `latest.json` 中 version、url、signature 和实际资产匹配。
- 签名不匹配时更新被拒绝。
- 无更新时显示“当前已是最新版本”。

### 5.5 签名与密钥管理

需求：

- updater 私钥存放在用户本机安全路径或 CI secret，不进入 Git。
- 公钥写入 `tauri.conf.json`。
- 构建脚本能读取私钥和可选密码生成 `.sig`。
- Windows 代码签名方案形成明确清单：
  - 是否使用 OV/EV 证书。
  - 证书保存位置。
  - signtool 接入方式。
  - timestamp server。
- 未完成代码签名前，文档明确 SmartScreen 风险和绕过方式。

验收：

- 仓库不包含 updater 私钥。
- 构建时有私钥则生成 `.sig`。
- 发布文档说明如何验证 `.sig` 和 `latest.json`。
- 代码签名接入后安装包发布者信息正确。

### 5.6 发布流水线

需求：

- 一键本地发布脚本至少完成：
  - 构建 sidecar。
  - 前端 build。
  - Tauri NSIS build。
  - 生成 updater artifacts。
  - 输出产物路径。
- 脚本不应硬编码只适用于单台机器的工具路径；无法自动发现时给出明确错误。
- 发布清单记录：
  - 版本号。
  - Git commit。
  - 安装包文件名和 hash。
  - `.sig` 文件名。
  - `latest.json` 内容。
  - 测试结果。
- 可选接入 GitHub Actions，但本阶段可先以本地可复现发布为硬验收。

验收：

- 新机器按文档准备依赖后能跑通 release build。
- 发布产物和版本号一致。
- README 或 usage-guide 能指导完整发布步骤。

### 5.7 发布 QA

需求：

- 发布前必须通过：
  - `pytest -q`
  - `npm run build`
  - `cargo check`
  - `alembic current`
  - 健康检查
  - `scripts\build-release.bat`
- 安装包 smoke：
  - 干净安装。
  - 首启配置。
  - 进入主界面。
  - 发送普通聊天。
  - 导入一份小文档。
  - 退出后确认 sidecar 关闭。
- 升级 smoke：
  - 老版本安装。
  - 检查更新。
  - 下载并安装。
  - 重启后配置和数据仍在。

验收：

- 发布 checklist 可以逐项勾选。
- 发布失败原因可定位到测试、构建、签名、上传、更新检查或运行时。

### 5.8 体积与性能

需求：

- 记录 sidecar 文件大小、安装包大小和首次启动耗时。
- 评估 PyInstaller onefile 与 onedir：
  - onefile：分发简单，首启解压慢。
  - onedir：启动更快，Tauri resources 或外部资源管理更复杂。
- 评估是否能排除 `onnxruntime` 等大依赖；必须用实际运行验证 ChromaDB/Ollama embedding 不受影响。
- 不为减小体积牺牲可靠性。

验收：

- 有一份体积/启动时间对比记录。
- 若切换 onedir，打包模式能启动 sidecar 并完成健康检查。
- 若排除依赖，全量测试和打包 smoke 通过。

### 5.9 跨平台准备

需求：

- 梳理 Windows、macOS、Linux 的差异：
  - sidecar target triple。
  - 配置目录。
  - 安装包格式。
  - 代码签名/公证。
  - 外部依赖安装方式。
- 不同平台使用同一套后端业务逻辑。
- 平台差异集中在 Tauri 配置、构建脚本和文档中。

验收：

- macOS/Linux 有明确构建前置条件和待验证清单。
- Windows 发布不被跨平台工作阻塞。

---

## 6. 数据与配置需求

### 6.1 用户数据目录

Windows 打包模式默认使用：

```text
%APPDATA%\personal-assistant\
```

要求：

- `.env` 存在于用户数据目录。
- Chroma、日志、备份等运行时数据也应在用户数据目录或 `PA_DATA_DIR` 指定目录。
- 卸载默认不删除该目录。
- 更新不得覆盖该目录。

### 6.2 配置文件

`.env` 至少包含：

```text
PA_DB_URL=mysql+aiomysql://user:password@host:3306/personal_assistant?charset=utf8mb4
PA_OLLAMA_BASE_URL=http://127.0.0.1:11434
PA_LLM_MODEL=qwen2.5:14b-instruct-q4_K_M
PA_EMBED_MODEL=bge-m3
```

要求：

- 密码不打印到普通 UI。
- 配置向导读写字段必须与 Python `pydantic-settings` 的 `PA_` 前缀一致。
- 重新配置后应提示重启应用或自动重启。

### 6.3 数据迁移

要求：

- sidecar 启动时执行 `alembic upgrade head`。
- 发布前必须确认迁移 head 与代码模型匹配。
- 升级 smoke 必须覆盖“旧版本数据库 -> 新版本迁移”。
- 重大迁移前建议提示用户先备份。

---

## 7. API 与前端需求

第五阶段主要使用 Tauri 命令，不新增后端业务 API。

### 7.1 Tauri 命令

| 命令 | 用途 |
|---|---|
| `config_exists` | 判断是否已有连接配置 |
| `read_config` | 读取连接配置 |
| `write_config` | 写入连接配置 |
| `check_dependencies` | 探测默认 MySQL/Ollama |
| `test_connections` | 按表单配置测试连接和模型 |
| `start_sidecar` | 启动 sidecar 并返回协商端口 |
| `get_api_port` | 获取当前后端端口 |
| `check_for_updates` | 检查更新 |
| `download_and_install_update` | 下载并安装更新 |
| `relaunch_app` | 重启应用 |

### 7.2 前端页面

需求：

- `ConfigWizard.vue` 保持紧凑、可重试、错误可读。
- `UpdateChecker.vue` 在设置页可见。
- 启动状态机需要区分：
  - checking
  - wizard
  - starting
  - done
  - dev
  - error
- 错误提示不应只显示底层异常；需要给出下一步动作。

---

## 8. 安全要求

- updater 私钥不得提交到仓库。
- API key、数据库密码不得写进构建产物或文档示例的真实值。
- 自动更新必须验证签名。
- 下载更新必须使用 HTTPS 或受信任内网发布源。
- 更新安装前终止 sidecar，避免文件占用和旧进程继续使用旧代码。
- 安装包未代码签名前，必须在文档中透明说明风险。

---

## 9. 测试需求

### 9.1 单元与构建

- 后端：`pytest -q`
- 前端：`npm run build`
- Tauri：`cargo check`
- 迁移：`alembic upgrade head && alembic current`

### 9.2 打包验证

- `scripts\build-sidecar.bat`
- `scripts\build-release.bat`
- 检查产物：
  - `apps\desktop\src-tauri\binaries\personal-assistant-server-x86_64-pc-windows-msvc.exe`
  - `apps\desktop\src-tauri\target\release\bundle\nsis\*.exe`
  - 若配置签名：`*.sig`

### 9.3 手工 smoke

- 首装。
- 首启配置。
- 健康检查全绿。
- 普通聊天。
- 文档导入。
- 退出清理 sidecar。
- 卸载。
- 覆盖安装。
- 从旧版本自动更新。

---

## 10. 验收清单

第五阶段完成时必须满足（开发与文档已完成；标 ⏳ 的项需真实发布环境执行，见 `docs/release-checklist.md`）：

- [x] Windows NSIS 安装包可在干净机器安装和启动。（安装包可构建并已验证产物；干净机安装 smoke 待按 release-checklist 执行 ⏳）
- [x] 首启配置向导可完成 MySQL/Ollama/模型检测和 `.env` 写入。
- [x] 打包模式 sidecar 端口协商、启动、退出清理稳定。
- [x] 发布脚本能生成安装包、updater artifact 和发布清单。
- [ ] updater 发布源部署完成，应用内检查更新可从旧版本升级到新版本。 ⏳（`generate-latest-json.py` + 上传流程已就绪，待部署 GitHub Release 并跑通升级 smoke）
- [x] updater 签名验证通过，签名不匹配时更新被拒绝。（已校验公钥/私钥/签名一致；签名不匹配由 Tauri updater 内置校验拒绝，`UpdateChecker.vue` 分类提示）
- [x] Windows 代码签名方案已接入，或形成明确证书采购/配置计划并在发布说明中标注未签名风险。（方案见 `docs/signing-and-keys.md` §2；当前未签名，发布说明保留 SmartScreen 提示）
- [x] 发布前 QA checklist 可执行且记录结果。（`docs/release-checklist.md`）
- [ ] 升级后用户配置、数据库、知识库、记忆和备份不丢失。 ⏳（用户数据目录保留策略已明确；待升级 smoke 实测）
- [x] onefile/onedir 体积与启动时间评估完成。（`docs/phase5-plan.md` M5 基线表）
- [x] macOS/Linux 跨平台计划明确，不阻塞 Windows 正式发布。（`docs/cross-platform.md`）
- [x] README 和 usage-guide 与真实发布流程一致。

---

## 11. 定版结论

第五阶段的重点是把产品从“功能完整的本地 Agent”变成“能交付给真实用户长期使用的桌面软件”。

这一阶段的成功标准不是多做几个按钮，而是用户可以安装、配置、升级、排障；开发者可以稳定构建、签名、发布、回滚。完成后，后续再扩展多 Agent、云同步或更多平台，才有可靠的交付底座。
