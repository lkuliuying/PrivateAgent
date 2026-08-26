# ADR-006 · Rust Exec Host 边界（AD-T02）

> 状态：Accepted with implementation gate（2026-08-25 CT6-01 JSONL spike 端到端实证，见 [evidence](./evidence/ct6-01-exec-host-spike-results-20260825.md)；沙箱/网络强制边界闭环前不得接入默认产品路径）
> 日期：2026-08-25
> 关联：专项计划 §5 AD-T02/§11；ADR-002（transport）；ADR-004（Windows 沙箱）
> 上游参考：`openai/codex@465eafa` `codex-rs/app-server/`（架构对照，非源码复用）

## 1. 背景

v1.0.0 需要统一 exec 能力（PTY、进程树、流式输出、取消、Windows 沙箱）。
Python 在这些系统级能力上存在线程不可强杀、Job Object 控制繁琐等限制；
但把业务控制面迁入第二运行时会产生双事实源。

## 2. 决定

1. **Python Agent Core 是唯一控制面。** Tool Planner、Policy、Approval、
   Lease、Lifecycle、Verification、Persistence 与 Turn terminalization 全部
   留在 Python `agent_v2`。
2. **Rust Exec Host 只负责受控执行。** 进程只接收经过 Python 策略决议的
   规范化执行请求，负责进程创建、PTY、stdio 分流、有界输出、超时、取消、
   kill tree、Job Object 与 Windows 沙箱落地。
3. **Exec Host 禁止事项（红线）：**
   - 自行发现工具或调用模型；
   - 请求网络授权或扩大 sandbox/network policy；
   - 写 MySQL 或任何 durable fact 存储；
   - 把 Turn/execution 标记为完成——只有 Python 依据 Evidence 终态化。
4. **信任与传输边界：** WebView 不直接访问 Exec Host。链路固定为
   `Vue → Tauri Agent Transport → Python Agent Core → Exec Host`。
   `execution/start` 不携带用户审批 token；环境变量采用 allowlist +
   explicit diff。

## 3. 协议形态

P0 方法/事件沿用专项计划 §11.2（initialize / health/read / execution/start /
stdin/write / output/read / cancel / status/read / shutdown；
started / stdout/delta / stderr/delta / output/truncated / exited /
cancelled / failed）。JSONL over stdio，消息上限与 ADR-002 一致（1 MiB，
超限转 artifact ref）。

命令模式灰度顺序：`argv`（默认）→ 受控 PTY → shell 字符串（仅当注入/
解释器链/网络/workspace 外写入测试全部通过；否则延期，不阻断 Tool Engine）。

## 4. 失败关闭语义

- 沙箱创建失败 → `sandbox_policy_unavailable` 失败关闭，不降级 full access；
- Exec Host 崩溃后新副作用调用失败关闭；已有 execution 按 durable fact 恢复，
  无法确定的非幂等执行标记 `unknown`；
- 取消必须终止完整进程树（Job Object 内无存活子孙），p95 ≤ 2s。

## 5. 后果与验证

- 打包链新增独立 binary：installer smoke + SHA 记录进入发布门禁；
- CT-6 退出证据：未授权 workspace 外写入/网络为 0；取消后残留进程为 0；
- 本 ADR 的"禁止事项"由集成测试固化（Exec Host 收到越权请求必须拒绝并审计）。
