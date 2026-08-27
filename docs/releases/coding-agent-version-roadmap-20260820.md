# PrivateAgent Coding Agent 版本路线图（v0.6.0–v1.0.0）

> **路线更新（2026-08-24）：** v0.6.0–v0.9.0 的历史拆分与门禁继续有效；
> v0.9 已进入功能范围封版，见 [封版决议](./v0.9.0/v0.9.0-freeze-decision-20260824.md)。
> 本文件中把 v1.0 定义为“7–10 天稳定发布收口”的内容已失效；v1.0 现为
> Agent 架构代际升级，见 [新开发计划](./v1.0.0/v1.0.0-agent-rearchitecture-plan-20260824.md)。

> 制定日期：2026-08-20
> 规划基线：`0.5.0-rc.4`（`9250da6`，数据库 schema `0026`）
> 正式实施基线：`v0.5.0-rc.4` 冻结工程基线，可直接进入 `v0.6.0`
> 总体方案：[Coding Agent 重构计划](../coding-agent-refactor-plan.md)
> 观察策略：[观察期顺延决策](./observation-policy-20260820.md)

## 1. 路线结论

Coding Agent 重构拆分为五个连续的次版本，不在单一版本中同时改写数据模型、执行工具、桌面 UI 和发布默认值：

| 版本 | 主题 | 主要交付 | 预计开发量 |
|---|---|---|---:|
| `v0.6.0` | Coding 领域与运行事实底座 | ProjectWorkspace、project-bound run、真实计划、可续读事件 | 8–12 个工作日 |
| `v0.7.0` | 可信编码执行 MVP | 多文件补丁、项目命令、验证、Artifact、权限/模型 profile | 10–15 个工作日 |
| `v0.8.0` | Coding Workbench | 新侧栏、首页、任务页、计划浮层、输入器、前端状态收敛 | 10–15 个工作日 |
| `v0.9.0` | 默认切换与可靠性 | 新 UI 默认、恢复与故障注入、可选 worktree、兼容归零 | 8–12 个工作日 |
| `v1.0.0` | Agent 架构代际升级 | Agent Core、Thread/Turn/Item、版本化协议、统一工具生命周期、Windows 沙箱、迁移与正式发布 | 16–19 周（2 人）+ 14 天 RC 观察 |

v0.6.0–v0.9.0 的原开发量估算保留为历史记录。v1.0 的全面改造单独估算：
单人 24–32 周；2 人 + QA/安全兼职 16–19 周；3 人 12–15 周，均另加
14 天 RC 观察。详见新计划 §21。

## 2. 版本规范

### 2.1 SemVer 与预发布节点

沿用仓库现有 SemVer 规则：

```text
X.Y.Z-alpha.N → X.Y.Z-beta.N → X.Y.Z-rc.N → X.Y.Z
```

- `alpha`：契约和主体实现允许继续演进，只发布内部检查点。
- `beta`：版本范围完整，主要处理集成、迁移和体验问题。
- `rc`：功能冻结，只修复阻断缺陷并收集绑定证据。
- 中间开发完成版：RC 即时门禁通过，形成内部里程碑，不切公开 updater。
- 公开稳定版：仅 `v1.0.0` 在最终观察通过后发布正式 Release 并切换 updater。

`v0.5.0`–`v0.9.0` 均不等待自然日，只等待自动化、真实项目/安装版 smoke 和绑定证据。全部功能、文档和发布物开发完成后，`v1.0.0-rc.1` 执行唯一一次 14 个自然日整体观察。

中间 RC 代码修改必须升 `rc.N+1` 并重新执行即时门禁；`v1.0.0-rc.1` 冻结后发生功能代码修改，则升 RC 并从 Day 1 重新开始最终观察。

### 2.2 文档命名

开发计划：

```text
docs/releases/vX.Y.Z/vX.Y.Z-development-plan-YYYYMMDD.md
```

完成某个实际节点后才创建检查点：

```text
docs/releases/vX.Y.Z/vX.Y.Z-alpha.1-checkpoint-YYYYMMDD.md
docs/releases/vX.Y.Z/vX.Y.Z-beta.1-checkpoint-YYYYMMDD.md
docs/releases/vX.Y.Z/vX.Y.Z-rc.1-checkpoint-YYYYMMDD.md
```

检查点必须绑定真实 commit、版本、数据库 revision、测试计数、安装包 SHA、flag 快照和已知问题。计划书不能代替检查点，也不预先创建空检查点。

### 2.3 版本源同步

每次预发布和稳定升版至少同步：

- `src/personal_assistant/__init__.py`
- `pyproject.toml`
- `apps/desktop/package.json`
- `apps/desktop/package-lock.json`
- `apps/desktop/src-tauri/tauri.conf.json`
- `apps/desktop/src-tauri/Cargo.toml`

`release-check-full` 必须确认版本一致、证据绑定当前 HEAD、installer 与版本匹配。预发布版本不得覆盖正式 `latest.json`；稳定版发布后才切换公开更新通道。

### 2.4 分支与冻结

- 使用短期责任分支或小 PR，不保留长期不可运行的集成分支。
- 同一 PR 不同时修改无关后端契约和多个大型页面。
- 共享 Schema、DTO、事件和设计 token 先合入，调用方随后迁移。
- 中间 RC 冻结后如需功能修复必须升 RC 并重新绑定证据；门禁通过即可进入下一版本。
- 最终 `v1.0.0` RC 冻结后不再提交功能改动；仅允许追加明确声明为非候选代码的观察文档。
- 下一版本开发从上一开发完成版或明确冻结的 RC 另建分支。

## 3. 版本依赖

```text
v0.5.0-rc.4 工程基线
  └── v0.6.0 Coding 事实底座
        └── v0.7.0 可信编码执行
              └── v0.8.0 Coding Workbench
                    └── v0.9.0 默认切换与可靠性
                          └── v1.0.0 Agent 架构代际升级与稳定发布
```

硬依赖：

- `v0.7.0` 不得重新定义 `v0.6.0` 已冻结的 ProjectWorkspace、RunPlan 和事件标识。
- `v0.8.0` 只消费 `v0.6.0`/`v0.7.0` 公开 DTO，不在组件内补第二套状态机。
- `v0.9.0` 只有在新旧主链 E2E 均可解释、旧调用可观测时才能切默认值。
- `v1.0.0` 以 v0.9 封版提交为基线重建 Agent Core、公共协议、统一工具生命周期
  和 Windows 沙箱；旧链隔离、硬化、迁移、文档和发布并入改造末端。

## 4. 跨版本迁移策略

### 4.1 数据库

- 所有迁移采用 additive 策略：先新增、再双写、再切读，最后独立清理。
- `v1.0.0` 之前不物理删除旧会话、旧 AgentTask、旧 ToolCall 或个人助手业务表。
- 大回填分批、幂等、可续跑，不持有长事务。
- 每个版本在主数据库副本完成升级和旧应用回退演练；应用回退不自动执行破坏性 schema downgrade。

### 4.2 API 与事件

- 新字段先可空并保持旧客户端可忽略。
- 新 UI 只能消费公开事件，不根据文案、消息数量或工具名称猜状态。
- 兼容 API 带弃用标记和低基数 telemetry；v1.0 RC 默认禁用但不物理删除，最终观察后的独立版本再评估清理。
- Token delta 可以临时传输，最终消息、计划、审批、执行结果和 Artifact 必须有 durable 事实。

### 4.3 桌面 UI

- 不新增永久 `ui_v3` 分支；在现有 v2 壳上逐步替换主工作区。
- `v0.8.0` 内部阶段保留回退，`v0.9.0` 新 UI 默认，`v1.0.0` 默认隔离已归零的旧壳并保留显式诊断回退。
- 组件不直接调用 HTTP、Tauri invoke、文件或系统能力。
- 不新增 Router、Pinia、Tailwind、Ant Design Vue 或 VueUse，除非单独立项并完成依赖评审。

## 5. 跨版本质量门禁

每个 beta/RC 至少执行：

- Ruff、compileall、Python 全量测试。
- Vue TypeScript、生产构建和 Vitest。
- Playwright 功能、视觉、可访问性、性能和资源清理。
- Cargo check/test。
- Alembic current、upgrade、数据库 clone 和应用回退 smoke。
- sidecar、认证、进程清理和安装版 smoke。
- release-check-full、manifest、flag 快照、SHA 和诊断脱敏。

跨版本零容忍问题：

- 数据损坏或不可恢复部分迁移。
- 同一请求产生多个有效 run。
- 重复工具副作用。
- 审批绕过、参数替换、token 重放或权限扩大。
- 路径穿越、符号链接/重解析点逃逸。
- 取消/超时/退出后残留模型或工具进程。
- 失败或未验证结果被展示为成功。
- Secret、完整敏感文件或未脱敏命令输出进入日志、Vue、报告或通知。
- 关闭 feature flag 后无法回退。

## 6. 发布节点总表

| 版本 | 预发布链 | 自然日观察 | 完成标志 |
|---|---|---:|---|
| `v0.6.0` | alpha.1 → alpha.2 → beta.1 → rc.1 → 内部完成版 | 无 | Project-bound run 与真实计划即时门禁通过 |
| `v0.7.0` | alpha.1 → alpha.2 → beta.1 → rc.1 → 内部完成版 | 无 | 可信编码执行主链即时门禁通过 |
| `v0.8.0` | alpha.1 → alpha.2 → beta.1 → rc.1 → 内部完成版 | 无 | 新工作台功能、视觉与资源门禁通过 |
| `v0.9.0` | alpha.1 → beta.1 → beta.2 → rc.1 → 内部完成版 | 无 | 新主链默认、恢复和兼容 telemetry 可解释 |
| `v1.0.0` | alpha.1 → alpha.2 → beta.1 → beta.2 → rc.1 → stable | 14 天 | Agent v2 主链、迁移回退、契约冻结与正式发布完成 |

## 7. 版本计划入口

- [v0.6.0：Coding 领域与运行事实底座](./v0.6.0/v0.6.0-development-plan-20260820.md)
- [v0.7.0：可信编码执行 MVP](./v0.7.0/v0.7.0-development-plan-20260820.md)
- [v0.8.0：Coding Workbench](./v0.8.0/v0.8.0-development-plan-20260820.md)
- [v0.9.0：默认切换与可靠性](./v0.9.0/v0.9.0-development-plan-20260820.md)
- [v1.0.0：Agent 架构代际升级](./v1.0.0/v1.0.0-agent-rearchitecture-plan-20260824.md)

## 8. 路线完成定义

`v1.0.0` 发布后应同时满足：

1. 产品主线为 Project/Workspace + Thread → Turn → Item。
2. 前端只通过版本化协议驱动 Agent，不参与模型或工具决策循环。
3. 消息、计划、工具、审批、验证和 Artifact 均为可重放的 typed Item/durable fact。
4. Coding Agent 可以读取、修改、验证并报告一个真实项目任务。
5. 权限、审批和 OS 沙箱边界分离；模型、Git、路径和进程可审计、可取消、可恢复。
6. 新工作台默认启用，旧 planner 与旧 UI 达到默认隔离和最终观察门槛。
7. 从 `v0.5.0-rc.4` 和 `v0.9.0` 内部完成版的升级、数据保留和应用回退通过。
8. `v1.0.0-rc.1` 完成唯一一次 14 天整体观察且没有未处置 P0/P1。

## 9. Post-1.0 边界

以下方向不纳入本路线的版本承诺，`v1.0.0` 后按真实需求另立计划：

- 自动化任务与计划执行。
- 插件市场和第三方连接体验。
- GitHub/GitLab PR 发布。
- 多 Agent 协作。
- 完整内置终端、LSP 和调试能力。
- macOS/Linux 正式支持。
- 云同步和团队协作。
- 最终观察通过后，对旧 planner、旧 UI 和兼容 API 的物理删除。
