# PrivateAgent 剩余工作执行计划

> 校准日期：2026-08-05  
> 适用版本：`0.2.0` / Git `dcac141`  
> 目的：只规划当前实际未完成的工作；已完成的数据库迁移、RAG 上线和本地集成样板不重复实施。

> **历史执行台账（不得当作当前状态）**：本文的里程碑进度、`dist/` 报告状态和基线描述只代表 2026-08-05 校准时点。2026-08-06 起本计划已被
> `docs/archive/planning/remaining-work-plan-20260806.md` 接管：M0（a0305cf、「当前状态」统一、`target/` 产物清理）与 M2（1258b8e、真实 Windows 升级与签名负面验证）已完成；
> M1 部分完成但报告绑定 `dcac141` 且 `worktree_dirty=True`，需要在最终干净 HEAD 以 `scripts/release-check-full.bat` 重跑并刷新 manifest 后才算正式放行。
> 当前状态（主库 `0020`、versioned RAG 已启用、Agent Runtime 等开关默认关闭）以各设计/审计文档顶部「当前状态（2026-08-06）」为准。

## 1. 校准结论

对照当前代码、运行配置、数据库 revision、验收清单和现有报告后，上一版计划需要做以下修正：

1. **删除“执行主库 `0012 → 0020` 迁移”任务。** 当前环境只读核验 `alembic current` 为 `0020 (head)`，迁移和回滚克隆已经完成。
2. **删除“完成 versioned RAG 生产上线”任务。** `PA_VERSIONED_RAG_INDEXING_ENABLED=true`、`PA_VERSIONED_RAG_RETRIEVAL_ENABLED=true` 已生效；4 个 canonical 文档已构建，最新 10 个 reviewed case 的 rollout gate 已通过。
3. **删除“实现首个本地集成样板”任务。** ICS 本地日历导入已经覆盖隐私预览、来源追踪、导入和撤销，并有 API、前端和测试。
4. **把 macOS/Linux、MCP OAuth、语义记忆向量化改为条件性工作。** 它们不阻塞当前 Windows 交付，只有决定支持对应平台或真实外部服务时才进入承诺范围。
5. **把 Agent Runtime 从“继续开发”改为“灰度启用与运维验收”。** Runtime、审批、checkpoint、恢复和持久化执行已经实现；当前缺的是生产开关、故障注入和兼容链退出证据。
6. **补入两个实际遗漏项。** 当前没有对应 `0.2.0` 最新源码的完整 release report；仓库还跟踪了 62 个 `scripts/windows/updater-signature-verifier/target/` Rust 构建产物，需要清理并防止再次提交。

## 2. 当前可信基线

| 项目 | 当前状态 | 证据/边界 |
|---|---|---|
| Git | 校准前工作区干净，`dcac141` | 本计划文件是校准后的唯一新增项 |
| 主库 schema | `0020 (head)` | 已通过实际 `alembic current` 只读核验 |
| Versioned RAG | 已生产启用 | indexing/retrieval 两个环境开关均为 `true` |
| RAG 数据 | 4 heads / 4 chunks / 4 vectors | 10 个 reviewed case；Recall/MRR/引用正确率均为 1.0 |
| RAG 已知局限 | 无答案拒答不足 | `abstention_rate=0.0`，当前没有召回相关性阈值 |
| Agent Runtime | 代码完成、生产默认关闭 | Agent/Chat/Context/Verification 开关未写入生产 `.env`，沿用默认 `false` |
| MCP | Client 代码完成、默认关闭 | 静态认证已验证；OAuth/第三方生产验收未完成 |
| Phase 8 | `14/14` | 真实 Windows `vN → vN+1` 升级 smoke 已通过（2026-08-05，run #26） |
| 发布报告 | 不足 | `dist/` 只有 2026-08-03 的 `release-check-0.1.2.*`，早于当前源码 |
| 平台 | Windows 为正式目标 | macOS/Linux 有脚本和文档，但未实机构建/smoke |

## 3. 优先级与里程碑

| 里程碑 | 目标 | 是否阻塞 Windows `0.2.0` 发布 |
|---|---|---:|
| M0 | 修正事实源、清理仓库发布卫生 | 是 |
| M1 | 生成当前源码完整发布证据 | 是 |
| M2 | 完成 Windows 真实升级与签名状态验收 | 是 |
| M3 | RAG 拒答与 Ollama 生命周期加固 | 建议发布前完成；可由风险接受决定 |
| M4 | Agent Runtime 灰度、故障门禁和旧链退出 | 阻塞 Runtime 默认启用，不阻塞 legacy 模式发布 |
| M5 | 领域验证器 | 阻塞对应高风险工作流开放，不阻塞只读 Agent |
| M6 | MCP/远程 Provider 生产互操作 | 仅阻塞对应外部能力启用 |
| M7 | 跨平台、记忆增强和更多集成 | 条件性后续，不阻塞 Windows 发布 |

## 4. M0：事实源与仓库卫生

### 4.1 统一文档当前状态

当前部分文档同时保留“主库仍为 `0012`”的历史描述和“主库已为 `0020`”的当前描述，容易让后续执行者错误重复迁移。

任务：

- 在 `agent-runtime.md`、`modernization-audit.md`、`migration-plan.md`、`database-design.md`、`testing-guide.md` 中区分“历史切片状态”和“当前状态”。
- 所有顶部状态摘要统一为：主库 `0020`、versioned RAG 已启用、Agent Runtime/MCP/自动摘要仍默认关闭。
- 历史数字允许保留，但必须明确标注日期和“历史证据”，不能继续写成当前结论。
- 修正 release report、Python 测试定义数和实际执行数之间的口径说明。

验收标准：

- 搜索当前状态文档时，不再出现互相冲突的主库 revision 或 rollout 结论。
- `README`、`CHANGELOG`、部署、数据库、RAG、测试五个入口给出一致状态。

### 4.2 清理已跟踪构建产物

当前 Git 跟踪了 62 个 `scripts/windows/updater-signature-verifier/target/` 文件。这些是 Cargo 可再生成产物，不应进入源码提交。

任务：

- 确认签名验证器真正需要提交的只有源码、`Cargo.toml` 和锁文件。
- 从 Git 跟踪中移除 `target/` 构建产物，不删除任何不可再生成的发布资产。
- 在 `.gitignore` 增加精确规则 `scripts/windows/updater-signature-verifier/target/`。
- 运行签名验证器的 Rust test/build，证明清理后可以重新生成。

验收标准：

- `git ls-files scripts/windows/updater-signature-verifier/target/**` 返回 0。
- Rust 测试和发布检查中的 updater 签名结构验证通过。

## 5. M1：当前源码完整发布门禁

现有 `release-check-0.1.2` 报告早于当前 Agent Runtime、RAG ToolSpec、输出验证、单执行链和 `0.2.0` 提交，不能作为当前发布结论。

任务：

1. 在允许 Node、Git、Python 和 MCP fixture 创建子进程的 Windows 发布环境运行完整门禁。
2. 覆盖 Python 全量、Ruff、compileall、Vitest、Playwright、Vue build、Rust test/check、sidecar smoke、Alembic current、诊断脱敏、Docker Compose、updater manifest。
3. 对历史 `WinError 5` 用例区分“产品失败”和“沙箱禁止子进程”；发布环境不得保留失败或 deselected 后伪装全绿。
4. 生成 `dist/release-check-0.2.0.json` 与 `.md`，记录代码 commit、schema、测试摘要、签名状态和各步骤耗时。

验收标准：

- 新报告与 `dcac141` 或其后明确提交绑定。
- 强制步骤 `0 failed / 0 skipped`；有条件步骤必须给出明确、可审计的 blocked/unsupported，而不是静默跳过。
- 发布报告不包含 token、密码、DSN、聊天正文或文档原文。

## 6. M2：Windows 真实升级与签名验收

这是 Phase 8 唯一未勾选的硬验收。

任务：

1. ✓ 构建并保留两个真实版本资产：官方 `0.1.2`（备份于 `dist/upgrade-smoke/0.1.2/`）与自构建 `0.2.0`（`dist/upgrade-smoke/0.2.0/`，含 `.sig` + `latest.json`）。
2. ✓ 在真实 Windows 环境安装旧版，创建非敏感 smoke 数据：`--generate-sample` 生成会话/文档/任务/收件箱等 10 表样本，前后快照 `before.json`/`after.json`。
3. ✓ 通过真实安装包执行 `v0.1.2 → v0.2.0`（了解 NSIS 就地升级，未被数据库迁移替代）；另用本地更新源跑通应用内 updater 完整链路（`check`→`download`→签名验证→安装→重启）。
4. ✓ 验证 sidecar/动态端口、凭据引用 keyring、schema `0020 (head)`、数据保留（`--verify preserved=true`，10 表全部 `lost=false`）、聊天/RAG 健康。
5. ✓ 升级失败与回滚 runbook：卸载 `0.2.0` 后数据目录保留，重装 `0.1.2` 恢复健康，再升级回 `0.2.0`。
6. ✓ 无 Authenticode 证书，release manifest 与 `unsigned-note-0.2.0.md`/`codesign-status-0.2.0.json` 如实标注 `unsigned`；updater 签名用 `private-agent-updater-signature-verifier.exe` 正向校验 `OK`。

验收标准：

- ✓ `scripts/upgrade_smoke.py` 有真实成功记录：run #26（`0.1.2 -> 0.2.0 result=passed`，`data_preserved=true`、`schema_ok=true`）。
- ✓ 产生版本、安装、升级、数据前后校验和回滚证据（记录于 run #26 notes、`dist/upgrade-smoke/`、本段）。
- ✓ Phase 8 第 14 项由证据勾选（2026-08-05，`docs/archive/phases/phase8-requirements.md`）。

已完成的边界（如实记录）：

- 应用内 updater 负面测试：`latest.json` 篡改（版本 0.2.1 + 注释区/signature 字节翻转）在下载后验证失败，弹出“更新签名验证失败…已拒绝更新”，安装器未运行、版本仍 `0.2.0`、进程未重启；篡改 untrusted comment 区域不触发拒绝（minisign 设计上不覆盖该注释），仅篡改 signature/文件字节才会被拒。
- 未部署 GitHub Release 真实远程源（需持有 GitHub 仓库写权限）；本地 `127.0.0.1:8736` 镜像源按任务文本许可用于补齐 updater 链路证据。`tauri.conf.json` 生产端点已回退为 GitHub。
- 无 Authenticode 证书，SmartScreen 风险已在发布说明如实标注。

## 7. M3：RAG 与 Ollama 运行质量加固

### 7.1 无答案拒答

当前 10 个 reviewed case 的质量门禁已通过，但无答案 case 仍返回 top-k，`abstention_rate=0.0`。这不是重新上线 RAG，而是上线后的质量加固。

任务：

- 设计可配置、可评测的最低相关性策略；不要直接用不同检索器不可比的原始分数硬切。
- 综合向量相似度、RRF、rerank 和命中渠道生成可解释的“证据不足”判断。
- 证据不足时返回空来源/明确拒答，不生成看似可信的引用。
- 增加无答案、近似干扰、跨 collection、短 query 和多语言回归。
- 重新运行 reviewed benchmark，并把 abstention 作为正式或明确观察门禁。

验收标准：

- 无答案 case 能稳定拒答，且已知答案 case 的 Recall/MRR/引用正确率不回退到批准阈值以下。
- 阈值和决策依据进入报告，不只写提示词。

### 7.2 Ollama 生命周期

当前可通过直接 `ollama serve` 运行，但旧 Desktop wrapper 曾出现 `0xC0000142`；临时手工后台进程不等于稳定部署。

任务：

- 明确桌面安装版是依赖外部 Ollama、托管 CLI 服务，还是使用容器 GPU profile；三种模式不能混用生命周期假设。
- 验证启动、模型缺失、预热、崩溃、重启、退出和 CPU/GPU fallback。
- 可选 Docker GPU profile 需真实拉取镜像、模型并执行 GPU healthcheck，当前仅配置解析通过。

验收标准：

- 选定交付模式具有可重复启动和故障诊断证据。
- 不能把一次手工 `ollama serve` 评测当作产品生命周期完成。

## 8. M4：Agent Runtime 灰度与旧链退出

Runtime 的实现已经完成，本里程碑不再重写第二套框架。

任务：

1. 在隔离环境按顺序开启 Agent API、只读工具、ContextBuilder、输出验证、RAG 工具和聊天接管。
2. 验证 owner lock 丢失、API 进程退出、孤儿 run、审批恢复、幂等 execution、非幂等 unknown、取消和并发 continuation。
3. 对 `grep_code` 线程任务、Git/legacy 子进程补强取消与退出清理；不可强取消的工具必须继续明确声明并丢弃迟到结果。
4. 评估 provider 精确 tokenizer，并避免旧聊天与 Runtime 使用互相矛盾的预算口径。
5. 用 compatibility telemetry 观察 `/tools`、`/tools/plan`、旧 approve/reject 和旧 tool-call 查询。
6. 只有跨版本观察窗口归零后，才单独提案删除旧链；历史 pending 调用在删除前必须耗尽或迁移。

验收标准：

- Runtime 模式的新消息只走 `/chat/stream`，旧 planner 调用为 0。
- 不重复执行工具、不重复插入 assistant message、不泄露原始审批 token。
- feature flag 可以独立回退；关闭 Runtime 不要求 schema downgrade。
- 旧端点删除必须有遥测证据，不能仅凭“新前端已更新”判断无人使用。

## 9. M5：领域验证器

当前已有非空、JSON Schema、组合和 RAG 引用验证。下列验证器只在对应工作流准备开放时实施，不应一次性创建没有调用方的抽象：

- 代码工作流：测试、编译、Lint、类型检查结果。
- 文件变更：旧内容 SHA、结构化 diff、应用结果和回读。
- Shell：退出码、stderr、超时、输出上限和取消状态。
- API：状态码、响应 Schema、幂等/重试边界。
- 数据库：事务提交结果、约束和读回验证。
- 多步骤任务：由可信调用方定义完成条件。

统一验收标准：

- 验证器由可信代码固定，模型不能自行选择或宣称通过。
- 验证失败只生成有界反馈和受控重试，不能增加 capability、消费审批或绕过安全策略。
- 验证事件进入 durable run 事实，错误中不回显敏感输入。

## 10. M6：MCP 与远程 Provider（条件性）

只有用户决定启用真实外部服务并提供授权环境时才启动本里程碑。

### MCP

- OAuth discovery、device flow、refresh、过期和撤销生命周期。
- 具体第三方服务的证书、限流、错误语义和互操作。
- 企业代理、证书 pinning 和宿主出口 ACL。
- 多客户端同时附着同一 run 只有出现真实需求时再设计。

在完成前保持 `PA_MCP_ENABLED=false`。当前没有外部客户端需求，因此不实现本应用 MCP Server。

### OpenAI/Claude

- 使用用户明确提供的授权环境执行真实流式、工具调用、Structured Output、取消和错误 smoke。
- 验证隐私预览、远程审计和首个 delta 后不重试。
- 没有真实 key 时只保留 MockTransport 合同证据，不得写成真实 Provider 已验收。

## 11. M7：条件性产品扩展

下列事项不属于当前 Windows `0.2.0` 发布阻塞：

- macOS/Linux 实机构建、签名、公证、依赖和 smoke；决定正式支持平台后再立项。
- Tauri 窗口级 E2E；当前已有浏览器 Playwright 和 sidecar smoke，可作为桌面自动化增强单独推进。
- 记忆专用版本化向量 head；数据量或召回需求达到阈值后再实现。
- 自动长期记忆写入；必须先有误写率、敏感分类、撤销体验和用户确认门禁。
- 记忆批量恢复/合并 UI；出现真实批量操作需求后再做。
- 更多本地集成类型；ICS 样板已经完成，不得把“增加日历/邮件/浏览器”等描述成首个样板仍缺失。
- LangGraph、多 Agent；只有现有状态机无法表达真实分支/并行/恢复需求时再评估。

## 12. 执行顺序与并行分工

推荐顺序：

1. **先完成 M0**，保证后续 AI 读取的是一致事实，并清理发布仓库。
2. **M1 与 M2 并行准备**；M2 使用 M1 生成的候选资产和报告。
3. **M3 可与 M1 并行开发**，但阈值变更进入候选版本后必须重新跑 M1。
4. **M4 单独灰度**，不与 Windows 安装升级同时切换默认执行框架，避免定位困难。
5. **M5 按具体工作流逐个交付**。
6. **M6/M7 由用户产品决策触发**，不自动扩张范围。

建议分工：

| 工作单元 | 范围 | 禁止事项 |
|---|---|---|
| Release | M0、M1、M2 | 不修改生产业务数据；不伪造签名/升级证据 |
| RAG/Ollama | M3 | 不重做已完成的 schema 迁移；不直接删除重复文档 |
| Runtime | M4、M5 | 不创建第二套 Agent 循环；不无证据删除兼容端点 |
| Integrations | M6 | 无凭据时不声称真实互操作；MCP 默认关闭 |
| Platform/Memory | M7 | 不阻塞 Windows 发布；不默认启用自动记忆 |

## 13. 通用安全约束

- 当前主库已经是 `0020`；任何新生产写入、feature flag 开启、删除或 downgrade 仍需单独明确授权。
- 保留回滚克隆 `personal_assistant_preupgrade_20260805111304`，不得由测试或清理脚本触碰。
- 主库历史 `diagnostic_runs` 36、37 是保留的审计记录；没有删除授权时不得清理。
- 测试必须使用守卫后的测试库、隔离 clone、临时目录或 mock 服务。
- 不提交 `.env`、token、API key、PFX、updater 私钥、数据库密码或文档正文。
- 每个工作包必须记录修改文件、实际命令、测试结果、数据库影响、回滚方法和未完成边界。
- 测试失败、真实环境缺失或证据过期时，不得把阶段标记为完成。

## 14. 总体验收定义

### Windows `0.2.0` 可发布

必须同时满足：

- M0 完成；
- 当前源码完整 release report 通过；
- Windows 真实 `vN → vN+1` 升级 smoke 通过；
- 签名状态真实记录；
- 数据、凭据引用、sidecar、RAG 和回滚证据完整。

### Agent Runtime 可默认启用

必须同时满足：

- M4 灰度和故障注入通过；
- 对应开放工作流的 M5 验证器到位；
- 兼容遥测证明没有双 planner/双执行；
- feature flag 回退演练通过。

### 外部能力可启用

- MCP 或远程 Provider 必须分别完成 M6 的真实服务、凭据、网络和隐私验收；不能由本地 mock 测试替代。
