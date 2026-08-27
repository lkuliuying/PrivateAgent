# ADR-002 · Agent 协议传输层：stdio/JSONL vs loopback WebSocket

> 状态：Accepted（2026-08-24 技术评审通过）
> 日期：2026-08-24
> 关联：上位计划 §8.1；执行计划决议 D5；S1-T2/T6
> 实证脚本：`scripts/spikes/s1_transport_stdio_spike.py`
> 实证结果：[evidence/s1-transport-spike-results-20260824.json](./evidence/s1-transport-spike-results-20260824.json)

## 1. 背景与决策问题

上位计划 §8.1 要求 Agent 主通道采用 JSON-RPC 2.0 语义，桌面默认使用 loopback WebSocket 或 Rust bridge，由 S1 spike 以安全性、背压、开发复杂度和打包稳定性决策最终 transport。决议 D5 预倾向 **Tauri Rust bridge 管理的 sidecar stdio/JSONL**（官方 Codex App Server 同样默认 stdio/JSONL，WebSocket 标记为实验性且不支持生产），本 ADR 以实测确认或推翻该预倾向。

注意：v0.9 现状是 sidecar 以 PyInstaller onefile 打包、Tauri `start_sidecar` 分配端口并通过 `PA_API_PORT` 注入（见 `apps/desktop/src-tauri/src/lib.rs`），HTTP 为现有通道；本决策只影响 1.0 Agent 主通道，REST facade 按上位计划 §12.3 保留。

## 2. 候选方案

| 方案 | 机制 | 安全面 | 背压 | 复杂度 | 打包稳定性 |
|---|---|---|---|---|---|
| A. stdio/JSONL（预倾向） | Rust bridge spawn sidecar，stdin/stdout 按行 JSON | 无网络监听面；进程隔离即边界 | 管道缓冲有限 → 必须有界队列 | 低（标准库可实现） | 高（无端口竞争/防火墙） |
| B. loopback WebSocket | sidecar 监听 127.0.0.1 端口 | 需一次性高熵 bearer + Host/Origin + 端口防护 | socket 缓冲 + 应用层队列 | 中（ws 库、重连、心跳） | 中（端口协商、企业防火墙策略） |

## 3. 实证记录（2026-08-24，本机实测，8/8 与记录一致）

最小服务端实现：读线程（字节级行长限制）→ 有界工作队列 → 工作线程 → 写锁输出。

| # | 语义 | 结果 |
|---|---|---|
| T1 | initialize 顺序强制（未初始化调用被拒） | ✅ `code=-32001 not_initialized` |
| T2 | initialize 交换 protocol_version / capabilities / notification_preferences | ✅ |
| T3 | ping 往返与 request id 原样回带 | ✅ |
| T4 | 未知方法 → 五字段错误信封（code/message/retryable/details/trace_id） | ✅ |
| T5 | 超长消息（>1 MiB）被拒且连接不中断 | ✅ |
| T6 | 有界队列背压：384 洪泛 / 队列 64 → 65 正常处理 + 319 显式 `retryable` 过载拒绝，无丢失无死锁 | ✅ |
| T7 | stdin EOF → 服务端干净退出（码 0） | ✅ |
| T8 | 吞吐基线：500 次 ping，p50=0.05ms / p95=0.08ms（本机管道，非生产承诺值） | ✅ |

### 3.1 实测踩坑（已固化为实现规则）

1. **线格式必须显式规定为 UTF-8**：Windows 控制台代码页（GBK）下服务端输出含非 ASCII 文本的 JSON 行会产生非法 UTF-8 字节，客户端 `json.loads` 静默失败、请求看似丢失。必须在协议规范中写明「每行一个 UTF-8 JSON，`\n` 结尾」，且 sidecar 启动环境固定 `PYTHONUTF8=1` / `PYTHONIOENCODING=utf-8`。
2. **客户端必须用持久读线程 + 按 id 匹配**，而非逐请求阻塞读：就绪标记、通知与响应共用一条流，逐请求读会被非匹配消息对头阻塞（实测挂死）。
3. **背压洪泛场景收发必须并行**：响应填满 stdout 管道缓冲后，纯"先发后收"客户端与服务端互相死锁（实测 180s 挂起）。
4. spike 中的非 JSON 就绪行只是测试夹具，不进入生产线格式。生产中 sidecar `stdout` **只能输出 UTF-8 JSONL 协议帧**，就绪信号使用 `initialize` 响应；运维日志、traceback 和诊断文本一律输出到 `stderr`，Rust bridge 分流采集。任何 stdout 非 JSON 字节都视为协议破坏并终止连接，不得静默忽略。

## 4. 决策（推荐，待评审）

**采用方案 A：stdio/JSONL，由 Tauri Rust bridge spawn 并管理 sidecar 生命周期。**

安全模型变化（相对上位计划 §8.1 的通用要求）：

- 无网络监听面 → 免除 Host/Origin 校验；「一次性高熵令牌」退化为进程派生权限控制（只有 Rust bridge 能 spawn/接入管道），另在 `initialize` 握手携带会话参数；若未来开放任何网络回退通道，bearer/Origin 要求恢复；
- 消息大小限制（1 MiB）与有界队列 + 显式 `retryable` 过载拒绝保留；
- `server/overloaded` 通知以错误信封形式在请求级返回（spike 已验证），广播型过载通知在 S2 schema 中定义。
- Rust 启动子进程时必须使用句柄白名单，只继承协议 stdin/stdout/stderr 所需句柄；无关句柄泄漏视为安全失败。

## 5. 方案 B 不采纳理由

实测未显示 WebSocket 的独立优势；其保留端口监听面（令牌、Origin、防火墙、企业策略）与重连/心跳复杂度，且与 Codex 的生产实践相反。保留为上位计划允许的备选，仅当 Rust bridge 在打包阶段出现不可修复问题时重议。

## 6. 遗留事项（移交后续阶段）

1. Rust bridge 与 PyInstaller sidecar 的就绪握手时序（现有 `start_sidecar` 改造为管道模式），S5 实现；
2. 通知流（`item/delta` 等）与请求响应在同一流上的客户端分发模型，S2 schema/codegen 时固化（前端 `transport/` 模块按 ADR 实现）；
3. stdio 管道的字节吞吐上限对大 artifact 引用的影响——大输出走 `content_ref`（§7.4），不经协议流，已天然规避。

## 7. 决策

评审接受 stdio/JSONL + Rust bridge 为 1.0 Agent 主通道。S2/S5 实现必须遵守 stdout 协议专用、stderr 日志分流、UTF-8、1 MiB 上限、有界队列和句柄白名单规则；任一条无法达成时不得静默回退到未认证的网络通道。
