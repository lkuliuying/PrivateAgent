# 构建、运维与验证脚本索引

本页按用途索引 `scripts/` 的既有受控文件，并纳入发布验证入口。脚本、共享模块、测试文件及 Rust 验签工程分别说明；不移动文件、不改调用路径。前端目录内的专项脚本仍由 [桌面端 package.json](../apps/desktop/package.json) 和[测试指南](../docs/testing-guide.md)管理。

## 执行前必须确认

- 以下是源码能力索引，不是本机执行成功清单。本次仓库整理没有运行构建、数据库操作或产品回归测试。
- **历史机路径尚未适配**：`run-tauri-dev.bat`、`cargo-check-tauri.bat`、`cargo-test-tauri.bat` 硬编码了 `F:\Program\Agent` 和 Visual Studio 2022 BuildTools 路径，不能直接作为任意检出目录的通用入口。前者还会强制结束占用 1420 端口的进程，运行前必须核对进程归属。`run_release_checks.py` 会调用两个 Cargo 包装脚本，因此完整门禁也受该限制。
- 其他入口也应先确认 Python、Node、Rust、MSVC、数据库和本地模型等各自依赖。按脚本说明从仓库根目录执行；不能因为文件名含 `check`、`verify`、`smoke` 就认定它只读。
- 数据库克隆、迁移、演练、性能测量、Agent 驱动和 soak 脚本可能写库、生成样本、启动服务或执行工具。先阅读[数据库升级手册](../docs/database-upgrade-runbook.md)及对应脚本参数，使用其约定的测试库或副本；保留已有备份、确认参数和数据隔离机制。
- 发布验证不等于发布授权。普通版与远程版更新渠道分别维护；构建记录、源码 SHA、签名和附件哈希必须相互对应，不能通过改标签说明为旧包补造来源。见[发布检查清单](../docs/release-checklist.md)、[远程客户端更新](../docs/remote-client-updates.md)和[仓库维护说明](../docs/repository-maintenance-20260831.md)。
- `.env`、`.secrets/`、签名材料、数据库、日志及 `.run/` 中的本机记录不随脚本交付。`read_process_env.py` 可以读取指定的进程环境变量，包括运行凭证，仅供已授权的本机 QA；不能将相关输出放入报告、聊天或仓库。

## 核心入口

| 任务 | 入口 | 前提与实际影响 |
|---|---|---|
| 启动桌面开发环境 | [run-tauri-dev.bat](./run-tauri-dev.bat) | 历史机专用路径待适配；会清理 1420 端口进程、设置 MSVC 环境并启动 Tauri，勿直接用于当前检出 |
| 打包普通版 Python 后端 | [build-sidecar.bat](./build-sidecar.bat)、[build-sidecar.sh](./build-sidecar.sh) | 需对应平台构建依赖；运行 PyInstaller 并写入 sidecar 构建产物，两个平台分别验证 |
| 构建普通版 Windows 安装包 | [build-release.bat](./build-release.bat) | 串联 sidecar、MSVC、Tauri/NSIS 和交付清单；可能读取本机签名材料，不上传 Release |
| 构建远程客户端 | [build-remote-client.cmd](./build-remote-client.cmd) → [build-remote-client.cjs](./build-remote-client.cjs) | 参数预览、测试安装包和正式更新包模式不同；输出独立应用与更新渠道，详见远程客户端文档 |
| 准备联网后端补丁 | [prepare-connected-backend.py](./prepare-connected-backend.py) | 固定源码路径与历史基线校验；可生成补丁归档，不读取环境文件、不自动部署或重启服务 |
| 检查联网部署源码 | [verify-deployment-regressions.py](./verify-deployment-regressions.py) | 不加载环境文件、不连接数据库的定向回归入口；仍会执行测试，不能替代服务器验收 |
| 检查已打包本机执行器 | [verify-local-executor.py](./verify-local-executor.py) | 需要已构建的可执行文件；启动真实进程进行 smoke，不需要账号或供应商凭据 |
| 发布快速检查 | [release-check.bat](./release-check.bat) | 执行后端测试、前端构建、Cargo 检查及迁移状态检查；依赖环境不齐全时须审阅跳过项 |
| 发布完整检查 | [release-check-full.bat](./release-check-full.bat) → [run_release_checks.py](./run_release_checks.py) | 串联实际构建、测试与运行检查并写证据；目前仍受两个 Cargo 包装脚本的硬编码路径限制 |
| 发布源码与附件校验 | [verify-release.ps1](./verify-release.ps1) | `Source` 核对标签、HEAD、事件 SHA、应用版本并写工作流输出；`Assets` 读取 Release 并拒绝附件重名；均不上传或发布 |
| 建立专用测试库 | [prepare_test_database.py](./prepare_test_database.py) | 根据测试库配置创建并迁移数据库，要求显式 `--yes`；先核对目标库 |
| 升级前克隆与演练 | [clone_application_database.py](./clone_application_database.py)、[rehearse_database_upgrade.py](./rehearse_database_upgrade.py) | 克隆并校验表与行数，再仅在已验证副本上演练；不是生产库直接升级入口 |
| 检查协议生成物 | [protocol_codegen.py](./protocol_codegen.py) | `--check` 只比对；不带该参数会覆盖生成文件，不能把两种模式混用 |

## 完整分类清单

下列清单覆盖本页建立时 `scripts/` 的全部既有受控文件及新增发布验证器；本索引自身不作为可执行脚本计数。文件名包含旧版本表示对应历史验证口径，不是删除依据。

### 构建、发布与签名

| 文件 | 用途与边界 |
|---|---|
| [_find-msvc.bat](./_find-msvc.bat) | 查找 MSVC 开发环境，供调用脚本复用 |
| [_find-uv.bat](./_find-uv.bat) | 查找 uv 可执行文件，供调用脚本复用 |
| [_release_utils.py](./_release_utils.py) | 发布工具共享辅助模块，不是独立发布入口 |
| [build-release.bat](./build-release.bat) | 普通版 Windows NSIS 安装包构建 |
| [build-remote-client.cmd](./build-remote-client.cmd) | 远程客户端 Windows 构建包装入口 |
| [build-remote-client.cjs](./build-remote-client.cjs) | 远程客户端配置、构建、签名验证和输出清单逻辑 |
| [build-remote-client.test.cjs](./build-remote-client.test.cjs) | 远程客户端构建脚本的自动化测试 |
| [build-sidecar.bat](./build-sidecar.bat) | Windows Python sidecar 打包 |
| [build-sidecar.sh](./build-sidecar.sh) | macOS/Linux Python sidecar 打包 |
| [generate-latest-json.py](./generate-latest-json.py) | 生成普通版更新清单，须使用最终产物及签名 |
| [generate_release_manifest.py](./generate_release_manifest.py) | 汇总真实构建身份、哈希及发布检查结果 |
| [release-check.bat](./release-check.bat) | 发布前快速检查 |
| [release-check-full.bat](./release-check-full.bat) | 完整发布检查的 Windows 包装入口 |
| [run_release_checks.py](./run_release_checks.py) | 完整检查编排及 JSON/Markdown 证据输出；需处理上述 Cargo 路径限制 |
| [verify-release.ps1](./verify-release.ps1) | 工作流源码身份及附件冲突校验，不执行发布 |
| [sign_installer.py](./sign_installer.py) | Windows Authenticode 签名、已有签名验证及状态记录；与 Tauri updater 签名区分 |
| [windows/updater-signature-verifier/Cargo.toml](./windows/updater-signature-verifier/Cargo.toml) | Tauri 更新签名验证器工程与依赖配置 |
| [windows/updater-signature-verifier/Cargo.lock](./windows/updater-signature-verifier/Cargo.lock) | 验签器依赖锁定，不是临时构建产物 |
| [windows/updater-signature-verifier/src/main.rs](./windows/updater-signature-verifier/src/main.rs) | 使用公钥验证安装包与 updater `.sig` 是否匹配 |

### 开发与契约检查

| 文件 | 用途与边界 |
|---|---|
| [run-tauri-dev.bat](./run-tauri-dev.bat) | 历史机 Tauri 开发启动；硬编码路径并结束 1420 端口进程，先适配再使用 |
| [cargo-check-tauri.bat](./cargo-check-tauri.bat) | 历史机 Rust 编译检查；硬编码仓库与 MSVC 路径 |
| [cargo-test-tauri.bat](./cargo-test-tauri.bat) | 历史机 Rust 单元测试；硬编码仓库与 MSVC 路径 |
| [check_agent_v2_imports.py](./check_agent_v2_imports.py) | 检查 Agent v2 的模块导入边界 |
| [protocol_codegen.py](./protocol_codegen.py) | 从协议 schema 生成或比对 Python、TypeScript 与 JSON Schema 契约 |

### 联网部署与本机执行器

| 文件 | 用途与边界 |
|---|---|
| [prepare-connected-backend.py](./prepare-connected-backend.py) | 准备、核验固定范围的联网后端补丁归档 |
| [verify-deployment-regressions.py](./verify-deployment-regressions.py) | 联网部署相关源码定向回归，不连接数据库 |
| [verify-local-executor.py](./verify-local-executor.py) | 已打包本机执行器的真实进程 smoke |

### 数据库与容器准备

| 文件 | 用途与边界 |
|---|---|
| [clone_application_database.py](./clone_application_database.py) | 创建不覆盖旧库的升级前副本，并核对表与行数；要求确认参数 |
| [prepare_test_database.py](./prepare_test_database.py) | 创建、迁移专用 MySQL 测试库；要求显式 `--yes` |
| [rehearse_database_upgrade.py](./rehearse_database_upgrade.py) | 在已验证升级前副本上进行迁移和回滚演练 |
| [generate_container_secrets.py](./generate_container_secrets.py) | 写入 Compose 所需本地秘密文件；拒绝覆盖已有秘密，产物不入库 |
| [v060_alpha1_migration_check.py](./v060_alpha1_migration_check.py) | 在专用临时库核对迁移回填、中断重跑和幂等性 |

### RAG 质量、迁移与评估

| 文件 | 用途与边界 |
|---|---|
| [build_rag_data_quality_notebook.py](./build_rag_data_quality_notebook.py) | 生成并执行基于聚合证据的 RAG 数据质量 Notebook |
| [build_rag_data_quality_report.py](./build_rag_data_quality_report.py) | 从聚合审计证据生成报告产物 |
| [evaluate_rag.py](./evaluate_rag.py) | 对固定查询集执行只读 RAG rollout 评估；仍需数据及检索环境 |
| [generate_rag_benchmark.py](./generate_rag_benchmark.py) | 从已有切片生成本地评测候选；输出到被忽略的数据目录，需人工复核后才能用于正式门禁 |
| [measure_tokenizer_accuracy.py](./measure_tokenizer_accuracy.py) | 对照保守 token 估算与真实 Ollama 计数，记录不支持或失败状态 |
| [migrate_versioned_rag.py](./migrate_versioned_rag.py) | 规划或执行有界的版本化 RAG 迁移；默认 dry-run，不自动启用检索 |
| [plan_rag_canonicalization.py](./plan_rag_canonicalization.py) | 读取现有数据并输出规范化计划，不修改原 RAG 数据 |
| [profile_rag_data_quality.py](./profile_rag_data_quality.py) | 生成有隐私边界的数据质量画像 |
| [rehearse_versioned_rag.py](./rehearse_versioned_rag.py) | 在已验证的可丢弃数据库副本上演练版本化 RAG |
| [validate_rag_data_quality.py](./validate_rag_data_quality.py) | 用独立聚合 SQL 复核 RAG 质量画像 |

### 性能测量

| 文件 | 用途与边界 |
|---|---|
| [measure_perf_baseline.py](./measure_perf_baseline.py) | 生成样本并测量数据库与业务路径；会写样本和报告，不是只读检查 |
| [measure_sidecar_baseline.py](./measure_sidecar_baseline.py) | 测量 sidecar/安装包大小；指定启动测量时会启动真实进程 |
| [measure_v100_baseline.py](./measure_v100_baseline.py) | 在专用测试库采集性能证据，不自行确立验收阈值 |

### 安装、运行与升级 smoke

| 文件 | 用途与边界 |
|---|---|
| [ollama_lifecycle_check.py](./ollama_lifecycle_check.py) | Ollama 外部运行环境的生命周期自查 |
| [sidecar_smoke.py](./sidecar_smoke.py) | 已构建 sidecar 的运行 smoke |
| [summary_worker_smoke.py](./summary_worker_smoke.py) | 写入专用会话样本并启动摘要 worker，验证摘要和幂等性 |
| [upgrade_smoke.py](./upgrade_smoke.py) | 升级前后数据快照、样本、比对及结果记录；不自动证明真实安装包升级通过 |
| [v050_workflow_smoke.py](./v050_workflow_smoke.py) | 历史可信工作流验收：真实模型、审批写入、命令取消及进程清理 |
| [v060_workflow_smoke.py](./v060_workflow_smoke.py) | 历史 project-bound run、断线、重启和回退验收 |

### 观察、遥测与本机 QA

| 文件 | 用途与边界 |
|---|---|
| [m0_agent_run_driver.py](./m0_agent_run_driver.py) | 调用安装版真实 Agent API 采集有效 run，可产生取消及 RAG 样本 |
| [m0_gate_runner.py](./m0_gate_runner.py) | 启停 sidecar 并采集 M0 观察证据，支持故障与审批场景 |
| [m0_gate_aggregate.py](./m0_gate_aggregate.py) | 合并多日报告、审计数据库并输出门槛判定 |
| [m0_gate_common.py](./m0_gate_common.py) | M0 有效 run 判定共享模块 |
| [rcn_collect.py](./rcn_collect.py) | 调用 soak 等检查并收集每日观察证据，缺失数据如实记录 |
| [reconcile_telemetry_windows.py](./reconcile_telemetry_windows.py) | 写入兼容遥测窗口的结束时间，修复陈旧未关闭窗口 |
| [telemetry_window_report.py](./telemetry_window_report.py) | 只读汇总兼容遥测窗口，分别评估生产与 QA 调用 |
| [read_process_env.py](./read_process_env.py) | 读取 Windows 进程环境；指定变量可能包含凭据，限已授权的本机 QA |

### 历史专项门禁与可行性实验

| 文件 | 用途与边界 |
|---|---|
| [run_ct8_spike.py](./run_ct8_spike.py) | 检查 CT-8 App Server 实验前提并记录 READY/DEFER，不代表已实施生产集成 |
| [run_n1c.py](./run_n1c.py) | 执行 CT-6 套件并归档网络拒绝与对照组证据；环境阻断单独记录 |
| [run_soak_gate.py](./run_soak_gate.py) | 真实 MySQL 持久层混合负载、重放和故障注入，会写入数据及证据 |
| [spikes/s1_sandbox_windows_spike.py](./spikes/s1_sandbox_windows_spike.py) | Windows 低完整性、Job Object 与写入边界实验，包含子进程和网络探针 |
| [spikes/s1_transport_stdio_spike.py](./spikes/s1_transport_stdio_spike.py) | stdio/JSONL 协议传输与生命周期实验 |
| [spikes/s4_network_appcontainer_spike.py](./spikes/s4_network_appcontainer_spike.py) | AppContainer 网络、目录和进程树隔离实验，仅 Windows |

## 路径与证据维护

部分脚本使用自身所在目录推导项目根目录，另有包装脚本、工作流及历史文档直接引用 `scripts/...`。重排目录前必须逐项迁移调用者和相对路径；本次只增加索引与已授权的发布验证入口。

真实执行报告应同时记录命令、源码提交、运行环境、结果和跳过项。旧版本脚本、迁移检查、视觉快照及实验结论均保留历史口径；“源码已检查”“测试已执行”“安装包已构建”和“服务器已部署”分别报告。
