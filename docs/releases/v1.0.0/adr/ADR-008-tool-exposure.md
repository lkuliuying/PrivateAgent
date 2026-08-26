# ADR-008 · 工具暴露与授权分离（AD-T06）

> 状态：Accepted（2026-08-25 专项评审通过；随 CT-2 ToolSpec v2/Catalog 落地生效）
> 日期：2026-08-25
> 关联：专项计划 §5 AD-T06/§7.1–7.3/§9；上位计划 §10.1–10.2

## 1. 决定

1. **Tool Exposure 只决定是否把 Schema 发给模型**，不能扩大 capability、
   approval 或 sandbox 权限。三原则冻结：
   - Hidden 不代表未注册；
   - Deferred 不代表自动批准；
   - Direct 不代表无需审批。
2. **ToolSpec 注册成功 ≠ 可暴露。** 必须依次通过 maturity、model requirements、
   workspace/environment、capability policy、health、intent relevance、
   context/schema budget 八层过滤（§9.2），每层产生稳定可测试的隐藏原因。
3. **每 Turn 生成不可变 ToolPlan**：direct/deferred/hidden 工具集、required
   effects 与 catalog/visible/model/policy 四个规范化 hash；Turn 运行中设置
   变化不修改既有 Plan，只能通过显式 `tool_plan_invalidated` 事件处理，
   禁止静默换工具。
4. **诊断可解释（ToolSnapshot）：** 提供脱敏诊断视图回答"为什么模型没有调用
   某个工具"——每个工具的 namespace/版本/exposure 状态/隐藏原因/risk/
   approval/executor kind/健康，以及四组 hash；不含 secret、完整敏感参数或
   用户文件内容。Exposure 决策不消费审批 token。

## 2. 命名与冲突

同一 `namespace + canonical_name + version` 在 Catalog 内唯一；Provider 可见
别名规范化（casefold）后再次检测冲突，冲突在模型调用前拒绝
（`tool_name_collision`）。公共 ToolSpec 不绑定 Provider 表达格式；
Qwen/Ollama 默认严格 JSON Function Tool，未知模型能力失败关闭（AD-T04）。

## 3. 并发红线（AD-T07 引用）

只有同时满足 `parallel_safe && side_effect_class == none && idempotent &&
approval_mode == auto` 且无共享会话的工具才允许并发；副作用工具并发数恒为 1。

## 4. 后果与验证

- CT-2 退出条件：每个 Turn 都能重建"模型究竟看到了什么工具以及原因"；
- 隐藏原因枚举（maturity/model/policy/feature/health/collision/context budget）
  由单元测试固化，禁止自由文本原因进入公开协议。
