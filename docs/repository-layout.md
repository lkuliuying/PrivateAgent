# 项目目录与文件保留规则

适用源码：2026-09-22 的 API Key 本机桌面链。完整清理依据、实际验证及例外见[本次整理记录](solutions/2026-09-22-project-cleanup.md)。目录和产物存在不代表安装、发布或真实模型验收已经通过。

## 开发入口

| 位置 | 职责与入口 |
| --- | --- |
| [`apps/desktop/`](../apps/desktop/README.md) | Vue 工作区、共置 Vitest 测试、浏览器 E2E、Tauri 桌面壳 |
| [`apps/exec-host/`](../apps/exec-host/) | Rust 命令执行宿主、Windows 沙箱与就绪探测 |
| [`src/private_agent_core/`](../src/private_agent_core/) | AgentRuntime、模型协议和适配器、工具契约、上下文及执行协议 |
| [`src/private_agent_local/`](../src/private_agent_local/) | 本机会话、SQLite、IPC、工具、权限、模型路由、记忆与任务运行 |
| [`tests/`](../tests/README.md) | Python 单元、打包和隔离验收；夹具与题集随测试维护 |
| [`scripts/`](../scripts/README.md) | 隔离验证、协议同步、构建和签名辅助 |
| [`docs/`](README.md) | 当前说明、专题记录、历史归档及证据索引 |
| `.github/`、`.signpath/` | 现有代码所有权、签名发布流程与产物配置 |

根目录保留项目 README、AGENTS、变更记录、许可、隐私和签名政策，以及 Python 依赖和 Git 配置。前端、Rust 依赖清单及锁文件继续放在各自组件目录，业务文件不因清理而移动。

## 测试与文档布局

- Python 测试按 `unit`、`packaging`、`coding_acceptance` 分组，完整套件映射由隔离运行器维护。
- Vue 测试继续与源码共置；E2E 及视觉基线保持原位。历史阶段命名不能作为删除测试的依据。
- 当前使用说明位于文档根目录；专题过程见 [analysis](analysis/README.md)，日期明确的交付见 [solutions](solutions/README.md)。
- 旧架构和已结束计划见 [archive](archive/README.md)，版本契约和检查点见 [releases](releases/README.md)，素材和证据见 [assets](assets/README.md)、[evidence](evidence/README.md)。
- `docs/vue-desktop-code/`、`docs/webfront-code/` 及 `docs/archive/packages/` 是被 Git 忽略的本机外部参考副本。它们不是项目运行依赖；用途未确认时不自动删除或替换。

## 本机产物和保留边界

| 位置 | 处理规则 |
| --- | --- |
| `dist/PrivateAgentCandidate-1.0.20/` | 最新完整候选包，含安装器、桌面程序、执行器、宿主及原始来源和校验记录；未签名、无更新端点 |
| `.run/records/` | 精简后的测试和构建证据，按原始 `.run`、`.tmp`、`dist` 来源分组；继续由 Git 忽略 |
| `.run/records/cleanup-20260922/` | 本次文件基线、处理清单、归档映射、失败例外及实际验证记录 |
| `.run/`、`.tmp/` 的其他内容 | 新运行输出，或因权限、链接、敏感配置、用途和复现价值尚未确认而保留的内容；不能整目录删除 |
| `.venv/`、`apps/desktop/node_modules/`、`.tools/` | 已有开发依赖和本机构建工具，保留 |
| `apps/exec-host/target/release/exec-host.exe` | 源码运行和测试直接使用的宿主，保留；其他编译缓存可重建 |
| 各 `target/`、前端 `dist/`、测试输出、`__pycache__/`、检查缓存 | 可重建产物；先保留必要结果和失败证据再清理 |
| `data/`、环境文件、凭据、个人配置、`.git/` | 保留，不借目录整理读取秘密、修改权限或清理 Git 登记 |
| `.agents/`、`.codex/`、`.claude/`、`.idea/` | 项目工具和个人工作配置，保留 |

构建和验证会再次产生缓存。后续首次构建可能较慢，不需要重新安装已保留的开发依赖。若执行宿主缺失，在具备 Rust/MSVC 环境的终端运行 `cargo build --release --locked --manifest-path apps/exec-host/Cargo.toml`；不能将缺少宿主的测试标为通过。

## 查找历史证据

原 `.run/<路径>` 的已归档文件位于 `.run/records/run/<路径>`；原 `.tmp/<路径>` 位于 `.run/records/tmp/<路径>`；原 `dist/<路径>` 位于 `.run/records/dist/<路径>`。只有成功归档且摘要一致的文件才移除原件；保留例外仍在原位，以本次审计清单为准。

历史报告中的命令及输入路径记录当时执行环境，不批量改写为新命令。查找结果时使用[本机记录索引](../.run/records/README.md)及来源映射。这些本机文件不保证存在于其他克隆；可复跑的正式入口以[测试指南](testing-guide.md)为准。
