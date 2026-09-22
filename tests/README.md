# 正式测试目录

| 目录 | 内容 |
| --- | --- |
| [`unit/`](unit/) | 本机运行时、模型、上下文、权限、安全、工具及存储 |
| [`packaging/`](packaging/) | NSIS 模板、构建清单及签名编排 |
| [`coding_acceptance/`](coding_acceptance/README.md) | 合成题集、评测协议、隔离守卫、执行宿主和持续运行场景 |

Vue 单元测试与源码共置于 `apps/desktop/src/`，浏览器流程和视觉基线位于 `apps/desktop/e2e/`。Node 构建器测试和 Rust 模块测试继续跟随对应组件。

Python 测试必须通过[隔离运行器](../scripts/run_coding_validation.py)或同等隔离环境运行；不要在仓库根直接运行会继承个人配置的裸 pytest。正式命令、结果边界和已知限制见[测试指南](../docs/testing-guide.md)。

2026-09-22 整理前后均收集到 80 个 Python 文件、2,087 个测试节点，节点清单完全一致。这是收集结果，不是断言通过数。当前正式测试、题集、夹具和视觉基线全部保留；临时测试工作区及复制的工具链在保存摘要后清理，历史结果见[本机记录索引](../.run/records/README.md)。
