# PrivateAgent 文档中心

这里是项目文档的统一入口。根目录仅保留持续维护的产品、架构、开发和运维文档；阶段性计划、历史材料、版本检查点和二进制参考资料分别归档。

> 文档状态：2026-08-31。源码声明版本为 `1.0.0`，当前开发分支为 `dev/1.0.0`。历史计划、检查点和观察记录只说明当时状态，不等同于当前发布公告或重新验收结论。

| 范围 | 已确认状态 | 使用边界 |
|---|---|---|
| 普通版 | 已发布 `v0.2.1`，仍为 GitHub Latest | 保留普通版下载和更新入口 |
| 远程版 | 已发布 `remote-v1.0.2` | 与普通版分开维护更新渠道 |
| 远程测试包 | `remote-v1.0.3-test.1` 为测试草稿 | 原包为 `debcd81` 加当时工作区改动，`dirty=true`；本次未重新构建，不能作为当前源码的干净构建证明 |
| 其他历史草稿 | `0.5.0-rc.4`、`v1.0.0` | `v1.0.0` 草稿为历史远程便携客户端，不是普通版正式安装包 |

草稿名称可能尚无对应实际 Git 标签；应按[仓库维护说明](./repository-maintenance-20260831.md)核对标签、源码提交和附件身份后再发布。仓库文件中出现 `1.0.0` 或 `1.0.3`，不能据此推断存在同名正式 Release。

## 快速入口

- 本次部署与换机：[2026-08-30 部署交接总结](./deployment-handoff-20260830.md)、[在另一台 Windows 电脑继续开发](./new-computer-development.md)
- 当前交接边界：[1.0.3 测试包与源码交接](./next-agent-handoff-1.0.3.md)、[联网客户端部署](./connected-desktop-rollout.md)、[联网客户端本机执行](./connected-desktop-local-execution.md)
- 使用产品：[使用指南](./usage-guide.md)、[故障排查](./troubleshooting.md)
- 搭建环境：[部署指南](./deployment-guide.md)、[跨平台说明](./cross-platform.md)
- 参与开发：[需求说明](./requirements.md)、[目标架构](./target-architecture.md)、[测试指南](./testing-guide.md)、[Coding Agent 重构计划](./coding-agent-refactor-plan.md)
- 历史观察策略：[观察期顺延决策](./releases/observation-policy-20260820.md)、[Day 10 历史记录](./releases/v0.5.0/observation-day10-20260820.md)
- 历史工程基线：[v0.5.0 开发计划](./releases/v0.5.0/v0.5.0-development-plan-20260809.md)、[rc.4 检查点](./releases/v0.5.0/v0.5.0-rc.4-checkpoint-20260810.md)、[v0.8.0 交接与分支勘误](./releases/v0.8.0/v0.8.0-handoff-to-v0.9.0-20260822.md)
- 版本计划与契约：[Coding Agent 版本路线图](./releases/coding-agent-version-roadmap-20260820.md)、[v0.6.0 开工审计](./releases/v0.6.0/v0.6.0-readiness-20260820.md)、[C0 契约](./releases/v0.6.0/v0.6.0-c0-contracts-20260820.md)、[v0.6.0 开发计划](./releases/v0.6.0/v0.6.0-development-plan-20260820.md) 至 [v1.0.0](./releases/v1.0.0/v1.0.0-development-plan-20260820.md)
- 发布维护：[发布检查清单](./release-checklist.md)、[远程客户端更新](./remote-client-updates.md)、[数据库升级手册](./database-upgrade-runbook.md)、[签名与密钥](./signing-and-keys.md)
- 仓库维护：[分支、标签、Release 与文件治理](./repository-maintenance-20260831.md)、[构建与运维脚本索引](../scripts/README.md)

## 长期维护文档

| 主题 | 文档 |
|---|---|
| 产品与使用 | [需求说明](./requirements.md) · [使用指南](./usage-guide.md) · [故障排查](./troubleshooting.md) |
| 系统架构 | [目标架构](./target-architecture.md) · [Coding Agent 重构计划](./coding-agent-refactor-plan.md) · [上下文设计](./context-design.md) · [Agent Runtime](./agent-runtime.md) |
| 核心能力 | [工具系统](./tool-system.md) · [MCP 设计](./mcp-design.md) · [记忆设计](./memory-design.md) · [RAG 设计](./rag-design.md) |
| 数据与接口 | [数据库设计](./database-design.md) · [API 参考](./api-reference.md) · [领域验证器](./domain-verifiers.md) |
| 安全与运行 | [安全模型](./security-model.md) · [Ollama 生命周期](./ollama-lifecycle.md) · [灰度验证](./agent-runtime-gray-verification.md) |
| 交付与质量 | [测试指南](./testing-guide.md) · [部署指南](./deployment-guide.md) · [发布检查清单](./release-checklist.md) |

## 目录说明

| 目录 | 内容 |
|---|---|
| [`analysis/`](./analysis/) | 现代化审计、缺口分析等专题分析 |
| [`releases/`](./releases/) | 按版本保存开发计划、契约、进度和检查点 |
| [`archive/`](./archive/) | 已结束阶段计划、旧路线图、历史提示词和工具包 |
| [`examples/`](./examples/) | 可复制使用的 JSON 配置与评估样例 |
| [`assets/`](./assets/) | 图片、PDF 等非 Markdown 参考资料 |
| [`evidence/`](./evidence/) | 质量门槛、演练和验收证据 |
| `vue-desktop-code/`（可选本地目录） | 外部桌面端工程参考资料，已被 Git 忽略，不随克隆提供 |
| `webfront-code/`（可选本地目录） | 外部 Web 前端工程参考资料，已被 Git 忽略，不随克隆提供 |

## 维护规则

1. 持续有效的架构、接口、测试和运维文档放在 `docs/` 根目录。
2. 版本计划、契约和检查点放在 `releases/vX.Y.Z/`，文件名保留版本号与日期。
3. 已完成或被替代的阶段计划移入 `archive/`，不要删除其中的历史结论。
4. JSON 示例放在 `examples/`；图片和 PDF 放在 `assets/`；运行生成的证据放在 `evidence/` 或 `dist/`。
5. 新增或移动文档后，必须更新本索引并检查仓库内的本地链接和路径契约。
6. 外部参考目录、安装包和临时过程文件继续遵守 `.gitignore`；历史引用优先使用归档路径或固定提交链接，不为修复导航而重新纳入临时产物。
