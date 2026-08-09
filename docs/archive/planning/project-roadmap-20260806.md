# PrivateAgent 项目整体执行路线图（2026-08-06 校准版）

> **路线状态（2026-08-08）**：本文保留 `0.2.1` 历史事实和技术背景；后续逐minor稳定发布、逐版本7–15天观察的安排，已由 [`integrated-0.5.0-development-plan-20260808.md`](./integrated-0.5.0-development-plan-20260808.md) 替代。后续以连续开发列车和 `0.5.0-rc.1` 单次14天集成观察为准。

> 基线日期：2026-08-06  
> 当前源码：`cbbc9fe`（0.2.1 冻结提交，`main` 比 `origin/main` 领先 11 个提交，工作区干净）
> 当前应用版本：`0.2.1`（本地候选已安装运行，unsigned）
> 当前数据库：`0021 (head)`  
> 当前交付边界：Windows 10/11 x64、本地优先、外部 Ollama、unsigned 安装包  
> 文档目的：给出从当前状态到稳定发布、Runtime 默认启用、可信工作流和后续扩展的完整执行顺序。

> **执行进度（2026-08-06）**：
> - 阶段 A（0.2.1 冻结）✅ `cbbc9fe`：版本统一 0.2.1、CHANGELOG、文档事实收口。
> - 阶段 B（工程门禁）✅：14/14 全绿、`worktree_dirty=false`、schema `0021`、`pytest 584 passed`。
> - 阶段 C（安装包与升级验收）✅：NSIS 构建、0.2.0→0.2.1 升级 run #27、回滚 run #28、
>   updater 签名正/负验证；安装版 0.2.1 已运行。
> - **QA 收尾（0.2.1 正式发布）✅ `a3ac17c` + tag `v0.2.1`**：
>   * T1 桌面退出 sidecar 进程树清理（taskkill /T）+ 3 轮启动-退出回归零残留；
>   * T2 安装版批 A 安全启用（%APPDATA%\.env，备份保留）+ QA 静态 token 钩子
>     （PA_QA_STATIC_TOKEN，默认关闭）+ 真实 Agent API/RAG smoke 通过；
>   * T3 全新 %APPDATA% 干净安装：health 全绿、collections=0、Agent API/RAG 可用，已还原；
>   * T4 run #27/#28 补齐 data_preserved/schema_ok、manifest 手工验收项由
>     `--qa-evidence` 机器证据勾选（dist/qa-evidence-0.2.1.json）；
>   * T5 最终门禁绑定 `a3ac17c`（打 tag 的同一提交）；
>   * T6 **已推送 main + tag v0.2.1 并发布 GitHub Release**
>     （https://github.com/lkuliuying/PrivateAgent/releases/tag/v0.2.1，9 资产）。
> - 阶段 D（批 A 生产观察）：安装版 0.2.1 已含批 A 与 0021，观察窗口自此起算。

## 1. 总体判断

PrivateAgent 目前已经完成大部分技术底座，但还没有形成一个与当前源码完全一致、可正式放行的发布候选。接下来不应继续横向增加功能，而应先完成一次版本收敛，再依次推进 Runtime 灰度、真实工作流接入和条件性外部能力。

推荐采用四条发布主线：

| 建议版本 | 主目标 | 主要内容 | 发布条件 |
|---|---|---|---|
| `0.2.1` | 稳定化发布 | 收纳 `0021`、RAG 拒答、Ollama 生命周期、Runtime 批 A、领域验证器底座 | 当前 HEAD 的完整发布门禁、安装/升级/回滚实测 |
| `0.3.0` | Runtime 默认接管 | Chat Runtime 批 B、摘要 worker 独立灰度、兼容遥测观察 | 批 A 稳定窗口、安装版实机、可一键回退 |
| `0.4.0` | 可信执行工作流 | 逐个开放代码、Shell、API、数据库和多步骤工作流 | 每个工作流固定验证器、审批、审计、E2E |
| `0.5.0+` | 外部与平台扩展 | MCP、真实远程 Provider、签名、跨平台、更多集成 | 有明确产品需求、凭据、平台和发布资源 |

这些版本号是推荐方案。若 `0.2.0` 从未对外分发，也仍建议保留现有 `0.2.0` 证据，不覆盖同名安装包；当前新增代码使用 `0.2.1` 可以避免版本、哈希和 updater 资产混淆。

## 2. 当前事实基线

### 2.1 已完成并可继续沿用

- 数据库已经迁移到 `0021`，其中包含 compatibility telemetry 持久化。
- Versioned RAG indexing/retrieval 已启用，canonical 数据和来源事实已经验证。
- `rag-evidence-v1` 已在生产配置开启；10 个 reviewed case 的无答案拒答率为 `1.0`，Recall、MRR、引用正确率均为 `1.0`。
- Windows Ollama 交付模式已经确定为“外部 Ollama 由用户管理”，安装、模型、健康和 embedding 延迟有实测报告。
- Agent Runtime 批 A 已开启：Agent API、只读工具、ContextBuilder、输出验证和 RAG 工具。
- 六类领域级结果验证器已经实现；文件 Diff 验证已经接入 `propose_patch` 真实工作流。
- Windows `0.1.2 → 0.2.0` 安装、升级、数据保留、回滚和 updater 签名负面验证已有历史证据。
- 当前 Git 工作区干净，不存在待提交代码。

### 2.2 不能继续沿用为当前发布结论的证据

- `dist/release-check-0.2.0.json` 和 manifest 绑定的是 `c4c1566`、schema `0020`，不是当前 `e878001`、schema `0021`。
- 旧报告的 `14 passed / 0 failed / 0 skipped` 和 535 个 Python 测试只证明旧候选提交。
- 旧 `0.2.0` 安装包不包含其后新增的约 4500 行 R2–R4 代码和 `0021` 迁移。
- Runtime 批 A 的真实模型端到端验证使用测试库；安装版新构建尚未完成同等验证。
- 当前 compatibility telemetry 为一个窗口，且 `/tools=1`、`legacy_zero=false`，不满足旧链退出条件。

### 2.3 当前明确未完成

- 当前 HEAD 的发布门禁、安装包、manifest 和 updater 资产。
- 当前版本的干净安装、覆盖安装、升级、卸载、回滚和真实 `/health` 全绿验收。
- Chat Agent Runtime 默认接管和摘要 worker 灰度。
- 跨版本 compatibility telemetry 观察窗口及 legacy 归零。
- 代码、Shell、API、数据库和多步骤验证器的真实业务工作流接入。
- MCP 和真实 OpenAI/Claude 端点生产互操作。
- Authenticode、真实 GitHub Release updater、macOS/Linux 和 Tauri 窗口级自动化。

## 3. 执行原则

1. **先发布稳定化版本，再增加能力。** `0.2.1` 候选冻结后，不再混入 MCP、自动记忆或跨平台开发。
2. **实现完成不等于生产完成。** 代码、单测、测试库、安装版和真实外部服务分别报告。
3. **每个阶段必须可独立回退。** Feature flag、应用版本、数据库和 updater 回滚边界分别说明。
4. **报告必须绑定实际候选提交。** 不使用旧 commit 的全绿报告证明新代码。
5. **高风险能力逐个开放。** 不提供无边界的通用 Shell、任意 API 或任意数据库执行入口。
6. **条件性项目不阻塞主线。** 无证书、凭据、平台设备或发布权限时，如实标记未执行。
7. **生产副作用需要单独授权。** 包括主库迁移/降级、`.env` 开关变化、远程发布和真实第三方调用。

## 4. 阶段 A：事实源修正与 `0.2.1` 冻结

建议工期：1–2 个工作日。  
优先级：P0。  
目标：消除版本冲突和文档漂移，形成唯一发布候选范围。

### 4.1 任务

1. 确认当前公开稳定版本和实际分发范围：
   - 核对 Git tag、GitHub Release 和用户正在使用的最高版本；
   - 明确 `0.2.0` 是已分发版本、预发布候选还是仅本地构建；
   - 选择后续升级 smoke 的真实起点。
2. 将 Python、Vue、Tauri 和 Cargo 版本统一升级为 `0.2.1`：
   - `pyproject.toml`；
   - `apps/desktop/package.json`；
   - `apps/desktop/src-tauri/tauri.conf.json`；
   - `apps/desktop/src-tauri/Cargo.toml` 及相关 lockfile。
3. 增加 `0.2.1` changelog，列出：
   - `0021` telemetry 迁移；
   - RAG 拒答策略；
   - 外部 Ollama 生命周期和诊断错误码；
   - Runtime 批 A；
   - 领域验证器底座；
   - 已知限制和回滚说明。
4. 修正当前文档中的事实漂移：
   - 删除剩余计划中重复且冲突的 R4 行；
   - 将 Git、schema、开关和 Runtime 状态更新到当前事实；
   - 将发布完成定义从固定 `0020` 改为候选版本声明的目标 head；
   - 将历史完成证据和当前候选证据分开。
5. 冻结 `0.2.1` 范围：本阶段之后只接受发布阻断缺陷和必要文档修正。

### 4.2 验收标准

- 所有版本文件一致为 `0.2.1`。
- 没有新的 `0.2.0` 同名安装包覆盖旧证据。
- 文档中不存在 R4 双重状态、schema `0020/0021` 冲突或“批 A 未开启”等过期结论。
- 候选提交、数据库目标 head、发布基线和升级来源均明确记录。
- Git 工作区干净，候选范围完成一次人工复核。

## 5. 阶段 B：当前 HEAD 的工程质量门禁

建议工期：1–2 个工作日。  
优先级：P0。  
依赖：阶段 A 完成。  
目标：证明源代码本身达到构建候选标准。

### 5.1 必跑门禁

在守卫测试库和干净候选提交上执行：

1. Python 全量 pytest。
2. Ruff 检查。
3. Python compileall。
4. Vue/TypeScript build。
5. 前端单元测试。
6. 浏览器 Playwright E2E。
7. Rust `cargo check`。
8. Rust `cargo test`。
9. sidecar smoke。
10. Alembic current，必须为 `0021 (head)`。
11. Git diff check。
12. Docker Compose 配置验证。
13. 诊断包脱敏 smoke。
14. updater `latest.json` 结构和签名验证。

额外补跑本轮新增重点：

- RAG abstention 与 RAG 引用验证。
- compatibility telemetry 增量、窗口结束和零调用基线。
- Runtime owner lock、取消、审批恢复、SSE 断线和唯一消息投影。
- 六类结果验证器和 dispatcher durable failure。
- 旧聊天预算与 tokenizer 安全系数。

### 5.2 测试隔离规则

- 数据库测试禁止并行争用同一个 schema；为每个测试进程分配独立数据库或串行执行数据库组。
- 子进程取消测试必须在允许创建 Windows 子进程的环境运行，不能把沙箱 `PermissionError` 记为产品失败。
- 测试不得使用生产文档正文、生产 token 或真实远程 Provider 凭据。
- 超时后必须清理本次测试创建的 Python、sidecar、Git 和浏览器进程。

### 5.3 验收标准

- 强制门禁 `failed=0`、`skipped=0`、`ok=true`。
- 报告记录当前候选 commit、`worktree_dirty=false` 和 schema `0021`。
- 没有未解释的 flaky、hang、孤儿进程或测试数据库残留。
- 测试数量和耗时如实写入报告，不能继续复用 535 passed 的旧摘要。

## 6. 阶段 C：`0.2.1` 安装包与升级发布验收

建议工期：2–4 个工作日。  
优先级：P0。  
依赖：阶段 B 全绿。  
目标：验证实际交付物，而不只验证源码。

### 6.1 构建和事实源

1. 用阶段 B 的同一候选源码构建 sidecar、NSIS 安装包和 updater `.sig`。
2. 生成新的 `release-check-0.2.1.json/.md`、manifest、`latest.json` 和代码签名状态。
3. 报告保存安装包大小、SHA-256、updater 签名摘要和实际候选 commit。
4. 没有 Authenticode 证书时继续标记 `code_signed=no`，发布说明必须包含 SmartScreen 风险。
5. 发布报告应作为候选构建产物或 Release asset 保存，避免为了提交报告改变被证明的源码 commit。

### 6.2 安装 QA 矩阵

#### 干净安装

- 新 Windows 用户配置目录。
- 首启向导完成 MySQL、Ollama、模型和凭据引用配置。
- `/health` 的 API、Ollama、MySQL、ChromaDB 四项全绿。
- schema 自动到 `0021`。
- 聊天、RAG、Agent API、审批、文件 Diff 和诊断包 smoke 正常。
- 退出后 sidecar、临时端口和本应用启动的子进程无残留。

#### 升级安装

升级来源按阶段 A 的调查结果选择：

- 若 `0.2.0` 已真实分发：必须执行 `0.2.0 → 0.2.1`；
- 若 `0.2.0` 未分发：至少执行“最新公开稳定版 → 0.2.1”，并保留本地 `0.2.0 → 0.2.1` 兼容 smoke；
- 验证 `0020 → 0021`，以及已经在 `0021` 上重复启动的幂等性。

升级前后核对：

- settings 和 OS keyring 引用；
- 聊天、消息、知识库、文档、RAG versions/chunks/provenance；
- Agent runs、events、tool executions 和审批；
- compatibility telemetry；
- Chroma collection/vector 数量；
- 用户数据目录和本地导入文件。

#### 回滚和负面验证

- 应用回滚到升级前版本，用户数据保留。
- `0021` 是增加 telemetry 表的迁移时，优先验证旧应用能忽略新增表；非必要不做生产 downgrade。
- 验证覆盖安装、卸载保留数据和卸载后重新安装。
- 篡改 updater signature、安装包或 `latest.json` 后必须拒绝更新。
- Ollama 未启动、模型缺失、MySQL 不可达和 Chroma 异常必须显示可读诊断。

### 6.3 发布决策

只有以下条件全部满足才允许发布：

- 完整门禁绑定最终候选 commit。
- 安装包与报告中的 SHA-256 一致。
- 干净安装、升级、数据保留、回滚和负面签名测试通过。
- schema `0021` 和应用版本 `0.2.1` 一致。
- release notes 明确 Windows-only、外部 Ollama 和 unsigned 边界。
- 若没有 GitHub 发布权限，只能标记“本地候选验收完成”，不能标记远程 updater 已发布。

## 7. 阶段 D：Runtime 批 A 生产观察

建议观察窗口：至少 7 天；低使用量时延长到 14 天或累计 100 个有效 run。  
优先级：P1。  
依赖：包含 `0021` 和批 A 的安装版投入使用。  
目标：证明批 A 在真实安装版和持续运行中稳定，而不只是一次测试库 smoke。

### 7.1 保持开启

- `PA_AGENT_RUNS_API_ENABLED=true`
- `PA_AGENT_RUN_READ_ONLY_TOOLS_ENABLED=true`
- `PA_AGENT_CONTEXT_BUILDER_ENABLED=true`
- `PA_AGENT_OUTPUT_VERIFICATION_ENABLED=true`
- `PA_AGENT_RAG_TOOLS_ENABLED=true`
- `PA_COMPATIBILITY_TELEMETRY_PERSIST_ENABLED=true`

聊天接管和摘要 worker 继续关闭。

### 7.2 观察指标

- run 创建、完成、失败、取消和 waiting approval 数量。
- owner lock 丢失、重复 coordinator、孤儿 run 和启动 reconcile。
- provider timeout、首个 delta 后失败和重试次数。
- 输出验证失败率、修正成功率和重试耗尽率。
- RAG 拒答率、引用验证失败、无证据回答投诉和 P95 延迟。
- ContextBuilder 截断率、估算 token 与 provider usage 偏差。
- 工具执行耗时、取消是否及时、残留进程和重复副作用。
- compatibility telemetry 的 `/tools`、`/tools/plan` 和旧 `/tool-calls` 调用。

### 7.3 进入批 B 的门槛

- 无数据损坏、重复副作用、审批绕过或秘密泄漏。
- 无持续 stuck run；异常 run 均可取消、恢复或由 reconcile 处理。
- owner lock 和多进程故障门禁稳定。
- 输出/RAG 验证失败均可解释，重试不会形成无界循环。
- 安装版重启、升级和异常退出后 telemetry 窗口连续可读。
- 已有故障有明确回退或修复，不存在未处置 P0/P1 阻断问题。

### 7.4 回退

- 逐个关闭批 A 开关，不做数据库 downgrade。
- 保留 `0021` telemetry 数据用于复盘。
- 停止新 run 后处理已有 running/waiting approval 状态，不能直接删除记录。

## 8. 阶段 E：Runtime 批 B 与默认聊天接管

建议工期：3–5 个工作日实施，加 7–14 天观察。  
建议版本：`0.3.0`。  
优先级：P1。  
依赖：阶段 D 达标。  
目标：让普通聊天和知识库聊天进入 durable Runtime，同时保留快速回退能力。

### 8.1 灰度顺序

1. 在隔离配置开启 `PA_CHAT_AGENT_RUNTIME_ENABLED=true`，先验证普通无工具聊天。
2. 验证多轮聊天、原生流式、SSE 断线、取消、重连和唯一 assistant message。
3. 验证知识库聊天进入 RAG 工具与引用验证链。
4. 验证审批暂停、应用重启和 resume。
5. 小范围安装版灰度，再扩到默认启用。
6. Chat Runtime 稳定后，单独开启摘要 worker；不得与聊天接管同批切换。

### 8.2 必须覆盖的故障场景

- Ollama 中途离线和超时。
- MySQL 短暂断连、owner lock 丢失和进程崩溃。
- SSE 客户端断开、重复 continuation 和并发取消。
- RAG 无答案、引用伪造和证据记录被篡改。
- 审批 token 过期、拒绝、一次消费和恢复。
- 旧 `tool_result` 请求继续走兼容链时的行为一致性。

### 8.3 验收标准

- 新聊天不再预调用旧 planner。
- 普通聊天和 RAG 聊天的 UI 契约保持兼容。
- 每个完成回复只投影一次，断线重连不产生重复消息。
- 关闭 Chat Runtime 开关即可回到 legacy ChatService，不要求数据库回退。
- 默认启用后完成一个稳定观察窗口，再讨论删除旧链。

## 9. 阶段 F：领域验证器接入真实工作流

建议工期：每个工作流 2–5 个工作日，逐个发布。  
建议版本：`0.4.0` 起。  
优先级：P1。  
依赖：Runtime 批 A 稳定；涉及聊天入口时还依赖阶段 E。  
目标：把已经实现的验证器变成用户可用且可审计的可信执行能力。

### 9.1 接入顺序

| 顺序 | 工作流 | 当前状态 | 上线前必需条件 |
|---:|---|---|---|
| 1 | 文件 Diff / patch proposal | 已有真实接入 | 补齐安装版 UI、失败展示和回滚 smoke |
| 2 | 代码验证命令 | 只有验证器 | 固定命令白名单、只读默认、超时和输出上限 |
| 3 | Shell 任务 | 只有验证器 | capability allowlist、危险命令拒绝、CONFIRM 审批、取消清理 |
| 4 | API 调用 | 只有验证器 | 固定目标 allowlist、Schema、TLS、幂等键、隐私预览 |
| 5 | 数据库操作 | 只有验证器 | 固定 repository 方法、事务、影响行上限、读回和备份 |
| 6 | 多步骤完成条件 | 只有验证器 | 由可信 workflow 定义谓词、checkpoint 和补偿动作 |

### 9.2 每个工作流的标准模板

每次只开放一个具体业务工作流，并完成：

1. 用户故事和非目标。
2. 输入/输出 JSON Schema 和大小限制。
3. SAFE/CONFIRM/DENY 风险等级。
4. 固定 capability 与资源 allowlist。
5. 验证器由可信 dispatcher 注入，模型不能选择。
6. 审批预览展示目标、参数、影响和敏感范围。
7. durable execution、幂等键和崩溃恢复。
8. 结果验证、失败反馈、重试上限和补偿/撤销。
9. UI 活动时间线和公开验证结果。
10. 成功、失败、超时、取消、审批拒绝、重放和恢复 E2E。

### 9.3 明确禁止

- 不提供模型可自由拼接的任意 Shell。
- 不允许任意 URL、任意 SQL 或任意文件系统路径。
- 不让模型自报“测试通过”或“数据库已提交”。
- 不以单元测试通过替代真实工作流接入验收。

## 10. 阶段 G：兼容链退役

建议工期：2–3 个工作日，必须作为独立版本变更。  
优先级：P2。  
依赖：阶段 E 默认启用并稳定运行至少一个发布周期。  
目标：安全移除不再使用的 planner/tool-call 兼容路径。

### 10.1 退役门槛

- Runtime 模式桌面消息的旧 planner 调用为 0。
- 批 B 默认启用后的完整观察窗口内 legacy 调用为 0。
- pending tool call 和 waiting approval 已耗尽、迁移或有人工处置方案。
- 最低支持客户端版本不再依赖旧端点。
- 回滚版本与 updater 策略不会重新调用已删除端点。

### 10.2 顺序

1. 增加弃用日志和诊断提示。
2. 先停止桌面端调用，保留后端兼容一个版本周期。
3. 用 telemetry 验证归零。
4. 独立提交删除 `/tools/plan` 和旧 tool-call 路由。
5. 重跑完整发布门禁、升级和回滚测试。

## 11. 阶段 H：条件性外部能力

这些工作只在有真实需求和授权环境时启动，不阻塞 `0.2.1–0.4.0` 主线。

### 11.1 MCP

- 保持 `PA_MCP_ENABLED=false`，直到明确首个真实服务。
- 首个 MCP 服务需要完成凭据 keyring 引用、TLS、工具 allowlist、审批、限流、审计和撤销。
- OAuth 服务还需 discovery、device/authorization flow、refresh、过期和 revoke。
- 企业代理、证书 pinning、多客户端和公网入口只在真实场景出现后设计。

### 11.2 OpenAI-compatible / Claude

- 由用户明确提供测试凭据和可发送数据范围。
- 验证真实流式、工具调用、Structured Output、usage、取消和错误分类。
- 远程调用前展示隐私预览，审计中不保存 secret 或完整敏感上下文。
- MockTransport 合同测试不能写成真实端点验收。

### 11.3 自动记忆与更多集成

- 自动长期记忆写入前先建立误写率、敏感分类、确认、撤销和来源追踪。
- 保持当前候选记忆/显式确认链作为安全默认。
- 邮件、浏览器和文件夹监听分别作为独立集成，不建立无边界“万能连接器”。
- 每个集成必须有隐私预览、最小权限、来源、审计和撤销。

## 12. 阶段 I：发布工程与平台扩展

优先级：P2/P3，可与后期功能研发并行，但必须有独立平台负责人。

### 12.1 Windows 正式签名

- 获取 Authenticode 证书和安全的签名执行环境。
- 私钥不得进入仓库、普通 CI 日志或开发机明文文件。
- 验证 signtool sign/verify、时间戳服务、证书到期和轮换。
- 重签安装包后重新生成 updater `.sig`、SHA-256 和 manifest。

### 12.2 真实 GitHub Release updater

- 获得仓库发布权限后上传安装包、`.sig`、`latest.json`、报告和说明。
- 用真实 HTTPS Release 资产执行检查、下载、签名验证、安装和回滚。
- 验证错误签名、404、断网、部分下载和旧版本回退。

### 12.3 Tauri 窗口级自动化

- 覆盖真实 WebView、首启向导、原生凭据窗口、托盘/关闭和 updater UI。
- 浏览器 Playwright 继续保留，但不能代替真实桌面窗口测试。

### 12.4 macOS/Linux

- 只有产品决定正式支持后启动。
- 分别完成 sidecar 构建、数据目录、权限、MySQL/Ollama 依赖、签名/公证、安装和 updater smoke。
- 在完成前始终声明 Windows-only。

## 13. 推荐的并行分工

| 工作流 | 可执行内容 | 不应并行修改 |
|---|---|---|
| Release/Version | 阶段 A、B、C；版本、manifest、安装包、升级证据 | 其他人不要同时改版本文件和 `dist` 发布事实源 |
| Runtime/Telemetry | 阶段 D、E、G；指标、灰度、兼容链 | 不要在 Release 冻结期间改 Runtime 核心代码 |
| Workflow/Verification | 阶段 F；一个工作流一个切片 | 不要多人同时改 dispatcher、审批和 execution 核心 |
| External | 阶段 H；真实 MCP/Provider 单项验证 | 不要未经授权修改生产 `.env` 或调用付费端点 |
| Platform/Signing | 阶段 I；证书、GitHub Release、桌面 E2E | 不接触未授权私钥，不覆盖现有 updater 资产 |
| Documentation/QA | 事实核对、runbook、测试矩阵、已知限制 | 不独立宣称生产完成，必须引用机器证据 |

可以并行的是独立文档、独立测试和不同模块的准备工作；不能并行争用主数据库迁移、生产 `.env`、同一个测试数据库、版本文件或 release artifact 目录。

## 14. 风险登记

| 风险 | 当前等级 | 影响 | 控制措施 |
|---|---:|---|---|
| `0.2.0` 同名资产与当前代码不一致 | 高 | updater、哈希和问题定位混乱 | 使用 `0.2.1`，保留旧证据不覆盖 |
| 发布报告绑定旧 commit/schema | 高 | 错误放行 | 当前候选重新跑完整门禁 |
| 安装版仍是旧二进制 | 高 | `.env` 已开启但代码能力未实际装入 | 构建 `0.2.1` 后做安装版实机 |
| legacy telemetry 非零 | 中 | 不能安全删旧链 | 批 B 后观察完整发布周期 |
| Runtime 高风险工具过早开放 | 高 | 文件、进程、网络或数据库副作用 | 一个工作流一个 capability、审批和验证器 |
| RAG 语义反转干扰 | 中 | 高相似错误证据被放行 | 引用验证、错误集、后续语义蕴含评估 |
| 外部 Ollama 不可用 | 中 | 本地推理和 embedding 中断 | 明确错误码、模型检查、文档和 CPU fallback 边界 |
| 安装包 unsigned | 中 | SmartScreen 和用户信任问题 | 如实说明；取得证书后独立签名阶段 |
| 数据库测试争用/hang | 中 | 假失败、残留进程 | 独立测试库或串行执行、超时清理 |
| 文档状态再次漂移 | 中 | 其他 AI 重复或遗漏任务 | 机器报告优先，文档记录 commit 和校准日期 |

## 15. 每个工作包的交付模板

任何 AI 或开发者完成一个工作包时必须提交以下内容：

1. 目标和非目标。
2. 修改文件列表。
3. 数据库、`.env`、外部服务和用户数据影响。
4. 实际执行命令及退出码。
5. 测试数量、失败、跳过、耗时和运行环境。
6. 安装版、测试库、mock 和真实服务证据分别标注。
7. 回滚方法及是否需要数据恢复。
8. 未完成边界和已知错误案例。
9. 证据绑定的 Git commit、版本和 schema。
10. 是否允许进入下一阶段的明确结论。

禁止只写“已完成”“测试通过”而没有可复核数据。

## 16. 近期执行清单

建议严格按以下顺序开始：

1. 核对最新公开 Release，确定真实升级来源。
2. 将当前候选版本统一改为 `0.2.1`。
3. 修正现有剩余计划、部署指南和 release checklist 中的 `0020/0021` 及状态冲突。
4. 冻结 `0.2.1` 功能范围并形成干净候选提交。
5. 串行运行数据库相关测试，执行当前 HEAD 的完整 14 项发布门禁。
6. 构建 `0.2.1` sidecar、NSIS、updater `.sig` 和报告。
7. 执行干净安装、真实升级、数据保留、回滚、卸载和签名负面验证。
8. 有发布权限时上传真实 GitHub Release；没有权限则停在本地候选状态。
9. 用安装版开始 Runtime 批 A 的 7–14 天观察窗口。
10. 达标后另立 `0.3.0` 任务开启 Chat Runtime 批 B。
11. 批 B 稳定后逐个接入代码、Shell、API、数据库和多步骤工作流。
12. legacy 归零一个发布周期后，使用独立版本退役旧链。

## 17. 项目阶段完成定义

### `0.2.1` 稳定化发布完成

- 当前候选 commit 的工程门禁全绿。
- schema `0021`、安装包、报告、manifest 和 updater 资产一致。
- 干净安装、升级、数据保留、回滚和负面签名验证通过。
- 安装版 Runtime 批 A smoke 通过。
- Windows-only、外部 Ollama、unsigned 等边界如实发布。

### `0.3.0` Runtime 默认接管完成

- 批 A 达到观察门槛。
- Chat Runtime 在安装版默认开启并完成稳定窗口。
- 摘要 worker 独立灰度通过。
- legacy 仍保留可回退，尚未提前删除。

### `0.4.0` 可信执行完成

- 至少一个非文件类真实工作流完整上线。
- 每个开放工作流均有固定 capability、审批、验证器、durable 事实和 E2E。
- 任意 Shell、任意 URL、任意 SQL 等无边界入口保持禁止。

### 外部能力或新平台完成

- 必须有真实凭据、真实网络、真实设备/平台和正式发布证据。
- mock、配置解析和本地镜像只能作为准备证据，不能替代生产验收。

## 18. 最终建议

项目接下来的第一目标不是继续增加功能，而是把当前成果发布成可复现、可升级、可回滚的 `0.2.1`。在这个稳定基线形成后，再用真实遥测推动 `0.3.0` Runtime 默认接管，并以逐工作流方式构建 `0.4.0` 的可信执行能力。MCP、远程 Provider、自动记忆、跨平台和正式签名都应保持条件性，只有在产品需求和外部资源到位后启动。
