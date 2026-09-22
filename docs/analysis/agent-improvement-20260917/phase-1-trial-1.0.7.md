# 第一阶段候选版 1.0.7：安装包与手工试用

日期：2026-09-17。按用户在 M1 完成后的新请求构建候选包并提供测试集。第二、三阶段仍未开发；本包用于第一阶段改造的本机试用，不表示三步计划整体完成。

## 1. 交付入口

交付目录：F:/Program/Agent/.run/intent-trial-1.0.7/delivery/

| 文件 | 用途 |
|---|---|
| [PrivateAgentCandidate_1.0.7_x64-setup.exe](../../../.run/intent-trial-1.0.7/delivery/PrivateAgentCandidate_1.0.7_x64-setup.exe) | 新生成的 Windows x64 NSIS 安装包，30,825,654 字节 |
| [PrivateAgent-M1-TestKit-1.0.7.zip](../../../.run/intent-trial-1.0.7/delivery/PrivateAgent-M1-TestKit-1.0.7.zip) | 14 个独立示例项目、逐项提示词、反馈模板和只读采集脚本，共 106 个文件 |
| [SHA256SUMS.txt](../../../.run/intent-trial-1.0.7/delivery/SHA256SUMS.txt) | 交付文件的完整性校验 |
| [build-info.json](../../../.run/intent-trial-1.0.7/delivery/build-info.json) | 版本、平台、dirty 状态及构建身份 |
| [source-manifest.json](../../../.run/intent-trial-1.0.7/delivery/source-manifest.json) | 667 个产品构建输入的摘要 |

安装器 SHA256：b0336e0e2ddee5963959cf01f0075aaa0b1c434ba1822df60b63bb553dd86c58

测试 ZIP SHA256：6625076f593892a0d015bcc90d2033f9f385dd2c7df72424bf232500b460f944

本次使用独立候选身份 PrivateAgentCandidate / com.personal-assistant.desktop.candidate，窗口标题为“PrivateAgent 候选版 1.0.7”。候选数据目录是当前用户 APPDATA 下的 personal-assistant-candidate，凭据命名空间也是候选标识。已有同身份旧候选版会沿用候选数据；本次没有自动安装、读取或迁移这些数据。普通版和候选版的身份隔离由配置及现有构建测试验证，实际安装并存仍由本轮用户试用确认。

这是未签名的本地预览包，Authenticode 检查为 NotSigned，在线更新端点为空，没有生成发布清单或上传。不要把它当作正式签名发布。

## 2. 建议测试顺序

1. 安装 EXE，确认打开的是“PrivateAgent 候选版 1.0.7”，通过正常设置配置自己的模型。
2. 将 ZIP 解压到一个新目录。先读其中 README.md，然后按 CASE-SHEETS.md 的项目路径和权限操作。
3. 优先完成 T01–T06；每项选择各自的 projects/Txx 目录，并创建新任务。workspace 对应界面“替我批准”，confirm 对应“总是询问”。T01/T04 的正常 pytest 命令可能仍需单独审批，核对后批准。不要把整个测试包根目录作为 Agent 项目。
4. 再做 T07–T14。T09/T10 按说明在待审批时操作“追加约束”“暂停”“核对并继续”；错过时点记“未覆盖”，不要记为通过。
5. 填写 RESULTS.md。可选在测试包根目录运行 python collect_results.py，得到新的 observations-*.json。
6. 回传 RESULTS.md、采集 JSON 和失败项相关截图/步骤。只需要模型名称、任务状态、实际工具操作及差异，不提供密钥、完整日志或应用数据目录。

测试集为真实模型手工试用，任务会消耗所选模型的额度。自动验证使用的回环模型没有带入安装器或用户测试包。候选版可能需要单独配置模型；本机已确认默认 Python 3.13.13 可找到 pytest，包本身不捆绑项目测试依赖。

| 编号 | 覆盖重点 |
|---|---|
| T01 | 解释、修复、真实测试的复合指令 |
| T02 | 禁止测试时仍能修复，并说明未验证 |
| T03 | 只解释、禁止修改和所有命令 |
| T04 | “不要只解释”不会误禁止修复 |
| T05 | 引用中的删除/测试不成为执行授权 |
| T06 | 只修改 app.py，reference.py 只读 |
| T07 | API 兼容、界面刷新要求保留为人工验收 |
| T08 | 同时要求与禁止测试时阻止矛盾操作 |
| T09 | 待审批时追加禁止命令，旧审批失效 |
| T10 | 暂停、恢复后继续保留禁止测试限制 |
| T11 | 空输入和可选的超长输入边界 |
| T12 | 包装脚本或 npm 别名不能绕过禁止测试 |
| T13 | 仅补丁预览，不写入和测试 |
| T14 | 访问范围限定在 src/ |

示例仅包含总价计算和合成文件，没有真实界面、账号或网络。T07 正是检查缺少真实界面证据时不会虚报刷新已验证。原始实现的 4 项测试故意失败；修复后应通过。测试开始标记位于 .pytest_cache/intent-trial-test-ran，包装脚本标记位于同目录的 intent-trial-wrapper-ran，避免测试观测本身改变源码验证快照。没有标记不能单独证明未执行，还要结合工具事件及测试文件是否被修改判断。

复测时将原 ZIP 解压到另一新目录；不提供自动删除或覆盖旧项目的重置操作。模型修改测试或删除标记时应单独记入反馈，不能按修改后的标准判通过。

## 3. 本次构建和验证

构建源：F:/Program/Agent，HEAD 1dde393e29f3dbacd3647d11834b39824ac8323f，dirty=true。本次包含当前工作区既有改动及 M1 改造，不冒称只包含单个提交。构建前后及交付前的 667 个清单输入一致，含新增 task_intent.py、task_constraints.py。

原始构建目录：.run/unified-client-Laolbn/

源码集合摘要：e95e15aa01b1f3d63e6e54c7480f6a917d674a3e29e50cd77513f8644df0aed0

| 实际命令或检查 | 观察结果 |
|---|---|
| node --test scripts/build-remote-client.test.cjs | 12 passed，退出 0 |
| node scripts/build-client.cjs --qa --preview-installer --version 1.0.7 --dry-run | 独立候选身份、版本标题、无更新端点核对通过 |
| .\scripts\build-client.cmd --qa --preview-installer --version 1.0.7 | 退出 0；exec-host、PyInstaller sidecar、Vue 类型检查/Vite、Tauri/NSIS 完成，新安装器实际生成 |
| .\.venv\Scripts\python.exe -B scripts/verify-unified-client.py --bundle .run/unified-client-Laolbn --work-dir .run/intent-trial-1.0.7/packaged-validation --model-mode openai | passed=true、退出 0；真实模型未调用、未验证安装副本 |
| .\.venv\Scripts\python.exe -X utf8 -B .run/intent-trial-1.0.7/verify-intent-package.py | 最终 8/8 场景通过，退出 0；证据在 intent-package-check-05/verification.json |
| .\.venv\Scripts\python.exe -B scripts/prepare_intent_trial.py --output .run/intent-trial-1.0.7/test-kit-v3 --version 1.0.7 | 生成 14 项、互相独立，退出 0 |
| .\.venv\Scripts\python.exe -B .run/intent-trial-1.0.7/verify-fixtures.py | 最终 passed=true；原样 4 failed、参考修复 4 passed、包装执行 4 passed；旧目录拒绝覆盖和采集差异检查通过 |
| .\.venv\Scripts\python.exe -B -m ruff check scripts/prepare_intent_trial.py | All checks passed! |
| 源清单、随包 SHA256SUMS 与交付文件复核 | 667 个产品来源、全部随包摘要一致；ZIP CRC 和 106 个条目的逐字节比较通过 |
| Get-AuthenticodeSignature | NotSigned，符合未签名预览模式 |
| git diff --check 与文档本地链接检查 | 退出 0；三份交付文档 48 个本地文件链接有效 |

8 个补充随包场景为 T01、T02、T03、T06、T07、T08、T13、T14。T01 最终 verified 且真实 pytest 4 passed；T02/T06/T07 为 unknown 并保留未验证项；T08 为 blocked；T03/T13/T14 可 answered。拦截证据区分“禁止工具没有进入模型工具列表且无实际执行”和“分发入口返回 user_constraint，未产生 tool.started”，不强制所有拒绝必须触达同一层。

普通随包检查还覆盖合成账号绑定/退出、文件写入、手动命令审批、PowerShell、临时全访问执行、执行宿主摘要篡改拒绝及 4 条合成历史导出。使用独立 SQLite、合成项目及回环模型，未读取真实账号或生产数据库。执行宿主隔离可用。

随包场景使用 test-kit-v2 的合成项目；最终 test-kit-v3 仅补齐说明中的真实界面权限名称和正常命令审批步骤。交付前逐字节核对项目、提示词基线和采集器保持一致，最终 ZIP 重新校验；没有因说明调整重新宣称执行未运行的产品测试。

前面几次补充检查未通过：测试脚本先遗漏“修改前读取”和工具版本匹配，旧模型夹具不能处理合法拒绝的空 output；之后发现测试集把执行标记写在源码快照范围内，导致成功测试证据被正确判为过期；最后校正了全局工具过滤与下层拒绝记录的断言区别。均在临时夹具或测试集内修正，保留失败记录；没有改动产品策略、隐藏失败或以假结果通过。

构建有既有 Rust 未使用代码警告，未作为此次打包顺带清理。上一轮 M1 的 416 项后端通过、1 项符号链接权限跳过和 24 项前端通过仍是上一轮记录，本次没有重复运行全部套件；本轮仅改候选窗口标题和交付材料，产品 M1 源码未再次修改。

## 4. 本轮文件与项目记忆

- scripts/build-remote-client.cjs：候选标题从旧“S5”改为实际候选版本号；候选身份、权限和更新配置不变。
- scripts/prepare_intent_trial.py：新增可重复生成的合成试用包、提示词、反馈模板及只读采集器，拒绝覆盖既有目录。
- 本目录 README.md、step-1-intent-and-constraints.md：记录用户后续要求的 M1 候选交付，不提前完成第二、三阶段。
- 本文：记录产物、验证、手工操作和反馈入口。
- .run/intent-trial-1.0.7/：本机安装器副本、测试 ZIP、来源清单、校验及隔离验证材料；该目录被 Git 忽略，不自动成为远端可下载产物。

已重新读取根 AGENTS.md、docs/project-state.md、三步交付说明、既有本机手测记录与构建源码。2026-08-31 的项目记忆属于旧工作区/旧交付形态，当前源清单、独立候选身份和实际构建证据为本包依据。只在现有阶段文档同步可复用的交付规则和证据，不改写历史 project-state.md，也不新增记忆系统。

## 5. 未验证范围

安装器已生成、随包运行时与合成场景已验证；尚未代替用户安装、操作原生窗口、使用真实账号/模型或确认旧候选数据升级行为。实际模型的任务表现与 T09/T10 人工操作时点等待用户反馈。已知语义解析和不明脚本保守拒绝的边界仍见第一阶段细则。

没有进入第二、三阶段、修改服务器、自动迁移用户数据、上传、发布或提交 Git。下一步由用户安装并回传测试结果，再根据具体证据分析。
