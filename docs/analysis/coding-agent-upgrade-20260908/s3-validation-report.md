# S3 仓库检索与多文件补丁验收报告

日期：2026-09-08。环境：Windows、`F:\Program\Agent`、现有 Python 3.12 虚拟环境及桌面 Node 依赖。

## 任务总结

用户要求进入 S3 开发。开工读取项目入口、完整 `docs/project-state.md`、S0 契约、S2 验收和 S3 计划后，核对分支为 `dev/1.0.0`、HEAD 为 `258544a`，工作区和暂存区均无改动。本轮按已说明的计划实现仓库读取、搜索、多文件补丁及桌面审查，未提交、推送、打包、安装或部署。

S3 已接入本机正式调用链：模型先读取版本，再提出结构化补丁；用户或现行自动批准策略消费精确预览；主机整体预检、逐项记录意图、执行并回读磁盘。部分失败保留已发生的操作，重启不自动重放。任务结束后可先预览再确认受保护回滚。S1 以日志和当前磁盘事实验证，S2 保留读取与执行来源关联。

本次完成的是源码与本机隔离验收。真实模型任务质量、发行安装和 S4 执行隔离不在这一结论内。

## 实际契约与实现决议

### 仓库工具

保留现有工具名称，相关工具执行及审批记录版本为 `2`；私有传输和执行宿主协议不变。

| 工具 | 行为与边界 |
| --- | --- |
| `read_code_file` | `start_line` 从 1 开始，`line_count` 默认 1000、最多 2000；单页正文 32000 字符。单行过长时用 `next_line/next_column` 续读，输入对应 `start_line/start_column`。返回完整文件 SHA、snapshot_id、总行数及实际行号。`expected_version` 不符则明确失败。 |
| `list_project_directory` | 默认每页 100、最多 200；目录优先、名称稳定排序。目录与条目元数据改变使游标失效。排除敏感位置、默认构建目录、链接和嵌套 Git。 |
| `search_project_files` | 字面/正则、内容/文件名、大小写、相对范围和 glob；默认每页 50、最多 200，游标绑定查询及扫描版本。完整两次扫描不一致则失败，避免静默漏项。 |
| `read_context_content` | 复用 S2 原始 ContextItem 受控续读，不能用任意磁盘路径替代引用。 |
| `read_patch_preview` | 按当前 run 的 patch_set_id/change_id、offset/limit 读取完整文件 diff；默认 8000、最多 16000 字符，支持 next_offset。 |

单文件上限 1 MiB，只接受 UTF-8 文本，可保留 BOM；局部行编辑保留未编辑内容及原 LF/CRLF 风格，末尾有无换行由局部替换文本明确决定。整文件覆盖仍会替换整个正文，因此提示模型优先采用局部 edits。二进制、不支持编码、硬链接与超限文件返回拒绝或明确跳过原因。

优先使用本机已有 rg，以 argv 和受控 stdin 执行，禁用 rg 配置注入；文件清单采用原生 ignore 语义，再由 Python 安全读取过滤。无 rg 时只提供有界字面搜索和基本 `.gitignore` 规则；复杂转义、字符组或 `**` 规则明确拒绝，不近似泄露被忽略内容，不自动安装依赖。没有捆绑 rg。参考：[ripgrep 指南](https://github.com/BurntSushi/ripgrep/blob/master/GUIDE.md)、[Git ignore 规则](https://git-scm.com/docs/gitignore)。

搜索限制为 10000 个扫描条目、16 MiB 文本、10000 条匹配；rg 每次最多 10 秒、输出最多 4 MiB，扫描逐目录/文件检查 10 秒预算。扫描移到工作线程，取消后在下一个文件边界停止；不能强行中断操作系统中已经开始的单次文件读取。匹配片段最多 500 字符，需要完整代码时按行读取。超限明确要求缩小范围，未建立全仓索引。

### 补丁、批准和落盘

`PatchProposal.operations` 支持 create、update、delete、move、mkdir，最多 32 项、请求 JSON 最多 4 MiB；展开后的前后内容及 diff 最多 12 MiB，每 run 最多 256 组补丁。move 拆成目标新增与源删除，并保留同一 group_id。mkdir 必须显式列出缺少的父目录。局部更新用 start_line/delete_count/text，不引入自由文本 patch 解析器或服务端仓储依赖。

update/delete/move 必须带当前 run 的 snapshot_id。快照保存规范路径、根身份、文件身份和 SHA，并关联产生它的 execution_id、operation_id、tool_call_id；旧 `write_project_file` 通过最近一次本 run 的实际读取绑定已有文件，缺少读取时拒绝。新增目标必须不存在。同集合重复路径、大小写别名、路径穿越、Windows 设备名/ADS、移动循环、文件祖先冲突均预先拒绝。

审批绑定 patch 内容摘要、根路径/身份、工作区、权限档位和临时授权。权限撤销、账号失效、规则变化或源文件变更均阻断继续执行。多文件目标分别经过 S2 规则发现；未实际交付给模型的受信子目录规则要求下一轮先检查。只读和仅预览模式可以提出预览，不能应用。

实际状态以 `validated → applying → applied` 为主，失败为 `conflicted / failed / partially_applied`，启动恢复为 `interrupted`。原计划中的 approved/rejected 仍由现有审批记录管理，未另建重复审批状态机。operation_id 标识各次工具调用，patch_set_id 标识预览集合；重复应用已 applied 的同一集合返回已有结果，不重复副作用。

每项 applying 意图先事务提交，再进行文件操作，写后独立回读并提交 applied 日志。更新在同目录创建临时文件、fsync 后 os.replace；新增通过排他硬链接提交临时文件并清理，避免覆盖已出现的目标。目录使用非递归 mkdir/rmdir，移动按明确的两步日志执行。保留 Python 支持的 mode；未声称完整复制 ACL、扩展属性或 Windows ADS。

### 日志、回滚、S1 与 Git

SQLite 当前为 schema 5，新增 `file_snapshots`、`patch_sets`、`patch_journal`。schema 2/3/4 先生成 `*.pre-v5-<唯一标识>.sqlite3` 一致性备份，再事务迁移；历史 ContextItem/授权/消息保留。大内容复用 Store 内容引用。当前没有新增自动保留期或清理任务，不能通过删表降级。

仅有 applying 意图而缺少 applied 记录时，磁盘即使碰巧等于预期也不补造成功；事实查询返回 matches_after/matches_before/conflict/unreadable 观察和原日志状态。原补丁禁止自动重放。重启只标记 interrupted，不自动恢复授权或接续执行。

回滚只选有 applied 日志且当前内容及身份仍吻合的项；后续用户修改保留并列出冲突。移动任一端冲突时两端都保留。新目录有后续文件时保留。回滚本身拥有独立预览、operation ID 和逐项日志，可能部分失败；本轮不支持对回滚再做回滚。UI 先展示预览，再用全局确认提交。重复提交同一回滚不重复改文件、事件或 workspace_version。

S1 从持久日志与当前磁盘状态生成证据，覆盖新增、修改、删除、移动和目录；不采信文件函数“成功”标记。回滚后原 run_outcome 转 unknown，原验证不能继续代表回滚后的工作区。

运行开始使用冻结的 WorkspaceIdentity 保存起始根、HEAD、分支和 dirty 状态；Git porcelain `-z` 保留中文/空格/重命名信息。UI 分开展示开始前 dirty、本任务补丁以及当前 Git 的外部/未知变化，不用最终 diff 猜测作者。非 Git 项目仍使用快照；父仓库不归属当前项目，子模块及嵌套 Git 内容拒绝编辑。

### 本机 API 与前端

| 方法与路径 | 用途及限制 |
| --- | --- |
| `GET /agent-runs/{run_id}/patches` | 任务补丁、起始 Git 和当前 Git；复用现有本机账号隔离。 |
| `GET /agent-runs/{run_id}/patches/{patch_id}/files/{change_id}` | 完整 diff 分页，返回预览摘要。 |
| `GET /agent-runs/{run_id}/patches/{patch_id}/facts` | 日志与当前文件事实核对。 |
| `POST /agent-runs/{run_id}/patches/{patch_id}/rollback-preview` | 输入独立 operation_id，无活动任务时生成回滚预览；同 ID 幂等。 |
| `POST /agent-runs/{run_id}/patches/{patch_id}/apply` | 输入 preview_sha256，仅消费任务结束后的 rollback 集合；普通补丁必须经过 Runtime 审批链。 |

新增能力位 `coding_patchsets_enabled`、`coding_repository_tools_version=2`、`coding_rg_available`；`coding_powershell_file_writes_enabled=false`。PowerShell 直接文件写 cmdlet 在所有权限档位关闭，保留登记的只读操作；项目脚本内部的间接写入不在此闭环内。

桌面使用已有 codingHttp、私有传输和全局通知确认；无新状态库、弹窗系统、接口服务或依赖。审批 DiffArtifact 可展开分文件完整 diff；任务面板展示历史日志和回滚入口。请求采用取消与序号保护，任务切换后迟到响应/确认不能污染新任务或对新任务发起写入。翻页失败保留当前位置，重试成功后才更新页历史。

S2 小窗口长任务因新增工具 schema 开销而触发预算回归，实际修复为递归删除无验证作用的 schema 标题/默认展示字段、精简工具说明，以及对 read v2 大正文采用 1200 字符投影和完整原始引用。未扩大窗口、删除用户约束或降低原长任务断言；原多次压缩、34 次模型请求测试通过。

## 验证结果

以下 Python 命令均在仓库根执行；前端命令工作目录为 `apps/desktop`。测试数据在新建 `.run/coding-agent-validation/` 下，禁止业务数据库与外网，不调用付费模型。

| 实际命令 | 观察结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all` | 235 passed、2 skipped、2 strict xfailed，69.43 秒。目录 `all-f5856d1c81dd4a5eb71ee98b467a1138`。最终工具版本标记和扫描取消补强后，重新运行下行相关 repository 套件。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite repository` | 最终 44 passed、1 skipped，11.80 秒。目录 `repository-61e9749e5a92461aaaa40d35dd330674`。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_legacy_validation.py` | 99 passed，10.79 秒。目录 `legacy-485fc313f3164836975c2fc5d43899f1`。不等于 MySQL/业务 API 验收。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite local` | 56 passed，13.52 秒。目录 `local-853172665d944af88dca3f010b9a8391`，随后已纳入上述 all。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite context` | 30 passed，7.80 秒。目录 `context-d92bac0cf0034d4bafacf2522a3547b9`；其后链接检查替身适配由上述 all 再次验证。 |
| `npm run test -- src/features/coding src/services/localExecutor.spec.ts src/services/privateTransport.spec.ts` | 33 个文件、211 passed，13.32 秒；此轮之后新增翻页失败重试测试，以下定向重跑覆盖最终组件。 |
| `npm run test -- src/features/coding/components/PatchPreview.spec.ts src/features/coding/components/PatchReviewPanel.spec.ts` | 最终 2 个文件、7 passed，2.21 秒。 |
| `npm run build` | 最终 vue-tsc 与 Vite 生产构建成功，Vite 16.02 秒；现有 antd chunk 814.47 kB，保留超 500 kB 提示，未修改拆包配置。 |
| `.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check` | `protocol codegen in sync: OK`。 |
| `.venv/Scripts/python.exe -B scripts/check_agent_v2_imports.py` | `agent_v2 dependency rules: OK`。 |
| 下方定向 Ruff 命令 | `All checks passed!`，包含新增和已修改 Python 文件。 |
| `git diff --check` | 无输出，退出码 0。 |

实际 Ruff 命令：

```powershell
$s3PythonFiles = @(git diff --name-only -- '*.py') + @(git ls-files --others --exclude-standard -- '*.py')
& .venv/Scripts/ruff.exe check @s3PythonFiles
```

边界验证包括完整多页续读、长单行与大文件尾部、UTF-8 BOM/CRLF、重复和失效游标、搜索取消、三处外部编辑时点、第二项文件故障、预览篡改与撤权、部分失败、移动回滚冲突、四处重启边界及意图/结果/终态日志异常。ASGI 测试走真实 read→propose→approve→apply→S1 verified→回滚 unknown，并验证跨账号不能访问、回滚重复提交无新增副作用。PY07 使用实际基线判定器先失败后成功，未把它计作模型质量成绩。

测试过程发现并修复：Windows Python 3.12 中 stat/fstat 的 ctime 采样语义不同导致误判；Git 基线子进程继承私有 stdin 导致 IPC 超时；S2 原链接替身仍 mock 旧 Path.is_symlink 导致测试不能覆盖新 lstat 检测；新增工具占用挤压 S2 小窗口。文件故障测试改为注入现行 patch 落盘边界，旧写入测试补齐读取前置条件，迁移测试真实模拟旧表结构，原保护断言保留。

最初受限环境的命名管道 `WinError 5` 和前端 esbuild `EPERM` 属于运行权限限制；按同一隔离入口在获准环境重跑通过。没有因这些失败弱化产品权限或跳过有效用例。文件故障使用注入的 `OSError("disk full")` 和日志异常，不声称真实磁盘满/断电演练通过。

两项 skip：当前 Windows 环境没有创建真实 symlink 的权限；ConPTY 环境探针未通过。真实 junction 与硬链接边界另有实际 I/O 测试通过，不能替代 symlink/ConPTY 结论。两项严格 xfail 为原 G10：可信项目脚本可间接写项目外、非 AppContainer 的 network_policy=none 不强制断网，留待 S4，未计作通过。

## 变更文件

以下仅列本轮实际新增/修改文件；无移动、删除、依赖或锁文件变更。

| 文件 | 变更 |
| --- | --- |
| `src/private_agent_core/patches.py` | 新增严格补丁输入、路径/操作校验及纯文本行编辑。 |
| `src/private_agent_local/repository.py` | 新增安全版本读取、目录/搜索分页和取消。 |
| `src/private_agent_local/patchsets.py` | 新增预览、逐项日志、落盘、事实与受保护回滚。 |
| `src/private_agent_local/runtime.py` | 工具与现行审批/规则/预算接入、根及 Git 基线。 |
| `src/private_agent_local/files.py` | 安全字节读取、reparse/身份核对、搜索子进程有界 stdin/stdout。 |
| `src/private_agent_local/store.py` | schema 5、升级备份、新表及 interrupted 恢复。 |
| `src/private_agent_local/policy.py` | 关闭 PowerShell 直接文件写，保护嵌套 Git。 |
| `src/private_agent_local/git_workspace.py` | 起始 dirty 清单、NUL 格式解析及私有 stdin 隔离。 |
| `src/private_agent_local/completion.py` | 多路径拒绝范围与持久补丁磁盘证据。 |
| `src/private_agent_local/context_manager.py` | 多目标规则、首次实际交付规则检查。 |
| `src/private_agent_local/context_history.py` | 读取版本元数据投影及补丁执行历史。 |
| `src/private_agent_local/app.py` | 本机补丁/回滚 API、能力位及回滚后的完成证据失效。 |
| `apps/desktop/src/features/coding/api/patches.ts` | 新增 typed API 和中文状态映射。 |
| `apps/desktop/src/features/coding/api/runs.ts` | 审批预览透传补丁元数据。 |
| `apps/desktop/src/features/coding/model/runContracts.ts` | 加性补丁预览类型。 |
| `apps/desktop/src/features/coding/components/PatchPreview.vue` | 新增完整分文件 diff 分页及错误重试。 |
| `apps/desktop/src/features/coding/components/PatchReviewPanel.vue` | 新增基线/日志/回滚预览与确认。 |
| `apps/desktop/src/features/coding/components/DiffArtifact.vue` | 在现行审批 diff 中接入完整预览。 |
| `apps/desktop/src/features/coding/components/CodingThreadWorkspace.vue` | 按能力位挂载任务补丁面板。 |
| `apps/desktop/src/features/coding/components/PatchPreview.spec.ts` | 新增分页、失败重试、摘要及取消回归。 |
| `apps/desktop/src/features/coding/components/PatchReviewPanel.spec.ts` | 新增 dirty 展示、回滚确认及跨任务保护回归。 |
| `scripts/run_coding_validation.py` | 增加 repository 套件并纳入 all。 |
| `tests/unit/test_local_file_ranges.py` | 新增范围/版本/编码/链接/别名 I/O 测试。 |
| `tests/unit/test_local_search_pagination.py` | 新增分页、ignore、rg 降级及取消测试。 |
| `tests/unit/test_local_patchsets.py` | 新增多文件、故障恢复、迁移、审批、S1、回滚和 PY07。 |
| `tests/coding_acceptance/test_baseline.py` | 旧取消/外部编辑测试补齐读取前置。 |
| `tests/unit/test_local_executor.py` | 旧写入拒绝测试补齐读取前置。 |
| `tests/unit/test_local_completion.py` | 虚假文件成功结果注入到现行落盘边界，保留未创建断言。 |
| `tests/unit/test_local_permissions.py` | 更新 PowerShell 写入口收缩契约断言。 |
| `tests/unit/test_local_context_history.py` | 旧 schema 3 迁移夹具与新备份名称适配。 |
| `tests/unit/test_local_store.py` | 旧 schema 2 迁移夹具适配。 |
| `tests/unit/test_local_instructions.py` | 链接替身适配实际 lstat 检测入口。 |
| `tests/coding_acceptance/README.md` | 更新 S3 复跑入口与证据边界。 |
| `docs/analysis/coding-agent-upgrade-20260908/README.md` | 更新阶段状态及后续 S4 边界。 |
| `docs/analysis/coding-agent-upgrade-20260908/s3-repository-and-patches.md` | 保留计划并链接实际验收。 |
| `docs/analysis/coding-agent-upgrade-20260908/s0-contract-decisions.md` | 追加 S3 ID、版本、存储与证据契约。 |
| `docs/analysis/coding-agent-upgrade-20260908/s3-validation-report.md` | 新增本验收报告。 |
| `docs/unified-desktop-runtime.md` | 同步当前 schema、工具行为及历史状态标记。 |
| `docs/context-design.md` | 同步 S3 大正文投影、多目标规则及 schema。 |
| `docs/testing-guide.md` | 增加 S3 验证入口。 |

## 项目记忆

已完整读取指定记忆 `docs/project-state.md`，并读取仓库入口、相关统一客户端说明、S0 契约、S2 验收与 S3 计划。指定记忆仍是 2026-08-31 的历史环境快照，其 `E:\Program\Agent`、旧 HEAD 和部分能力描述与本轮 F 盘/S2 基线不同；通过实际 Git status/log/diff、当前调用链及隔离测试确认，未把历史部署结果继承为本轮成功。

按项目入口“仅在用户明确要求新增或更新项目记忆时”约定，本次未改写 `docs/project-state.md`，未创建新记忆系统。耐久契约同步在现有阶段索引、契约决议、上下文、运行时与测试指南，并以本报告记录新证据；历史快照保留日期、范围和后续报告入口，当前实现说明中的 schema/工具限制已同步，避免不同文档把当前能力说成待实施。

## 风险、限制与假设

- 跨文件、SQLite 与文件系统没有事务；单项最终核对到 rename/unlink 之间仍有极窄外部竞态，句柄/身份检查不能等同平台原子 compare-and-swap。故障未知保留日志并停止，不承诺自动安全恢复。
- 支持 UTF-8 普通文件和本机支持排他硬链接/原子替换的文件系统；其他编码、二进制、链接、嵌套仓库、仅大小写重命名均拒绝。特殊 ACL、网络文件系统、非 Windows 和真实磁盘故障没有完成平台验收。
- 搜索与预览有明确上限；大量文件、复杂 ignore 且无 rg、超大 patch 会停止并要求缩小范围。内容和日志复用现有存储，没有新增自动清理策略。
- S4 的脚本间接写入与 OS 网络隔离问题仍在；ConPTY 未通过，不能声明完整终端能力。
- 没有真实模型调用、真实账号验收、完整桌面人工视觉验收、Tauri 发行安装包或升级/回退演练。Vue 组件测试和前端构建只证明对应层面的结果。

## 用户需执行的操作

本轮源码开发无需用户执行额外操作。复验可使用上方现成命令。若需要验证安装版、真实账号/模型或开始 S4，应作为后续明确任务进行；不要用不理解 schema 5 的旧客户端覆盖写入新数据库。
