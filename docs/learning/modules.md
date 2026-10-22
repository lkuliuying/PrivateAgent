# PrivateAgent 模块实现卡

这 20 张卡按功能边界组织当前实现。先沿“入口 → 状态 → 外部作用 → 失败处理”阅读，每张卡都要结合测试解释一个成功路径和一个失败路径。

## 模块地图

| 模块 | 学习日 | 主要职责 |
| --- | --- | --- |
| M01 工作台与事件投影 | D02、D13、D26 | 交互、选择状态、事件展示和组件生命周期 |
| M02 桌面启动与私有 IPC | D03、D26 | 子进程、请求传输、凭据和更新边界 |
| M03 API 与身份作用域 | D03、D04 | 请求校验、身份空间及实体绑定 |
| M04 SQLite 与历史持久化 | D04 | 事务、事件、迁移、历史和所有者锁 |
| M05 模型协议与适配 | D05 | 模型选择、能力、消息、流式协议和用量 |
| M06 Agent 循环与本机适配 | D06 | 模型与工具循环、限额、取消和事件接口 |
| M07 任务解释与执行限制 | D08 | 来源、路径、条件、禁止项和完成要求 |
| M08 计划与运行控制 | D08、D13 | 计划版本、追加要求、暂停、继续和进展 |
| M09 工具契约与按需发现 | D09 | 注册、暴露、schema、路由和工具搜索 |
| M10 文件搜索与补丁 | D10 | 读取版本、分页、补丁预览、落盘和回滚 |
| M11 权限与系统沙箱 | D11 | 审批策略、路径和 AppContainer 隔离 |
| M12 命令宿主与持续执行 | D12 | 进程会话、输出、stdin、退出与回收 |
| M13 规则与上下文管理 | D15、D16 | 可信规则、预算、压缩、归档和原文续读 |
| M14 长期记忆 | D17 | 来源、提取、召回、冲突、管理和遗忘 |
| M15 任务恢复 | D18 | 检查点、租约、版本、预算和未知副作用 |
| M16 完成验证与纠错观察 | D19、D20 | 机器证据、结构化输出、失败循环和公开观察 |
| M17 Skills 与 MCP | D22 | 技能加载、服务库、项目绑定、工具权限和认证 |
| M18 网页与浏览器检查 | D22 | 公共网页读取、本机预览和证据记录 |
| M19 草稿附件与数据恢复 | D23、D24 | 草稿、队列、材料、模型保存与备份恢复 |
| M20 Git 工作区与交接 | D25 | Git 基线、worktree、审阅、冲突和任务搜索 |

## M01 工作台与事件投影

**职责：**把用户目标和运行事件转成可操作、可恢复的工作台。

**调用与依赖：**[CodingComposer](../../apps/desktop/src/features/coding/components/CodingComposer.vue)向[任务页](../../apps/desktop/src/features/coding/components/CodingThreadWorkspace.vue)提交输入；任务页使用[工作台 store](../../apps/desktop/src/features/coding/model/codingWorkspaceStore.ts)提供的选择状态，调用[useRunStream](../../apps/desktop/src/features/coding/composables/useRunStream.ts)管理当前运行，再由[runProjector](../../apps/desktop/src/features/coding/model/runProjector.ts)派生展示状态。

**输入输出：**输入包括正文、权限、模型、附件和运行事件；输出为运行投影、审批、过程记录和最终结果。前端显示依赖后端事实及能力声明。

**状态与持久化：**工作台 store 是模块级响应式状态，不能笼统称为 Pinia store。当前连接、投影和定时器在前端；持久草稿和后端运行记录另有持久化路径。

**实现过程：**

1. 工作台加载项目、工作区、任务和模型，用请求序号防止迟到加载覆盖当前选择。
2. 创建运行使用稳定请求标识；响应丢失时按标识查询并核对正文、附件。
3. 断线后获取快照、补读事件缺口、恢复流；投影按序号去重，旧版本不覆盖新事实。
4. 切换任务或销毁作用域递增前端代次，并清理流和重连定时器。

**失败处理：**连接失败保留可恢复输入；流断开不自动取消后台运行。迟到回调和旧快照受到代次、序号及版本检查。

**设计取舍：**投影集中处理事件，有利于回放和测试；代价是要同时维护快照纠偏、事件增量和版本兼容。

**测试与自测：**阅读[流控制测试](../../apps/desktop/src/features/coding/composables/useRunStream.spec.ts)和[投影测试](../../apps/desktop/src/features/coding/model/runProjector.spec.ts)。回答：为什么关闭组件和取消任务是两个不同动作？

外围界面沿现有设计组件和主题服务构建，入口为[设置页](../../apps/desktop/src/components/SettingsView.vue)、[主题控制器](../../apps/desktop/src/services/wallpaperTheme/controller.ts)、[窗口关闭服务](../../apps/desktop/src/services/windowClose.ts)及[通知状态](../../apps/desktop/src/stores/notifications.ts)。这些组件的任务是呈现状态和引导操作；执行权限仍由本机层判断。

## M02 桌面启动与私有 IPC

**职责：**管理桌面壳与本机执行器的生命周期，并将受控请求和流式结果跨进程传递。

**调用与依赖：**[localExecutor](../../apps/desktop/src/services/localExecutor.ts)调用[原生执行器模块](../../apps/desktop/src-tauri/src/local_executor.rs)；[privateTransport](../../apps/desktop/src/services/privateTransport.ts)封装请求，Python 的[entry](../../src/private_agent_local/entry.py)与[ipc](../../src/private_agent_local/ipc.py)接收。

**输入输出：**请求帧包含请求标识、方法、路径、头和正文；响应帧分为状态、数据、结束或错误，前端还原为可增量读取的 Response。

**状态与持久化：**待响应请求、管道和子进程句柄在内存；模型和 MCP 密钥通过 Rust 系统凭据库边界管理，不在学习实验中读取。

**实现过程：**

1. 合并并发启动，验证传输协议和就绪状态。
2. Rust 为请求登记 Channel，以请求 ID 匹配流式响应；请求并发有上限。
3. Python 校验路径、方法、大小和允许的头，将请求转换为 ASGI scope。
4. 取消、管道退出和父进程退出分别触发所属请求及资源清理。

**失败处理：**启动失败可重新连接；无效帧、超限、重复 ID 和过慢消费显式失败。执行器不因不可用而把本机路径交给旧远端服务。

**设计取舍：**私有 stdio 减少桌面主链的监听端口；需要处理 framing、请求复用、背压和进程退出。

**测试与自测：**阅读[IPC 测试](../../tests/unit/test_local_ipc.py)与[连接恢复 E2E](../../apps/desktop/e2e/recovery-fixes.spec.ts)。回答：供应商 401 与本机会话过期如何区分？

打包入口为[build-client](../../scripts/build-client.cjs)与[构建器](../../scripts/build-remote-client.cjs)，协议同步入口为[protocol_codegen](../../scripts/protocol_codegen.py)。更新目标和端点由[updater_config](../../apps/desktop/src-tauri/src/updater_config.rs)核对，前端[UpdateChecker](../../apps/desktop/src/components/UpdateChecker.vue)展示结果。构建、updater 验签、Authenticode 和实际安装升级分别验证。

## M03 API 与身份作用域

**职责：**验证请求边界，取得当前身份运行时，再把请求交给对应服务。

**调用与依赖：**[create_app 与 DesktopState](../../src/private_agent_local/app.py)组装路由和本机依赖；[identity](../../src/private_agent_local/identity.py)决定本机数据空间；[RunInput](../../src/private_agent_local/app.py#L139)约束任务输入。

**输入输出：**输入为本机请求 DTO，输出为项目、会话、运行、审批或结构化错误。运行绑定包含 project、workspace、session，三者不能随意组合。

**状态与持久化：**当前身份、Runtime 和凭据引用有各自生命周期；业务数据存入身份作用域内的数据库。

**实现过程：**

1. 中间件核对本机请求边界，依赖函数验证会话。
2. Pydantic 校验输入；运行创建额外核对模型恢复、模型能力和执行协议。
3. 项目管理和 Runtime 核对实体归属、授权目录与活动状态。
4. 路由把控制冲突等错误转换为约定的状态和错误码。

**失败处理：**错误身份、跨项目绑定、被删除模型、未确认恢复和无效权限不创建新运行。重复请求先查询已有记录，再核对一致性。

**设计取舍：**路由保持请求编排职责，复杂执行交给服务；DTO 校验之外仍需运行时事实校验。

**测试与自测：**阅读[本机 API 测试](../../tests/unit/test_local_executor.py)、[访问测试](../../tests/unit/test_local_access.py)和[项目管理测试](../../tests/unit/test_local_project_management.py)。回答：为什么 DTO 校验通过仍不能直接执行工具？

## M04 SQLite 与历史持久化

**职责：**保存实体、运行、事件、工具事实和历史，并让数据库升级和故障恢复保留原记录。

**调用与依赖：**[Store](../../src/private_agent_local/store.py)被 Runtime 和各业务服务使用；[migration](../../src/private_agent_local/migration.py)负责历史交换与导入回滚。

**输入输出：**输入为业务实体、运行快照及事件；输出为查询记录、事件页和持久化回执。部分字段采用 JSON 保存，集合另有关系表。

**状态与持久化：**当前主库 schema 10，启用 WAL 和外键检查；数据库所有者锁防止不受控的多执行器占用。长期记忆为另一数据库。

**实现过程：**

1. 打开库前取得所有者锁，拒绝向更高版本库写入。
2. 升级前生成并核对备份，在事务中迁移，失败保留源库。
3. 事件在事务中分配当前运行的唯一序号；一般事件同步运行状态及恢复检查点。
4. 高频增量采用 lightweight 追加路径，避免反复保存完整历史；大内容使用带摘要的本机产物引用。
5. 重启处理撤销授权、关闭未确认调用并保留未知副作用。

**失败处理：**事务回滚不能继续采信内存中的成功事件。备份损坏、内容摘要不匹配和未来 schema 明确拒绝。

**设计取舍：**SQLite 适合本机单用户持久化；WAL 提供读写协作，但不能把它描述为分布式数据库或无条件多写者系统。

**测试与自测：**阅读[Store 测试](../../tests/unit/test_local_store.py)中的事件回滚、迁移失败和重启场景。回答：业务事务与磁盘文件副作用为什么需要不同的恢复方法？

## M05 模型协议与适配

**职责：**把不同模型供应商的请求、工具调用、增量输出和用量映射到统一契约。

**调用与依赖：**[ConfiguredModels](../../src/private_agent_local/direct_models.py)选择模型并创建适配器；[ModelGateway](../../src/private_agent_core/llm/gateway.py)统一调用边界；[adapters](../../src/private_agent_core/llm/adapters.py)及[Responses 适配器](../../src/private_agent_core/llm/responses.py)转换协议。

**输入输出：**使用[共享契约](../../src/private_agent_core/contracts.py)中的 ModelRequest、ModelResponse、ModelMessage、ToolCall 和 TokenUsage。外部 JSON 必须转换和校验后进入核心。

**状态与持久化：**模型目录和能力由[model_catalog](../../src/private_agent_local/model_catalog.py)管理。公开消息与内部 provider_state 有不同存储和导出边界。

**实现过程：**

1. 核对供应商是否启用、协议、API 格式、地址和模型 ID。
2. 按配置选择 Chat Completions、Responses、Claude Messages 或 Ollama 适配器。
3. 将工具定义与历史消息转换为供应商格式，解析文本、工具参数、finish 状态和流式结束。
4. 完整 Responses 状态只续接到匹配端点、模型和凭据的路由。
5. 区分声明能力、探测结果和本次真实用量；缺失用量或费用保持未知。

**失败处理：**无效协议、截断响应、非 JSON 工具参数和能力不支持明确报错。直连主链的请求尝试与共享 Gateway 的通用重试能力分别阅读；不能假定供应商失败会自动换 API 格式或模型。

**设计取舍：**统一契约减少循环对供应商的依赖；原生续接和流式细节仍要在适配器保留，兼容地址也不等于支持全部能力。

**测试与自测：**阅读[模型 Gateway](../../tests/unit/test_model_gateway.py)、[直连](../../tests/unit/test_direct_models.py)和[Responses](../../tests/unit/test_responses_adapter.py)测试。回答：为什么“模型列表连接成功”不能证明工具调用可用？

## M06 Agent 循环与本机适配

**职责：**推进模型决策和工具反馈，同时使执行受累计预算与取消约束。

**调用与依赖：**[AgentRuntime](../../src/private_agent_core/runtime.py)依赖 ModelClient、ToolDispatcher 和 EventSink 协议；[LocalRunAdapter](../../src/private_agent_local/core_adapter.py)同时实现本机接入。

**输入输出：**输入为消息、工具定义、运行标识和限额；输出为 AgentRunResult、步骤、用量和终态，候选输出可进入验证器。

**状态与持久化：**核心维护当前循环上下文；本机适配器记录消息、公开增量、工具事实和 SQLite 事件。模型请求、工具调用与公开消息分别定位。

**实现过程：**

1. 建立运行上下文，检查取消和轮次、步骤、工具调用及时间预算。
2. 请求模型并确认完整响应，记录消息和用量。
3. commentary 无工具时继续；有工具时校验批次预算和工具暴露范围，再派发。
4. 将工具结果按原始调用顺序回填，继续模型请求。
5. 最终文本交给验证器；可纠正失败的反馈在原预算中重试。

**失败处理：**工具错误可以作为反馈；结果 ID 不匹配、非法输出、事件写入故障、取消和限额有明确停止路径。批准等待不是普通工具失败。

**设计取舍：**协议注入让核心可被合成模型和工具测试；本机业务仍由适配器承接，避免把持久化和权限逻辑塞进通用循环。

**测试与自测：**[运行时测试](../../tests/unit/test_agent_runtime.py)包含工具后续接、失败恢复、取消和预算检查。回答：为何一个工具输出不能直接成为最终答案？

## M07 任务解释与执行限制

**职责：**从真实用户来源提取可执行限制和可核验要求，保留原文供模型理解语义。

**调用与依赖：**[interpret_task 与 rebuild_task](../../src/private_agent_core/task_intent.py)产生 TaskInterpretation；[task_constraints](../../src/private_agent_local/task_constraints.py)在文件、命令、stdin、MCP 和完成检查边界使用它。

**输入输出：**输入为原始目标、明确要求和追加指令；输出包括来源、条件、路径范围、禁止项、撤销限制和完成要求。当前内部解释版本为 1.2。

**状态与持久化：**原文和来源进入上下文；派生解释与当前目标版本保存在运行 JSON，恢复时核对来源并重建。

**实现过程：**

1. 区分用户有效指令与示例、引用、日志等内容。
2. 提取明确限制，区分全局禁止、路径限制和子任务提示。
3. 条件保留给模型结合现场事实判断；程序不替代完整自然语言理解。
4. 执行前重新检查，只有真实用户明确放宽的限制才可解除。

**失败处理：**派生缓存不能扩大授权；旧记录来源不完整时保留限制并说明不能升级。命令执行后的范围核对可以标记 violated 或 unverified，保留实际变化。

**设计取舍：**确定性限制可以测试、审计，但覆盖的语言和动态命令语义有限；用户原文必须保留，执行权限另有检查。

**测试与自测：**阅读[任务意图](../../tests/unit/test_task_intent.py)与[任务限制](../../tests/unit/test_local_task_constraints.py)测试。回答：“A 修复，B 只分析”和“整个任务先只分析”应如何区别？

## M08 计划与运行控制

**职责：**维护可核对的多步计划，并安全接收暂停、继续、取消和追加要求。

**调用与依赖：**[LocalPlanner](../../src/private_agent_local/planning.py)、[PlanningInteraction](../../src/private_agent_local/planning_interaction.py)、[RunControls](../../src/private_agent_local/run_controls.py)配合 Runtime 和恢复服务。

**输入输出：**计划更新携带 expected_plan_version 与 goal_version；控制请求携带请求标识和 expected_state_version；输出为新版计划、状态或冲突回执。

**状态与持久化：**计划、条目键、当前目标、公开说明、控制记录、代次和进展指纹保存在运行及控制表。

**实现过程：**

1. 按稳定 item_key 核对计划更新和合法状态转换，来源引用须属于当前逻辑任务。
2. 追加目标使计划进入 needs_review，更新代次，旧模型和工具响应失效。
3. 控制在模型、工具等安全边界生效，并记录请求去重及状态版本。
4. [progress](../../src/private_agent_local/progress.py)识别重复观察；计划勾选仍须通过完成验证。

**失败处理：**旧状态版本返回冲突；取消保留已发生的文件副作用；暂停和取消竞争不能绕过审批。规划模式只读探索，实施交接是明确的下一步。

**设计取舍：**版本和代次增加状态管理复杂度，但避免迟到结果覆盖新目标；进展是模型报告，不构成机器验收。

**测试与自测：**阅读[计划测试](../../tests/unit/test_local_planning.py)、[规划模式](../../tests/unit/test_local_plan_mode.py)和[进展测试](../../tests/unit/test_local_progress.py)。回答：为什么目标版本与计划版本需要分开？

## M09 工具契约与按需发现

**职责：**为工具提供统一元数据、校验和选择，使模型只看到当前可用能力。

**调用与依赖：**[ToolSpec 与 ToolRegistry](../../src/private_agent_core/tool_specs.py)描述和校验工具；[本机注册表](../../src/private_agent_local/tool_registry.py)聚合工具；[ToolCatalog](../../src/private_agent_local/tool_catalog.py)支持按需搜索。

**输入输出：**工具定义包含名称、版本、输入和输出 schema、副作用、审批、能力、取消及并行元数据；调用进入统一 ToolCall，返回 ToolResult。

**状态与持久化：**注册表为程序定义；当前任务的可见目录、发现状态和版本在运行中维护，配置撤销在后续边界重新筛选。

**实现过程：**

1. 注册契约；根据权限、任务限制、项目配置和材料选择候选工具。
2. 基础工具与可发现工具分别进入请求，减少无关定义占用上下文。
3. 调用前核对名称、暴露状态、输入 schema 和动态权限。
4. 调用后核对结果格式和大小；符合元数据的相邻幂等只读调用最多两个并行。

**失败处理：**未注册或未暴露工具不能派发；写入、命令、控制与外部调用不因模型批量输出而自动并行。

**设计取舍：**契约集中管理减少入口差异，动态选择节省预算；新增工具必须正确声明副作用，元数据不能代替执行检查。

**测试与自测：**阅读[注册表测试](../../tests/unit/test_local_tool_registry.py)、[工具选择](../../tests/unit/test_tool_selection_runtime.py)与[并行测试](../../tests/unit/test_parallel_tools.py)。回答：自动审批、幂等与可并行为什么是不同属性？

## M10 文件搜索与补丁

**职责：**提供授权目录内的版本化读取、分页搜索和可核对的文件修改。

**调用与依赖：**[files](../../src/private_agent_local/files.py)验证路径；[Repository](../../src/private_agent_local/repository.py)管理范围读取、查询和快照；[PatchService](../../src/private_agent_local/patchsets.py)管理补丁。

**输入输出：**读取返回内容、范围、snapshot_id 和摘要；搜索返回查询版本及续页游标；补丁包含修改前后状态、预览摘要、操作标识和逐项事实。

**状态与持久化：**file_snapshots、patch_sets、patch_journal 在主库；实际文件仍位于授权目录。读过的版本与补丁应用后的版本是不同事实。

**实现过程：**

1. 读取核对路径、文件类型和 expected_version，保存编辑快照；分页绑定查询和版本。
2. 根据结构化编辑生成完整前后状态、diff 与 preview_sha256，审批前预览。
3. 应用前核对根目录身份、规则、权限、预览和当前文件；逐项记意图、替换、独立磁盘回读，再记成功。
4. 多文件失败保留实际逐项状态；回滚先预览，再保护应用后的用户修改。

**失败处理：**过期读取、被篡改预览和外部修改明确拒绝。中断可以留下 partially_applied 或待核对日志，恢复不宣称跨文件原子完成。

**设计取舍：**逐项日志和内容摘要支持恢复、审阅与冲突保护；文件系统与数据库之间无法简单依靠一个 SQL 事务保证全部修改原子性。

**测试与自测：**阅读[范围读取](../../tests/unit/test_local_file_ranges.py)、[搜索分页](../../tests/unit/test_local_search_pagination.py)和[补丁测试](../../tests/unit/test_local_patchsets.py)。回答：为什么预览成功不能保证稍后的执行一定成功？

## M11 权限与系统沙箱

**职责：**决定操作是否需要交互确认，并限制普通进程的实际访问能力。

**调用与依赖：**[policy](../../src/private_agent_local/policy.py)制定权限和命令计划；[windows_sandbox](../../src/private_agent_local/windows_sandbox.py)处理授权对象；[Rust sandbox](../../apps/exec-host/src/sandbox.rs)启动受限进程。

**输入输出：**输入为权限模式、执行模式、参数、路径和网络要求；输出为批准、拒绝或命令执行计划。能力查询同时报告实际限制。

**状态与持久化：**限时授权绑定会话和项目，审批绑定操作；AppContainer 与 ACL 租约绑定具体进程执行及资源清理。

**实现过程：**

1. readonly、confirm、workspace、full_access 分别约束操作和审批；全访问仍受路径、任务限制和执行策略检查。
2. 普通命令始终经 AppContainer，默认无网络，不因启动失败自动降级。
3. 扫描已有敏感对象，保护已有秘密文件和控制目录；ACL 清理移除本次 SID 并恢复相关继承状态。
4. trusted_project 是每次单独批准的脱离沙箱申请，权限接近当前用户的能力。

**失败处理：**重叠租约、无法安全授权或恢复的 ACL、扫描超限、链接和宿主能力不足会拒绝启动。

**设计取舍：**审批解决用户是否允许，沙箱解决进程实际能做什么。现有敏感对象保护没有按未来文件名持续拦截，也没有按域名放行网络，不能把 full_access 说成管理员权限。

**测试与自测：**阅读[安全权限](../../tests/unit/test_security_permissions.py)、[敏感路径沙箱](../../tests/unit/test_sandbox_sensitive_paths.py)和[Windows 沙箱](../../tests/unit/test_windows_sandbox.py)测试。回答：一次批准为何不能替代后续版本和权限复核？

## M12 命令宿主与持续执行

**职责：**将命令启动、等待、增量输出和输入管理为有身份、有生命周期的执行会话。

**调用与依赖：**[execution_tools](../../src/private_agent_local/execution_tools.py)提供入口；[ExecutionSessions](../../src/private_agent_local/execution_sessions.py)编排；[ExecHostClient](../../src/private_agent_core/execution/exec_host_client.py)对接[exec-host](../../apps/exec-host/src/main.rs)。

**输入输出：**输入包括 argv、cwd、环境差异、执行模式、stdin 和保留范围；输出为执行标识、状态、输出游标、退出或未知结果。

**状态与持久化：**[ExecutionStore](../../src/private_agent_local/execution_store.py)保存会话记录及输出；活动进程、监听任务和管道保留在内存，不把 PID 当成可跨重启复用的完整身份。

**实现过程：**

1. 启动前核对任务约束、命令计划、权限、工作区和宿主能力。
2. 宿主按协议建立进程，管理标准输出、错误、PTY 或 stdin。
3. 监控任务增量发布输出，退出或取消时保存真实结果并回收资源。
4. stdin 写入核对当前版本及任务约束；session 或 run 保留范围决定何时清理。

**失败处理：**超时、宿主退出和进程身份不明分别处理。结果未知时保留 uncertain 状态，不能用默认退出码补成成功。

**设计取舍：**持续会话支持长命令与交互输入，但需要身份、游标、取消和输出脱敏；持续进程不意味着恢复后能凭 PID 安全重新附着。

**测试与自测：**阅读[持续执行](../../tests/unit/test_local_execution_sessions.py)、[stdin 授权](../../tests/unit/test_execution_stdin_authorization.py)和[执行宿主](../../tests/unit/test_local_exec_host.py)测试。回答：取消任务后还需要等待哪些资源清理？

## M13 规则与上下文管理

**职责：**在每次请求前组装当前规则、目标、历史、工具和可选记忆，并保证预算与来源可核对。

**调用与依赖：**[InstructionLoader](../../src/private_agent_local/instructions.py)、[LocalContext](../../src/private_agent_local/context_manager.py)、[ContextHistory](../../src/private_agent_local/context_history.py)、[context_summary](../../src/private_agent_local/context_summary.py)配合[预算算法](../../src/private_agent_core/context.py)。

**输入输出：**输入为当前 ModelRequest、模型容量、规则与历史；输出为预算内的请求或显式限制错误。工具原文续读输出是当前会话内容的公开投影。

**状态与持久化：**原始 context_items 与派生 context_checkpoints 分开；预算、校准、已交付规则及当前代次在运行上下文中维护。

**实现过程：**

1. 检查身份、授权根、模型路由及能力指纹；按目标子树加载受信规则，保留来源。
2. 注入最新目标、限制、计划、纠错和完成检查提示，外部正文保留不可信来源。
3. 组装完整请求并估算预算；可选记忆在触发压缩或超限时优先移除。
4. 保留必要用户约束和最近完整调用组，将更早内容转成带引用的工作摘要与事实索引。
5. 原始内容保留，续读先校验摘要；provider_state 不出现在公开投影中。
6. 压缩完成前检查代次，追加目标后旧摘要不得提交。

**失败处理：**预算不足、路由变化、规则改变、损坏引用和不完整状态明确失败；不裁剪不透明原生状态来勉强发送。

**设计取舍：**压缩节约窗口但会损失语义；来源索引、原文续读和硬限制帮助模型重新核对，不能保证每条旧细节仍在当前请求中。

**测试与自测：**阅读[指令](../../tests/unit/test_local_instructions.py)、[上下文历史](../../tests/unit/test_local_context_history.py)、[压缩](../../tests/unit/test_local_compaction.py)与[对齐](../../tests/unit/test_context_alignment.py)测试。回答：会话原文保留与当前请求包含全文为何不同？

## M14 长期记忆

**职责：**在用户可控范围内保存跨会话参考，支持提取、召回、纠正、冲突处理和遗忘。

**调用与依赖：**[Memories](../../src/private_agent_local/memories.py)提供服务；[MemoryStore](../../src/private_agent_local/memory_store.py)持久化；[memory_tools](../../src/private_agent_local/memory_tools.py)和[memory_routes](../../src/private_agent_local/memory_routes.py)复用服务。

**输入输出：**输入为明确记忆操作、合格会话来源和召回查询；输出为带来源、版本、作用域和采纳理由的条目。召回使用中文双字、英文标识符和路径匹配，没有向量索引。

**状态与持久化：**独立 memories.sqlite3 保存设置、事实、候选、修订、来源和遗忘哈希；全局、项目及会话开关共同决定行为，默认总开关关闭。

**实现过程：**

1. 先核对开关、来源、敏感内容和版本，再进行管理或后台生成。
2. 后台只处理符合条件的会话，使用有界片段和经校验的结构化输出契约；真实生成会调用所选模型。
3. 主题冲突进入候选与复核，不覆盖人工修改；生成提交前再次检查来源及管理版本。
4. 当前查询按词重叠、人工标记和更新时间排序，最多 8 条、约 6000 UTF-8 字节进入可选上下文。
5. 遗忘删除正文并留下去重哈希，来源清理由启动与管理路径核对。

**失败处理：**关闭、编辑、遗忘或来源变化使在途生成取消或丢弃；生成失败保留可重试来源并退避。

**设计取舍：**关键词召回简单、可解释，语义改写和同义表达可能漏召回；遗忘哈希也不能保证阻断换键改写。记忆是可能过时的参考，不授予权限。

**测试与自测：**阅读[记忆服务](../../tests/unit/test_local_memories.py)、[管理](../../tests/unit/test_memory_management.py)和[MCP 记忆边界](../../tests/unit/test_mcp_memory_boundaries.py)测试。回答：后台生成、显式记住和请求时召回分别在哪里发生？

## M15 任务恢复

**职责：**在暂停、中断或取消后，根据可验证的现场决定是否继续。

**调用与依赖：**[Recovery](../../src/private_agent_local/recovery.py)、[RunControls](../../src/private_agent_local/run_controls.py)、[Workspaces](../../src/private_agent_local/workspaces.py)及 Store 的重启处理共同实现。

**输入输出：**输入为 run、checkpoint_id、状态版本及恢复请求；输出为 can_resume、blockers、文件事实、命令状态和累计预算。

**状态与持久化：**逻辑任务标识、检查点、来源、计划、已消费预算和 workspace_leases 持久化；取消或中断后继续可能创建关联运行，暂停继续可以沿用当前运行。

**实现过程：**

1. 校验检查点格式和摘要、授权根及文件身份。
2. 对照补丁日志和实际磁盘，检查最新文件事实、命令与外部副作用。
3. 核对最新会话运行、模型配置、能力指纹、执行协议、权限和累计预算。
4. 从已提交上下文继续规划，关联旧运行和历史证据。

**失败处理：**未知命令、未确认外部写入、被修改的文件、过期授权或预算耗尽阻止继续；重启不重放旧审批、命令或文件写入，也不只凭 PID 重新附着。

**设计取舍：**检查点解决运行事实可追溯，现场核对解决事实已变化的问题。外部动作与本地事务无法构成统一原子提交，unknown 必须保留。

**测试与自测：**阅读[恢复测试](../../tests/unit/test_local_recovery.py)，特别关注 approval/pause/cancel 竞争和 restart unknown 场景。回答：为什么请求去重仍不能保证外部动作端到端 exactly once？

## M16 完成验证与纠错观察

**职责：**用实际证据核对目标，控制纠错循环，并向用户呈现公开进展和结果。

**调用与依赖：**[LocalCompletionVerifier](../../src/private_agent_local/completion.py)、[output](../../src/private_agent_local/output.py)、[reflection](../../src/private_agent_local/reflection.py)、[reflection_review](../../src/private_agent_local/reflection_review.py)、[Observer](../../src/private_agent_local/observer.py)和[observer_steps](../../src/private_agent_local/observer_steps.py)。

**输入输出：**输入为最终候选、完成要求、文件、命令和限制事实；输出为 OutputVerification、goal_outcome、verification_results 和 unverified_items。可选 output_schema 再验证结构。

**状态与持久化：**完成结果、纠错来源索引、失败次数、公开步骤和复核状态保存在运行及事件中；最终消息、结果和终态事务提交。

**实现过程：**

1. 核对候选的目标版本、计划状态、权限限制及所需证据。
2. 文件变化不能替代行为测试；命令结果核对具体命令和退出事实。
3. 可纠正的候选获得有界反馈重试，预算与之前尝试累计。
4. reflection 按同目标、工作区和操作归类未解决失败；无关成功读取不能洗掉该失败。
5. 必要时进行有界、无工具的独立上下文复核；Observer 呈现公开事实和配置检查。

**失败处理：**缺失、矛盾或未知证据分别报告。重复失败与成功但无进展有各自停止规则，模型复核不能替代机器或人工验收。

**设计取舍：**显式目标结果使“运行结束”和“任务验证通过”可分开表达；可核验要求的覆盖仍有限，用户业务预期需要相应验证。

**测试与自测：**阅读[完成](../../tests/unit/test_local_completion.py)、[结构化输出](../../tests/unit/test_local_output.py)、[反思](../../tests/unit/test_reflection_integration.py)与[Observer](../../tests/unit/test_observer_checks.py)测试。回答：公开决策摘要与模型隐藏推理为什么不能混为一谈？

## M17 Skills 与 MCP

**职责：**按项目选择和用户授权接入技能说明与外部工具。

**调用与依赖：**[SkillLibrary](../../src/private_agent_local/skills.py)、[MCP 服务库](../../src/private_agent_local/mcp_library.py)、[Integrations](../../src/private_agent_local/integration_mcp.py)、[文档 MCP](../../src/private_agent_local/documentation_mcp.py)及[MCP 凭据桥](../../src/private_agent_local/mcp_credentials.py)。

**输入输出：**技能输入含标识、版本和引用路径；MCP 输入含选定服务、目录版本、工具、schema 和参数；返回内容带外部来源及不可信属性。

**状态与持久化：**个人服务配置与项目绑定分开；工具选择和权限按项目管理。静态及 OAuth 凭据走系统凭据库桥，配置保存有准备、提交和清理状态。

**实现过程：**

1. 发现技能或 MCP 工具，用户明确启用并选择；技能通过内容摘要核对版本。
2. MCP 服务目录与 schema 被保存，调用绑定当前服务、配置及目录版本。
3. HTTPS 或经信任确认的 stdio 建立实际连接；OAuth 处理回调 state 和令牌边界。
4. 在审批前、发送前复查限制及敏感参数；外部写入始终逐次审批。
5. 只读工具可按项目配置使用会话许可，但配置和权限撤销会重新核对。

**失败处理：**目录变更、认证失败、配置撤销和 task 禁止 stdio 启动显式失败；写请求已发送而响应丢失标记 execution_unknown，禁止自动重放。

**设计取舍：**服务配置可复用、项目授权独立，减少重复配置；接入成功与真实 OAuth、第三方工具效果仍需分开验收。外部结果不能成为新的用户授权。

**测试与自测：**阅读[工作台集成](../../tests/unit/test_workbench_integrations.py)、[MCP 服务库](../../tests/unit/test_mcp_library.py)和[凭据生命周期](../../tests/unit/test_mcp_credential_lifecycle.py)测试。回答：MCP 与 Skills 各提供什么，为什么工具返回的文本不能放宽权限？

## M18 网页与浏览器检查

**职责：**读取允许的公开网页，或验证已启动的本机预览并保留可核对证据。

**调用与依赖：**[BrowserTools](../../src/private_agent_local/browser_tools.py)使用[public_http](../../src/private_agent_local/public_http.py)和受限预览代理，工具从注册表进入正常审批路径。

**输入输出：**公开页面输入为 HTTPS URL，输出为正文、来源和链接；预览输入为回环 URL 及有界选择器动作，输出为 DOM 检查和截图标识。

**状态与持久化：**网页结果进入带来源的工具记录；预览使用新浏览器配置，截图作为本机产物保留，不复用已登录浏览器。

**实现过程：**

1. 校验公开网络地址、凭据和 DNS 解析边界，拒绝私网及重绑定风险。
2. 本机预览限制为已运行回环源、合格端口及有限动作。
3. 代理限制到精确 origin 的 GET/HEAD，拒绝写请求及跨源。
4. 记录真实断言和截图；浏览器没有负责启动预览服务。

**失败处理：**无可用浏览器、不支持的地址、选择器断言失败及超时分别报告。

**设计取舍：**有限动作与新配置减少浏览器状态依赖，但不能覆盖任意网站、登录流程或完整视觉验收。

**测试与自测：**阅读[集成测试](../../tests/unit/test_workbench_integrations.py)中的 DNS rebinding、preview proxy 和浏览器证据用例。回答：截图存在为何不代表视觉验收全部通过？

## M19 草稿附件与数据恢复

**职责：**使输入、材料、配置和历史在发送失败、重启与迁移后可核对地保留。

**调用与依赖：**[Drafts](../../src/private_agent_local/drafts.py)、[TurnQueue](../../src/private_agent_local/turn_queue.py)、[attachments](../../src/private_agent_local/attachments.py)、[attachment_media](../../src/private_agent_local/attachment_media.py)、[attachment_storage](../../src/private_agent_local/attachment_storage.py)、[backups](../../src/private_agent_local/backups.py)、[前端备份下载](../../apps/desktop/src/api/backups.ts)、[ModelSaves](../../src/private_agent_local/model_saves.py)及[model_preferences](../../src/private_agent_local/model_preferences.py)。

**输入输出：**草稿带作用域、revision、mutation_id 和发送标识；附件有摘要及草稿/消息引用；备份有格式、payload 和摘要；模型保存带操作标识和凭据准备回执。

**状态与持久化：**草稿、引用、导入和配置保存记录在主库；材料正文独立存储；模型密钥在系统凭据库。长期记忆数据库不随当前历史或应用数据导出。

**实现过程：**

1. 草稿版本检查避免覆盖新输入；创建运行核实后再确认消费旧草稿。
2. 后续队列保存输入和请求标识，满足继续条件时推进；失败或重启保留输入并要求核对。
3. 校验图片和 PDF，按需提取文字或渲染；含视觉内容的发送核对模型能力。
4. 清理先预览引用和释放量，执行时重新核对引用版本，保留源文件和需要的历史材料。
5. 应用备份白名单导出配置、历史、草稿和材料，保留原始下载字节；v2 继续读取合法 v1。
6. 导入映射到用户选择的目录并创建新记录；重复导入返回原记录，数据失败回滚。
7. 模型恢复比较供应商身份、协议、格式、地址和模型 ID，不匹配先保存待确认状态，发送前阻断。
8. 模型保存通过准备、凭据完成和配置提交衔接；旧凭据清理分批报告已确认进度。

**失败处理：**损坏摘要、超限、未知版本、材料变化、模型不明和配置保存中断明确报告。历史回滚有后续改动指纹保护；配置导入与历史数据回滚的边界分开。

**设计取舍：**正文与引用分离减少重复材料，事务与摘要提供可核对恢复；OS 凭据库和 SQLite 不是同一事务，需要保存恢复状态。备份不复制项目代码、密钥、活动审批或运行进程。

**测试与自测：**阅读[草稿](../../tests/unit/test_local_drafts.py)、[材料清理](../../tests/unit/test_attachment_storage.py)、[备份](../../tests/unit/test_local_backups.py)、[模型恢复](../../tests/unit/test_backup_model_restore.py)和[模型保存](../../tests/unit/test_model_saves.py)测试。回答：为什么把备份 JSON 解析后重新 stringify 会破坏某些摘要？

## M20 Git 工作区与交接

**职责：**记录 Git 和文件基线，管理隔离工作区、审阅与交接，并提供任务搜索和归档。

**调用与依赖：**[git_workspace](../../src/private_agent_local/git_workspace.py)、[git_tools](../../src/private_agent_local/git_tools.py)、[Workspaces](../../src/private_agent_local/workspaces.py)、[WorktreeHandoff](../../src/private_agent_local/worktree_handoff.py)、[run_review](../../src/private_agent_local/run_review.py)、[workspace_search](../../src/private_agent_local/workspace_search.py)。

**输入输出：**输入为项目、工作区、Git 请求、交接预览版本或搜索条件；输出为基线、当前差异、冲突、交接事实或分页任务结果。

**状态与持久化：**工作区身份、初始 HEAD、分支及脏状态、工作区租约、交接日志和运行补丁记录分别保留。

**实现过程：**

1. 开始任务记录 Git 和文件事实；目录别名及同一 worktree 子树共享对应租约判断。
2. Git 查询通过授权和版本边界；写操作经过对应权限与审批。
3. worktree 操作核对活动任务、目录和 Git 状态，交接先预览再检查来源、目标及版本。
4. 审阅区区分运行内文件修改、用户后续改动和当前 Git 差异。
5. 全文任务搜索、分页及归档筛选使用本机历史，搜索结果可回到原消息。

**失败处理：**脏工作区、目标被修改、预览过期、活动租约或未知进程导致拒绝不安全的清理或交接；保留来源工作区和真实修改。

**设计取舍：**独立 worktree 减少任务之间的直接干扰，但依然需要版本、租约和交接核对；本机 Git 跟踪引用不证明远端实时状态。

**测试与自测：**阅读[恢复及真实 Git 测试](../../tests/unit/test_local_recovery.py)、[工作区功能](../../tests/unit/test_workspace_features.py)和[Git 工具](../../tests/unit/test_local_git.py)测试。回答：运行文件增删统计与 git diff 的净变化为什么可能不同？

## 按目录定位剩余实现

| 目录或文件组 | 如何继续阅读 |
| --- | --- |
| [共享契约](../../src/private_agent_core/coding_contracts.py)、[契约 schema](../../src/private_agent_core/coding_contracts.schema.json)、[执行契约](../../src/private_agent_core/execution/contracts.py) | 结合 M05、M06、M12 追踪类型及版本，不把生成结果手工改成独立事实 |
| [模型元数据](../../src/private_agent_core/model_metadata.py)、[能力探测](../../src/private_agent_core/model_probe.py)、[模型评测](../../src/private_agent_local/model_evaluation.py) | 区分能力声明、探测和真实任务质量；真实评测另有数据和费用约束 |
| 前端 api、model、composables、components | 分别跟踪请求边界、状态推导、生命周期和视图；从当日入口展开直接依赖 |
| [原生 lib](../../apps/desktop/src-tauri/src/lib.rs)、[模型凭据保存](../../apps/desktop/src-tauri/src/model_save_credentials.rs)、[MCP 凭据](../../apps/desktop/src-tauri/src/mcp_credentials.rs) | 结合 M02、M17、M19 检查桥接、错误及清理 |
| 前端 dev 和 E2E 夹具 | 用于观察或验证合成界面状态，单独记录与原生客户端的证据边界 |
| [正式测试](../../tests/README.md)、[脚本](../../scripts/README.md)、[发布说明](../releases/v1.0.1/github-release.md) | 用于复跑、构建和追溯；历史成绩不填入个人本轮实验记录 |
| [readonly_agents](../../src/private_agent_local/readonly_agents.py) | 作为历史兼容边界阅读；当前独立只读子任务已移除，不能据文件存在宣布可用 |

读完一张卡后，在源码中找到它的直接调用者和一个失败测试，再填写[学习记录](workbook.md)。当前入口说明不能替代源码逐步追踪。
