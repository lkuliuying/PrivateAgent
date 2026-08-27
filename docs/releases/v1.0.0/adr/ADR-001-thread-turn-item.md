# ADR-001 · Thread/Turn/Item 公共领域模型与兼容矩阵

> 状态：Accepted（2026-08-24 技术评审通过）
> 日期：2026-08-24
> 关联：上位计划 §7；v0.9 h0 契约 §4；`agents/contracts.py` AgentEventType（34 类）
> 冻结测试输入：`tests/test_v090_h0_contracts.py`

## 1. 模型与字段（基线 = 上位计划 §7.2–7.4）

### 1.1 Thread

字段：`id`、`project_id`、`workspace_id`、`status`、`title`、`created_at`、`updated_at`、`archived_at`、`settings_snapshot`、`instruction_snapshot_id`、`protocol_version`，扩展预留 `parent_thread_id`、`source_kind`、`budget_inheritance`（nullable，1.0 不启用，§13.3）。

约束（继承 v0.9 h0 §4.2 冻结）：
- 新 Thread 必须具有非空 `project_id` + `workspace_id`；
- 不因导航静默改变工作目录；换目录 = 另一 Workspace；
- legacy/unbound 会话保留可读，绑定仅显式入口（迁移后为显式迁移动作，见 ADR-005）。

### 1.2 Turn 状态机

```text
queued → running ↔ waiting_approval
  │        ├→ completed / failed / timed_out / limit_exceeded
  └────────┴→ interrupted
```

| 转移 | 触发者 | 持久化义务 |
|---|---|---|
| queued→running | orchestrator admission（幂等 + ownership） | `turn/started` 通知 + Turn 行快照 |
| queued→interrupted | `turn/interrupt`（尚未 admission） | 取消排队 ownership，落终态且不启动模型/工具 |
| running→waiting_approval | tool lifecycle 请求审批 | `approval_request` Item 落库（跨重启可恢复） |
| waiting_approval→running | `approval/resolve`（token + 防重放） | `approval_resolution` Item |
| waiting_approval→interrupted | `turn/interrupt` | 原子终结未决审批、使审批 token 失效，落中断终态 |
| running→completed/failed/timed_out/limit_exceeded | terminalization | 终态 Item + usage + 公开报告 |
| running→interrupted | `turn/interrupt` | 取消模型/工具/进程树/流后落终态 |

规则：一 Thread 最多一个有副作用 active Turn；`turn/start` 以 `client_request_id` 幂等；`turn/steer` 只追加用户输入 Item；running 模型调用无法证明完成时恢复为 interrupted/failed，不伪造 continuation（§11.3）。

### 1.3 Item（15 种 P0 kind）

`user_message`、`agent_message`、`public_reasoning_summary`、`plan`、`plan_step`、`command_execution`、`file_change`、`patch_set`、`tool_call`、`approval_request`、`approval_resolution`、`verification`、`artifact`、`context_compaction`、`error`。

公共字段：`item_id`、`thread_id`、`turn_id`、`kind`、`status`、`sequence`（同 Turn 单调）、`created_at`、`completed_at`、`public_payload`、`content_ref`、`schema_version`。大输出只存摘要 + 引用。隐私：不持久化隐藏 chain-of-thought（v0.9 h0 §8 冻结延续）。

## 2. v0.9 → v1 兼容矩阵（本 ADR 核心）

### 2.1 对象映射

| v0.9 | v1.0 | 规则 |
|---|---|---|
| Project | Project（不变） | 保持原 ID |
| ProjectWorkspace（kind=root\|git_worktree） | Workspace/Environment | 保持原 ID；cwd/root/Git facts/权限根 |
| Session（kind=coding） | Thread | 原 ID 进映射表；`settings_snapshot` 取会话级权限/模型设置 |
| Session（kind=legacy，含 unbound） | Thread（source_kind=legacy） | 只读可导出；未绑定者 `workspace_id` 指向迁移期占位环境或保持显式迁移入口（ADR-005 §2.5） |
| AgentRun | Turn | 原 run_id 进映射表；`permission_snapshot_json` → Turn 权限快照 |
| RunPlan | `plan` + `plan_step` Items | 不再是旁路状态机 |
| ToolApproval | `approval_request`/`approval_resolution` Items + 独立审计事实 | UI 从 Item 观察，审计表保留 |
| ToolExecution | `command_execution`/`tool_call` Items + 独立审计事实 | 同上 |
| Artifact | `artifact` Item + content_ref | 有界存储不变 |

### 2.2 事件映射（AgentEventType 34 类 → Item/生命周期事件）

| v0.9 事件 | v2 表达 |
|---|---|
| `run.started` | `turn/started` 通知（Turn 行落库） |
| `context.prepared` | context fragment 元数据（不落公共 Item，诊断可见） |
| `model.started` / `model.completed` | `agent_message`/`public_reasoning_summary` Item 的 started/completed 生命周期 + usage |
| `chat.output_persisted` | `agent_message` Item completed |
| `tool.requested` | `tool_call` Item started |
| `tool.approval_required` | `approval_request` Item + `approval/required` 通知 |
| `tool.approval_resolved` | `approval_resolution` Item |
| `tool.started` / `tool.completed` / `tool.failed` | 对应 Item 生命周期（failed 附错误信封字段） |
| `patch_set.preview_created` | `patch_set` Item（proposal 态）+ `file_change` 预览 |
| `patch_set.applied` / `rolled_back` / `failed` / `unknown` | `patch_set` Item 终态（unknown 阻止自动继续） |
| `plan.created` / `plan.updated` / `plan.item_changed` | `plan`/`plan_step` Item started/delta/completed |
| `artifact.created` | `artifact` Item completed |
| `output.validation_started/passed/failed` | `verification` Item |
| `context.compaction_started/completed/failed` | `context_compaction` Item |
| `decision.summary` | `public_reasoning_summary` Item（payload 七键原样） |
| `permission.downgraded` | `error` Item（低基数原因）+ 审计 |
| `run.completed/failed/cancelled/timed_out/limit_exceeded` | Turn 终态 + `turn/completed`/`turn/status/changed` 通知（cancelled→interrupted） |

无法映射项处置：隔离到 migration report 并生成通用 `error`/diagnostic 记录，不静默丢弃（上位计划 §14.2）。

### 2.3 状态映射

| v0.9 run status | v2 Turn status |
|---|---|
| queued / running / waiting_approval（v0.9 以事件表达） | queued / running / waiting_approval |
| completed / failed / timed_out / limit_exceeded | 同名 |
| cancelled | interrupted |

## 3. 关键问题决议

1. **恢复重演顺序**：重启后按 `(turn_id, sequence)` 从事件 store 重放至快照点，先恢复 Turn 状态，再按 Item sequence 重建未决 `approval_request`；快照仅加速，不取代事件（§11.2/§11.3）。
2. **steer 时序**：`turn/steer` 写入新 `user_message` Item 后立即返回；模型循环在下一个安全点（当前 tool 边界或流式块边界）消费，不创建第二个 Turn（§7.3）。
3. **unknown 表达**：`command_execution`/`patch_set`/`tool_call` Item 支持 `status=unknown`；仅 `execution/unknown/resolve` 人工动作可推进，自动重试路径在 lifecycle 层硬禁止（§10.3）。
4. **content_ref 边界**：指向 artifact 有界存储（复用或扩展，归属 ADR-003 §2.1）；事件/通知只带引用与摘要。
5. **schema_version**：Item 级携带；未知 kind 由前端渲染通用卡片并记诊断（§8.4-4），未知字段忽略。

## 4. 决策

评审接受本模型与兼容矩阵，并补齐 queued/waiting approval 的中断语义。§2 矩阵从本决议生效起成为 S2 离线 mapper（S2-T7）与 S7 迁移（ADR-005）的唯一事实源；任何矩阵变更须同步更新本文件与 contract/golden 测试。
