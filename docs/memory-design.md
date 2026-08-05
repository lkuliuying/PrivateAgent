# 记忆与会话压缩设计

> 状态：结构化记忆版本、冲突、软删除和可追溯摘要已实现；自动抽取与自动摘要继续采用候选/显式启用策略。

## 1. 分层模型

PrivateAgent 把记忆分成三个层次：

| 层次 | 事实源 | 用途 |
|---|---|---|
| 短期上下文 | `messages` + `conversation_summaries` | 当前会话连续性和旧消息压缩 |
| 长期结构化记忆 | `memory_items` + `memory_revisions` + `memory_conflicts` | 可查看、修正、确认、过期和删除的事实 |
| 语义索引 | Chroma 中可重建的向量表示 | 只服务相关性召回，不是事实源 |

核心代码：`src/personal_assistant/core/memory.py`、`repo_memories.py`、`memory_candidates.py`、`context_summaries.py` 和 `src/personal_assistant/api/routes_memories.py`。

## 2. 结构化记忆生命周期

迁移 `0017_context_memory_facts.py` 为 `memory_items` 增加：

- `stable_key`、`memory_version`、`content_sha256`
- `importance`、`expires_at`
- `sensitivity_level`
- `confirmed_at`、`last_confirmed_at`
- `deleted_at`

每次创建、编辑、确认或删除都会把完整可审计快照写入不可变的 `memory_revisions`。相同 stable key 采用单调版本；内容哈希用于检测重复或并发变化。

记忆状态遵循：

```text
candidate -> confirmed -> disabled
    |            |           |
    +------------+-----------+-> soft deleted
```

- 自动提取只生成 candidate，不自动把低置信或敏感内容写成已确认事实。
- `confirmed`、启用、未过期、未软删除且 `sensitivity_level=normal` 的记忆才可进入默认 ContextBuilder。
- 编辑和冲突解决生成新 revision，不覆盖历史证据。
- 删除是软删除；物理清理必须是单独、可审计的维护动作。

## 3. 候选提取与确认

`MemoryCandidateService` 从明确用户陈述中生成候选，并限制标题、摘要和内容长度。敏感信息、低置信内容、临时上下文或与现有事实冲突的内容不得静默启用。

`routes_memories.py` 提供创建候选、查询、更新、确认使用、查看 events/revisions 和删除端点。API 不返回秘密配置，ContextBuilder 也不会把敏感记忆发送到远程 provider。

自动长期记忆写入 worker 尚未启用。这是安全选择：在没有真实误写率、撤销体验和敏感分类验收前，系统只提供候选和显式确认链路。

## 4. 冲突模型

`memory_conflicts` 显式连接左右两条记忆并保存原因、状态、解决结果和时间。冲突不能通过“最后写入者覆盖”消失；用户可以选择保留左侧、右侧、两者、合并或废弃，解决动作进入 revision/event 证据。

唯一的 `(left_memory_id, right_memory_id)` 约束避免重复登记同一有序冲突对。调用方在创建前应规范化 ID 顺序。

## 5. 会话摘要

`ConversationSummaryRepository` 保存精确消息范围、source SHA-256、生成配置、token 使用和状态。摘要只替代 ContextBuilder 中的旧消息表示，不删除 `messages`。

同源摘要幂等；更正生成新 `summary_version` 并把旧版本标记为 superseded。敏感摘要保留审计但不进入默认非敏感上下文。

`ConversationSummaryService` 从 active 摘要最高水位之后选择连续旧消息，始终保留最近消息，并同时限制单批消息数和字符数。后台 worker 默认关闭、要求 schema `0017+`，用 MySQL 命名锁防止多进程重复生成；结构化输出验证失败不会落库。远程 provider 需要独立二次许可，避免仅因聊天 provider 改为远程就自动上传历史消息。

## 6. 语义记忆与一致性

MySQL 永远是记忆事实源；Chroma 只保存可再生成的表示。结构化记忆变更时，应先提交 MySQL revision，再构建/更新语义索引。向量写入失败不能回滚已提交的事实修改，应记录待重建状态并由维护任务补偿。

当前版本化 RAG 索引主要覆盖文档；记忆专用的版本化向量 head 尚未单独引入。数据量或召回需求未达到阈值前，不新增第二套向量数据库。

## 7. API 与 UI

主要端点：

- `GET/POST /memories`
- `GET/PATCH/DELETE /memories/{memory_id}`
- `POST /memories/search`
- `POST /memories/candidates`
- `GET /memories/{memory_id}/events`
- `GET /memories/{memory_id}/revisions`
- `GET/POST /memory-conflicts`
- `POST /memory-conflicts/{conflict_id}/resolve`

前端记忆管理继续使用兼容 API；版本、哈希、有效期、敏感级别和冲突字段已加入返回契约。批量恢复/合并 UI 尚未完成，出现真实操作需求后再补。

## 8. 验证和回滚

```powershell
uv run pytest -q tests/test_memory_facts.py tests/test_phase4_memories.py `
  tests/test_context_builder.py tests/test_agent_context.py
```

关闭 ContextBuilder 或候选提取不会删除记忆。schema downgrade 会删除 revisions、conflicts、summaries 以及 `memory_items` 新字段；只有在确认升级后没有必须保留的新事实，并且已有完整数据库克隆时才能执行。
