# CT-6 Exec Host · v1.0.0 发布策略决议（默认禁用）

> 日期：2026-08-26
> 关联：[ADR-004](../ADR-004-windows-sandbox.md)、[ADR-006](../ADR-006-exec-host-boundary.md)、
> [s4-network-enforcement-plan.md](./s4-network-enforcement-plan.md)、
> 专项计划 §11.5/§16/§20、验收关闭顺序 #2
> 状态：**正式决议**（替代"完成网络隔离或默认禁用"的待决状态）

## 1. 决议

v1.0.0 正式版 **保持 Exec Host 默认禁用**：

- `PA_AGENT_V2_EXEC_HOST_ENABLED` 默认 `false`（config.py，§20 已注册）；
- Exec Host 不进入默认产品路径：`ExecHostClient` 在生产代码中**无任何
  拉起调用点**（仅测试与取证脚本引用），命令执行继续走 v0.9 argv 白名单
  工作流；
- 通用命令能力（包管理器/解释器/通用 shell）**不标记 stable**，不作为
  发布面能力声明——与专项计划 §11.5/§16 阻断语义一致（"网络强制边界未
  解决前不得把通用包管理器、解释器或 shell 标记为 stable"）。

## 2. 依据（当前环境实证）

| 项 | 状态 | 证据 |
|---|---|---|
| 网络强制（§19.1 未授权外发=0） | 本机取得 **fail_closed 形态**（AC 子进程创建阶段被拒，出网数结构性为 0）；**强形态 kernel_deny(10013) 进程内实证不可达** | s4-network-enforcement-plan.md §3.8（pair_confirmed=true）、n1c-discriminant-results-*.json |
| 根因 | 本机会话对属性表启动链（AC/ConPTY）存在加载链限制（0xC0000142/203 同源），与 N1b/N1c 同族 | s4-network-enforcement-plan.md §3.6/§3.9 |
| ConPTY 受控 PTY | 附着探针不通过 → `pty_environment_unavailable` 结构化拒绝；健康环境自动放行 | tests/test_v100_ct6_stdin_pty.py |
| sandbox_available | health 如实上报 `false` 直至强形态环境可用 | exec-host health 用例 |

结论：本机**无法形成"默认开启的安全执行能力"发布闭环**；可验收的是
"技术探针与失败关闭机制"（与验收结论口径一致）。

## 3. 失败关闭不变式（随禁用决议一并冻结）

1. `network_policy != none` + appcontainer 一律拒绝（能力授予未开放）；
2. AC/PTY 创建失败 → 结构化错误码（`sandbox_policy_unavailable` /
   `pty_environment_unavailable`），零降级、零静默伪会话；
3. `execution/stdin/write` 逐次校验 execution id + session nonce，
   缺绑定/错配/已关闭一律结构化拒绝；
4. 开启 flag 仅表示允许 Python Core 拉起 exec-host，通用命令能力仍受
   ADR-004 沙箱门禁裁决；同一 execution 不跨执行器自动重试（§24）。

## 4. 解除条件（重新评估入口）

满足以下任一即启动"默认启用"重评估（不自动生效，需新 ADR）：

1. 在无加载链限制的健康会话/参考机上取得 **kernel_deny(10013) 进程内
   判别式证据对**（`scripts/run_n1c.py` 已就绪，断言固化、解除即自动产出）；
2. 完成 §3.2 N4 门禁测试全量（含子孙进程继承、取消后无孤儿、
   沙箱创建失败失败关闭）；
3. `sandbox_available` 转为如实上报 `true`，且 §19.1/§19.2 相关门禁全绿。

## 5. 范围外声明

本决议不改变：CT-6 已交付的协议契约（§11.2 P0 方法全集）、
Rust 边界红线（AD-T02）、Job/MIC/AC 三层原语实现与自动化锚定；
它们作为技术探针验收的一部分保留并随发布证据归档。
