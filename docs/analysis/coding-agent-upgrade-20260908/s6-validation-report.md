# S6 开发与校准报告

日期：2026-09-09（Asia/Shanghai）。仓库 `F:\Program\Agent`，分支 `dev/1.0.0`，接手及交付基线 HEAD `25ba4d3`；接手工作区干净、暂存区为空，本地跟踪引用显示 ahead 6，本轮未 fetch。当前记录是源码开发和隔离校准报告，**M3 未放行**。

## 任务总结

按 [S6 阶段目标](./s6-evaluation-and-delivery.md)实现独立评测工具、公开任务校准、Provider 回环验证、交付回归和文档同步。复用 S0 隔离启动器及 S1–S5 的正式账号绑定、项目/会话、完成验证、审批、补丁、持续执行和恢复 API；未修改生产运行时、前端、Rust 宿主、数据库 schema 或依赖。

开发产物包括：

1. Python、Vue/TypeScript、Rust 各 10 题，按原计划分类分布划分为 18 道开发题及 12 道保留组题。冻结提示、初始树、允许修改文件、许可、标准验证命令及外置判定。S0 原清单保留，S6 另行版本化。
2. `preflight/control/matrix/quality` 入口。正式 stdio 子进程在独立目录中运行，文件修改和验证命令经过原有授权与验证器；支持暂停接续、失败后修复、拒绝写入、长文件补丁及 dirty 用户工作保护。
3. 每次尝试保存清单、事件、运行/执行/审查快照、文件摘要与 diff；始终保留失败和未启动项。证据缺失、摘要变化、身份变化、预算不足及关闭失败不能变成成功。人工审阅以摘要绑定并追加记录，不改写原始尝试。
4. 按模型、语言、分类及开发/保留组分别统计。真实质量预定义 90 次尝试，27 个编码目标 × 3 次组成 81 次编码分母，3 个拒绝场景 × 3 次仅统计系统边界。控制替身的编码质量分母为 0，成本或用量未知不写为零。
5. 真实进程断流不重放、重开后旧审批失效及关联恢复、合成 schema 3–6 升级与备份、报告事实审阅、资源与取消边界回归。打包校验新增可选 `--s6`，沿用原校验后追加正式 IPC 正反对照。

当前 30 题为原创 CC0-1.0 **公开校准集**，参考实现与断言已暴露，不是独立盲评集；项目规模以校准工具机制为主，不能外推真实复杂工程完成率。`quality` 只接受明确声明不计费的字面回环模型配置，本轮未执行，具体模型版本、真实质量和真实费用均没有结论。完整参数、预算与可信项目执行边界见 [评测协议](./s6-acceptance-protocol.md)。

## 变更文件

以下为本轮全部 22 个变更文件；没有用户原有未提交修改需要合并或覆盖。

| 文件 | 变更 |
| --- | --- |
| [run_coding_acceptance.py](../../../scripts/run_coding_acceptance.py) | 新增隔离运行器、正式 API 编排、预算与逐次证据。 |
| [coding_acceptance_catalog.py](../../../scripts/coding_acceptance_catalog.py) | 新增冻结任务校验、重建、环境预检、源码保护与三类语言外置判定。 |
| [coding_acceptance_transport.py](../../../scripts/coding_acceptance_transport.py) | 新增回环账号/模型服务及有界正式 IPC 客户端。 |
| [coding_acceptance_evidence.py](../../../scripts/coding_acceptance_evidence.py) | 新增脱敏证据、分组统计、失败完整性与保守门禁决议。 |
| [coding_acceptance_review.py](../../../scripts/coding_acceptance_review.py) | 新增基于摘要的追加人工审阅入口。 |
| [run_coding_validation.py](../../../scripts/run_coding_validation.py) | 增加 acceptance 套件并纳入 all。 |
| [verify-unified-client.py](../../../scripts/verify-unified-client.py) | 增加可选 S6 检查、UTF-8 输出及失败退出码。 |
| [s6_fixtures.py](../../../tests/coding_acceptance/s6_fixtures.py) | 新增 30 题公开校准定义及固定分类/分母。 |
| [test_s6_acceptance.py](../../../tests/coding_acceptance/test_s6_acceptance.py) | 新增判定器、证据、模型配置与正式 IPC 假完成负例。 |
| [test_s6_delivery.py](../../../tests/coding_acceptance/test_s6_delivery.py) | 新增交付、迁移、审阅、资源采样和取消回归。 |
| [验收入口说明](../../../tests/coding_acceptance/README.md) | 同步 S6 入口并区分历史成绩。 |
| [S6 评测协议](./s6-acceptance-protocol.md) | 新增任务、预算、命令、隔离和审阅协议。 |
| [本报告](./s6-validation-report.md) | 新增实测证据、失败归因、交付限制与后续验收责任。 |
| [总体路线](./README.md) | 更新 S6 开发状态，保留 S5 历史证据日期及环境边界。 |
| [S6 阶段说明](./s6-evaluation-and-delivery.md) | 增加实际开发入口，保留原始验收目标及未放行结论。 |
| [使用指南](../../usage-guide.md) | 补充项目、规则、审批、终端、恢复与审查使用方式。 |
| [测试指南](../../testing-guide.md) | 同步隔离启动、精确参数、证据位置及测试层次。 |
| [API 参考](../../api-reference.md) | 同步已实现的完成、执行、控制与代理流契约。 |
| [安全模型](../../security-model.md) | 区分 OS 限制、可信项目、公开校准与真实账号边界。 |
| [故障排查](../../troubleshooting.md) | 补充宿主、命令验证、暂停、Rust 和评测错误定位。 |
| [发布检查清单](../../release-checklist.md) | 补充当前 Coding S6 的产物身份与阻断门禁。 |
| [数据库升级手册](../../database-upgrade-runbook.md) | 区分本机 SQLite 与旧业务数据库，说明迁移及回退限制。 |

## 验证结果

命令均在仓库根执行。使用现有 Python 3.12.13 开发环境与已有 Node/Vue/Rust/MSVC；测试目录为新建 `.run` 子目录，没有读取业务 `.env`、真实账号数据库或模型凭据。Windows 正式执行宿主需要测试进程权限，相关集成命令经运行环境授权后执行，未关闭产品能力门禁。

| 实际命令 | 本轮结果及证据 |
| --- | --- |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all` | **414 passed、1 skipped**，414.20 秒，退出 0；`all-3cd3b22ba470447c9ea317b02d01438a`。唯一跳过是 Windows 无真实符号链接创建权限；不是通过。此轮收集了当时 65 项 S6 测试，随后评测器边界修改由下行最终专项覆盖，产品代码未变。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite acceptance` | **74 passed**，41.73 秒，退出 0；最终 `acceptance-9f15f69443ac4b7bb9eaad016b2e8e53`，包括最后的取消及缓存 junction 正反对照。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode control` | **30/30 系统行为通过**，退出 0；最终 `control-0c4aaf07480f4ea7b6d52a40b57bd498`，无真实模型调用。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode matrix --tasks PY01,PY09,PY10,VT07,RS01` | **15/15 通过**，退出 0；最终 `matrix-93d66d8a40d5479bb08da46125f91193`，service/OpenAI/Ollama 各 5 次，均为回环替身。 |
| `.venv/Scripts/python.exe -B scripts/verify-unified-client.py --bundle .run/unified-client-gHXwHg --work-dir .run/s6-packaged-validation --model-mode openai --s6` | 最终 `passed=true`、`s6_exit_code=0`、退出 0、`real_model_called=false`。候选副本 `packaged-runtime-_pb0lo1n`；S6 证据 `control-6b9888052983419e963ce92cfd9ccefb`。原校验的账号替身绑定/退出、文件写入、审批、PowerShell、full_access、宿主篡改拒绝和 4 条历史导出均通过；S6 正反对照 2/2。这是候选 IPC 检查，不是完整桌面安装。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode preflight --bundle .run/unified-client-gHXwHg` | 退出 0，开发依赖与候选清单检查通过；`preflight-b018ad82638748b3a7181e6000391e84`。636 文件来源清单与当前产品相关文件一致，`source_matches=true`，`installed_desktop_verified=false`。 |
| `.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check` | `protocol codegen in sync: OK`。 |
| `.venv/Scripts/python.exe -B scripts/check_agent_v2_imports.py` | 依赖边界检查通过。 |
| `git diff --check` | 通过，无空白错误；交付前另核对新增文档引用、Git 状态及全部变更文件。 |

针对所有新增和改动的 Python 文件执行以下准确命令，结果为 `All checks passed!`：

```powershell
.venv/Scripts/python.exe -B -m ruff check scripts/coding_acceptance_catalog.py scripts/coding_acceptance_evidence.py scripts/coding_acceptance_transport.py scripts/coding_acceptance_review.py scripts/run_coding_acceptance.py scripts/run_coding_validation.py scripts/verify-unified-client.py tests/coding_acceptance/s6_fixtures.py tests/coding_acceptance/test_s6_acceptance.py tests/coding_acceptance/test_s6_delivery.py
```

`all` 与 `acceptance` 有重复测试，不能相加为独立覆盖数。`control` 与 `matrix` 的通过数是系统机制对照，没有真实模型编码质量分母。本轮没有改动前端、Rust 产品代码或打包脚本，因此没有重新运行前端构建、Rust 全量测试或重新制作安装包。

交付前另外使用标准输入形式的只读 Python 检查（`.venv/Scripts/python.exe -B -`）：新增/改动文本中的 **52 个本地 Markdown 引用全部存在**；最终 30+15 次尝试的事件/产物/diff 摘要及评测器源码摘要一致；报告中的 5 个候选文件摘要与磁盘一致；10 个新增文件通过 UTF-8、末尾换行和空白检查。`git status --short --branch`、`git diff --numstat`、`git diff --staged --stat` 核对 22 个预期文件、空暂存区，无生产源码、依赖或锁文件改动。

### 候选身份

实际执行的是从现有 `.run/unified-client-gHXwHg` 复制到隔离目录的新进程。没有声称检查原桌面服务内存或安装中的进程。候选记录：

| 文件 | SHA-256 |
| --- | --- |
| `private-agent-local.exe` | `513d062f270ce4139f330b9c291cbb5efd896e2627d98bb0cb903f2eede4c91c` |
| `exec-host.exe` | `e508c9e6965126b66f1652051c7468642498b825f32daeabf91779a9eb5cc57b` |
| `exec-host.sha256` 文件 | `57f6aa2d78d0267b710b3d5f90a21f7803d51a65595fabd3ed7b4049b7d9b895` |
| `build-info.json` | `d0a5f434bd54ebd518c4d1c02d91eb8b9c7cefb86ed936e384841e32b0c68b2a` |
| `source-manifest.json` | `be28d894e79225efbb11198c1d8df8b9991c20179b635d4bd4d517b579491248` |

### 开发期间的失败及修正

失败现场保留在忽略目录，未改写失败记录或删减分母。主要归因为本轮新增评测工具，而非已交付产品变更：

- 最初正式 IPC 专项 49 passed、4 failed：隔离 AppData 层级及 Windows 宿主权限导致能力预检失败。按 OS 用户目录结构修正后，53 项通过；增加交付覆盖后 60 项通过。权限问题使用受准许的宿主测试进程解决，未移除能力检查。
- 回环 Provider 配置与实际 profile 不一致、普通脚本未登记为验证命令、命令首段输出后尚未退出、Rust 隔离工具链/链接器与首次 Cargo.lock 写入使工作区版本改变：分别修正替身 profile、使用已有 pytest/npm/cargo 验证命令、正式执行续读、项目局部 MSVC/SDK 配置及开始前生成离线锁文件。没有安装依赖或修改全局配置。
- 暂停待审批写入会按产品规则使旧操作失效。正向“暂停继续”场景调整到首次模型等待期间，旧审批失效仍由独立负例覆盖，没有复用过期授权。
- 扩展矩阵 `matrix-a63d97aff64d4ea19dad6c0f5f6bc079` 为 13/15，两个 Rust 尝试失败。资源采样多次文件查询遇到编译器删除的中间产物，改用单次元数据并仅容忍 ENOENT；权限错误仍失败。后续完整对照 `control-99653ca6adba473192db032eba3dfaf2` 仍有 5 个 Rust 失败，证明第一次修正不足。
- 定位轮 `control-54a2f2665c834d6e8b77e4e9b88da15f` 记录到真正的 Windows 缓存 junction：隔离 `home/.../INetCache/Content.IE5` 指向同目录 `IE`。修正只跳过该精确别名的重复计量，其他位置、目标及链接继续拒绝；增加消失文件/目录、权限错误、工作区链接与越界缓存正反对照。
- 新增 token 超限测试经真实 IPC 先复现空对象取消的 422，再复现乐观状态版本取消的 409；最终采用既有无请求体单向取消入口。保留原失败现场 `s6-delivery-dee561aacece4458bc10bc115896e3bf` 和 `s6-delivery-ade88497c50644acb7ac4b2cd34a0cb5`。隔离交付复现命令见下文，失败分别为 1 failed、14 passed，没有将失败记为完成。

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_acceptance.py --mode control --tasks RS02,RS06,RS07,RS08,RS09 --repetitions 3
.venv/Scripts/python.exe -B -c "import sys; sys.path.insert(0, 'scripts'); import run_coding_validation as v; v.SUITES['s6-delivery'] = ['tests/coding_acceptance/test_s6_delivery.py']; sys.exit(v.run('s6-delivery'))"
.venv/Scripts/python.exe -B -c "import sys; sys.stdout.reconfigure(encoding='utf-8'); sys.path.insert(0, 'scripts'); import run_coding_validation as v; v.SUITES['s6-delivery'] = ['tests/coding_acceptance/test_s6_delivery.py']; sys.exit(v.run('s6-delivery'))"
```

### 门禁与继续验收决议

| 门禁 | 本轮范围与未完成部分 |
| --- | --- |
| T01 完成真实性 | 三种回环协议及旧代理的假完成负例、真实完成验证已有自动覆盖；任意自然语言最终说明仍须独立审阅。 |
| T02 写入保护 | 初始用户文件、未计划文件、外置判定期间自改、补丁及既有并发保护回归；真实模型和 UI 协作仍须对照。 |
| T03 副作用恢复 | 断流不重发、重开旧审批失效、显式关联继续及既有故障回归；完整真实模型故障矩阵待验收。 |
| T04 事件一致性 | 正式事件分页、连续序号及唯一终态，缺失与重复负例；实际桌面断线显示范围待验收。 |
| T05 取消与清理 | 运行器关闭/超限回归和既有宿主测试；完整平台进程树 5 秒门禁未在本轮单独测量。 |
| T06 终端能力 | 运行器实际执行、续读及既有执行套件；本轮未重跑独立 600 秒专项。 |
| T07 交互延迟 | 本轮未测真实 UI p95，不沿用 S5 的 386.70 ms 作为新成绩。 |
| T08 权限边界 | 固定审批策略、拒绝对照、受限宿主既有回归；真实符号链接测试跳过及跨环境范围保留限制。 |
| T09 编码质量 | 未运行真实模型，公开任务不满足盲评要求，未达到可判断默认模型 ≥80% 的条件。 |
| T10 协议兼容 | service/OpenAI/Ollama 回环及旧 complete 协商、现有候选 IPC；远程供应商及完整新旧 UI/安装组合未验收。 |
| T11 安装升级 | 合成 schema 3–6 迁移、旧内容和备份摘要测试；干净 OS、旧安装程序升级及程序回退未验收。 |
| T12 文档一致性 | 本轮更新 7 份使用/运维文档并核对源码与入口；独立人员复现及正式签署未完成。 |

运行器将这些门禁保留为 `not_run` 并附局部证据，交付决议为 `blocked`。退出 0 仅表示选定工具校准通过，不代表全部 S6 门禁满足。真实服务身份、远程费用和模型版本不由回环替身证明。

## 项目记忆

接手完整读取 `docs/project-state.md` 和根 `AGENTS.md`，结合本目录 S0 基线/契约、S0–S5 阶段入口、S5 收尾验收报告及当前相关源码核对。项目记忆为 2026-08-31 的 `E:\Program\Agent`、HEAD `0c17055` 快照；本轮实际为 `F:\Program\Agent`、HEAD `25ba4d3`。通过 `git status --short --branch`、`git log -5 --oneline`、当前 API/存储/运行时及候选 source-manifest 核验，确认时间和版本不同，没有把旧记忆当成实时状态。

根入口明确规定只有用户要求维护项目记忆时才改写 `docs/project-state.md`，本轮没有该要求，因此保留原历史记忆，不更新其日期、不创造新的记忆系统。已在总体路线、S6 阶段说明、本协议/报告和 7 份操作文档同步本轮可复用信息：评测入口、分类/分母、可信执行边界、审阅与 M3 阻断状态。历史 S5 成绩仍注明其原环境和日期；现阶段文档中的“S6 未开发”已更新，历史报告保持原始事实。

## 风险、限制与假设

- 完整 S6 验收尚未完成。未指定并运行真实候选模型，未准备独立未污染保留题；不能交付真实编码成功率或默认模型推荐。
- 仅接受不计费本机模型的质量入口是当前实现边界。用量要等响应返回才可见，token 预算不是账单硬上限；付费远程模型需要另行确定供应商、预算和实际授权流程。
- 固定命令使用显式可信项目执行，外置断言、目录采样及内容脱敏不是恶意代码的 OS 沙箱；当前校准集不允许导入生产项目、敏感内容或未经审查的脚本。
- 未测模型/工具/审批等待的独立时间分解和峰值进程数；目前保留原始事件、执行事实、总耗时及采样存储峰值，未知指标不能填零。采样不是磁盘硬配额。
- 支持 Windows 版本/架构、标准用户、干净安装、实际 Tauri 窗口、旧程序回退与真实账号均没有本轮完整验证。没有发布、部署、提交或推送。
- `.run` 为本机忽略目录，其他机器需按协议重新运行；不要复制整个目录中的运行环境或私人资料作为交付。

## 用户需执行的操作

开发工具交付无需手工修复环境。若继续正式验收，按以下顺序补齐依赖；未自行创建新任务、排期或指定人员：

1. 模型验收角色确定默认候选模型、可核对的模型版本及预算。使用已安装且确认不计费的本机服务时，按评测协议准备不含密钥的模型配置；不能从私人配置提取凭据。
2. 独立评测角色准备未参与开发/调试的保留题，冻结来源、许可、初始版本、断言与人工审阅规则。公开校准可先复跑，但不升级为盲评成绩。
3. 桌面/发布验收角色在声明支持的 Windows 隔离环境完成实际 UI、干净安装、旧数据升级及旧程序回退，并保存产物摘要和进程身份。
4. 测试角色复核全部 T01–T12、质量分母和人工介入；通过后才能形成新的 M3 决议。生产发布仍须独立明确任务。
