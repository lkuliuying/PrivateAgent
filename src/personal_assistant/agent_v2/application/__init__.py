"""agent_v2.application：用例与编排服务层。

依赖方向：application → domain（禁止反向、禁止导入 adapters/实现层，
``scripts/check_agent_v2_imports.py`` 强制）。

- catalog：Tool Catalog 构建（唯一性/别名冲突/规范化 hash，CT2-02）；
- planner：ToolPlan 与 ToolSnapshot 暴露决策（CT2-03）；
- preflight：模型调用前的必需副作用预检（CT1-04）；
- intent_rules：v0.9 启发式 → v2 ExecutionIntent 规则桥接（CT1-02）；
- effect_mapping / contract_factory：完成门禁收口的可信映射与契约工厂
  （CT1-05，ADR-007）。
"""
