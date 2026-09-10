# 应用数据库升级与回滚手册

## 统一客户端本机 SQLite（S6，2026-09-09）

此节适用于 `private_agent_local.Store` 的账号隔离记录；下面 MySQL/Alembic 克隆命令属于原业务数据库，不能用于本机 `projects.sqlite3`。

当前 schema 为 7。Store 对现有可识别旧格式执行一致性备份后迁移，备份位置、SHA-256 和版本写入 `schema_migrations`。启动后验证记录关联和内容引用；旧完成记录缺少 `goal_outcome` 时保持未记录验证，旧活动记录按协议保守收束，不重放审批或未知副作用。

S6 自动回归只构造空白隔离目录和合成 schema 3–6 数据：项目、旧完成/失败/活动记录、长内容引用、账号分隔及备份摘要。不使用真实账号数据库，不宣称所有历史安装版本均已验证。具体测试入口：`.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite acceptance`，既有 `--suite local` / `--suite recovery` 覆盖其他迁移与恢复边界。

实际升级前保留一致性备份及全部内容文件；不要只复制运行中的 SQLite 主文件遗漏 WAL。程序回退与恢复升级前数据是两个操作：当前程序拒绝高于自身支持版本的数据写入，但旧二进制是否正确拒绝新格式必须逐版本验证。从旧备份恢复会遗漏升级后记录；在独立副本演练新增记录的保留/导出方案前，不提供“无损回退”承诺或生产覆盖步骤。当前回退安装组合仍待验收，见 [S6 报告](analysis/coding-agent-upgrade-20260908/s6-validation-report.md)。

## 1. 原则

应用数据库升级必须先有完整、已核验且不会覆盖源库的回滚副本。现有 ZIP 备份适合导出、完整性校验、设置恢复和人工取证，但执行恢复只自动覆盖 settings；它不能单独作为全库 schema 升级的回滚手段。

`scripts/clone_application_database.py` 使用 MySQL 官方 `mysqldump`/`mysql` 创建同服务器逻辑克隆。密码只放入子进程环境，不进入命令行、manifest 或日志；dump 使用匿名临时文件，导入结束后自动删除。目标名称必须是源库专属的 `*_preupgrade_<UTC timestamp>`，已存在目标永不覆盖。

## 2. 升级前

```powershell
# 只预览目标名称
uv run python scripts/clone_application_database.py

# 创建完整克隆并逐表核对表集合、Alembic 版本和精确行数
uv run python scripts/clone_application_database.py --yes
```

成功输出包含 clone database、schema head、表数、总行数、计数 SHA-256 和不含秘密的 manifest 路径。保留该输出；未得到 `verified: true` 不得升级。

先在该克隆上使用真实数据演练升级与回退；脚本拒绝主库和任意非预升级名称，结束时恢复克隆到基线版本：

```powershell
uv run python scripts/rehearse_database_upgrade.py --clone <verified-clone-name>
uv run python scripts/rehearse_database_upgrade.py --yes --clone <verified-clone-name>
```

未得到 `sequence: ["0012", "0020", "0012"]`、源表行数保持和回退计数哈希一致，不得申请正式主库迁移。历史 `0019` 演练不能替代新增来源表后的最新 head 演练。

2026-08-05 正式迁移已完成：先以 `personal_assistant_preupgrade_20260805111304` 克隆演练 `0012 → 0020 → 0012`（48 张源表保持、回退 10,581 行、计数 SHA-256 为 `a40758211caff6665e0ddbbe2ad8247d789023f55184a4509c9bb43fa545f033`），获授权后主库执行 `alembic upgrade head` 到 `0020 (head)`，48 张原表行数零变化，全部测试 `535 passed`。回滚备份保留为 `personal_assistant_preupgrade_20260805111304`。

RAG 端到端演练也已在最新 `0020` head 完成：`scripts/rehearse_versioned_rag.py` 的输出 `data/rehearsals/versioned-rag-canonical-0020-20260805.json` 显示 `rehearsal_passed=true`、`rollout_ready=true`（10 个 reviewed case 全部通过，P95 `412.24 ms`），练习用临时克隆已回退并删除。

生产 rollout 已完成（2026-08-05，详情见 `docs/analysis/rag-data-quality-validation.md` 与 `docs/rag-design.md` §7）：主库 `0020` 上 `migrate_versioned_rag.py` 对 4 个 canonical 文档小批构建成功（4/4，来源哈希一致），`PA_VERSIONED_RAG_INDEXING_ENABLED=true` 与 `PA_VERSIONED_RAG_RETRIEVAL_ENABLED=true` 均已启用，生产 hybrid 评测 10 个 reviewed case 全部通过。

随后记录源库只读快照：

```powershell
uv run alembic current
uv run python scripts/upgrade_smoke.py --snapshot
```

## 3. 执行 schema 升级

先停止所有会写数据库的桌面端和 sidecar，再执行：

```powershell
uv run alembic upgrade head
uv run alembic current
uv run pytest -q
```

`0013` 至 `0020` 以 additive 表为主；`0017` 为 memory 投影增加版本字段。升级仍按普通生产迁移处理，不能因为测试库可逆就跳过克隆。

## 4. RAG 小批 rollout

schema 到 head 后先 dry-run，版本化检索开关继续关闭：

```powershell
uv run python scripts/migrate_versioned_rag.py --limit 25
```

只对有源文件的少量文档执行旁路构建；每批完成固定 case set 的 legacy/versioned 对照，确认 Recall@K、MRR、引用正确率、空召回率与 P95 后，才扩大批次。任何构建失败都保持 legacy 数据和旧 active head。

## 5. 回滚

在没有升级后必须保留的新写入时，最直接的完整回滚是停止 sidecar，并把开发 `.env` 的数据库名或 Windows 安装配置中的数据库名切换到已核验 clone。不要把 clone 覆盖回源库，也不要在应用运行中切换。

若必须保留升级后的新写入，应停止并人工比对差异后再决定迁移数据；不能盲目用旧 clone 覆盖。仅回退 additive schema 可在另一次新备份后按顺序执行 Alembic downgrade，但版本化索引和 MCP/Agent 新事实会被删除。

克隆保留到升级、RAG rollout 和回滚窗口全部结束。删除 clone 是独立的破坏性操作，必须重新核对完整名称和 manifest，不由本脚本自动执行。
