# 第一阶段试用反馈修复 · 1.0.11

记录日期：2026-09-18。承接 1.0.10 T01 用户反馈：修改、四项 pytest 和首次最终验收通过；本次过程未调用搜索工具，因此不能把它当作 glob 参数修复的新增实测证据。说明文字仍出现 `0 + 4 = 0`，正确值为 4。

## 本轮实现

- `runProjector` 优先读取后端 `estimated_input_tokens`，兼容旧 `estimated_tokens`。缺失、非整数、负数或无效值保留为未知；界面显示“估算暂不可用”，不补成 0。实际报告的 0 仍可显示。
- 现有安全 Markdown 渲染器支持表头、分隔行、对齐、转义竖线、行内格式及有界列补齐。单个表格最多 32 列、2048 个数据单元格，超限内容保留为文字，防止稀疏大表补齐导致内存膨胀。公开流式输出、最终答案和历史回答复用该渲染器。保留 HTML 不执行、危险链接不可点击的边界，不增加依赖。
- 执行结果新增可选 `runtime_warnings` 元数据。Windows 受限模式可见 stderr 中出现完整的 Python 路径解析警告时，返回 `python_path_resolution_warning` 与固定说明；命令卡展示诊断，原始输出、退出码、任务验收和权限不变。已完成会话的诊断随记录回放，历史记录不追写。
- 模型系统提示增加“回复前复核数值例子、测试成功不证明每项解释正确”的要求。通过真实请求适配器验证提示已传给模型；没有把提示等同于模型正确性的保证。

## Python 警告的定位与限制

使用本机 `C:\ProgramSoftware\Environment\python\python.EXE`（3.13.13）在独立测试目录对照：普通进程没有 stderr；同一解释器在 AppContainer 内仍可执行，但输出该警告。相同文件句柄的 `GetFinalPathNameByHandleW` 在 DOS/GUID 卷名模式返回 Win32 错误 5，在 NT/无卷名模式成功，文件打开本身成功。

[CPython 路径解析实现](https://github.com/python/cpython/blob/3.13/Modules/getpath.c)使用 DOS 卷名查询；[微软上游问题记录](https://github.com/microsoft/mxc/issues/694)描述了相同 AppContainer 兼容限制。以上证据支持本机根因判断，不意味着任意环境中同文警告都只有这一原因。

本轮采用诊断处理，未消除解释器发出的原始提示。没有修改系统对象 ACL、放宽沙箱、替换 Python、隐藏 stderr 或自动升级执行权限。彻底消除提示需要解释器或系统层兼容修复，保留为限制。

## 验证与交付状态

源码回归：本地 87、上下文 35、执行会话 33、完成验收 174，共 329 项通过；前端 110 项通过。执行会话新增测试首次有 2 项因 Windows 文本模式换行假设失败，改为二进制输出夹具后 33 项通过，产品未改写换行。

浏览器使用实际 Vue 组件检查 1100px、480px：token 为 3,521，表格可见，窄窗多列表格内部滚动，页面不横向溢出。首次临时预览因扫描范围过大挂起，已回收进程，限定桌面目录后通过。该检查不等同于已安装桌面窗口验收。

Ruff 与协议生成一致性检查通过。最终候选包构建、通用随包验证与 8 个场景全部通过。测试集保留原有 T01–T14 项目字节，新增 `UI-RETEST.md` 展示与诊断复测说明。

最终二进制的首次 T01 随包检查触发夹具 90 秒期限。只读核对其独立测试数据库，`python --version` 与修复前 pytest 分别在约 43、45 秒后正常退出（0、1），尚未到修复步骤；不是把修复后的测试失败判为通过。T01 含三次沙箱启动，因此将本次临时夹具期限设为 240 秒后在新目录复测，8 个场景全部通过。保留原失败证据；产品时限、权限和结果断言不变。

## 项目记忆同步

读取根 `AGENTS.md`、`docs/project-state.md` 历史快照、本阶段索引及 1.0.10 记录，与当前源码和用户回执核对。旧 token 消费字段与当前后端事件字段不一致，已修正消费者并覆盖新旧事件；阶段索引更新最新证据。按仓库入口约定不自动改写 2026-08-31 历史状态记忆，不改旧候选交付物。

## 本轮变更文件

以下相对于任务开始时保存的工作区基线核对，保留之前的未提交改动：

| 文件 | 变更 |
|---|---|
| `src/private_agent_local/runtime.py` | 数值例子复核提示 |
| `src/private_agent_local/execution_diagnostics.py` | 新增有条件的路径警告识别 |
| `src/private_agent_local/executor.py` | 单次执行输出附加诊断 |
| `src/private_agent_local/execution_sessions.py` | 持续执行完成、模型续读及回放保留诊断 |
| `tests/unit/test_local_model_contract.py` | 实际模型请求中的复核提示断言 |
| `tests/unit/test_local_execution_sessions.py` | 诊断匹配边界、输出与退出码保留、历史回放 |
| `apps/desktop/src/features/coding/model/runProjector.ts` | 新旧估算字段映射与未知值 |
| `apps/desktop/src/features/coding/model/runProjector.spec.ts` | 字段优先级、无效值与重放 |
| `apps/desktop/src/features/coding/components/RunTranscript.vue` | 估算显示、公开输出复用 Markdown |
| `apps/desktop/src/features/coding/components/RunTranscript.spec.ts` | 展示与公开输出验收边界 |
| `apps/desktop/src/features/coding/components/MarkdownContent.vue` | 安全表格与渲染边界 |
| `apps/desktop/src/features/coding/components/MarkdownContent.spec.ts` | 表格、转义、流式、恶意内容及大表测试 |
| `apps/desktop/src/features/coding/components/CommandOutput.vue` | 已知警告标签及详情 |
| `apps/desktop/src/features/coding/components/CommandOutput.spec.ts` | 警告元数据与退出结果分离 |
| `apps/desktop/src/features/coding/dev/codingRunPreview.ts` | 开发预览改用当前后端字段 |
| `docs/analysis/agent-improvement-20260917/README.md` | 最新用户回执与候选状态 |
| 本文 | 原因、变更、验证与限制 |

临时复现、基线副本、构建日志、截图、全新测试集和交付物均在 `.run/intent-trial-1.0.11/`，不混入产品代码。未修改依赖、锁文件、系统权限、生产数据或 Git 历史。

## 可追溯验证命令

执行目录为 `F:\Program\Agent`，测试使用独立目录和本地模拟模型：

```powershell
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite local
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite context
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite execution
.\.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite completion
.\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.11/check-frontend.py
node .run/intent-trial-1.0.11/visual-check.mjs
.\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.11/diagnose-python.py
.\.venv\Scripts\python.exe -B -m ruff check src/private_agent_local/runtime.py src/private_agent_local/executor.py src/private_agent_local/execution_sessions.py src/private_agent_local/execution_diagnostics.py tests/unit/test_local_model_contract.py tests/unit/test_local_execution_sessions.py
.\.venv\Scripts\python.exe -B scripts/protocol_codegen.py --check
git diff --check
.\scripts\build-client.cmd --qa --preview-installer --version 1.0.11
```

四组后端测试分别为 87、35、33、174 项通过，无跳过。前端脚本执行 7 个现有 Vitest 文件，共 110 项通过。Ruff 首次发现新增导入顺序错误，调整后通过；协议生成与差异空白检查通过。浏览器检查和 Python 对照结果如上。构建包含 `vue-tsc --noEmit`、Vite、PyInstaller、Rust 与 NSIS；保留既有的 10 条 Rust 未使用代码警告。

模型真实调用、安装后的桌面窗口与全部人工场景尚未验收。请安装最终候选包，在全新目录中复测 T01 与 `UI-RETEST.md` 的 U01–U03。

## 最终随包证据与交付

以下最终包命令实际执行并退出 0：

```powershell
.\.venv\Scripts\python.exe -B scripts/verify-unified-client.py --bundle .run/unified-client-kng6UE --work-dir .run/intent-trial-1.0.11/packaged-validation-final --model-mode openai
.\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.11/verify-intent-package.py --bundle .run/unified-client-kng6UE --area .run/intent-trial-1.0.11/intent-package-check-final-retest
.\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.11/prepare-delivery.py
```

通用结果位于 `.run/intent-trial-1.0.11/packaged-validation-final/packaged-runtime-e94d86e2067a40ed9577373ee3736376/verification.json`；8 场景结果位于 `.run/intent-trial-1.0.11/intent-package-check-final-retest/verification.json`。T01 用用户同一 Python 3.13.13 执行：原始代码 4 failed / 退出 1，修复后 4 passed / 退出 0，最终 verified、2 项要求。两次 pytest 的原始路径警告和结构化诊断均保留。实际 `context.prepared` 事件提供正的 `estimated_input_tokens`。搜索空 glob 拒绝与纠正重试仍通过。

最后一次前端大表格边界改动后重新构建，最终 sidecar 文件摘要变化，因此对最终二进制重新执行随包验证；没有将前一构建的结果直接当作最终包结果。

交付目录：`F:/Program/Agent/.run/intent-trial-1.0.11/delivery/`。

- [1.0.11 候选安装器](../../../.run/intent-trial-1.0.11/delivery/PrivateAgentCandidate_1.0.11_x64-setup.exe)：30,833,928 字节。
- [全新测试 ZIP](../../../.run/intent-trial-1.0.11/delivery/PrivateAgent-M1-TestKit-1.0.11.zip)：14 个项目用例、107 个文件，附 U01–U03 展示与诊断复测；100 个项目文件及采集脚本与核对过 SHA256 的旧 1.0.9 ZIP 逐字节一致。
- [安装说明](../../../.run/intent-trial-1.0.11/delivery/README.md)、[补充复测步骤](../../../.run/intent-trial-1.0.11/delivery/UI-RETEST.md)、[反馈模板](../../../.run/intent-trial-1.0.11/delivery/RESULTS-template.md)。
- [验证清单](../../../.run/intent-trial-1.0.11/delivery/validation.json)、[构建信息](../../../.run/intent-trial-1.0.11/delivery/build-info.json)、[来源清单](../../../.run/intent-trial-1.0.11/delivery/source-manifest.json)、[文件校验值](../../../.run/intent-trial-1.0.11/delivery/SHA256SUMS.txt)。

安装器 SHA256：`ee5ddc066b50a3f80294137f7cfd70e2767fa3e935f6594c2a8aa0d7a06085a6`。

测试 ZIP SHA256：`b8a9176f949f236bf56f973d8526aebf30668330f42d8b7e1e10169d6296f04b`。

来源集合 SHA256：`db3ec755f6e5360a1cf5889bf803ad767556a2f57272f96fa98732dfcce814aa`。668 个来源文件逐项核对一致；相对于 1.0.10，仅本轮 13 项打包输入变化，无来源移除，后端测试及阶段文档不属于打包来源集合。Git HEAD 为 `1dde393e29f3dbacd3647d11834b39824ac8323f`，`dirty=true`。

候选身份 `com.personal-assistant.desktop.candidate`，版本 1.0.11，更新端点为空，签名检查为 `NotSigned`。没有自动安装、发布、上传、调整正式更新通道或创建 Git 提交。`validation.json` 明确记录 `python_warning_eliminated=false`、`real_model_called=false`、`installed_desktop_verified=false`。
