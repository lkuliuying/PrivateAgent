# 2026-09-20 本机代码收敛与上下文管理改进

本次范围是删除旧服务端代码，保留 API Key 桌面本机链，并针对此前比较中发现的上下文预算和压缩连续性问题完成改进。源码基于 `dev/1.0.0` 的工作区，HEAD 为 `1dde393e29f3dbacd3647d11834b39824ac8323f`；开始时已有大量未提交改动，因此本记录按任务开始前的文件快照区分本次变更，不把整个 Git diff 计作本次成果。

## 1. 当前交付边界

- 保留 `apps/desktop`、`apps/exec-host`、`private_agent_core`、`private_agent_local`。模型由用户电脑通过已有供应商适配器直连，密钥仍由系统凭据库管理，本机数据仍使用 SQLite。
- 删除 `personal_assistant` 全部源码、Alembic 迁移及配置、旧容器与服务器部署入口、服务器专属脚本和测试、桌面旧服务器启动与凭据提示链，以及已经不在本机路由中的旧业务页面和接口。
- 原 `cloud.py` 中的账号服务器 HTTP 代理删除。本机仍使用的安全错误和调用关联标识独立为 `model_errors.py`；内部 `CloudError` 名称保留，不代表旧网络代理仍存在。
- 共享模型网关、模型元数据、模型探测、运行时及桌面签名测试保留，导入改为本机共享包。用于本机测试的模型替身只在进程内返回合成响应，不建立旧账号服务器。
- Python wheel 只收录两个本机包；移除 ORM、MySQL、Alembic、向量库及旧文档/RAG 依赖，重新解析与当前声明一致的锁文件。FastAPI 继续服务本机 IPC 请求分发和可选回环入口。
- 不删除已有用户数据库、供应商密钥或安装副本，不迁移或合并旧身份空间，不改变已有桌面数据目录和密钥命名。

`build-client.cmd` 是本机入口；`build-release.bat` 转发到同一入口。底层构建器保留两种既有桌面标识，但产物均为本机 API Key 链，两种更新目标仍隔离。默认配置没有旧后端 sidecar 和旧更新源，正式统一客户端要求显式配置独立更新地址。

发布清单从明确指定的本机构建目录读取源码清单和产物摘要，不再探测数据库或推断测试通过。SignPath 工作流改用本机打包链，更新签名覆盖最终签名后的安装器字节，并调用已有验证器核验签名。本次没有执行远端工作流、签名、发布或安装。

## 2. 上下文改进

### 输入预算先于硬上限触发压缩

此前默认 8192 tokens 窗口预留 2048 输出和 512 安全量，输入硬上限为 5632，但自动压缩阈值为 6554，存在已经超限却未触发压缩的区间。

现在阈值取以下较小值，并限制为非负数：

1. 窗口的 80%，或显式 `context_limits.auto_compact_token_limit`。
2. 输入预算减去 `max(256, 输入预算 × 10%)`。

请求字节、消息数或输入估算超过硬上限时一定满足压缩条件。若用户原文、规则等必需内容压缩后仍放不下，继续明确阻断。容量未知时仍显示未知，并沿用 8192 的内部保守边界；没有把估算包装成模型精确 tokenizer 的计数。

### 带来源的工作摘要与事实索引并存

活跃任务在安全模型边界压缩时，默认尝试一次语义摘要：

- 使用当前供应商、模型和凭据；不带工具，不自动重试，最多等待 30 秒，并受任务剩余时间约束。
- 最多选择 24 个非敏感历史来源，每个摘录最多 1000 字符，较长条目保留首尾；输入保守估算最多 16000 tokens，且不能突破所选模型预算。
- 输出最多 1024 tokens。通过严格 schema 限制为最多 8 项发现、决定、待办或风险，每项最多 240 字符，并要求 1 至 4 个已提供的来源 ID。
- 校验已知凭据、疑似秘密、来源 ID、响应结构和模型路由；拒绝工具调用。摘要只作为未经重新核验的参考，不增加权限或完成证据。
- 调用计入任务请求数、token、费用和有效运行时间。超时、取消或无效响应可能已经产生供应商费用，未知用量不能记录为零。
- 至少为主任务保留一次模型调用机会。关闭 `semantic_compaction`、预算不足、无摘要适配器、响应不合格或加入摘要后超限时，使用确定性事实索引；空闲手动压缩不额外调用模型。
- 在调用模型前先核对事实索引是否能缩小请求并满足硬预算；必需内容已经无法容纳时直接停止，不为无收益的摘要消耗模型调用。

全部用户原文、最近两个完整调用组及原始历史继续保留。稳定项目规则放在动态计划信息之前，减少不必要的前缀变化；不声称供应商一定命中缓存。

### 有界索引和原文续读

请求只携带最近 12 项工具事实、有限的失败/修改/回答引用和既有分析摘录。完整事实及来源索引保存在 SQLite 检查点，通过 `archive_ref` 交给 `read_context_content` 分页读取；旧的原始 item ID 续读继续可用。单页最多 6000 字符，拒绝负偏移和跨会话访问。

语义摘要完成后重新检查运行代次、模型配置和能力、项目位置、规则、权限、历史末序号。取消或配置变化不会提交半份或过时摘要。检查点只增加 JSON 元数据，没有数据库 schema 迁移。

### 长期记忆相关性

自动生成的记忆在查询关键词零匹配时不进入召回；人工维护的用户偏好继续可用。仍采用原有关键词排序、最多 8 条和约 6000 字节的限制，没有新增向量服务或改变默认关闭策略。

## 3. 与 Codex 的对齐范围

本次对齐的是公开可观察的管理行为：提前压缩、通过摘要延续任务语义、按需取回来源、保留规则与任务约束、明确预算和失败边界。参考会话中查阅的 [Codex 压缩命令](https://learn.chatgpt.com/docs/developer-commands?surface=cli)、[配置项](https://learn.chatgpt.com/docs/config-file/config-reference)与[项目指令](https://learn.chatgpt.com/docs/agent-configuration/agents-md)。

本项目使用供应商通用文本摘要，未接入 OpenAI 专有 compaction 接口，也没有复制 Codex 内部算法。以下能力仍有差别：

- 用户原文始终完整保留，极长用户对话仍可能超限；这比自动舍弃旧指令保守，但容量收益有限。
- 摘要只覆盖有界来源，结构和引用校验不能证明语义完全准确。
- 长期记忆仍为关键词召回；没有语义检索或本机子 Agent 上下文隔离。
- 技能按需加载、跨会话记忆质量和不同模型的长任务成功率没有在本次做等价实测。

## 4. 验证记录

所有 Python 业务测试通过隔离运行器创建独立目录，使用临时数据和合成模型。没有读取真实用户数据或调用付费模型。

### 已通过

| 实际命令 | 观察结果 |
| --- | --- |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite context-alignment` | 最后一次 15 passed；覆盖预算、摘要来源/秘密/路由、失败回退、取消、等待期间模型/规则变化、归档续读与本机交付边界 |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite memory` | 77 passed；含上下文原有回归和召回筛选 |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite context` | 44 passed |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite shared-models` | 37 passed |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite direct-models` | 58 passed |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite streaming` | 26 passed |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite desktop-packaging` | 24 passed |
| `.venv\Scripts\python.exe -B scripts/protocol_codegen.py --check` | 本机共享协议生成结果同步 |
| `node --test scripts/build-remote-client.test.cjs` | 12 passed |
| `npm run build`（`apps/desktop`） | Vue 类型检查与 Vite 构建通过；保留已有 chunk 大于 500 kB 警告 |
| `cargo test --offline --manifest-path apps/desktop/src-tauri/Cargo.toml --lib`（初始化 MSVC） | 普通本机权限下 3 passed、1 ignored；忽略项为由另一测试启动的子进程辅助用例 |
| `cargo check --offline --locked --manifest-path apps/desktop/src-tauri/Cargo.toml --features readiness-probe`（初始化 MSVC） | 通过，已有 readiness probe 的 4 个未使用项警告 |
| `uv lock --check --offline --cache-dir .run/uv-cache` | 58 个锁定依赖解析一致 |
| `uv build --wheel --offline --out-dir .run/local-only-wheel --cache-dir .run/uv-cache --python .venv/Scripts/python.exe` | 最终 wheel 构建通过；ZIP 检查仅含两个本机包和发行元数据，未混入旧服务端或缓存，三个上下文模块与最终源码逐字节一致 |

`uv` 和 `cargo` 实际调用使用本机已安装程序的绝对路径。wheel 首次尝试 `--no-build-isolation` 因虚拟环境缺少 `hatchling` 失败，随后使用默认隔离构建成功，没有向项目运行环境额外安装构建器。

变更涉及的 37 个 Python 文件执行 Ruff 检查通过。任务修改文件的 `git diff --check` 和 README/本记录/文件清单的本地链接检查通过。SignPath YAML 解析及 12 段 PowerShell 脚本静态语法检查通过；安装的 Tauri CLI 帮助确认 `signer sign` 使用位置文件参数。以上不等于远端工作流已经运行。

### 限制和未通过项

- 后端 `--suite all` 两次均超过 900 秒，调用记录返回 124，未形成完整 pytest 结束报告；首次为受限环境，第二次为普通本机权限。因此没有“后端全量通过”的结论，不能把第二次超时单独归咎于权限。
- 第二次超时前出现 40 个失败标记。逐项核对发现一项本次引入的多余摘要请求，已修复并定向复验通过；其余已归因情况见下表。全量运行启动早于最后的修复，修复后重新运行了上下文 15 项、原有上下文 44 项和相应 IPC 用例，没有把早先结果当作最终全量结果。
- 前端 `npm test` 最后一次为 582 passed、2 failed。失败均在 `RunS1Completion.spec.ts`，正文断言仍要求出现“已回答”“已验证完成”；测试与对应展示组件和状态映射同任务开始前一致，本次没有修改断言来获得通过。
- 浏览器 `node node_modules/@playwright/test/cli.js test e2e/local-access.spec.ts e2e/memories.spec.ts --retries=0` 为 1 passed、1 failed。本机访问流程通过；记忆流程第 63 行的 `getByRole('status')` 同时匹配保存提示与处理中状态，触发 strict mode。对应测试和记忆设置组件同任务开始前一致，该用例后续步骤未验证。
- 整体 Ruff 存在 `tests/unit/test_local_file_ranges.py:67:5 I001`；该文件与任务开始前逐字节一致。没有顺带整理其他任务改动。
- 首次受限环境前端构建遇到进程启动限制，Rust 子进程清理测试遇到 `WAIT_TIMEOUT`；普通本机权限下对应构建和 Rust 测试通过。
- 没有构建完整 NSIS/便携 exe，没有执行安装、升级、真实供应商调用或跨平台验证。

### 后端失败归因与定向复验

定向测试通过 `.venv\Scripts\python.exe -B -X utf8 -` 调用隔离环境和进程树管理器，再执行 `pytest --noconftest -p coding_validation_plugin -p pytest_asyncio.plugin -o addopts= -o filterwarnings= -q -ra`，按下表节点或 `-k` 选择用例。源码对照使用任务开始前保存的两个本机包副本和同一个已构建测试宿主，没有回退工作区或修改测试断言。

| 用例/选择条件 | 实际结果与归属 |
| --- | --- |
| `test_s6_delivery.py::test_ipc_runtime_wins_after_budget_cancel_decision` | 原改动多发一次摘要请求，定向复验失败；加入模型调用前的硬预算检查后 1 passed，原源码对照也通过 |
| `-k "late_ipc_cancel"` | 4 failed；测试用 `__new__` 构造的 `RuntimeClient` 缺少 `token`。测试与 `coding_acceptance_transport.py` 均与任务开始前逐字节一致 |
| `test_s6_delivery.py::test_ipc_budget_cancel_closes_pending_approval_without_consuming_it` | 当前源码和原源码副本均未等到 `waiting_approval`，实际为 `limit_exceeded / context_limit`，原有失败 |
| `-k "legacy_local_unbilled or product_probe_uses_agent"`（`test_s6_models.py`） | 当前源码与原源码副本均 3 failed，任务输出验收为 `task_or_protocol_failed`；没有改写断言或放宽验收 |
| `-k "execution_instructions_preserve_public"`（`test_s6_local_probe.py`） | 30 failed，任务文本转成的要求列表与旧断言不一致；测试、提示生成器、`completion.py` 和 `task_intent.py` 均与任务开始前逐字节一致 |
| `test_s6_local_probe.py::test_local_probe_uses_actual_agent_and_bounded_cloud_adapter[pass]` | 全量运行中失败，原源码副本定向复验也为 `task_or_protocol_failed`，原有失败 |

受限环境下同一 IPC 定向测试还出现过“持续执行宿主不可用”的预检错误；上表有关进程行为的归因均使用普通本机权限的复验或原源码对照，不以该环境错误替代代码诊断。

## 5. 文档与项目记忆

已读取 `docs/project-state.md`、上下文/记忆设计及相关本机执行说明。9 月 19 日状态记忆中“旧独立后端仍保留”的描述早于本次删除；以当前包目录、导入审计、构建产物和本记录为准。

按仓库入口要求，只有用户明确要求维护项目记忆时才改写 `docs/project-state.md`，因此其内容与任务开始前逐字节一致。当前源码边界已同步到 `AGENTS.md`、README、上下文/记忆设计、本机模型、测试及新电脑开发说明；旧服务器设计保留并明确标为历史。没有新建独立记忆系统。

## 6. 变更归属和恢复边界

任务开始前已保存源文件快照及 SHA-256 清单，完整任务差异见[本次变更文件清单](2026-09-20-local-only-context-files.md)。统计以快照为基线，排除开始前已删除或新增且本次未改动的文件；已有本机功能改动继续保留。

本次没有提交、推送、部署、修改服务器或清空本机用户数据。源码目录和 wheel 验证结果不代表电脑上已安装的旧副本已更新。若后续需要安装包验收，应从同一源码构建客户端、执行器与宿主，并在隔离测试数据下验证安装和升级；不能只替换其中一个二进制文件。
