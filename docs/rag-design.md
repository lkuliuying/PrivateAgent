# RAG 架构、数据质量与上线门禁

> **当前状态（2026-08-06）**：版本化索引与 retrieval 已启用（`PA_VERSIONED_RAG_INDEXING_ENABLED=true`、`PA_VERSIONED_RAG_RETRIEVAL_ENABLED=true`）。应用主库已于 2026-08-05 授权迁移到 `0020`、2026-08-06 迁移到 `0021`（新增 compatibility telemetry 表），4 个 canonical 文档完成生产构建（4 chunks / 4 vectors，来源哈希一致），生产 hybrid 评测 10 个 reviewed case 全部通过（Recall/MRR/引用 1.0，P95 约 510 ms）。回滚克隆 `personal_assistant_preupgrade_20260805111304` 与 `personal_assistant_preupgrade_20260806070435` 保留。
>
> **R2.1 证据充分性（2026-08-06 上线）**：检索层新增 `rag-evidence-v1` 无答案拒答策略
> （`src/personal_assistant/core/rag_evidence.py`，`PA_RAG_EVIDENCE_ENABLED=true` 生产已授权开启）。
> 阈值 `PA_RAG_EVIDENCE_MIN_FINAL_SCORE=0.80`、`PA_RAG_EVIDENCE_MIN_SINGLE_CHANNEL_SCORE=0.85`
> 经真实语料校准（已知答案 0.906–0.954，无答案 0.761–0.848，单渠道）；10 reviewed case 重跑
> `abstention_rate=1.0` 且 Recall/MRR/引用正确率保持 1.0、零误拒答。拒答返回空来源 + 结构化原因
> （`evidence_insufficient`/`single_channel_weak`/`no_results`），聊天提示词与
> `search_knowledge_base` 工具输出都会明确说明资料不足。已知边界：语义反转类干扰查询
> （>0.88、双渠道高分）分数策略无法拒答，需语义蕴含级验证，记录于
> `data/rehearsals/rag-evidence-r2-20260806/summary.md`。评测口径：`evaluate_rag.py`
> 现在支持 `--min-abstention` 门禁（默认 0.8）与分数分布报告。

## 1. 存储职责

- MySQL：文档元数据、解析片段、索引版本、active head、状态和 manifest 的事实源。
- ChromaDB：可重建的向量索引，不承载唯一业务事实。
- 原始文件：在授权数据目录中保存，解析与重建必须显式校验可用性。
- Ollama：`bge-m3` embedding 和本地模型推理。

核心实现：

- 解析和 legacy 检索：`src/personal_assistant/core/rag.py`
- 混合检索：`core/hybrid_retrieval.py`
- Chroma 存储：`core/store_chroma.py`
- 版本化索引：`core/index_versions.py`
- 导入和恢复：`workers/importer.py`
- 管理 API：`api/routes_documents.py`
- 评测：`core/rag_benchmark.py`、`core/rag_evaluation.py` 和 `scripts/evaluate_rag.py`

## 2. 文档处理与 legacy 路径

导入支持 PDF、DOCX、Markdown 和 TXT。`parse_document` 负责类型分派，`split_text` 生成片段；MySQL `doc_chunks` 保存片段正文和 BM25/FULLTEXT 数据，Chroma legacy collection 保存向量。

检索采用：

1. Chroma 向量召回；
2. MySQL FULLTEXT/ngram 词法召回；
3. RRF 融合；
4. embedding rerank；
5. 返回带文档、片段和命中渠道的引用。

单路召回失败时保留可用路径；所有链路无可靠内容时返回空结果，不伪造引用。

legacy 路径仍使用纯文本字符窗口。版本化路径改用 `parse_document_blocks`：PDF 按页；DOCX 按正文段落、Heading 样式和文档顺序中的表格；Markdown 将标题、正文段落和围栏代码分别作为语义块；TXT 按段落；Python 按顶层 AST 类/函数；其他常见代码按类/函数/Vue section 线索解析。`split_document_blocks` 只在单个来源块内切分，所以 PDF 片段不会跨页，Markdown 围栏中的 `#` 不会污染标题路径，DOCX 表格不会与前后段落混合，代码优先保持符号边界。Markdown 和 DOCX 解析器版本分别为 `markdown:v2` 与 `python-docx:v2`；chunk 写入保守 tokenizer-free token 估算，版本 source SHA-256 直接取原始文件字节。超长结构块仍按字符窗口二次切分；复杂/合并表格的结构保真和 provider 精确 tokenizer 仍是后续解析质量项。

## 3. 版本化索引

迁移 `0018_versioned_rag_indexes.py` 新增：

- `document_index_versions`
- `document_index_chunks`
- `document_index_heads`

迁移 `0020_document_chunk_provenance.py` 为每个版本化 chunk 增加一对一来源事实：source kind、parser version、页/字符/行范围、标题路径和独立 SHA-256。旧 `0019` chunk 只回填显式 `unspecified`，不会伪造页码。版本化构建、校验、回滚前复核和检索均要求来源记录完整且哈希一致；schema 低于 `0020` 时 indexing 在解析和 embedding 前失败关闭。

独立 Chroma collection 为 `document_chunks_v2`。构建状态：

```text
building -> validated -> active -> retired
    |            |
    +----------> failed
```

旁路构建流程：

1. 创建 building version，不修改旧 active head。
2. 解析、切块并写版本化 DB chunks。
3. 写向量，校验 chunk/vector 数、维度、内容哈希和 manifest。
4. 标记 validated。
5. 在 MySQL 单事务中切换 active head，并 retire 旧版本。

构建失败只标记新 version，旧 active/legacy 保持可用。回滚前再次核对目标版本的向量和 manifest；active version 禁止直接删除。清理只处理达到保留期的 retired version，并保留至少 `PA_VERSIONED_RAG_MIN_RETIRED_VERSIONS` 个回滚点。

## 4. 渐进开关

| 配置 | 默认值 | 作用 |
|---|---:|---|
| `PA_VERSIONED_RAG_INDEXING_ENABLED` | `false` | 允许旁路版本构建和启动恢复 |
| `PA_VERSIONED_RAG_RETRIEVAL_ENABLED` | `false` | 有 active head 时走 v2，无 head 时回退 legacy |
| `PA_VERSIONED_RAG_RETENTION_DAYS` | `14` | retired 最短保留天数 |
| `PA_VERSIONED_RAG_MIN_RETIRED_VERSIONS` | `1` | 每文档最少回滚版本数 |
| `PA_AGENT_RAG_TOOLS_ENABLED` | `false` | 向 durable Agent 注册 4 个只读 RAG 工具，由模型按需调用 |

必须先开 indexing 并验证，最后才开 retrieval。两个开关不能同时从 false 直接全量打开。

工具集包含 `search_knowledge_base`、`get_document_chunk`、`get_document` 和 `list_knowledge_bases`。搜索接受 query/top-k 和可选 collection/doc type/language/project/tags 过滤，返回有上限的原文摘录、chunk/version ID、页/行/标题路径、命中原因及真实知识库 ID/名称；collection filter 同时约束向量与 BM25 两路，空集合在调用 embedding 前返回空结果。片段详情要求 search 返回的 doc/chunk 标识，versioned 路径还要求 version ID，只读取 active head 并复核正文/provenance 哈希；文档详情不暴露本地源路径；列表返回集合及总文档/就绪文档计数。四个工具固定为 safe/read-only、幂等、严格输入输出 schema，内容仍按不可信工具结果进入 Runtime。它们默认不注册，因此普通消息不会被强制执行 RAG。

当 RAG 工具和输出验证两个开关同时开启时，durable Agent 要求最终结果为 `{answer, citations}`。验证器不信任模型自报来源，而是在每次验证时从同一 run 的 `agent_tool_executions` 重载成功搜索/片段读取结果，复核 canonical JSON 的持久化大小和 SHA-256，并只接受模型实际看到的 excerpt 或 chunk 正文。相同 version/chunk 的 excerpt 与完整正文可安全合并；身份或展示元数据冲突、未知引用、非精确 quote、证据篡改、超过 128 个源或合计 2 MiB 都失败关闭。该路径跨审批恢复不依赖进程内列表。再开启聊天 Runtime 后，`/chat/stream` 的 `knowledge_base=true` 请求进入同一工具循环，验证通过后只向旧 SSE 和消息表投影可读 answer，sources 由 durable 证据生成而非采用模型自报元数据；任一开关缺失时仍使用兼容 RAG 路径。

## 5. 真实数据审计

2026-08-02 的只读审计结果保存在：

- `docs/analysis/rag-data-quality-audit-20260802.ipynb`
- `docs/analysis/rag-data-quality-report-artifact.json`
- `docs/analysis/rag-data-quality-validation.md`
- `data/analysis/rag-canonicalization-plan-20260802.json`

聚合结论：

- 1,117 个 document 行中，383 个为 ready/enabled，357 个实际有 chunk。
- 两条独立校验路径都只识别出 4 个逻辑内容组，组大小为 180 / 59 / 59 / 59；存在 353 个多余重复行。
- legacy Chroma 向量覆盖为 0；54 个 chunk 缺 BM25；76 个文档的声明/实际 chunk count 不一致。
- 32 个有 chunk 的文档仍能解析源文件，覆盖全部 4 个逻辑组。
- dry-run canonicalization plan 每组选了 1 个源文件可用、BM25 完整且 chunk count 一致的 canonical 文档。

该 plan 没有删除、更新或合并任何业务行。重复数据治理必须另行审核，不能把“选出 canonical”理解为已获授权删除 353 行。

## 6. 独立真实演练

`scripts/rehearse_versioned_rag.py` 在全新、来源名称受限的 MySQL 克隆和独立 Chroma 目录中执行：

1. 创建并逐表核验主库克隆；
2. `0012 -> 0020`；
3. 按 canonical plan 迁移 4 个文档；
4. 校验 active head、manifest、DB chunk 和 Chroma vector 一致；
5. 跑 versioned hybrid benchmark；
6. `0020 -> 0012`；
7. 复核主库 revision/计数哈希不变；
8. 只删除本次新建的临时克隆。

2026-08-02 的两份报告是在当时的 `0019` head 上生成，属于历史性能和数据质量证据，不等同于当前 `0020` RAG 端到端演练。`0020 → 0019 → 0020` 已在守卫后的专用测试库验证；当前真实数据克隆也已完成纯 schema `0012 → 0020 → 0012` 并保持原表计数/回退哈希。2026-08-05 已用最新 structured parser 在隔离克隆重跑 4 个 canonical 索引、hybrid 评测和来源正确性，见下方最新报告。

首次报告 `data/rehearsals/versioned-rag-canonical-live-20260802.json` 暴露 P95 13,402.64 ms。Ollama 服务日志显示热态 `/api/embed` 实际只需约 40–370 ms，RTX 4070 已完成 25/25 层 CUDA offload；根因是 `OllamaProvider._embedder()` 在每次 query embedding 和 rerank embedding 前都重新构造客户端，各增加约 6 秒初始化。

`OllamaProvider` 现复用同一 provider 实例内的 embedding client，预检同时完成客户端/模型预热。修复后的完整报告为 `data/rehearsals/versioned-rag-canonical-cached-gpu-20260802.json`：

| 指标 | 2026-08-02 缓存修复版 | 2026-08-05 最新 0020 版 |
|---|---|---:|
| 演练完整性 | 通过 | 通过 |
| 迁移文档 / 失败 | 4 / 0 | 4 / 0 |
| active chunk / vector | 4 / 4 | 4 / 4 |
| Recall@K | 1.0 | 1.0 |
| MRR | 0.8333 | 1.0 |
| 引用正确率 | 1.0 | 1.0 |
| 空召回率 | 0.0 | 0.0 |
| abstention（观察指标，不计门禁） | – | 0.0 |
| P95 | 437.78 ms | 412.24 ms |
| 正式 2 秒质量/延迟 gate | 通过 | 通过 |
| case 人工复核 | 否 | 是（10 个 reviewed case） |
| rollout ready | 否 | 是 |

2026-08-05 最新报告为 `data/rehearsals/versioned-rag-canonical-0020-20260805.json`，`evaluation.status=passed`、`reviewed=true`、`rollout_ready=true`。10 个 reviewed case 覆盖真实意图（4）、重复文档（2）、引用边界（2）和无答案（2）；全部 recall=1.0、MRR=1.0、引用正确率=1.0。无答案 case 的 `abstention_rate=0.0`：Chroma 检索无相似度阈值，越界查询仍会返回 top-k 结果，这是已知局限，不阻断本轮门禁，但生产提示词层应自行做相关性兜底。演练后临时克隆已回退并删除，主库 revision 和当次计数哈希未变化。

技术 gate 已返回 `passed`，但 2026-08-02 的 `rollout_ready` 仍为 false，因为 4 个 generated case 尚未人工复核。演练后临时克隆已回退并删除，主库 revision 和当次计数哈希未变化；本轮临时 Ollama server/runner 也已停止。

## 7. 上线门禁（已完成）

2026-08-05 生产上线全部完成：

- 应用数据库已获明确授权并升级到 `0020`（48 张原表行数零变化，10,581 行精确保持；回滚克隆 `personal_assistant_preupgrade_20260805111304` 保留）。
- 最新源码在隔离克隆完成 `0012 → 0020 → 0012`，原表计数与回退哈希保持。
- 固定、人工复核的 10 个 case set 覆盖真实意图、无答案、重复文档和引用边界。
- 生产 hybrid 评测：Recall@K、MRR、引用正确率均 1.0，空召回率 0。
- P95 约 510 ms，正式默认阈值为 2 秒。
- DB chunk、Chroma vector、维度、manifest 和 active head 一致（4 / 4 / 1024）。
- 4 个 canonical 文档生产构建来源哈希与 canonical 计划一致。

`PA_VERSIONED_RAG_INDEXING_ENABLED=true`、`PA_VERSIONED_RAG_RETRIEVAL_ENABLED=true` 已写入 `.env`。未构建 versioned 索引的文档自动走 legacy 检索（见 `hybrid_retrieval.py` 中 active head 排除逻辑），两套路径无缝共存。

## 8. 运维命令

只读或 dry-run：

```powershell
uv run python scripts/profile_rag_data_quality.py --output data/analysis/rag-profile.json
uv run python scripts/plan_rag_canonicalization.py --output data/analysis/rag-plan.json
uv run python scripts/migrate_versioned_rag.py --limit 25
uv run python scripts/evaluate_rag.py --cases docs/rag-evaluation-cases.example.json --retrieval versioned
```

真实迁移和独立演练必须先确认目标数据库、隔离 `PA_DATA_DIR` 和报告路径。完整顺序见 `docs/deployment-guide.md` 和 `docs/database-upgrade-runbook.md`。
