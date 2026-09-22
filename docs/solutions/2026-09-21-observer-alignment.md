# 2026-09-21 观察器与 Codex 生命周期及完成检查对齐

范围为当前 API Key 桌面本机链。开始时工作区已经有大量未提交修改，本记录仅列相对任务开始快照新增的变化；未提交、推送、安装或发布。

## 已实现的行为

- 模型和工具步骤在核心事件边界持久化。本机审批、输出和终态保留步骤关联，并行调用不共用一个活动步骤；持续进程的晚到输出始终属于创建它的调用。取消和重启关闭未完成步骤，已有成功步骤保留。
- 计划阶段以调用开始时的 `model_report` 快照关联，仅作上下文，不作为执行或完成证据。历史缺失的关联保持未知。
- 项目编辑中可独立保存最多 8 项完成检查：产物存在、测试通过或命令退出证据。配置默认关闭，使用版本检查避免并发覆盖；新任务保存快照，同一逻辑任务恢复沿用原快照，恢复检查点摘要包含该配置。
- 检查只用于修改任务，继续遵循当前用户的禁止修改、禁止测试、禁止命令及路径限制。配置不会直接运行命令或授予权限。显式用户验收与项目检查分别保留，标识冲突不会覆盖结果。
- 完成检查复用现有磁盘摘要、工作区版本、执行终态及恢复证据。根目录的检查不能用子目录同名命令替代；不允许用帮助、版本或收集用例冒充测试。缺失证据反馈给原主模型，继续受最多两次完成纠错和原任务预算限制。
- 正式工作台的“环境与变更 → 观察诊断”展示错误分类、检查状态、步骤和事件，支持手动刷新及复制诊断 JSON。后端和前端均按白名单投影，不包含对话正文、模型正文、工具参数、命令日志或原始错误消息。
- 诊断最多返回最近 100 条事件和 100 个步骤，并提供总数及截断标志。检查记录绑定目标、工作区和追加指令版本；版本变化后显示待重验，新的用户禁令显示跳过。历史工作区不可用时仍保留诊断读取。

## 对齐范围与限制

参考 Codex 官方 [App Server 生命周期](https://learn.chatgpt.com/docs/app-server) 和 [Stop Hooks](https://learn.chatgpt.com/docs/hooks) 的事件关联与完成前检查思路。本实现提供内置确定性检查，没有实现任意 Shell/MCP Hook 协议，也没有新增独立评判模型。

面板读取上次核验记录，刷新不重跑命令。外部文件变化未必增加任务版本，需等下一次完成核验通过磁盘摘要识别。文件存在或命令退出码成功，不等于所有业务语义已验证。旧事件没有可靠关联时不猜测补齐。

本次未修改数据库 schema（仍为 7）、依赖或权限模型，未调用真实付费模型，未制作或安装 Tauri 安装包。

## 实际验证

后端使用隔离 runner，每个套件均创建全新临时目录、合成模型响应和测试数据库，不加载业务模块。以下为最终回执，合计 **466 passed**：

| 实际命令 | 结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite observer` | 66 passed |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite completion` | 234 passed |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite parallel` | 57 passed |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite streaming` | 26 passed |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite orchestration` | 46 passed |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite execution` | 37 passed |

在 `apps/desktop` 实际执行：

```powershell
node node_modules/vitest/vitest.mjs run src/features/coding/api/observer.spec.ts src/features/coding/components/RunObserverPanel.spec.ts src/features/coding/components/ProjectObserverSettings.spec.ts src/features/coding/components/ThreadTools.spec.ts src/features/coding/components/EditProjectDialog.spec.ts src/features/coding/components/CodingThreadWorkspace.spec.ts
npm.cmd run build
```

Vitest 为 **6 files / 37 passed**；`vue-tsc --noEmit` 和 Vite 生产构建通过，仍有既有 Ant Design 分包超过 500 kB 的警告。

正式浏览器验收实际执行 `node node_modules/@playwright/test/cli.js test e2e/observer.spec.ts --retries=0`，**1 passed**。使用模拟本机接口并拦截外网，覆盖配置保存、重新打开、旧运行保留配置快照、诊断刷新及白名单复制。1440×950 和 760×900 下检查页面及面板无横向溢出，并目视核对四张截图；不等同于 Tauri 原生验收。

改动涉及的 16 个 Python 文件实际运行以下检查并通过：

```powershell
.venv/Scripts/python.exe -B -m ruff check src/private_agent_core/runtime.py src/private_agent_local/observer.py src/private_agent_local/observer_routes.py src/private_agent_local/observer_steps.py src/private_agent_local/completion.py src/private_agent_local/context_manager.py src/private_agent_local/runtime.py src/private_agent_local/core_adapter.py src/private_agent_local/store.py src/private_agent_local/execution_sessions.py src/private_agent_local/execution_tools.py src/private_agent_local/planning.py src/private_agent_local/app.py tests/unit/test_observer_checks.py tests/unit/test_observer_steps.py scripts/run_coding_validation.py
```

测试过程中保留以下失败及处理记录，没有删除或跳过断言：

- 受限工具环境无法创建 Windows 私有管道（`WinError 5`）或启动 esbuild（`spawn EPERM`）；获准使用普通本机进程运行相同隔离测试，没有放宽产品沙箱。
- 新增过期证据测试最初未在第二次修改前读取文件，写入被正确拒绝；随后前置断言误把成功响应的 `error: null` 视为失败。已按现有读后写和补丁结果契约修正，保留并强化磁盘内容、版本递增及证据失效断言，最终 66 项通过。
- 持续执行首轮 36 passed / 1 failed：`test_restricted_session_enforces_workspace_and_releases_lease` 未在固定窗口内收到终态。隔离数据库最终记录退出码 0、`stopped=true`，越界写入被拒绝，未留活动租约；随后原套件独立复验 37 passed。未修改该测试或等待窗口，终态延迟的具体原因未确定。
- 前端项目编辑集成的 Teleport 替身会随父层更新重建子组件，改用真实 Teleport 和实际配置面板验证保存生命周期，最终 37 项通过。
- 浏览器首轮跨断点时，既有侧栏重新挂载会关闭编辑弹窗，用例因此超时；按实际生命周期在窄窗口重新打开并核对持久配置。完成证据夹具同时补齐，使主界面结果与观察报告一致；最终禁用重试运行通过，没有改动既有响应式行为。

最终按任务开始快照生成差异复核，新增文本无 UTF-8 BOM、替换字符或新增行尾空白；既有项目记忆摘要未变化。原有未提交删除和修改保持原状。

## 本次文件清单

以下“修改”相对于任务开始时的文件快照，不以本来就未提交的 Git 状态判断归属。

| 文件 | 本次变化 |
| --- | --- |
| `src/private_agent_core/runtime.py` | 修改：可选步骤快照 sink，决定摘要关联模型步骤 |
| `src/private_agent_local/core_adapter.py` | 修改：调用级关联与实时步骤持久化 |
| `src/private_agent_local/store.py` | 修改：事件关联、轻量运行快照、重启步骤收尾 |
| `src/private_agent_local/execution_sessions.py` | 修改：持续进程的原始步骤关联 |
| `src/private_agent_local/execution_tools.py` | 修改：命令执行证据记录相对 cwd |
| `src/private_agent_local/runtime.py` | 修改：运行配置快照、步骤与审批接线 |
| `src/private_agent_local/completion.py` | 修改：内置检查验收与结果记录 |
| `src/private_agent_local/context_manager.py` | 修改：当前适用检查提示 |
| `src/private_agent_local/planning.py` | 修改：恢复摘要绑定检查快照 |
| `src/private_agent_local/app.py` | 修改：注册本机观察器接口 |
| `src/private_agent_local/observer.py` | 新增：配置、适用性、验收记录及有界诊断 |
| `src/private_agent_local/observer_routes.py` | 新增：配置及诊断路由 |
| `src/private_agent_local/observer_steps.py` | 新增：步骤关联、等待状态和中断收尾 |
| `tests/unit/test_observer_checks.py` | 新增：配置、约束、证据、恢复和脱敏回归 |
| `tests/unit/test_observer_steps.py` | 新增：并行、持续进程、取消与重启关联回归 |
| `scripts/run_coding_validation.py` | 修改：增加隔离 observer 套件 |
| `apps/desktop/src/features/coding/api/observer.ts` | 新增：接口及诊断白名单投影 |
| `apps/desktop/src/features/coding/api/observer.spec.ts` | 新增：解析与接口验证 |
| `apps/desktop/src/features/coding/components/RunObserverPanel.vue` | 新增：正式诊断面板 |
| `apps/desktop/src/features/coding/components/RunObserverPanel.spec.ts` | 新增：刷新、复制、错误与过期请求回归 |
| `apps/desktop/src/features/coding/components/ProjectObserverSettings.vue` | 新增：项目完成检查设置 |
| `apps/desktop/src/features/coding/components/ProjectObserverSettings.spec.ts` | 新增：校验、版本冲突和保存回归 |
| `apps/desktop/src/features/coding/components/ThreadTools.vue` | 修改：正式观察诊断页签 |
| `apps/desktop/src/features/coding/components/ThreadTools.spec.ts` | 修改：页签和空态回归 |
| `apps/desktop/src/features/coding/components/CodingThreadWorkspace.vue` | 修改：按需挂载当前任务诊断 |
| `apps/desktop/src/features/coding/components/CodingThreadWorkspace.spec.ts` | 修改：正式入口回归 |
| `apps/desktop/src/features/coding/components/EditProjectDialog.vue` | 修改：独立设置入口及保存时交互控制 |
| `apps/desktop/src/features/coding/components/EditProjectDialog.spec.ts` | 修改：真实 Teleport 下的配置保存生命周期回归 |
| `apps/desktop/e2e/observer.spec.ts` | 新增：正式页面的配置、诊断和宽窄窗口验收 |
| `docs/local-tool-system.md` | 修改：接口、行为、证据与兼容边界 |
| `docs/solutions/2026-09-21-observer-alignment.md` | 新增：本次交付记录 |

## 项目记忆核对

已读取 `AGENTS.md`、`docs/project-state.md`、`docs/solutions/2026-09-20-local-only-context.md` 和 `docs/local-tool-system.md`。9 月 19 日记忆中仍存在独立后端的历史描述；已按仓库入口要求，与 9 月 20 日本机化说明及当前两个 Python 包、桌面本机路由交叉核对，以后者作为本次范围。

依照仓库专用交接约定，未自动改写 `docs/project-state.md`。本次接口、模块职责及验证边界同步到工具系统文档和本文；没有改写历史环境的结论，也没有创建新的记忆体系。
