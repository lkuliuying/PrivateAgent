# 项目目录与文件保留规则

适用源码：2026-10-28 的 API Key 本机桌面链。Python 源码统一为 `private_agent`，按职责划分模块。早期产物清理依据、实际验证及例外见[整理记录](solutions/2026-09-22-project-cleanup.md)。目录和产物存在不代表安装、发布或真实模型验收已经通过。

## 开发入口

| 位置 | 职责与入口 |
| --- | --- |
| [`apps/desktop/`](../apps/desktop/README.md) | Vue 工作区、共置 Vitest 测试、浏览器 E2E、Tauri 桌面壳 |
| [`apps/exec-host/`](../apps/exec-host/) | Rust 命令执行宿主、Windows 沙箱与就绪探测 |
| [`src/private_agent/`](../src/private_agent/) | 按职责划分的本机 Agent，启动入口为 `entry.py` |
| [`tests/`](../tests/README.md) | Python 单元、打包和隔离验收；夹具与题集随测试维护 |
| [`scripts/`](../scripts/README.md) | 隔离验证、协议同步、构建和签名辅助 |
| [`docs/`](README.md) | 当前说明、专题记录、历史归档及证据索引 |
| `.github/`、`.signpath/` | 现有代码所有权、签名发布流程与产物配置 |

根目录保留项目 README、AGENTS、变更记录、许可、隐私和签名政策，以及 Python 依赖和 Git 配置。前端、Rust 依赖清单及锁文件继续放在各自组件目录。

## Python 模块

| 模块 | 职责 |
| --- | --- |
| `api/` | FastAPI 应用、私有 stdio IPC 和各功能路由 |
| `contracts/` | Agent、Coding、计划、补丁契约及生成的 JSON Schema |
| `agent/` | `loop.py` 中的 AgentRuntime、`runtime.py` 中的本机任务编排，以及适配、计划、完成验证、恢复、观察与反思 |
| `models/` | 模型配置、凭据、偏好、能力探测与评测；`llm/` 保存供应商协议、适配器和网关 |
| `context/` | 项目指令、请求组装、历史、压缩与交接；`budget.py` 提供预算契约和算法，`usage.py` 计算本机使用量 |
| `memory/` | 长期记忆、记忆存储及授权工具 |
| `workspace/` | 文件、仓库、Git 工作区、worktree、补丁、草稿、搜索及附件 |
| `tools/` | 工具契约、注册表、目录，以及 Git、浏览器和技能工具 |
| `execution/` | 命令执行、宿主协议及客户端、执行会话、Windows 进程与沙箱 |
| `integrations/` | 通用 MCP、文档 MCP、服务库、MCP 凭据及公开 HTTP 传输 |
| `storage/` | 主 SQLite 存储、历史格式与迁移、应用备份及恢复 |
| `security/` | 本机身份、权限策略和秘密过滤 |

在已有开发环境中通过 `python -m private_agent.entry --help` 查看启动参数。模块间使用明确导入，包初始化文件不集中导出业务对象；原有延迟导入继续留在使用位置。Python 包整理不改变 HTTP/IPC 协议、SQLite 格式、数据目录、凭据标识或桌面可执行文件名称。

## 测试与文档布局

- Python 测试按 `unit`、`packaging`、`coding_acceptance` 分组，完整套件映射由隔离运行器维护。
- Vue 测试继续与源码共置；E2E 及视觉基线保持原位。历史阶段命名不能作为删除测试的依据。
- 当前使用说明位于文档根目录；专题过程见 [analysis](analysis/README.md)，日期明确的交付见 [solutions](solutions/README.md)。
- 旧架构和已结束计划见 [archive](archive/README.md)，版本契约和检查点见 [releases](releases/README.md)，素材和证据见 [assets](assets/README.md)、[evidence](evidence/README.md)。
- `docs/vue-desktop-code/`、`docs/webfront-code/` 及 `docs/archive/packages/` 是被 Git 忽略的本机外部参考副本。它们不是项目运行依赖；用途未确认时不自动删除或替换。

## 本机产物和保留边界

| 位置 | 处理规则 |
| --- | --- |
| `dist/PrivateAgentCandidate-1.0.23/` | 本地留存的最新完整候选包，安装器、桌面程序、执行器及宿主的摘要已复核；无更新端点，不代表当前未提交源码已重新打包或安装验收 |
| `.run/records/` | 精简后的测试和构建证据，按原始 `.run`、`.tmp`、`dist` 来源分组；继续由 Git 忽略 |
| `.run/records/cleanup-20260922/` | 2026-09-22 的历史清理基线、归档映射和验证记录 |
| `.run/records/cleanup-20261028/` | 本轮逐文件清单、归档摘要、执行结果、保留例外及源码完整性验证 |
| `.run/module-reorganization/` | 未提交的源码模块迁移快照和验证记录，原位保留 |
| `.run/release-*/`、已登记 worktree | 正式发布回执、签名资产及 Git 工作树，独立保留，不参与候选包淘汰 |
| `.run/`、`.tmp/` 的其他内容 | 新运行输出，或因权限、链接、敏感配置、用途和复现价值尚未确认而保留的内容；不能整目录删除 |
| `.venv/`、`apps/desktop/node_modules/`、`.tools/` | 已有开发依赖和本机构建工具，保留 |
| `apps/exec-host/target/release/exec-host.exe` | 源码运行和测试直接使用的宿主，保留；其他编译缓存可重建 |
| `scripts/windows/updater-signature-verifier/target/release/private-agent-updater-signature-verifier.exe` | 打包测试所需的验签辅助程序，保留；其他编译缓存可重建 |
| 各 `target/`、前端 `dist/`、测试输出、`__pycache__/`、检查缓存 | 可重建产物；先保留必要结果和失败证据再清理 |
| `data/`、环境文件、凭据、个人配置、`.git/` | 保留，不借目录整理读取秘密、修改权限或清理 Git 登记 |
| `.agents/`、`.codex/`、`.claude/`、`.idea/` | 项目工具和个人工作配置，保留 |

构建和验证会再次产生缓存。后续首次构建可能较慢，不需要重新安装已保留的开发依赖。若执行宿主缺失，在具备 Rust/MSVC 环境的终端运行 `cargo build --release --locked --manifest-path apps/exec-host/Cargo.toml`；不能将缺少宿主的测试标为通过。

## 查找历史证据

原 `.run/<路径>` 的已归档文件位于 `.run/records/run/<路径>`；原 `.tmp/<路径>` 位于 `.run/records/tmp/<路径>`；原 `dist/<路径>` 位于 `.run/records/dist/<路径>`。只有成功归档且摘要一致的文件才移除原件；保留例外仍在原位，以本次审计清单为准。

历史报告中的命令及输入路径记录当时执行环境，不批量改写为新命令。查找结果时使用[本机记录索引](../.run/records/README.md)及来源映射。这些本机文件不保证存在于其他克隆；可复跑的正式入口以[测试指南](testing-guide.md)为准。
