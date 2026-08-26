# CT-8 · Codex App Server Spike 评估结论（2026-08-25）

> 专项计划 §15 CT-8（研究项，3–5 天，S6）；§27 决议表既定推荐：**dev-only Spike**。
> 状态：**Defer（有条件）**——本轮完成可行性与价值评估，未执行运行时 Spike；
> 触发条件与执行清单如下，满足即启动。

## 1. 评估结论：Defer

| 维度 | 结论 |
|---|---|
| 前置依赖 | 需要外部 OpenAI Codex App Server 可执行产物与受控网络出口；本会话安全策略已收紧至禁止 exec-host 派生子进程（见 [N1c-attempt](./n1c-attempt-20260825.json)），Spike 所需的"独立样例 workspace + App Server 子进程 + 本地 Ollama/Qwen Provider"三件套均无法在当前会话成立 |
| 边际价值 | 主链（CT-0～5、CT6 沙箱强制、CT-7、CT-9、§19.2 soak）已在 PrivateAgent 自有 Runtime 上闭环；App Server 仅作为"可选第二 Turn executor"的对照研究，不阻塞任何 P0 门禁（计划书 §16 明示 CT-7/CT-8 不阻断 P0/S8/RC） |
| 风险 | 计划书 §23 已列"App Server 造成双执行器/双事实源"为高影响风险；在 N1c 未闭环前引入第二执行器会放大该风险面 |

## 2. 触发条件（满足任一即启动 Spike）

1. N1c 关闭（NET_DENIED(10013)+对照组 NET_OK 判别式证据对归档），且
   会话允许派生子进程；
2. 产品决策需要评估"OpenAI 托管工具/Responses tool item"生态接入
   （当前多 Provider 矩阵无此需求）。

## 3. 执行清单（触发后按序，预计 3–5 天）

1. **环境准备（0.5 天）**：获取 openai/codex@<新冻结 commit> 的
   app-server 产物；独立样例 workspace（无生产秘密）；独立测试库；
   更新 `docs/third-party/codex-adoption-manifest.md` 分类 C 条目。
2. **协议探针（1 天）**：stdio/JSONL 握手 + thread/start + turn/start
   最小往返；记录事件模型与 ADR-002 差异矩阵。
3. **Provider 兼容（1 天）**：接本地 Ollama/Qwen profile，复跑 §8.2 六类
   probe 用例，与原生 Runtime 成功率对比（同数据集）。
4. **审批/证据边界验证（1 天）**：验证 App Server 是否可被限制为
   "单一 Turn executor"——审批、Effect/Evidence、审计全部留在
   PrivateAgent 侧；任一绕过即 Reject。
5. **结论报告（0.5 天）**：Adopt/Reject/Defer 三选一，含成功率/延迟/
   资源对比表；归档至 `adr/evidence/ct8-app-server-spike-results-*.json`。

## 4. 不启动的影响

- 不影响 §26 DoD 第 1–12 条中的任何条目（CT-8 属研究项）；
- v1.0.0 发布判定继续以自有 Runtime 主链门禁为准。
