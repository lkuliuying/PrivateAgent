# ADR-007 · 副作用完成证据与 Completion Contract（AD-T05）

> 状态：Accepted（2026-08-25 专项评审通过；本 ADR 随 CT-1 落地即生效）
> 日期：2026-08-25
> 关联：专项计划 §5 AD-T05/§7.4–7.7/§18.2；上位计划 S2/S3；ADR-001（Turn 终态）；ADR-003（持久化）
> 背景：`hello.py` 假成功复现——模型返回"已创建"而运行记录 0 次工具、磁盘无文件

## 1. 决定

1. **`completed` 是 Runtime 状态，不是模型输出字段。** 只有 CompletionContract
   在 persisted Evidence 上求值满足后，Turn/run 才能进入 `completed`；
   模型文字、工具文本输出、只读预览（propose）都不能替代。
2. **最低规则（P0 冻结）：** 明确的文件变更任务至少需要一个 `succeeded` 且
   回读验证（`verified=true`）的 `filesystem.write` effect。失败命令、
   proposal-only、模型声明均不满足完成条件。
3. **CompletionContract 由可信代码在 Turn/run 开始时生成并冻结**，模型不可
   见不可改；随 run 持久化条件确定性重建（create 与 resume 得到同一 contract，
   满足 §13.3"随 Turn 恢复，不按新设置重算"）。
4. **ExecutionIntent 规则层优先。** 用户明确"仅解释/仅预览/不执行"时清除对应
   required effects；可选模型分类只能补充 tag，不能降低规则层结论；
   误判只会要求更多证据或给出预检说明，绝不授予额外能力。

## 2. 完成判定单一事实源

v0.9 H1-B 的临时加固（`min_tool_executions` /
`require_successful_file_write` 分支）自 CT-1 起**收口到 v2 求值引擎**
（`agent_v2/domain/completion.py` 的 `evaluate_completion`），v0.9 分支仅作
兼容层保留、不再扩展；同一条件族不得存在两套并行判断。公开错误码冻结：

| 错误码 | 语义 |
|---|---|
| `required_effect_missing` | 零执行证据却宣称完成（F-003） |
| `completion_not_met` | 有执行但缺必需成功 effect（如只有 proposal，F-004） |
| `side_effect_unverified` | 写入已执行但回读证据不一致/缺失（F-007） |
| `completion_evidence_unavailable` | durable facts 加载失败，失败关闭 |

## 3. Effect/Evidence 契约

Effect 与 Evidence 分离（§7.6）：effect 是工具执行的规范化副作用事实，
evidence 是可信 verifier 对事实的确认。证据链必须可关联：
`trace_id → thread_id → turn_id → item_id → tool_call_id → execution_id`；
payload 只存相对路径、hash、大小、状态与 artifact 引用，不复制用户代码。

## 4. 预检门禁（preflight）

明确 file.mutate 意图在本轮没有任何可真正落盘的工具入口时（Patch flag 关闭 /
readonly 权限 / 执行器离线 / 模型不支持工具协议），run 创建即返回
`tool_capability_unavailable` 并说明公开原因，**不调用模型、不产生任何磁盘
变更**（§14.3 话术模板）。

## 5. 测试锚点

回归场景 F-001～F-008 固化于 `tests/test_v100_ct1_fake_success_gate.py`；
门禁指标：明确副作用任务假完成率 0；文件写入完成后磁盘 evidence 覆盖率 100%。
