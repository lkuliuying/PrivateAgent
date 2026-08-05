# 数据库与持久化设计

> 状态：源码 Alembic head 为 `0020`；应用主库 `personal_assistant` 已获授权于 2026-08-05 迁移到 `0020`（48 张原表行数零变化，10,581 行精确保持）。专用测试库已验证升级/回退；真实数据克隆 `personal_assistant_preupgrade_20260805111304` 保留为回滚备份，RAG 端到端演练（2026-08-05，`rollout_ready=true`）已在同 head 完成。

## 1. 职责划分

- MySQL 8：业务事实、状态机、审批、审计、文档元数据、索引 manifest。
- ChromaDB：可重建的文档和记忆向量；不作为唯一事实源。
- 本地文件：授权项目、上传原文件、日志、报告和备份。
- Windows Credential Manager：安装版数据库密码和远程 provider key。

SQLAlchemy async session 位于 `src/personal_assistant/core/db.py`，ORM 模型位于 `core/models.py`；API 路由只通过领域服务或 repository 操作持久化，不能散落原始连接。

## 2. 现代化迁移

| Revision | 主要变化 | 回退影响 |
|---|---|---|
| `0013` | `agent_runs`、`run_steps`、`agent_run_events` | 删除运行与事件事实 |
| `0014` | `tool_approvals` | 删除审批证据 |
| `0015` | `agent_run_checkpoints` | 删除待恢复状态 |
| `0016` | `agent_tool_executions` | 删除 durable 工具结果与 claim |
| `0017` | 记忆版本字段、`memory_revisions`、`memory_conflicts`、`conversation_summaries` | 删除新增记忆/摘要事实和字段 |
| `0018` | `document_index_versions`、`document_index_chunks`、`document_index_heads` | 删除版本化索引元数据 |
| `0019` | `mcp_servers`、`mcp_call_logs` | 删除 MCP 配置和审计 |
| `0020` | `document_index_chunk_provenance` | 删除版本化 chunk 的来源坐标与独立来源哈希 |

迁移文件位于 `alembic/versions/0013_*.py` 至 `0020_*.py`。MySQL DDL 非事务性；失败可能留下部分表或列，不能假设异常会自动回滚。迁移前必须有完整克隆，sidecar 迁移失败会拒绝启动，见 `src/personal_assistant/server_entry.py`。

## 3. 完整克隆与演练

`scripts/clone_application_database.py` 只接受源库专属的 `<source>_preupgrade_<UTC timestamp>` 名称，目标已存在时拒绝覆盖。它使用 `mysqldump/mysql`，密码只进入子进程环境，临时 dump 自动删除，并逐表比较：

- 表集合；
- Alembic revision；
- 精确行数；
- 计数 SHA-256。

已保留三份升级前克隆（均为 `0012` schema 的历史基线，无凭据 manifest 位于 `data/backups/*.json`）：

- `personal_assistant_preupgrade_20260802105903`：`0012 / 48 tables / 10579 rows / aa5a2cca…096db`（诊断审计行修复前）；
- `personal_assistant_preupgrade_20260803081120`：`0012 / 48 tables / 10581 rows / a4075821…f033`（匹配 2026-08-03 时点主库，含审计行）；
- `personal_assistant_preupgrade_20260805111304`：`0012 / 48 tables / 10581 rows / a4075821…f033`，当前正式回滚备份（2026-08-05 正式迁移前克隆，计数/哈希与 03081120 一致）。

最终发布检查审计（2026-08-02/03）发现旧版 `diagnostic_redaction_smoke` 曾错误连接应用主库，并留下两条成功的 `diagnostic_runs`（ID 36、37）。该时点主库计数因此为 `0012 / 48 tables / 10581 rows / counts SHA-256 a40758211caff6665e0ddbbe2ad8247d789023f55184a4509c9bb43fa545f033`；与更早的 `02105903` 克隆唯一的表计数差异是 `diagnostic_runs +2`，关键业务表计数未变。精确删除请求未获批准，这两条审计记录继续保留。2026-08-05 主库迁移到 `0020` 后，48 张原表行数保持 10,581 不变。

发布 runner 已修正为通过 `resolve_test_database_url` 只使用专用测试库，并在成功或失败后删除自己新增的测试库诊断记录、恢复临时 setting、删除临时诊断包。修复后的 smoke 已验证主库与测试库前后表计数均不变。

`scripts/rehearse_database_upgrade.py` 已在当前真实克隆完成 `0012 -> 0020 -> 0012`：head 时 48 张原表行数保持，回退后 10,581 行和完整计数哈希与主库一致，报告明确 `primary_database_modified=false`。`scripts/rehearse_versioned_rag.py` 也已用最新 `0020` 克隆完成 RAG 端到端演练（`data/rehearsals/versioned-rag-canonical-0020-20260805.json`，`rollout_ready=true`）；历史 `0019` 一次性克隆证据仍保留为历史性能记录。

保留克隆不是日常查询库。删除它属于独立破坏性动作，必须在升级、RAG rollout 和回滚窗口结束后重新授权。

## 4. 事务与一致性

- Run、step 投影和公开事件在同一事务提交。
- 审批 token 只存哈希，并通过行锁/条件更新保证一次消费。
- 工具 execution 先持久化经校验的结果，再交回 Runtime。
- 版本化 RAG 在 DB 与 Chroma 侧旁路构建；只有全部验证通过才在 MySQL 事务中切 active head。
- Chroma 失败不应删除 MySQL 业务事实；恢复任务根据持久化状态补偿。
- 删除 active 索引版本被拒绝，retired 清理受保留期和最小版本数约束。

跨 MySQL 与 Chroma 不使用分布式事务。系统通过 durable 状态、manifest、幂等重试和 reconciler 达成可恢复的一致性。

## 5. 数据保留与删除

业务删除优先软删除或显式状态迁移；审计事件不随主体级联抹除。文档删除需要同时处理 MySQL 元数据、legacy chunks、版本化 head/version 和 Chroma 向量，并记录失败以便补偿。

版本化 RAG 默认保留 retired 版本至少 14 天且每文档至少 1 个。物理清理应是有范围、可预览、可审计的维护任务，不应由普通查询或模型输出直接触发。

## 6. 凭据与连接

源码开发通过被 Git 忽略的 `.env` 提供 `PA_DB_URL`。Windows 安装版由 Rust 主进程从 Credential Manager 读取密码，只在内存中组装 DSN 并注入 sidecar 子进程；Vue、HTTP DTO、日志、备份和持久化设置只接触状态或 `secret://` 引用。

连接串和驱动异常可能含 DSN 或 SQL 参数，启动失败日志只记录异常类型。报告和 clone manifest 不包含密码。

可选 Compose 拓扑使用独立 MySQL 8.0.41 命名卷和 `private_agent` 用户，密码来自 `/run/secrets/mysql_password`；后端用 `PA_DB_PASSWORD_FILE` 在内存中把密码写入 SQLAlchemy URL 组件。MySQL 不发布宿主端口，API 等待其健康后以单实例执行 Alembic。该新卷与现有桌面主库完全分离，不能替代主库升级授权；命名卷也不是可恢复备份。

## 7. 升级与回滚决策

正式升级前：

1. 停止所有写入 sidecar；
2. 核验完整克隆；
3. 记录主库 revision 和关键计数；
4. 在克隆上完成 upgrade/downgrade；
5. 取得对主库 schema 变更的明确授权；
6. 执行 `alembic upgrade head` 并立即验收；
7. 保持新功能开关关闭，逐项 rollout。

如果没有必须保留的新写入，最安全回滚是停机后把连接切到已核验 clone。若已有升级后写入，先做新备份和差异迁移设计，不能用旧 clone 覆盖。详细命令见 `docs/database-upgrade-runbook.md`。

## 8. 测试

数据库集成测试必须使用 `PA_TEST_DB_URL` 指向专用测试库。`tests/conftest.py` 有生产库名称守卫；任何迁移、truncate 或 fixture 清理都不得指向应用主库。

```powershell
uv run python scripts/prepare_test_database.py
uv run pytest -q
uv run alembic current
```

最后一条默认读取当前 `PA_DB_URL`，运行前必须明确知道它指向主库还是测试库；只读检查可以针对主库，升级命令不可以在未授权时针对主库。
