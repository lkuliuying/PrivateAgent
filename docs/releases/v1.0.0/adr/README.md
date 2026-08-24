# ADR 索引（v1.0.0 Agent 架构改造）

| ADR | 主题 | 状态 |
|---|---|---|
| [ADR-001](./ADR-001-thread-turn-item.md) | Thread/Turn/Item 状态机与兼容矩阵 | Accepted（含 queued/waiting approval 中断语义） |
| [ADR-002](./ADR-002-protocol-transport.md) | Agent 协议 transport：stdio/JSONL（Rust bridge） | Accepted（stdout 协议专用，stderr 日志分流） |
| [ADR-003](./ADR-003-persistence.md) | v2 持久化（表结构/序列仲裁/Store 边界/checksum） | Accepted（Item/Event 序列分离，哈希链落库） |
| [ADR-004](./ADR-004-windows-sandbox.md) | Windows 沙箱技术组合 | Accepted with implementation gate（MIC/Job 接受；网络强制待 S4 闭环） |
| [ADR-005](./ADR-005-legacy-migration.md) | v0.9 → v1 数据迁移（游标/重入/隔离/回退） | Accepted |

规则：状态流转 `Proposed → Accepted → Superseded`；Accepted 前必须附可复现实证（脚本/测试/测量）。
