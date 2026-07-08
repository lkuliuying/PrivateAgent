# 私人助手 Agent · 第六阶段开发计划书

> 对应 `docs/phase6-requirements.md`。第六阶段定位为“主动个人中枢”：在第五阶段已经具备可复现发布工程基础的前提下，补齐今日入口、统一收件箱、提醒与例行回顾、目标追踪、主动简报、隐私审计和数据体检。当前仓库已有聊天、知识库、项目、学习、任务、记忆、Provider、备份和发布工程化，本计划书以这些真实能力为基线，不重复实现已有模块。

---

## 1. 阶段判断

当前项目已经具备：

1. **响应型工作台**
   - 用户进入聊天、知识库、项目、学习、任务、记忆、设置七个入口。
   - 每个入口都有独立数据和操作。

2. **长期上下文**
   - 长期记忆可 CRUD、搜索、候选生成、聊天注入。
   - 学习主题有复习调度、错题、薄弱点和周报。
   - 任务有计划草稿、审批、步骤执行、证据和最终报告。

3. **治理底座**
   - 工具调用可审批、可审计。
   - Provider 有远程启用开关和发送范围提示。
   - 备份导出和恢复预览可用。

4. **分发底座**
   - Windows NSIS 安装包、sidecar、updater artifact、发布清单脚本可用。
   - v0.1.1 sidecar 已重新构建并验证 MySQL 8 `cryptography` 打包修复。
   - GitHub Release 资产上传、代码签名和跨平台实机 smoke 仍归第五阶段 release checklist 跟踪，不作为第六阶段产品能力的前置条件。

主要缺口：

| 缺口 | 影响 | 第六阶段对应 |
|---|---|---|
| 没有今日入口 | 用户每天不知道先处理什么 | M2 |
| 没有统一收件箱 | 行动项散落在聊天、任务、学习、活动中 | M2 |
| 没有通用提醒 | 学习有 due_at，但个人事项/例行回顾无法主动提醒 | M3 |
| 没有统一目标层 | 学习、任务、集合各自有 goal，缺少长期目标视图 | M4 |
| 没有主动简报 | 系统不会主动汇总当天/本周重点 | M5 |
| 远程 Provider 治理粗 | 只有范围提示，缺少请求级审计和上下文预览 | M6 |
| 数据体检轻量 | 备份、失败导入、孤立数据没有每日暴露 | M6 |

---

## 2. 总体目标

第六阶段交付后，用户每天打开应用应能完成三个代表场景：

### 场景 A：今日处理

1. 打开应用进入“今日”。
2. 看到到期复习、提醒、待审批任务、失败导入、候选记忆和数据体检。
3. 生成今日简报。
4. 把一条建议转为任务草稿。
5. 批准后执行，执行结果沉淀为任务证据或候选记忆。

### 场景 B：提醒闭环

1. 用户在聊天或今日页创建“明天下午复习 MySQL 索引”。
2. 系统保存 reminder 和 inbox item。
3. 到期后今日页显示，可选桌面通知。
4. 用户完成后，提醒进入 done；重复提醒生成下一次。

### 场景 C：周回顾

1. 用户打开目标页，选择一个长期目标。
2. 系统汇总相关学习、任务、文档集合、记忆和活动。
3. 生成周回顾和下周建议。
4. 用户把建议保存为 inbox items 或任务计划。

---

## 3. 里程碑

### M0 · 第六阶段文档与范围校准

目标：基于当前真实代码状态，定义第六阶段边界。

任务：

- [x] 新增 `docs/phase6-requirements.md`。
- [x] 新增 `docs/phase6-plan.md`。
- [x] 更新 README 第六阶段引用。
- [x] 更新 `docs/requirements.md` 后续阶段表。
- [x] 更新 `docs/usage-guide.md` 路线图。
- [x] 明确第五阶段剩余真实发布 smoke 不属于第六阶段核心产品能力。

验收：

- 第六阶段不与旧 phase4/phase5 文档编号冲突。
- 需求文档和计划书是两份独立文档。
- 文档中不把规划写成已实现。

### M1 · 数据底座与聚合服务

目标：新增今日中枢所需的数据结构和查询服务。

任务：

- [x] 新增迁移 `0009_phase6_proactive_hub.py`。
- [x] 新增 ORM：
  - `InboxItem`
  - `Reminder`
  - `PersonalGoal`
  - `GoalLink`
  - `GoalCheckin`
  - `Briefing`
  - `ProviderCallAudit`
- [x] 新增 core repo/service：
  - `repo_inbox.py`
  - `repo_reminders.py`
  - `repo_goals.py`
  - `repo_briefings.py`
  - `repo_privacy.py`
  - `today.py`
- [x] 聚合现有来源：
  - 学习 due cards。
  - Agent task 状态。
  - Activity failed。
  - draft memories。
  - backup list。

验收：

- Alembic head 前进到 `0009`。
- `pytest` 可在空数据和有数据场景下通过。
- 今日聚合服务没有引入 UI 依赖。

### M2 · 今日入口与统一收件箱

目标：用户每天有一个明确入口，所有待处理项集中可见。

任务：

- [x] 新增 API：
  - `GET /today`
  - `GET /inbox`
  - `POST /inbox`
  - `PATCH /inbox/{id}`
  - `POST /inbox/{id}/to-task`
  - `POST /inbox/{id}/to-reminder`
- [x] 新增前端：
  - `TodayView.vue`
  - `InboxPanel.vue`
- [x] 导航新增“今日”。
- [x] 从现有来源创建 inbox item：
  - 失败活动。
  - 待审批任务。
  - draft 记忆。
  - 聊天消息手动保存。
- [x] 今日页支持完成、稍后、忽略、跳转来源。

验收：

- 今日页在无数据时有空状态。
- 今日页在有 due card / failed activity / draft memory 时展示正确。
- inbox item 完成不删除原始对象。
- `npm run build` 通过。

### M3 · 提醒与例行任务

目标：补齐通用提醒，让助手能在正确时间把事项重新带回用户面前。

任务：

- [x] 新增 API：
  - `GET /reminders`
  - `POST /reminders`
  - `PATCH /reminders/{id}`
  - `POST /reminders/{id}/snooze`
  - `POST /reminders/tick`
- [x] 新增 `reminders.py` 服务：
  - 到期扫描。
  - snooze。
  - 重复规则计算。
  - 生成/更新 inbox item。
- [x] sidecar 启动后注册轻量后台 tick。
- [x] 支持设置项：
  - reminders_enabled
  - reminder_tick_seconds
  - desktop_notifications_enabled
- [x] Tauri 桌面通知预研/接线：
  - 通知失败时降级到今日页。

验收：

- 到期 reminder 进入今日页。
- snooze 后 `next_fire_at` 正确延后。
- 重复 reminder 完成后生成下一次。
- 重启后提醒状态不丢。

### M4 · 目标系统与周回顾

目标：建立跨模块长期目标层，让学习、项目、任务和文档集合围绕目标组织。

任务：

- [x] 新增 API：
  - `GET /goals`
  - `POST /goals`
  - `GET /goals/{id}`
  - `PATCH /goals/{id}`
  - `POST /goals/{id}/links`
  - `POST /goals/{id}/checkins`
  - `POST /goals/{id}/briefing`
- [x] 新增 `goals.py` 服务：
  - 目标 CRUD。
  - 关联对象读取。
  - check-in。
  - 进展摘要。
- [x] 新增前端：
  - `GoalsWorkspace.vue`
  - 目标详情页。
  - 关联对象列表。
- [x] 从学习主题/项目/任务/集合创建目标链接。
- [x] 支持目标生成任务计划草稿。

验收：

- 一个目标可关联至少两类对象。
- 周回顾引用真实关联对象。
- 归档目标不再默认进入今日待处理。

### M5 · 主动简报与上下文包

目标：让助手能把分散信息组织成可行动的摘要。

任务：

- [x] 新增 `briefings.py`：
  - today briefing。
  - weekly briefing。
  - learning/project/goal briefing。
  - sources_json 构造。
- [x] 新增 API：
  - `POST /today/briefing`
  - `POST /briefings/weekly`
  - `GET /briefings`
  - `POST /briefings/{id}/to-task`
- [x] 新增前端：
  - `BriefingPanel.vue`
  - 来源列表。
  - 转任务按钮。
- [x] 将简报作为可追踪上下文包：
  - 用户可在简报面板查看完整 Markdown 内容。
  - 用户可“一键生成任务草稿”。
- [x] 简报不使用远程 Provider，除非用户已启用并确认隐私预览。

验收：

- 今日简报至少包含重点、风险、下一步、来源。
- 没有来源的建议必须标注“模型推断”。
- 简报转任务后，任务 plan_json 保留 briefing id。

### M6 · 隐私审计、数据体检与备份提醒

目标：让主动能力保持可控、可审计、可恢复。

任务：

- [x] 新增 `privacy.py`：
  - context preview。
  - remote provider audit。
  - sensitive memory filter。
- [x] 在 ChatService / PrivacyService / BriefingService 相关路径记录或生成审计。
- [x] 新增 API：
  - `GET /privacy/audits`
  - `POST /privacy/preview`
  - `GET /maintenance/health-report`
- [x] 今日页展示：
  - 最近备份。
  - 失败导入。
  - draft 记忆。
  - 孤立证据。
  - Chroma/MySQL 风险提示。
- [x] 定期备份提醒：
  - 不自动写备份，除非用户显式开启。
  - 默认只提示。

验收：

- 远程 Provider 调用有审计记录。
- `sensitive=true` 记忆不会进入远程上下文。
- 数据体检能在空数据、健康数据、失败导入场景下返回明确结果。

### M7 · 收束验证与文档

目标：把第六阶段收束到可交付状态。

任务：

- [x] 更新 `docs/usage-guide.md` 第六阶段说明。
- [x] 更新 README 阶段状态。
- [x] 补充 API 表。
- [x] 补充数据模型说明。
- [x] 跑完整验证：
  - `pytest -q`
  - `npm run build`
  - `cargo check`
  - `alembic current`
- [x] 打包 smoke：
  - 今日页可打开。
  - reminder tick 不阻塞启动。
  - Provider audit 不泄露 API key。

验收：

- 第六阶段验收清单全部勾选。
- 文档与实际代码一致。
- 无新增未说明的隐私风险。

---

## 4. 推荐开发顺序

1. M0：先把规划写清楚，避免第六阶段变成泛泛的“更多 AI 能力”。
2. M1：先上数据底座，所有后续功能依赖 inbox/reminder/goal/briefing/audit。
3. M2：做今日和收件箱，这是第六阶段用户价值最高的第一屏。
4. M3：接提醒，把“待处理”变成“会按时间回来”。
5. M4：做目标，让学习、任务、项目、文档有共同方向。
6. M5：做主动简报，把已有数据变成行动建议。
7. M6：补隐私审计和数据体检，防止主动能力失控。
8. M7：验证、打包、文档收束。

---

## 5. 测试计划

### M1

- `pytest tests/test_phase6_today.py`
- Alembic upgrade/current。
- 空数据库聚合返回空列表而不是报错。

### M2

- inbox CRUD。
- 今日聚合多来源。
- inbox 转 task/reminder。
- 前端 build。

### M3

- reminder 到期扫描。
- snooze。
- recurrence。
- app restart persistence。

### M4

- goal CRUD。
- goal link。
- check-in。
- goal briefing sources。

### M5

- today briefing。
- weekly briefing。
- briefing to task。
- sources_json 完整性。

### M6

- remote provider audit。
- privacy preview。
- sensitive memory exclusion。
- maintenance health report。

### 阶段总验收

- `pytest -q`
- `npm run build`
- `cargo check`
- `alembic current`
- `/health`
- 打包模式 smoke

2026-07-08 验证结果：
- `uv run pytest -q`：146 passed。
- `npm run build`：vue-tsc + Vite production build passed。
- `cargo check`：Tauri desktop crate passed。
- `uv run alembic current`：`0009 (head)`。
- `git diff --check`：无空白错误，仅 Windows 换行提示。

---

## 6. 数据迁移草案

新增迁移文件：

```text
alembic/versions/0009_phase6_proactive_hub.py
```

包含表：

- `inbox_items`
- `reminders`
- `personal_goals`
- `goal_links`
- `goal_checkins`
- `briefings`
- `provider_call_audits`

注意：

- 所有跨模块关联使用 `target_type/target_id`，避免强外键导致模块间删除困难。
- 不自动级联删除用户数据。
- `meta_json` / `sources_json` 只保存摘要和 id，不保存大段原文。
- remote provider audit 不保存完整 prompt，只保存类别、估算大小和状态。

---

## 7. 风险与控制

| 风险 | 控制方式 |
|---|---|
| 今日页变成噪音中心 | 默认只显示 open/overdue/high priority；支持忽略和归档 |
| 提醒打扰用户 | 通知默认关闭或轻提示；今日页始终可见；支持 snooze |
| 简报编造事实 | 每条建议绑定来源；无来源标注模型推断 |
| 目标系统过重 | 只做个人目标和 check-in，不做团队项目管理 |
| 远程 Provider 泄露敏感上下文 | 请求级 preview + sensitive memory 硬过滤 + audit |
| 后台 tick 影响 sidecar 性能 | 低频轮询；可关闭；测试环境手动触发 |
| 数据清理误删 | 只给建议；删除必须显式确认 |
| OCR 体积拖累安装包 | OCR 只预研，不作为硬验收 |

---

## 8. 文档交付

第六阶段完成时至少更新：

- `README.md`
  - 第六阶段状态。
  - 今日中枢入口说明。
- `docs/usage-guide.md`
  - 今日页、收件箱、提醒、目标、简报、隐私审计使用说明。
- `docs/requirements.md`
  - 阶段路线表补充第六阶段。
- `docs/phase6-requirements.md`
  - 勾选验收清单。
- `docs/phase6-plan.md`
  - 勾选里程碑任务。

---

## 9. 阶段结论

第六阶段把私人助手从“能力齐全”推向“每天好用”。前五阶段已经解决了能聊、能查、能读资料、能做任务、能记忆、能打包的问题；第六阶段要解决的是：它如何主动把这些能力组织到用户的一天里。

完成后，用户不需要记住每个模块在哪、每个任务是否卡住、每张卡片何时复习。助手会把这些东西带到今日中枢里，但仍由用户决定是否执行、是否发送、是否沉淀。
