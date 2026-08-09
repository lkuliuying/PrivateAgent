# 私人助手 Agent · 第八阶段开发计划书

> 对应 `docs/archive/phases/phase8-requirements.md`。第八阶段定位为“发布级质量与可扩展集成层”：在第七阶段完成可信赖日常操作层后，补齐桌面 E2E、发布检查 2.0、真实升级 smoke、代码签名、跨平台实测、性能基线、扩展注册和本地集成样板。

---

## 完成状态（M0–M10）

第八阶段已完成 M0–M10，验证证据：`pytest -q` 256 通过、`npm run build`、`npm run test`(13)、`npm run e2e`(2)、`cargo check`、`alembic current -> 0011 (head)`、`git diff --check` 通过；迁移 `0011_phase8_release_quality_extensions.py`。

| 里程碑 | 状态 | 交付 |
|---|---|---|
| M0 文档与范围 | ✅ | phase8 需求/计划/README/requirements/usage-guide 同步 |
| M1 前端测试与桌面 smoke | ✅ | Vitest(13) + Playwright E2E(2) + `scripts/sidecar_smoke.py` |
| M2 发布检查 2.0 | ✅ | `scripts/release-check-full.bat` + `run_release_checks.py`（JSON/MD 报告） |
| M3 升级 smoke 与回滚 | 🔧 | `scripts/upgrade_smoke.py` + `/testing/*` 路由 + runbook（真实升级待真实环境执行） |
| M4 代码签名 | ✅ | `scripts/sign_installer.py`（signtool + 重签 .sig + unsigned 透明策略） |
| M5 macOS/Linux 实测 | 🔧 | config.py/lib.rs macOS 数据目录修正 + 多平台 latest.json（实机构建待真实环境） |
| M6 性能基线 | ✅ | `scripts/measure_perf_baseline.py` + 热点优化与后续方案 |
| M7 扩展注册表 | ✅ | `core/extensions.py` + `/extensions` API + `ExtensionRegistryPanel.vue` |
| M8 本地集成样板 | ✅ | ICS 日历导入 + `/integrations` API + `IntegrationImportPanel.vue` |
| M9 备份恢复与迁移安全 | ✅ | manifest 增强 + `/backup/restore/drill` + `/backup/migration-runbook` + `BackupUpgradePanel.vue` |
| M10 文档矩阵收束 | ✅ | README/requirements/usage-guide/release-checklist/cross-platform/signing-and-keys 同步 + 版本矩阵 |

> 🔧 = 工具/脚本/逻辑测试已就绪，真实环境执行部分（真装两份安装包升级、signtool 实签、非 Windows 实机构建）待真实环境执行，与第五阶段同款处理，不宣称已完成。

---

## 1. 阶段判断

当前项目已经具备：

1. **完整产品能力**
   - 聊天、知识库、项目、学习、任务、记忆、今日、设置/诊断八个入口。
   - Today、全局搜索、命令面板、快速捕获、OCR 队列、通知中心、诊断中心、数据完整性体检。

2. **发布工程基础**
   - Windows sidecar、NSIS 构建、updater `.sig`、`latest.json`、发布清单、发布 checklist。
   - `scripts/release-check.bat` 可运行 pytest、npm build、cargo check、alembic current。

3. **测试基础**
   - 后端 pytest 覆盖阶段 1-7 主流程。
   - 第七阶段已有 Today、搜索、捕获/OCR、通知、诊断、完整性、Provider 测试。

4. **文档基础**
   - README、总需求、使用说明、发布清单和 phase1-7 文档已经形成阶段链。
   - 跨平台、签名、发布 QA 都有预研文档。

主要缺口：

| 缺口 | 影响 | 第八阶段对应 |
|---|---|---|
| 没有前端组件测试和桌面 E2E | UI 回归只能靠 build 和人工点 | M1 |
| release-check 没有桌面 smoke/清单校验/诊断包校验 | 发布前证据不完整 | M2 |
| GitHub Release 升级 smoke 未实测 | updater 是否保数据仍缺真实证据 | M3 |
| Windows 代码签名未接入 | SmartScreen 拦截，信任不足 | M4 |
| macOS/Linux 仅预研 | 不能宣称跨平台可用 | M5 |
| 性能基线不持续 | 规模增长后退化难发现 | M6 |
| 扩展边界未落地成注册表 | 后续集成会继续散落改代码 | M7 |
| 外部输入源无安全样板 | 日历/邮件/浏览器接入风险大 | M8 |
| 备份恢复缺升级演练 | 迁移失败时用户恢复路径不够硬 | M9 |
| 文档数量增多，状态易漂移 | 入口文档可能互相矛盾 | M10 |

---

## 2. 总体目标

第八阶段交付后，项目应能完成四个代表场景：

### 场景 A：发布前一键得到证据

1. 开发者运行 full release check。
2. 自动完成后端测试、前端构建、组件/E2E、Tauri smoke、迁移、清单、签名和诊断包校验。
3. 失败时定位到步骤、日志、截图或诊断包。
4. 通过时生成 Release 可复制摘要。

### 场景 B：真实升级不丢数据

1. 旧版本安装并写入样本数据。
2. 新版本发布为 GitHub Release 或本地等价更新源。
3. 应用内检查更新、下载、验证、安装、重启。
4. 验证旧数据、配置、schema、知识库、记忆、任务、通知、捕获与 OCR job 保留。

### 场景 C：非 Windows 平台有实测状态

1. 在 macOS 或 Linux 上构建 sidecar。
2. 构建 Tauri 包。
3. 首启配置、`/health` 全绿。
4. 聊天和小文档导入 smoke 通过。
5. 文档写清已支持、未支持和未实测边界。

### 场景 D：新增集成不破坏隐私边界

1. 通过注册表新增一个本地输入源。
2. 用户授权本地文件或目录。
3. 系统展示隐私预览。
4. 导入后来源可追踪、可撤销、可诊断。

---

## 3. 里程碑

### M0 · 第八阶段文档与范围校准

目标：把第八阶段定位为质量、发布和扩展治理阶段。

任务：

- [ ] 新增 `docs/archive/phases/phase8-requirements.md`。
- [ ] 新增 `docs/archive/phases/phase8-plan.md`。
- [ ] 更新 README 阶段引用。
- [ ] 更新 `docs/requirements.md` 阶段表。
- [ ] 更新 `docs/usage-guide.md` 后续路线图。
- [ ] 明确第八阶段不做云同步、不做手机端、不一次性接入所有外部生态。

验收：

- 第八阶段需求文档和计划书是两份独立文档。
- 文档基于当前仓库缺口：无前端测试、无桌面 E2E、签名未接入、跨平台未实测、升级 smoke 未跑通。
- 未实现内容保持未勾选。

### M1 · 前端测试与桌面 smoke

目标：给桌面 UI 和关键路径自动化回归证据。

任务：

- [ ] 引入前端测试工具：
  - Vitest 或等价组件测试。
  - Playwright 浏览器 smoke。
- [ ] 新增 npm scripts：
  - `test`
  - `test:watch`
  - `e2e`
  - `e2e:headed` 或等价命令。
- [ ] 组件测试覆盖：
  - CommandPalette。
  - GlobalSearch。
  - CapturePanel。
  - NotificationCenter。
  - DiagnosticsView。
- [ ] E2E smoke 覆盖：
  - Today 首屏。
  - 全局搜索。
  - 快速捕获。
  - 诊断中心。
  - 后端断开提示。
- [ ] Tauri/sidecar smoke：
  - 启动 sidecar。
  - 获取端口。
  - `/health`。
  - 退出清理。
- [ ] 失败输出截图、trace 和日志路径。

验收：

- 本地可运行前端测试。
- 至少一条 E2E smoke 可重复运行。
- 至少一条 sidecar/端口协商 smoke 可重复运行。

### M2 · 发布检查 2.0

目标：把发布前检查从“编译与测试”升级为“可发布证据包”。

任务：

- [ ] 保留 `scripts/release-check.bat` 作为 quick check。
- [ ] 新增 `scripts/release-check-full.bat` 或支持参数模式。
- [ ] full check 串联：
  - `uv run pytest -q`
  - `npm run build`
  - `npm run test`
  - `npm run e2e`
  - `cargo check`
  - `uv run alembic current`
  - `git diff --check`
  - 诊断包脱敏 smoke
  - release manifest 校验
  - latest.json 与 `.sig` 校验
- [ ] 输出：
  - `dist/release-check-<version>.json`
  - `dist/release-check-<version>.md`
- [ ] `generate_release_manifest.py` 读取 full check 结果。

验收：

- 一条命令产出发布检查摘要。
- 任一步失败时退出码非 0。
- 发布清单模板包含 phase8 check。

### M3 · 真实升级 smoke 与回滚演练

目标：证明 updater 不只是能生成清单，而是真的能升级且保数据。

任务：

- [ ] 准备旧版本样本数据：
  - 会话。
  - 文档。
  - 记忆。
  - 任务。
  - 收件箱。
  - 提醒。
  - 目标。
  - 通知。
  - capture / OCR job。
- [ ] 构建新版本安装包、`.sig`、`latest.json`。
- [ ] 部署 GitHub Release 或本地等价更新源。
- [ ] 跑 vN -> vN+1：
  - 检查更新。
  - 下载。
  - 安装。
  - 重启。
  - 数据保留检查。
  - schema head 检查。
- [ ] 负面场景：
  - 签名错误。
  - latest.json 缺字段。
  - 下载失败。
  - 回滚旧版本。
- [ ] 输出升级 smoke 报告。

验收：

- 至少一次 Windows 升级 smoke 通过。
- 负面场景不破坏当前可用版本。
- 报告记录版本、路径、样本数据和结果。

### M4 · Windows 代码签名与信任策略

目标：接入或透明处理 Windows Authenticode 信任问题。

任务：

- [ ] 支持证书配置：
  - `.pfx` / `.p12` 路径。
  - 密码来源。
  - 时间戳服务器。
- [ ] build-release 接入签名顺序：
  - tauri build。
  - signtool sign。
  - signtool verify。
  - 重新生成 Tauri updater `.sig`。
  - 生成 latest.json。
- [ ] 无证书时：
  - 不阻塞个人构建。
  - release manifest 标记 unsigned。
  - release notes 自动保留 SmartScreen 说明。
- [ ] 更新 `docs/signing-and-keys.md` 与 `docs/release-checklist.md`。

验收：

- 有证书环境签名与 verify 通过。
- 无证书环境说明清晰、不误报已签名。
- `.sig` 与最终安装包字节一致。

### M5 · macOS/Linux 最小实测

目标：把跨平台从预研推进到至少一个非 Windows 平台的真实 smoke。

任务：

- [ ] 更新 Tauri bundle targets：
  - macOS：`app` / `dmg`。
  - Linux：`appimage` 或 `deb`。
- [ ] 修正平台数据目录：
  - macOS 使用 `~/Library/Application Support/personal-assistant` 或文档明确当前路径。
  - Linux 遵循 XDG。
- [ ] 扩展 `generate-latest-json.py`：
  - 多平台 `platforms`。
  - 多资产 URL。
  - 多 `.sig`。
- [ ] 在 macOS 或 Linux 实机执行：
  - `scripts/build-sidecar.sh`。
  - Tauri build。
  - 首启配置。
  - `/health`。
  - 聊天。
  - 文档导入。
- [ ] 更新 `docs/cross-platform.md`。

验收：

- 至少一个非 Windows 平台有实测记录。
- 未验证平台继续标注未实测。
- 多平台清单生成逻辑有测试。

### M6 · 性能基线与规模护栏

目标：让性能从主观感受变成可重复数字。

任务：

- [ ] 新增样本数据生成脚本：
  - 1000 条消息。
  - 500 个 inbox item。
  - 100 个文档。
  - 5000 个 doc_chunks。
  - 200 条通知。
  - 100 条完整性发现项。
- [ ] 新增性能测量：
  - Today 聚合。
  - 全局搜索。
  - 文档导入。
  - 诊断快照。
  - 完整性体检。
  - 备份导出。
  - sidecar 冷/热启动。
- [ ] 输出报告：
  - JSON。
  - Markdown。
- [ ] 定义阈值：
  - warning。
  - release blocker。
- [ ] 对发现的热点做至少一处优化或给出后续方案。

验收：

- 性能基线脚本可重复运行。
- 报告被 release checklist 引用。
- 关键路径超过阈值时能被发现。

### M7 · 扩展注册表落地

目标：把第七阶段的扩展边界变成真实代码结构。

任务：

- [ ] 设计注册项模型：
  - id。
  - title。
  - kind。
  - risk。
  - permissions。
  - input schema。
  - output summary。
  - enabled。
- [ ] 新增注册表：
  - command actions。
  - capture sources。
  - providers。
  - diagnostic checks。
  - maintenance checks。
  - notification targets。
- [ ] 迁移内置项：
  - 新建提醒。
  - 新建收件箱。
  - 生成今日简报。
  - 运行健康检查。
  - 导出诊断包。
  - 完整性体检。
- [ ] 新增 `/extensions` API。
- [ ] 新增 `ExtensionRegistryPanel.vue`。
- [ ] 测试重复 id、缺权限声明、禁用项不执行。

验收：

- 新增一个 command action 不需要改多个页面。
- diagnostic check 同时出现在诊断中心和诊断包。
- 注册冲突有测试。

### M8 · 本地集成样板

目标：建立一个安全外部输入源接入模式。

任务：

- [ ] 选择一个样板：
  - ICS 日历导入。
  - 浏览器书签 HTML 导入。
  - `.eml` / `.mbox` 邮件文本导入。
  - 文件夹监听导入。
- [ ] 设计解析流程：
  - 文件授权。
  - 隐私预览。
  - 用户确认。
  - 创建目标对象。
  - 来源追踪。
  - 撤销。
- [ ] 进入现有对象：
  - capture。
  - inbox。
  - reminder。
  - document。
- [ ] 失败进入诊断/通知。
- [ ] 新增集成测试。

验收：

- 至少一个本地集成样板可用。
- 可预览、确认、撤销。
- 不默认外发。

### M9 · 备份恢复与迁移安全

目标：让升级前后的数据安全有可操作证据。

任务：

- [ ] 增强备份 manifest：
  - app version。
  - schema head。
  - module list。
  - checksum。
  - created_at。
- [ ] 升级前备份建议：
  - 检测 schema 变化。
  - 提示备份。
  - 记录用户选择。
- [ ] 恢复演练：
  - 恢复预览。
  - 完整性体检。
  - Chroma/MySQL 一致性检查。
- [ ] 迁移失败 runbook：
  - MySQL 不可用。
  - Alembic 失败。
  - Chroma 不一致。
  - 备份包不兼容。

验收：

- 备份包可校验。
- 升级前有备份建议或记录。
- 至少一次恢复预览 + 完整性体检路径通过。

### M10 · 文档导航、版本矩阵与阶段收束

目标：防止阶段文档和真实状态漂移。

任务：

- [ ] 新增或更新阶段索引：
  - 当前版本。
  - 当前 schema head。
  - 阶段完成度。
  - 发布状态。
  - 未完成边界。
- [ ] 更新：
  - `README.md`。
  - `docs/requirements.md`。
  - `docs/usage-guide.md`。
  - `docs/release-checklist.md`。
  - `docs/cross-platform.md`。
  - `docs/signing-and-keys.md`。
- [ ] 标记历史文档：
  - phase4 sidecar research。
  - phase5 installer/updater historical redirect。
- [ ] 运行文档一致性检查：
  - 阶段引用。
  - schema head。
  - 未实现边界。
  - 旧文件名。

验收：

- README 可以导航到第八阶段需求和计划。
- 总需求和使用说明包含第八阶段状态。
- 未完成项不写成已完成。

---

## 4. 推荐开发顺序

1. M0：先写清第八阶段范围，避免偏成新功能堆叠。
2. M1：先补前端/桌面 smoke，因为后续发布检查要依赖它。
3. M2：把 release-check 升级为 full evidence pipeline。
4. M3：跑真实升级 smoke，验证 updater 和数据保留。
5. M4：接入代码签名或完善 unsigned 透明策略。
6. M6：补性能基线，给发布质量一组数字。
7. M7：落地扩展注册表，降低后续集成复杂度。
8. M8：基于注册表做一个本地集成样板。
9. M9：补备份恢复与迁移演练。
10. M5：跨平台实测可与 M3/M4 并行，但不阻塞 Windows 发布质量。
11. M10：最后收束文档、矩阵和验收证据。

---

## 5. 测试计划

### M1

- 组件测试。
- Playwright smoke。
- Tauri/sidecar smoke。
- 失败截图/trace。

### M2

- quick/full release-check。
- 失败退出码。
- JSON/Markdown 摘要。
- release manifest 消费摘要。

### M3

- 正常升级。
- 签名错误。
- latest.json 缺字段。
- 下载失败。
- 回滚。
- 数据保留。

### M4

- signtool sign。
- signtool verify。
- 重新生成 `.sig`。
- 无证书 fallback。
- 私钥/证书不入库检查。

### M5

- macOS 或 Linux sidecar build。
- Tauri build。
- 首启配置。
- `/health`。
- 聊天。
- 文档导入。

### M6

- 样本数据生成。
- Today 性能。
- 搜索性能。
- 诊断性能。
- 完整性体检性能。
- 启动性能。

### M7

- 注册项 schema。
- 重复 id。
- 缺权限声明。
- 禁用项不执行。
- 命令/诊断/维护注册项联动。

### M8

- 集成源解析。
- 隐私预览。
- 确认导入。
- 撤销。
- 失败诊断。

### M9

- 备份 manifest。
- checksum。
- 恢复预览。
- 完整性体检。
- 迁移失败 runbook。

### 阶段总验收

- `uv run pytest -q`
- `npm run build`
- `npm run test`
- `npm run e2e`
- `cargo check`
- `uv run alembic current`
- `git diff --check`
- full release-check
- 至少一次升级 smoke 或记录明确阻塞原因

---

## 6. 数据迁移草案

若第八阶段需要持久化测试、发布和集成状态，建议新增迁移：

```text
alembic/versions/0011_phase8_release_quality_extensions.py
```

候选表：

- `test_runs`
- `release_artifacts`
- `upgrade_smoke_runs`
- `integration_sources`
- `integration_imports`
- `extension_registry_items`

注意：

- 测试运行记录只保存摘要、状态、路径和 hash。
- release artifact 保存 sha256、平台、签名状态，不保存证书或密钥。
- integration import 要保存可撤销信息和目标对象引用。
- extension registry item 可先不持久化，内存注册 + 设置启用状态也可接受。

---

## 7. 风险与控制

| 风险 | 控制方式 |
|---|---|
| E2E 在 Windows 上不稳定 | 先覆盖最小 smoke；失败保存截图/trace；full check 可重试一次但必须记录 |
| Playwright/Tauri 工具链引入复杂度 | 先做浏览器模式，再做桌面模式；避免一开始追求全路径 |
| 代码签名证书不可得 | 保留 unsigned 透明策略，不阻塞个人发布 |
| 签名顺序错误导致 updater 拒绝 | 自动校验 `.sig` 与最终安装包一致 |
| 升级 smoke 破坏真实数据 | 使用合成数据和独立测试目录/数据库 |
| 跨平台差异过大拖慢主线 | 只要求至少一个非 Windows 平台实测，其他保持未实测 |
| 性能脚本误伤开发速度 | quick check 不跑重基线，full/release check 才跑 |
| 扩展注册抽象过度 | 先迁移内置命令/诊断/维护三类，不做第三方插件市场 |
| 本地集成泄露隐私 | 强制文件授权、隐私预览、来源追踪和撤销 |
| 文档状态继续漂移 | M10 增加文档一致性检查和版本矩阵 |

---

## 8. 文档交付

第八阶段完成时至少更新：

- `README.md`
  - 第八阶段状态。
  - 相关文档链接。
- `docs/requirements.md`
  - 后续阶段表补充第八阶段。
  - 当前完成态更新。
- `docs/usage-guide.md`
  - 测试、发布、升级、扩展注册和本地集成说明。
- `docs/release-checklist.md`
  - full release-check。
  - 升级 smoke。
  - 代码签名。
  - 跨平台 smoke。
- `docs/cross-platform.md`
  - 实测平台状态。
- `docs/signing-and-keys.md`
  - 代码签名执行结果或 unsigned 策略。
- `docs/archive/phases/phase8-requirements.md`
  - 勾选验收清单。
- `docs/archive/phases/phase8-plan.md`
  - 勾选里程碑任务。

---

## 9. 阶段结论

第八阶段要把私人助手从“我自己机器上功能完整”推进到“每个版本都能被验证、升级、回滚和扩展”。它的核心不是新鲜感，而是证据链：桌面 E2E 证明 UI 可用，升级 smoke 证明数据不丢，签名和清单证明包可信，跨平台 smoke 证明边界真实，性能基线证明规模可控，扩展注册证明后续集成不失控。

完成后，项目才真正具备继续扩展外部生态的底气。
