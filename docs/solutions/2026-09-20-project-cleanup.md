# 2026-09-20 项目测试与文档清理

## 范围和依据

对任务开始时 Git 跟踪及未忽略的 792 个现存文件建立清单和 SHA-256 基线，核对源码目录、构建入口、Python 导入、测试收集、前端路由、Markdown 链接及文件间引用。工作区原有大量未提交改动，本记录只统计本次快照之后的变化。

当前边界由 [README](../../README.md)、[本机化说明](2026-09-20-local-only-context.md)、`App.vue` 的 `CODING_ALLOWED_VIEWS` 和本机模型路由确认。未读取个人环境配置、密钥、用户数据库或生产日志；忽略目录只核对整理目标，保留本机材料和用户数据。

## 整理结果

- 将 37 份旧说明和研究资料移入 `docs/archive/legacy/`，另保存整理前的测试指南；文档根目录的 Markdown 从 40 份收敛为 8 份。
- 移动 7 个 Python 测试文件：4 个共享运行时/模型测试归入 `tests/unit/`，3 个打包测试归入 `tests/packaging/`。更新运行器和仓库根定位，保留所有 Python 测试节点与断言。
- 删除 11 个旧 E2E 文件、5 张对应的旧页面快照、3 个实验脚本、独立 Rust 实验的 3 个文件，以及 1 份过期生成清单，共 23 个清单内文件。
- 混合视觉文件仅移除 5 项旧页面测试，6 项 Coding 测试及其截图不变。E2E 收集清单从 25 个文件/136 项变为 14 个文件/65 项，减少的 71 项均对应明确退役目标；没有按测试是否失败来决定删除。
- 清理空的 `alembic/`、`deploy/`、`tests/fixtures/`、`scripts/spikes/` 和退役 `apps/spawn-test/`；最后一处同时移除 15 个可重建编译产物，其余目录为空。
- 已移除源码的历史 Markdown 链接改为明确标注的历史路径；保留原始验收结论和失败记录。

`viewRegistry.ts` 等保留模块仍有旧命名，部分当前 Coding 测试仍沿用历史 fixture。它们不能仅凭名字或旧 mock 字段判定为无用，本次保留。第三方依赖、业务源码、安装包、用户数据和当前视觉基线不在删除范围；更新检查器和清单生成器仅同步提示文案中的文档路径。

## 实际验证

| 命令 | 结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B -X utf8 .tmp/project-cleanup-20260920-375a/collect_tests.py before` | 1,359 项收集成功；套件无缺失/遗漏文件 |
| `.venv/Scripts/python.exe -B -X utf8 .tmp/project-cleanup-20260920-375a/collect_tests.py after` | 仍为 1,359 项；按移动映射逐项比较一致 |
| `.venv/Scripts/python.exe -B -X utf8 .tmp/project-cleanup-20260920-375a/run_moved_tests.py` | 7 个移动文件，73 passed；调用原隔离运行器 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite tooling` | 34 passed、1 failed；失败在整理前快照中复现，详见下文 |
| `.venv/Scripts/python.exe -m ruff check scripts/run_coding_validation.py scripts/sign_installer.py tests/packaging tests/unit/test_agent_runtime.py tests/unit/test_model_gateway.py tests/unit/test_model_metadata.py tests/unit/test_model_probe.py` | 通过 |
| `node node_modules/@playwright/test/cli.js test --list --reporter=json`（`apps/desktop`） | 整理前后均成功；保留测试标题逐项匹配，没有意外丢失或新增 |
| `node node_modules/@playwright/test/cli.js test e2e/local-access.spec.ts e2e/documentation-mcp.spec.ts e2e/memories.spec.ts e2e/planning-mode.spec.ts e2e/project-management.spec.ts --reporter=line`（`apps/desktop`） | 5 passed；本机接入、MCP、记忆、规划与项目管理 |
| `npm run build`（`apps/desktop`） | Vue 类型检查和 Vite 构建通过；保留现有大于 500 kB 的分包警告 |
| `node node_modules/vitest/vitest.mjs run src/components/UpdateChecker.spec.ts`（`apps/desktop`） | 随后的提示路径同步后定向复验，7 passed |
| `.venv/Scripts/python.exe -m ruff check scripts/generate-latest-json.py` | 随后的错误提示路径同步后检查通过 |
| `.venv/Scripts/python.exe -B -X utf8 .tmp/project-cleanup-20260920-375a/verify_cleanup.py` | 测试节点映射一致；本地 Markdown 链接目标无缺失；未发现范围外文件变化 |
| `git diff --check -- <本次变更路径清单>` | 通过；按本次快照归属检查，未将其他会话的差异计作本次改动 |

额外 AST 对比确认七个移动测试文件的函数内容一致（仅归一化必要的仓库根定位）；保留的 Coding 视觉测试和夹具与整理前文本一致。核对最终 Git 状态后，任务开始前已删除的文件仍保持删除，原有业务源码和依赖改动均保留。

本机审计脚本和原始文件快照位于 Git 忽略的 `.tmp/project-cleanup-20260920-375a/`，不是新测试框架或跨工作区依赖。当前可复跑的正式入口见[测试指南](../testing-guide.md)。

浏览器和 Vite 首次受限执行均遇到 `spawn EPERM`；使用获准的正常本机权限后通过。没有改变应用权限、更新基线或放宽断言。

### 保留的既有失败

`tests/coding_acceptance/test_tooling.py::test_configuration_import_is_blocked_and_directory_supports_io` 预期导入守卫返回“隔离测试禁止”，实际先遇到 `No module named 'personal_assistant'`。旧后端在本次之前已被删除。

通过整理前保存的 `test_tooling.py`、`run_coding_validation.py`、`coding_validation_plugin.py` 与原有隔离环境重跑同一节点，得到同样的 1 failed。相关测试、插件和业务源码均未改动，没有删除或放宽该断言。此结果不是本次路径移动造成的回归，也不宣称全量测试通过。

本次未运行 Python 1,359 项全量断言、全部 65 项浏览器断言或真实安装/更新/付费模型验收；收集成功仅证明入口完整。

## 项目记忆同步

已阅读 `docs/project-state.md` 及本机化、上下文和当前工具说明。项目记忆中的旧后端描述保留明确日期，以较新的本机化说明和源码为准。

`project-state.md` 只修正因归档变化的链接，并将已删除源码链接改成历史路径标注；未改写日期、业务状态或历史测试结果。目录职责和当前运行命令同步到文档中心、根 README 和测试指南，没有创建新的记忆系统。

## 完整文件清单

以下相对于本次开始前的快照，未将其他会话已经删除或修改的文件计作本次工作。

### 移动或重命名

| 原路径 | 现路径 | 内容 |
| --- | --- | --- |
| `docs/admin-service-logs.md` | `docs/archive/legacy/admin-service-logs.md` | 历史资料归档；同步链接和适用范围 |
| `docs/agent-runtime-gray-verification.md` | `docs/archive/legacy/agent-runtime-gray-verification.md` | 历史资料归档；同步链接和适用范围 |
| `docs/agent-runtime.md` | `docs/archive/legacy/agent-runtime.md` | 历史资料归档；同步链接和适用范围 |
| `docs/analysis/modernization-audit.md` | `docs/archive/legacy/analysis/modernization-audit.md` | 历史资料归档；同步链接和适用范围 |
| `docs/analysis/rag-data-quality-audit-20260802.ipynb` | `docs/archive/legacy/analysis/rag-data-quality-audit-20260802.ipynb` | 历史资料归档；同步链接和适用范围 |
| `docs/analysis/rag-data-quality-report-artifact.json` | `docs/archive/legacy/analysis/rag-data-quality-report-artifact.json` | 历史资料归档；同步链接和适用范围 |
| `docs/analysis/rag-data-quality-validation.md` | `docs/archive/legacy/analysis/rag-data-quality-validation.md` | 历史资料归档；同步链接和适用范围 |
| `docs/api-reference.md` | `docs/archive/legacy/api-reference.md` | 历史资料归档；同步链接和适用范围 |
| `docs/centos-stream9-deployment.md` | `docs/archive/legacy/centos-stream9-deployment.md` | 历史资料归档；同步链接和适用范围 |
| `docs/coding-agent-refactor-plan.md` | `docs/archive/legacy/coding-agent-refactor-plan.md` | 历史资料归档；同步链接和适用范围 |
| `docs/connected-desktop-local-execution.md` | `docs/archive/legacy/connected-desktop-local-execution.md` | 历史资料归档；同步链接和适用范围 |
| `docs/connected-desktop-rollout.md` | `docs/archive/legacy/connected-desktop-rollout.md` | 历史资料归档；同步链接和适用范围 |
| `docs/connected-runtime-1.0.3-repair.md` | `docs/archive/legacy/connected-runtime-1.0.3-repair.md` | 历史资料归档；同步链接和适用范围 |
| `docs/cross-platform.md` | `docs/archive/legacy/cross-platform.md` | 历史资料归档；同步链接和适用范围 |
| `docs/database-design.md` | `docs/archive/legacy/database-design.md` | 历史资料归档；同步链接和适用范围 |
| `docs/database-upgrade-runbook.md` | `docs/archive/legacy/database-upgrade-runbook.md` | 历史资料归档；同步链接和适用范围 |
| `docs/deployment-guide.md` | `docs/archive/legacy/deployment-guide.md` | 历史资料归档；同步链接和适用范围 |
| `docs/deployment-handoff-20260830.md` | `docs/archive/legacy/deployment-handoff-20260830.md` | 历史资料归档；同步链接和适用范围 |
| `docs/domain-verifiers.md` | `docs/archive/legacy/domain-verifiers.md` | 历史资料归档；同步链接和适用范围 |
| `docs/examples/rag-evaluation-cases.example.json` | `docs/archive/legacy/examples/rag-evaluation-cases.example.json` | 历史资料归档；同步链接和适用范围 |
| `docs/mcp-design.md` | `docs/archive/legacy/mcp-design.md` | 历史资料归档；同步链接和适用范围 |
| `docs/new-computer-development.md` | `docs/archive/legacy/new-computer-development.md` | 历史资料归档；同步链接和适用范围 |
| `docs/next-agent-handoff-1.0.3.md` | `docs/archive/legacy/next-agent-handoff-1.0.3.md` | 历史资料归档；同步链接和适用范围 |
| `docs/ollama-lifecycle.md` | `docs/archive/legacy/ollama-lifecycle.md` | 历史资料归档；同步链接和适用范围 |
| `docs/rag-design.md` | `docs/archive/legacy/rag-design.md` | 历史资料归档；同步链接和适用范围 |
| `docs/release-checklist.md` | `docs/archive/legacy/release-checklist.md` | 历史资料归档；同步链接和适用范围 |
| `docs/remote-client-updates.md` | `docs/archive/legacy/remote-client-updates.md` | 历史资料归档；同步链接和适用范围 |
| `docs/requirements.md` | `docs/archive/legacy/requirements.md` | 历史资料归档；同步链接和适用范围 |
| `docs/security-model.md` | `docs/archive/legacy/security-model.md` | 历史资料归档；同步链接和适用范围 |
| `docs/server-code-update-workflow.md` | `docs/archive/legacy/server-code-update-workflow.md` | 历史资料归档；同步链接和适用范围 |
| `docs/signing-and-keys.md` | `docs/archive/legacy/signing-and-keys.md` | 历史资料归档；同步链接和适用范围 |
| `docs/target-architecture.md` | `docs/archive/legacy/target-architecture.md` | 历史资料归档；同步链接和适用范围 |
| `docs/tool-system.md` | `docs/archive/legacy/tool-system.md` | 历史资料归档；同步链接和适用范围 |
| `docs/troubleshooting.md` | `docs/archive/legacy/troubleshooting.md` | 历史资料归档；同步链接和适用范围 |
| `docs/unified-desktop-runtime.md` | `docs/archive/legacy/unified-desktop-runtime.md` | 历史资料归档；同步链接和适用范围 |
| `docs/unified-preview-server-update.md` | `docs/archive/legacy/unified-preview-server-update.md` | 历史资料归档；同步链接和适用范围 |
| `docs/usage-guide.md` | `docs/archive/legacy/usage-guide.md` | 历史资料归档；同步链接和适用范围 |
| `tests/test_agent_runtime.py` | `tests/unit/test_agent_runtime.py` | 有效测试按职责归类；保留断言 |
| `tests/test_model_gateway.py` | `tests/unit/test_model_gateway.py` | 有效测试按职责归类；保留断言 |
| `tests/test_model_metadata.py` | `tests/unit/test_model_metadata.py` | 有效测试按职责归类；保留断言 |
| `tests/test_nsis_installer_template.py` | `tests/packaging/test_nsis_installer_template.py` | 有效测试按职责归类；保留断言 |
| `tests/test_phase8_release.py` | `tests/packaging/test_release_manifest.py` | 有效测试按职责归类；保留断言 |
| `tests/test_phase8_signing.py` | `tests/packaging/test_sign_installer.py` | 有效测试按职责归类；保留断言 |
| `tests/test_v100_ct3_model_probe.py` | `tests/unit/test_model_probe.py` | 有效测试按职责归类；保留断言 |

### 原位置修改

| 文件 | 修改 |
| --- | --- |
| `AGENTS.md` | 同步归档链接与历史路径说明 |
| `CHANGELOG.md` | 同步归档链接与历史路径说明 |
| `README.md` | 同步测试分组与归档目录 |
| `apps/desktop/e2e/visual-regression.spec.ts` | 移除旧页面断言与专用夹具，保留 Coding 部分 |
| `apps/desktop/src/components/UpdateChecker.vue` | 仅同步提示文案中的签名文档路径 |
| `apps/desktop/playwright.config.ts` | 仅更新原生验收说明的文档引用注释 |
| `docs/README.md` | 重写当前文档入口和目录职责 |
| `docs/analysis/agent-improvement-20260917/README.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/agent-improvement-20260917/step-2-planning-context-and-recovery.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/agent-improvement-20260917/step-3-capabilities-and-trial-delivery.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/README.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s0-baseline-and-contracts.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s0-validation-report.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s1-completion-and-verification.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s1-validation-report.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s2-instructions-and-context.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s2-validation-report.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s3-repository-and-patches.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s3-validation-report.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s4-execution-streaming-and-permissions.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s4-validation-report.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s5-blockers-validation-report.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s5-remaining-gates-validation-report.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s5-validation-report.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s6-evaluation-and-delivery.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s6-phase-c-validation-report.md` | 同步归档链接与历史路径说明 |
| `docs/analysis/coding-agent-upgrade-20260908/s6-validation-report.md` | 同步归档链接与历史路径说明 |
| `docs/archive/README.md` | 增加旧架构归档入口 |
| `docs/archive/phases/phase4-plan.md` | 同步归档链接与历史路径说明 |
| `docs/archive/phases/phase5-plan.md` | 同步归档链接与历史路径说明 |
| `docs/archive/phases/phase5-requirements.md` | 同步归档链接与历史路径说明 |
| `docs/archive/phases/phase6-plan.md` | 同步归档链接与历史路径说明 |
| `docs/archive/phases/phase6-requirements.md` | 同步归档链接与历史路径说明 |
| `docs/archive/phases/phase7-plan.md` | 同步归档链接与历史路径说明 |
| `docs/archive/phases/phase7-requirements.md` | 同步归档链接与历史路径说明 |
| `docs/archive/phases/phase8-plan.md` | 同步归档链接与历史路径说明 |
| `docs/archive/phases/phase8-requirements.md` | 同步归档链接与历史路径说明 |
| `docs/archive/planning/migration-plan.md` | 同步归档链接与历史路径说明 |
| `docs/archive/planning/remaining-work-plan-20260806.md` | 同步归档链接与历史路径说明 |
| `docs/project-state.md` | 修正归档链接，将已删除源码链接标为历史路径，保留日期和状态 |
| `docs/releases/coding-agent-version-roadmap-20260820.md` | 同步归档链接与历史路径说明 |
| `docs/releases/remote-v1.0.1-server-preview.1.md` | 同步归档链接与历史路径说明 |
| `docs/releases/remote-v1.0.2-model-config-preview.1.md` | 同步归档链接与历史路径说明 |
| `docs/releases/remote-v1.0.3-git-permissions-preview.1.md` | 同步归档链接与历史路径说明 |
| `docs/releases/remote-v1.0.4-test.1-20260831.md` | 同步归档链接与历史路径说明 |
| `docs/releases/v1.0.0/v1.0.0-ct0-ct2-iteration-report-20260825.md` | 同步归档链接与历史路径说明 |
| `docs/releases/v1.0.0/v1.0.0-development-plan-20260820.md` | 同步归档链接与历史路径说明 |
| `docs/solutions/2026-08-31-model-502-admin-timezone.md` | 同步归档链接与历史路径说明 |
| `docs/solutions/2026-08-31-privateagent-1-0-3.md` | 同步归档链接与历史路径说明 |
| `docs/solutions/2026-08-31-server-account-login.md` | 同步归档链接与历史路径说明 |
| `docs/solutions/2026-09-19-api-key-only.md` | 同步归档链接与历史路径说明 |
| `docs/solutions/2026-09-20-local-only-context-files.md` | 同步归档链接与历史路径说明 |
| `docs/testing-guide.md` | 以本机隔离入口替换旧测试指南 |
| `scripts/run_coding_validation.py` | 更新七个测试文件路径 |
| `scripts/generate-latest-json.py` | 仅同步错误提示中的签名文档路径 |
| `scripts/sign_installer.py` | 仅同步文档和测试引用 |

### 新增

| 文件 | 用途 |
| --- | --- |
| `docs/archive/legacy/README.md` | 旧架构归档索引 |
| `docs/archive/legacy/testing-guide.md` | 保留整理前测试指南及历史结果 |
| `docs/solutions/2026-09-20-project-cleanup.md` | 本次删除依据、清单与验证边界 |

### 删除

| 文件 | 依据 |
| --- | --- |
| `apps/spawn-test/Cargo.lock` | 固定本机绝对路径的独立实验，无当前调用方 |
| `apps/spawn-test/Cargo.toml` | 固定本机绝对路径的独立实验，无当前调用方 |
| `apps/spawn-test/src/main.rs` | 固定本机绝对路径的独立实验，无当前调用方 |
| `scripts/spikes/s1_sandbox_windows_spike.py` | 早期可行性实验，不被当前构建和测试入口调用 |
| `scripts/spikes/s1_transport_stdio_spike.py` | 早期可行性实验，不被当前构建和测试入口调用 |
| `scripts/spikes/s4_network_appcontainer_spike.py` | 早期可行性实验，不被当前构建和测试入口调用 |
| `docs/examples/updater-latest.json` | 旧 0.1.1 生成清单；保留可复制的 .example 模板 |
| `apps/desktop/e2e/accessibility.spec.ts` | 断言目标为已退役页面或全局配置导入；evidence 是旧版一次性截图生成器 |
| `apps/desktop/e2e/agent-w6r2.spec.ts` | 断言目标为已退役页面或全局配置导入；evidence 是旧版一次性截图生成器 |
| `apps/desktop/e2e/agent-w6r3.spec.ts` | 断言目标为已退役页面或全局配置导入；evidence 是旧版一次性截图生成器 |
| `apps/desktop/e2e/animation.spec.ts` | 断言目标为已退役页面或全局配置导入；evidence 是旧版一次性截图生成器 |
| `apps/desktop/e2e/coding-h1d.spec.ts` | 断言目标为已退役页面或全局配置导入；evidence 是旧版一次性截图生成器 |
| `apps/desktop/e2e/evidence.spec.ts` | 断言目标为已退役页面或全局配置导入；evidence 是旧版一次性截图生成器 |
| `apps/desktop/e2e/keyboard-focus.spec.ts` | 断言目标为已退役页面或全局配置导入；evidence 是旧版一次性截图生成器 |
| `apps/desktop/e2e/pages-smoke.spec.ts` | 断言目标为已退役页面或全局配置导入；evidence 是旧版一次性截图生成器 |
| `apps/desktop/e2e/performance-resource.spec.ts` | 断言目标为已退役页面或全局配置导入；evidence 是旧版一次性截图生成器 |
| `apps/desktop/e2e/shell-v2.spec.ts` | 断言目标为已退役页面或全局配置导入；evidence 是旧版一次性截图生成器 |
| `apps/desktop/e2e/smoke.spec.ts` | 断言目标为已退役页面或全局配置导入；evidence 是旧版一次性截图生成器 |
| `apps/desktop/e2e/visual-regression.spec.ts-snapshots/v1-legacy-1440-chromium-win32.png` | 对应已退役页面的截图基线 |
| `apps/desktop/e2e/visual-regression.spec.ts-snapshots/v2-agent-1280-chromium-win32.png` | 对应已退役页面的截图基线 |
| `apps/desktop/e2e/visual-regression.spec.ts-snapshots/v2-agent-1440-chromium-win32.png` | 对应已退役页面的截图基线 |
| `apps/desktop/e2e/visual-regression.spec.ts-snapshots/v2-agent-1920-chromium-win32.png` | 对应已退役页面的截图基线 |
| `apps/desktop/e2e/visual-regression.spec.ts-snapshots/v2-today-1440-chromium-win32.png` | 对应已退役页面的截图基线 |

本次未提交、推送、发布、部署或变更锁文件。
