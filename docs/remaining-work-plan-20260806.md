# PrivateAgent 剩余工作执行计划（M2 后校准版）

> 校准日期：2026-08-06  
> 当前版本：`0.2.0`  
> 当前 Git：`1258b8e`，本地 `main` 比 `origin/main` 领先 3 个提交  
> 适用范围：只处理 2026-08-06 核验后仍未完成的事项，不重复执行已经完成的数据库迁移、RAG 上线、Windows 升级 smoke 或 ICS 集成样板。

> **执行台账（2026-08-06 更新，随工作推进刷新）**：
> - **R0/R1 完成**：发布事实源收口（`release-check-<version>.json` 为机器事实源、manifest checklist 由报告生成）、
>   Ruff/compileall/cargo_test/sidecar_smoke 加入完整门禁（10 步扩至 14 步）、干净 HEAD `c4c1566` 重跑
>   `14 passed / 0 failed / 0 skipped / ok=true`、`worktree_dirty=false`、schema `0020`、manifest 与报告同 commit。
> - **R2.1 完成**：`rag-evidence-v1` 策略（阈值 `0.80`/单渠道 `0.85`，校准证据在
>   `data/rehearsals/rag-evidence-r2-20260806/`）；10 reviewed case 重跑 `abstention_rate=1.0`、
>   Recall/MRR/引用正确率保持 1.0、零误拒答；生产 `.env` 已授权开启 `PA_RAG_EVIDENCE_ENABLED=true`；
>   已知局限：语义反转类干扰（>0.88 双渠道）需语义级验证，已记录为错误案例。
> - **R2.2 完成**：Windows 交付模式定为**外部 Ollama 由用户管理**（用户决策）；`/health` 增加
>   `error_code`（`ollama_not_running`/`ollama_timeout`/`ollama_http_error`/`ollama_model_missing`）与
>   `missing_models`；`scripts/ollama_lifecycle_check.py` + 证据报告
>   （embed P50 87ms / P95 111ms，bge-m3 常驻 1.6 GB）；文档 `docs/ollama-lifecycle.md`。
> - **R3 部分完成**：取消清理修复（git/命令子进程 CancelledError 时 kill、grep to_thread stop_event
>   退让）、SSE 断线取消与 owner 监控 verify→shutdown 测试补齐、灰度逐项验证矩阵与兼容链退出提案
>   （`docs/agent-runtime-gray-verification.md`）；**生产开启任何 Runtime 开关仍待单独授权**，
>   跨版本遥测观察窗口未启动，provider tokenizer 口径对比未做。

## 1. 已完成且不得重复实施

以下事项已经有代码、运行状态或验收证据，本计划不再安排：

- 应用主库 `0012 → 0020` 正式迁移；当前实际 `alembic current` 为 `0020 (head)`。
- Versioned RAG 生产启用；indexing/retrieval 两个开关均为 `true`。
- 4 个 canonical 文档的 versioned 构建和 10 个 reviewed benchmark case。
- Agent Runtime、ToolSpec、审批、checkpoint、durable execution、ContextBuilder 和 RAG 引用验证的代码底座。
- ICS 本地日历集成样板，包括隐私预览、来源追踪、导入和撤销。
- `scripts/windows/updater-signature-verifier/target/` 构建产物清理；Git 跟踪数已为 0。
- Windows `0.1.2 → 0.2.0` 安装升级、数据保留、卸载/重装回滚和 updater 签名负面验证。
- Phase 8 形式验收清单 `14/14`。

保留边界：当前安装包没有 Authenticode 正式证书，已如实标记 `unsigned`；本地 updater 镜像验证不能冒充已部署 GitHub Release。

## 2. 当前未完成项总表

| 编号 | 工作包 | 当前状态 | 优先级 | 阻塞范围 |
|---|---|---:|---:|---|
| R0 | 发布事实源与文档收口 | 完成（2026-08-06） | P0 | 已解除 |
| R1 | 当前干净提交的完整发布门禁 | 完成（2026-08-06，`c4c1566`，14/0/0） | P0 | 已解除 |
| R2 | RAG 无答案拒答与 Ollama 生命周期 | 完成（2026-08-06；语义反转干扰为已知边界） | P1 | 质量风险已按授权处理 |
| R3 | Agent Runtime 灰度与兼容链退出 | 部分完成（取消清理/故障门禁/退出提案；生产开启与遥测窗口待授权） | P1 | 阻塞 Runtime 默认启用 |
| R4 | 领域级验证器 | 未完成 | P1 | 阻塞对应高风险工作流开放 |
| R5 | MCP 与远程 Provider 生产互操作 | 条件性、未启动 | P2 | 仅阻塞外部能力启用 |
| R6 | 跨平台、正式签名与桌面自动化 | 条件性、未启动 | P2 | 不阻塞 unsigned Windows 交付 |
| R7 | 记忆与更多集成增强 | 条件性、未启动 | P3 | 不阻塞当前版本 |

## 3. R0：发布事实源与文档收口

### 3.1 当前问题

仓库已经生成 `release-check-0.2.0.*`，但现有文档和产物仍存在以下冲突：

- `docs/remaining-work-plan.md` 的基线仍写“只有 0.1.2 报告”。
- `dist/release-manifest-0.2.0.md` 仍记录 `passed: 9 / failed: 1`，且 validation checklist 未勾选。
- 后生成的 `release-check-0.2.0.md` 记录 `10 passed / 0 failed`。
- `modernization-audit.md`、`migration-plan.md` 中保留大量历史 `0012` 叙述，部分缺少醒目的“历史切片”标记。
- 自动生成产物的生成顺序不明确，后生成报告不会自动同步旧 manifest。

### 3.2 执行任务

1. 明确唯一的当前发布事实源：建议以 `release-check-<version>.json` 为机器事实，manifest 只引用其摘要。
2. 调整生成流程：先完成完整 release check，再生成或刷新 release manifest，避免 manifest 固化旧结果。
3. 让 manifest checklist 由真实步骤结果生成；不要人工勾选制造完成状态。
4. 在设计/审计文档中增加统一标记：
   - `当前状态（2026-08-06）`
   - `历史执行台账（不得当作当前状态）`
5. 更新旧计划书顶部状态，明确 M0/M2 已完成、M1 仍需干净提交重跑。
6. 保留历史报告，不覆盖或改写历史数字；只修正其解释和当前引用关系。

### 3.3 验收标准

- README、CHANGELOG、release manifest、testing guide、database/RAG/Agent 文档对当前 commit、schema、开关和发布状态描述一致。
- 当前状态搜索不会把历史 `0012`、未上线 RAG 或旧 9/1 报告误判成现状。
- manifest 与 release report 的 passed/failed/skipped、commit、schema、签名状态一致。
- 文档变更通过 `git diff --check`，不包含凭据或业务正文。

## 4. R1：当前干净提交的完整发布门禁

### 4.1 当前问题

现有 `release-check-0.2.0` 虽然显示 `10 passed / 0 failed / 0 skipped` 和 `535 passed`，但不能作为最终 HEAD 的完整证据：

- 报告绑定 commit `dcac141`，当前 HEAD 为 `1258b8e`。
- 报告记录 `worktree_dirty: True`。
- 报告生成时间早于 M0、M1、M2 三个提交。
- 当前 runner 没有独立的 Ruff 和 compileall 步骤，而本计划和测试指南把它们列入门禁。
- release manifest 仍保留旧的 9/1 摘要。

### 4.2 执行任务

1. 决定 Ruff/compileall 的正式门禁口径：
   - 推荐把 `ruff check` 和 `python -m compileall` 加入 full runner；
   - 若明确不作为发布门禁，必须同步修改测试指南和本计划，不能文档要求但 runner 不执行。
2. 确保开始门禁前工作区干净；报告生成目录应被忽略，不使源码工作区变脏。
3. 在允许 Node、Python、Git、Rust 和 MCP fixture 创建子进程的 Windows 发布环境运行完整检查。
4. 覆盖至少：
   - Python 全量测试；
   - Ruff/compileall（若保留为正式门禁）；
   - Vue TypeScript/Vite build；
   - Vitest；
   - Playwright；
   - Rust test/check；
   - sidecar smoke；
   - Alembic current；
   - Docker Compose 配置；
   - 诊断脱敏；
   - updater/latest.json 校验；
   - `git diff --check`。
5. 重新生成 `release-check-0.2.0.json/.md`，然后由该报告刷新 release manifest。
6. 校验报告和 manifest 不包含 token、API key、密码、DSN、聊天全文或文档正文。

### 4.3 验收标准

最终机器报告至少满足：

```text
commit.short = 1258b8e 或其后明确提交
commit.dirty = false
database_schema = 0020
failed = 0
skipped = 0
ok = true
```

如果为完成 R0/R1 又产生新提交，应以最终新 HEAD 再跑，不能继续接受 `dcac141` 报告。

附加标准：

- release manifest 引用同一 commit 和同一报告摘要。
- 强制步骤缺失必须失败；条件性平台/证书项应标记 unsupported/unsigned，而不是伪装 passed。
- 本地分支若要成为团队交付基线，需要用户授权后推送；当前 `ahead 3` 不等于远端已交付。

## 5. R2：RAG 无答案拒答与 Ollama 生命周期

### 5.1 无答案拒答

当前检索质量门禁已经通过，但 reviewed benchmark 的 `abstention_rate=0.0`。越界问题仍可能获得 top-k 结果，生产提示词只能降低风险，不能替代检索层判断。

任务：

1. 收集向量相似度、rerank、RRF、BM25 和命中渠道在已知答案/无答案 case 上的分布。
2. 设计可配置、可解释的“证据不足”策略；不同检索器的原始分数不可直接共用一个阈值。
3. 证据不足时返回空来源和结构化原因，由回答层明确说明资料不足。
4. 严格保持 collection/document 过滤，防止用其他知识库的弱相关结果填补空答案。
5. 增加无答案、近似干扰、短 query、多语言、只有关键词命中和只有向量命中测试。
6. 重新运行 10 个 reviewed case，并扩充人工复核的拒答 case。

验收标准：

- 无答案 case 能稳定拒答；拒答不生成伪引用。
- 已知答案 case 的 Recall/MRR/引用正确率不低于批准阈值。
- 报告记录策略版本、阈值、分数分布和错误案例。
- 阈值可配置并有安全默认值，不能只写死在提示词。

### 5.2 Ollama 生命周期

当前可通过直接 `ollama serve` 运行，但旧 Desktop wrapper 曾出现 `0xC0000142`。需要选择并验收一种正式生命周期，而不是混用外部应用、临时 CLI 和容器假设。

任务：

1. 明确 Windows 交付模式：
   - 外部 Ollama 由用户管理；或
   - PrivateAgent 托管 CLI 服务；或
   - 容器 GPU profile。
2. 对选定模式验证安装检测、启动、模型缺失、预热、健康、崩溃、重启、退出和升级。
3. 明确 CPU fallback 行为和用户可读错误；不能在 GPU 不可用时静默挂起。
4. 若选择 Docker GPU profile，真实拉取镜像和模型，验证 GPU 可见性、offload、持久卷、healthcheck 和清理。
5. 记录冷/热启动时间、embedding P95 和模型常驻行为。

验收标准：

- 用户按照文档可重复启动，不依赖遗留手工后台进程。
- 失败时诊断页能区分服务未启动、模型缺失、GPU 不可用和请求超时。
- 选定模式有启动/退出残留检查和可复现证据。

## 6. R3：Agent Runtime 灰度与兼容链退出

### 6.1 边界

Runtime 代码底座已经完成；本工作包只做灰度、故障门禁、运维证据和旧链退出，不另建第二套 Agent 循环。

当前生产 `.env` 未设置 Agent/Chat/Context/Verification/Summary/MCP 开关，因此它们继续使用默认 `false`。

### 6.2 灰度顺序

建议在隔离环境按以下顺序开启：

1. Agent Runs API，无工具；
2. 只读 safe 工具；
3. confirm 文件读取和审批恢复；
4. ContextBuilder；
5. 非空输出验证；
6. RAG 工具与引用验证；
7. Chat Agent Runtime 接管；
8. 自动摘要 worker（独立灰度，不与聊天接管同批开启）。

每一步必须独立验证并可通过关闭单个 feature flag 回退。

### 6.3 故障与兼容任务

- owner lock 丢失、第二进程竞争和数据库断连。
- API 退出、孤儿 run、已有取消意图和 waiting approval checkpoint。
- 幂等 execution 回放与非幂等 unknown 状态。
- 审批 token 轮换、一次消费、拒绝和过期。
- SSE 断线、并发 continuation 和唯一 assistant message 投影。
- `grep_code` 线程、Git/legacy 子进程的取消和退出清理。
- provider 精确 tokenizer 与旧聊天预算口径评估。
- compatibility telemetry 的跨版本观察窗口。

### 6.4 旧链退出标准

只有同时满足以下条件才提案删除 `/tools`、`/tools/plan` 或旧 tool-call 端点：

- Runtime 模式的新桌面消息 planner 调用稳定为 0。
- 一个批准的跨版本观察窗口内 legacy 调用为 0。
- 历史 pending 调用已耗尽、迁移或有明确人工处置方案。
- 回滚版本不再依赖旧端点，或删除与最低支持版本同步。
- 删除是独立变更，可单独回滚，不与默认开启 Runtime 同一提交完成。

## 7. R4：领域级验证器

当前已有非空、JSON Schema、组合和 RAG 引用验证。新增验证器必须由真实工作流需求驱动。

### 7.1 推荐实施顺序

1. **文件 Diff 验证器**：复用现有 old SHA、diff 和回读事实，风险低且调用方明确。
2. **代码验证器**：白名单测试、编译、Lint、类型检查命令及结构化结果。
3. **Shell 验证器**：退出码、stderr、超时、截断和取消状态。
4. **API 验证器**：状态码、固定响应 Schema、重试和幂等边界。
5. **数据库验证器**：事务提交、约束、影响行和读回验证。
6. **多步骤完成条件**：由具体 workflow 的可信调用方定义，不提供模型可自由填写的“完成”字段。

### 7.2 通用约束

- 验证器由可信代码固定，模型不能选择验证器或自行宣称通过。
- 验证器本身不能增加 capability、消费审批或执行未审批副作用。
- 验证失败只能产生有界反馈和受控重试。
- 事件写入 durable run 事实，但不保存秘密、完整文件或无界 stderr。
- 每个验证器必须同时覆盖成功、失败、超时、取消、重试耗尽和恢复路径。

### 7.3 验收标准

- 每个验证器至少有一个真实调用工作流和端到端测试。
- UI 展示公开验证结果，不展示模型隐式推理。
- 关闭验证器或工作流 feature flag 不要求数据库 downgrade。

## 8. R5：MCP 与远程 Provider（条件性）

只有用户决定启用真实外部服务并提供授权环境时才执行。

### MCP

- OAuth discovery、device flow、refresh、过期和撤销。
- 具体第三方服务的 TLS、证书、限流、错误语义和兼容测试。
- 企业代理、证书 pinning 和宿主出口 ACL。
- 多客户端附着同一 run 仅在有真实调用者时设计。

在完成前保持 `PA_MCP_ENABLED=false`。当前没有外部客户端需求，不实现 PrivateAgent MCP Server。

### OpenAI/Claude

- 使用用户明确提供的凭据完成真实流式、工具调用、Structured Output、取消和错误 smoke。
- 验证隐私预览、远程调用审计、敏感上下文排除和首个 delta 后不重试。
- 没有真实授权环境时只保留 MockTransport 合同证据，不得写成真实端点已验收。

## 9. R6：跨平台、正式签名与桌面自动化（条件性）

- Authenticode 正式实签：只有取得发布证书后执行；此前保持 unsigned 和 SmartScreen 风险说明。
- GitHub Release updater：需要仓库发布权限后，以真实远程资产补一次更新 smoke；当前本地镜像证据继续保留但不冒充远程发布。
- macOS/Linux：决定正式支持后再完成 sidecar/Tauri 构建、首启、依赖、签名/公证和 smoke。
- Tauri 窗口级 E2E：当前浏览器 Playwright 和 sidecar smoke 已存在；可另立自动化增强任务覆盖真实 WebView、原生凭据窗口和退出清理。
- Docker Ollama GPU 已归入 R2；未做真实 GPU healthcheck 前不得宣称容器 GPU 交付完成。

这些项目不阻塞如实标记 unsigned、Windows-only 的 `0.2.0` 交付。

## 10. R7：记忆与更多集成（条件性）

- 记忆专用版本化向量 head：数据规模或检索质量证明 MySQL/现有召回不足后再做。
- 自动长期记忆写入：先建立误写率、敏感分类、撤销体验和用户确认门禁；当前 candidate/显式确认链保持默认。
- 批量恢复/合并 UI：出现真实批量操作需求后实施。
- 更多集成：ICS 首个样板已完成；邮件、浏览器、文件夹监听等必须分别做隐私预览、只读边界、来源追踪和撤销。
- LangGraph/多 Agent：只有当前状态机无法表达真实分支、并行汇合或跨主体权限时再评估。

## 11. 执行顺序

推荐顺序：

1. **先做 R0。** 修正事实源和生成顺序，避免后续报告继续互相冲突。
2. **立即做 R1。** 以最终干净 HEAD 重跑完整门禁；R0/R1 若产生新 commit，则再跑一次绑定最终 commit。
3. **R2 与 R3 可并行研发。** 任一代码变化进入发布候选后必须重新执行 R1。
4. **R4 按验证器逐个交付。** 不等待所有验证器一起完成。
5. **R5–R7 等待用户产品决策或真实外部环境。** 不自动扩大任务范围。

依赖关系：

```text
R0 → R1 → Windows 0.2.0 最终放行
R2 ─────┘（若纳入本次候选）

R3 → Runtime 默认启用
R4 ─────┘（按开放工作流匹配）

用户授权/真实环境 → R5 / R6 / R7
```

## 12. 分工建议

| 工作单元 | 负责范围 | 交付物 |
|---|---|---|
| Release | R0、R1 | 当前 commit 绑定报告、同步 manifest、文档一致性 |
| RAG/Ollama | R2 | 拒答策略、评测报告、正式 Ollama 生命周期证据 |
| Runtime | R3 | 灰度报告、故障注入、兼容遥测和旧链退出提案 |
| Verification | R4 | 逐领域 verifier、真实工作流和端到端测试 |
| External | R5、R6 | 真实服务/平台/签名证据；无授权则保持 blocked |
| Memory/Integration | R7 | 经产品需求批准的独立增强切片 |

## 13. 通用安全与报告要求

- 当前主库已经是 `0020`；任何新生产写入、删除、feature flag 开启或 downgrade 仍需单独明确授权。
- 不触碰回滚克隆 `personal_assistant_preupgrade_20260805111304`。
- 不删除历史 `diagnostic_runs` 36、37，除非取得精确生产数据删除授权。
- 测试使用守卫后的测试库、隔离 clone、临时目录或本地 mock 服务。
- 不提交 `.env`、token、API key、数据库密码、PFX、updater 私钥或业务正文。
- 不使用 `git reset --hard`、覆盖用户改动或批量清理不明目录。
- 每个工作包必须报告：修改文件、运行命令、测试结果、数据库影响、外部状态变化、回滚方法和未完成边界。
- 测试失败、报告绑定旧 commit、工作区 dirty 或缺少真实环境时，不得标记为完成。

## 14. 完成定义

### 当前 Windows `0.2.0` 最终放行

必须完成 R0、R1，并保留已完成的 M2 证据。最终 report/manifest 必须绑定同一个干净 HEAD，schema 为 `0020`，强制门禁零失败、零跳过，签名状态如实记录。

### Agent Runtime 默认启用

必须完成 R3；开放文件写入、Shell、API 或数据库工作流时，还必须完成对应的 R4 验证器。兼容链删除需要独立遥测观察和回滚计划。

### 外部能力或新平台启用

必须完成对应 R5/R6 的真实凭据、网络、平台和发布验收；不能用本地 mock、配置解析或文档准备替代真实能力声明。

