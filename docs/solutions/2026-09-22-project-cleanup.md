# 2026-09-22 项目目录清理与证据归档

## 基线与范围

本次按用户确认的方案清理缓存、保留开发环境；安装包仅保留最新完整一套；保留所有测试摘要、关键证据和历史说明。开始时分支为 `dev/1.0.0`，HEAD 为 `0ade0a7799ab73624ac55d9cccde24a54740bdb0`，Git 工作区干净。

执行前扫描到 725,959 个普通文件，共 61,173,145,314 字节。该统计是可访问文件的逻辑大小，不包含无法读取目录的内容，也不等于磁盘实际占用。与规划阶段相差一个 41 字节文件，按执行前基线处理。元数据扫描不读取环境文件、凭据或用户数据库正文。

本次保留全部正式测试：80 个 Python 文件、91 个 Vitest 文件、18 个 E2E 文件，以及 Node/Rust 测试、夹具、题集和视觉基线。清理前在现有隔离环境中收集到 2,087 个 Python 测试节点；收集不代表全部断言通过。

## 整理方式

- 通过逐文件清单区分保留、归档、删除和无法核实；删除前检查绝对路径、全部祖先的重解析属性、文件大小与修改时间。归档先核对源/目标摘要，再移除原件。
- 测试和构建摘要、历史报告、截图及协议证据归入 `.run/records/`，按原 `.run`、`.tmp`、`dist` 层级保留来源。失败、跳过和超时记录不因清理消失。
- 删除可重建编译缓存、隔离测试工作区、复制的工具链、旧版本和重复安装包、退役服务器二进制；用途、敏感性和复现价值未充分确认的内容保留。
- 保留 `.venv`、前端实际依赖、`.tools`、数据、配置、Git 元数据及源码运行所需的 `apps/exec-host/target/release/exec-host.exe`。不跟随重解析点，不修改 ACL，不清理 worktree 登记。
- 根目录设计验收报告归入[界面验收记录](2026-09-22-ui-design-qa.md)，原始字节另存本机记录。补充目录、脚本、测试、专题和证据索引，替换桌面端 README 模板，修正文档导航。

当前目录职责见[目录说明](../repository-layout.md)，原始结果入口见[本机记录索引](../../.run/records/README.md)。历史命令及当时的状态保留原文，查找结果使用来源映射，不能把旧验收数字写成本次成绩。

## 实际清理结果

| 项目 | 实际结果 |
| --- | --- |
| 删除文件 | 514,815 个，56,436,554,361 字节（约 56.44 GB）；含验证后清除的 38 个合成文件和前端产物 |
| 归档文件 | 14,758 个，254,825,122 字节（约 254.83 MB） |
| 归档构成 | 14,753 份既有记录、4 份本次打包测试摘要、1 份根目录设计报告原件 |
| 移除空目录 | 150,504 个，含验证后清除的 27 个空目录 |
| 可访问文件逻辑大小 | 从约 61.17 GB 降至约 4.90 GB，净减少约 56.28 GB；最终逐根目录统计见 `final-scan.json` |
| 正式文件 | 866 个原跟踪文件均保留；16 份原文档修改、8 份新文档，业务源码、正式测试、夹具、6 张视觉基线、5 份锁文件及独立执行宿主摘要不变 |
| 最新完整包 | 只保留 1.0.20 的安装器、桌面程序、本机执行器、执行宿主及配套说明；另保留源码运行所需的独立宿主 |

GB、MB 采用十进制。删除字节数含可重建产物；净减少量还计入新增完整包副本、文档和审计材料，两者不是同一指标。逻辑大小不等于 NTFS 实际释放空间，不包含拒绝访问的目录内容。

归档前核对源与目标 SHA-256，完成后独立复核全部 14,753 份既有记录；另外复核根报告及本次新增的 4 份测试摘要。基线中 2,496 份标准名称的测试或构建摘要全部可追溯，其中 2,493 份已归档，3 份疑似含敏感测试内容的摘要原位保留。首轮登记的 565 个去重引用已逐项核对：412 个仍在原位、140 个有归档位置、13 个旧安装器或重复副本按保留策略清理；没有丢失需要保留的引用证据。最终全量 Markdown 链接复核另补充归档 20 份被复合链接引用的结果、评审及说明，详情见 `link-supplement.json`。

| 来源 | 新位置或查阅方式 |
| --- | --- |
| `.run/<路径>` | `.run/records/run/<路径>`，仅适用于成功归档条目 |
| `.tmp/<路径>` | `.run/records/tmp/<路径>`，仅适用于成功归档条目 |
| `dist/<旧版本记录>` | `.run/records/dist/<旧版本记录>` |
| 原根目录 `design-qa.md` | 说明正文进入本目录；原始字节在 `.run/records/root/design-qa-20260922.md` |
| 全部逐文件映射 | [archive-map-all.json](../../.run/records/cleanup-20260922/archive-map-all.json) |
| 删除依据及成功/保留结果 | [审计索引](../../.run/records/cleanup-20260922/README.md)中的计划清单和执行事件 |
| 访问、链接和敏感性保留例外 | [retained-exceptions.json](../../.run/records/cleanup-20260922/retained-exceptions.json) |

用途仍待确认的 68,549 个文件（约 3.44 GB）原位保留，其中包括旧复现工作区、测试 ZIP 和可能涉及私密配置的内容。它们在四类清单中仍标为“无法核实”，不能为了达到空间目标而视为可删除。另有 4 份归档候选因敏感内容模式触发保留，具体路径仅记录在例外清单，不复制其正文。

## 保留的候选包

最新完整包位于 `dist/PrivateAgentCandidate-1.0.20/`，源自 `.run/unified-client-zPbEDD/`。安装器为 `PrivateAgentCandidate_1.0.20_x64-setup.exe`，42,970,264 字节，SHA-256 为 `b2665a518b1c8a982eff24aee77111f102f86bf4c48cf44104738f06ae1c7b52`。

同目录保留桌面程序、本机执行器、执行宿主、宿主摘要、四个可执行文件摘要、源码清单、构建信息、原验证说明及发布清单。原构建提交 `1dde393e29f3dbacd3647d11834b39824ac8323f` 和 `dirty=true` 保持不变；没有重新打包或把历史构建改写为干净构建。

本次已核验 410 个构建输入及四个可执行产物摘要。候选包未签名、无更新端点；没有执行安装、升级、发布或真实模型调用。

## 实际验证

命令在仓库根执行，使用已有依赖；原始输出保存在 `.run/records/cleanup-20260922/`。

| 命令 | 实际结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B -X utf8 .run/records/cleanup-20260922/verify.py collect before` | 80 个文件、2,087 个节点，退出码 0 |
| `.venv/Scripts/python.exe -B -X utf8 .run/records/cleanup-20260922/verify.py collect after` | 80 个文件、2,087 个节点，清理前后清单完全一致，无新增或缺失 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite desktop-packaging` | 24 passed |
| `.venv/Scripts/python.exe -B scripts/protocol_codegen.py --check` | `protocol codegen in sync: OK` |
| `node --test scripts/build-remote-client.test.cjs` | 普通本机权限复验：12 passed |
| `npm run e2e --prefix apps/desktop -- --list` | 成功收集 18 个文件、77 项用例，未执行浏览器断言 |
| `npm run build --prefix apps/desktop` | 普通本机权限复验：类型检查和 Vite 生产构建通过；保留大于 500 kB 的分包警告 |
| `.venv/Scripts/python.exe -B -X utf8 .run/records/cleanup-20260922/verify.py integrity` | 867 项保护基线中仅预期文档变化；410 个构建输入、4 个产物摘要一致 |
| `.venv/Scripts/python.exe -B -X utf8 .run/records/cleanup-20260922/verify.py links` | 239 份正式 Markdown 与 5 份本机维护入口共 244 份，本地链接和图片目标无缺失 |
| `.venv/Scripts/python.exe -B -X utf8 .run/records/cleanup-20260922/finalize.py archive-audit` | 14,753 份既有归档摘要一致，565 个原引用去向明确，worktree 登记未变 |
| `.venv/Scripts/python.exe -B -X utf8 .run/records/cleanup-20260922/finalize.py body-paths` | 检查 69 处正文中的本机绝对路径，历史命令与示例保持原文 |
| `.venv/Scripts/python.exe -B -X utf8 .run/records/cleanup-20260922/finalize.py scan` | 不跟随重解析点的全目录复扫；可执行项目产物仅余完整包中的 4 份及独立宿主 |
| `git diff --check` | 通过 |

Node 测试与 Vite 首次在受限工具环境报 `spawn EPERM`。两次失败输出独立保留，后续获准普通本机权限复验通过，没有修改测试、构建配置或依赖来绕过失败。

文件清理结束后又在最终环境执行打包、协议、Node、E2E 收集和前端构建检查，表中通过数来自最终一轮，不累加重复验证。原始输出与退出码见审计目录中的 `*-final.log`、`*-final.json`。本次验证产生的 4 份摘要归档后，合成证书、假安装器及 Vite 输出已清除。

链接检查覆盖正式维护文档与新增本机入口。原始历史报告保持归档字节，其内部旧命令、已退役路径及示例输出目录通过映射和适用日期说明，不据此声称历史命令可在当前目录直接执行。

## 文档变更清单

下表仅列本次实际新增、修改或移动的正式文档。大量本机文件的逐文件处置见 `.run/records/cleanup-20260922/plan.jsonl.gz`、`apply-events.jsonl.gz` 和来源映射；这些文件继续由 Git 忽略。

| 文件 | 变更 |
| --- | --- |
| [README.md](../../README.md) | 增加目录、候选包和证据入口 |
| [apps/desktop/README.md](../../apps/desktop/README.md) | 替换脚手架模板，补充桌面目录、开发和构建说明 |
| [docs/README.md](../README.md) | 补齐当前文档导航和归档规则 |
| [docs/testing-guide.md](../testing-guide.md) | 说明历史结果映射、保留环境和复跑边界 |
| [docs/repository-layout.md](../repository-layout.md) | 新增目录职责和文件保留规则 |
| [scripts/README.md](../../scripts/README.md) | 新增现有脚本入口索引 |
| [tests/README.md](../../tests/README.md) | 新增正式测试职责和隔离执行入口 |
| [docs/analysis/README.md](../analysis/README.md) | 新增专题索引 |
| [docs/solutions/README.md](README.md) | 新增带日期的交付索引 |
| [docs/evidence/README.md](../evidence/README.md) | 新增证据索引 |
| [docs/solutions/2026-09-22-project-cleanup.md](2026-09-22-project-cleanup.md) | 新增本次处置依据和实际结果 |
| [docs/solutions/2026-09-22-ui-design-qa.md](2026-09-22-ui-design-qa.md) | 从根目录 `design-qa.md` 归档，添加适用日期、截图映射并修正相对链接 |
| [docs/archive/design-artifacts/README.md](../archive/design-artifacts/README.md) | 更新既有设计归档入口 |
| [docs/releases/v0.8.0/v0.8.0-w0-ui-freeze-20260822.md](../releases/v0.8.0/v0.8.0-w0-ui-freeze-20260822.md) | 更新历史 QA 链接和路径维护日期 |
| [phase-1-trial-1.0.7.md](../analysis/agent-improvement-20260917/phase-1-trial-1.0.7.md) | 更新验收记录位置，标明旧安装包已清理 |
| [phase-1-trial-1.0.8.md](../analysis/agent-improvement-20260917/phase-1-trial-1.0.8.md) | 更新验收记录位置，标明旧安装包已清理 |
| [phase-1-trial-1.0.9.md](../analysis/agent-improvement-20260917/phase-1-trial-1.0.9.md) | 更新验收记录位置，标明旧安装包已清理 |
| [phase-1-trial-1.0.10.md](../analysis/agent-improvement-20260917/phase-1-trial-1.0.10.md) | 更新验收记录位置，标明旧安装包已清理 |
| [phase-1-trial-1.0.11.md](../analysis/agent-improvement-20260917/phase-1-trial-1.0.11.md) | 更新验收记录位置，标明旧安装包已清理 |
| [phase-1-trial-1.0.12.md](../analysis/agent-improvement-20260917/phase-1-trial-1.0.12.md) | 更新验收记录位置，标明旧安装包已清理 |
| [phase-1-trial-1.0.13.md](../analysis/agent-improvement-20260917/phase-1-trial-1.0.13.md) | 更新验收记录位置，标明旧安装包已清理 |
| [s1-validation-report.md](../analysis/coding-agent-upgrade-20260908/s1-validation-report.md) | 更新隔离测试摘要链接 |
| [s6-b-c-final-candidate-readiness.md](../analysis/coding-agent-upgrade-20260908/s6-b-c-final-candidate-readiness.md) | 更新构建身份、云评审及重试证据链接 |
| [s6-phase-b-local-learning-validation.md](../analysis/coding-agent-upgrade-20260908/s6-phase-b-local-learning-validation.md) | 更新题集、预检及 control 验收记录链接 |

另外新增本机记录索引 `.run/records/README.md`、本次审计工具和输出，以及完整候选包的 `README.md`。原根目录设计报告字节、历史记录及构建来源均有独立摘要，不用新文档覆盖原始证据。

## 项目记忆与限制

已完整读取 `AGENTS.md`、`docs/project-state.md`，并核对本机化说明、前次清理记录、测试指南和实际源码入口。状态记忆的 2026-09-19 及更早内容是历史快照；当前本机架构以 9 月 20 日之后的代码和文档为准。按仓库入口约定，不改写其历史日期、业务状态或测试结论；本次目录职责和保留规则同步到 README、文档中心、测试指南和本记录。

`docs/project-state.md` 的摘要与清理前一致，未发现因本次移动而需要修正的记忆链接。历史架构描述与当前源码的区别已在文档中心和本机化说明中标明适用日期，没有把历史状态改写为当前完成状态，也没有另建项目记忆系统。

扫描遇到 158 处访问受限和 328 个重解析点，均登记而不跨越权限或链接边界。另有一条指向已不存在测试位置的 Git worktree 登记，未修改 Git 元数据。未知材料与疑似敏感配置保留原位，不能宣称所有本机目录均已清空。

本次不是全量业务回归，没有执行完整 Python 断言、全部前端单元测试、浏览器断言、原生安装升级、签名或付费模型验收。构建缓存被清理后首次构建可能较慢。
