"""agent_v2.domain：公共领域模型（Thread/Turn/Item，ADR-001）。

占位包：S2 起落实现。本层禁止导入 FastAPI、SQLAlchemy、Tauri、
具体 Provider SDK 及任何实现层（adapters/persistence/providers/execution），
由 ``scripts/check_agent_v2_imports.py`` 强制。
"""
