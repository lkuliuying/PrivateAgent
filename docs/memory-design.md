# 记忆与会话压缩设计

## 当前桌面本机链路（2026-09-20）

当前 `private_agent_local` 的记忆分为三层。2026-09-20 已删除旧完整后端源码，本文后半部分的 MySQL/Chroma 设计仅为历史，不是可运行的第二条链路。

| 层次 | 本机事实源 | 进入请求的方式 |
|---|---|---|
| 项目规则 | 受信任的项目根及子目录 `AGENTS.md` | 按目标目录加载，变更后重新检查；不扩大工具权限 |
| 短期记忆 | `projects.sqlite3` 的 `context_items`、`context_checkpoints` | 当前会话原始历史与派生压缩视图；保留用户原文、完整工具配对和来源引用 |
| 长期记忆 | 同一本机身份目录的 `memories.sqlite3`（schema 1） | 按项目及跨项目偏好召回，为可选参考数据；不写入原始会话历史 |

长期记忆行为参考 [Codex Memories](https://learn.chatgpt.com/docs/customization/memories)：默认关闭，使用与生成独立控制，支持单会话排除，在后台处理空闲会话。采用本项目已有 SQLite 与模型接口，不声称复现 Codex 内部算法或与其记忆文件格式兼容。

### 开关、来源与调用边界

- 设置 → 记忆：总开关、使用开关、生成开关、生成模型、空闲时间、每日调用上限、排除外部文档会话；会话上下文面板另有两个独立开关。全局与会话均允许时才生效。
- 默认总开关关闭，开启生成前界面说明会向所选模型发送会话片段，可能产生费用。只处理开启或重新开启之后新增的内容，不回溯关闭期间的历史。生成模型默认沿用会话模型。
- 执行器存活时每 30 秒检查一次；有活动任务时不启动生成。来源必须为最近 30 天内已完成且空闲至少 300 秒的会话，至少含两条尚未处理的有效用户消息。失败、取消、未完成和过短会话不处理。
- 默认跳过曾调用 `call_documentation_tool` 的会话。只提取用户及助手消息，不发送工作区文件、工具结果正文或历史 `legacy` 导入内容；历史中被引用或粘贴的外部内容不能靠来源标签完全识别。
- 单批最多 32 条、12000 字符；单条超过 6000 字符或含疑似凭据时整条跳过。单次生成超时 60 秒，输出最多 2048 tokens，严格校验 JSON、条目数量、长度、范围与用户来源引用。错误不回显模型正文，失败至少等待 15 分钟后再尝试。
- 默认每日最多 12 次生成尝试（UTC），包含失败和取消；这是生成调用次数限制，不是费用金额上限。应用重启保留当天计数，中断的运行标记为取消。
- 凭据过滤包括常见密钥格式、敏感字段赋值和当前已加载模型凭据；它不是完整隐私分类器，无法保证识别所有敏感个人信息。模型被要求只提取用户明确陈述的长期事实，仍可能归纳错误，用户可查看和修正。

### 保存、召回与遗忘

- 每个项目及跨项目偏好范围最多各 200 条。跨项目条目仅允许 `preference`；项目条目支持偏好、决定、工作流经验和参考位置。
- 保存来源会话、条目 ID、来源时间与版本。相同主题键按新来源时间更新；内容哈希去重。人工编辑优先，不被自动生成覆盖；版本冲突返回 409，要求刷新后编辑。
- 生成结果写入、处理游标和尝试状态同事务提交。保存前重新检查设置版本、会话来源、活动任务和管理操作版本；在途生成遇到关闭、编辑、遗忘或来源变化时取消或丢弃。
- 请求时以关键词、人工维护标记和更新时间排序，最多召回 8 条、约 6000 UTF-8 字节的条目数据。自动生成且关键词零匹配的条目不再注入；人工维护的当前作用域条目仍可用。没有向量索引或语义检索服务。记忆明确标为可能过时的数据，现行规则、当前用户请求和现场证据优先。
- 可选记忆计入完整请求预算。达到压缩阈值或输入上限时先移除记忆，再对会话历史应用原有压缩和硬限制；运行记录及会话面板展示召回和省略数量。
- 遗忘清除记忆正文，保留主题及内容的去重哈希，阻止相同键或相同内容从旧历史再次生成；不能保证阻止语义相同但换了主题键、改写了措辞的模型输出。会话原文不随遗忘删除，已发出的模型请求不能撤回。
- 删除会话清理其自动提取的记忆，人工维护内容独立保留；删除项目清理项目记忆。每次启动也核对来源，处理跨数据库删除在中断时遗留的记录；全局遗忘标记不因删除来源会话失效。
- 两个数据库仍按本机身份空间隔离。现有历史迁移/导出不包含独立的 `memories.sqlite3`，不自动合并旧后端或旧账号记忆；这不是备份格式升级。

### 模块与验证

`memory_store.py` 负责策略、事实、版本及去重，`memories.py` 负责后台提取与召回，`memory_routes.py` 提供身份保护的管理接口。运行时持有后台任务，关闭或切换身份时先取消任务再释放数据库与凭据。

- 管理 API：`GET/PUT /local-memories/settings`、`GET /local-memories/status`、`GET/POST /local-memories/items`、`PUT/DELETE /local-memories/items/{id}`。项目条目需携带 `project_id`，修改需携带 `expected_version`。
- 会话 API：`GET/PUT /sessions/{id}/memory-settings`。
- 隔离后端测试：`.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite memory`。使用临时 SQLite 与模拟模型，不读取用户数据库、不产生模型费用。
- 前端测试位于 `memories.spec.ts`、`MemorySettingsPanel.spec.ts`、`SessionMemoryPanel.spec.ts`；浏览器验收为 `e2e/memories.spec.ts`，模拟本机 IPC 并阻断外部请求。

## 已退役的旧完整后端设计

> 以下记录适用于已删除的 `personal_assistant`，其中源码、迁移和命令不再适用于当前仓库；保留历史结论，不用于判断本机功能。

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
