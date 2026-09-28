# 2026-09-21 反思与纠错对齐记录

## 目标与对齐范围

在现有 API Key 本机桌面链中补齐“失败事实 → 纠正反馈 → 新证据 → 完成检查”闭环。用户选择的默认策略为：仅重复失败后触发独立复核。

本次参考 Codex 公开的[工具后反馈与停止检查](https://learn.chatgpt.com/docs/hooks)、[独立子代理上下文](https://learn.chatgpt.com/docs/agent-configuration/subagents)及[测试与复核实践](https://learn.chatgpt.com/guides/best-practices)。公开文档说明的是可配置机制，不证明 Codex 每次任务都执行独立 reviewer；这里的两次失败触发、预算和证据约束是本项目实现策略，不是对未公开内部实现的复刻。

## 实施前后

| 能力 | 原有行为 | 本次实现 |
| --- | --- | --- |
| 工具纠错 | 依赖原始错误及相同失败连续计数；成功工具打断计数 | 错误类别、操作摘要、次数和真实来源组成有界记录，无关成功不清除失败 |
| 重复失败 | 参数或错误变化、穿插读取可能重置旧连续计数 | 同目标、同工作区同操作保留失败周期，第 3 次警告、第 4 次停止；实际进展开启新周期 |
| 完成纠正 | 机器检查失败返回主模型，最多两次 | 保留旧上限，反馈缺失验收项、来源及纠正要求，过期证据不能计入新目标 |
| 独立复核 | 没有独立模型复核层 | 达到两次可纠正失败的修改任务，仅机器验收通过后调用无工具复核 |
| 恢复与控制 | 已有逻辑任务预算、恢复检查点、追加约束与取消 | 纠错状态及复核额度进入检查点；新目标同步清理内存和持久失败周期，事务失败完整回滚 |
| 诊断 | 已有观察器白名单摘要 | 补充纠错、复核事件类别及仍未解决的失败次数，不公开复核正文 |

## 关键边界

- `reflection.py` 最多保存 16 项纠错，参数、错误和工具正文只计算摘要，不复制到状态；下一轮最多提示 4 项未解决事实。相同操作成功可以解决错误，普通无关读取不能解决。命令计数使用本机持久终态、关联执行和事件，重复轮询不重复计数。
- 参数、证据或执行等可纠正失败在同一目标累计两次后锁存复核标记；一次验收即使有多项失败也只计一次。权限阻塞、取消、未知副作用不触发付费复核，也不鼓励变换入口或重放。
- 复核仅检查已有机器验收通过且包含实际文件变化证据的候选。普通问答、规划、预览、人工待确认或机器证据不足不触发。项目 Observer 检查仍是独立的确定性验收条件，不会因模型意见而被跳过。
- `reflection_review.py` 使用当前配置模型的独立消息，无工具、无原生推理续接状态。输入包含目标、约束、机器事实、候选说明及最多 12 条同会话历史摘录；历史包括旧任务时也只作为不可信参考。问题只允许引用已提供来源，输出为受限 `pass/revise` JSON，拒收工具调用、秘密、缺失来源或未完整响应。
- 一个逻辑任务最多 2 次复核，每次最多 30 秒并受剩余有效时间约束；给主任务保留至少一次模型请求。请求数、tokens、缓存用量、费用均计入原预算。发送后的超时、取消或无效响应可能收费，因此无法确认的用量保持未知。
- 复核否决返回主模型纠正，之后重新取得证据；复核失败或额度耗尽保留 `unknown`。代次、模型配置、项目规则或工作区发生变化后拒收旧意见；初始扫描前就绑定候选代次，过期候选不会消耗复核额度。
- 复核通过后再次核验文件或命令证据，防止原验收完成到复核开始之间的外部写入使旧证据继续被使用。追加目标及规划回答通过同一个事务边界清理失败周期，费用与请求预算、已使用复核次数继续累计。
- 沿用现有运行 JSON 和 SQLite schema，不迁移数据、不改工具权限或公开接口、不自动生成长期规则，也不保存或要求模型提供隐藏推理。

## 变更文件

| 文件 | 本次变更 |
| --- | --- |
| `src/private_agent_local/reflection.py` | 新增结构化纠错与重复失败判断 |
| `src/private_agent_local/reflection_review.py` | 新增独立复核、限额及失效处理 |
| `src/private_agent_local/core_adapter.py` | 记录工具纠错并反馈主模型 |
| `src/private_agent_local/context_manager.py` | 注入有界纠错事实并检查停滞 |
| `src/private_agent_local/completion.py` | 复核触发、缺失检查反馈及交付前再验收 |
| `src/private_agent_local/run_controls.py` | 新目标失败周期与检查点事务一致 |
| `src/private_agent_local/planning_interaction.py` | 规划回答复用目标更新事务 |
| `src/private_agent_local/planning.py` | 检查点摘要绑定纠错和复核状态 |
| `src/private_agent_local/recovery.py` | 恢复时保留累计停滞限制 |
| `src/private_agent_local/runtime.py` | 恢复继承状态并从公开快照隐藏内部记录 |
| `src/private_agent_local/observer.py` | 纠错事件白名单和失败计数 |
| `tests/unit/test_local_reflection.py` | 纠错事实、分类与去重单测 |
| `tests/unit/test_reflection_review.py` | 复核协议、预算和异步边界单测 |
| `tests/unit/test_reflection_integration.py` | ASGI、持久化、控制和完成闭环测试 |
| `scripts/run_coding_validation.py` | 登记隔离 `reflection` 套件 |
| `docs/context-design.md` | 同步上下文和恢复约定 |
| `docs/local-tool-system.md` | 同步当前纠错和复核能力 |
| `docs/testing-guide.md` | 同步测试入口 |
| `docs/solutions/2026-09-21-reflection-alignment.md` | 记录方案、验证与限制 |

## 验证

模型均使用合成响应；测试运行于 `.run/coding-agent-validation/` 下独立目录和临时 SQLite。没有调用真实付费模型、用户数据库或生产凭据。

| 实际命令 | 最终结果 |
| --- | --- |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite reflection` | 98 passed |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite completion` | 234 passed |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite orchestration` | 46 passed |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite context` | 44 passed |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite observer` | 66 passed |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite parallel` | 57 passed |

新增测试覆盖真实 ASGI、工具及 SQLite 下的触发条件、否决后修正再通过、预算与费用、超时取消、配置与磁盘变化、恢复防篡改、用户追加约束及规划回答、事件提交故障和状态回滚。

修改前的 `completion` 基线为 233 passed / 1 failed，失败节点为 `test_s1_t03_search_empty_is_normal`；修改后在相同受限环境重现。`observer` 在受限环境为 65 passed / 1 failed，错误为 Windows 命名管道 `PermissionError: [WinError 5]`。`parallel` 在受限环境为 55 passed / 2 failed，两个真实宿主场景无法完成启动或到达故障点。这三个套件保持原命令和断言，在获准的非受限执行环境复跑后分别全部通过。未放宽断言或绕过应用自身权限规则。

六组最终结果合计 545 项通过。相关 Python 文件 Ruff 检查通过，执行命令为：

```powershell
.venv\Scripts\python.exe -B -m ruff check src/private_agent_local/reflection.py src/private_agent_local/reflection_review.py src/private_agent_local/completion.py src/private_agent_local/context_manager.py src/private_agent_local/core_adapter.py src/private_agent_local/observer.py src/private_agent_local/planning.py src/private_agent_local/planning_interaction.py src/private_agent_local/recovery.py src/private_agent_local/run_controls.py src/private_agent_local/runtime.py tests/unit/test_local_reflection.py tests/unit/test_reflection_review.py tests/unit/test_reflection_integration.py scripts/run_coding_validation.py
```

开发中的计数、代次竞争及检查点一致性回归失败均已修复并包含在最终 `reflection` 通过结果中。未修改既有测试以回避环境故障。

`git -c core.safecrlf=false diff --check` 和 `git -c core.safecrlf=false diff --staged --check` 均退出 0；本次 19 个文件的 UTF-8、尾部空白及相关文档本地链接检查通过。基于任务开始时保存的文件快照复核本次差异，已有未提交改动保留，未创建提交或分支。

## 项目记忆同步与限制

实施前读取 `docs/project-state.md`、本机化说明、测试指南、上下文设计、记忆设计、任务编排与观察器交付记录。源码中已有 Observer 配置及完成检查，因此复用现有验证链，不重复建立完成钩子体系。

已更新 `docs/context-design.md`、`docs/local-tool-system.md` 和 `docs/testing-guide.md`，同步纠错生命周期、复核触发与预算、恢复行为及验证入口；旧“成功工具打断失败计数”说明补充了新协议的结构化保护。按仓库入口约定，本次未改写需要明确授权更新的 `docs/project-state.md`，也未新建长期记忆系统。

这是基于有限事实与摘录的交付复核，不是完整代码审查，不能证明全部业务语义正确。未实现通用多代理调度或任意脚本 hooks，未覆盖真实供应商响应质量、安装包和端到端人工验收。旧恢复协议维持兼容行为；源码及测试通过不代表已打包、安装或发布。
