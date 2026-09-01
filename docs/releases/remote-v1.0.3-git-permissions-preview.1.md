# PrivateAgent 1.0.3 Git 分支与权限预览版

发行标签：`remote-v1.0.3-git-permissions-preview.1`。这是统一客户端的 Windows x64 未签名手动安装预览包，不设为 GitHub Latest，不生成 `latest.json`，不进入现有普通版或 Remote 自动更新通道。

## 本次变化

1. 项目页从所选项目根目录读取本地 Git 分支，分支下拉框可显示当前分支及其他本地分支；父目录仓库和远端分支不纳入列表。
2. 用户显式切换分支时检查活动任务、目标分支和工作区 dirty 状态。存在未提交改动时拒绝切换，保留用户现场。
3. 模型可执行 `git branch` 查询：总是询问逐次审批，替我批准和完全访问按本机策略自动执行。
4. Windows 新增受控 PowerShell 工具，仅接受登记的 cmdlet、具名参数和项目内相对路径，不接受任意脚本、管道或位置参数。
5. 任务过程默认展开为公开执行轨迹，移除“本轮决策”“接下来”和重复目标，展示公开行动、具体命令、审批及执行结果，不输出模型隐藏思维链。

权限行为如下：

| 模式 | 项目文件操作 | 登记命令和受控 PowerShell |
| --- | --- | --- |
| 总是询问 | 新增、修改、删除前逐次审批 | 每条命令逐次审批 |
| 替我批准 | 默认自动执行并审计，模型可主动要求审批 | 默认自动执行，模型可主动要求审批 |
| 完全访问 | 限时授权内自动执行项目目录中的登记操作 | 限时授权内自动执行，不获得管理员权限 |

三种可写模式均不向模型开放项目外路径。工具策略和 Windows Job 进程回收不是完整 OS 沙箱；获准的项目脚本仍继承当前系统用户本身的文件和网络权限。

## 安装包与源码依据

- 安装包：`PrivateAgent_1.0.3_x64-setup.exe`。
- 大小：30,064,054 字节。
- SHA-256：`f9d47f065d2f69707727c3fbdd044f6cc5d3baf94fa3cb1c2c00ac322f8fb146`。
- 同时发布未经改写的 `build-info.json` 及只校验发布附件的 `SHA256SUMS.txt`。
- 构建目录：`.run/unified-client-ulnC5o`；整理后的发布附件位于 `.run/git-permissions-release-1.0.3/assets`。
- 构建记录基线：`8f6d792e912e89763d1a62640662fab5658cf199`，版本 `1.0.3`，目标 `x86_64-pc-windows-msvc`，`signing=unsigned`，`updateUrl=null`。
- 构建时 `dirty=true`，唯一未提交源码差异是用户原有 `README.md` 修改；该修改未暂存、未进入下列功能提交，也不进入发行标签。安装包运行代码与前三批功能提交一致。
- 打包验收脚本在安装包生成后按新权限语义修正；该脚本不进入客户端包，最终发行标签包含修正后的验收脚本和本文。

## 分批提交

| 批次 | 提交 | 内容 |
| --- | --- | --- |
| 1 | `2831fbe` | 本机 Git 分支接口、项目内权限策略、受控 PowerShell 与运行时测试 |
| 2 | `6b0e768` | 桌面分支选择、公开执行轨迹、权限文案与前端测试 |
| 3 | `8f6d792` | 项目范围、审批语义、Git 和 PowerShell 安全边界说明 |
| 4 | `4947d59` | 打包验收覆盖替我批准、总是询问、PowerShell 和完全访问 |

本文作为独立发行记录提交。`README.md` 的既有本机改动保持未提交状态。

## 实际验证

- Python 本机执行器与服务端更新分类回归：`185 passed, 1 skipped`。跳过项是当前 Windows 用户不能创建测试所需的真实符号链接。
- 桌面端全量 Vitest：81 个测试文件，`485 passed`。
- 构建参数和发布边界测试：`9 passed`。
- Ruff、Vue/TypeScript 类型检查通过。
- Vite 生产构建转换 5022 个模块；PyInstaller、本机 Rust 执行宿主、Tauri release 编译和 NSIS 打包完成。
- 安装包文件版本和产品版本均为 `1.0.3`；Authenticode 状态为 `NotSigned`。
- 服务器模型、Ollama、OpenAI 兼容三种回环模式的最终打包执行器验收全部通过，覆盖登录/退出、项目文件写入、替我批准自动执行、总是询问人工审批、PowerShell、完全访问、撤权、上下文统计、历史导出和宿主摘要篡改阻断。
- 发布附件的 SHA-256 复核全部匹配。验收未使用生产账号、真实供应商或付费模型。

构建保留既有 Rust 未使用代码、链接器提示和 Vite 大分块警告，未为消除与本次功能无关的警告扩大修改范围。

## 客户端安装步骤

1. 完全退出旧客户端及托盘进程。
2. 备份 `%LOCALAPPDATA%\com.personal-assistant.desktop\local-projects`。
3. 下载并校验 `PrivateAgent_1.0.3_x64-setup.exe`，在测试环境手动安装。
4. 登录后选择本机 Git 项目，确认分支列表、三种权限、PowerShell 命令和公开执行轨迹。
5. 当前项目存在未提交改动时，分支显示正常但切换会被拒绝；先妥善保存工作再切换。

## 服务端源码更新步骤

本次相对上一统一客户端预览标签只修改 `apps/desktop`、`src/private_agent_local`、测试、客户端验证脚本和文档，没有服务器业务代码、依赖、数据库模型、迁移或配置变化。服务器源码可同步，但不需要重启 `private-agent` 服务，也不会替用户升级已安装客户端。

推荐由服务器维护者先执行只检查模式：

```bash
/opt/private-agent/venv/bin/python -I -B \
  /opt/private-agent/current/scripts/update-connected-server.py check
```

确认输出中的目标为本发行标签对应的完整提交、工作区干净、差异仅为上述客户端范围后，执行默认一键更新：

```bash
/opt/private-agent/venv/bin/python -I -B \
  /opt/private-agent/current/scripts/update-connected-server.py
```

仅包含本批差异时预期返回 `CODE_SYNCED_NO_RESTART`。如果返回本地修改、分叉、依赖/迁移/配置、更新工具变化或未知文件等人工审阅结果，立即停止，不执行 `reset --hard`、`clean`、强制合并或修改白名单绕过保护，按[服务器源码更新指南](../server-code-update-workflow.md)处理。

更新后核对：

```bash
runuser -u privateagent -- git -C /opt/private-agent/current status --short --branch
runuser -u privateagent -- git -C /opt/private-agent/current rev-parse HEAD
supervisorctl -c /etc/supervisord.conf status private-agent
```

源码同步成功只证明服务器仓库到达目标提交。它不等于客户端安装完成，也不替代真实账号、模型、项目操作或管理员功能验收。

## 已知限制

- 安装包没有 Windows Authenticode 或 Tauri updater 签名，只用于手动安装预览；不要关闭系统安全功能或绕过组织策略。
- 没有执行真实安装覆盖、卸载、自动更新或另一台 Windows 电脑验收。
- 没有操作生产服务器，也没有完成真实账号和供应商调用验收。
- 任意项目脚本无法在当前 `sandbox_available=false` 的宿主上获得完整 OS 级目录隔离；客户端只约束直接工具入口和传入路径。

## 项目记忆检查

已读取 `AGENTS.md` 和 `docs/project-state.md`，并重新核对当前 Git、源码、测试、构建和 GitHub Releases。项目记忆是 2026-08-31 的历史快照，本次以实时开发机和远端证据为准。权限、分支与 PowerShell 的持久行为已同步到 `docs/unified-desktop-runtime.md`，发行证据记录在本文。按仓库约定，本次未改写 `docs/project-state.md` 或全局记忆。
