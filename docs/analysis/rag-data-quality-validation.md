# RAG 数据质量审计验证记录

审计结论：**审计证据可分享，生产 versioned hybrid RAG rollout 不可放行。** 本记录只评估数据质量与证据链，不授权修改主库。

## 决策证据

| 指标 | 应用侧 profile | 独立 MySQL 聚合 | 结论 |
|---|---:|---:|---|
| document rows | 1,117 | 1,117 | 一致 |
| legacy chunk rows | 358 | 358 | 一致 |
| ready + enabled documents | 383 | 383 | 一致 |
| ready + enabled + chunks | 357 | 357 | 一致 |
| ordered chunk-manifest groups | 4 | 4 | 一致 |

4 个逻辑组的行数分别为 `180 / 59 / 59 / 59`；357 条可检索文档全部属于重复组，因此相对于每组保留一个 canonical 行，有 353 条 excess duplicate。Chroma legacy collection 当前为 0 个向量，358 个 MySQL chunks 全部缺向量。

## 方法与独立性

- 应用侧 profile 在内存中按 `ordinal, chunk id` 排序 chunk 内容并计算 SHA-256，只输出聚合指标。
- 独立验证使用 MySQL `GROUP_CONCAT ... ORDER BY` 与数据库侧 `SHA2` 重算 manifest；不复用应用侧哈希实现。
- 两条路径在五个决策关键计数上精确一致。
- 19 条有效声明哈希全部属于没有 chunk 的 ready/enabled 文档；357 条有 chunk 文档没有可比较的声明哈希。因此不能声称“声明哈希与 manifest 哈希一致”，只能确认两个独立 manifest 计算路径一致。
- 生成的 notebook 已从头执行：4 个代码单元全部有 execution count，0 个 error output。
- MCP report artifact 已通过结构验证：report surface、6 个 bounded datasets、3 个 sources、2 个 native charts、2 个 native tables，snapshot status 为 ready；可见渲染返回成功。

## 完整性与可恢复性

- orphan chunks：0；empty chunks：0。
- BM25 缺失 chunks：54；声明/实际 chunk count 不一致文档：76。
- 当前可解析源文件的 ready/enabled 文档为 58，其中同时有 chunk 的为 32；32 条覆盖全部 4 个逻辑组。
- canonicalization dry-run 为每个逻辑组都选出一个有源文件、BM25 完整且 chunk count 一致的 canonical 文档。计划只保存本地 document ID，不含名称、路径、正文或内容哈希；未执行任何数据库更新或删除。

## Rollout 门禁

| 门禁 | 当前状态 | 要求 |
|---|---|---|
| 生产 schema | `0020`（2026-08-05 已授权迁移完成） | 获得明确授权且最新克隆演练通过后迁移到 `0020`（已满足） |
| embedding dependency | 直接启动 Ollama 后 preflight 与真实 embedding 成功；client 已复用 | 修复/升级 Desktop wrapper，形成稳定启动方式 |
| vector consistency | legacy `0%`；隔离 versioned 演练 `4 chunks / 4 vectors` | 主库获批后小批构建并逐批核对 |
| benchmark | 10 个 reviewed case（真实意图 4 / 重复文档 2 / 引用边界 2 / 无答案 2）；质量通过，P95 `412.24 ms`，`rollout_ready=true` | 固定、人工审阅且能代表真实任务的 case set |

## 验证结论

- **分析正确性：Ready to share。** 关键计数有独立口径复核，隐私边界和证据限制已明确记录。
- **生产 rollout：已完成（2026-08-05 授权后）。** 主库已迁移 `0012 → 0020`（48 张原表行数零变化），4 个 canonical 文档完成生产构建，versioned indexing/retrieval 已启用，生产 hybrid 评测 10 个 reviewed case 全部通过；回滚克隆 `personal_assistant_preupgrade_20260805111304` 保留。
- **安全下一步：** 已完成——2026-08-05 获授权后主库迁移到 `0020` 并小批构建了 4 个 canonical 索引；versioned retrieval 已打开，未构建索引的文档自动走 legacy 检索。

2026-08-02 的隔离演练由 `scripts/rehearse_versioned_rag.py` 在当时的 `0019` head 完成：全新临时克隆按 canonicalization plan 构建 4 个 active version、运行 hybrid 评测、再回退到 `0012` 并删除。首次报告揭示客户端重复初始化；缓存修复后的 `data/rehearsals/versioned-rag-canonical-cached-gpu-20260802.json` 通过 2 秒门禁。两次演练的主库 revision 和各自计数哈希均未变化，报告未打印私有值。

2026-08-05 用最新 `0020` head 在同样受控克隆中完成 RAG 端到端演练：`data/rehearsals/versioned-rag-canonical-0020-20260805.json`，10 个 reviewed case 全部通过，`status=passed`、`reviewed=true`、`rollout_ready=true`，P95 `412.24 ms`，主库 revision 与计数哈希未变化。无答案 case 的 `abstention_rate=0.0` 记录为已知局限：Chroma 无相似度阈值，越界查询仍返回 top-k 结果。

最终跨栈回归（2026-08-02/03，rollout 前证据）通过：Python `445 passed`、Vitest `28 passed`、Playwright `13 passed`、Rust `6 passed`、Vue/Vite production build、`cargo check --locked` 与 Docker Compose 配置门禁成功；发布报告为 10 passed / 0 failed / 0 skipped。主库当时仍为 `0012`，RAG 演练和修复后的最终复跑没有改变业务表；较更早保留克隆仅多两条修复前发布 smoke 留下、未获删除授权的 `diagnostic_runs` 审计记录。该时点门禁已由 2026-08-05 授权迁移后的小批构建和全新完整门禁取代。

## 可复现材料

- `docs/analysis/rag-data-quality-audit-20260802.ipynb`
- `docs/analysis/rag-data-quality-report-artifact.json`
- `scripts/profile_rag_data_quality.py`
- `scripts/validate_rag_data_quality.py`
- `scripts/plan_rag_canonicalization.py`
- `data/analysis/rag-data-quality-report-source-v2-20260802.json`（本地忽略目录）
- `data/analysis/rag-data-quality-validation-source-v2-20260802.json`（本地忽略目录）
- `data/analysis/rag-canonicalization-plan-20260802.json`（本地忽略目录）
- `data/rehearsals/versioned-rag-canonical-live-20260802.json`（本地忽略目录）
- `data/rehearsals/versioned-rag-canonical-cached-gpu-20260802.json`（本地忽略目录）
- `data/rehearsals/versioned-rag-canonical-0020-20260805.json`（本地忽略目录）
