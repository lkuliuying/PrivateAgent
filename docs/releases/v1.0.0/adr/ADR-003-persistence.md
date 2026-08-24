# ADR-003 · v2 持久化：表结构、序列仲裁、Store 边界与投影一致性

> 状态：Accepted（2026-08-24 技术评审通过）
> 日期：2026-08-24
> 关联：上位计划 §11；执行计划决议 D6；ADR-001（Item 模型）；ADR-005（迁移）
> 现状输入：`agents/repository.py` record_event/_project、migration 0013–0033

## 1. v0.9 基线（保留的仲裁资产）

现有 `record_event` 已验证的机制，v2 全部继承而非重造：

1. **行锁 + 严格序列**：`SELECT ... FOR UPDATE` 锁 run 行（`populate_existing` 强制读最新已提交事实），`expected = last_event_sequence + 1` 强校验；
2. **幂等去重**：同 `(run_id, sequence)` 且 type/step/payload 完全一致的重写视为幂等成功；冲突则抛序列错误；
3. **投影不变式**：首事件必须是 `run.started`；终态 run 拒绝新事件；快照纠偏只接受 `last_event_sequence ≥ 游标` 的事实；
4. **事实表形态**：`agent_runs` / `run_steps` / `agent_run_events` / `agent_run_checkpoints` / `agent_tool_executions` / 审批表 / `coding_patch_sets(_files)` / `run_plan_items` / `agent_run_artifacts`（引用式，`content_sha256` + workspace 相对路径）。

## 2. v2 表设计（全 additive，表名冻结候选）

| 表名 | 职责 | 关键列 |
|---|---|---|
| `agent_threads_v2` | Thread 命令态 | `id CHAR(36) PK`、`project_id`、`workspace_id`、`status`、`title`、`settings_snapshot_json`、`instruction_snapshot_id NULL`、`protocol_version`、`parent_thread_id NULL`、`source_kind NULL`、`budget_inheritance_json NULL`、`archived_at NULL`、时间戳（DATETIME(fsp=3) naive UTC，延续 §5 时区契约） |
| `agent_turns_v2` | Turn 命令态 | `id PK`、`thread_id FK`、`status`（ADR-001 §1.2 集合）、`client_request_id`、`permission_snapshot_json`、`provider_profile_snapshot_json`、`last_event_sequence BIGINT`、`last_event_hash CHAR(64)`、`owner_key VARCHAR`、终态字段 |
| `agent_items_v2` | Item 命令态 + 读模型 | `item_id PK`、`thread_id`、`turn_id`、`kind`（VARCHAR(48)，不用 ENUM——unknown kind 必须可存）、`status`、`item_sequence BIGINT`（Item 创建顺序）、`last_event_sequence BIGINT`、`public_payload_json`、`content_ref VARCHAR(2048) NULL`、`schema_version`、`created_at`、`completed_at NULL` |
| `agent_events_v2` | append-only 事件事实 | `id BIGINT AI`、`turn_id`、`thread_id`（冗余，免 join 读）、`event_sequence BIGINT`、`event_type VARCHAR(64)`、`item_id NULL`、`payload_json`、`prev_event_hash CHAR(64)`、`event_hash CHAR(64)`、`created_at`；`UNIQUE(turn_id, event_sequence)` |
| `agent_snapshots_v2` | 恢复加速 | `turn_id PK`、`snapshot_version`、`event_sequence`、`state_json`、`checksum CHAR(64)`、时间戳 |
| `agent_instruction_snapshots` | 指令快照 | `id PK`、`thread_id NULL`、`turn_id NULL`、`sources_json`（path scope/hash/bytes/顺序/信任类型，§9.2）、`content_ref`、`total_bytes` |
| `agent_protocol_metadata` | 幂等 + 投影元数据 | `client_request_id PK`、`turn_id`、`protocol`（v090\|v2）、`created_at`、`expires_at` |

索引要点：`agent_items_v2 (turn_id, item_sequence)` 唯一、`(thread_id, created_at)` 列表分页；`agent_events_v2 (turn_id, event_sequence)`、`(thread_id, event_sequence)` 补读；`agent_turns_v2 (status, owner_key)` 恢复扫描、`(thread_id, created_at)`。

字符集/引擎延续项目基线：utf8mb4 / utf8mb4_unicode_ci / InnoDB。migration 编号延续 `0034+`，全部 additive，不动 v0.9 表。

## 3. 序列仲裁（v2 规则）

1. `event_sequence` 作用域为 **Turn**（对齐协议 §8.4-3），生成与校验完全复用 v0.9 行锁模式：锁 `agent_turns_v2` 行 → `expected = last_event_sequence + 1` → 写 `agent_events_v2` + 投影 `agent_items_v2` 于同一事务；
2. Item 的 `item_sequence` 是首次 `item/started` 时分配的稳定排序号；后续 delta/completed/failed 各自获得新的 `event_sequence`，并更新 Item 的 `last_event_sequence`。因此“一个 Item 多个生命周期事件”与“Turn 事件严格单调”同时成立，不伪造一一对应；
3. 幂等重写判定沿用 v0.9（type/item/payload 全等 → 幂等成功）；
4. 单 Turn 单执行器 + owner_key（ADR-001 §1.2 / §14.3 互斥），行锁只作兜底不作并发设计。

## 4. Store 边界（§11.2 落地）

| Store | 职责 | 禁止 |
|---|---|---|
| Command store | Thread/Turn/Item 状态事务（同事务写 events + items + turns） | 不做列表查询优化 |
| Event store | append-only；只增不改不删；sequence 唯一 | 不承担读模型 |
| Snapshot store | 恢复加速；每个 Turn 终态或每 N 事件落一次；携带 `checksum` 与 `event_sequence` | 不取代事件事实（恢复以事件为准） |
| Read model | Thread 列表/搜索/历史分页（`agent_items_v2` 直查 + 覆盖索引） | 不写事实 |

## 5. 投影一致性（checksum 与重建）

1. **事件哈希链**：`event_hash = sha256(prev_event_hash ‖ turn_id ‖ event_sequence ‖ event_type ‖ canonical(payload))`，`prev_event_hash` 为该 Turn 上一事件哈希（首事件用固定 genesis）。`prev_event_hash` 与 `event_hash` **必须落事件行**，Turn 行同步保存 `last_event_hash`；只计算不落库无法形成可校验的预期根，不得称为防篡改链；
2. **投影校验**：重建器从事件流重放生成 Item 集合与 Turn 终态，与 `agent_items_v2`/`agent_turns_v2` 现状逐条比对，输出结构化差异报告；
3. **失败即报警**：任何不一致 → 该 Turn 投影标记 `projection_inconsistent`，阻止继续写入并进入诊断（对齐 §11.2"失败并报警"与 §22 停止条件）；
4. 校验入口：S2 起作为 replay 测试常驻；S7 起纳入升级演练（时间戳克隆上跑全量重建）。

## 6. 幂等与保留

1. `client_request_id` 全局唯一（跨 protocol，§14.3"同一 key 只能归属一个 protocol/runtime"）；`agent_protocol_metadata.protocol` 记录归属，重复请求跨协议冲突 → 拒绝并审计；
2. 保留窗口：终态 Turn 的幂等记录保留 90 天后由维护任务清理（清理前校验 Turn 终态）；未终态永不清理；
3. 事件行大小：`payload_json` 上限 1 MiB（对齐 ADR-002 消息限制）；超限内容强制转 `content_ref`（artifact 存储复用 `agent_run_artifacts` 形态，v2 新表与否在 S2 migration 评审时定，倾向复用 + `turn_id` 兼容列）。

## 7. 测试策略（决议 D6）

1. 日常：本地独立可重建测试库（`prepare_test_database.py` 口径），测试前自动重建；
2. 升级/迁移演练：`clone_application_database.py` 时间戳克隆，禁止直接操作日常应用库；
3. 必备套件：严格序列冲突测试（复刻 `test_v060_c*` 口径）、幂等重写/冲突、投影重建 checksum、5000+ Item 分页读、恢复扫描（未终态 + waiting_approval）。

## 8. 决策

评审接受表名、Store 边界和 additive 策略，并修正两个关键问题：Item 创建序列与事件序列分离；哈希链必须持久化链值与 Turn 根。修正后的表结构进入 0034 migration（S2-T4），序列、hash chain 与 checksum 规则进入 contract/replay 测试（S2-T8）。
