# ADR-004 · Windows 沙箱技术组合

> 状态：Accepted with implementation gate（2026-08-24；写边界/进程树基线接受，网络强制边界尚未闭环）
> 日期：2026-08-24
> 关联：上位计划 §10.4 / §15 S1；执行计划 S1-T4/T7
> 实证脚本：`scripts/spikes/s1_sandbox_windows_spike.py`（基线）
> 　　　　　`scripts/spikes/s4_network_appcontainer_spike.py`（网络补偿二次实证）
> 实证结果：[evidence/s1-sandbox-spike-results-20260824.json](./evidence/s1-sandbox-spike-results-20260824.json)（5/5 项与记录一致）
> 　　　　　[evidence/s4-network-appcontainer-results-20260824.json](./evidence/s4-network-appcontainer-results-20260824.json)（6/6 项与记录一致）

## 1. 背景与问题

1.0 要求所有子进程进入可验证的 Windows 原生沙箱：工作区可写、系统依赖可读、敏感目录拒绝、网络默认关闭、进程树统一回收，且策略无法表达时失败关闭（§10.4）。本 ADR 决定实现该策略的技术组合。

## 2. 候选方案

| 方案 | 机制 | 写边界 | 网络控制 | 派发权限要求 | 工具链兼容性 |
|---|---|---|---|---|---|
| A. 低完整性令牌（MIC） | DuplicateTokenEx 降级 + Low IL | ✅ NO_WRITE_UP 原生强制 | ❌ 无 | 普通桌面权限（实测） | 高（解释器/构建工具普遍可用） |
| B. Restricted Token | CreateRestrictedToken + restricted SIDs | ✅ 双重访问检查 | ❌ 无 | 普通桌面权限 | 中（需精细 DACL 配置） |
| C. AppContainer | SECURITY_CAPABILITIES | ✅ 默认几乎全拒 | ✅ 出站默认拒绝 | 普通桌面权限（已实测） | 低（默认下 System32/cmd 加载失败） |
| D. Job Object | KILL_ON_JOB_CLOSE | ❌ 无 | ❌ 无 | 普通桌面权限 | 高 |
| E. WFP/防火墙规则 | 按进程路径/令牌过滤 | ❌ 无 | ✅ 可实现 | 需管理员规则配置 | 高 |
| F. `Experimental_CreateProcessInSandbox` | Windows 11 `processmodel.dll` + AppContainer/BFS policy | ✅ | ✅ | 待实测 | 不适用 1.0：官方标记 experimental，且不支持 Windows 10 |

## 3. 实证记录（2026-08-24，本机实测）

### 3.1 派发机制（关键架构发现）

1. `CreateProcessWithTokenW` 在非提权桌面进程下失败：`ERROR_PRIVILEGE_NOT_HELD (1314)`——需要 SE_IMPERSONATE/SE_TCB，交互式用户令牌不具备。
2. **`CreateProcessAsUserW` + 启用当前进程令牌自带的 `SeAssignPrimaryTokenPrivilege`（默认存在、禁用态）成功派发低完整性子进程，无需管理员权限**。这意味着沙箱派发器可运行在普通桌面权限（sidecar 内），不依赖安装期提权常驻组件。
3. 句柄继承：`bInheritHandles=True` 时管道重定向生效；生产实现必须改用 `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` 白名单，防止无关句柄泄漏给沙箱进程。

### 3.2 五项最小证明（脚本 `--json` 输出为准）

| # | 证明 | 结果 | 证据 |
|---|---|---|---|
| P1 | Low 标签工作区目录可写 | ✅ | 探针写入成功且文件存在 |
| P2 | python.exe / kernel32.dll 可读 | ✅ | 两个探针均成功 |
| P3 | %TEMP%、%USERPROFILE%、`~/.ssh` 写入被拒 | ✅ | 全部 `PermissionError: [Errno 13]`，无文件产生 |
| P4 | MIC 下出站网络行为 | ✅（记录缺口） | DNS 与 TCP（127.0.0.1:135）均成功 → **MIC 不实施网络控制，确认为已知缺口** |
| P5 | Job Object 进程树回收 | ✅ | 终止前 job 内活跃进程=4（父+孙树），关闭句柄后全部终止，无孤儿 |

补充：v0.9 `_JobObject`（`command_workflow.py`）已在生产验证 KILL_ON_JOB_CLOSE 语义，可直接复用其封装形态。

## 4. 推荐组合（待评审）

**基线层：MIC 低完整性令牌（写边界）+ Job Object（进程树）+ `SeAssignPrimaryTokenPrivilege` 派发路径。**

**网络层候选（2026-08-24 二次实证已完成，结论如下）：**

- 候选 N1：AppContainer 子沙箱——**实测不可单独采用**：非提权桌面权限可创建 AppContainer profile 并派发子进程（`PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES=0x00020009`），出站默认拒绝成立（含回环），但默认拒绝语义下 System32 对 AppContainer SID 不可读，cmd 加载链直接 `STATUS_DLL_INIT_FAILED (0xC0000142)`——隔离过度成立但工具链零兼容；除非实现 System32/.venv 全链授权工程（工作量大、引入新攻击面），否则不采用；
- 候选 N2：防火墙按程序规则——**实测非提权不可配置**（`netsh advfirewall` 需管理员，普通桌面权限返回“需要提升”）。Microsoft 官方口径明确 Windows Firewall 默认允许出站，禁止需命中阻断规则，程序规则绑定具体可执行路径（[Microsoft Learn](https://learn.microsoft.com/windows/security/operating-system-security/network-security/windows-firewall/configure)）。由于 Agent 可启动 Python/Node/Cargo/Git 及其子进程，单一 sidecar/启动器路径规则**不能证明整棵任意工具链被阻断**。安装期规则只能作为待验证候选，不得仅凭“规则存在”宣称达标；
- 候选 N3：审批层兜底 + 出站审计（弱方案）——仅在 N2 安装期方案验证失败且经安全评审显式接受残余风险时使用；**默认不视为达标**。

Windows 11 新增的 `Experimental_CreateProcessInSandbox` 能用 AppContainer + Bound File System 同时表达文件与网络策略，但官方明确标记 API 为 experimental，最低仅 Windows 11（[Microsoft Learn](https://learn.microsoft.com/windows/win32/secauthz/createprocessinsandbox)）。PrivateAgent 1.0 承诺 Windows 10/11，因此本 API 只记入后续候选，不作 1.0 强制边界。

**接受的基线**：MIC + Job Object（已实证），用于写边界与进程树回收。**未接受的部分**：N2 安装期防火墙规则尚未证明能覆盖任意子进程工具链，所以网络默认关闭仍为 S4 实施门禁。S2/S3 可继续，但 S4 不得退出、`alpha.2` 不得发布，直到任意工具链出站阻断、规则篡改检测和卸载对称性有完整实证。

## 5. 失败关闭规则（不可协商）

1. 令牌降级、Job 挂入、完整性标签设置任一失败 → 命令拒绝执行，返回明确错误，不静默降级为 full access；
2. 沙箱策略与审批策略独立：审批通过不豁免沙箱，沙箱不替代审批（§10.4 / §18 三权分离）；
3. 策略无法表达（如目标路径无法完成完整性标签检查）→ 拒绝并记录审计。

## 6. 开放问题（二次实证后更新）

1. 网络补偿机制：N1 不单独采用（工具链零兼容实证）；N2 只是 S4 首个待验证候选，未完成任意子进程工具链阻断实证前不视为闭环。
2. `.git`、凭据、PrivateAgent 配置目录除 MIC 默认拒绝外，是否需要叠加显式 DACL deny ACE 作纵深防御？
3. workspace 内符号链接/重解析点指向外部时的逃逸面：MIC 下符号链接目标的完整性级别决定写入结果，需专项路径测试（纳入 S4 安全测试矩阵）。
4. 解释器链（python → pip → 子进程）在 Low IL 下的缓存写入行为（如 pip cache、npm cache 位于 Medium 目录）会失败——需定义“缓存目录白名单标签化”策略或命令级豁免审批。
5. `full_access` 策略下仍保留的硬边界（秘密、审计、远程外发）的执行点定义，与审批策略的接口。
6. **新增（二次实证）**：N2 安装期规则的完整设计——规则范围（仅沙箱子进程路径/令牌可识别粒度）、与 uninstall 的清理对称、规则存在性运行时审计、被篡改时的失败关闭路径；若验证失败则回到 N3 + 安全评审。

## 7. 决策

评审接受 MIC + Job Object + `CreateProcessAsUserW` 作为生产实现基线，并接受 N1 不适作通用工具沙箱的实证结论。本 ADR 以 `Accepted with implementation gate` 生效：它解锁 S2/S3，但不构成“网络默认关闭”验收证据。S4 必须将脚本升级为 adapter/security 回归，并在具体网络强制方案全绿前保持失败关闭。
