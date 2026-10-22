# 任务恢复改造验收记录（2026-10-22）

结论：**整体验收未通过。发现 1 项 P1 和 4 项 P2，需修正后复验。** 当前测试通过能证明已覆盖的路径可用，不能支持计划书第 15 节“M0–M5 均已验证完成”的整体结论。

本次依据 [改造计划书](F:/Program/Agent/docs/analysis/2026-10-21-task-recovery-improvement-plan.md) 核对当前源码、相关差异和隔离测试。验收对象为 `dev/1.0.0`、HEAD `87a8331` 上的未提交改动；工作区还存在上下文、记忆等其他改动。本轮没有修改业务源码、既有测试、计划书实施记录或项目状态记忆，没有提交、发布或调用真实模型。

## 1. 阶段判定

| 阶段 | 本轮结论 | 依据与限制 |
| --- | --- | --- |
| M0 基线与隔离 | 当前检查完成 | 核对 Git 状态、差异、计划及隔离入口；本轮未重演改造前的 44 项历史基线。 |
| M1 活动计时 | 本轮覆盖范围通过 | 当前恢复套件 73 项通过，包含新增计时 6 项、旧记录与故障边界用例；未验证真实已安装应用跨日重开。 |
| M2 未知现场核对 | **未通过** | 文件核对错误扩大范围、陈旧核对继续生效；人工处理结果与 MCP 执行门禁不一致，见 R1、R2。 |
| M3 失败及模型续跑 | **未通过** | 同一 profile 新配置不能显式接受；能力预检误拒绝合法任务，见 R3、R4。 |
| M4 恢复界面 | **部分通过** | 组件及浏览器夹具通过；390px 实际截图出现挤压和裁切，见 R5。后端闭环问题也影响完整用户路径。 |
| M5 故障回归与交付 | **未通过整体验收** | 已有用例没有捕获本轮反例；补充回归后需重新核对阶段状态。 |

## 2. 必须修正的问题

### R1 · P1：文件核对会放行其他文件，且内容变化后旧决定仍有效

位置：[recovery.py:45](F:/Program/Agent/src/private_agent_local/recovery.py:45)、[recovery.py:318](F:/Program/Agent/src/private_agent_local/recovery.py:318)、[recovery.py:487](F:/Program/Agent/src/private_agent_local/recovery.py:487)。

`covers()` 在 `item_id` 不同时，仍按同一个 `operation_id` 认定核对记录覆盖当前项。一组补丁中的不同文件共享操作标识，核对 A 因而会解除 B 的阻塞。报告派生时只检查该覆盖关系，没有复核当时的文件内容和身份；核对记录也没有保存该项完整的观察证据绑定。

隔离探针复现了两种情况：

1. 同一补丁有 `a.txt`、`b.txt` 两项，B 当前为第三种冲突内容。只核对 A 后，B 仍是 `observation=conflict`，却被标记 `status=resolved`，整个报告 `can_resume=true`。
2. A 当前匹配写前内容，提交机器观察后，再由外部改成第三种内容。刷新后 A 为 `observation=conflict`、`resolvable=false`，但仍是 `status=resolved`、`can_resume=true`。

这违背计划 7.2 的“多个文件逐项核对”及“第三种内容继续阻塞”。本轮证明的是恢复资格被错误放行，没有进一步执行写入，也没有声称已经发生文件覆盖。

修正要求：文件决定按具体补丁变更和路径绑定，不能用共享操作标识覆盖整组；记录并复核内容摘要及必要的文件/目录身份。现场变化后，旧机器观察仍可保留作审计，但必须失去放行当前现场的效力。

复验标准：上述两个反例均保持 B/变化后的 A 为 open、`can_resume=false`；分别核对合法项才解除各自阻塞。重启、再次续跑及多文件部分落盘后仍成立。

### R2 · P2：MCP 人工核对后报告允许续跑，但新操作仍被旧未知范围拦截

位置：[recovery.py:318](F:/Program/Agent/src/private_agent_local/recovery.py:318)、[runtime.py:348](F:/Program/Agent/src/private_agent_local/runtime.py:348)、[integration_mcp.py:394](F:/Program/Agent/src/private_agent_local/integration_mcp.py:394)、[completion.py:98](F:/Program/Agent/src/private_agent_local/completion.py:98)。

恢复报告读取 `recovery_resolutions`，人工说明可以解除对应项对续跑资格的阻塞；子运行却原样继承 `uncertain_operations`，MCP 门禁继续只按来源及工具名判断，不读取处理决定，也不区分原调用和新参数。

探针使用带 `tool_version`、`arguments_sha256` 的新格式执行记录，通过实际 `reconcile_mcp_execution()` 生成未知操作，再提交人工核对并创建关联子运行。结果为：父报告 `can_resume=true`，原执行有参数指纹，新请求参数指纹不同，但同一来源/工具的范围仍被拒绝。调用点在发送请求前会返回 `execution_unknown`；本轮没有发起任何外部 MCP 请求。

计划 7.3 要求报告、工具防护和租约等使用一致的处理结论，同时禁止重发已处理的原操作。对于缺少可靠指纹的旧记录，计划允许保守限制；本项针对有指纹的新记录，并不要求放宽旧记录。

修正要求：复用一个可审计的处理结果派生逻辑；保留未知原始事实，把原调用身份加入禁止重发判定，不能持续封锁该工具所有新参数。旧记录缺信息时继续保守，并在报告和界面说明剩余范围限制。

复验标准：有完整身份的新记录核对后，原参数换 `run_id/call_id` 仍不能自动重发；新的独立参数在原权限和审批链下可执行；旧记录缺指纹时显示保守阻塞。至少以受控 MCP 连接替身验证实际工具入口，不能只断言报告的 `can_resume`。

### R3 · P2：同一 profile 修改配置后，预览与提交不一致，界面没有接受入口

位置：[recovery.py:420](F:/Program/Agent/src/private_agent_local/recovery.py:420)、[recovery.py:542](F:/Program/Agent/src/private_agent_local/recovery.py:542)、[RecoveryPanel.vue:242](F:/Program/Agent/apps/desktop/src/features/coding/components/RecoveryPanel.vue:242)。

预览仅用 profile ID 是否变化决定 `switched`。提交只有目标 ID 不同才校验显式接受及预览摘要；同 ID 始终走旧配置严格校验。界面同时禁止为当前 ID 点击“预览差异”。

隔离复现：为原运行保存旧 endpoint 的配置版本，再将同一 profile 的 endpoint 改成另一个合成地址。只读预览返回 `eligible=true`、`switched=false`、不要求接受模型变化；携带该预览摘要和 `accept_model_change=true` 提交校验，仍报 `模型配置已变化或不可用，未切换模型恢复`。

这缺失了计划 8.2 明确要求的“选择同一 profile 的新配置或另一个模型，核对差异后继续”。

修正要求：将配置/能力版本变化纳入显式交接判断；同 ID 新配置提供差异预览和接受入口。差异应基于原运行已记录事实，不能把当前配置同时作为变更前和变更后。提交及首次执行还需绑定所接受的目标版本。

复验标准：不接受时继续阻塞；接受有效预览后能关联续跑；预览后目标配置再次变化会冲突并要求刷新；旧运行和历史不改写。

### R4 · P2：能力预检将累计用量当成上下文容量，并将所有附件当成图片

位置：[recovery.py:404](F:/Program/Agent/src/private_agent_local/recovery.py:404)。附件现有元数据依据：[attachments.py:132](F:/Program/Agent/src/private_agent_local/attachments.py:132)。

`capability_gaps()` 使用整个逻辑任务的累计 `input_tokens + output_tokens` 比较目标模型单次 `context_tokens`。例如累计输入 200000、输出 50000，就会拒绝 128000 窗口模型，即使当前压缩后待发上下文很小。累计预算与单次窗口是不同约束。

该函数还仅凭存在 `attachment_ids` 就要求视觉能力；纯文本附件已有 `requires_vision=false`，仍会错误阻止切到文本模型。两个分支均由隔离探针直接调用实际实现复现，未调用模型。

修正要求：容量检查复用当前实际待发请求及压缩后的上下文预算口径；累计用量仍独立继承。视觉要求读取附件类型和 `requires_vision` 等现有元数据。

复验标准：累计用量较大、当前上下文可容纳的任务允许预览；真实必需上下文超限仍阻止；纯文本附件允许文本模型，图片附件缺视觉能力仍阻止；结构化输出和工具能力检查保持有效。

### R5 · P2：390px 窄窗口截图不满足可读性，现有测试误判通过

位置：[task-recovery.spec.ts:168](F:/Program/Agent/apps/desktop/e2e/task-recovery.spec.ts:168)；恢复面板布局：[RecoveryPanel.vue:276](F:/Program/Agent/apps/desktop/src/features/coding/components/RecoveryPanel.vue:276)。

按用例自身流程，在宽窗口打开恢复现场，再缩到 390×844。实测截图中工作区左侧仍留有约 200px 空间，恢复面板被压到很窄，长按钮被裁切、说明严重折行。现有断言只检查根节点 `scrollWidth` 和按钮 `toBeVisible()`；外层裁切或内层滚动仍能让断言通过，不能证明按钮、确认文本完整可读。

这是当前验收页面的观察结果，外层既有布局可能也参与成因；本轮不把全部布局问题归因于新增恢复代码。但计划第 9 节“界面验收”的 390px 标准尚未满足。

证据：[390px 截图](F:/Program/Agent/.run/task-recovery-acceptance-20261022/browser-results/task-recovery-窄窗口保持恢复面板可读且不横向溢出-chromium/test-finished-1.png)。宽窗口截图中的恢复说明与人工核对入口可读。

修正要求：在窄窗口为恢复现场提供足够内容宽度，按钮和输入框在可用宽度内重排；验证内层容器的裁切和实际交互。浏览器测试应检查关键控件的边界、完整文本及可点击性，并复核截图，不能仅以根节点无滚动作为通过条件。

复验标准：重新运行原宽→窄流程及直接以窄窗口进入，两种情况下核对输入、提交、模型预览与继续按钮均可完整阅读和操作，不横向裁切。

## 3. 本轮实际执行的检查

| 检查 | 本轮结果 | 证据边界 |
| --- | --- | --- |
| `--suite recovery` | **73 passed，93.34s** | 隔离 SQLite、合成项目及受控模型；含已有子进程故障边界。 |
| `useRunStream.spec.ts`、`RecoveryPanel.spec.ts`、`PatchReviewPanel.spec.ts` | **30 passed** | 16+8+6；组件与状态逻辑。 |
| `e2e/task-recovery.spec.ts` | **4 passed，10.5s** | 独立 Vite 1449 端口、浏览器路由夹具；保存截图及 trace。截图复核产生 R5。 |
| `npm run build` | **通过** | `vue-tsc` 和 Vite 构建通过；有产物块超过 500KB 的提示。 |
| `protocol_codegen.py --check` | **通过** | `protocol codegen in sync: OK`。 |
| 本轮额外隔离探针 | **正常执行并复现上述后端反例** | 探针退出 0 表示完成采集，不表示产品验收通过。 |

复现命令如下。前两项在仓库根目录运行，前端命令在 `apps/desktop` 运行：

```powershell
.venv\Scripts\python.exe -u -B scripts/run_coding_validation.py --suite recovery
.venv\Scripts\python.exe -B scripts/protocol_codegen.py --check

node node_modules/vitest/vitest.mjs run src/features/coding/composables/useRunStream.spec.ts src/features/coding/components/RecoveryPanel.spec.ts src/features/coding/components/PatchReviewPanel.spec.ts --maxWorkers=2 --minWorkers=1
node node_modules/@playwright/test/cli.js test e2e/task-recovery.spec.ts --config .run/task-recovery-acceptance-20261022/playwright.config.ts --retries=0
npm run build
```

临时浏览器配置继承原配置，仅固定独立端口、输出目录并打开截图/trace；它和探针均位于已忽略的 `.run`，没有改写既有测试。

探针命令（仓库根目录）：

```powershell
.venv\Scripts\python.exe -u -B .run/task-recovery-acceptance-20261022/acceptance_probe.py probe
```

当前证据：

- [后端套件结果](F:/Program/Agent/.run/coding-agent-validation/recovery-4da9e530beda474abe8cf8a2c43ae22e/pytest-result.json)。
- [探针脚本](F:/Program/Agent/.run/task-recovery-acceptance-20261022/acceptance_probe.py)。
- [最终探针结果](F:/Program/Agent/.run/task-recovery-acceptance-20261022/probe-43622dcdf0494b7db43ca98704dcdea6/probe-results.json)。
- [浏览器配置](F:/Program/Agent/apps/desktop/.run/task-recovery-acceptance-20261022/playwright.config.ts)。

沙箱内首次后端测试未进入业务逻辑，诊断栈停在 Windows `asyncio` 初始化 `_make_self_pipe → socket._fallback_socketpair → accept`；中止后，经本机执行审批，以相同隔离入口运行得到上述最终结果。首次浏览器沙箱启动也未完成；最终使用独立 1449 端口运行完成。未把这些环境阻塞记为产品测试失败。

## 4. 证据解释与未验证范围

- 本轮没有重跑首轮实施记录中的 execution、repository、mcp-memory-boundaries、completion、context-alignment、orchestration 全套，原记录的数量不是本轮结果。发现阻塞后不以扩大测试数量替代缺陷修正。
- 未验证真实供应商、真实外部 MCP 写入、真实用户库、原生已安装桌面、安装升级与真实进程跨日恢复；本轮浏览器通过不代表这些环境通过。
- 探针额外观察到：切换模型后再按当前模型续跑，子运行缺少前次 `model_handoff`，上层公开投影返回 `native_same_model`。该结果只证明上层元数据/投影判断不连续。[Responses 适配器](F:/Program/Agent/src/private_agent_core/llm/responses.py:91) 仍有按 endpoint、模型和凭据路由摘要过滤不透明状态的防护，因此**本轮没有证明旧状态实际跨路由发出，也不将该探针结果直接认定为数据泄漏**。修正 M3 时应补上连续两次恢复的真实出站组装回归。
- 按仓库约定，本轮仅新增此验收报告；不自动更新 `docs/project-state.md` 或用户级记忆。原有未提交工作全部保留。

## 5. 交给实施者的修正顺序与完成条件

先修 R1，补多文件逐项核对和核对后外部变化的回归；随后修 R2，贯通实际 MCP 门禁与核对结论。再修 R3、R4，覆盖同 ID 新配置和正确的上下文/附件能力预检，最后修 R5 并重新检查宽、窄窗口截图。

每项先用本报告反例验证失败，再修到通过；继续使用现有隔离入口和测试框架，不引入依赖或数据库迁移。保留原执行未知事实、预算、失败次数及原权限链；不能通过删除未知记录或放宽所有门禁来换取通过。

本报告列出的反例及受影响既有测试均通过、浏览器真实交互和截图满足要求后，重新提交验收，并据新证据更正计划书第 15 节的阶段状态。当前不能将整体改造标为已验收。
