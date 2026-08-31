# PrivateAgent 共享项目状态记忆

最后整理：**2026-08-31（Asia/Shanghai）**。适用工作区：`E:\Program\Agent`。其他路径或 worktree 应先核对各自 Git 状态，不能直接继承这里的未提交修改。

**先记住：联网版 1.0.3 模型和管理员日志故障已定位；本机代码修复、修复工具和相关验证已完成，但没有收到服务器应用补丁、重启及真实账号验收回执。当前不能宣称“已上线修复”。**

本文是共享事实索引，不是自动执行计划或实时监控。用户提供的新回执、当前环境检查和具体源码优先于过期快照。源码、构建、安装、进程和用户验收必须按各自证据判断，不能相互代替。

## 1. 当前状态快照

| 项目 | 状态 | 依据与边界 |
| --- | --- | --- |
| 仓库 | `lkuliuying/PrivateAgent`，当前分支 `dev/1.0.0` | 本机 Git 检查；默认 main 不代表当前工作分支 |
| 本机 HEAD | `0c1705570ed0b75940189d52708c59b0021c2034` | 整理时实测；后续会话必须重查 |
| 本地远端跟踪引用 | `origin/dev/1.0.0` 为 `180603b6690d2fb18f08bf10c4197520b97840cc`，本地显示 ahead 4 | 本轮未 fetch，不证明 GitHub 当前状态；历史合并保留了本地提交，不应因 ahead 自动 reset |
| 工作区 | 有本次修复和文档的未提交改动 | 不能按旧“克隆/同步后干净”记录清理；详见第 3 节 |
| 本轮后端回归 | 45 passed、1 skipped | 来自修复阶段本机隔离测试；整理记忆时未重跑，不代表生产验收 |
| 服务器 | 已定位运行包与源码错位，必要模型开关关闭 | 用户提供的诊断结果，详见第 4 节；当前生产状态仍需新回执 |
| 客户端 | 本次排查核对过联网版 1.0.3 测试安装包及本机执行器 | 历史 dirty 构建；没有重打包或发布新版本 |
| 发布/更新 | 本轮未提交、推送、发布或修改正式更新源 | GitHub 草稿、标签、正式更新源的实时状态未在线复核 |

## 2. 产品方向与实际职责边界

项目技术栈为 Tauri/Rust + Vue/TypeScript 桌面端，Python/FastAPI + SQLAlchemy 后端。`pyproject.toml` 要求 Python >=3.12。

当前联网版目标：用户安装客户端后连接服务器，文件和项目操作留在用户电脑，账号、模型配置及模型供应商调用由服务器提供。管理员入口按“系统 → 用户 → 日志”组织。

| 部分 | 当前职责 | 主要源码入口 |
| --- | --- | --- |
| 普通版 | 完整本机业务后端；MySQL、Ollama 等依赖按使用场景配置 | [根 README](../README.md)、[常规 Tauri 配置](../apps/desktop/src-tauri/tauri.conf.json) |
| 联网版桌面壳 | 独立 `PrivateAgentRemote` 标识与更新通道，启动捆绑的 `private-agent-local.exe` | [联网版构建脚本](../scripts/build-remote-client.cjs)、[执行器生命周期](../apps/desktop/src-tauri/src/local_executor.rs) |
| 本机执行器 | `/projects`、`/sessions`、`/agent-runs`、`/capabilities`、`/chat` 分流到本机；项目文件与按账号隔离的 SQLite 元数据在本机 | [请求分流](../apps/desktop/src/services/localExecutor.ts)、[本机 API](../src/private_agent_local/app.py)、[本机存储](../src/private_agent_local/store.py) |
| 云端接口 | 账号、模型 profile、供应商配置与 `/admin/*` | [HTTP 客户端](../apps/desktop/src/api/http.ts)、[模型配置接口](../src/personal_assistant/api/routes_model_profiles.py) |
| 模型执行 | 本机执行器经 `POST /desktop/model/complete` 请求服务器，由服务器解析账号模型并调用供应商 | [本机云端调用](../src/private_agent_local/cloud.py)、[桌面模型代理](../src/personal_assistant/api/routes_desktop_model.py) |
| 管理员日志 | 仅管理员访问固定来源，进行有界尾部读取和脱敏，不接受任意路径 | [日志 API](../src/personal_assistant/api/routes_admin_logs.py)、[日志读取](../src/personal_assistant/core/admin_logs.py) |

不要扩展这些结论：

- 本机执行器不可用时应报错，不能回退到 Linux 服务器处理 Windows 本机路径。
- 联网版终端自带轻量执行器及 Python 运行时，不要求终端用户先安装 MySQL 或本地模型；项目自身的测试/构建工具仍需具备。
- 文件保存在本机不等于完全离线；推理用提示词、代码片段和工具结果会发送服务器及供应商。项目和历史不会因此自动跨电脑同步。
- `/chat` 被分流不等于旧聊天功能已经实现；本机能力声明不支持的 full_access、Git worktree、上下文压缩等，不能按普通版文档宣称可用。
- 写文件和固定项目命令需审批；写入前校验原文件摘要，拒绝/取消不得写入。项目脚本不是操作系统沙箱。

## 3. 必须保留的本机交付

整理记忆前已存在以下未提交改动；本轮只新增记忆入口、状态文档及历史提示，不修改业务代码：

| 文件 | 内容 |
| --- | --- |
| [routes_desktop_model.py](../src/personal_assistant/api/routes_desktop_model.py) | ORM 推理强度字段修复 |
| [test_desktop_model.py](../tests/unit/test_desktop_model.py) | 真实 ORM 对象与边界回归覆盖 |
| [repair-connected-runtime.py](../scripts/repair-connected-runtime.py) | 新增的运行包定向检查、应用与回滚工具 |
| [test_connected_runtime_repair.py](../tests/unit/test_connected_runtime_repair.py) | 新增修复工具测试 |
| [服务器修复操作说明](./connected-runtime-1.0.3-repair.md) | 新增的服务器应用、配置和回滚指南 |
| [1.0.3 修复总结](./solutions/2026-08-31-privateagent-1-0-3.md) | 新增的根因、修复和验证记录 |
| [文档索引](./README.md) | 新增修复与记忆入口 |

`.run/incident-1.0.3/` 包含本机临时诊断脚本，`.tmp/incident-103/` 包含临时测试/整理材料；两者被 Git 忽略，不保证另一台机器或新 worktree 存在。不要复制整个 `.run`、虚拟环境、账号会话或凭据来“同步环境”。

共享状态文件本身不保证已提交或推送。接手时运行 `git status --short --branch` 并检查实际 diff；仅凭本表不能断定当前变更都属于同一会话。

## 4. 当前故障：已确认到什么程度

### 服务器源码与安装副本错位

用户在已授权的 FinalShell 会话执行诊断并提供结果。本机助手没有直接 SSH 执行生产修复，也没有读取原 Python 进程内存。

| 对象 | 本轮已有证据 |
| --- | --- |
| 服务器源码根 | `/opt/private-agent/current/src/personal_assistant`，相关模块存在，两个新增路由有导入和注册 |
| 服务解释器入口 | `/opt/private-agent/venv/bin/python` |
| 重建服务环境后实际解析位置 | `/opt/private-agent/venv/lib/python3.12/site-packages/personal_assistant`，不是源码目录 |
| 该安装副本 | 缺少 `api/routes_admin_logs.py`、`api/routes_desktop_model.py`、`core/admin_logs.py`，两个新增路由未注册 |
| 同环境新进程加载的配置 | `coding_permission_models_enabled=false`；`coding_agent_ui_enabled=false` |

这解释了源码已有补丁但新接口仍不可用。`git pull` 的服务器输出是 fetch 成功、merge 因本地修改/未跟踪文件冲突而中止，不能算更新成功。环境变量显示 `unset` 本身也不能证明开关关闭，本次依据是实际配置加载结果。

模型页面的关闭文案对应云端模型配置接口 `409 + coding_mode_disabled`。日志 404 也可能来自未知 `source_id`，本次“缺路由”结论还依赖上述安装副本证据；不能把任何日志 404 都诊断为版本旧。当前日志固定来源为 `supervisor`、`supervisord`、`nginx-access`、`nginx-error`；配置/文件不可读属于 503，应另行检查而不是扩大权限。

### 本机代码修复

模型代理曾访问不存在的 ORM 属性 `profile.reasoning_efforts`。换用真实 `ModelProfile` 对象后已复现异常，现改为 `profile.reasoning_efforts_json`，并测试支持、不支持和未声明推理强度的情况。

**只修 ORM 属性。HTTP DTO 中的 `reasoning_efforts` 仍是合法字段，不得全仓替换为 `reasoning_efforts_json`。**

### 服务器修复准备

工具只处理实际安装副本的五个文件：`config.py`、`main_api.py` 和上述三个缺失模块。源码只读；来源与目标摘要未知时拒绝覆盖；应用/回滚必须确认 `private-agent STOPPED`。备份目录为 `/opt/private-agent/rollback-connected-runtime-1.0.3`，使用备份清单、原子替换及回滚保护。

必要配置项仅为 `PA_CODING_PERMISSION_MODELS_ENABLED="true"`，不顺带开启其他 Coding 开关。保留 Supervisor 现有环境项，包括 `PA_PARENT_PID`、日志路径与秘密文件引用；保留 `alembic/env.py` 和其他服务器修复。不 reset/clean，不整体覆盖配置，不改数据库或 Nginx 权限。

这是安装副本应急补丁，不更新 wheel 的 `dist-info/RECORD`，不等于正规重构建；后续重装可能覆盖补丁。精确操作、失败停止条件和回滚只按[操作说明](./connected-runtime-1.0.3-repair.md)核对，不按旧交接中的部署命令重复操作。

### 诊断脚本的退出超时

早期诊断工具把 `PYTHONINSPECT` 设为字符串 `"0"`，终端中会在结果输出后进入交互等待，最终超时。本机 v3 已移除变量，并设置子进程 `stdin=DEVNULL`；真实终端场景复现与修正检查通过。已输出的完整模块/配置结果仍有诊断价值；这个脚本退出问题不能推导为业务服务卡死。

## 5. 验证记录和环境边界

- 修复阶段五组隔离 pytest：**45 passed、1 skipped**，覆盖模型代理、管理员日志、本机执行器、联网后端补丁包和新修复工具。跳过的是 Windows 无创建真实符号链接权限的既有测试。
- 已验证未知摘要拒绝、重复应用、服务停止门禁、模拟写入失败后回滚、备份篡改和后续修改保护；本机助手未执行生产应用，尚未收到用户已应用的回执。
- 相关 Python 文件 Ruff 与 `git diff --check` 通过；服务器说明中的 Bash 命令块通过 `bash -n`，并未因此在生产执行。
- 本机 `.venv/Scripts/python.exe` 存在；整理时 `apps/desktop/node_modules` 不存在。本轮未跑前端 Vitest/类型检查或完整安装包构建；不要把原机的 196 项 Vitest 写成本机成绩。
- 复跑本轮 Python 单测时使用无环境文件的隔离工作目录、仓库 `src` 的 `PYTHONPATH`，以及 `--noconftest -p no:cacheprovider`；不要直接套用会加载开发/生产配置的全量测试入口。具体用例见第 3 节和[测试指南](./testing-guide.md)。
- 本机单测使用模拟依赖，不证明真实账号 profile、供应商 Key、真实推理费用/响应或生产日志可读性。只读健康检查、匿名 401、源码路由存在和进程 `RUNNING` 都不能代替功能验收。

## 6. 客户端与版本记录

排查时核对的安装包是 `PrivateAgentRemote_1.0.3_x64-setup.exe`，25,519,903 字节，SHA256：

```text
f8409dc1b80590b3ee707e9f25a8e32749bf4e113d63c52757cbc84ccfe3fb2f
```

当时安装目录为 `C:\ProgramSoftware\PrivateAgent`，含 `privateagent-remote.exe` 与 `private-agent-local.exe`。这些是该次检查记录，不是未来会话的实时进程清单。

该包基于历史 `debcd81` 加工作区改动构建，记录为 `dirty=true`，不是从当前 HEAD 干净构建。根配置文件的 `1.0.0` 不等于联网版测试安装包版本，联网构建脚本会生成独立配置；不要为了“统一”直接修改普通版版本号。

旧交接记录的 `remote-v1.0.3-test.1` 草稿、正式远程更新源 1.0.2 等属于历史快照，本轮未在线复核。没有新安装包、公开发布、签名或在线升级验收。测试包的无 Authenticode 许可不等于可绕过 updater 签名验证。

## 7. 历史文档的使用顺序

先看本文的状态及日期，再看任务对应的源码、修复总结和操作说明，最后按需追溯历史。

| 历史材料 | 易误读内容 | 正确使用方式 |
| --- | --- | --- |
| [2026-08-30 交接提示](./next-agent-handoff-1.0.3.md) | “根因尚未确认”“五文件已部署、Supervisor 恢复” | 是此前记录；后续诊断查明补丁没有进入实际安装副本，不能证明本轮修复已上线 |
| [初期部署交接](./deployment-handoff-20260830.md)、[换机开发指南](./new-computer-development.md) | 旧远程客户端“不启动本地 Python sidecar”、旧草稿/测试 EXE 入口 | 初期云端执行方案，不适用于当前捆绑轻量本机执行器的联网版；不能让 Linux 接管 Windows 项目目录 |
| [根 README](../README.md) | 普通版依赖、源码版本与大量能力描述 | 基础工程概览，不是联网版运行状态或当前生产能力证明 |
| [文档索引](./README.md) | 2026-08-20 的 v0.5.0 / v0.6.0 阶段说明 | 历史工程阶段，不能作为当前部署/客户端版本 |

不要删除历史证据来消除冲突；注明其适用时间与产品形态。新的环境证据只更新对应结论，不把未检查的其他功能顺带标为通过。

## 8. 仍待完成或确认

以下是接续事项，不是“用户已执行”的记录。执行前遵循当前会话授权和实际环境。

- 取得修复工具预检、应用结果，以及必要模型开关配置与单个服务稳定 `RUNNING` 的回执。
- 用真实管理员账号确认四类日志接口与读取；另验日志轮转后的权限保持。
- 确认当前账号启用/默认模型 profile；如重启丢失内存 Key，由用户在安全配置页重新保存，不导出凭据。
- 以无敏感内容完成真实模型请求及联网版本机文件/审批流程；真实推理可能付费，不能用单测结果代替。
- 新安装包、公开发布与正式在线更新是独立任务，未因本次修复获得完成状态。

若缺少回执，应报告“待确认”，不要重复假定服务器已停服、已更新或已经恢复，也不要为了验证而重新部署。

## 9. 其他会话如何使用与更新

根目录 [AGENTS.md](../AGENTS.md) 要求接手先读本文。官方说明中，Codex 在运行开始时发现项目指令，因此不保证已经打开的会话自动刷新；已有会话可以明确收到“请读取根目录 AGENTS.md 和 docs/project-state.md，再继续当前任务”的提示。[依据：AGENTS.md 读取机制](https://learn.chatgpt.com/docs/agent-configuration/agents-md)。

共享文件只能帮助读取同一工作区的会话；未提交文件不会自动出现在另一台电脑或其他 worktree。本文未向其他会话发送消息，也不宣称它们已经读取。

仅在用户明确要求新增或更新项目记忆时维护本文，普通修复、测试、交付或生成交接文档不自动触发记忆改写。更新时记录“日期、环境、对象、动作、原始结果的脱敏摘要、未完成项”，先核对当前 Git 和对应证据，再更新第 1、4、5、8 节。不要保存密码、令牌、账号会话、生产日志正文或整份部署配置；不要把期望结果写成实际结果。

### 本次记忆变更记录

- 2026-08-31：建立共享事实入口；区分联网版与普通版、历史部署与最新诊断、本机验证与生产验收；保留所有既有业务修复，本轮仅整理文档。
