# 测试与验证指南

> 原则：测试必须能证明行为、回滚和安全边界；使用专用测试库，绝不清理或迁移应用主库。

> **当前状态（2026-08-06）**：应用主库为 Alembic `0020 (head)`；versioned RAG indexing/retrieval 已生产启用；Agent Runtime、MCP、自动摘要相关开关仍默认关闭。专用测试库为 `0020 (head)`，已完成真实 `0020 → 0019 → 0020` 往返。Windows `0.2.0` 发布里程碑：M0/M2 完成，M1 完整发布门禁已在干净 HEAD 以 `scripts/release-check-full.bat` 重跑（Ruff/compileall 已加入 runner 并全绿）。历史切片（2026-08-05 之前的报告、`0012` 叙述）属于**历史执行台账（不得当作当前状态）**。

## 1. 环境

```powershell
uv sync --extra dev
Set-Location apps\desktop
npm ci
Set-Location ..\..
```

准备 `.env` 时区分：

- `PA_DB_URL`：应用/开发库，只允许读检查或经明确授权的正式迁移。
- `PA_TEST_DB_URL`：专用测试库，测试 fixture 和迁移往返只能用它。

`tests/conftest.py` 有库名守卫，但操作者仍必须先核对连接目标。遇到 `uv` 缓存权限问题可为本次 shell 设置工作区或用户可写的 `UV_CACHE_DIR`。

## 2. 快速静态检查

```powershell
uv run --with ruff ruff check src tests scripts
uv run python -m compileall -q src scripts
```

Ruff 门禁口径固化在 `pyproject.toml` 的 `[tool.ruff.lint]`（`select = ["E", "F", "I"]`，`ignore = ["E501"]`）；`ruff check src tests scripts` 即该口径。E501 长行属于仓库既有风格债务，不作为门禁；新增规则变更必须同时修改测试指南和 `scripts/run_release_checks.py` 的步骤。`ruff` 不在常规依赖中，按需通过 `uv run --with ruff` 提供；离线环境需要预先缓存该包。

前端类型检查包含在生产构建中：

```powershell
Set-Location apps\desktop
npm run build
Set-Location ..\..
```

## 3. Python 测试

全量：

```powershell
uv run pytest -q
```

现代化核心的快速集合：

```powershell
uv run pytest -q tests/test_model_gateway.py tests/test_agent_runtime.py `
  tests/test_agent_run_repository.py tests/test_agent_runs_api.py `
  tests/test_tool_contracts.py tests/test_tool_approvals.py `
  tests/test_tool_executions.py tests/test_context_builder.py `
  tests/test_agent_context.py tests/test_memory_facts.py `
  tests/test_versioned_rag.py tests/test_mcp.py tests/test_api_security.py `
  tests/test_agent_recovery.py tests/test_chat_agent_runtime_compat.py
```

测试按以下层次组织：

- 纯单元：Schema、预算、状态机、哈希和评测指标。
- HTTP 集成：FastAPI 路由、SSE、审批、恢复和 feature gate。
- MySQL 集成：repository、并发 claim、迁移与回退。
- 外部协议：Ollama NDJSON、OpenAI Chat Completions SSE、Claude Messages SSE 的分帧/工具 JSON/usage/终止生命周期与完整响应聚合，流式重试/取消边界，官方 MCP stdio fixture、带 Bearer/API-key 的真实 Streamable HTTP server、DNS/SSRF 拒绝。
- 流式兼容：工具回合草稿不发布、最终 delta 不重复、SSE `run/token/done/title` 顺序和持久化完整回答一致。
- 端到端 RAG：解析、索引、混合召回、引用和降级。

## 4. 前端与桌面

```powershell
Set-Location apps\desktop
npm run test
npm run build
npm run e2e
Set-Location ..\..
scripts\cargo-check-tauri.bat
```

- Vitest 验证共享 HTTP auth、组件状态、MCP 原生凭据引用和 Agent 管理 UI。
- Playwright 使用浏览器 preview fixture 验证主工作台、响应式、审批和错误状态，不代表真实 Tauri 安装升级。
- Cargo test/check 验证 sidecar token、Provider/MCP 凭据命名空间、CSP 配置和 Rust 编译。

## 5. 数据库迁移验证

先在专用测试库准备 head：

```powershell
uv run python scripts/prepare_test_database.py --yes --verify-reversible
```

生产数据升级必须使用完整克隆：

```powershell
uv run python scripts/clone_application_database.py
uv run python scripts/clone_application_database.py --yes
uv run python scripts/rehearse_database_upgrade.py --clone <verified-clone-name>
uv run python scripts/rehearse_database_upgrade.py --yes --clone <verified-clone-name>
```

只接受来源专属 clone 名称和完整 `0012 -> 0020 -> 0012` 证据。主库迁移需要额外明确授权，测试通过本身不构成授权；历史 `0019` 演练只保留为历史证据。

## 6. RAG 数据质量与门禁

数据质量检查默认只读或 dry-run：

```powershell
uv run python scripts/profile_rag_data_quality.py --output data/analysis/rag-profile.json
uv run python scripts/validate_rag_data_quality.py `
  --profile data/analysis/rag-profile.json `
  --output data/analysis/rag-validation.json
uv run python scripts/plan_rag_canonicalization.py `
  --output data/analysis/rag-canonicalization.json
```

`scripts/evaluate_rag.py` 对固定 JSON case set 计算 Recall@K、MRR、引用正确率、空召回率和 P50/P95；`expect_empty` 的无答案 case 另计 `abstention_rate`（观察指标，不计门禁）。未经人工复核的 case 只能用于工程演练，不能让正式 rollout gate 变为 ready。

真实版本化 RAG 演练必须使用一次性克隆和隔离 Chroma：

```powershell
uv run python scripts/rehearse_versioned_rag.py `
  --canonicalization-plan data/analysis/rag-canonicalization-plan-20260802.json `
  --cases data/benchmarks/rag-evaluation-cases-reviewed-20260805.json
```

先读 preview。只有确认 clone 名、隔离目录和主库只读后才加 `--yes`；演练输出不得包含文档名称或正文。最新已完成演练见 `data/rehearsals/versioned-rag-canonical-0020-20260805.json`（`rollout_ready=true`）；`data/benchmarks/rag-full-generated-20260802.json` 仅作为未审阅的候选集保留。

## 7. 发布门禁

```powershell
scripts\release-check.bat
scripts\release-check-full.bat
docker compose --env-file .env.container --profile ollama-gpu config --quiet
uv run pytest -q tests/test_conversation_summary_worker.py
uv run pytest -q tests/test_agent_recovery.py
```

完整门禁（`scripts/release-check-full.bat` → `scripts/run_release_checks.py`）至少覆盖以下步骤，任一非跳过步骤失败即整体失败：

1. pytest（Python 全量）；
2. ruff_check（`uv run --with ruff ruff check src tests scripts`，口径见 §2）；
3. compileall（`uv run python -m compileall -q src scripts`）；
4. npm_build（`vue-tsc --noEmit && vite build`）；
5. npm_test（Vitest）；
6. npm_e2e（Playwright，runner 直接管理 Vite 进程）；
7. cargo_check；
8. cargo_test（Rust 单元测试，`scripts/cargo-test-tauri.bat`）；
9. sidecar_smoke（已构建 sidecar 时启动并轮询 `/health`；未构建如实标记 skipped）；
10. alembic_current（必须为 `0020 (head)`）；
11. git_diff_check（`git diff --check`）；
12. docker_compose_config（短生命周期 secret files，配置后强制删除）；
13. diagnostic_redaction_smoke（测试库，不得直连 `PA_DB_URL`）；
14. latest_json_validation（updater 清单结构与签名）。

报告生成顺序固定为：先跑完整 release check，再由 `scripts/generate_release_manifest.py --write` 以 `dist/release-check-<version>.json` 为机器事实源刷新 manifest；manifest 的 validation checklist 由真实步骤结果生成，不人工勾选。报告和 manifest 都不得包含 token、密码、DSN、聊天正文或文档原文。发布 runner 为 Compose 生成三个短生命周期 secret files，配置检查后强制删除；报告和命令行都不包含值。

## 8. 最近基线

2026-08-05 正式迁移配套的完整发布门禁：全部测试 `535 passed`（实际执行数，含参数化展开），Vitest / Playwright / Rust / Vue production build / `cargo check --locked` / Docker Compose 配置门禁通过；发布检查报告为 `10 passed / 0 failed / 0 skipped`。

2026-08-06 发布门禁收口（R0/R1）：把 Ruff（`E/F/I`，忽略 E501）、compileall、Rust `cargo test` 和已构建 sidecar smoke 加入完整 runner（门禁由 10 步扩至 14 步），并在干净 HEAD 以 `scripts/release-check-full.bat` 重跑。最新发布报告为 `14 passed / 0 failed / 0 skipped / ok=true`、`worktree_dirty=false`、`database_schema=0020`、`pytest 535 passed`；`release-manifest-0.2.0.md` 与报告绑定同一提交，checklist 由报告步骤生成。当前发布 HEAD 的具体短哈希以 `dist/release-check-0.2.0.json` 的 `commit.short` 为准（该文件是机器事实源），本文不重复粘贴，避免文档与报告漂移。

口径说明：发布报告数字是流水线**步骤数**（当前 14 个 gate step），不是测试用例数；pytest 的 `535 passed` 是**实际执行数**（参数化可能高于静态定义数，仓库静态函数定义为 493 个 Python 测试函数、32 个 Vitest 定义、11 个 Playwright 定义，均可能低于展开后的执行数）；三者口径不同，不能互相替代或直接比较。

2026-08-03 最近一次完整代码门禁（完成于 Phase 4 Slice 3 的 RAG ToolSpec/collection isolation 变更之前）：

- Python：494 passed
- Vitest：29 passed
- 前端生产构建：通过
- Rust：9 tests passed，`cargo check --locked` 通过
- Playwright：13 passed
- 专用测试库：`0020 (head)`；已完成 `0020 → 0019 → 0020`
- 当前真实数据克隆：`0012 → 0020 → 0012`，48 张原表保持，回退 10,581 行及完整计数哈希一致

结构化 provenance/code parsing 初始聚焦切片通过 52 个 RAG/数据质量回归和定向 Ruff；后续 Markdown 围栏代码与 DOCX 顺序表格切片的结构化解析专项为 12 passed，与版本化索引、legacy RAG 和四个只读 RAG 工具的联合回归为 53 passed，相关文件 Ruff 全绿。`dist/release-check-0.1.2.json`（2026-08-03T08:05:49Z）为 10 passed / 0 failed / 0 skipped；该完整报告早于后续 RAG 工具、远程流式、输出验证和解析器 v2 切片，平台提权额度耗尽后尚未取得新的完整发布报告。首次沙箱内运行因 MCP/Git/Node 子进程 `WinError 5` 得到 6/10，按相同命令在允许子进程的发布环境重跑后全绿。第十步使用短生命周期秘密校验两个 Compose profile并验证自动清理。Playwright 使用由发布 runner 直接管理的随机 loopback 端口 Vite 进程，13 个用例约 24 秒完成，退出后验证无残留进程。

上述完整报告之后新增的 Slice 3 已完成 42 个定向回归（四个 RAG 工具注册、严格输入/输出 schema、来源/知识库名称、active version 与完整性校验、API 接管和 collection 双路隔离），相关 `compileall`、Ruff `E/F/I` 及 `git diff --check` 通过。由于发布环境提权额度耗尽，变更后的完整发布命令尚未复跑；这组定向证据不能替代新的 10/10 报告，发布状态仍未放行。

此后桌面单执行链收口新增 1 个 Python 测试函数、3 个 Vitest 定义和 1 个 Playwright 定义：`tests/test_health.py` 为 3 passed，完整 Vitest 为 10 files / 32 passed，`vue-tsc --noEmit && vite build` 通过。浏览器用例实际模拟 `agent_runtime`，发送消息后断言 chat stream 一次、旧 planner 零次。仓库当前静态计数为 493 个 Python 测试函数、32 个 Vitest 定义和 11 个 Playwright 定义；参数化执行数可能高于定义数。该切片仍未复跑完整发布门禁。

同一完整报告之后补齐的远程原生流式切片通过 61 个定向回归：AgentRuntime 与旧聊天兼容层均消费 OpenAI/Claude SSE，覆盖 text/tool/usage 累积、Claude thinking 隐藏、OpenAI 缺 `[DONE]` 后失败且不重试、Claude 流内错误分类和既有 Agent API 兼容；compileall 与 Ruff 通过。这些是 MockTransport 协议证据，未使用真实 API key，也不替代新的完整发布门禁或真实付费端点 smoke。

受控输出验证切片最初通过 65 个 Agent Runtime/repository/recovery/chat/model 定向回归，另有 5 个验证器专属用例：覆盖 JSON parse/schema 路径、组合短路、无效候选不发布、一次修正后通过、重试耗尽稳定失败以及验证事件真实 MySQL 投影。固定非空策略接入 Agent API/兼容聊天后联合回归为 66 passed；RAG 引用身份/精确 quote 验证加入后为 71 passed，覆盖有效、缺失、未知、伪造引用和一次受控修正。原生 Structured Output 补充验证了安全 Schema 契约、能力不支持时零 Provider 调用，以及 OpenAI/Claude/Ollama 普通与流式请求的六条协议映射。durable RAG 工作流用例再覆盖成功检索持久化、伪造 quote 拒绝、一次修正、事件脱敏、重新加载证据和 SHA 篡改失败关闭；此前 Agent/RAG/MCP 组合回归为 `148 passed, 2 deselected`。其后知识库兼容聊天接管专项为 `7 passed`，与引用验证、RAG 工具和 ModelGateway 的最新聚焦回归为 `47 passed`：覆盖三开关接管、缺少 RAG 工具或输出验证时的独立回退、原始 JSON 不进入 UI/消息、可信来源投影和 run 原始输出保留；同一 7 项聊天回归随后加入首次完成后重连及双 continuation 并发，验证 message ID 稳定、assistant 行与 `chat.output_persisted` 各只有一条。`compileall`、定向 Ruff `E/F/I`（按仓库既有门禁忽略 E501）、`uv lock --check`（139 packages）和差异检查通过。随后扩大到 Agent/RAG/MCP/tool/context/summary/memory/model 关键词集合，得到 `223 passed, 1 failed, 303 deselected`；唯一失败仍是 legacy 白名单命令测试创建 Python 子进程时的 `WinError 5`，不是本切片断言失败，仍不记全绿。此前受限沙箱运行除两个官方 MCP stdio 用例外的近全量 Python 套件，结果为 `519 passed, 4 failed, 2 deselected`；4 个失败均在 legacy 项目任务/Git 测试创建子进程时得到 `WinError 5`。这些结果都不替代先前被平台拒绝的完整发布门禁。本次没有调用真实付费端点。全规则 Ruff 仍报告历史 Runtime/API 风格债务；RAG 接管任一开关缺失时仍走兼容路径，代码写入、Shell/API 和数据库领域验证器及切片后的完整发布门禁仍是后续条件。

Phase 2 兼容收口切片的首轮目标回归为 `44 passed`，扩大到 Agent Runtime/repository/recovery、审批与 durable execution 后为 `91 passed`：覆盖 4 个 safe 与 2 个 confirm 只读工具的注册契约、审批 requester 下的模型可见性、旧 planner 双开关过滤、模型强行选择已迁移工具时失败关闭，以及既有聊天兼容路径。后续 `propose_patch` 纯预览迁移新增无残留聚焦回归 `14 passed`，覆盖第五个 safe 工具、严格输入/输出 Schema、200,000 字符 diff 上限、截断标记和源文件不写入。相关文件 `compileall`、`uv lock --check`（139 packages）和差异检查通过；当前受限环境没有可调用的 Ruff 可执行文件，因此这条新证据不声明 lint 通过，也不替代完整发布门禁。

兼容遥测聚焦回归为 `4 passed`：覆盖 legacy full、Runtime filtered、planned/not-planned 计数、`Deprecation` 响应头、陈旧工具选择失败关闭和诊断快照字段。测试创建的会话在 `finally` 中按精确 ID 级联清理；计数只含固定标签，不接收用户消息或工具参数。

聊天兼容遥测聚焦回归为 `3 passed`：覆盖 `agent_runtime`、Runtime 关闭、旧 `tool_result`、RAG 工具关闭和输出验证关闭五种固定路由结果；既有 SSE、消息幂等和 legacy 精确回退断言保持通过。

旧工具端点遥测聚焦回归为 `2 passed`：覆盖 approve succeeded、reject rejected、拒绝后 approve conflict、按会话 list、detail found/not-found、成功与错误响应弃用头，以及会话、工具调用、活动和受信路径的精确测试清理。

上述工具所有权、diff 边界、planner/chat/旧 tool-call 遥测、诊断字段与 Agent bundle 的最终无残留联合回归为 `26 passed`；随后 `compileall`、139-package lock check 和差异检查通过。该结果仍不包含 Ruff 或完整发布门禁。

MCP DNS pinning 切片通过 `uv lock --check`（139 packages）、Ruff、compileall 和 13 个非 stdio MCP 用例，覆盖私网解析拒绝、预检地址直接进入 TCP、多地址切换、hostname/port 换址拒绝，以及 Bearer/API-key 的官方 SDK loopback HTTP 互操作。受限沙箱中的两个官方 stdio 用例因 Windows Named Pipe `WinError 5` 无法创建子进程，未计为通过；历史完整发布环境中的 stdio 证据仍保留，但本切片未重新取得完整发布报告。

发布门禁的诊断脱敏 smoke 必须使用 `resolve_test_database_url`；不得直接连接 `PA_DB_URL`。诊断健康聚合也必须注入该测试 session，不能通过模块级 engine 旁路到主库。本轮修复前曾向主库留下两条 `diagnostic_runs` 审计记录，现已在 `docs/database-design.md` 记录并保留。修复后的最终复跑没有新增主库或测试库行。

## 9. 失败处理

- 任一强制 gate 失败：不得声称阶段完成或打开功能开关。
- 测试失败先保留报告和最小复现，不自动重置用户工作区。
- 数据库迁移失败：停止 sidecar，不继续在未知 schema 上写入。
- RAG 指标失败：保留 legacy retrieval，不能用“离线质量很好”覆盖延迟或人工复核门禁。
