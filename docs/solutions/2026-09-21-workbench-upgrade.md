# 2026-09-21 本机工作台体验与能力完善

> 后续修正（2026-09-21）：用户要求收拢对话入口，Skills 改为 `/skill` 调用，worktree 创建移至项目编辑，三项快捷任务移至新会话中央；移除对话 Token/费用上限与独立只读子任务功能。下文保留本轮历史交付和测试证据，当前入口及更新配置以[工作台使用说明](../workbench-guide.md)为准，不再沿用下文已被移除功能的启用步骤。

## 任务总结

基于当前 API Key 本机桌面链，完善任务查找、执行中协作、审阅和扩展能力。用户授权将评估中发现的问题及建议落实到代码；此次交付包含源码、隔离回归、界面核对和功能文档，不包含桌面安装、发布或真实模型验收。

沿用 Tauri/Vue、Python 本机执行器、共享 AgentRuntime 与 SQLite。先核对项目记忆和工作区，保留接手前的未提交内容；随后实现、验证并核对本次差异。没有变更依赖、锁文件、数据库 schema 或创建 Git 提交。

| 发现的问题 | 完善后的行为 |
| --- | --- |
| 侧栏密集、操作图标难辨、工作区宽度固定 | 放大标题与操作区域，带文字的更多菜单，侧栏及审阅区可调整宽度，窄窗口抽屉 |
| 输入器有不可用入口，首次使用缺少起点 | 移除虚假语音入口，补充起始提示，预算与技能按需展开 |
| 命令面板只能导航，历史正文难查找 | 项目、任务和完整消息搜索，项目/状态/时间筛选，分页、归档恢复与定位原消息 |
| 运行中难以继续沟通或安排下一步 | 当前任务追加要求、下一条持久化排队、暂停继续、断线后的原请求幂等重试 |
| 结束提示和证据不够明确，反馈缺少上下文 | 区分回答结束与验证结果，展示用量和证据，diff 行号反馈附文件与审阅版本并保留草稿 |
| 独立工作区缺少完整交接路径 | 新建任务可选 worktree；预览冲突后交接到项目根目录，保留源目录和逐文件日志 |
| 插件入口实际承载壁纸，缺少可管理扩展 | 壁纸移至外观；新增技能目录、依赖检查、内容版本启用和通用 MCP 工具管理 |
| 仅固定文档 MCP，网页验收与协作能力有限 | 通用 HTTPS/stdio MCP 和 OAuth，公开页面读取、本机 DOM/截图证据，可选独立只读子任务 |
| 模型能力、费用和限制不够清楚 | 展示已存探测记录、任务预算和实际用量；未知费用明确显示未知 |

完整使用方式、限制和存储语义见[工作台说明](../workbench-guide.md)。这些改动借鉴 Codex 的任务工作流，不表示已经实现其全部产品能力。

## 验证结果

下列均为本次实际执行结果，后端组合套件存在交叉用例，因此不将通过数相加为独立测试数量。未调用真实付费模型。

仓库根目录执行：

| 命令 | 观察结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite workbench` | 36 passed；含真实 MCP stdio 进程、本机 Edge DOM/截图、队列实际续跑、工作区冲突、独立子任务与取消恢复 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite tool-evolution` | 847 passed、1 skipped；跳过为 Windows 未授予真实符号链接创建权限 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite security` | 105 passed |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite project-management` | 27 passed |
| `.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check` | `protocol codegen in sync: OK` |

在 `apps/desktop` 执行：

| 命令 | 观察结果 |
| --- | --- |
| `node node_modules/vitest/vitest.mjs run --reporter=json --outputFile=../../.run/ux-upgrade-20260921/frontend-final.json` | 675 passed、0 failed；包括最终状态刷新提示与请求结果未知时的重试保护 |
| `node node_modules/@playwright/test/cli.js test e2e/workbench-upgrade.spec.ts e2e/project-management.spec.ts e2e/coding-output.spec.ts e2e/documentation-mcp.spec.ts --retries=0` | 6 passed；宽窄窗口流程、键盘调宽与焦点、既有项目管理、输出和旧文档 MCP 兼容 |
| `npm run build` | 类型检查与 Vite 生产构建通过 |
| `npm run bundle:check` | 配置的四项包体积预算均通过 |

仓库根目录的 `git diff --check` 退出码为 0，输出仅有既有文件的 LF/CRLF 转换提醒。另对本次新增文件检查尾部空白、对变更 Markdown 检查本地链接，均无问题。核对接手时保存的 617 个文件摘要：本次清单外的基线文件均未改变。

以下实际执行的 Ruff 检查返回 `All checks passed!`：

```powershell
.venv/Scripts/python.exe -B -m ruff check src/private_agent_local/app.py src/private_agent_local/runtime.py src/private_agent_local/store.py src/private_agent_local/run_controls.py src/private_agent_local/tool_catalog.py src/private_agent_local/tool_registry.py src/private_agent_local/task_constraints.py src/private_agent_local/skills.py src/private_agent_local/integration_mcp.py src/private_agent_local/public_http.py src/private_agent_local/workspace_search.py src/private_agent_local/turn_queue.py src/private_agent_local/task_review.py src/private_agent_local/workspace_features_routes.py src/private_agent_local/worktree_handoff.py src/private_agent_local/browser_tools.py src/private_agent_local/readonly_agents.py tests/unit/test_workspace_features.py tests/unit/test_workbench_integrations.py tests/unit/test_local_model_contract.py tests/unit/test_local_project_management.py tests/coding_acceptance/recovery_process.py scripts/run_coding_validation.py
```

浏览器页面与截图还实际检查了首页、侧栏菜单、搜索、插件及窄窗口布局；界面流程使用合成 API/IPC 数据，后端网络与工具边界另由隔离测试覆盖。壁纸已有的颜色测试覆盖各色调正文、按钮及深色语义状态色；本次复用其结果，修正菜单和分隔条将阴影令牌误用为轮廓的问题，并验证键盘焦点及宽度边界。

测试过程中发现并修复的回归包括：新工具无条件展开导致小上下文超限、搜索未进入本机请求白名单、MCP SDK 异常组没有转换为明确错误、技能目录被通用文件保护阻断、CRLF 对工作区交接的影响及侧栏菜单被裁切。新工具改为按需发现，技能使用受范围与版本约束的专门读取入口；未放宽通用秘密过滤或删除有效断言。

Windows 受限工具环境曾出现 `WinError 5` / `EPERM`，测试和构建通过结果来自获准普通进程权限下的复验。Vite 仍提示既有 Ant Design 分包超过 500 kB（压缩前约 772 kB，gzip 约 235 kB）；构建成功不等于消除了这一包体积提醒。

## 项目记忆

已阅读 `docs/project-state.md`，并与本机化说明、当前源码、测试及接手时 Git 差异核对。其日期较早的旧后端、插件和归档描述不能代表本次实现；依据当前路由、页面及回归证据更新 `README.md`、文档索引、本机模型/工具说明和测试指南，新增工作台说明与本记录。

遵循仓库会话入口“仅在用户明确要求新增或更新项目记忆时”维护该文件的约定，没有改写 `docs/project-state.md`；文件摘要与接手基线一致。历史记录按原日期保留，当前入口明确链接新说明，避免将历史验收状态误当成现状。

## 风险、限制与假设

- 未重新打包安装 Tauri 客户端，未验证系统凭据库、签名、安装与更新；新功能需要同版本前端和 Python 执行器。
- 未连接真实第三方 OAuth 账号、MCP 服务或付费模型。协议、回调状态、进程与本机浏览器有隔离验证，不能等同于所有供应商兼容性验收。
- 通用 MCP 的 stdio 进程以用户权限运行，并非操作系统级只读沙箱。OAuth 登录令牌仅保留在内存；没有内置搜索账号，搜索服务由用户配置 MCP。
- 搜索按创建 ID 分页且单页扫描有界，不提供语义检索；任务审阅最多 200 次运行。浏览器证据工具仅支持受限本机 HTTP 预览，DOM/截图生成不代表自动完成视觉验收。
- worktree 交接逐文件写入，跨文件不能保证一次事务；预览冲突检查、请求标识、逐文件日志与源目录保留用于识别和恢复部分完成。
- 独立子任务需要用户显式启用，仅允许只读探索或审查，不支持递归或并行修改代码。未恢复已退役的云端后台、自动化和跨设备任务系统。
- 本次在 Windows 验证；未进行其他操作系统、屏幕阅读器或完整真实账号长时间验收。

## 用户需执行的操作

审阅源码与文档无需额外操作。若要让已安装桌面客户端使用新增功能，后续需按项目现有流程重新打包并安装包含同版本前后端的客户端；本次未发布或替换现有安装。Skills、MCP、OAuth 和只读子任务按界面配置或启用，不需要向会话提供任何密钥。

## 变更文件

下表仅记录本次相对接手基线实际新增或修改的文件，不将原有大范围未提交变更计入本次成果。

| 文件 | 操作 | 用途 |
| --- | --- | --- |
| [README.md](../../README.md) | 修改 | 更新当前功能与工作台入口 |
| [apps/desktop/e2e/documentation-mcp.spec.ts](../../apps/desktop/e2e/documentation-mcp.spec.ts) | 修改 | 验证旧文档服务折叠入口兼容 |
| [apps/desktop/e2e/project-management.spec.ts](../../apps/desktop/e2e/project-management.spec.ts) | 修改 | 保留项目编辑、置顶和删除确认回归 |
| [apps/desktop/src/App.vue](../../apps/desktop/src/App.vue) | 修改 | 接入搜索结果、消息定位和真实插件管理 |
| [apps/desktop/src/api/http.spec.ts](../../apps/desktop/src/api/http.spec.ts) | 修改 | 检验新增接口使用本机认证与 IPC |
| [apps/desktop/src/components/AppShell.vue](../../apps/desktop/src/components/AppShell.vue) | 修改 | 侧栏宽度调整与键盘操作 |
| [apps/desktop/src/components/CommandPalette.spec.ts](../../apps/desktop/src/components/CommandPalette.spec.ts) | 修改 | 保留导航命令和键盘回归 |
| [apps/desktop/src/components/CommandPalette.vue](../../apps/desktop/src/components/CommandPalette.vue) | 修改 | 任务正文检索、筛选、分页与焦点管理 |
| [apps/desktop/src/components/ModelProvidersPanel.vue](../../apps/desktop/src/components/ModelProvidersPanel.vue) | 修改 | 展示能力记录并适配窄窗口 |
| [apps/desktop/src/components/SettingsModuleNav.spec.ts](../../apps/desktop/src/components/SettingsModuleNav.spec.ts) | 修改 | 核对设置入口变化 |
| [apps/desktop/src/components/SettingsModuleNav.vue](../../apps/desktop/src/components/SettingsModuleNav.vue) | 修改 | 外观与外部能力导航 |
| [apps/desktop/src/components/SettingsView.vue](../../apps/desktop/src/components/SettingsView.vue) | 修改 | 接入外观、通用 MCP 与旧文档服务 |
| [apps/desktop/src/features/coding/api/projects.ts](../../apps/desktop/src/features/coding/api/projects.ts) | 修改 | worktree 交接预览、应用与历史接口 |
| [apps/desktop/src/features/coding/api/threads.ts](../../apps/desktop/src/features/coding/api/threads.ts) | 修改 | 任务详情和归档接口 |
| [apps/desktop/src/features/coding/components/CodingComposer.vue](../../apps/desktop/src/features/coding/components/CodingComposer.vue) | 修改 | 运行中输入、排队、技能、预算与草稿保护 |
| [apps/desktop/src/features/coding/components/CodingHome.vue](../../apps/desktop/src/features/coding/components/CodingHome.vue) | 修改 | 起始提示及独立 worktree 创建 |
| [apps/desktop/src/features/coding/components/CodingSidebar.vue](../../apps/desktop/src/features/coding/components/CodingSidebar.vue) | 修改 | 层级、菜单、字号、抽屉及搜索入口 |
| [apps/desktop/src/features/coding/components/CodingThreadWorkspace.spec.ts](../../apps/desktop/src/features/coding/components/CodingThreadWorkspace.spec.ts) | 修改 | 面板、生命周期和任务操作回归 |
| [apps/desktop/src/features/coding/components/CodingThreadWorkspace.vue](../../apps/desktop/src/features/coding/components/CodingThreadWorkspace.vue) | 修改 | 协调搜索定位、控制、反馈与审阅面板 |
| [apps/desktop/src/features/coding/components/PatchPreview.spec.ts](../../apps/desktop/src/features/coding/components/PatchPreview.spec.ts) | 修改 | 核对真实差异行渲染 |
| [apps/desktop/src/features/coding/components/PatchPreview.vue](../../apps/desktop/src/features/coding/components/PatchPreview.vue) | 修改 | 补丁行级反馈 |
| [apps/desktop/src/features/coding/components/PatchReviewPanel.vue](../../apps/desktop/src/features/coding/components/PatchReviewPanel.vue) | 修改 | 将行级反馈传至任务草稿 |
| [apps/desktop/src/features/coding/components/RunTranscript.spec.ts](../../apps/desktop/src/features/coding/components/RunTranscript.spec.ts) | 修改 | 验证结果文案与公开过程回归 |
| [apps/desktop/src/features/coding/components/RunTranscript.vue](../../apps/desktop/src/features/coding/components/RunTranscript.vue) | 修改 | 定位消息与区分结束、验证状态 |
| [apps/desktop/src/features/coding/components/ThreadTools.spec.ts](../../apps/desktop/src/features/coding/components/ThreadTools.spec.ts) | 修改 | 面板、归档和高级操作回归 |
| [apps/desktop/src/features/coding/components/ThreadTools.vue](../../apps/desktop/src/features/coding/components/ThreadTools.vue) | 修改 | 固定可调审阅区及高级操作收纳 |
| [apps/desktop/src/features/coding/model/contracts.ts](../../apps/desktop/src/features/coding/model/contracts.ts) | 修改 | 任务创建时的协作配置类型 |
| [apps/desktop/src/features/coding/model/runContracts.ts](../../apps/desktop/src/features/coding/model/runContracts.ts) | 修改 | 运行参数中的只读子任务许可 |
| [apps/desktop/src/models/settingsSections.ts](../../apps/desktop/src/models/settingsSections.ts) | 修改 | 同步设置模块定义 |
| [apps/desktop/src/models/viewRegistry.ts](../../apps/desktop/src/models/viewRegistry.ts) | 修改 | 插件入口文案与职责 |
| [apps/desktop/src/services/localExecutor.ts](../../apps/desktop/src/services/localExecutor.ts) | 修改 | 允许搜索请求进入现有本机身份通道 |
| [docs/README.md](../../docs/README.md) | 修改 | 更新当前功能与工作台入口 |
| [docs/direct-model-execution.md](../../docs/direct-model-execution.md) | 修改 | 同步插件、外观和归档说明 |
| [docs/local-tool-system.md](../../docs/local-tool-system.md) | 修改 | 区分旧文档 MCP 与新增通用 MCP |
| [docs/testing-guide.md](../../docs/testing-guide.md) | 修改 | 新增工作台复验命令与结果入口 |
| [scripts/run_coding_validation.py](../../scripts/run_coding_validation.py) | 修改 | 增加隔离 workbench 套件 |
| [src/private_agent_local/app.py](../../src/private_agent_local/app.py) | 修改 | 本机路由、归档、隐藏内部子任务及证据清理 |
| [src/private_agent_local/run_controls.py](../../src/private_agent_local/run_controls.py) | 修改 | 父任务控制传播与子任务停止边界 |
| [src/private_agent_local/runtime.py](../../src/private_agent_local/runtime.py) | 修改 | 新工具分发、延迟发现、队列及子任务预算与恢复 |
| [src/private_agent_local/store.py](../../src/private_agent_local/store.py) | 修改 | 删除父任务时事务清理内部子任务 |
| [src/private_agent_local/task_constraints.py](../../src/private_agent_local/task_constraints.py) | 修改 | 新能力遵循已有任务约束 |
| [src/private_agent_local/tool_catalog.py](../../src/private_agent_local/tool_catalog.py) | 修改 | 按需加载 Skills、MCP、浏览器工具 |
| [src/private_agent_local/tool_registry.py](../../src/private_agent_local/tool_registry.py) | 修改 | 注册新工具契约 |
| [tests/coding_acceptance/recovery_process.py](../../tests/coding_acceptance/recovery_process.py) | 修改 | 避免合成令牌与普通模型名碰撞，保留秘密过滤 |
| [tests/unit/test_local_model_contract.py](../../tests/unit/test_local_model_contract.py) | 修改 | 更新严格的协议工具矩阵 |
| [tests/unit/test_local_project_management.py](../../tests/unit/test_local_project_management.py) | 修改 | 核对归档与原项目删除边界 |
| [apps/desktop/e2e/workbench-upgrade.spec.ts](../../apps/desktop/e2e/workbench-upgrade.spec.ts) | 新增 | 宽窄窗口搜索、控制、审阅、插件和预算流程 |
| [apps/desktop/src/api/externalLinks.ts](../../apps/desktop/src/api/externalLinks.ts) | 新增 | 通过桌面能力打开 HTTPS OAuth 页面 |
| [apps/desktop/src/components/CapabilityRegistryPanel.vue](../../apps/desktop/src/components/CapabilityRegistryPanel.vue) | 新增 | 集中 Skills 与 MCP 管理 |
| [apps/desktop/src/components/McpIntegrationsPanel.vue](../../apps/desktop/src/components/McpIntegrationsPanel.vue) | 新增 | 服务配置、发现、工具授权与 OAuth 状态 |
| [apps/desktop/src/components/ModelCapabilityStatus.vue](../../apps/desktop/src/components/ModelCapabilityStatus.vue) | 新增 | 显示已存能力记录及显式重新探测 |
| [apps/desktop/src/components/SkillsPanel.vue](../../apps/desktop/src/components/SkillsPanel.vue) | 新增 | 创建、检查、依赖核对和按版本启用技能 |
| [apps/desktop/src/components/WorkspaceSearch.spec.ts](../../apps/desktop/src/components/WorkspaceSearch.spec.ts) | 新增 | 检索、请求取消及结果选择回归 |
| [apps/desktop/src/composables/useResizablePanel.ts](../../apps/desktop/src/composables/useResizablePanel.ts) | 新增 | 有界宽度、持久化及事件回收 |
| [apps/desktop/src/features/coding/api/integrations.ts](../../apps/desktop/src/features/coding/api/integrations.ts) | 新增 | 通用 MCP 类型及请求 |
| [apps/desktop/src/features/coding/api/runEvidence.ts](../../apps/desktop/src/features/coding/api/runEvidence.ts) | 新增 | 用量、浏览器和子任务证据请求 |
| [apps/desktop/src/features/coding/api/skills.ts](../../apps/desktop/src/features/coding/api/skills.ts) | 新增 | 技能目录、检查与启用请求 |
| [apps/desktop/src/features/coding/api/taskReview.ts](../../apps/desktop/src/features/coding/api/taskReview.ts) | 新增 | 任务范围审阅请求 |
| [apps/desktop/src/features/coding/api/turnQueue.ts](../../apps/desktop/src/features/coding/api/turnQueue.ts) | 新增 | 后续输入队列请求 |
| [apps/desktop/src/features/coding/api/workspaceSearch.ts](../../apps/desktop/src/features/coding/api/workspaceSearch.ts) | 新增 | 检索筛选与结果契约 |
| [apps/desktop/src/features/coding/components/DiffFeedback.vue](../../apps/desktop/src/features/coding/components/DiffFeedback.vue) | 新增 | 真实差异侧、行号和版本绑定 |
| [apps/desktop/src/features/coding/components/RunControlBar.vue](../../apps/desktop/src/features/coding/components/RunControlBar.vue) | 新增 | 暂停继续、幂等重试、排队撤回与状态提示 |
| [apps/desktop/src/features/coding/components/RunEvidencePanel.vue](../../apps/desktop/src/features/coding/components/RunEvidencePanel.vue) | 新增 | 用量、截图、断言与子任务结果 |
| [apps/desktop/src/features/coding/components/RunResultSummary.vue](../../apps/desktop/src/features/coding/components/RunResultSummary.vue) | 新增 | 区分回答结束、验证成功和待核实 |
| [apps/desktop/src/features/coding/components/SkillPicker.vue](../../apps/desktop/src/features/coding/components/SkillPicker.vue) | 新增 | 按需技能选择与插入 |
| [apps/desktop/src/features/coding/components/TaskReviewPanel.vue](../../apps/desktop/src/features/coding/components/TaskReviewPanel.vue) | 新增 | 最近一轮、整个任务和工作区审阅 |
| [apps/desktop/src/features/coding/components/WorkbenchInteractions.spec.ts](../../apps/desktop/src/features/coding/components/WorkbenchInteractions.spec.ts) | 新增 | 草稿保护、幂等重试、状态恢复和反馈回归 |
| [apps/desktop/src/features/coding/components/WorktreePanel.vue](../../apps/desktop/src/features/coding/components/WorktreePanel.vue) | 新增 | 独立工作区交接预览、确认和记录 |
| [apps/desktop/src/features/coding/model/pendingControls.ts](../../apps/desktop/src/features/coding/model/pendingControls.ts) | 新增 | 保留尚未确认的控制请求标识 |
| [docs/solutions/2026-09-21-workbench-upgrade.md](../../docs/solutions/2026-09-21-workbench-upgrade.md) | 新增 | 本次交付范围、逐文件清单与实际验证证据 |
| [docs/workbench-guide.md](../../docs/workbench-guide.md) | 新增 | 记录新工作流、接口语义和明确限制 |
| [src/private_agent_local/browser_tools.py](../../src/private_agent_local/browser_tools.py) | 新增 | 公开页面读取、本机隔离浏览器证据与清理 |
| [src/private_agent_local/integration_mcp.py](../../src/private_agent_local/integration_mcp.py) | 新增 | 通用 HTTPS/stdio MCP、OAuth 与调用授权 |
| [src/private_agent_local/public_http.py](../../src/private_agent_local/public_http.py) | 新增 | 公开 HTTPS、DNS 固定与传输回收 |
| [src/private_agent_local/readonly_agents.py](../../src/private_agent_local/readonly_agents.py) | 新增 | 有界独立上下文、父预算汇总与取消 |
| [src/private_agent_local/skills.py](../../src/private_agent_local/skills.py) | 新增 | 技能目录、版本启用和范围内参考文件读取 |
| [src/private_agent_local/task_review.py](../../src/private_agent_local/task_review.py) | 新增 | 任务操作记录与工作区 Git 审阅范围 |
| [src/private_agent_local/turn_queue.py](../../src/private_agent_local/turn_queue.py) | 新增 | 持久化、幂等队列及正常结束后的续跑 |
| [src/private_agent_local/workspace_features_routes.py](../../src/private_agent_local/workspace_features_routes.py) | 新增 | 工作台本机 API 与所属关系校验 |
| [src/private_agent_local/workspace_search.py](../../src/private_agent_local/workspace_search.py) | 新增 | 完整正文和归档范围检索 |
| [src/private_agent_local/worktree_handoff.py](../../src/private_agent_local/worktree_handoff.py) | 新增 | 有冲突检查与逐文件日志的本地交接 |
| [tests/unit/test_workbench_integrations.py](../../tests/unit/test_workbench_integrations.py) | 新增 | 真实 stdio、本机浏览器、OAuth 边界及子任务测试 |
| [tests/unit/test_workspace_features.py](../../tests/unit/test_workspace_features.py) | 新增 | 检索、技能、队列、归档与 worktree 冲突测试 |
