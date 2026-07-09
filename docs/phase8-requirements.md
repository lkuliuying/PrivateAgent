# 私人助手 Agent · 第八阶段需求文档

> 第八阶段定位：把已经完成“可信赖日常操作层”的桌面 Agent，推进到“发布级质量与可扩展集成层”。重点不是继续堆新业务页面，而是补齐桌面端到端自动化、真实发布升级、代码签名、跨平台实测、性能基线和扩展注册机制，让项目从“本机可用”走向“可稳定发布、可持续回归、可安全扩展”。

---

## 1. 背景

前七个阶段已经完成：

- 第一阶段：桌面端、FastAPI 后端、Ollama、MySQL、ChromaDB、聊天与知识库闭环。
- 第二阶段：受控工具调用、审批状态机、授权路径、活动流和工作台 UI。
- 第三阶段：项目工作区、学习系统、文档工作台、编码工具和多步任务编排。
- 第四阶段：长期记忆、学习复习、文档集合、patch set、可编辑任务计划、Provider 路由和备份/恢复预览。
- 第五阶段：Windows 安装包、sidecar 生命周期、updater 清单、发布脚本、签名策略、发布 QA 与跨平台预研。
- 第六阶段：今日中枢、统一收件箱、提醒、长期目标、主动简报、隐私预览、Provider 调用审计和维护健康报告。
- 第七阶段：真实 Today、全局搜索、命令面板、快速捕获、OCR 队列、通知中心、诊断中心、Provider 失败分类、数据完整性体检和修复计划预览。

当前项目的主要不足来自现有代码、测试和发布文档：

1. **桌面端到端证据仍薄**：前端 `package.json` 只有 `dev/build/preview/tauri`，没有 Vitest、Playwright 或 Tauri 桌面 smoke；第七阶段主要由后端/API smoke 和 `npm run build` 保证。
2. **发布前校验不够产品化**：`scripts/release-check.bat` 只跑 pytest、npm build、cargo check、alembic current，尚未串联第七阶段 smoke、桌面启动、安装包构建、updater 清单校验和诊断包导出。
3. **真实升级链路未跑通**：发布清单仍要求部署 GitHub Release 并执行 vN -> vN+1 升级 smoke；目前工具就绪，但真实 Release 资产、升级、回滚和数据保留还缺实测记录。
4. **Windows 代码签名未接入**：`docs/signing-and-keys.md` 已写清 Authenticode 方案和签名顺序，但当前安装包仍未代码签名，SmartScreen 仍会拦截。
5. **macOS/Linux 仍停留在预研**：`docs/cross-platform.md` 明确 macOS/Linux 未实际构建或 smoke；`tauri.conf.json` 当前 bundle targets 只有 `nsis`，`generate-latest-json.py` 也只面向 Windows 单平台清单。
6. **性能和规模边界缺少持续量化**：第七阶段已有列表上限和部分分页，但 Today、全局搜索、诊断、完整性体检、Chroma/MySQL 一致性检查、大文档导入和长会话加载还缺固定性能基线与退化报警。
7. **扩展注册仍偏文档化**：第七阶段定义了 command、capture source、provider、notification target、diagnostic check、maintenance check 等扩展边界，但内置模块仍分散在各服务和路由里，缺少统一注册表、能力声明和冲突检测。
8. **外部生态接入还没有安全样板**：日历、邮件、浏览器剪藏、文件夹监听等真实日常输入源尚未接入；如果直接做完整同步会扩大隐私和稳定性风险，需要先做本地文件/导入型、只读、可撤销的集成样板。
9. **备份恢复仍偏“功能可用”，不是“升级可证明”**：恢复预览、诊断包和发布 checklist 已有，但缺少升级前自动备份建议、备份包校验、恢复演练和迁移失败后的可操作 runbook。
10. **版本与文档状态易漂移**：README、总需求、使用说明、发布清单、阶段文档数量已多；每次阶段推进都需要更强的文档索引、版本矩阵和“当前完成/后续增强”边界检查。

第八阶段要解决的是：把已经好用的本地私人助手变成“可以放心发布、放心升级、放心扩展”的产品，而不是再增加一批未经充分回归的新能力。

---

## 2. 阶段目标

第八阶段完成后，产品应具备：

1. **桌面端到端自动化证据**
   - 建立前端组件测试和 Playwright 浏览器模式 smoke。
   - 建立最小 Tauri 桌面 smoke，覆盖 sidecar 启动、端口协商、首屏 Today、诊断中心和退出清理。
   - 失败时输出截图、trace、前端日志、后端日志或诊断包路径。

2. **发布检查 2.0**
   - `release-check` 串联后端测试、前端构建、Rust 检查、迁移 head、桌面 smoke、诊断包脱敏、release manifest 校验和 updater 清单校验。
   - 支持 `--quick` / `--full` 或等价脚本，区分开发自检和发布前完整校验。
   - 发布清单自动记录版本、git commit、schema head、测试摘要、安装包 hash、签名状态和已知限制。

3. **真实升级与回滚演练**
   - 至少完成一个 vN -> vN+1 的 Windows 升级 smoke。
   - 验证旧配置、MySQL 数据、Chroma 数据、记忆、任务、通知、捕获和 OCR job 不丢失。
   - 验证签名错误、latest.json 错误、下载失败和回滚流程。

4. **Windows 代码签名接入或可替代透明策略**
   - 若证书可用，接入 `signtool sign` / `signtool verify`，并在代码签名后重新生成 Tauri updater `.sig`。
   - 若证书暂不可用，发布流程必须自动标记 unsigned，并在 release notes 与安装说明中保留 SmartScreen 风险提示。

5. **macOS/Linux 实测闭环**
   - 在至少一个 macOS 或 Linux 目标上完成 sidecar 构建、Tauri 构建、首启配置、`/health`、聊天和文档导入 smoke。
   - 修正平台数据目录、bundle targets、外部依赖检查和多平台 updater 清单策略。
   - 未实测平台继续明确标注，不写成已支持。

6. **性能基线与规模护栏**
   - 建立固定脚本测量 Today、全局搜索、文档导入、诊断快照、完整性体检、长会话加载、备份导出和启动时间。
   - 定义数据规模样本和阈值，例如 1000 条消息、500 个收件箱、100 个文档、5000 个切片。
   - 性能退化时给出报告，不直接阻塞开发；发布前超过硬阈值才失败。

7. **扩展注册机制落地**
   - 将 command action、capture source、provider、diagnostic check、maintenance check、notification target 抽象为可注册结构。
   - 内置模块先迁移到注册表，避免后续集成时散落修改多个页面和路由。
   - 注册项必须声明风险等级、权限、输入 schema、输出摘要和是否可出现在命令面板。

8. **安全的本地集成样板**
   - 优先做本地、只读、可撤销的集成样板，而不是云同步。
   - 候选样板：ICS 日历导入、浏览器书签/导出 HTML 导入、邮件 `.eml`/`.mbox` 文本导入、文件夹监听收件箱。
   - 每个集成必须走隐私预览、来源追踪、删除/撤销和诊断记录。

9. **备份恢复与迁移安全升级**
   - 升级前提示备份或自动生成备份建议。
   - 增强备份包 manifest 校验、schema 兼容检查、恢复演练记录和迁移失败 runbook。
   - 发布前至少执行一次“备份 -> 升级 -> 恢复预览 -> 数据完整性体检”路径。

10. **文档导航与版本矩阵**
   - 建立阶段索引和版本矩阵，说明当前版本、schema head、阶段完成度、发布状态和未完成边界。
   - README、`docs/requirements.md`、`docs/usage-guide.md`、`docs/release-checklist.md` 与阶段文档保持一致。

---

## 3. 非目标

第八阶段不做：

- 不做云账号、云同步和多设备同步。
- 不做完整手机 App。
- 不做无人值守的高风险自动化；命令、文件写入、远程发送仍需审批或显式设置。
- 不把所有外部生态一次性接完；只做 1-2 个本地、只读、可撤销的样板。
- 不承诺 macOS/Linux 全量发布，除非实机构建、签名/依赖、smoke 和文档都完成。
- 不把没有证书的 Windows 安装包写成“已可信签名”。
- 不以性能优化为由重写现有架构；优先测量、设阈值、针对热点优化。

---

## 4. 用户场景

### 4.1 发布前一键验证

开发者准备发布新版本：

1. 运行完整发布检查。
2. 脚本自动跑后端测试、前端构建、Rust 检查、迁移 head、桌面 smoke、诊断包脱敏和清单校验。
3. 失败时输出具体步骤、日志和截图路径。
4. 通过后生成可附到 Release 的验证摘要。

### 4.2 安装包升级不丢数据

用户已安装旧版本：

1. 新版本发布到 GitHub Release。
2. 旧版本在设置页检查更新。
3. 下载、签名验证、安装、重启。
4. 用户的会话、知识库、记忆、任务、收件箱、提醒、目标、捕获、OCR job 和配置都保留。
5. 升级后诊断中心显示 schema head 与版本一致。

### 4.3 Windows 安装不再被未知发布者吓住

用户下载安装包：

1. 若已接入代码签名，安装包显示明确发布者并通过 `signtool verify`。
2. 若暂未接入证书，下载页和安装说明明确提示 SmartScreen 风险和绕过方式。
3. 应用内 updater 仍校验 Tauri `.sig`，确保更新包未被篡改。

### 4.4 在 macOS 或 Linux 上完成最小可用路径

开发者在非 Windows 机器上验证：

1. 构建平台对应 sidecar。
2. 构建 Tauri 包。
3. 首启配置 Ollama 和 MySQL。
4. `/health` 全绿。
5. 完成一次聊天和一次小文档导入。
6. 文档明确该平台验证状态和剩余限制。

### 4.5 安全集成一个本地输入源

用户想把外部信息放进助手：

1. 导入本地 ICS、书签 HTML、`.eml` 或指定文件夹。
2. 系统先展示隐私预览和解析摘要。
3. 用户确认后进入 capture/inbox/document。
4. 来源可追溯，误导入可撤销。

---

## 5. 功能需求

### 5.1 桌面 E2E 与组件测试

需求：

- 引入前端测试工具链：
  - Vitest 或等价组件测试。
  - Playwright 浏览器模式 smoke。
  - Tauri 桌面 smoke 可使用 WebDriver、Playwright 控制 dev server，或先以脚本方式验证 sidecar/窗口/端口契约。
- 覆盖关键组件：
  - CommandPalette。
  - GlobalSearch。
  - CapturePanel。
  - NotificationCenter。
  - ConfirmDialog。
  - DiagnosticsView。
  - TodayView。
- 覆盖用户路径：
  - 首屏进入 Today。
  - 后端断开提示。
  - 全局搜索打开并返回结果。
  - 快速捕获转收件箱。
  - 诊断包导出。
  - 退出后 sidecar 清理。
- 失败输出：
  - screenshot。
  - trace 或 video。
  - 前端 console。
  - 后端日志或诊断包路径。

验收：

- `npm run test` 或等价命令可运行组件/单元测试。
- `npm run e2e` 或等价命令可运行至少一条用户路径 smoke。
- 发布 checklist 引用这些命令。

### 5.2 发布检查 2.0

需求：

- 扩展或新增发布检查脚本：
  - `scripts/release-check.bat` 保持快速检查。
  - 新增 full 模式或 `scripts/release-check-full.bat`。
- full 模式串联：
  - `uv run pytest -q`。
  - `npm run build`。
  - 前端测试。
  - 桌面 smoke。
  - `cargo check`。
  - `uv run alembic current`。
  - `git diff --check`。
  - 诊断包脱敏验证。
  - release manifest 校验。
  - latest.json 与 `.sig` 校验。
- 输出结构化摘要：
  - JSON。
  - Markdown。
  - 可复制到 Release notes 的文本。

验收：

- 发布前可一条命令得到完整验证结果。
- 任一步失败时退出码非 0。
- release manifest 中能看到 phase8 验证摘要。

### 5.3 真实升级 smoke 与回滚

需求：

- 准备两个版本的测试路径：
  - 旧版本安装并写入样本数据。
  - 新版本发布为 GitHub Release 或本地等价更新源。
- 验证：
  - 更新发现。
  - 签名验证。
  - 下载与安装。
  - 重启后版本变化。
  - 数据保留。
  - schema 升级。
  - 诊断中心状态。
- 负面场景：
  - latest.json 签名错误。
  - 安装包 hash 不匹配。
  - 下载失败。
  - 迁移失败。
  - 回滚到旧 Release。

验收：

- 至少完成一次 Windows vN -> vN+1 升级 smoke。
- 发布清单记录旧版本、新版本、数据样本、结果和失败截图/日志。

### 5.4 Windows 代码签名

需求：

- 支持两种路径：
  - 有证书：接入 Authenticode 签名。
  - 无证书：自动标记 unsigned 并生成透明风险说明。
- 有证书时流程必须遵守：
  - 先生成安装包。
  - `signtool sign` 修改安装包字节。
  - `signtool verify /pa /v`。
  - 再对最终安装包重新生成 Tauri updater `.sig`。
  - 再生成 `latest.json`。
- 私钥、证书、密码不得入库。

验收：

- 有证书环境下签名和验证通过。
- 无证书环境下构建不中断，但 release manifest 标记 `code_signed: no`。
- 文档说明签名状态和 SmartScreen 行为。

### 5.5 macOS / Linux 实测

需求：

- macOS：
  - 支持 `.app` / `.dmg` targets。
  - sidecar 文件名按 target triple。
  - 数据目录改为或确认 `~/Library/Application Support/personal-assistant`。
  - 记录 Gatekeeper、代码签名和 notarization 状态。
- Linux：
  - 支持 AppImage 或 deb 至少一种。
  - 文档列出 WebKitGTK 4.1 和构建依赖。
  - 验证运行期依赖缺失时的错误提示。
- updater：
  - `latest.json` 支持多平台 `platforms`。
  - 每个平台资产有独立 URL 与签名。

验收：

- 至少一个非 Windows 平台完成 sidecar 构建、Tauri 构建和 smoke。
- 未完成平台保持“未实测”标记。
- `docs/cross-platform.md` 更新为实测状态表。

### 5.6 性能基线与规模护栏

需求：

- 新增性能脚本或测试：
  - 构造样本数据。
  - 测 Today 聚合。
  - 测全局搜索。
  - 测文档导入。
  - 测诊断快照。
  - 测完整性体检。
  - 测备份导出。
  - 测 sidecar 冷启动和热启动。
- 输出：
  - Markdown 报告。
  - JSON 原始数据。
  - 与上次基线对比。
- 定义阈值：
  - 开发提醒阈值。
  - 发布阻断阈值。

验收：

- 有可重复的性能基线报告。
- 发布 checklist 引用关键性能结果。
- 至少一个热点路径有优化或明确后续计划。

### 5.7 扩展注册表

需求：

- 新增注册结构：
  - command action registry。
  - capture source registry。
  - provider registry。
  - diagnostic check registry。
  - maintenance check registry。
  - notification target registry。
- 注册项声明：
  - id。
  - title。
  - description。
  - risk level。
  - permissions。
  - input schema。
  - output summary。
  - UI entry。
  - enabled/default state。
- 内置能力先迁移到注册表：
  - 生成今日简报。
  - 新建收件箱。
  - 新建提醒。
  - 运行健康检查。
  - 导出诊断包。
  - 数据完整性体检。

验收：

- 新增一个 command action 不需要同时改多个组件。
- 新增一个 diagnostic check 后可同时出现在诊断中心和诊断包。
- 注册冲突、重复 id、缺权限声明会在测试中失败。

### 5.8 本地集成样板

需求：

- 至少选择一个本地集成样板：
  - ICS 日历导入。
  - 浏览器书签 HTML 导入。
  - `.eml` / `.mbox` 邮件文本导入。
  - 文件夹监听到 capture/inbox。
- 必须满足：
  - 本地只读。
  - 隐私预览。
  - 来源追踪。
  - 可撤销。
  - 不默认外发。
  - 可诊断。
- 集成结果进入现有系统：
  - capture。
  - inbox。
  - reminder。
  - document。
  - task draft。

验收：

- 至少一个本地集成样板跑通。
- 用户能预览、确认、撤销。
- 诊断中心能显示最近集成失败。

### 5.9 备份、恢复与迁移安全

需求：

- 发布前支持备份建议：
  - 检测 schema 变更。
  - 提示用户升级前备份。
  - 可生成备份校验摘要。
- 备份包增强：
  - manifest schema。
  - app version。
  - schema head。
  - included modules。
  - checksum。
- 恢复演练：
  - 恢复预览。
  - 数据完整性体检。
  - Chroma/MySQL 一致性检查。
  - 失败 runbook。

验收：

- 发布前能生成备份建议或备份校验摘要。
- 至少一次恢复预览 + 完整性体检路径通过。
- 迁移失败时诊断中心给出明确下一步。

### 5.10 文档导航与版本矩阵

需求：

- 新增或更新：
  - 阶段索引。
  - 版本矩阵。
  - schema head 矩阵。
  - 发布状态矩阵。
  - 未完成边界表。
- README、总需求、使用说明、发布清单和阶段文档保持一致。
- 历史文档若不再是入口，必须明确标为历史归档或 redirect。

验收：

- 新读者能从 README 找到当前阶段、当前版本、发布状态和下一阶段计划。
- `rg "未实现|后续增强|规划"` 不会出现误导性完成状态。
- 阶段 8 完成前所有 checklist 保持未勾选。

---

## 6. 数据需求

建议新增或扩展的数据结构：

| 数据结构 | 用途 |
|---|---|
| `test_runs` | 记录发布检查、E2E、性能基线和 smoke 结果摘要 |
| `release_artifacts` | 记录安装包、sidecar、latest.json、签名、hash 和平台 |
| `upgrade_smoke_runs` | 记录升级前后版本、样本数据和结果 |
| `integration_sources` | 本地集成源配置与状态 |
| `integration_imports` | 每次导入的来源、摘要、目标对象和可撤销信息 |
| `extension_registry_items` | 可选：持久化扩展注册项状态、启用状态和风险等级 |

数据要求：

- 测试与发布记录只保存摘要和路径，不保存完整日志中的敏感内容。
- 集成源不得保存敏感凭据；第八阶段只做本地文件型集成。
- 升级 smoke 样本数据必须可重建，不依赖用户真实隐私数据。
- release artifact 记录必须包含 sha256。

---

## 7. API 需求

建议新增或扩展路由：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/testing/runs` | 查看最近发布检查、E2E、性能运行摘要 |
| POST | `/testing/diagnostic-smoke` | 触发诊断包脱敏 smoke（仅本地/dev） |
| GET | `/release/artifacts` | 查看本机生成过的发布产物摘要 |
| POST | `/integrations/import` | 执行本地集成导入 |
| GET | `/integrations/sources` | 查看本地集成源 |
| DELETE | `/integrations/imports/{id}` | 撤销一次导入（若目标支持） |
| GET | `/extensions` | 查看注册的命令、诊断、维护、Provider、capture source |
| PATCH | `/extensions/{id}` | 启用/禁用可配置扩展 |

注意：

- 测试/发布类 API 默认只在开发模式或本地授权下可用。
- 集成导入必须复用 trusted paths 和隐私预览。
- 扩展启用/禁用不得绕过审批边界。

---

## 8. 前端需求

建议新增或调整：

- `TestRunsPanel.vue`
  - 展示最近 release-check、E2E、性能基线、升级 smoke。
- `ReleaseStatusPanel.vue`
  - 展示版本、schema head、签名状态、latest.json 状态、平台资产。
- `ExtensionRegistryPanel.vue`
  - 展示 command/capture/provider/diagnostic/maintenance 注册项。
- `IntegrationImportPanel.vue`
  - 本地集成导入、隐私预览、目标选择、撤销记录。
- `BackupUpgradePanel.vue`
  - 升级前备份建议、备份校验、恢复演练摘要。
- `DiagnosticsView.vue`
  - 增加发布检查摘要、性能基线摘要和集成失败摘要。

---

## 9. 安全与隐私要求

- 所有本地集成必须先走 trusted paths 或文件选择器授权。
- 集成导入前必须展示隐私预览。
- 发布检查、E2E 和诊断包不得泄露 API key、数据库密码、完整聊天内容、完整文档原文或敏感记忆。
- 代码签名证书、私钥、密码不得入库。
- 扩展注册项必须声明风险等级和权限。
- 命令面板和扩展注册不得绕过现有审批状态机。
- 升级 smoke 使用合成数据，不使用用户真实隐私数据。

---

## 10. 测试需求

### 10.1 后端

- `uv run pytest -q`
- 新增测试：
  - 扩展注册重复 id 和缺权限声明失败。
  - 本地集成导入预览、确认、撤销。
  - 备份 manifest 校验。
  - release artifact 摘要生成。
  - 诊断包脱敏 smoke。
  - 性能脚本样本数据生成。

### 10.2 前端

- `npm run build`
- 新增：
  - Vitest/组件测试。
  - Playwright 浏览器 smoke。
  - 关键组件键盘操作测试。
  - 失败截图/trace 输出。

### 10.3 Tauri / 打包

- `cargo check`
- 新增：
  - Tauri dev smoke。
  - sidecar 启动/退出清理 smoke。
  - 安装包构建校验。
  - latest.json 与 `.sig` 校验。
  - 代码签名验证（有证书时）。

### 10.4 发布与升级

- Windows vN -> vN+1 升级 smoke。
- latest.json 负面场景。
- 签名错误场景。
- 数据保留检查。
- 回滚 runbook 演练。

---

## 11. 验收清单

第八阶段完成时必须满足：

- [x] 至少一条 Playwright 或等价前端 smoke 可重复运行。
- [x] 至少一条 Tauri/sidecar smoke 覆盖端口协商、首屏和退出清理。
- [x] 前端组件测试覆盖 CommandPalette、CapturePanel、NotificationCenter、DiagnosticsView 中至少三个。
- [x] 发布检查 2.0 串联后端、前端、Rust、迁移、桌面 smoke、清单校验。
- [x] release manifest 自动记录测试摘要、schema head、平台、hash 和签名状态。
- [ ] Windows vN -> vN+1 升级 smoke 至少通过一次。（工具与 runbook 已就绪，待真实环境执行）
- [x] Windows 代码签名接入；若无证书，则 unsigned 状态和 SmartScreen 风险自动写入发布说明。
- [x] 至少一个非 Windows 平台完成构建与 smoke，或文档明确仍未实测且不宣称支持。
- [x] 性能基线脚本能输出 Today、搜索、诊断、完整性体检、启动时间结果。
- [x] 扩展注册表覆盖 command、diagnostic、maintenance 至少三类。
- [x] 至少一个本地集成样板完成隐私预览、导入、来源追踪和撤销。
- [x] 备份 manifest 校验和恢复预览 + 完整性体检路径通过。
- [x] README、`docs/requirements.md`、`docs/usage-guide.md`、`docs/release-checklist.md` 更新第八阶段状态。
- [x] `uv run pytest -q`、`npm run build`、`cargo check`、`uv run alembic current`、`git diff --check` 通过。

> 13/14 已满足；唯一未勾选项「Windows vN->vN+1 升级 smoke 至少通过一次」需真实 Windows 环境构建两份安装包并运行 updater，工具（`scripts/upgrade_smoke.py`）与 runbook 已就绪，标注「待真实环境执行」，与第五阶段同款处理。

---

## 12. 定版结论

第八阶段的价值是把“功能完整、日常可信”推进到“发布可信、升级可信、扩展可信”。它应优先补自动化证据、真实升级、签名信任、跨平台实测、性能基线和扩展注册，而不是继续增加未经回归的新业务面。

完成后，项目应该能回答三个问题：这个版本能不能发布？升级会不会丢数据？新增集成会不会破坏隐私和审批边界？如果这三个问题都有可重复证据，第八阶段就算成功。
