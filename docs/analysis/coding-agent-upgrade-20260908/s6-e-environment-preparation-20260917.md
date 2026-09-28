# 历史存档：已取消的 E 环境与旧数据准备

> **已取消（2026-09-17）：用户将目标限定为当前电脑上的 Agent 学习使用，明确取消 E、F 阶段。** 本页停止执行与追加材料，保留已有准备记录；用户无需启用 Sandbox、创建虚拟机、寻找旧安装包或演练升级回退。下文是取消前的历史方案，不是待办清单，也不表示 E 已通过。当前范围见 [本机学习计划](s6-follow-up-development-plan.md#1-目标与完成边界)。

历史记录日期：2026-09-17。在取消决定之前，用户确认没有现成 Windows 虚拟机、快照和旧数据，并要求准备可行方案；下文记录当时已经生成的材料和原拟执行步骤。原始材料未删除，未启动虚拟机或执行 E/F。最新学习使用状态见 [当前记录第 36 节](s6-pre-e-readiness.md#36-本机学习范围调整ef-阶段取消)。

## 1. 已准备材料

证据根目录为 `F:\Program\Agent\.run\s6-gap-closeout-20260917`，下文记作 `G/`。这些文件是本机忽略目录中的实验材料，不是已发布产品。

| 材料 | 位置与性质 |
| --- | --- |
| 当前源码候选 | `G/build-01/candidate/`，标准产品标识 `com.personal-assistant.desktop`，1.0.0、x64、schema 7、未签名 portable；不是安装包。源码汇总 `a43891d39598de77935a164fff9955d7698d5c58dc023af8fbcc3b213a1ef4b4`。 |
| 独立旧数据 | `G/upgrade-materials/schema-{3,4,5,6,7}/data/`，每版各 `empty`、`owner-a`、`owner-b` 三份，共 15 份；所有数据均为合成。 |
| 历史来源清单 | 每版 `origin.json` 记录完整 Git commit、历史 Python 源码摘要、生成命令与退出码；`data/data-manifest.json` 记录 schema、表行数、表内容摘要、文件摘要和完整性结果。 |
| 干净环境介质 | `G/e-environment/media/`，仅含候选、合成数据和清单；没有仓库源码、`.venv`、真实账号数据或 `readiness-probe.json`。 |
| 可选 Sandbox 冒烟入口 | `G/e-environment/optional-smoke.wsb`，仅生成并校验 XML，未启动。 |
| 待填写回执 | `G/e-environment/execution-record-template.json`，默认 `not_run` / `e_accepted=false`；不能把模板当实测结果。 |

历史存储实现分别来自 schema 3：`ef54b9c`、4：`258544a`、5：`a2208a6`、6：`d0250ee`、7：`25ba4d3`，完整提交号见各 `origin.json`。每份数据由对应版本的 `Store` 初始化，未直接修改 `PRAGMA user_version` 伪造旧 schema。非空数据包括中文及空格路径、项目、会话、超过 32 KiB 的长消息、已失败运行、待审批运行和合成审批；不含执行命令或真实副作用。

15 份起点均实测 `PRAGMA integrity_check=ok` 且 schema 与声明相符。它们由本地历史源码生成，**尚未与任何已发布旧安装包建立对应关系**。原始 `data/` 作为只读起点保存；每次迁移必须使用新副本，连同同目录 `artifacts/` 一起复制。

## 2. 推荐方案：独立 Windows 虚拟机与快照

完整 E 使用可保存快照的独立虚拟机。目标首先限定为已明确的 Windows 11 Pro 25H2 / x64，不据此宣称覆盖其他系统。建议分配 4 vCPU、8 GiB 内存、80 GiB 可扩展磁盘；这是预设实验配置，不是已验证最低硬件要求。

1. 使用合法来源的 Windows 安装介质建立虚拟机；虚拟化软件采用已有可用工具。尚未安装或启用工具时，由用户选择并完成相应管理员操作。本轮没有启用 Hyper-V、调整 BIOS、修改系统安全设置或下载系统镜像。
2. 更新到拟支持的明确系统构建号。建立专用本地标准用户 `EStandard`，用 `whoami /groups` 记录实际组身份；管理员账户仅用于系统准备。不要用生产账号或复制宿主用户配置。
3. 安装并记录产品所需 WebView2 运行时及版本；不安装 Python、Node、Git、Rust 或项目依赖。若运行时缺失也是声明支持的安装场景，另从缺失状态验证安装包的处理，不能靠预装绕过该检查。
4. 禁用宿主用户目录共享、剪贴板及不必要的网络；只导入 `media/`。完整 E 中需要模型行为时使用单独的本机受控替身方案，不调用付费供应商；替身的部署、可达性和隔离另记，不把有开发依赖的宿主当干净虚拟机。
5. 在安装产品前创建 `E0-clean-standard-user` 快照，记录快照 ID、系统构建、权限、WebView2 版本和介质清单摘要。快照名称是建议值，实际 ID 以工具回执为准。
6. 从同一 E0 分别建立干净安装、旧版升级、回退三个实验分支。每个分支使用独立数据副本，按下表记录原始证据。

| 分支 | 要执行的检查 | 通过所需证据 |
| --- | --- | --- |
| 干净安装 | 真实安装包安装到中文及空格路径；普通用户首次打开、缺少开发工具时的明确错误、正常关闭、重开、系统重启后再开。 | 安装包 SHA256/标识/版本、安装与进程加载路径、退出状态、截图及结构化日志；不能用 portable 运行替代安装成功。 |
| 独立数据升级 | 每个 schema 的三份新副本迁移；核对项目/会话/长消息、审批、事件顺序及副作用状态，再关闭和重开。 | 起点及迁移后清单、备份摘要、schema、SQLite 完整性、字段级差异；待审批运行按重启恢复契约转为失败/中断并取消审批，不要求错误地保留“运行中”。 |
| 安全回退 | 在独立快照中恢复旧版安装和匹配的升级前数据库及 `artifacts/`；验证旧版可读。再单独检查旧版面对更高 schema 时拒绝写入。 | 回退前后包/数据来源及摘要；拒绝路径前后逻辑内容核对。不要把降级程序直接写入升级后数据库作为回退方案。 |
| 版本组合 | 明确安装器、桌面、sidecar、exec-host 与协议组合；检验不兼容组合的失败提示。 | 实际加载副本、组件摘要、错误码与未执行副作用证据，不以源码存在替代运行证据。 |

若来源明确的旧安装包仍不可得，可先完成合成数据迁移预演；这项结果只能称“历史 schema 兼容性预演”。历史源码重建包也只能作为明确标注的实验旧包，不能冒充已发布安装包。

## 3. 可选 Sandbox：仅做一次性干净运行冒烟

已生成的 `.wsb` 关闭网络、剪贴板、音视频输入和打印重定向；只读映射 `media/` 到 `C:\E Media`，把空的专用 `results/` 映射到 `C:\E Results` 以保存回执。没有自动启动命令，避免双击后立即安装或运行候选。配置项依据 [Microsoft Windows Sandbox 配置文档](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file)。

在用户已经准备并启用 Sandbox 后，才可打开 `G/e-environment/optional-smoke.wsb`。把只读介质复制到 Sandbox 内的 `C:\E 测试\候选 1.0.0` 后再运行；候选需要写入临时状态，不能直接把只读映射目录当工作目录。先核对介质摘要与进程实际加载路径；结果仅写入专用结果目录。宿主的整个项目、用户目录和 `.venv` 不得映射进去。

Sandbox 使用与宿主相关的系统环境，关闭后会丢弃内部状态；它不能替代本方案的持久快照、标准用户权限及完整升级回退分支。不要仅因窗口处于 Sandbox 内就把 `standard_user_verified` 填为 true。相关行为以 [Microsoft Sandbox 说明](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-overview) 为依据。

## 4. 尚未具备的条件与停止边界

- 没有已运行并取证的干净虚拟机或标准用户快照。本轮只准备材料和方案。
- 没有与这些历史数据来源匹配的标准产品旧安装包。已有 `PrivateAgentCandidate_1.0.0_x64-setup.exe` 属于 QA 候选标识 `com.personal-assistant.desktop.candidate`，不能直接充当标准产品升级起点。
- 当前构建为 portable 且未签名；后续真实安装组合需要独立生成和审核匹配安装包，不能把本页介质视为发布授权。
- 工程准入仍以审查页的当前测试、原生场景与异常状态为准。本页不放宽这些门禁，也不重新要求用户提供真实数据或凭据。

本轮实际执行：`prepare_upgrade_materials.py`（五版均 exit 0），`prepare_e_bundle.py`（exit 0，验证全部介质文件摘要、15 份数据库及 `.wsb` XML）。原始脚本、命令输出及结果保存在 G/。没有启动虚拟机、安装产品、执行 E/F、修改生产数据或发布远端资源。
