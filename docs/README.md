# PrivateAgent 文档中心

这里是项目文档的统一入口。根目录仅保留持续维护的产品、架构、开发和运维文档；阶段性计划、历史材料、版本检查点和二进制参考资料分别归档。

> 文档状态：2026-08-20。`v0.5.0-rc.4` 已作为 Coding Agent 工程基线，当前可进入 `v0.6.0` 开发；自然日观察统一顺延到 `v1.0.0-rc.1` 功能开发完成后执行。检查点文档用于记录当时事实，不等同于正式发布公告。

## 快速入口

- 使用产品：[使用指南](./usage-guide.md)、[故障排查](./troubleshooting.md)
- 搭建环境：[部署指南](./deployment-guide.md)、[跨平台说明](./cross-platform.md)
- 参与开发：[需求说明](./requirements.md)、[目标架构](./target-architecture.md)、[测试指南](./testing-guide.md)、[Coding Agent 重构计划](./coding-agent-refactor-plan.md)
- 当前策略：[观察期顺延决策](./releases/observation-policy-20260820.md)、[v0.6.0 开工审计](./releases/v0.6.0/v0.6.0-readiness-20260820.md)
- 工程基线：[v0.5.0 开发计划](./releases/v0.5.0/v0.5.0-development-plan-20260809.md)、[rc.4 检查点](./releases/v0.5.0/v0.5.0-rc.4-checkpoint-20260810.md)、[Day 10 历史记录](./releases/v0.5.0/observation-day10-20260820.md)
- 后续版本：[Coding Agent 版本路线图](./releases/coding-agent-version-roadmap-20260820.md)、[v0.6.0 开工审计](./releases/v0.6.0/v0.6.0-readiness-20260820.md)、[C0 契约](./releases/v0.6.0/v0.6.0-c0-contracts-20260820.md)、[v0.6.0 开发计划](./releases/v0.6.0/v0.6.0-development-plan-20260820.md) 至 [v1.0.0](./releases/v1.0.0/v1.0.0-development-plan-20260820.md)
- 发布维护：[发布检查清单](./release-checklist.md)、[数据库升级手册](./database-upgrade-runbook.md)、[签名与密钥](./signing-and-keys.md)

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
| [`vue-desktop-code/`](./vue-desktop-code/) | 桌面端工程规范与参考资料 |
| [`webfront-code/`](./webfront-code/) | Web 前端工程规范与参考资料 |

## 维护规则

1. 持续有效的架构、接口、测试和运维文档放在 `docs/` 根目录。
2. 版本计划、契约和检查点放在 `releases/vX.Y.Z/`，文件名保留版本号与日期。
3. 已完成或被替代的阶段计划移入 `archive/`，不要删除其中的历史结论。
4. JSON 示例放在 `examples/`；图片和 PDF 放在 `assets/`；运行生成的证据放在 `evidence/` 或 `dist/`。
5. 新增或移动文档后，必须更新本索引并检查仓库内的本地链接和路径契约。
