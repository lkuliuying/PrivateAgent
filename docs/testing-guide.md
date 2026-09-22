# 本机测试与验证指南

适用于 2026-09-20 起的 API Key 本机桌面源码。旧 MySQL、服务器、RAG 和发布门禁说明保存在[历史测试指南](archive/legacy/testing-guide.md)，不能作为当前执行入口。

## 1. 测试目录

| 位置 | 职责 |
| --- | --- |
| `tests/unit/` | 共享运行时、模型协议、本机存储、工具、权限、上下文和记忆 |
| `tests/packaging/` | NSIS 安装模板、updater 清单与代码签名编排 |
| `tests/coding_acceptance/` | 合成任务集、验收协议、评测隔离、执行宿主与较长运行场景 |
| `apps/desktop/src/**/*.spec.ts` | Vue 组件、状态与服务的 Vitest 测试，跟随源码共置 |
| `apps/desktop/e2e/` | 当前 Coding、设置与本机能力的浏览器流程 |
| `apps/desktop/e2e/visual-regression.spec.ts-snapshots/` | 当前 Coding 的视觉断言基线 |
| `scripts/build-remote-client.test.cjs` | 本机构建器的 Node.js 回归测试 |

根目录的共享模型、运行时测试已移入 `tests/unit/`；旧阶段命名的签名和发布测试已按职责改名。Python 测试没有因目录整理减少断言。删除的旧页面测试、实验脚本及其依据见[清理记录](solutions/2026-09-20-project-cleanup.md)。

## 2. Python 隔离入口

在仓库根目录使用已有虚拟环境：

```powershell
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite shared-models
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite desktop-packaging
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite all
```

运行器为每次执行创建独立的 `.run/coding-agent-validation/<suite>-<随机标识>/`，清除非允许的环境变量并使用临时目录。插件禁止加载旧业务配置模块，不读取仓库 `.env`，不使用真实用户数据库。每次留下 `invocation.json` 和正常 pytest 退出时的 `pytest-result.json`。

`all` 汇总去重后的套件文件，排除 `duration` 和 `execution-duration` 两个长时间套件；单次上限 900 秒。超时返回 124 并尝试回收所属进程树，超时不是通过。不要用根目录裸跑 pytest 替代隔离入口。

## 3. 按改动选择套件

| 套件 | 范围 |
| --- | --- |
| `workbench` | 全文搜索、归档、后续队列、技能版本与路径、通用 MCP/OAuth/stdio、worktree 交接、浏览器证据，以及已移除的只读子任务许可不再继承 |
| `shared-models` | 共享适配器、模型元数据与能力探测 |
| `output` | 可选 JSON Schema、格式纠错、事实门禁、任务恢复与最终结果事务提交 |
| `reasoning`、`streaming` | 原生消息阶段、公开增量、取消及旧文本协议兼容 |
| `parallel` | 并行读取、AgentRuntime 与恢复 |
| `reflection` | 结构化纠错、重复失败独立复核、预算与恢复边界；全部使用合成模型响应 |
| `desktop-packaging` | 安装模板、发布清单、签名 |
| `context-alignment`、`context`、`memory` | 请求预算、上下文归档、压缩和记忆 |
| `local`、`direct-models` | 本机请求、供应商直连及模型路由 |
| `tool-evolution` | 工具、审批、执行、文档 MCP 与任务约束的组合回归 |
| `security` | 各权限模式的沙箱边界、真实 Windows 敏感对象保护、跨分片脱敏、模型和 MCP 外发阻断、流式取消与持久化 |
| `security-regression` | 安全专项与既有沙箱、执行授权、工具、原生续接、供应商、文档 MCP、文件和流式回归的去重集合 |
| `orchestration`、`project-management` | 计划交互、进展与项目管理 |
| `acceptance`、`model-evaluation`、`local-probe` | 验收工具与模型评测的隔离回归 |
| `tooling` | 测试环境过滤、固定题集判定器和进程回收 |
| `duration`、`execution-duration` | 单独运行的长时间宿主场景 |

完整名称及文件映射由 [run_coding_validation.py](../scripts/run_coding_validation.py) 维护。这里的模型测试使用合成响应；真实模型评测入口 `run_coding_acceptance.py`、`run_coding_local_probe.py` 需要另行核对用户授权、费用与测试数据，不能把离线回归结果当作真实模型验收。

## 4. 前端与浏览器

```powershell
npm test --prefix apps/desktop
npm run build --prefix apps/desktop
npm run e2e --prefix apps/desktop -- --list
npm run e2e --prefix apps/desktop -- e2e/local-access.spec.ts e2e/documentation-mcp.spec.ts
```

Vitest 跟随源码发现测试，Playwright 从 `e2e/` 收集当前流程并按配置启动 Vite。浏览器测试使用接口或 IPC 替身，不能替代真实 Tauri 安装、更新和系统凭据库验证。

输出交付专项在仓库根目录运行以下后端回归：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite output
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite reasoning
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite streaming
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite shared-models
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite completion
```

在 `apps/desktop` 运行以下界面回归与构建；浏览器用合成工作区验证阶段去重、复制代码、文件引用、产物、行号和越界拒绝：

```powershell
node node_modules/vitest/vitest.mjs run src/features/coding/model/runProjector.spec.ts src/features/coding/components/RunTranscript.spec.ts src/features/coding/composables/useRunStream.spec.ts src/features/coding/dev/runProjectorTerminal.spec.ts
node node_modules/vitest/vitest.mjs run src/features/coding/model/outputFiles.spec.ts src/features/coding/components/MarkdownContent.spec.ts src/features/coding/components/FileWorkspace.spec.ts src/features/coding/components/CodingThreadWorkspace.spec.ts
node node_modules/vitest/vitest.mjs run src/features/coding/model/patchSummary.spec.ts src/features/coding/components/PatchReviewPanel.spec.ts
node node_modules/@playwright/test/cli.js test e2e/coding-output.spec.ts e2e/coding-output-layout.spec.ts --retries=0
npm run build
```

任务结束后默认收起执行过程，用时按钮切换公开进展、工具摘要和上下文压缩记录；最终回答及文件摘要持续显示。相邻且同文的公开进展与兼容决策摘要只显示一次，待审批操作不受折叠影响。文件摘要默认显示前三项，审核与文件列表独立展开，撤销继续经过回滚预览和确认。

文件增删行数来自完整补丁版本，仅汇总日志已确认落盘且未回滚的文件操作；同一文件多次写入按操作累计，旧记录缺少统计时不显示数字，不代表项目当前 Git 净差异。计数及回滚边界使用 `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite repository` 验证；浏览器用例输出收起、展开和窄窗口文件卡片截图，使用合成接口数据，不访问真实工作区或模型。

`--list` 只证明测试能够收集，不证明断言通过。视觉基线需要人工核对后更新，不能为了消除失败自动重录。旧 Today、RAG、旧聊天和兼容壳的测试已删除，历史截图仍作为对应版本的文档证据保存。

## 5. 协议与构建辅助

```powershell
.venv\Scripts\python.exe -B scripts/protocol_codegen.py --check
node --test scripts/build-remote-client.test.cjs
```

涉及 Rust/Tauri 时，在已经初始化 MSVC 的终端执行：

```powershell
cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml --lib
cargo check --offline --locked --manifest-path apps/desktop/src-tauri/Cargo.toml --features readiness-probe
```

打包入口是 `scripts\build-client.cmd`。构建、签名、安装、部署和真实账号验收是分别需要证据的结论。

## 6. 已知限制与结果记录

[本机化验证记录](solutions/2026-09-20-local-only-context.md)保留全量超时、既有模型验收失败、Windows 执行宿主限制及当时的定向通过结果。本次目录整理的结果另见[清理记录](solutions/2026-09-20-project-cleanup.md)，不能将历史通过数当成本次运行结果。

失败时保留具体套件、隔离目录、退出码和失败节点。区分实现回归、原有问题和运行环境限制；不得删除有效测试、放宽断言或修改真实数据来获得通过。

2026-09-21 安全与权限对齐使用最终源码实际验证：

| 命令 | 结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite security` | 105 passed；包含真实 AppContainer 文件访问、ACL 回收、重叠授权拒绝及秘密过滤 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite security-regression` | 695 passed、1 skipped；跳过为本机未授予真实符号链接创建权限 |
| 在 `apps/desktop` 执行 `node node_modules/vitest/vitest.mjs run src/features/coding/components/CodingThreadWorkspace.spec.ts src/features/coding/components/CodingComposer.spec.ts` | 27 passed |
| 在 `apps/desktop` 执行 `npm run build` | 类型检查与 Vite 构建通过；保留原有大分包警告 |

安全组合首次发现的 ACL 继承合并问题已在预检中拒绝；合成会话令牌与普通 `fixture` 文件名冲突的问题通过独立测试令牌解决，原隔离与参数断言保留。Windows 私有管道、ACL 和前端构建在受限工具环境曾报 `WinError 5` / `EPERM`，表中通过结果来自获准普通进程权限下的隔离复验。未调用真实付费模型，未打包安装或发布；不能把本机源码回归当作已安装客户端验收。

2026-09-21 工作台完善新增以下复验入口。功能范围、实际结果与未验证项见[工作台交付记录](solutions/2026-09-21-workbench-upgrade.md)，不要将其与前述安全专项数量相加为独立用例总数。

仓库根目录执行后端专项：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite workbench
```

在 `apps/desktop` 执行界面回归：

```powershell
node node_modules/@playwright/test/cli.js test e2e/workbench-upgrade.spec.ts e2e/project-management.spec.ts e2e/coding-output.spec.ts e2e/documentation-mcp.spec.ts --retries=0
```

`workbench` 包含真实本机浏览器和 stdio 进程，但模型及 OAuth 远端仍使用隔离合成数据；浏览器流程验证搜索、归档恢复、运行中输入、排队、审阅反馈、插件和窄窗口。

## 7. 静态检查与维护

现有 Ruff 规则为 `E/F/I`，忽略 `E501`，以根目录 `pyproject.toml` 为准：

```powershell
.venv\Scripts\python.exe -m ruff check src tests scripts
git diff --check
```

目录移动需同步运行器中的套件路径和测试内的仓库根定位，并比较移动前后的收集节点。文档移动需检查本地链接。只改测试组织或文档时，不额外变更业务代码、依赖版本和锁文件。
