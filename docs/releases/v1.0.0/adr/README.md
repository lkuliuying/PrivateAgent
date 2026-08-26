# ADR 索引（v1.0.0 Agent 架构改造）

| ADR | 主题 | 状态 |
|---|---|---|
| [ADR-001](./ADR-001-thread-turn-item.md) | Thread/Turn/Item 状态机与兼容矩阵 | Accepted（含 queued/waiting approval 中断语义） |
| [ADR-002](./ADR-002-protocol-transport.md) | Agent 协议 transport：stdio/JSONL（Rust bridge） | Accepted（stdout 协议专用，stderr 日志分流） |
| [ADR-003](./ADR-003-persistence.md) | v2 持久化（表结构/序列仲裁/Store 边界/checksum） | Accepted（Item/Event 序列分离，哈希链落库） |
| [ADR-004](./ADR-004-windows-sandbox.md) | Windows 沙箱技术组合 | Accepted with implementation gate（MIC/Job 已落地并实证；网络强制按 [S4 等价方案](./evidence/s4-network-enforcement-plan.md) AppContainer 路径闭环中） |
| [ADR-005](./ADR-005-legacy-migration.md) | v0.9 → v1 数据迁移（游标/重入/隔离/回退） | Accepted |
| [ADR-006](./ADR-006-exec-host-boundary.md) | Rust Exec Host 边界（AD-T02，专项计划） | Accepted with implementation gate（CT6-01 JSONL spike 端到端跑通；沙箱/网络强制待 CT-6 闭环） |
| [ADR-007](./ADR-007-completion-evidence.md) | 副作用完成证据与 Completion Contract（AD-T05，专项计划） | Accepted |
| [ADR-008](./ADR-008-tool-exposure.md) | 工具暴露与授权分离（AD-T06，专项计划） | Accepted |

规则：状态流转 `Proposed → Accepted → Superseded`；Accepted 前必须附可复现实证（脚本/测试/测量）。
