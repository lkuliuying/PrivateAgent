# ADR-005 · v0.9 → v1 数据迁移：映射、游标、重入与回退

> 状态：Accepted（2026-08-24 技术评审通过）
> 日期：2026-08-24
> 关联：上位计划 §14；ADR-001（映射矩阵唯一事实源）；ADR-003（v2 表）；决议 D6
> 现状框架：`scripts/rehearse_database_upgrade.py`（源/升级库对照 + 保留断言）、`scripts/clone_application_database.py`（时间戳克隆）

## 1. Strangler 数据侧落点（§14.1 八阶段对应）

| 阶段 | 数据动作 | 依赖 |
|---|---|---|
| 1 旁构建 | 0034+ additive migration 建 v2 表，默认关闭 | ADR-003 |
| 2 离线映射 | ADR-001 §2 矩阵实现为离线 mapper（只读 v0.9 表 → v2 fixtures） | ADR-001 |
| 3 shadow | 只消费已落库 facts 生成投影与差异报告；**不调用模型、不执行工具** | mapper |
| 4 dogfood | 全新 v2 Thread，不经迁移 | S3/S4 |
| 5 显式迁移 | 用户选定 v0.9 Conversation 受控迁移（本 ADR 执行器） | mapper + 执行器 |
| 6 Beta 1 默认 | 新 Thread 默认 v2；旧 Thread 由 `rest_v090` adapter 读取 | S5 |
| 7 Beta 2 | 回退、归零、升级验证 | S7 |
| 8 RC 冻结 | schema/feature 冻结 | S9 |

## 2. 迁移执行器设计

### 2.1 单元与批次

1. 迁移单元 = 一个 v0.9 Session（→ Thread）及其全部 AgentRun（→ Turn）；
2. 批内事务：Thread 行 + ID 映射表行同事务提交；每个 Turn 独立事务（失败不牵连其他 Turn，隔离到 report）；
3. 批次大小默认 50 Turn/批，可配置；每批结束写 `migration_cursor`。

### 2.2 游标与重入（可暂停/续跑/重入）

迁移状态表 `agent_v2_migration_state`（additive）：

| 列 | 语义 |
|---|---|
| `migration_run_id` | 一次迁移作业标识 |
| `source_session_id` / `source_run_id` | 当前游标 |
| `source_row_count` / `source_hash` | 迁移前快照统计（行数 + 抽样内容哈希），验收对照用 |
| `failure_cursor_json` | 最近失败单元 + 原因码 |
| `status` | running / paused / completed / failed / quarantined |

重入规则：以 `(source_session_id)` 幂等——映射表已有条目即跳过；已部分完成的 Session 按 Turn 级游标续跑；任何时刻杀掉进程后重启可从 `migration_cursor` 恢复，不产生重复 Item（目标侧 `item_id` 由 `source 事件 ID 派生` 保证天然幂等）。

### 2.3 失败隔离（不静默丢弃）

无法映射/不完整/冲突记录 → `agent_v2_migration_quarantine`（additive）：source 标识、原因码（`unknown_event_type` / `missing_fk` / `payload_conflict` / `sequence_gap`）、原始行 JSON 快照；migration report 汇总计数与明细引用。quarantine 项不阻塞其他单元；人工处置后支持单项重试。

### 2.4 防双副作用（§14.3）

1. `client_request_id` / 执行 ownership key 写入 `agent_protocol_metadata`（ADR-003 §6），v0.9 与 v2 互斥；
2. 迁移中的 Session 打 `migrating` 标记：v0.9 侧禁止新 Run，v2 侧未 `completed` 前不接新 Turn；
3. adapter 不得把 v2 tool result 回灌旧 planner（S5/S7 测试注入重复请求验证）；
4. shadow 仅读已落库 facts，无写路径。

### 2.5 legacy/unbound 会话

`kind=legacy` 且未绑定项目的 Session：迁移为 `source_kind=legacy` 的只读 Thread（无 workspace 执行能力，仅历史可读/导出）；显式绑定入口延续 v0.9 h0 §4.2 唯一入口语义（绑定后才获得执行能力）。不做批量绑定、不做最近项目猜测。

## 3. 升级矩阵与演练（决议 D6）

1. **v0.5/v0.8/v0.9 → v1**：统一先经既有 alembic 链升到 0033 口径，再跑 v2 additive + 迁移（不实现跨版本直达捷径，复用 `rehearse_database_upgrade.py` 的源/升级对照与保留断言）；
2. 演练一律在 `clone_application_database.py` 时间戳克隆上进行；禁止直接操作日常应用库；
3. 验收指标（§22 停止条件对应）：行数一致、抽样哈希一致、关系一致性（FK/映射表双向全连接）、重复副作用 = 0、数据丢失 = 0；
4. 故意故障注入（§14.3）：重复请求、断线、进程杀死、owner 切换、未决审批、迁移中途 orphan——每项有专项测试用例。

## 4. 应用回退（§14.3/§20）

1. v1 应用回退到 v0.9：v0.9 二进制忽略全部 `_v2`/`agent_protocol_metadata`/migration state 表，直接读取原表历史（全 additive 的直接推论，无需代码分支）；
2. 已迁移 Thread 的 v0.9 原数据保持只读存在，回退后原 Conversation 照常可读；
3. 回退窗口内禁止"双向回写"：v2 新产生的 Thread/Turn 在 v0.9 中不可见（文档明示），避免用户误以为丢数据——S7 需在回退说明中列出。

## 5. 决策

评审接受 Strangler 阶段、Turn 级事务、游标重入、quarantine、防双副作用和 additive 回退语义。`agent_v2_migration_state` / `agent_v2_migration_quarantine` 表并入 0034+ migration；S7-T2 实现执行器；升级演练脚本扩展为克隆上全自动矩阵。
