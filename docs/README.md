# PrivateAgent 文档中心

当前源码以 **2026-09-20 的 API Key 本机桌面链**为准：Tauri/Vue、Python 本机执行器、共享 AgentRuntime、SQLite。旧服务器、账号系统、MySQL/Alembic、RAG 和个人中枢页面已经退役。

## 当前入口

| 需要了解 | 文档 |
| --- | --- |
| 产品、架构、开发环境与构建 | [项目 README](../README.md) |
| 完整目录职责、产物位置与保留规则 | [项目目录说明](repository-layout.md) · [脚本入口](../scripts/README.md) · [正式测试目录](../tests/README.md) |
| 会话约定与历史状态 | [AGENTS.md](../AGENTS.md) · [项目状态记忆](project-state.md) |
| 当前源码范围与已知验证限制 | [本机化与上下文改进](solutions/2026-09-20-local-only-context.md) |
| API Key、模型调用与身份空间 | [本机模型直连](direct-model-execution.md) |
| 搜索、任务控制、审阅、Skills、通用 MCP 与浏览器证据 | [工作台使用说明](workbench-guide.md) · [2026-09-21 交付记录](solutions/2026-09-21-workbench-upgrade.md) |
| 工具契约、审批、Git 与文档 MCP | [本机工具系统](local-tool-system.md) |
| 上下文预算、压缩与原文续读 | [上下文设计](context-design.md) |
| 本机记忆与用户控制 | [记忆设计](memory-design.md) |
| 测试目录、隔离运行与验证命令 | [测试指南](testing-guide.md) |
| GitHub Release 更新源与正式发布验收 | [1.0.0 发布操作说明](releases/v1.0.0/github-release.md) · [签名政策](../CODE_SIGNING_POLICY.md) |
| 历史签名方案 | [SignPath 申请记录（未启用）](signpath-application.md) |
| 本次目录整理及删除依据 | [2026-09-22 清理记录](solutions/2026-09-22-project-cleanup.md) · [2026-09-20 历史清理](solutions/2026-09-20-project-cleanup.md) |

项目状态记忆保留 2026-09-19 及更早日期的事实，不代表 2026-09-20 之后的代码或部署状态。当前实现以源码和对应日期的交付记录核对；外部签名、部署及安装状态需要各自证据。

## 目录分工

| 目录 | 用途 |
| --- | --- |
| `docs/` | 当前入口、持续维护的本机说明与项目记忆 |
| [`analysis/`](analysis/README.md) | Coding 专项与三步改进计划，按各自日期和验收状态阅读 |
| [`solutions/`](solutions/README.md) | 带日期的修复、验证与整理记录 |
| [`archive/legacy/`](archive/legacy/README.md) | 已退役架构、服务器操作、旧产品手册和 RAG 研究 |
| [`archive/`](archive/README.md) | 更早的阶段计划、路线图和设计过程资料 |
| [`releases/`](releases/README.md) | 历史版本契约、检查点、ADR 和验收记录 |
| [`examples/`](examples/) | 可复制的配置模板；生成的真实发布清单不作为模板保存 |
| [`assets/`](assets/README.md)、[`evidence/`](evidence/README.md) | 被文档引用的图片、历史验收证据和本机结果索引 |
| [`third-party/`](third-party/) | 上游采用与归属记录 |

## 查阅历史

- [2026-09-17 三步改进计划](analysis/agent-improvement-20260917/README.md)及其试用记录。
- [2026-09-08 Coding 改造计划](analysis/coding-agent-upgrade-20260908/README.md)及 S0–S6 验收记录。
- [2026-09-19 API Key 单模式交付](solutions/2026-09-19-api-key-only.md)。
- [旧服务器与产品文档索引](archive/legacy/README.md)。

历史记录保留原有结论、未完成项和失败证据。归档中的源码路径、命令、版本和截图反映记录当时的系统，不能据此执行当前部署或宣布当前功能可用。

## 维护规则

1. 当前使用方式和可执行命令进入本页对应的本机说明。
2. 旧功能文档进入历史归档；日期明确的阶段记录保留在原专题或版本目录。
3. 移动文件时同步本地链接；测试文件按现有职责分组，入口同步到隔离运行器。
4. 不将运行日志、安装包、测试结果、个人配置或本机工具副本写入正式文档目录。
5. `.run/`、`.tmp/` 和被 Git 忽略的外部规范副本是本机材料，不保证其他工作区存在。
6. 已归档的本机输出在 `.run/records/` 按原始来源查找。历史命令和验收结论保留原文；仅修正文档链接和新增归档映射，不将清理当作重新验收。详见[目录说明](repository-layout.md#查找历史证据)。
