# R4 领域级验证器（result verification）

> **当前状态（2026-08-06）**：6 类验证器全部实现并通过测试（`tests/test_result_verification.py`，
> 18 个用例），文件 Diff 验证器已接入真实只读工作流（`propose_patch` 预览复核）。实现与约束见
> `docs/remaining-work-plan-20260806.md` §7。

## 1. 与输出验证器的区别

- **输出验证器**（`agents/verification.py`）：验证**模型最终输出**（非空/JSON Schema/引用），
  固定注入 runtime 的 start/resume 路径，失败触发受控修正（0–2 次）。
- **结果验证器**（`agents/result_verification.py`，本工作包）：验证**工具执行结果**——
  工具完成后、结果返回模型前，由可信代码对磁盘/命令/API/数据库事实复核；
  失败时执行记 `failed`（durable run 事实）并返回有界反馈，模型按工具失败处理。

## 2. 验证器清单

| 验证器 | 覆盖工具（可配置） | 复核的事实 |
|---|---|---|
| `FileDiffResultVerifier` | `propose_patch` / `apply_patch_to_workspace` | 磁盘回读 SHA vs 结果声明的 old/new SHA；入参 `new_content` → `new_sha256` 交叉校验；路径越界拒绝；预览后内容变化拒绝 |
| `CodeCommandResultVerifier` | 代码检查命令工具 | 白名单前缀 + 成功/失败标记 + Shell 结构检查 |
| `ShellResultVerifier` | 命令执行工具 | 退出码、stderr、超时、截断、取消状态 |
| `ApiResultVerifier` | API 调用工具 | 状态码范围、固定响应 Schema（Draft 2020-12）、重试次数上限、幂等键 |
| `DatabaseResultVerifier` | 数据库操作工具 | 事务提交、约束错误、影响行数范围、读回字段 |
| `WorkflowCompletionVerifier` | 多步骤工作流 | 可信调用方定义的完成条件谓词（模型不能自由宣称完成） |
| `CompositeToolResultVerifier` | — | 按注册顺序组合，首个失败即返回 |

## 3. 接入点（`ValidatedToolDispatcher`）

```python
dispatcher = ValidatedToolDispatcher(
    registry,
    policy=...,
    execution_store=...,
    result_verifier=FileDiffResultVerifier(resolve_root),  # R4
)
```

执行链：schema 校验 → **结果验证** → 脱敏/大小上限 → `complete_success` 持久化。
验证失败 → `_terminal_failure(code=验证码, message=有界)` → `agent_tool_executions` 记为 `failed`
（error_code 可审计），模型收到有界错误反馈。

已接入的真实工作流：`routes_agent_runs.py::get_agent_tool_bundle` 在
`PA_AGENT_RUN_READ_ONLY_TOOLS_ENABLED` 时对 `propose_patch` 注入
`FileDiffResultVerifier`（只读复核，无新增 capability）。

## 4. 通用约束落实（§7.2）

- 验证器由可信代码固定（dispatcher 注入），模型不能选择验证器或宣称通过；
- 验证器只读复核：文件回读有界（≤5 MB）、不写盘、不消费审批、不增加 capability
  （`test_result_verification.py::test_result_verification_never_consumes_approval`）；
- 失败反馈有界：`ResultVerification.message ≤ 2000`，stderr 只取前 400 字符；
- durable 事实：失败写 `agent_tool_executions.error_code`；恢复路径不回放失败执行；
- 每个验证器覆盖成功/失败/超时/截断/取消/重试边界/恢复路径（见测试文件）。

## 5. 验收对照（§7.3）

- ✅ 每个验证器有真实调用工作流与端到端测试：文件 Diff 走真实
  `apply_patch_to_workspace`/`propose_patch`（真实写盘+回读）；Shell/代码走真实命令结构；
  API/DB 走结构化结果复核；runtime 端到端验证模型收到有界反馈后完成回答。
- ✅ UI 展示公开验证结果：验证失败作为 failed 工具执行出现在 run 事件/活动时间线
  （`agent_tool_executions.error_code` + 有界 message），不暴露模型隐式推理。
- ✅ 关闭验证器或工作流 flag 不要求数据库 downgrade（纯代码注入，无 schema 变更）。

## 6. 开放工作流门禁（何时必须挂验证器）

- 开放 `apply_patch` 写文件工作流 → 必须先挂 `FileDiffResultVerifier`（已实现）。
- 开放 Shell/代码命令工作流 → 必须先挂 `ShellResultVerifier` + `CodeCommandResultVerifier`。
- 开放 API 调用工作流 → 必须先挂 `ApiResultVerifier`。
- 开放数据库写工作流 → 必须先挂 `DatabaseResultVerifier`。
- 多步骤工作流 → 完成条件由可信调用方用 `WorkflowCompletionVerifier` 定义。
