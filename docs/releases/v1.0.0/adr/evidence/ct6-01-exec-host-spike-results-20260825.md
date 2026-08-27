# CT6-01 · Rust Exec Host JSONL Spike 实证（2026-08-25）

> 关联：[ADR-006](../ADR-006-exec-host-boundary.md)（AD-T02）；专项计划 §11/§15 CT6-01
> 结论：**最小 JSONL 子集 + 真实 argv 进程执行已端到端跑通**；沙箱强制边界仍开放

## 1. 交付物

| 组件 | 路径 | 说明 |
|---|---|---|
| Rust crate | `apps/exec-host/` | 仅依赖 `serde_json`；release 构建 4s |
| 协议契约 | `agent_v2/execution/contracts.py` | P0 方法/事件/错误信封/规范化 start 参数 |
| 客户端 | `agent_v2/execution/exec_host_client.py` | 握手版本校验、单一读取泵、有界事件队列、失败关闭 |
| 端到端测试 | `tests/test_v100_ct6_rust_host_e2e.py` | 6 用例；binary 缺失时整组跳过 |

## 2. 已验证行为（全部自动化复现）

1. **握手**：`initialize` → health（`protocol_version="1.0"`、`modes=["argv"]`）；
   版本不符 → `ExecutorUnavailable` 失败关闭；
2. **事件流**：`execution/start` → `started` / `stdout delta` / `stderr delta`
   / `exited(exit_code=0)` 按序到达，stdout/stderr 分流正确；
3. **取消**：`execution/cancel` → kill 子进程 → `cancelled` + `exited`；
4. **超时**：`timeout_ms=800` 的 sleep 子进程被终止，
   `exited(cancelled_by_timeout=true)`——无孤儿悬挂；
5. **stdin/write 明确拒绝**（`unsupported_stdin`），不静默丢弃；
6. **退出码透传**：子进程 `SystemExit(3)` → `exited.exit_code=3`。

门禁结果：`cargo build --release` 成功；pytest e2e 6 passed（1.59s）。

## 3. 如实声明的边界（未证明项）

- **沙箱强制 = 未落地**：health 中 `sandbox_available=false` 为真实上报。
  restricted token/MIC/Job Object、workspace 外写入拦截与**网络强制边界**
  （ADR-004 S4 门禁）尚未实现；在闭环前不得将通用 exec 标记 stable，
  不得接入默认产品路径（专项计划 §11.5）。
- stdin 管道、PTY 模式、进程树（Job Object）级联终止：后续工作包；
- 输出上限当前为 delta 分帧限制，磁盘 artifact ref 与总量保留策略属 S5。

## 4. 复现步骤

```powershell
cargo build --release --manifest-path apps/exec-host/Cargo.toml
uv run pytest tests/test_v100_ct6_rust_host_e2e.py -q
```

## 5. CT-6 沙箱强制增量（同日第二轮）

| 能力 | 实现 | 自动化证明 |
|---|---|---|
| Job Object 级联终止 | 每 execution 一个 KILL_ON_JOB_CLOSE Job；挂起态入 Job 再恢复；cancel/超时/Drop → TerminateJobObject 级联整棵树 | `test_job_object_cascades_grandchild_termination`：孙进程心跳 1.6s 内停止 |
| Low MIC 写拦截 | 复制 primary token + `SetTokenIntegrityLevel(Low)` + `CreateProcessAsUserW`（CREATE_SUSPENDED→入Job→Resume） | `test_low_integrity_denies_write_outside_workspace`：用户主目录写入被拒；`test_inherit_control_group_*` 对照组成功 |
| 环境 allowlist | env_clear 后仅回填显式 `env_diff`（std 与受限两路径一致） | `test_low_integrity_child_runs_with_explicit_env_only`：未下发的 host 变量不泄漏 |
| stdin EOF | 管道写端即刻关闭 | 全部用例隐式覆盖 |

新增协议字段：`execution/start.integrity_level = inherit|low`（默认 inherit，
向后兼容）。测试套件：`tests/test_v100_ct6_sandbox_enforcement.py` 4 passed。

**仍未闭环**：网络强制边界——等价方案与实验计划见
`s4-network-enforcement-plan.md`（选定 AppContainer 主路径，N1–N4）；
`health.sandbox_available` 维持如实上报 false。

## 6. CT6-N 网络强制增量（同日第三轮）

- 协议新增 `appcontainer: bool`；host 实现 AppContainer 零能力 profile
  生命周期（创建/删除/SID 释放）与属性表启动路径；
- **门禁语义**：network_policy=none + appcontainer 时，要么 AC 内核强制
  执行、要么结构化失败关闭（sandbox_policy_unavailable），零降级；
  network_policy!=none 直接拒绝（能力授予未开放）；
- 测试：`tests/test_v100_ct6_appcontainer.py`（探针永不 NET_OK / 对照组
  连接成立 / 非 none 拒绝 / 执行面条件跳过）；
- N1b 待办与本机 203/0xC0000142 根因记录见
  `s4-network-enforcement-plan.md` §3.5。
