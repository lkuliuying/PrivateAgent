# 上下文管理改进实施记录（M0–M5）

日期：2026-10-20（Asia/Shanghai）；2026-10-21 补充 M5 与独立验收返工（F1–F7）。
工作区：`F:\Program\Agent`，分支 `dev/1.0.0`，实施前 HEAD `87a8331`。
依据：[上下文管理改进计划书](../analysis/2026-10-20-context-management-improvement-plan.md)。

本记录只陈述本工作区源码、隔离测试与合成模型回放的结果。**未调用真实付费模型，未安装或打包客户端，未提交、建分支、PR、推送、发布或部署**；因此不宣称真实模型理解能力、费用或成功率提升。

## 1. 本轮范围

首轮 M0–M5 全部在本地实现并验证。计划版本边界：2026-10-20 当日按 **M0–M4** 实施；同日计划修订为 **M0–M5**，2026-10-21 按独立验收报告第 5 节补齐 M5 并修复 F1–F7（见第 7 节）。计划第 10 节的后续候选（用户消息裁剪、原生 compaction、精确计数接口、子 Agent、向量数据库、额外付费模型调用）均未实施。

实施前一次性说明的必要接口调整（用户已确认 M0–M4 范围，未重复询问；M5 按计划第 2 节“复用现有条目列表、来源、修订、复核、编辑和遗忘接口，不新增数据库字段或跨条目合并接口”实施）：

1. 本机上下文预算响应增加可选 `breakdown` 分项字段，前端兼容旧记录。
2. 压缩检查点 JSON 增加可选 `compaction_metrics` 与 `summary.handoff`（含 `version`），旧检查点保持可读。
3. 新增只读、按需加载的 `search_context_history` 工具；其余工具必填入参、权限与审批规则不变。

未新增依赖、未重建锁文件、未迁移数据库、未新增数据表。

## 2. 阶段改动

### M0 基线与长任务回归

- `tests/unit/test_context_baseline.py`：26k 窗口、32 次读取、一次失败后修正、真实写入 `done.txt`，以及同会话追加目标写入 `report.txt`。只记录元数据（请求估算、压缩前后、来源覆盖、压缩次数、工具失败数、耗时）到隔离目录 `baseline.json`；断言不读取真实数据库或凭据。
- `test_baseline_is_repeatable_and_stable`：同一夹具重复两次，状态、请求数、条目序号与压缩次数一致。
- `scripts/run_coding_validation.py` 新增 `context-baseline` 套件，并纳入 `context` 套件（因此也进入 `tool-evolution`）。未提高窗口、未放宽既有 26k 断言。
- `apps/desktop/e2e/coding-workbench.spec.ts` 增加上下文抽屉浏览器用例（宽/窄视口、折叠与展开、压缩前后与六类交接），复用该文件既有 API 替身；`contextPanel` 覆盖项缺省时不改变其他用例的响应。

### M1 分项计量与展示

- `private_agent_core/context.py`：`request_breakdown()` 按组装位置分摊同一请求的 UTF-8 字节，输出分类、字节与估算；图片按每张 8192 tokens 预留、不把 Base64 当文本；`provider_state` 单独计量；结构开销归入“协议与结构”；取整差额记入最大项，保证分项之和等于总量估算。纯函数，不改变请求与预算。
- `context_manager.prepare`：在安全边界记录 `run["context_budget"]["breakdown"]`；公开事件 `context.prepared` 不带分项明细，避免每条事件重复持久化。
- `context_history.compact` 与 `context_manager.measure_compaction`：检查点记录 `compaction_metrics`（`measured`、压缩前后估算、归档条目数、保留条目数与字节）。手动空闲压缩没有请求边界，只记录结构计量并标记 `measured=false`。
- `app.py` 的 `/sessions/{id}/context` 返回 `checkpoint.compaction_metrics`；`/context-budget` 通过现有透传返回 `breakdown`。
- 前端：`api.ts` 增加 `ContextBreakdown` 类型（可选字段），`LocalContextPanel.vue` 增加“上下文分项明细”表格与“压缩前后估算”；旧记录显示“暂无分项明细”，未知数值显示“未知”。

### M2 证据选择与六类交接

- 新增 `src/private_agent_local/context_handoff.py`：
  - `select_evidence`：稳定优先级（未解决失败 1 → 当前步骤 2 → 本轮修改 3 → 既有摘要 4 → 普通读取 5），同优先级按原始序号；重复读取同一目标只保留最近一次**成功**结果，失败结果与写入记录不合并。
  - `build_handoff`：六类确定性投影（目标与验收条件、生效限制、当前计划与下一步、关键发现与决定、修改与验证、未解决问题），区分 `observation` / `user_requirement` / `model_report`；修改条目带工作区版本，版本不一致标记 `stale` 并要求复核；来源不足的类别写 `unknown`。
- `context_history.compact`：先解析工具事实（含执行记录中的工作区版本），再选择证据；请求内事实索引改为“失败与修改优先 + 最近 4 项”并只带公开定位字段，完整事实与交接留在检查点；新增 `evidence_selection` 与 `summary.handoff`。
- `context_summary.summary_request`：按优先级选择来源（超出预算先丢最低优先级，最高优先级的早期证据保留到最后），并加入有界的 `required_state`（目标版本、验收条件、限制、下一步、未解决问题）；模型摘要仍受 24 个来源、1000 字符摘录、8 项与 1024 tokens 限制，引用必须属于提供的来源。
- 前端：`LocalContextPanel.vue` 增加“压缩交接（程序投影）”折叠区，展示六类状态、下一步与“需复核”；旧检查点显示“旧检查点未保存该明细（待核对）”。

### M3 当前会话归档搜索

- `ContextHistory.search`：只读、仅当前会话；中文双字 + 英文标识符 + 路径匹配；确定性排序（匹配数降序、原始序号降序）；`role` 与 `tool_name` 过滤；单条摘录 400 字符、最多 10 条、整体不超过 8 KiB；命中上限返回 `truncated` 和缩小查询提示；未命中返回空结果与说明，不生成答案。
- 安全边界：只搜索公开投影，`provider_state` 不参与匹配、排序、摘录或序列化；命中内容经现有敏感词与已加载凭据过滤；只有调用记录、没有公开正文的消息不进入结果。执行层在存在 `access_scopes` 时拒绝（与 `read_context_content` 同一处检查）。
- 工具契约：`SearchHistoryArgs`（`query` 1–200、`role`、`tool_name`、`limit` 1–10）与 `search_context_history` ToolSpec（只读、`context.read`、`idempotent`、`execution_protocol=True`）；加入 `DEFERRED_TOOLS`、`tool_search` 关键词与 `task_constraints` 规划模式只读集合、`progress.READ_TOOLS`。
- 旧协议保持原样：该工具标记 `execution_protocol=True`，在没有按需加载的执行协议下不进入请求定义，因此既不改变旧协议的工具集合，也不影响既有 26k 窗口回归。

### M4 面向当前步骤的记忆召回

- `memories.recall_query`：有界组合当前目标（首段 700 + 末尾 200）、当前进行中步骤（或首个待办）、明确路径与符号、已生效追加要求；总长度不超过 1800 字符，不调用模型。
- `memories.search`：接收信号并给出 `matched_signals`；活跃条目先占候选名额，非活跃条目只在名额有余时出现；排序仍为确定性（活跃、分数、人工、更新时间）。
- `recall_with_details`：详情增加 `matched_signals`，并原样保留条目版本；最多 8 条、约 6000 字节与“预算紧张先移出记忆”的既有行为不变。
- `context_manager`：每次组装按本轮运行状态重建查询，记录 `memory_context.query_signals`（只记信号名，不复制原文）。
- 前端：`SessionMemoryPanel.vue` 在命中说明后展示“匹配目标/当前步骤/路径/追加要求”。

## 3. 实际验证（本工作区，隔离运行器）

| 命令 | 结果 |
| --- | --- |
| `--suite context-baseline` | 2 passed（基线 + 可重复性） |
| `--suite context` | 54 passed |
| `--suite context-alignment` | 24 passed |
| `--suite tool-selection` | 47 passed |
| `--suite mcp-memory-boundaries` | 29 passed |
| `--suite memory` | 145 passed |
| `--suite orchestration` | 46 passed |
| `--suite reasoning` | 46 passed |
| `--suite tools` | 67 passed |
| `--suite execution-autonomy` | 34 passed（单次组合运行曾因并行资源争用失败，单独复跑通过） |
| `--suite streaming`、`--suite local` | 30 passed、84 passed |
| `--suite tool-evolution` | 908 passed、1 skipped（跳过为本机未授予真实符号链接创建权限） |
| 在 `apps/desktop` 执行 `node node_modules/vitest/vitest.mjs run LocalContextPanel.spec.ts ContextDrawer.spec.ts contextRing.spec.ts SessionMemoryPanel.spec.ts` | 27 passed |
| 在 `apps/desktop` 执行 `node node_modules/@playwright/test/cli.js test e2e/coding-workbench.spec.ts -g "上下文抽屉" --retries=0` | 1 passed；1100×760 与 900×720 两种视口，展开分项明细与压缩交接后明细可读，容器无横向溢出 |
| 在 `apps/desktop` 执行 `npm run build` | `vue-tsc --noEmit` 与 Vite 生产构建通过；保留既有 antd 分包 >500 kB 警告 |

全部命令使用 `.venv\Scripts\python.exe -B scripts/run_coding_validation.py`，每次创建独立 `.run/coding-agent-validation/<suite>-<随机>` 目录，使用临时 SQLite、合成资料与进程内模拟模型；未读取真实数据库、凭据或生产日志，未发起付费模型调用。

## 4. 对照指标（同一夹具的合成回放）

同一 `test_long_task_baseline_two_compactions_and_real_write` 夹具（26k 窗口、32 次读取、1 次失败、真实写入、同会话追加目标），仅比较元数据：

| 指标 | M0 基线（M1/M2 前） | 本轮完成后 |
| --- | --- | --- |
| 状态 | completed | completed |
| 会话内模型请求数 | 37 | 37 |
| 会话内压缩次数 | 34 | 34 |
| 压缩失败次数 | 1 | 1 |
| 最终请求估算 tokens | 21,668 | 20,388 |
| 最终请求字节 | 17,334 | 16,310 |
| 检查点覆盖原始条目 | 是（75 个来源） | 是（75 个来源） |
| 早期关键发现被选入证据顺序 | 未记录（仅时间顺序） | 是（`early_evidence_selected`） |
| 早期失败证据可核对 | 仅 `failed_attempts` 引用 | `handoff.findings` 与 `handoff.unresolved` 均带来源 ID |
| 最近一次压缩前后估算 | 未记录 | 22,459 → 18,200 tokens（归档 75 项 / 131,750 字节，保留 5 条消息、2 条用户原文） |
| 交接类别 | 无 | 目标/发现/修改验证/未解决有来源；计划与限制在该夹具中为 `unknown` |

说明：请求估算下降来自请求内事实索引改为“优先 + 最近 4 项”并精简公开字段；压缩失败次数仍为 1，属于“可压缩前缀过小（失败读取与目录列表等小条目占满前缀）时压缩无收益”的既有边界。需要区分“压缩尝试失败”和“整个任务失败”：`context_manager` 只在原请求本身已超出硬预算时才把该失败升级为 `context_limit`；原请求仍能容纳时保留旧视图继续执行，本轮基线正是这种情况（任务 completed）。本轮未改变该判定，也没有放宽断言。上表是控制流程与内容保留的合成回放，不能用于宣称真实模型质量、费用或成功率变化。

浏览器组合运行：`node node_modules/@playwright/test/cli.js test e2e/coding-workbench.spec.ts --retries=0` 为 15 passed、1 failed。失败项是既有的“Provider 未配置（409 coding_mode_disabled）：引导前往设置”，本轮独立选择运行仍复现；未进行修改前环境的完整对照，因此只确认当前失败与调用范围，不确认“环境问题”的根因。本次未修改其断言，也未通过跳过或放宽取得通过，记为未解决项。新增的上下文抽屉用例单独运行 1 passed。

一次压缩的失败历史（本会话内实测，未修改代码以掩盖）：当压缩前缀只包含小结果时，事实索引本身的开销使“压缩后估算 ≥ 压缩前”，于是显式报错并保留原历史；M2 因此改为只把有界交接投影放进请求，其余事实留在检查点。

## 5. 兼容、回退与未验证项

- 新字段均可选：旧预算记录无 `breakdown`，旧检查点无 `handoff`/`compaction_metrics`，界面显示“暂无/未知/待核对”，不伪造零值。
- 未新增表，未迁移数据库；`search_context_history` 只读且只在按需加载协议下暴露，移除它不影响旧历史可读性。
- 原始条目、全部用户原文、工具配对、审批、原生 `provider_state` 与预算硬限制均保留；压缩仍保留最近两个完整调用组并在提交前复核代次、配置、规则、权限与历史末序号。
- 未验证：真实供应商与真实账号下的效果对照（同模型/同题目/同预算）、已安装桌面产品中的界面验收、真实成本变化、`search_context_history` 在真实长会话中的召回质量、非中文/非英文语种匹配。
- 回退条件与步骤：直接还原本次源码即可，不需要迁移或清库。回退后读取新版检查点时，`messages`、`summary`、`summary_strategy`、`through_ordinal` 等既有键保持不变，`handoff`、`compaction_metrics`、`breakdown` 只是额外 JSON 键，旧逻辑忽略未知键；旧检查点在新代码下按“暂无/未知”展示。不得删除 `context_items`/`context_checkpoints`、清空历史或用旧 schema 覆盖数据库来降级。

## 6. 相关文档

- [上下文设计](../context-design.md)
- [记忆设计](../memory-design.md)
- [测试与验证指南](../testing-guide.md)

## 7. 独立验收返工（2026-10-21）

依据：`.run/context-acceptance-uomx8qax/acceptance-report.md` 的 F1–F7 与第 5 节返工顺序。本轮只改本地源码、测试与文档，未提交、未发布、未调用真实模型。计划版本同步为 2026-10-20 修订版（M0～M5）；本节补 M5 与 F1–F7 的证据。

### 7.1 F1 证据去重（`context_handoff.select_evidence`、`context_history.compact`）

去重键改为「工具名 + 同一读取范围（rel_path/start_line/line_count/offset/limit/query/cursor 等）+ 结果正文摘要」三者都相同；由 `read_dedupe_key` 计算。写入、失败、范围或版本未知一律没有去重键，因而不会合并；不同区间、同区间不同版本内容与不同执行记录都保留。回归：`test_evidence_dedupe_requires_same_range_and_same_result`、`test_evidence_dedupe_keeps_failures_and_writes`。

### 7.2 F2 摘录窗口（`context_handoff.excerpt_window`、`context_summary.summary_request`、`context_history.compact`）

新增 `excerpt_window`：命中当前步骤/目标词时取命中位置附近窗口并返回 `range` 与 `truncated`；无法定位时仍取首尾；预算含省略标记，单条不超过调用方上限。`summary_request` 接收来自交接（下一步与验收条件）的 `keywords`，历史分析摘录也改用同一函数；工具 JSON 在公开正文上定位，不把 `provider_state` 带入。回归：`test_excerpt_window_bounds_and_fallbacks`、`test_summary_request_includes_middle_of_long_result`、`test_historical_analysis_window_reaches_middle_evidence`。

### 7.3 F5 已解决失败（`context_handoff._split_failures`、`reflection.target_hash`）

失败事实按纠错状态分为 open / resolved / unknown：open 进入未解决并附来源 ID；resolved 记为“此前失败已由同目标成功调用解决”进入发现区；没有纠错记录可核对时保留失败并标 `state="unknown"`，未解决区段状态为 `recheck_required`，不伪造已解决。`reflection.target_hash` 公开既有目标摘要算法，不新建第二套判定。回归：`test_resolved_failure_is_history_not_unresolved`。

### 7.4 F3 目标契约（`context_handoff`、`LocalContextPanel.vue`、`context.ts`、前端夹具）

后端目标区段只暴露 `requirements`（其余五段使用 `items`）；前端渲染前把 `goal.requirements` 统一映射为 `items`，类型增加可选 `requirements`。`LocalContextPanel.spec.ts` 与 `coding-workbench.spec.ts` 改用真实结构并新增“目标正文可见”断言，不再使用虚构的 `goal.items`。后端契约守卫：`test_handoff_goal_section_exposes_requirements_only`。

### 7.5 F4 原生公开正文可搜（`ContextHistory.search`）

搜索只排除内部状态字段本身：公开正文始终参与匹配与摘录；`provider_state` 不在 `content` 中，也不参与匹配、排序、摘录或序列化。回归：`test_native_public_text_is_searchable_but_internal_state_is_not`（同时验证公开正文命中与不透明状态零命中）。

### 7.6 F6 召回查询预算（`memories.recall_query`、`compose_query`）

组合查询恢复 500 字符上限，并给目标（210）、步骤（110）、路径（90）、追加要求（80）分别留额度：长目标保留首尾、最新追加要求保留末尾、路径按整条累加不截半；`compose_query` 是唯一查询来源，匹配与 `matched_signals` 使用同一份最终信号；`search` 对超过 500 字符的查询报错。回归：`test_recall_query_includes_long_goal_tail_step_paths_and_steer`、`test_recall_query_keeps_latest_steer_within_total_budget`、`test_steer_only_memory_is_recalled_within_query_budget`。

### 7.7 F7 偏好保底与空查询过滤（`memories.search`、`recall_with_details`）

自动注入先排除非活跃与敏感条目再截取候选上限；人工零匹配保底仅限 `origin=user`、`active`、`kind=preference`，最多 2 条且排在相关命中之后，原因标为 `preference_floor`（不伪装成关键词命中）；人工 project/workflow/reference 需相关才注入；空查询分支同样先过滤后截取；管理页 `search` 与 `search_memories` 仍能看到待复核条目。回归：`test_inactive_candidates_do_not_crowd_out_active_memory`、`test_manual_preference_kept_and_generated_zero_match_excluded`、`test_manual_preference_floor_is_bounded_and_after_relevant_hits`、`test_empty_query_filters_inactive_before_slicing`；同时更新原先依赖“无关人工 project 事实也注入”的两项旧断言（修订计划已明确改为需要相关）。

### 7.8 M5 维护体验（`MemorySettingsPanel.vue`、`api/memories.ts`、`e2e/memory-maintenance.spec.ts`）

- 同主题对照：候选带 `supersedes_id` 且旧条目在当前列表时，并列展示当前条目与新候选的 scope/kind/版本/来源/更新时间，提供采用新值、保留旧值、编辑新候选，沿用既有复核与编辑接口。
- 疑似重复：只在管理页对当前列表计算派生提示，比较同 scope 的 `topic_key`、规范化标题、规范化正文；按重复组展示理由，最多 6 组；不新增后台任务、模型调用、数据库表或必填字段，不提供一键合并。
- 过期维护：每条显示更新时间、来源数量与来源时间；无来源时明确“不显示为已验证”；状态筛选（全部/待复核/已过期/可使用）只影响展示；标记过期、确认使用、编辑、遗忘沿用现有接口。
- 验证：`MemorySettingsPanel.spec.ts` 10 项（含对照、重复分组、跨 scope 不合并、筛选不写入、409 保留草稿）；浏览器 `e2e/memory-maintenance.spec.ts` 覆盖宽/窄窗口与键盘展开，既有 `e2e/memories.spec.ts` 仍通过。

### 7.9 本轮复验

| 命令 | 结果 |
| --- | --- |
| `--suite context-alignment` | 31 passed |
| `--suite memory` | 149 passed |
| `--suite tool-selection` / `mcp-memory-boundaries` | 49 / 31 passed |
| `--suite context` | 54 passed |
| `apps/desktop`：Vitest（LocalContextPanel、ContextDrawer、contextRing、SessionMemoryPanel、MemorySettingsPanel、MemoryEvidence） | 40 passed |
| `apps/desktop`：Playwright（上下文抽屉、memory-maintenance、memories） | 3 passed |
| `apps/desktop`：`npm run build` | 类型检查与 Vite 构建通过；保留既有 antd 分包警告 |

## 8. 复验返工（2026-10-21 第二轮：R1、R2）

依据：`.run/context-reacceptance-h7oepqkr/reacceptance-report.md`。本轮只修 R1/R2 与相邻回归；F3–F7 与 M5 的既有结论不变。

### 8.1 R1 摘录预算越界（`context_handoff.excerpt_window`、`context_history.compact`）

- 对任意 `limit >= 0` 保证 `len(excerpt) <= limit`：未命中分支的剩余预算为负时不再用负索引切片，改为上限内的开头片段；命中分支在 `limit <= 标记总长 + 4` 时退化为无标记窗口，避免负内容预算与倒置 range。
- `range` 始终非负、不倒置、`end <= len(text)`；命中词在内容预算足够时优先完整落入窗口（`lead` 扣除命中词长度）。
- `compact()` 的 1200 字符批次预算在剩余不足 `MIN_EXCERPT_CHARS`（24）时省略该条，不追加无信息量的短片段；单条仍不超过调用方给出的上限。
- 回归：`test_excerpt_window_never_exceeds_limit`（limit 0–29、32/48/64/128/399/400/401/999/1000/1001 × 命中/未命中）、`test_compact_analysis_excerpts_stay_within_budget_with_tiny_remainder`（399/400/400/5000 与剩余 1 字符，合计 1199 ≤ 1200）。压缩后“不减少/仍超限”的保护未放宽。

### 8.2 R2 跨组复用调用 ID（`context_handoff.select_evidence`）

- 证据身份改为上下文条目唯一 ID：删除了按 `(role, tool_call_id)` 的全局 `seen` 去重，供应商跨组复用 ID 不再丢弃后出现的完整调用组。
- 调用与结果的目标关系按完整 assistant/tool 组绑定（组内 `pending` 映射），不再用裸调用 ID 做全局覆盖；组内找不到对应调用时只保留消息自带名称，不跨组猜测目标。
- 调用条目自身也按自己的参数参与当前步骤匹配，保证“调用与对应结果一起选取”。
- 去重仍只对已证明同工具、同范围、同结果的读取生效；不同范围/结果、失败与写入继续保留。
- 回归：`test_reused_call_id_across_groups_keeps_both_results`（同 ID 两段不同范围读取 + 32 个同 ID 噪声；两份都进入 `evidence_selection` 且都出现在实际 `summary_request` 来源中）、`test_reused_call_id_with_different_targets_uses_own_arguments`（同 ID 不同目标时优先级按各自参数计算）。

### 8.3 本轮复验

| 命令 | 结果 |
| --- | --- |
| `--suite context-alignment` | 114 passed（含 R1 参数化边界与 R2 回归） |
| `--suite context` / `context-baseline` | 54 / 2 passed |
| `--suite memory` | 149 passed |
| `--suite tool-selection` / `mcp-memory-boundaries` | 49 / 31 passed |
| `--suite tool-evolution` | 910 passed、1 skipped（本机未授予真实符号链接创建权限） |
| `apps/desktop`：`node node_modules/@playwright/test/cli.js test e2e/coding-workbench.spec.ts --retries=0` | 16 passed（含 Provider 未配置引导用例按真实“配置模型”契约修正后通过） |
| 前端 | 本轮未改前端组件；上一轮 40 Vitest、3 浏览器用例、`npm run build` 通过的结果仍适用 |

仍未验证：真实供应商/真实账号、已安装客户端、真实成本、真实长会话召回质量、非中英文匹配。

### 8.4 Provider 引导用例的契约核对（单独事项）

复验报告确认失败原因是定位文案与页面不一致：未配置状态实际渲染“配置模型”（`data-testid="home-provider-create"`），旧用例等待已不存在的“前往设置”。本轮按页面实际契约把定位改为该 testId，保留原有“进入模型设置区”断言，未放宽或跳过：`e2e/coding-workbench.spec.ts` 整文件 16 passed。该用例使用模拟本机 IPC，不代表真实安装包验收；修改前的历史归属仍未做完整对照。

仍未验证：真实供应商/真实账号效果、已安装客户端、真实成本、真实长会话质量、非中英文匹配。M5 的对照与重复提示只是派生展示，不代表冲突已解决或内容已核实。
