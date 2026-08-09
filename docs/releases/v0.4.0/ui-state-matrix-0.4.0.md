# PrivateAgent 0.4.0 UI 状态矩阵（D0）

> 基线：`0.3.0-alpha.2`；唯一后端事实源：[`v0.3.0-public-contracts.md`](../v0.3.0/v0.3.0-public-contracts.md)
> 用途：D1 设计系统状态映射、D3 Agent 工作流、UI Lab 场景、D6 验收核对。
> fixture 实现：`apps/desktop/src/dev/uiStateFixtures.ts`（真实类型，非独立演示组件）。

## 1. Agent 任务全局状态（`AgentTaskState`）

| 状态 | 触发 | 顶栏/导航表达 | 活动流表达 | 用户可做的主操作 |
|---|---|---|---|---|
| idle | 无消息或无活动 | 状态徽标"就绪"（neutral） | 空状态引导 + 任务输入 | 输入并发送 |
| running | streaming 或工具 approved/running | "正在执行"（info，旋转图标） | 流式 token 追加、工具卡更新 | 停止 |
| waiting | 存在 pending 审批 | "等待确认"（warning） | 审批卡高优先级置顶原位展示 | 批准 / 拒绝 / 查看详情 |
| completed | 助手有最终内容且不在流式 | "已完成"（success） | 结果块 + 产物入口 | 继续追问 / 保存产物 |
| failed | 工具 failed 或 SSE error | "执行失败"（danger） | 错误块：原因/影响/已完成/恢复动作 | 重试 / 查看诊断 |
| stopped | 用户停止 | "已停止"（neutral） | 停止标记，区分"正在请求停止/已停止" | 重新发送 |

## 2. 计划步骤状态（`WorkspaceStepStatus`）

pending（待处理/neutral）、running（进行中/info）、completed（已完成/success）、blocked（等待确认/warning）、failed（失败/danger）。
计划步骤与活动流关联：点击步骤定位对应活动（D3）。

## 3. 工具调用状态（`ToolCallStatus`，legacy planner）

pending_approval → approved → running → succeeded / failed / rejected / cancelled。
卡片必须显示：动作摘要、对象/路径/命令范围、授权原因、风险等级（safe/confirm/risky）、可撤销性、批准/拒绝/详情。

## 4. Agent Run 审批状态（`AgentRunApproval.status`，Runtime）

pending / approved / rejected / consumed / expired / cancelled。
- 批准后卡片**原位**转为"已批准/执行中"，不得从活动流消失后异地重现；
- expired/cancelled 给出恢复入口（重新发起审批）；
- consumed 为终态，仅保留审计痕迹。

## 5. SSE 连接与恢复状态

| 场景 | 表达 | 恢复 |
|---|---|---|
| sidecar 断开 | 状态栏红色 + InlineNotice 横幅 | 自动重连 + 手动重试 |
| Ollama 离线 | 状态栏黄色 + 聊天内联提示 | 状态页修复动作入口 |
| 断线后恢复 | 重连成功后按 run id 续传，不伪造终态 | 恢复提示一次性出现 |
| 输出验证失败 | 错误块含验证原因 | 重试生成 |
| RAG 引用拒答 | 结果块标注"未找到可信来源" | 引导导入文档或改用普通模式 |

## 6. 消息/内容类型（活动流条目）

user（简洁任务输入，不过度气泡化）、agent 解释（正文）、plan（独立步骤列表）、tool（动作摘要+可展开参数结果）、approval（高优先级确认卡）、change/Diff（文件数+增删行+查看入口）、log（默认折叠技术区）、result（高层级结果块+产物）、error（原因/影响/恢复）。

## 7. 右侧上下文栏状态（D3 四 tab）

| Tab | 内容 | 空态 |
|---|---|---|
| Files | 授权路径、修改状态、Diff 入口 | "尚未授权文件" |
| Context | 会话上下文、模型、模式、限制、附件 | 会话元信息 |
| Sources | RAG 来源、引用、可信状态 | "本回答未使用知识库来源" |
| Artifacts | 文档/代码/图片/报告/导出 | "任务完成后产物出现在这里" |

右栏内容必须与当前任务绑定；无当前任务时不展示无关全局信息。

## 8. 页面级通用状态（每个业务页必须覆盖）

empty / loading（>500ms 才显示加载态）/ error（原因+重试）/ success / 权限不足（授权引导）。
键盘与焦点、窄窗口（<960px）、reduced-motion 为每页必查项。

## 9. 启动流程状态

`检查配置 → 启动 sidecar → 检查能力 → 进入工作台`。
- checking/starting：>500ms 才显示加载态，避免闪屏；
- wizard：首次配置 / 重新配置；
- error：说明失败依赖、是否影响本地数据，提供 重试 / 重新配置 / 打开诊断 / 退出，不堆叠原始异常。

## 10. 通知与全局反馈

Toast（成功/失败瞬时反馈）、ConfirmDialog（破坏性操作）、NotificationCenter（异步完成/系统事件）、CommandPalette（Ctrl/Cmd+K）、GlobalSearch。
层级：toast > dialog > palette/search > inspector > 内容。触发规则：用户动作即时结果用 Toast；后台异步事件入通知中心；不可逆操作必须 ConfirmDialog。

## 11. fixture 覆盖核对

| fixture | 覆盖状态 |
|---|---|
| `emptyWorkspace` | idle / 空任务 |
| `planningWorkspace` | 正在规划（legacy planner） |
| `streamingWorkspace` | 流式回答 running |
| `toolRunningWorkspace` | 工具执行 running |
| `approvalPendingWorkspace` | waiting（Runtime 审批） |
| `legacyToolPendingWorkspace` | waiting（legacy 工具审批） |
| `approvalResolvedWorkspace` | 批准后 consumed + 最终结果 |
| `failedWorkspace` | 工具 failed + 错误块 |
| `stoppedWorkspace` | stopped |
| `ragAnswerWorkspace` | RAG 来源 + Sources tab |
| `ragRefusalWorkspace` | RAG 拒答 |
| `reconnectingWorkspace` | sidecar 断开/重连提示 |
| `completedWithArtifactsWorkspace` | completed + 多产物 Artifacts |
