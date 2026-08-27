"""agent_v2：v1.0 Agent Core（上位计划 §6.1）。

依赖规则（不可反转）：``domain <- runtime/application <- adapters``。
本包在 S1 阶段仅包含 protocol 骨架（schema/codegen）与占位层；
各层实现自 S2 起按里程碑进入。详见
``docs/releases/v1.0.0/adr/README.md``。
"""
