"""agent_v2.execution：Exec Host 协议契约与客户端（专项计划 §11，CT-6）。

实现层边界（AD-T02）：本包只承载 Exec Host 的传输与协议事实；
审批、策略、durable fact 与完成判定全部留在 Python Agent Core。

依赖规则：execution 属实现层，可导入 domain/application；禁止导入
FastAPI/Tauri/Provider SDK。
"""
