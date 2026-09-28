# S0 开发交接与验收报告

日期：2026-09-08。基线：`F:\Program\Agent`，`dev/1.0.0`，HEAD `8dcfa7f`。**S0 基线、隔离入口、契约、任务集和早期宿主风险探针已交付，可开始 S1；已知产品缺口没有在 S0 修复。**未执行付费模型、真实账号、安装包验收、提交、推送或发布。

机器事实见 [s0-evidence.json](s0-evidence.json)，调用链及矩阵见 [执行基线](s0-execution-baseline.md)，新旧协议边界见 [契约决议](s0-contract-decisions.md)。

## 1. 工作项结论（S0-07）

| 工作项 | 状态 | 交付与未完成边界 |
| --- | --- | --- |
| S0-01 主链追踪 | 完成 | 文件/符号清单覆盖创建、工具、模型、本机 SQLite、审批、取消及 UI 投影 |
| S0-02 能力矩阵 | 完成 | 区分代码、接入、默认策略、实测和安装；安装列统一未执行 |
| S0-03 隔离入口 | 完成 | 最终固定套件两次新目录结果一致，均无业务配置导入；默认工具沙箱的命名管道限制仍需获准执行环境 |
| S0-04 契约冻结 | 完成 | 六类共享 Pydantic 契约，生成 JSON Schema/TS，扩展既有检查入口；业务接入仍属于 S1–S5 |
| S0-05 任务基线 | 完成基础集 | 3 类合成项目、30 任务、24 开发/6 留出；全部起始实现失败、参考实现通过、用户文件保护通过；模型评测未执行 |
| S0-06 风险探针 | 完成当前宿主基线 | 实测文件范围、回环网络、stdin、PTY、低完整性启动、取消/超时/后代回收；PTY 不可用；OS 隔离未达标 |
| S0-07 开发决议 | 完成 | 继续演进共享 Python 核心；不引入第二执行循环；App Server 可选验证未纳入 |

S0 的完成指“基线可复现且缺口有证据”，不代表总体路线 M0 已达成；M0 还需要 S1。

## 2. 最终验证结果

使用已有环境：Python 3.12.13、Node v24.14.0、cargo 1.96.1。未安装/升级依赖，未更改锁文件。所有 pytest 运行均由启动器自动设置隔离 cwd、源码路径、临时目录与白名单环境。

| 实际命令 | 实际结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all`，连续两次 | 每次 **118 passed、1 skipped、4 xfailed**，无普通失败；两次耗时 21.90/25.30 秒 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite duration` | **1 passed**；真实命令 120.203 秒终止，进程已退出，早期输出未可见 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite contracts` | 最终将目录边界检查移到 mkdir 前后复核入口，**14 passed**；默认沙箱即可运行无管道子测试 |
| `.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check` | `protocol codegen in sync: OK` |
| `.venv/Scripts/python.exe -B scripts/check_agent_v2_imports.py` | `agent_v2 dependency rules: OK` |
| `cargo build --release --locked --offline --manifest-path apps/exec-host/Cargo.toml` | 成功；真实探针使用该构建产物，SHA-256 已记录 |
| `cargo test --locked --offline --manifest-path apps/exec-host/Cargo.toml` | 命令成功，但当前 crate **0 个 Rust 单测**；真实宿主覆盖来自 Python 集成测试 |
| `npm run test -- src/services/localExecutor.spec.ts src/services/privateTransport.spec.ts src/features/coding/composables/useRunStream.spec.ts src/features/coding/composables/useRunStreamBlocker.spec.ts src/features/coding/model/runProjection.spec.ts`（桌面目录） | 4 文件/19 项通过；末尾 filter 使用了不存在的 `runProjection.spec.ts`，未误算覆盖 |
| `npm run test -- src/features/coding/model/runProjector.spec.ts`（桌面目录） | 补用实际文件名，1 文件/13 项通过 |
| `npm run test -- src/features/coding/components/RunS0Baseline.spec.ts`（桌面目录） | 1 文件/2 项通过；收紧退出码断言后再次运行 |
| `npm run build`（桌面目录） | TypeScript 与 Vite 成功；保留既有大于 500 kB 分块告警 |
| `git diff --check` | 通过；CRLF 提示不属于空白错误 |

最终定向 Ruff 命令：

```powershell
.venv/Scripts/python.exe -B -m ruff check scripts/run_coding_validation.py scripts/coding_validation_plugin.py scripts/coding_validation_process.py scripts/coding_contract_codegen.py scripts/coding_task_baseline.py scripts/protocol_codegen.py src/private_agent_core/coding_contracts.py tests/coding_acceptance tests/unit/test_local_model_contract.py
```

结果：`All checks passed!`。另用 `python -I` 按文件路径加载 `protocol_codegen.py` 并调用 `generate()`，得到 6 个生成物，验证不依赖 scripts 恰好存在于 PYTHONPATH；原 `tests/test_agent_v2_skeleton.py` 已加入最终套件。

最终另运行内联 Python 检查当前 34 个修改/未跟踪文本文件的 UTF-8 无 BOM、JSON 解析、Markdown 相对链接及尾随空白，全部通过；其中包含 7 个开工前已有文档，非本轮修改数。核对 `git diff -- docs/project-state.md` 为空。

最终重复运行目录：

- `.run/coding-agent-validation/all-0fd9f3c5efb847f88eb0347142863dd0`
- `.run/coding-agent-validation/all-1f69bad2f8504cc188b88f1429a12df9`
- 慢探针：`.run/coding-agent-validation/duration-47f55bfac4f74a83ae15f06a3e691eda`

目录中保留实际 invocation、pytest 结果和逐场景事实，汇总复制到版本化证据文件；测试目录不纳入 Git。

## 3. 八个基线场景与宿主探针

| 场景 | 已观察事实 | 对后续工作的影响 |
| --- | --- | --- |
| T01 零工具假完成 | 磁盘未改，tool_call_count=0，run completed，无 goal_outcome | G01 严格 xfail，交 S1。UI 已有“不含执行证据”提示，不能声称 UI 完全没有提示 |
| T02 测试退出码 1 | 工具执行 completed，输出 returncode=1，run completed | G02 严格 xfail，交 S1。UI 命令卡显示红色“退出码 1”，状态文字直接为 completed |
| T03 大文件尾部 | 只返回前 32000 字符，truncated=true，尾部标记不在输出 | S3 行范围/定位与续读 |
| T04 长模型任务 | 实际 24 次请求后 limit_exceeded/context_limit；147 事件 | S2 上下文预算与历史；无真实模型费用 |
| T05 长命令 | 桌面传入 120 秒；真实 130 秒等待脚本在 120.203 秒被停止，命令失败且无残留 | S4 持续命令与输出；循环最终仍能 completed，不等于命令通过 |
| T06 待审批取消/重启 | 迟到批准 422，未写入；Store 重启将运行失败、执行 unknown、审批取消 | S5 安全恢复；不重放副作用 |
| T07 用户已有改动 | 预览后新增用户修改未被覆盖；真实临时 Git dirty 分支切换被拒绝 | 当前保护窗口为 preview-to-write，不能推导出 read-to-write 保护 |
| T08 能力不一致 | 当前 health=1/stdio=2；前端旧连接信息校验与不回退测试通过 | 新 CapabilitySnapshot 尚未接线，不能宣称新版能力握手已完成 |
| HOST-FILE | 当前普通宿主允许项目内文件和测试兄弟目录文件写入 | 严格 xfail；工具层范围不等于 OS 范围 |
| HOST-NETWORK | approved 正对照连通，非 AC 的 none 同样连通本机随机回环端口 | 严格 xfail；不推广为外网探测结果 |
| HOST-STDIN | 错误 nonce 拒绝，正确 nonce 的中文输入成功 | 底层能力可复用，桌面工具尚未提供 stdin |
| HOST-PTY | argv 正对照成功，PTY 返回 pty_environment_unavailable | skipped，明确能力未通过；不能以进程未启动证明隔离有效 |
| HOST-LOW | inherit 与 low 的真实 Python 启动均成功 | 仅证明启动，未证明受限工作区/网络边界 |

四个 xfail 均为 `strict=True`，保留期望的目标行为并限制为断言失败；正对照启动异常不转为预期产品失败。未来修复导致 XPASS 时，门禁会要求重新核对并转为正式回归。

## 4. 失败过程与归因

- 第一次隔离收集被守卫阻止：`test_local_model_contract.py` 经旧服务端包触发业务配置。已确认旧类型是共享核心兼容别名，仅将该本机测试改为直接导入真实共享模型、网关和适配器。
- 默认工具沙箱中出现 `3 failed、51 passed`，三项均在 asyncio 命名管道创建处报 `WinError 5`。临时目录已经可以读写；经工具审批在允许命名管道的环境运行相同入口后通过。没有修改 Windows 管道实现或跳过这三项。
- 首轮前端在 esbuild 启动处 `spawn EPERM`；获准运行后测试与构建成功。
- 新任务判定器初版在 Windows 子解释器的默认编码上出现 2 个失败及读取线程告警。使用 `-X utf8` 和二进制读取后消除，最终无此告警；没有放宽任务输出预期。
- 新增测试初版有 4 处 Ruff 问题，已定向修正；后续协议回归检查发现按路径导入时不应依赖 scripts 在 sys.path，生成器已改为显式路径加载。

## 5. 开发决议与接口所有权

继续使用 Tauri/Vue、本机 Python 应用服务、共享核心、SQLite 和 Rust 宿主。运行和审批由本机应用层唯一拥有，Rust 只负责执行事实，UI 只发送意图和投影持久化事实。

S1 开工项：接入完成验证器、建立 RunOutcome、区分测试失败与协议错误、联动快照/终态/UI，并把 T01/T02 转为通过的正式回归。S2–S5 沿用冻结契约，不各自定义同名字段。此次同一开发者顺序完成，没有假定额外团队已执行工作。

原 54–82 人日是提案估计。S0 的自动化用时不等于后续人日，不据此压缩估算；S4 的 PTY/隔离兼容仍是排期风险。没有充分证据重估 S1–S6，维持原区间，待各阶段首次集成后再校准。

## 6. 实际变更文件

| 文件 | 变更 |
| --- | --- |
| `scripts/run_coding_validation.py` | 新增固定套件启动器、隔离环境、全新目录与执行记录 |
| `scripts/coding_validation_plugin.py` | 新增业务配置导入守卫、ACL 安全临时目录及结果记录 |
| `scripts/coding_validation_process.py` | 新增测试进程树生命周期管理 |
| `scripts/coding_task_baseline.py` | 新增任务重建及独立产物判定 |
| `scripts/coding_contract_codegen.py` | 新增共享契约到 Schema/TS 生成 |
| `scripts/protocol_codegen.py` | 扩展现有生成与检查入口，保留旧生成物内容 |
| `src/private_agent_core/coding_contracts.py` | 新增六类跨阶段契约与语义约束 |
| `src/private_agent_core/coding_contracts.schema.json` | 新增生成 Schema |
| `apps/desktop/src/features/coding/model/generated/codingContracts.ts` | 新增生成类型 |
| `apps/desktop/src/features/coding/components/RunS0Baseline.spec.ts` | 新增真实组件的 S0 显示基线 |
| `tests/unit/test_local_model_contract.py` | 改为直接导入真实共享核心，避免间接业务配置 |
| `tests/coding_acceptance/test_contracts.py` | 新增生成一致性与契约语义测试 |
| `tests/coding_acceptance/test_baseline.py` | 新增 T01–T08 桌面基线 |
| `tests/coding_acceptance/test_host_probes.py` | 新增真实宿主正反探针 |
| `tests/coding_acceptance/test_host_duration.py` | 新增独立 120 秒真实超时探针 |
| `tests/coding_acceptance/test_tooling.py` | 新增任务正反对照、隔离和资源回收测试 |
| `tests/coding_acceptance/tasks.json` | 新增固定 30 任务、起始实现、判定与预算 |
| `tests/coding_acceptance/contract_examples.json` | 新增六个最小契约实例 |
| `tests/coding_acceptance/README.md` | 新增复跑与判定说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s0-execution-baseline.md` | 新增调用链和能力矩阵 |
| `docs/analysis/coding-agent-upgrade-20260908/s0-contract-decisions.md` | 新增契约所有权和兼容决议 |
| `docs/analysis/coding-agent-upgrade-20260908/s0-validation-report.md` | 本报告 |
| `docs/analysis/coding-agent-upgrade-20260908/s0-evidence.json` | 新增脱敏机器证据汇总 |
| `docs/analysis/coding-agent-upgrade-20260908/README.md` | 更新 S0 状态与交付入口 |
| `docs/analysis/coding-agent-upgrade-20260908/s0-baseline-and-contracts.md` | 更新工作项交付状态和实际文件入口 |
| `docs/testing-guide.md` | 增加本机 Coding 隔离测试入口 |
| `docs/archive/legacy/unified-desktop-runtime.md` | 增加当前 S0 源码基线入口，保留历史记录 |

`docs/README.md` 和 S1–S6 计划是开工前已有内容，不计入本轮改动。没有修改产品运行行为、schema 版本、权限默认值或依赖。

## 7. 项目记忆、限制与后续操作

已读 `AGENTS.md`、完整 `docs/project-state.md`、统一客户端说明及测试指南。旧记忆的工作区 E 盘、HEAD `0c170557`、依赖与部分能力是历史快照；本轮以当前 Git、共享核心调用路径、Node/Rust 实际工具和隔离测试核对，差异记入本专项基线。按仓库“仅明确要求时更新共享记忆”的约定，没有改写 `docs/project-state.md`，没有建立新的共享记忆系统。

持续知识已同步到 S0 契约、调用链、测试说明及本报告；旧版本历史原样保留。新契约尚未接入真实业务，PTY/OS 隔离仍受限，AppContainer 全边界验证延至 S4：旧 spike 会向解释器目录追加 ACL，不能作为本轮临时目录探针直接执行。

30 个合成任务是可复现起始集，规模不足以直接支持复杂仓库独立完成率；留出答案在开发仓库可读，正式 S6 应隔离评测环境。真实模型、安装/升级、跨平台、生产账号与生产服务均未验收。

无需用户补做 S0 代码步骤。复跑使用测试 README 的明确命令；受限沙箱若禁止命名管道，应在获准开发终端运行相同入口。继续 S1、付费评测或发布需要对应的新任务范围，不由本报告自动执行。
