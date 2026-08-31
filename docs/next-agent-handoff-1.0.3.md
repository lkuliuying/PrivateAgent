# PrivateAgent 接手提示词：1.0.3 异机模型不可用

> 历史记录提示（2026-08-31 补充）：下文保留 2026-08-30 的交接现场。后续已定位旧安装副本缺路由及模型开关关闭，并完成本机修复；服务器应用和真实验收仍待确认。接手先读 [共享项目状态记忆](./project-state.md)，不要将下文“根因尚未确认”或“已部署”直接作为当前结论。

请在另一台 Windows 电脑的 Agent 中使用以下内容。记录时间：2026-08-30；这是项目交接，不是执行部署、公开发布或读取凭据的额外授权。服务器和 GitHub 的状态在后续操作前应重新核对。

## 任务与产品目标

你现在接手我的 PrivateAgent 项目。当前问题和后续维护都转移到这台电脑。请先核对源码和已安装客户端，再复现、定位并最小化修复“另一台电脑安装 1.0.3 测试客户端后模型能力不可用”。先检查再给出具体方案，按项目规则执行 PLAN → EXECUTE → TEST → DELIVER。

产品目标已经明确：用户从 GitHub 下载 Windows 安装包，安装后直接连接服务器；文件保存在用户电脑，项目、文件修改和工具命令在本机执行，账号、模型配置和模型调用由服务器提供。管理员左侧按“系统 → 用户 → 日志”排列，可查看固定的 Supervisor 与 Nginx 日志。

普通版保留完整本机后端；联网版继续使用 `PrivateAgentRemote` 的独立应用标识和更新通道。客户端自带轻量执行器及 Python 运行时，不要求用户安装 MySQL 或本地模型。执行某个项目的测试、构建仍需要该项目自身的开发工具和依赖，不能偷偷安装。

## 源码已经可以从 GitHub 接手

仓库：[lkuliuying/PrivateAgent](https://github.com/lkuliuying/PrivateAgent)，开发分支 **`dev/1.0.0`**。

原机本次已将功能源码、未跟踪的新文件及测试分批提交并推送。主要功能提交：

| 提交 | 范围 |
| --- | --- |
| `599f97fad1324f000cc1488e44515c4da85d29e4` | 服务端桌面模型代理、管理员日志接口及测试 |
| `bdd7e0aa7f7395cacc0845d5e2d0bf885a6449be` | 本机执行器、账号隔离、请求分流、安装包捆绑及测试 |
| `bd217177bf529d13315f6336ca537bf3a46e8cc4` | 管理员日志界面、服务层、测试和权限说明 |

部署辅助脚本、发布工作流保护、相关指南及本文档随其后的交接提交一起同步到同一分支。**拉取该分支的最新提交，不要只停在上述第三个提交，也不要从旧测试草稿或旧标签取得源码。**

新电脑尚未克隆时：

```powershell
git clone --branch dev/1.0.0 https://github.com/lkuliuying/PrivateAgent.git
cd PrivateAgent
git status --short
git log -5 --oneline
```

已有仓库时先检查工作区和当前分支。如果已有未提交改动或分叉，保留它们并说明差异，不能自动 reset、clean、覆盖或强制推送。工作区干净且能够快进时再执行：

```powershell
git status --short
git branch --show-current
git fetch origin dev/1.0.0
git switch dev/1.0.0
git pull --ff-only origin dev/1.0.0
git log -5 --oneline
git merge-base --is-ancestor bd217177bf529d13315f6336ca537bf3a46e8cc4 HEAD
```

原机目录 `F:\Program\Agent` 仅是历史路径，新电脑使用实际仓库目录。不要复制原机虚拟环境、整个 `.run`、环境文件、数据库、日志、账号会话、凭据库、私钥或签名材料。本文档是可随源码传递的版本，必要运维记录由用户另外安全交接。

## 已安装测试包与源码的区别

- 安装包：`PrivateAgentRemote_1.0.3_x64-setup.exe`，25,519,903 字节。
- SHA256：`f8409dc1b80590b3ee707e9f25a8e32749bf4e113d63c52757cbc84ccfe3fb2f`。
- 安装时应包含 `private-agent-local.exe`，不要继续运行以前单独复制的旧便携 EXE。
- 该安装包历史构建基于 `debcd81d9b6084f8ab13f4c0423b9f14696b9496` 加当时工作区改动，构建记录为 `dirty=true`。此次提交没有重新打包，不能将原包宣称为从这些新提交干净构建的产物。
- GitHub 测试草稿 `remote-v1.0.3-test.1`（Release ID `379298626`）在本次只读核对时仍为 `draft=true`、`prerelease=true`，附件为安装包和 `SHA256SUMS.txt`，目标仍是旧 `debcd81`。草稿需要对应仓库权限访问，不等于已经公开发布。
- 原机此前记录的正式远程更新源仍为 1.0.2；本次没有修改服务器或更新源。不要把 GitHub 普通版 Latest 当作该测试包的下载入口。

该测试包没有 Windows Authenticode 签名，也没有在线更新 `.sig`；只能按组织安全策略用于测试安装，不关闭安全软件。用户允许证书未到时制作无 Authenticode 的测试包，不等于允许绕过 Tauri 更新签名验证。

## 已实现的调用边界

```text
Tauri / Vue 桌面界面
  ├─ 项目、会话、任务、文件、工具 → 本机 private-agent-local.exe
  └─ 账号、模型配置、管理员接口 → HTTPS 服务器

本机执行器 → POST /desktop/model/complete → 服务器解析账号模型并调用供应商
```

构建启用 `VITE_LOCAL_EXECUTOR=true`。本机执行器使用随机回环端口、进程内启动凭证和 Host/Origin 校验；登录后绑定经过服务器验证的账号。SQLite 元数据按服务器源站和账号隔离，退出或切换账号会取消旧任务并清理前端状态。

旧 1.0.2 把另一台 Windows 电脑的目录交给 Linux 服务器处理，造成建项目 HTTP 422。新代码将 `/projects`、`/sessions`、`/agent-runs`、`/capabilities`、`/chat` 分流到本机；本机不可用时必须报错，不能回退到服务器处理本机目录。旧 chat 目前在本机返回未实现，不能假装支持。

`/auth/*`、`/agent-model-profiles*`、模型/供应商设置和 `/admin/*` 仍走服务器。模型供应商 API Key 不下发本机执行器。

文件修改与固定项目命令需审批；写前校验原文件摘要，取消、拒绝和过期审批不能写文件。Windows 子进程用 Job Objects 清理。项目脚本不是操作系统沙箱，只批准可信项目。没有实现的自动批准、full_access、Git worktree、上下文压缩等能力不能宣称可用。

整个项目不会自动上传，但用于推理的提示词、代码片段和工具结果会发送服务器及模型供应商。文件保存在本机不表示完全离线，也不表示跨电脑自动同步项目和历史。

## 当前问题：先确认实际失败请求

用户只反馈“模型能力不可用”。尚未取得异机的精确截图、失败 HTTP 状态、账号类型及真实推理记录，**根因尚未确认，本次提交没有修复这个问题**。

优先确认是“模型能力未开启”、没有可选模型、模型列表请求失败，还是实际推理失败；确认是否与原机使用相同账号。以下是有代码依据的排查顺序，不是已经证实的原因：

1. `apps/desktop/src/features/coding/api/modelProfiles.ts` 请求云端 `GET /agent-model-profiles?enabled_only=true`。**409 + `coding_mode_disabled`** 会变成 `status: disabled`；`CodingHome.vue` 对应显示“模型能力未开启”。记录状态码与脱敏错误码，不记录认证头或完整请求正文。
2. `src/personal_assistant/api/routes_model_profiles.py::_require_flag()` 检查 `coding_permission_models_enabled`，环境设置名为 **`PA_CODING_PERMISSION_MODELS_ENABLED`**，代码默认 false。此前部署只新增接口和日志路径，没有主动调整此开关；**尚未核实生产进程的实际值，不能断言它为 false**。
3. 新客户端的 `/capabilities` 来自本机，模型 profile 来自服务器，两者能力声明可能不一致。工作台能打开不等于云端 profile API 已启用。
4. profile API 正常后，再检查当前账号是否有启用的默认 profile、`model_name`、供应商配置和 `native_tool_calls`。不要把管理员账号的配置视为所有账号共享。
5. `routes_desktop_model.py` 复用 `routes_agent_runs.py::_model_gateway_for_run`。若能力和模型列表正常而推理失败，再排查供应商连接及密钥是否配置；后端重启可能清掉只存内存的密钥，需要时由用户在客户端安全界面重新保存，不能导出或打印密钥。
6. 区分本机执行器/身份绑定失败、云端 401/403、profile 409、模型配置 422、推理 502/503/504。`src/private_agent_local/cloud.py` 会简化部分错误，界面文案不能替代原始请求状态。

先复现并取得证据，再决定改哪一层。若是必要能力位未配置，说明影响并按授权修改必要项；若是代码接入缺陷，只修对应边界。不要开启所有 feature flags，不要关闭认证，不要伪造模型可用，不要把项目执行重新移回服务器。

## 关键源码入口

| 部分 | 文件或目录 |
| --- | --- |
| Tauri 执行器生命周期 | `apps/desktop/src-tauri/src/local_executor.rs`、`lib.rs` |
| 前端分流与启动 | `apps/desktop/src/services/localExecutor.ts`、`backendStartup.ts`、`apps/desktop/src/api/http.ts` |
| 账号和项目隔离 | `apps/desktop/src/stores/auth.ts`、`apps/desktop/src/features/coding/model/codingWorkspaceStore.ts` |
| 本机任务和文件工具 | `src/private_agent_local/` |
| 云端能力及模型解析 | `src/personal_assistant/api/routes_model_profiles.py`、`routes_desktop_model.py`、`routes_agent_runs.py` |
| 日志接口与界面 | `src/personal_assistant/api/routes_admin_logs.py`、`src/personal_assistant/core/admin_logs.py`、`apps/desktop/src/components/AdminLogsPanel.vue` |
| 打包与部署校验 | `scripts/build-remote-client.cjs`、`scripts/verify-local-executor.py`、`scripts/prepare-connected-backend.py` |

## 服务端与发布边界

2026-08-30 前一阶段已经部署 5 个后端文件的定向补丁，新增 `POST /desktop/model/complete`、`GET /admin/logs` 和 `GET /admin/logs/{source_id}`，接入四个固定日志来源，Supervisor 恢复运行。当前文档更新没有再次连接服务器执行部署。

服务器仓库仍是原提交加定向补丁，不能因为 GitHub 已更新就直接在生产目录 pull、reset 或覆盖本地修复。原 `alembic/env.py` 修复需要保留。提交前只调整了 `main_api.py` 中新增接口的一行 import 顺序，当前该文件的字节摘要与旧部署归档不同；若以后生成新包，必须核对新清单，不能重复使用旧摘要。

历史服务器验证覆盖匿名接口 401、CORS 预检、4 个日志文件可读、模拟身份路由权限、脱敏与符号链接拒绝；**没有证明真实账号模型调用、管理员页面、第二台电脑或在线升级已经验收通过**。Nginx 日志轮转后只读权限是否保留仍待确认，不能贸然新增另一套轮转。

日志接口只允许管理员、有固定来源和有界尾部读取，不接受任意路径；不能为诊断扩大日志权限、改 root 运行或导出生产日志。服务器访问须由用户安全授权新电脑，不复制旧机私钥，不提取 FinalShell 密码，不关闭 SSH 主机验证。

`.github/workflows/signpath-release.yml` 的 `remote-v*` 排除条件随本次源码交接提交，用于避免远程版触发普通版构建。**旧测试草稿仍指向 `debcd81`，本次推送不会自动改变草稿目标或旧标签使用的工作流。** 发布前检查实际目标提交并取得发布授权；不得用另一个工具绕过此前公开草稿/取消工作流被自动审查拒绝的限制。

后续从干净、可追溯的修复提交构建新的测试版本，不覆盖旧资产来混淆来源。普通版和远程版更新渠道保持隔离；真实升级验收前不改正式更新清单，不宣称稳定发布。

## 提交前实际验证与新机复现入口

本次原机重新运行的结果：

- 前端 Vitest：30 个文件、196 项通过。
- 隔离 pytest：33 passed、1 skipped；包含本机执行器、桌面模型接口、管理员日志、部署补丁工具。跳过项是 Windows 无创建真实符号链接权限的用例。
- Node 打包配置测试：8 项通过。
- `vue-tsc --noEmit`、相关 Python 文件 Ruff、Git 差异空白检查通过。
- Ruff 最初发现新增 import 顺序问题，仅调整该行后复跑 Python 测试和 Ruff 通过。

更早阶段的 vue-tsc/Vite/PyInstaller/Rust/NSIS 完整预览构建及捆绑执行器启动检查通过；**本次提交没有重新运行完整安装包构建，也没有进行异机或生产模型验证**。这些本机结果不能替代当前电脑的复现。

在 `apps/desktop` 下运行：

```powershell
npm.cmd test -- src/services/localExecutor.spec.ts src/api/http.spec.ts src/services/backendStartup.spec.ts src/stores/auth.spec.ts src/features/coding src/components/AdminLogsPanel.spec.ts src/pages/AdminPage.spec.ts src/RootApp.spec.ts
node node_modules/vue-tsc/bin/vue-tsc.js --noEmit
```

在仓库根目录运行：

```powershell
node --test scripts/build-remote-client.test.cjs
git diff --check
```

Python 测试从不含环境文件的独立目录执行，设置 `PYTHONPATH=<实际仓库>/src`，使用已有项目环境，避免读取开发环境配置或连接生产数据库：

```text
python -X utf8 -B -m pytest <仓库>/tests/unit/test_local_executor.py <仓库>/tests/unit/test_desktop_model.py <仓库>/tests/unit/test_admin_logs.py <仓库>/tests/unit/test_connected_backend_bundle.py --noconftest -p no:cacheprovider -q
```

真实验收使用无敏感内容的测试目录，覆盖：登录 → 选择本机文件夹建项目 → 获取模型 profile → 模型读取测试文件 → 审批修改 → 拒绝/取消不写文件 → 重启与换账号隔离 → 管理员日志；真实推理可能产生费用，遵循用户授权。模型修复与日志轮转/在线升级是不同验收项，分别记录。

进一步的实现、部署历史和发布步骤见 [本机执行记录](./connected-desktop-local-execution.md)、[管理员日志](./admin-service-logs.md)、[部署与验收](./connected-desktop-rollout.md)、[远程更新渠道](./remote-client-updates.md)。不要照搬旧部署章节重复操作。

## 工作约束与首次回复

只解决用户当前问题，不附带重构、清理、删文件、依赖升级、数据库迁移、配置变更或发布。任何修改都先说明精确问题、涉及文件、方案、验证与风险；保留现有改动。不要打印、复制、修改或提交环境文件、凭据、API Key、密码、令牌、私钥或账号数据。

先给出接手核对：当前分支和提交、源码完整性、安装包来源与摘要、精确报错、失败请求及证据，然后给出最小修复计划并按授权继续。已有访问足够时直接检查，只在缺少必要信息或权限时向用户询问。最终说明根因、改动文件、实际测试结果、未验证项和剩余人工步骤。
