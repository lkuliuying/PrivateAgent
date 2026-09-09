# S5 恢复、运行中协作与变更审查开发报告

> 本文保留首次源码开发记录。后续原生隔离、真实 Tauri 和安装候选验证见 [S5 阻断项补充验收](./s5-blockers-validation-report.md)。最终 ConPTY、真实桌面协作组合、符号链接和前台延迟均已通过，当前可进入 S6，详见 [S5 剩余门禁验收记录](./s5-remaining-gates-validation-report.md)。本文以下“未打包/未修改宿主/未放行”等为当时历史结论，不代表收尾状态；本轮仅本地提交 S5，S6 未开发。

日期：2026-09-09（Asia/Shanghai）。环境：现有 Windows、Python 3.12 虚拟环境、exec-host 及桌面 Node 依赖。开工基线：`F:\Program\Agent`，`dev/1.0.0`，HEAD `d0250ee`，工作区和暂存区干净。

## 任务总结

本轮按用户“进入 S5 阶段的开发”指令，先核对项目入口、完整项目记忆、路线及 S4 开发前置证据，再建立计划、实现、测试和审查。S5 设计文档用于确定范围，不作为服务器操作、付费调用、发布或其他附加操作的授权。

本机主链和桌面界面已接入恢复契约 1.0。支持持久化控制、同进程暂停继续、中断或取消后关联新运行、累计预算、工作区协调、显式 worktree 和任务变更归属审查。真实 SQLite、Git 和 exec-host 故障注入及浏览器控制流程已验证。没有修改共享核心协议、Rust 宿主、依赖或锁文件；没有提交、推送、打包、安装、部署或调用真实付费模型。

这是一轮源码开发交付。完整 Tauri→本机服务→真实模型→重启→恢复→审查流程尚未验收，S5 阶段退出条件没有全部满足，不能据此放行 M2。S4 遗留的原生隔离、PTY、安装链和性能验收限制仍保留，M1 也未放行。

## 实现与协议

### 状态和控制

创建请求可显式发送 `recovery_contract_version: "1.0"`，能力响应通过 `coding_recovery_contract_version` 协商。执行契约仍单独使用 `execution_contract_version: "1.0"`。没有新契约的客户端保留旧运行方式，旧记录缺少检查点时不能调用恢复控制。

| 状态或动作 | 实际行为 |
| --- | --- |
| `created` / `queued` | 等待取得工作区；队列显示位置、资源上限或原持有者核对原因，可以暂停或取消。 |
| `running` / `waiting_approval` | 模型、工具与审批依照持久化代次检查；新控制使旧响应或旧审批失效。 |
| `paused` | 在安全边界保存现场，保留原 run ID 和租约，不调度新工具。普通命令被取消，显式保留服务单独展示。 |
| 暂停后 `resume` | 重新核对检查点、模型、权限、工作区和预算，继续原 run ID。 |
| `interrupted` | 启动恢复收束新协议活动运行。旧协议仍收束为 failed。原待审批关闭，未确认命令记 unknown。 |
| 中断/取消后 `resume` | 建立新 run ID，保留 `logical_task_id`、`resumed_from_run_id` 和祖先链，旧运行终态及事件不改写。 |

新增接口均沿现有本机私有传输与账号绑定边界：

| 接口 | 输入或输出 |
| --- | --- |
| `POST /agent-runs/{id}/pause` | `request_id`、`expected_state_version`。 |
| `POST /agent-runs/{id}/steer` | 上述字段和 `message`，消息长度 1–32000；先持久化真实用户消息，再在安全边界应用。 |
| `POST /agent-runs/{id}/resume` | 上述控制字段和 `checkpoint_id`；返回原 ID 或 `result_run_id` 关联新运行。 |
| `POST /agent-runs/{id}/cancel` | 接受同一控制输入，也兼容无请求体的旧入口；返回清理回执。 |
| `GET /agent-runs/{id}/recovery` | 是否支持、状态/版本、检查点、阻塞原因、文件事实、执行状态、预算和控制记录。 |
| `GET /agent-runs/{id}/review` | 任务补丁、起始 dirty、外部或无法归属的变化及命令候选变化。 |
| `POST /projects/{id}/workspaces/worktree` | 用户选定 `ref`、幂等 `request_id`。 |
| `POST /projects/{id}/workspaces/{workspace_id}/cleanup` | 受保护地清理本应用拥有的 worktree。 |

控制状态区分 `received`、`applied`、`interrupted`，每 run 最多 256 条控制记录。相同 ID 与相同输入返回原回执；复用 ID 修改内容或状态版本不匹配返回 HTTP 409 和当前 `state_version`。前端网络失败使用原 ID 重试，409/422 刷新后要求新的用户操作，不自动覆盖。

控制和事件事务失败时恢复内存中的运行版本，消息、控制及新运行一并回滚。关联运行的协程仅在外层控制事务提交后启动。结束时尚未应用的控制标为中断；用户输入保留在消息与上下文历史中，并避开待配对工具结果的中间位置。用户确认关联继续时，尚未应用的追加约束进入新运行的控制队列，保留原消息与来源引用，再在安全边界应用，不重复创建用户消息或改写旧回执。

第一版只收紧原约束。“只解释”“停止写文件”“不要测试”等限制在后续安全边界生效；正在发生的文件副作用保留真实结果。旧失败、拒绝和未核实操作不会被清除。解除限制或重大独立目标需要新任务。模型请求可取消，迟到响应按 generation 丢弃；每个多文件写入边界及实际命令启动前重新检查代次。启动中的专用宿主也纳入取消；批量停止先同时发布停止意图，再等待各进程收束。

### 检查点、授权及预算

SQLite 升为 schema 7，新增 `run_checkpoints`、`run_control_requests`、`workspace_leases`。复用 S2 内容块、上下文历史、S3 补丁日志和 S4 执行记录，不创建第二份执行事实源。格式版本为 1.0，检查点包含运行/会话/工作区身份、逻辑任务、上下文游标、压缩检查点引用、已确认响应、操作引用、事件序号、目标/代次、模型配置及能力摘要、执行契约和预算。

完整状态事件和对应检查点在同一 SQLite 保存点事务提交；高频文本/终端增量沿 S4 轻量事件路径，不逐字符写检查点。模型请求尝试先记预算；完整响应确认、工具意图/审批、结果入库、控制接收/应用、暂停、压缩和终态均通过事件边界记录。大内容先落内容块，再发布引用；读取检查摘要、归属、版本与上下文配对。

启动前取得数据库所有权 OS 锁，另一活动服务不能打开同一库后把原运行误判为中断。schema 2–6 升级前产生一致 SQLite 备份；新格式拒绝旧程序降级写入。没有执行生产数据迁移，测试只使用新建目录及合成记录。

重启关闭旧审批与完全访问授权。继续任务重新核对账号、根目录身份、模型配置和能力摘要、宿主协议及预算。模型不可用或能力变化时不静默换模型。继续旧完全访问任务，需要用户明确重新确认当前会话的新授权；新运行使用新 grant ID，旧记录保留原引用。

新运行继承模型尝试、工具次数、用量、费用已知性、活动时间、重复失败、验收纠正次数、原要求和约束。验收纠正累计最多 2 次；逻辑任务最多关联继续 32 次。费用缺失不能被恢复成已知费用。暂停、审批和排队不消耗活动计时；崩溃时最后检查点之后的精确活动时长无法重建，当前保守计到重启时刻并以预算上限截断，可能包含离线时间，不能称为精确计费。

历史操作证据仅在当前文件摘要或代码版本核对后复用。通过新运行的 `evidence.revalidated` 事件登记原 run、operation、execution 和 sequence 来源，再生成当前运行的 EvidenceRef，保持 S1 的证据归属契约。

### 工作区和 worktree

同一 Git 工作树的根目录及子目录登记共享锁键；非 Git 目录使用规范路径与实际文件身份。每账号最多 2 个工作区同时持有租约，最多 16 个活动/排队任务；同一会话不能同时创建第二个运行。保留执行进程继续占有原租约，关闭后释放。S4 每工作区 2 个执行、账号 4 个执行的上限继续有效。

OS 锁文件带账号摘要、持有者、run 和代次；SQLite 保存租约状态。原持有者失联后检查文件日志与未知命令，不能按超时夺锁。存在未核实副作用时，既阻止 resume，也阻止另一个新任务绕过租约。另一账号留下的未核实现场只能由原账号核对。锁仅协调同一应用数据根中的执行器，不阻止外部编辑器或其他数据根的程序写入；S3 摘要保护仍然必要。

worktree 创建采用结构化 Git 参数，从显式 ref 解析到确定提交，使用 detached HEAD；不会创建业务分支、提交、合并或推送，也不复制未提交文件。目录在应用数据根的受管理 `worktrees/<账号摘要>/<唯一短 ID>` 内，记录主仓库、ref、SHA、实际目录身份和 Git common-dir；检查 Git、目录归属和至少 256 MiB 剩余空间。

清理要求实际路径、所有权和 Git 归属一致，且无活动/排队/暂停任务、修改、未跟踪/忽略文件或后续提交；只调用不带 force 的 `git worktree remove`。失败/未核实创建记录保留为 conflict/error，不自动删目录或覆盖重试。第一版不提供未提交修改搬运、未知现场强制解锁或失败 worktree 的自动修复。

界面直接进行的分支切换、附件写入和回滚应用也取得工作区锁。不同工作区的新协议普通任务不会因 UI 切换项目而结束；完全访问仍按现有策略撤权，旧协议仍保持全局单任务及切换行为。

### 任务变更审查

沿祖先链聚合 S3 补丁与逐文件事实；对比首个运行前的 Git dirty 和有界摘要，将已记录补丁、原有修改、外部或无法归属的变化分别展示。命令前后摘要只能归集候选变化，不能证明变化全部来自命令。全文 diff 和撤销复用 S3 面板与哈希保护；外部编辑导致摘要不匹配时拒绝撤销，保留新内容。

扫描最多 10000 文件、64 MiB，排除凭据、链接和既有忽略目录，超限明确标记不完整。二进制/范围外变化只提供摘要；不宣称完整仓库审计。移动操作沿 S3 补丁中的对应文件变化展示，不建立新的任意 Git 回退入口。

## 验证结果

最终回归使用现有隔离脚本，独立临时目录、测试账号及受控模型；业务配置/数据库模块被测试插件阻断。实际结果：

| 命令 | 观察结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite recovery` | 35 passed，40.09 秒；`recovery-8df902a4761244729b5d14067df9f328`。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite execution` | 15 passed，12.79 秒；`execution-78af20494c1f477e8952b3329ee9fbfa`。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all` | 320 passed、2 skipped、2 strict xfailed，121.86 秒；`all-dd9a6e6beff945769c96dee4c0bc4084`。包含当时的 recovery 和 execution，不应重复累加。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_legacy_validation.py` | 106 passed，11.72 秒；`legacy-7e2f27e45bd448c28ec8a1dca2864274`。 |
| `npm run test -- src/features/coding src/services/localExecutor.spec.ts src/services/privateTransport.spec.ts` | 在 `apps/desktop` 运行，35 文件、222 passed，15.49 秒。 |
| `npm exec playwright test e2e/coding-run.spec.ts -- --grep S5 --retries=0` | 在 `apps/desktop` 运行，1 passed，5.1 秒；浏览器真实渲染，后端路由为模拟。 |
| `npm run build` | 在 `apps/desktop` 运行，vue-tsc 与 Vite 成功；Vite 14.97 秒，保留现有 antd chunk 超过 500kB 提示。 |
| `.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check` | `protocol codegen in sync: OK`。 |
| `.venv/Scripts/python.exe -B scripts/check_agent_v2_imports.py` | `agent_v2 dependency rules: OK`。 |
| 下方 Ruff 命令；`git diff --check` | 均通过。 |

```powershell
.venv/Scripts/python.exe -B -m ruff check src/private_agent_local scripts/run_coding_validation.py tests/unit/test_local_recovery.py tests/unit/test_local_store.py tests/unit/test_local_context_history.py tests/unit/test_local_patchsets.py tests/coding_acceptance/recovery_process.py tests/coding_acceptance/test_baseline.py
```

Python 证据位于被 Git 忽略的 `.run/coding-agent-validation/<上述目录>/`，包括 `invocation.json`、`pytest-result.json` 及保留的合成现场。最终测试输出另存 `s5-all-validation.log`、`s5-recovery-validation.log`、`s5-execution-validation.log`、`s5-legacy-validation.log`。不把这些临时日志作为项目记忆或提交文件。

全量回归后，最后补充了“已收到但未应用的追加约束随关联运行继续应用”的保护及一项回归；随后重跑 recovery，35 项通过，并通过定向 Ruff 与差异检查。全量结果不冒充在这一最终小改动之后重新执行。租约释放同时核对受管理执行的 unknown/stopped 状态，即使工具终态缺失也不会放行第二个任务；此边界已纳入上述全量与专项。

两个 skipped 是 Windows 未授权真实符号链接和 ConPTY 探针失败；两个 strict xfailed 是 S4 已知 G10 文件/网络原生隔离缺口，没有弱化断言或改成成功。没有复跑 S4 十分钟专项，也没有把历史成绩算作本轮结果。

初次沙箱运行存在 Windows 命名管道 WinError 5 和 Node/esbuild spawn EPERM；随后经工具审批在本机运行隔离测试与构建。没有自动审批拒绝或需要用户补充的权限。开发过程中曾出现并已修正：临时目录误共享上层仓库租约、worktree 测试长路径、故障模型补丁参数、测试账号初始化、控制事务/命令启动竞态、恢复证据归属及累计纠正重复扣除。

真实补丁链另发现既有适配器把成功结果中的 `error: null` 当失败，导致 ToolResult 契约校验失败。它直接阻断 S5 多文件故障场景，本轮将失败判断改为非 null 错误，未放宽失败结果的核心校验。批量停止先广播取消，避免项目切换等待第一个宿主时后面的宿主先被记为授权失联；原有执行回归验证通过。

## 故障矩阵与尚未覆盖的门禁

| S5 用例 | 本轮证据及边界 |
| --- | --- |
| T01 | 子进程在 model.requested、model.response_confirmed、tool.requested、tool.approval_required、tool.result_recorded 后 `os._exit(23)`；重新打开实际 SQLite，核对中断、检查点、历史和文件未被重放。事件/检查点和控制事务的提交前失败另行注入。 |
| T02 | 真实两文件补丁在首项意图、磁盘替换、结果日志后退出；明确第一文件已写或未写、第二文件保持原值。未核实 applying 状态阻止继续。 |
| T03 | 真实 exec-host 启动命令后服务退出，重新打开数据库看到 unknown；启动计数不增加，未重放命令。 |
| T04 | 采用完全不依赖 PID 重新附着的路径，未知身份直接阻断；S4 协议及会话归属测试继续通过。没有模拟系统真实 PID 复用，也没有证明自动附着能力。 |
| T05 | 真实审批边界退出关闭旧等待；撤销授权后 resume 被拒，新授权才允许关联继续；未绑定账号返回 401，切换绑定后原账号记录返回 404。 |
| T06 | 重复控制消息只持久化/应用一次；取消不及时的模型迟到响应被丢弃，旧工具不执行。暂停期间收到但未应用的约束在关联继续后生效，用户消息不重复。 |
| T07 | 第一个文件落盘后注入真实 steer 请求，后续文件仍为原值；保留 partially_applied 和已写事实，未宣称全部完成。 |
| T08 | 暂停/取消/迟到批准不启动旧操作；真实宿主启动期间暂停，未发送命令，宿主收束。 |
| T09 | 关联继续保留旧事件、逻辑任务、模型/工具预算和验收纠正；耗尽预算拒绝继续，旧文件证据在新运行重新登记。 |
| T10 | 同一目录的重复登记及 Git 子目录共享租约；不同仓库并发，原账号记录不跨账号读取。 |
| T11 | OS 锁及持有者残留核对；很旧的另一账号标记不会因超时自动释放。宿主清理未确认且工具终态缺失时仍保持租约。不是针对多套不同数据根执行器的全机锁保证。 |
| T12 | 起始 dirty、Agent 写入后的用户修改与任务操作分开；回滚拒绝覆盖用户新内容。 |
| T13 | 真实 Git 创建 detached worktree、无未提交内容搬运、幂等请求、非法 ref、dirty 清理拒绝及干净清理。未完成崩溃创建目录的自动修复或所有平台路径别名测试。 |
| T14 | 检查点摘要/格式、数据库未来版本、模型配置/能力变化均失败关闭；宿主能力核验沿 S4 测试。没有部署新旧宿主安装组合。 |
| T15 | 前端状态投影、重复帧与既有断线快照测试；浏览器验证追加、暂停、继续、取消、关联新 run 和审查。真实应用强退后重开并恢复的 Tauri 整体链未验收。 |

## 变更文件

| 文件 | 变更 |
| --- | --- |
| `src/private_agent_local/recovery.py` | 新增检查点、模型能力摘要、控制记录和恢复核对。 |
| `src/private_agent_local/run_controls.py` | 新增持久化控制、安全边界、消息生效、代次及暂停取消协调。 |
| `src/private_agent_local/workspaces.py` | 新增 OS 锁、租约、队列及受管理 worktree。 |
| `src/private_agent_local/run_review.py` | 新增任务归属审查及命令候选变化。 |
| `src/private_agent_local/store.py` | schema 7、所有权锁、事件检查点事务和启动恢复。 |
| `src/private_agent_local/runtime.py` | 协商、关联运行、生命周期、工作区调度及审批保护。 |
| `src/private_agent_local/core_adapter.py` | 模型尝试/响应检查点、迟到响应、工具安全边界及成功结果判断。 |
| `src/private_agent_local/context_manager.py` | 累计预算、能力核对和新约束进入上下文。 |
| `src/private_agent_local/completion.py` | 旧操作重新核对登记证据、累计纠正限制和迟到结果防护。 |
| `src/private_agent_local/execution_sessions.py` | 启动取消、批量停止、保留进程租约和候选变化。 |
| `src/private_agent_local/execution_tools.py` | 代次守卫与命令基线。 |
| `src/private_agent_local/app.py` | 控制、恢复、审查、worktree API 及直接写入协调。 |
| `apps/desktop/src/features/coding/api/recovery.ts` | 新增控制和恢复类型、API。 |
| `apps/desktop/src/features/coding/components/RecoveryPanel.vue`、`RecoveryPanel.spec.ts` | 新增恢复协作面板与回执、版本冲突、生命周期测试。 |
| `apps/desktop/src/features/coding/components/WorktreePanel.vue` | 新增显式创建/清理和全局确认。 |
| `apps/desktop/src/features/coding/components/CodingHome.vue`、`CodingThreadWorkspace.vue` | 接入 worktree/恢复面板、协商和新运行关联。 |
| `apps/desktop/src/features/coding/components/ThreadHeader.vue` | 新增状态图标。 |
| `apps/desktop/src/features/coding/model/runContracts.ts`、`runOutcome.ts`、`runProjector.ts`、`runProjector.spec.ts` | paused/queued/interrupted 生命周期、投影和测试。 |
| `apps/desktop/e2e/coding-run.spec.ts` | 新增 S5 浏览器控制与关联恢复流程。 |
| `tests/unit/test_local_recovery.py` | 新增 35 项恢复、控制、并发、Git 和进程故障专项。 |
| `tests/coding_acceptance/recovery_process.py` | 新增真实进程退出的边界注入助手。 |
| `tests/unit/test_local_store.py`、`test_local_context_history.py`、`test_local_patchsets.py` | 适配 schema 7 迁移夹具及 Store 所有权锁，保留旧行为断言。 |
| `tests/coding_acceptance/test_baseline.py`、`scripts/run_coding_validation.py` | 新能力断言及 recovery 验证入口。 |
| 本报告、同目录 `README.md`、`s5-recovery-steering-and-review.md`、`docs/unified-desktop-runtime.md` | 同步实现、schema、支持边界、实际测试和剩余验收。 |

## 项目记忆与后续操作

已完整读取 `docs/project-state.md`，并核对 `AGENTS.md`、S4 报告和统一客户端说明。项目记忆的 2026-08-31 路径/HEAD/能力是历史快照，和当前 `F:\Program\Agent`、`d0250ee` 及 S4/S5 源码不同；以本轮 Git、调用路径及隔离测试核实，未把历史状态当作当前部署事实。

依照项目入口“仅在用户明确要求新增或更新项目记忆时维护 `docs/project-state.md`”的专门约定，本轮没有改写该历史记忆，也没有建立新的记忆系统。持久信息同步到现有路线、统一客户端说明和本阶段报告；设计文档保留原验收目标，明确其与实际完成范围的区别。所有日志和故障现场留在被忽略的测试目录，没有写入记忆。

本轮源码交付无需用户执行额外操作。若要在已安装客户端获得功能，仍需按独立交付任务验证匹配的前端/本机服务/宿主并构建安装；本轮没有执行这些操作。S6 及 M2 放行前还需完成真实安装升级、Tauri 强退重启流程、真实 Provider、平台身份与路径边界及性能验收。未知副作用现场须保留并核对，不能通过删库、清除租约、强制 Git 清理或重放命令来制造“可恢复”状态。
