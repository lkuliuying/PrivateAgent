# Codex 上游采用清单（Codex Adoption Manifest）

> 专项计划：[v1.0.0 Codex 工具体系融合开发计划书](../releases/v1.0.0/v1.0.0-codex-tool-engine-integration-plan-20260825.md) §3/§22
> 建立日期：2026-08-25（CT0-01）
> 状态：Active

## 1. 固定参考快照

| 项目 | 值 |
|---|---|
| 上游仓库 | `openai/codex` |
| 冻结 commit | `465eafacbc2db4ff828cd6d18ed8f25d22e48f53` |
| 上游许可证 | Apache-2.0 |
| 升级策略 | 只从冻结 commit 升级到经人工评审的新 commit；不追随漂移的 `main` |
| 评估节奏 | 季度评估一次；不作为单版本发布阻断 |

规则（计划书 §3.1/§22.1）：

1. 任何复制或修改上游代码的提交必须保留 Apache-2.0 许可证与版权声明；
2. 架构思想和接口语义可以重新实现，无需登记；**源码复用必须逐文件登记在本清单**；
3. 本清单中每个"已采用"条目必须有 owner、上游路径、上游 commit、本地落点与本地替代边界；
4. 不复制 OpenAI 品牌、内部服务地址、认证流程、产品 UI 和产品专属 prompt（分类 D）。

## 2. 采用分类总表（专项计划 §3.2）

| 分类 | 内容 | 采用方式 | 当前状态 |
|---|---|---|---|
| A：直接重实现 | Registry、Router、Exposure、Lifecycle、Tool Search、并发规则 | 在 Python `agent_v2` 按本项目契约实现 | 进行中（CT-1/CT-2 起） |
| B：选择性源码复用 | apply-patch parser、PTY、进程树、Windows 沙箱辅助逻辑 | 独立 Rust crate/binary，保留归属和上游 commit | 未开始（CT-5/CT-6） |
| C：协议适配 | Codex App Server、Responses tool item | 隔离 adapter/Spike，不进入主事实链 | 未开始（CT-8，dev-only） |
| D：只参考不采用 | ChatGPT 登录、OpenAI 托管工具、产品 UI、专属 prompts | 不进入 PrivateAgent | 持续有效 |
| E：延后 | Skills、Hooks、子 Agent、Computer Use | v1.1+ 单独立项 | 延后 |

## 3. 逐文件登记表（源码复用，分类 B/C 专用）

> 分类 A 为重实现，不落入本表；仅记录对应研究参考路径。

### 3.1 已采用条目

（当前为空——本专项尚未复制任何上游源码文件。）

| # | 上游路径（@冻结 commit） | 本地落点 | Owner | 许可证处理 | 引入版本/commit | 备注 |
|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — |

### 3.1.1 评估记录（已评估、暂不采用）

| 上游模块 | 评估日期 | 结论 | 理由 |
|---|---|---|---|
| `codex-rs/apply-patch/`（自由文本 patch parser） | 2026-08-25（CT-5） | **Defer** | Qwen/Ollama 默认走严格 JSON Function Tool（AD-T04），自由格式解析成功率依赖模型专门训练；P0 统一内部表示冻结为结构化 `PatchOperation[]`（`agent_v2/domain/patch_operations.py`）。仅当 §8.2 模型 probe 证明某 Provider 自由 patch 稳定后，再按分类 B 移植该 parser 并登记本表 |

### 3.2 研究参考路径（分类 A 重实现对照，不复制源码）

| 上游路径 | 参考主题 | 对应工作包 | 本地实现位置 |
|---|---|---|---|
| `codex-rs/core/src/tools/` | 工具注册/路由/暴露分层 | CT-2/CT-4 | `src/personal_assistant/agent_v2/domain/tool_catalog.py`、`application/catalog.py`、`application/planner.py` |
| `codex-rs/app-server/` | 执行宿主进程边界 | CT-6/CT-8 | `apps/exec-host/`（规划，ADR-006） |
| `codex-rs/app-server-protocol/` | JSONL 方法/事件协议形态 | CT-6 | `agent_v2/execution/contracts.py`（规划） |
| `codex-rs/apply-patch/` | patch parser 结构 | CT-5 | 统一 PatchOperation（规划） |
| `codex-rs/windows-sandbox-rs/` | Windows 沙箱组合 | CT-6 | ADR-004 组合沿用 |

## 4. 升级检查模板

每次升级冻结 commit 时按序执行并记录结论：

1. `git diff <旧commit>..<新commit> -- <已采用路径>`：逐文件审阅差异；
2. 新增依赖的许可证与供应链审查（`cargo audit` / SBOM 更新）；
3. 行为语义变化是否影响本地替代边界；影响则先改本地契约测试再合并；
4. 更新本清单冻结 commit 与逐文件条目的"上游 commit"列；
5. 结论记录到 `docs/releases/v1.0.0/adr/evidence/`（升级 diff 报告）。

## 5. 发布合规门禁

- 发布包包含 Apache-2.0 LICENSE/NOTICE 要求的材料（§22.1）；
- SBOM 与二进制 SHA 记录随发布证据归档；
- 出现未登记的上游源码复用 = 发布阻断项。
