# 更新日志

## 0.2.0（2026-08-06 发布门禁收口）

### 发布事实源与门禁（R0/R1，对应 `docs/remaining-work-plan-20260806.md`）

- 明确 `dist/release-check-<version>.json` 为唯一机器事实源：`scripts/generate_release_manifest.py` 改为从该报告的步骤结果生成 manifest 的 validation checklist，不再人工勾选；生成顺序固定为先完整 release check、后刷新 manifest。
- `scripts/run_release_checks.py` 新增四个强制步骤：`ruff_check`、`compileall`、`cargo_test`（新增 `scripts/cargo-test-tauri.bat`）、`sidecar_smoke`，完整门禁由 10 步扩至 14 步。
- Ruff 门禁口径固化到 `pyproject.toml` 的 `[tool.ruff.lint]`（`select = ["E", "F", "I"]`、`ignore = ["E501"]`），并清理存量 `E/F/I` 违规（未使用导入、导入排序、缺失模型导入、死代码等）；`ruff check src tests scripts` 与测试指南口径一致。
- 设计/审计文档统一「当前状态（2026-08-06）」与「历史执行台账（不得当作当前状态）」标记；旧计划书顶部状态更新为 M0/M2 已完成、M1 待干净 HEAD 重跑。
- 以干净工作区最终 HEAD 重跑完整发布门禁：`release-check-0.2.0.json/.md` 绑定该 commit（`worktree_dirty=false`、schema `0020`、`failed=0 / skipped=0 / ok=true`），manifest 与报告同一 commit 与摘要。
- 发布状态边界如实记录：无 Authenticode 证书（`code_signed: no`）；GitHub Release 远程 updater 未以真实远程资产验收。

## 0.2.0（2026-08-05）

### 版本化 RAG 生产上线（schema `0020`）

- 主库完成 `0012 → 0020` 正式迁移并核验：48 张原表行数零变化、10,581 行精确保持，回滚克隆 `personal_assistant_preupgrade_20260805111304` 保留。
- 新增 15 张迁移表：Agent 运行持久化（`agent_runs` / `agent_run_checkpoints` / `agent_run_events` / `agent_tool_executions` / `tool_approvals` / `run_steps`）、记忆事实（`memory_facts`）、版本化 RAG 索引（`document_index_heads` / `document_index_versions` / `document_index_chunks` / `document_index_chunk_provenance`）、MCP 注册表（`mcp_servers` / `mcp_call_logs`）、会话摘要（`conversation_summaries`）。
- 版本化检索已正式启用（`PA_VERSIONED_RAG_INDEXING_ENABLED=true`、`PA_VERSIONED_RAG_RETRIEVAL_ENABLED=true`）：active head 文档走版本化向量路径，未构建索引的文档自动落 legacy 检索，两套路径无缝共存。
- 4 个 canonical 文档完成生产小批构建（4 heads / 4 chunks / 4 versions / 4 provenance，Chroma 4 向量，1024 维），来源 SHA-256 与 canonicalization plan 完全一致。
- 生产评测：10 个人工复核 benchmark case 全部通过（Recall@K / MRR / 引用正确率 1.0，空召回率 0），P95 延迟约 510–713 ms，远低于 2 秒正式阈值。

### Agent Runtime（默认关闭，按开关启用）

- 全新 Agent 执行引擎：持久化 run、计划步骤、恢复与终止语义，MySQL 跨进程命名锁保证单 owner，第二进程 fail closed。
- 崩溃恢复：10 秒监控发现 ownership 丢失即停止本进程写入口，孤儿运行被确定性终结，幂等工具标 failed、非幂等标 unknown 且绝不自动重放。
- 工具审批流：`tool_approvals` 支持逐次审批、取消与恢复未决审批，跨会话/重载保持。
- 模型统一契约：JSON Schema / RAG 引用验证下发为 OpenAI `response_format`、Claude `output_config.format` 或 Ollama `format`，能力不支持时在网络请求前失败关闭。
- 输出验证（`PA_AGENT_OUTPUT_VERIFICATION_ENABLED`）：最终答案非空验证，无效候选最多受控修正 0–2 次。
- Context Builder（`PA_AGENT_CONTEXT_BUILDER_ENABLED`）：预算化输入上下文组装，默认 `PA_AGENT_CONTEXT_MAX_TOKENS=6000`。
- 旧聊天兼容映射（`PA_CHAT_AGENT_RUNTIME_ENABLED`）：无 RAG/无工具结果的开发聊天可接入 durable RAG 工具循环。

### MCP 客户端（默认关闭）

- MCP registry/client 独立默认关闭，每个 server 需显式信任并启用（`PA_MCP_ENABLED`）。
- 支持 stdio server、审批闭环、刷新恢复、调用日志与失败分类；DNS 私网地址默认拒绝。
- 凭据经系统安全存储管理，备份脱敏，不落配置文件。

### 记忆事实与上下文摘要

- `memory_facts` 支持结构化记忆事实，注入远程上下文时自动排除敏感/禁用条目。
- 可追溯会话摘要 worker（默认关闭）：按来源范围/hash 写结构化摘要、不删除原消息，本地 Provider 默认、远程二次许可，需 schema `0017+`。

### 数据治理、备份与回滚工程

- 数据库克隆脚本（`scripts/clone_application_database.py`）：mysqldump 逻辑克隆 + 逐表行数核对 + 计数 SHA-256 manifest，密码只进子进程环境。
- 升级演练脚本（`scripts/rehearse_database_upgrade.py`）：克隆上真实执行 `0012 → 0020 → 0012` 往返，验证回退哈希一致。
- 版本化迁移脚本（`scripts/migrate_versioned_rag.py`）：只对有源文件的小批文档旁路构建，失败保持 legacy 数据与旧 head。
- RAG 数据质量工具链：`profile_rag_data_quality.py` / `plan_rag_canonicalization.py` / `validate_rag_data_quality.py` / `build_rag_data_quality_report.py`。
- 评测基准：`generate_rag_benchmark.py` / `evaluate_rag.py`，支持空答案（abstention）、重复文档、引用边界与 P95 指标。

### 安全与容器部署

- API 认证强化：默认开启 token 认证、`PA_API_ALLOWED_HOSTS` / `PA_API_ALLOWED_ORIGINS`、`PA_API_ALLOW_NON_LOOPBACK_BIND=false`。
- 容器部署：Dockerfile、compose.yaml、容器密钥生成与 secret file 注入（`PA_API_TOKEN_FILE` / `PA_DB_PASSWORD_FILE`），本地开发/Windows 安装包/容器三种凭据来源互斥。
- Windows 凭据：Tauri sidecar 启动注入 256-bit 随机令牌，不写入磁盘。

### 桌面工作台

- 引入 anime.js 动画系统，Agent 工作台体验与交互细节打磨。
- 新组件：AgentActivityFeed、AgentPlan、AgentRunApprovalCard、TaskComposer、McpServersPanel（含组件测试）。
- 新 API 客户端模块：agentRuns、runtime、mcp；健康轮询状态在组件间共享。
- 检查器 `Files` / `Context` / `Artifacts` 三视图；窗口宽度低于 1320px 自动收起。

### 工程与质量

- Python 测试 535 通过（覆盖 Agent Runtime、恢复、审批、MCP、版本化 RAG、数据克隆、容器密钥、API 安全等新增域）；Vitest / Playwright / Rust / Vue production build / `cargo check --locked` / Docker Compose 配置门禁通过。
- 发布检查器修复：Windows 使用 `npm.cmd`、输出改临时文件防挂起、诊断 smoke 自清理。
- 新增文档：`rag-design.md`、`database-design.md`、`database-upgrade-runbook.md`、`migration-plan.md`、`modernization-audit.md`、`deployment-guide.md`、`mcp-design.md`、`memory-design.md`、`context-design.md`、`security-model.md`、`agent-runtime.md`、`api-reference.md`、`testing-guide.md`、`troubleshooting.md`、`tool-system.md`、`usage-guide.md` 等。

---

## 0.1.2（2026-07-11）

- 首次可安装桌面交付：Tauri/NSIS 安装包、应用内更新、发布检查、升级演练和可选代码签名。
