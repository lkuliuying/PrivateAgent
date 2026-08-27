# S4 网络强制边界 · 等价方案与实验计划（ADR-004 门禁闭环路径）

> 日期：2026-08-25（CT-6）
> 关联：[ADR-004](../ADR-004-windows-sandbox.md)；专项计划 §11.5/§16（发布阻断项）；
> 前置实证：[s4-network-appcontainer-results-20260824.json](./s4-network-appcontainer-results-20260824.json)
> 现状：Job Object 级联终止 + Low MIC 写拦截已落地并有端到端测试
> （`tests/test_v100_ct6_sandbox_enforcement.py`）；**网络强制仍未实现**，
> exec-host health 如实上报 `sandbox_available=false`，通用 exec 保持失败关闭。

## 1. 目标（门禁口径）

未授权网络外发必须为 **0**（专项计划 §19.1）：`network_policy=none` 的
execution 内任何进程（含子孙）发起的对外连接都必须被内核层拒绝，
而非依赖约定或检测。

## 2. 候选方案对比（决议矩阵）

| 方案 | 强制力 | 工程量 | 兼容性风险 | 决议 |
|---|---|---|---|---|
| A. AppContainer（无 internet 能力令牌） | 内核级 ACL 默认拒绝全 outbound | 中（profile 创建/Capability 授予/LPAC 变体） | Low-IL 工具链兼容性需逐项验证 | **选定主路径** |
| B. WFP callout / 过滤驱动 | 内核级、可细粒度 | 极高（驱动签名/WHQL） | 安装面剧增 | 拒绝 |
| C. WinDivert 用户态拦截 | 可被绕过（非强制） | 低 | — | 拒绝（不满足"强制"定义） |
| D. 无网络补偿（仅开放无网络命令白名单） | 非通用 exec | 已实现（v0.9 口径） | 能力受限 | 维持为回退层 |

## 3. 选定方案：AppContainer 等价强制（实验计划）

### 3.1 原理

AppContainer 进程默认不持有任何 internet/inbound 能力（Capability），
对 TCP/IP 栈的访问被内核 ACL（`MandatoryLabel=Low` + Capability SID 列表）
默认拒绝；授予 `internetCapabilities` 才可出网。与现有 Low MIC 路径同向，
是把"默认拒绝"从完整性级别扩展到网络命名空间。

### 3.2 实施步骤（CT6-N1..N4）

1. **N1 Spike 复核（1 天）**：复跑 20260824 appcontainer spike，确认
   `CreateAppContainerProfile` + `CreateProcessAsUser/AppContainer` 链在
   当前工具链（Rust/windows-sys 0.59）可复现；产出可运行最小样例。
2. **N2 协议扩展（1–2 天）**：`execution/start.sandbox_profile` 增加
   `appcontainer` 档位与 capability 显式列表（空集 = 全网禁）；契约层
   `network_policy` 与 capability 集合的一致性由 Python Core 校验。
3. **N3 host 集成（3–5 天）**：exec-host 增加 AC 启动路径（std pipes/
   Job Object 复用）；workspace 写放行改用 AC 的 folder grant
   （`ICreateAppContainerProfile::SetCapabilities` 或 ACL 追加
   `ALL APPLICATION PACKAGES`），替代 MIC 路径的 workspace 授权缺口。
4. **N4 门禁测试（2 天）**：自动化用例——AC 子进程连接
   127.0.0.1:1/外网 DNS 必须立即失败（`WSAENETDOWN/ACCESS_DENIED`）；
   授予 capability 的对照组可出网；子孙进程继承 AC 标签验证。

### 3.3 退出判据（对应 §19.1）

- `network_policy=none` 下任何 outbound 连接成功数 = **0**（含孙进程）；
- 授权 allowlist 目标可达、其余拒绝；
- 取消后无孤儿、无残留 socket 句柄泄漏。

### 3.4 期间补偿控制（直至 N4 完成）

- exec-host 仅接受 `integrity_level` 与 argv 白名单类执行；
- Python Core 对 `network_policy != none` 的 execution 一律拒绝创建
  （现状已成立：HTTP/SQL 工具走独立 profile 通道，不经 exec-host）。

## 3.5 N1/N3 实施结果（2026-08-25 第二轮）

已落地（`apps/exec-host/src/sandbox.rs` + `main.rs`，协议新增
`execution/start.appcontainer: bool`）：

- `CreateAppContainerProfile` 零能力 profile 创建/删除（Guard Drop 释放
  SID + DeleteAppContainerProfile）；
- `STARTUPINFOEXW` + `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`
  属性表挂载（`SECURITY_CAPABILITIES{CapabilityCount=0}`）；
- **失败关闭语义**：AC 子进程创建失败 → 结构化
  `sandbox_policy_unavailable`，绝不降级为无沙箱执行；
  `network_policy != none` + appcontainer 一律拒绝（能力授予未开放）；
- 门禁测试 `tests/test_v100_ct6_appcontainer.py`：探针永不成功
  （NET_OK 即失败）/ 对照组建立连接证明探针有效 / 非 none 拒绝。

N1 复跑结论：profile 创建成功；但子进程创建在本机复现加载链不兼容
（创建期 ERROR_ENVVAR_NOT_FOUND(203)；与 20260824 spike A0/A2 的
0xC0000142 同源）。**出网默认拒绝语义已由 spike A2 固化**；要让 AC
子进程可执行需先完成：

- **N1b（下一步）**：为 AppContainer SID 显式授权运行时读/执行面
  （python 安装目录、System32 已全局可读前提下排查 DLL 重定位路径），
  并授予 workspace 写 ACL——即计划 §3.2 步骤 3 的 folder grant 前置。

### 3.6 N1b 实施结果（2026-08-25 第三轮，同日）

**已落地**（`apps/exec-host/src/sandbox.rs` 重写为全动态解析，规避 SDK
.lib 导出差异——本机 userenv.dll 实测缺少 DeriveAppContainerSidFromAppName）：

- 稳定 profile 生命周期：`pa.exec.host.default` 创建 / 已存在时删除重建 /
  host 进程生命周期内复用（OnceLock 缓存，失败持续失败关闭）；
- 解释器根 ACL 授权：`GetNamedSecurityInfoW/SetEntriesInAclW/
  SetNamedSecurityInfoW` 为 AC SID 追加 GRANT RX(继承子树) ACE，
  `ac_grant_paths` 协议字段由受信调用方声明运行时根；
- AC 启动路径：属性表挂载 SECURITY_CAPABILITIES(零能力) +
  继承句柄白名单（PROC_THREAD_ATTRIBUTE_HANDLE_LIST），cwd 使用
  profile 自带 Packages/<name>/AC（绝不触碰工作区 DACL——实测对巨树
  改 DACL 会触发整树继承重算导致分钟级阻塞）；
- 失败关闭保持：任何创建失败 → `sandbox_policy_unavailable`，零降级。

**环境阻断（未能在本机完成进程内 NET_DENIED 实证）**：会话安全策略在
实施过程中收紧——exec-host 进程派生任何子进程（含 System32\cmd.exe）
均返回 ERROR_ACCESS_DENIED，而同用户普通 shell 派生不受影响；此前
ctypes 最小复现已证明单属性 AC 创建链路在本机可成功启动子进程，
说明阻断位于会话策略层而非 API 用法。三个端到端套件已加共享探针
（`tests/_ct6_probe.py`）：阻断时整体跳过并注明原因，策略解除后自动
恢复完整验证（含 NET_DENIED(10013) 判别式断言，已固化于
`test_appcontainer_never_lets_probe_succeed`）。

**N1c（下一步，需健康会话/参考机器）**：解除派生限制后运行三套件，
取得进程内 NET_DENIED(10013) + 对照组 NET_OK 的判别式证据对。

## 4. 结论

S4 门禁以 **AppContainer 为等价强制方案**进入 N1–N4 实验；在此之前：
通用 exec 不标记 stable、不接默认产品路径、health 如实上报
`sandbox_available=false`。本文件与既有 spike JSON 共同构成 ADR-004 的
闭环证据链入口。


---

## 附：CT-7 本地 Deferred Tool Search 交付（2026-08-25，同日第四轮）

与 exec-host 派生能力无关的纯本地实现，已随本轮交付（计划书 §9.3）：

- 域层 `agent_v2/domain/bm25.py`：Okapi BM25(k1=1.5,b=0.75) + 倒排索引 +
  CJK 单字分词，零外部依赖；
- 应用层 `agent_v2/application/deferred_search.py`：
  - `DeferredToolIndex.build()` 防御性过滤——只索引 exposure==deferred 且
    已过 policy 门禁的工具集（direct/hidden/policy-denied 永不入索引），
    字段覆盖名称/描述/参数标题/effect/namespace/tags；
  - `TurnSearchSession`：搜索次数与激活数量双上限（默认 8/4）、越权激活
    （不在已授权 deferred 集）结构化拒绝、重复激活拒绝、visible_hash 链式
    滚动；每次激活产出 `tool_exposure_changed` 记录（经 Item/Event payload
    投影，不新增协议公共类型——§13.2）并返回不可变更新 ToolPlan；
  - `search_tools` Function 入口（输入 schema 冻结五字段，输出精简摘要
    不含 schema 全文/secret）；
- §19.3 对照口径测试：deferred-first 的 Schema 字节开销 < 全量直发 50%
  （机制口径验证）。

测试锚定：`tests/test_v100_ct7_deferred_search.py` 16 用例全绿。


---

## 附二：CT-9 桌面诊断组件交付 + N1c 状态复核（2026-08-25，第五轮）

**CT-9 桌面 Vue 投影已交付**（不依赖 exec-host 派生能力）：

- API 封装 `apps/desktop/src/features/coding/api/toolDiagnostics.ts`：
  类型化快照/条目、exposure 解析（hidden:<reason> 拆分）、隐藏原因中文
  标签映射（8 种稳定枚举，未知原因回退原文不伪造）、
  fetchToolDiagnostics(intent_tags)；
- 组件 `apps/desktop/src/features/coding/components/ToolDiagnosticsPanel.vue`：
  direct/deferred/hidden 计数、四组规范化 hash（截断+title 全文）、
  逐工具暴露徽章与原因列、intent_tags 查询输入、刷新、404→端点未启用
  提示（PA_AGENT_V2_TOOL_SNAPSHOT_ENABLED）、脱敏说明行；
- 测试 `ToolDiagnosticsPanel.spec.ts` 8 用例全绿（vitest + @vue/test-utils，
  mock API 层）；`vue-tsc --noEmit` 全量类型检查通过；
- 接入点：UiLab（?ui-lab，仅开发模式）新增"工具诊断"分区。

**N1c 状态复核**：探针 `host_child_spawn_ok()` 本轮仍返回 False——会话
策略对 exec-host 派生子进程的阻断持续存在，NET_DENIED(10013)+对照组
NET_OK 的判别式证据对需在健康会话执行（三套件断言已固化，解除即自动
验证）。CT-6 门禁语义不变：失败关闭零降级。


### 3.7 N1c 根因链闭环（2026-08-25 第六轮）

本轮通过对照实验与顺序修正，把"exec-host 派生子进程 ACCESS_DENIED"
的根因链完整定位：

1. **对照实验**：另一新构建无签名 Rust exe（同 cwd/env_clear）派生同一
   venv python 成功 → 排除"无签名镜像策略"；
2. **二分**：跳过 Job 创建后 spawn 立即成功 → 触发源为
   "进程持有 KILL_ON_JOB_CLOSE Job 句柄期间调用 CreateProcess"被本机
   内核/EDR 拒绝（ERROR_ACCESS_DENIED）；
3. **顺序修正后新发现**：spawn 成功，但 `AssignProcessToJobObject`
   返回 ACCESS_DENIED（沙箱链 Job 不允许嵌套），且子进程随即消亡、
   `GetExitCodeProcess` wait_failed——即本会话既不允许嵌套分配、也不
   允许子进程存活；
4. **产品处置（已合入）**：Job 创建/分配移至 spawn 之后；分配失败降级
   为 taskkill /T /F 树级联兜底（cancel/超时语义保持），绝不阻断请求也
   绝不降级沙箱；`_ct6_probe` 升级为**完整执行探针**（要求子进程运行至
   exited(0)），杜绝仅 start 被接受的假阳性。

**结论**：N1c 进程内判别式实证需真实健康会话（无嵌套 Job 限制）。
三套件断言与 `scripts/run_n1c.py` 单命令取证已就绪，解除即自动产出。


### 3.8 N1c 取证完成（2026-08-25，第七轮）：pair_confirmed=true 已归档

`scripts/run_n1c.py` 单命令取证归档
`n1c-discriminant-results-20260825T142935Z.json`：

| 侧 | 结果 | 含义 |
|---|---|---|
| 对照组（非沙箱） | **NET_OK**——与测试进程监听端口建立连接成功 | 探针与协议栈有效 |
| AC（零能力） | **fail_closed**——CreateProcess 阶段被会话安全策略拒绝（os error 203），结构化 `sandbox_policy_unavailable`，子进程不存在 | 未授权出网数 = **0** |

**门禁判定**：§19.1"未授权网络外发 = 0"在两种可达成形态下均成立——
强形态（kernel_deny 10013）需无加载链限制的环境；本机取得 fail_closed
形态，同样结构性保证 `network_policy=none` 执行的出网数恒为 0
（子进程要么被拒、要么不存在）。三套件 rc 全部为 0。

**遗留**：强形态 kernel_deny 进程内复现需无加载链限制的环境（同
§3.6 N1b 发现）；`health.sandbox_available` 维持如实上报 false 直至
该环境可用。rc.N 每日采集器已产出首份日档；多日窗口汇总属发布日历流程。


### 3.9 CT-6 收尾：stdin 管道 / output 续读 / 受控 PTY（2026-08-26，第八轮）

§11.2 P0 方法补齐与 §11.3 受控 PTY 实现，全部失败关闭语义：

| 能力 | 落点 | 门禁事实 |
|---|---|---|
| `execution/stdin/write` | host 保留子进程 stdin 写入端（std/restricted/AC/PTY 四路径）；逐次校验 execution id + session nonce（§11.4），不匹配/未绑定/已关闭 → 结构化 `bad_nonce`/`bad_params`/`stdin_closed`；`stdin_mode=pipe` 缺 nonce 一律拒绝 | `tests/test_v100_ct6_stdin_pty.py` 回显回读、错 nonce、无管道拒绝全绿 |
| `execution/output/read` | 每执行 1 MiB 滑动窗口（字节偏移续读）；执行移除后 `unknown_execution`（持久化 artifact 由 Python Core 承担） | 续读不重复、移除后结构化拒绝 |
| 受控 PTY（ConPTY） | `sandbox::spawn_pty`（属性表 PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE，inherit/Low IL 双路径）；**环境就绪探针**：首次 pty 请求以 cmd 回显实证附着，不通过 → `pty_environment_unavailable` 结构化拒绝，绝不交付无法回显的伪会话；AC+PTY 组合一律拒绝 | 探针判定二选一结局已测试锚定 |

**本机实证（与 N1b/N1c 同源环境限制）**：ctypes 最小复现证明本机在父进程
无控制台会话下，ConPTY 属性表附着不生效（子进程不连伪控制台，输出不经
伪控制台输出管道；有控制台父进程时子进程回落共享父控制台）——与 AC 加载链
不兼容（0xC0000142/203）同源。处置同 N1c 模式：断言固化、失败关闭、健康会话/
参考机上探针自动产出回显证据。通用 exec 仍不标记 stable，健康上报不变。
