# 2026-09-21 对话入口、模型身份与更新修复

> 后续界面调整：用户进一步要求紧凑排列“上下文 → 模型 ID → 模型强度”，强度使用滑杆浮层，上下文浮层显示已用比例与标记数。此前截图中的超长名称是溢出测试使用的模拟 ID，已改用 `deepseek-flash` 和 `qwen-3.8-flash` 示例；当前界面只显示配置中的模型 ID。下文保留原轮次的测试记录，当前交互以[工作台说明](../workbench-guide.md)为准。

## 本轮模型栏调整

已按新参考图实现紧凑模型栏。显示字段只取 `model_name`，不拼接供应商、日期或上下文属性，也不通过截断字符串改变实际模型 ID。强度滑杆只呈现模型声明的档位，支持键盘调整与恢复默认；切换模型时清除其不支持的档位。上下文浮层显示已用比例、已用标记和总容量，保留估算标识、未知状态、异常反馈与会话切换后的旧回执隔离。

本轮相对任务开始时的文件快照修改以下 12 个文件，保留原有未提交工作：

| 文件 | 本轮修改 |
| --- | --- |
| [CodingComposer.vue](../../apps/desktop/src/features/coding/components/CodingComposer.vue) | 紧凑控件顺序、纯模型 ID、接入强度滑杆与能力切换 |
| [ModelStrengthPicker.vue](../../apps/desktop/src/features/coding/components/ModelStrengthPicker.vue) | 新增强度浮层、分档滑杆、恢复默认及焦点处理 |
| [ContextUsageRing.vue](../../apps/desktop/src/features/agent/ContextUsageRing.vue) | 上下文圆环、悬浮用量、新会话空态及请求和监听清理 |
| [contextRing.ts](../../apps/desktop/src/features/agent/model/contextRing.ts) | 不完整或非数值的计量结果按不可用处理 |
| [CodingComposer.spec.ts](../../apps/desktop/src/features/coding/components/CodingComposer.spec.ts) | 控件顺序、发送强度和切换模型后的能力校验 |
| [ModelStrengthPicker.spec.ts](../../apps/desktop/src/features/coding/components/ModelStrengthPicker.spec.ts) | 新增档位、重置、能力缺失、关闭和焦点测试 |
| [ContextUsageRing.spec.ts](../../apps/desktop/src/features/agent/ContextUsageRing.spec.ts) | 用量展示、估算与未知、延迟回执及卸载测试 |
| [contextRing.spec.ts](../../apps/desktop/src/features/agent/model/contextRing.spec.ts) | 非法计量边界测试 |
| [workbench-upgrade.spec.ts](../../apps/desktop/e2e/workbench-upgrade.spec.ts) | 使用真实形式的简短 ID，验证宽窄窗口及浮层交互 |
| [coding-artifact.spec.ts](../../apps/desktop/e2e/coding-artifact.spec.ts) | 输入器契约适配滑杆，等待请求回执并按现有入口展开结果 |
| [workbench-guide.md](../workbench-guide.md) | 同步模型栏、强度与上下文行为 |
| 本文 | 保留前轮历史，补充本轮验证和限制 |

本轮在 `apps/desktop` 实际执行：

```powershell
node node_modules/vitest/vitest.mjs run src/features/coding/components/ModelStrengthPicker.spec.ts src/features/coding/components/CodingComposer.spec.ts src/features/coding/components/CodingComposerH1BC.spec.ts src/features/coding/components/WorkbenchInteractions.spec.ts src/features/agent/ContextUsageRing.spec.ts src/features/agent/model/contextRing.spec.ts
node node_modules/vue-tsc/bin/vue-tsc.js --noEmit
npm run build
node node_modules/@playwright/test/cli.js test e2e/workbench-upgrade.spec.ts e2e/coding-artifact.spec.ts --retries=0
node node_modules/@playwright/test/cli.js test e2e/coding-artifact.spec.ts --grep "CodingComposer 契约" --retries=0 --output "../../.run/model-toolbar-current-results"
node node_modules/@playwright/test/cli.js test e2e/workbench-upgrade.spec.ts e2e/coding-artifact.spec.ts --grep "CodingComposer 契约|上下文、模型 ID" --retries=0 --output "../../.run/model-toolbar-final-results"
```

- 组件测试最终 **46 passed，6 个文件**；类型检查与生产构建通过。构建仍有既有 Ant Design 分包超过 500 kB 的提示。
- 首轮浏览器组合为 **7 passed、4 failed**，其中工作台文件的 **6 项全部通过**。输入器契约中的请求断言早于模拟回执；增加等待并按当前折叠入口展开结果后，专项复验 **1 passed**，保留原请求体与结果可见性断言。
- 补充恢复默认后把焦点移回滑杆的处理及断言，最终两项专项浏览器回归 **2 passed**，覆盖键盘重置和关闭、宽窄窗口及请求体。新增测试曾触发旧编译目标不支持 `Array.at` 和联合类型未收窄错误；改用兼容写法并明确校验模型能力后，类型检查与 46 项组件测试均复验通过。
- 剩余 3 项分别停在隐藏的 `command-duration`、隐藏的 `command-output-toggle` 和旧 `thread-context-toggle` 入口。本轮未修改对应业务组件或这些用例的断言。
- 从根目录执行 `node .run/model-toolbar-baseline/verify-legacy.mjs`，临时 Vite 服务加载任务开始前保存的 3 个运行时组件文件；确认 `Loaded pre-change source files: 3/3`，同样 3 项在相同断言处失败。因此属于本轮改动之前的回归问题，未把整套旧测试写成通过，未扩展范围修改这些入口。
- 已查看 1440px 与 600px 的上下文及强度截图；新会话另覆盖 900px。模型名称、浮层位置与控件顺序符合本轮参考图。
- 本轮 12 个文件经 UTF-8 无 BOM、尾部空白和本地文档链接检查，无问题；限定这些文件的 `git diff --check` 返回 0。

本轮读取 `docs/project-state.md` 及现有工作台、修复记录，对照当前源码核实。本次更新 `workbench-guide.md` 和本文中被新要求替代的“完整 ID 换行、普通强度下拉框”说明；按仓库入口约定未改写历史状态快照，也未新增记忆体系。

本轮未修改后端协议、安装器或依赖，未调用真实模型，未替换已安装客户端。使用已安装版本时需按现有构建安装流程更新客户端，才能看到源码中的新界面。更新源尚未部署的限制仍与前轮相同。

---

以下保留前轮修复的交付与验证记录；模型栏外观以本轮调整为准。

## 任务总结

按五张截图收拢对话入口：Skills 通过 `/skill` 打开，独立 worktree 在项目编辑中创建，三项快捷任务放在新会话中央。删除对话 Token/费用上限选项和独立只读子任务能力；保留运行时内部限制、用量核算与已有历史数据。

模型选择器移除“默认”前缀，完整 ID 随可用宽度换行。模型请求的系统上下文携带本轮已验证路由的实际模型 ID，切换模型后随新请求刷新；未知时不使用 Profile ID 或助手角色代替。

关于与更新页读取实际版本，支持补充并保存当前客户端的 HTTPS JSON 更新地址。检查和安装使用同一来源，核对版本、安装目标及固定公钥签名，检查与下载均限制等待时间；完成下载验签后再停止本机执行器并安装。用户确认更新源尚未部署，本次未填入旧联网版地址、未部署、未执行真实升级。

## 变更文件

以下相对接手时保存的文件基线核对，不把原有大范围未提交改动计入本次成果。

| 文件 | 本次变更 |
| --- | --- |
| [CodingHome.vue](../../apps/desktop/src/features/coding/components/CodingHome.vue) | 快捷任务移至中央，移除输入区 worktree 开关 |
| [CodingComposer.vue](../../apps/desktop/src/features/coding/components/CodingComposer.vue) | `/skill`、完整模型 ID、移除预算和子任务选项 |
| [SkillPicker.vue](../../apps/desktop/src/features/coding/components/SkillPicker.vue) | 按需加载、错误与空态、取消和键盘焦点 |
| [ProjectWorktreeSettings.vue](../../apps/desktop/src/features/coding/components/ProjectWorktreeSettings.vue) | 新增分支选择和幂等创建面板 |
| [EditProjectDialog.vue](../../apps/desktop/src/features/coding/components/EditProjectDialog.vue) | 接入 worktree，保护未保存修改与并发操作 |
| [CodingSidebar.vue](../../apps/desktop/src/features/coding/components/CodingSidebar.vue) | 创建后刷新并选中工作区 |
| [CodingThreadWorkspace.vue](../../apps/desktop/src/features/coding/components/CodingThreadWorkspace.vue) | 停止发送已删除选项 |
| [contracts.ts](../../apps/desktop/src/features/coding/model/contracts.ts) | 删除首轮预算和子任务参数 |
| [runContracts.ts](../../apps/desktop/src/features/coding/model/runContracts.ts) | 删除前端运行请求对应参数 |
| [UpdateChecker.vue](../../apps/desktop/src/components/UpdateChecker.vue) | 更新配置、检查、安装及失败状态 |
| [api/tauri.ts](../../apps/desktop/src/api/tauri.ts) | 更新配置与来源参数封装 |
| [api.ts](../../apps/desktop/src/api.ts) | 导出更新接口和类型 |
| [lib.rs](../../apps/desktop/src-tauri/src/lib.rs) | 接入更新配置、目标校验和下载超时 |
| [updater_config.rs](../../apps/desktop/src-tauri/src/updater_config.rs) | 新增来源、客户端目标、清单校验与单元测试 |
| [context_manager.py](../../src/private_agent_local/context_manager.py) | 注入本轮模型身份 |
| [app.py](../../src/private_agent_local/app.py) | 拒绝开启已删除的子任务功能 |
| [runtime.py](../../src/private_agent_local/runtime.py) | 不再开放或恢复子任务权限 |
| [readonly_agents.py](../../src/private_agent_local/readonly_agents.py) | 移除创建执行，保留历史查询和取消清理 |
| [tool_registry.py](../../src/private_agent_local/tool_registry.py) | 删除子任务工具注册 |
| [turn_queue.py](../../src/private_agent_local/turn_queue.py) | 后续任务不继承旧子任务开关 |
| [CodingHome.spec.ts](../../apps/desktop/src/features/coding/components/CodingHome.spec.ts) | 中央快捷任务回归 |
| [CodingComposer.spec.ts](../../apps/desktop/src/features/coding/components/CodingComposer.spec.ts) | `/skill` 和完整 ID 回归 |
| [ProjectWorktreeSettings.spec.ts](../../apps/desktop/src/features/coding/components/ProjectWorktreeSettings.spec.ts) | 新增创建、重试、卸载和非 Git 边界测试 |
| [WorkbenchInteractions.spec.ts](../../apps/desktop/src/features/coding/components/WorkbenchInteractions.spec.ts) | 草稿发送不包含删除参数 |
| [UpdateChecker.spec.ts](../../apps/desktop/src/components/UpdateChecker.spec.ts) | 来源配置、校验、同源安装和失败恢复 |
| [test_local_context.py](../../tests/unit/test_local_context.py) | 默认/显式模型、切换和未知身份 |
| [test_workbench_integrations.py](../../tests/unit/test_workbench_integrations.py) | 拒绝子任务请求及旧许可恢复 |
| [test_workspace_features.py](../../tests/unit/test_workspace_features.py) | 队列不继承旧子任务许可 |
| [workbench-upgrade.spec.ts](../../apps/desktop/e2e/workbench-upgrade.spec.ts) | `/skill`、宽窄布局、worktree 和更新按钮完整界面流程 |
| [README.md](../../README.md) | 修正当前能力说明 |
| [workbench-guide.md](../workbench-guide.md) | 同步入口、模型身份、删除功能和更新配置 |
| [testing-guide.md](../testing-guide.md) | 修正工作台回归范围 |
| [原工作台交付记录](2026-09-21-workbench-upgrade.md) | 保留历史并标注本次后续修正 |
| 本文 | 记录本次文件、验证及交付边界 |

## 验证结果

在仓库根目录实际执行：

| 命令 | 结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite local` | 84 passed |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite workbench` | 36 passed，包含获准重试的完整工作台回归 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite context` | 44 passed |
| `cargo test --offline --locked --manifest-path apps/desktop/src-tauri/Cargo.toml --lib` | 7 passed、1 ignored；被忽略项仅是由进程树测试单独启动的辅助进程入口 |
| `rustfmt --check --edition 2021 apps/desktop/src-tauri/src/updater_config.rs` | 通过 |
| `git diff --check` | 退出码 0，仅有 LF/CRLF 转换提醒 |

Python 静态检查返回 `All checks passed!`：

```powershell
.venv/Scripts/python.exe -m ruff check src/private_agent_local/app.py src/private_agent_local/context_manager.py src/private_agent_local/runtime.py src/private_agent_local/readonly_agents.py src/private_agent_local/tool_registry.py src/private_agent_local/turn_queue.py tests/unit/test_local_context.py tests/unit/test_workspace_features.py tests/unit/test_workbench_integrations.py
```

在 `apps/desktop` 实际执行，组件回归共 88 passed：

```powershell
node node_modules/vitest/vitest.mjs run src/components/UpdateChecker.spec.ts src/features/coding/components/WorkbenchInteractions.spec.ts src/features/coding/components/CodingComposer.spec.ts src/features/coding/components/CodingComposerH1BC.spec.ts src/features/coding/components/CodingHome.spec.ts src/features/coding/components/EditProjectDialog.spec.ts src/features/coding/components/ProjectWorktreeSettings.spec.ts src/features/coding/components/CodingSidebar.spec.ts src/features/coding/components/CodingThreadWorkspace.spec.ts
```

| 命令 | 结果 |
| --- | --- |
| `node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` | 通过 |
| `node node_modules/@playwright/test/cli.js test e2e/workbench-upgrade.spec.ts e2e/project-management.spec.ts --retries=0` | 最终 6 passed；含 1440、900、600 宽度及更新按钮流程 |
| `npm run build` | 类型检查和生产构建通过；保留既有 Ant Design 分包超过 500 kB 的提醒 |

已实际查看新会话、完整模型 ID、项目编辑和更新页截图，未发现本次改动造成的文本裁切或横向溢出。变更文件另经 UTF-8 无 BOM、尾部空白和本地文档链接检查。

初次受限环境运行曾出现 `EPERM` / `WinError 5`，普通进程权限复验通过；工作台普通权限审批两次超时后，经用户明确允许重试，36 项全部通过。浏览器新增分支选择用例曾因精确标签定位失败，改为按可访问角色定位后通过，未删减创建和工作区切换断言。

## 项目记忆

读取 `docs/project-state.md`、本机化说明及相关工作台、模型、测试文档，并以当前源码和接手基线验证。发现当前 README、工作台和测试指南仍描述旧入口与子任务能力，已同步修正；原交付记录保留历史并标注后续变化。

按仓库入口“仅在用户明确要求新增或更新项目记忆时”维护状态快照的约定，未修改 `docs/project-state.md`。持久行为说明更新在现有文档位置，没有创建新的项目记忆体系。

## 风险、限制与假设

- 更新源尚未部署，未实测正式签名包的下载、安装和重启。更新页界面回归使用原生 IPC 替身，不能等同于真实升级验收。
- 未发起真实付费模型调用。模型 ID 已按实际路由写入请求并验证，不代表所有供应商都一定遵循身份提示。
- 未重新打包或替换已安装客户端；需使用同版本的前端、Tauri 壳和 Python 执行器。
- 保留历史任务和内部执行限制；没有数据库迁移、依赖升级、提交、发布或部署。

## 用户需执行的操作

1. 使用修复后的桌面程序需按现有流程构建并安装同版本客户端；本机验证安装器可从仓库根执行 `scripts\build-client.cmd --preview-installer --version 1.0.0` 生成，具体输出以构建回执为准。
2. 在线更新需后续部署独立的统一客户端更新源及与内置公钥匹配的签名安装包，再在“设置 → 关于与更新 → 更新源设置”填写 HTTPS `latest.json` 地址。当前没有可填写的正式地址。
