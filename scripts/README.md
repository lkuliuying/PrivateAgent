# 开发与验证脚本

在仓库根目录使用已有开发环境执行。当前产品为 API Key 本机桌面链；这些入口不授权安装、发布或调用真实付费模型。

| 用途 | 入口 |
| --- | --- |
| Python 隔离回归 | `run_coding_validation.py --suite <名称>`；套件、隔离规则见[测试指南](../docs/testing-guide.md) |
| 协议同步检查 | `protocol_codegen.py --check`，底层共享生成器为 `coding_contract_codegen.py` |
| 桌面构建 | `build-client.cmd`；`build-release.bat` 转发到同一本机入口 |
| 兼容构建器 | `build-remote-client.cjs` 和对应 `.cmd`；旧名称不表示恢复服务器账号链 |
| 构建器回归 | `node --test scripts/build-remote-client.test.cjs` |
| 包内隔离验证 | `verify-local-executor.py`、`verify-unified-client.py`，使用合成模型及临时数据 |
| 来源与发布清单 | `generate_release_manifest.py --bundle <明确构建目录>`；不推断安装或测试通过 |
| 签名与更新辅助 | `sign_installer.py`、`generate-latest-json.py`、`windows/updater-signature-verifier/` |
| 模型质量验收 | `run_coding_acceptance.py`、`run_coding_local_probe.py`；真实模型调用需要另行确认费用和测试数据 |
| Windows 开发辅助 | `run-tauri-dev.bat`、`cargo-check-tauri.bat`、`cargo-test-tauri.bat`；先核对脚本里的本机路径和 MSVC 环境 |

`coding_acceptance_*`、`coding_validation_*`、`coding_task_baseline.py` 等模块是上述入口的内部支持代码。历史阶段命名的模块仍可能被正式测试使用，不按名称或日期删除。

脚本生成的工作区通常位于 `.run/`。本次整理将已有摘要及关键证据归入 `.run/records/`；后续脚本仍沿用原输出约定。详见[目录与保留规则](../docs/repository-layout.md)。
