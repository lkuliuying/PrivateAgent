# S1-T9 v0.9 性能基线报告（已评审）

> 基线：`v0.9.0` 封版提交 `fe7bd1a`；测量时间 2026-08-24T02:22:45.872376+00:00
> 数据库：`127.0.0.1:3306/personal_assistant_test`（专用测试库，决议 D6）
> 依据：上位计划 §19.3；决议 D7——阈值由项目/发布负责人审批，本报告不自批。
> 评审结论：2026-08-24 批准保持上位计划 §19.3 默认预算，不因本次基线放宽。M1 仅是后端代理，M4/M5 待 S5 真实桌面 harness 复核；在复核前默认阈值仍生效。

| 指标 | 口径 | n | p50 (ms) | p95 (ms) | max (ms) |
|---|---|---:|---:|---:|---:|
| M1 会话列表（后端代理指标） | GET /sessions，进程内 ASGI，无模型 | 30 | 313.714 | 476.812 | 646.895 |
| M2 事件持久化延迟 | record_event 严格序列仲裁（行锁+校验+投影） | 100 | 8.323 | 12.128 | 16.239 |
| M3 interrupt→进程树终止 | Job Object terminate→活跃进程=0（父+孙两层） | 3 | 0.212 | 0.334 | 0.334 |

## 延迟/引用项

| 指标 | 目标（§19.3） | 状态 | 口径 |
|---|---|---|---|
| M4_5000_item_first_interactive | p95 ≤ 1.5 s（分页/虚拟化，§19.3） | desktop_harness_required | S5 桌面 harness：注入 5000 Item 夹具 Thread，测量首次可交互时间 |
| M5_reconnect_gap_convergence | 1000 事件缺口 2 s 内收敛（§19.3） | v2_transport_required | S5：after_sequence 补读 1000 事件 + 实时订阅收敛时间 |
| M6_bounded_queue_saturation | 饱和时显式拒绝、无无界内存增长（§19.3） | measured_by_s1_spike | 见 evidence/s1-transport-spike-results-20260824.json T6：队列 64 / 洪泛 384 → 65 正常处理 + 319 显式 retryable 拒绝，零丢失零死锁 |

## 说明

- M1 为后端侧代理指标：S5 桌面 harness 建立后以真实首屏测量替换；
- M2 测得的是 v0.9 严格序列仲裁路径，v2 继承同模式（ADR-003 §3）；
- M3 复用 v0.9 `_JobObject`（生产已验证），测终止延迟而非取消决策链；
- 本机单项测量存在环境噪声，正式验收以 S8 多轮统计为准。
