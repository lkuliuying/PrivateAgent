# 隔离本机 Coding / 云 API 联调

日期：2026-09-15。适用于个人学习时使用隔离本机客户端直连云 API。用户已确认自建服务器修复，本次继续沿用已配置的本机联调入口。

本轮已完成配置和真实联调：`probe-03f47eff5f7b4515a159047d2862a248` 的公开 `PY01` 为 `completed / verified`，实际修改、Agent 内测试、外置功能判定及预算核对通过。无需再次初始化或重复云调用。最新证据见 [候选冻结与本机验证](s6-final-candidate-local-validation.md)；此前失败及修复保留在 [交接记录第 9 节](s6-b-c-final-candidate-readiness.md#9-验证命令超时条件的修复与同范围复验)。

入口使用当前本机 Agent 和云 API 适配器。临时账号服务只在随机的 127.0.0.1 端口提供测试身份，模型请求由 Agent 直接发给配置的供应商。工具仍运行在无网络的 Windows AppContainer 内，沿用文件修改、命令批准和证据账本。

## 1. 填写非敏感配置

在仓库根目录的 PowerShell 中使用下列命令。不要在 Codex 聊天、JSON 或命令参数中填 API Key。

    Set-Location F:\Program\Agent
    .venv/Scripts/python.exe -B scripts/run_coding_local_probe.py init

配置生成到 `.run/coding-local-probe.json`。本次准备已经生成此文件，无需再次初始化；初始化遇到已有文件会停止，不覆盖内容。可用 `--config <本机路径>` 指定另一份配置。

必须填写：

| 字段 | 填写内容 |
| --- | --- |
| `provider.protocol` | `openai` 表示 OpenAI 兼容 Chat Completions；`claude` 表示 Anthropic Messages。当前入口不支持 Responses API。 |
| `provider.endpoint` | 云平台的 HTTPS Base URL，不含用户名、密码、密钥、查询参数或片段。按平台文档填写基础地址，不追加 `/chat/completions` 或 `/messages`，不要保留末尾的 `/`。 |
| `model` | 平台实际提供的模型 ID。 |
| `context_tokens` | 模型声明的上下文容量；模板中的 32768 只是初始值。 |
| `parameters.llm_context_length` | 本次使用的上下文长度，不得大于上述容量。 |
| `supports_streaming` | 支持流式响应填 `true`，否则填 `false`；按声明选择，不在失败后悄悄切换。 |

其余参数请核对：温度默认 0.7、最大输出 2048、自动压缩开启、知识库关闭。`model_version` 默认 `null`，表示不可变版本未知；当前运行时没有供应商版本证明。`reasoning_effort` 默认 `null`，不要为不支持该参数的模型随意填写。

`provider.id` 只是本次隔离目录内的标识，可保留 `local-probe`。不需要服务器 URL、账号密码、会话令牌、旧客户端目录、内部 profile ID 或系统凭据引用。

## 2. 核对任务和预算

初始模板固定为公开题 `PY01` 一次，单次与整场上限均为：

| 项目 | 初始上限 |
| --- | ---: |
| 模型请求 | 8 |
| 工具调用 | 12 |
| 活动时间 | 60 秒 |
| token | 10000 |
| 美元费用 | 未知，`null` |

`tasks` 最多可指定 3 个现有公开任务，每题只运行一次；失败不会自动扩大任务集。需要增加额度时，修改对应单次和整场字段，再重新检查。整场预算可提前阻止后续题目启动。

请求数和工具数沿用运行时限制；活动时间由运行时观察。token 按已知用量结算，缺失用量会阻止继续消费，首个或在途响应仍可能超过软预算。当前入口不含模型价格表，因此不接受美元限额；如需账单硬上限，请在供应商控制台设置。这里的初始数值不是费用估算或自动调用授权。

    .venv/Scripts/python.exe -B scripts/run_coding_local_probe.py check

`check` 只读配置和公开题清单，显示配置 SHA256、端点、模型、任务及预算，不输入密钥、不连接供应商。空占位值、未知字段和无效预算会被拒绝。

当前复验使用 `.run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/retry-model.json`，已由用户实际运行：`deepseek-flash`、`PY01` 一次、最多 12 次模型请求、20 次工具调用、100000 tokens、60 秒活动时间，费用未知。本轮没有增加预算。该文件 SHA256 为 `394fd3d72bd12f672f14bc46ae924805d5550396a0e35db6d28fbe87ad8af157`；以上初始模板数值保留作初始化说明。

    .venv/Scripts/python.exe -B scripts/run_coding_local_probe.py check --config .run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/retry-model.json

## 3. 本机预检

    .venv/Scripts/python.exe -B scripts/run_coding_local_probe.py preflight

在本机 PowerShell 的隐藏输入提示中粘贴本次专用 API Key。输入不会回显，也不会保存到配置、日志、命令参数或 Windows 凭据库；每次重新启动需再次输入。入口拒绝管道输入及无法隐藏输入的终端。

预检启动隔离 IPC，验证模型配置交接、冻结和 AppContainer 条件。它不调用推理、不获取模型列表，也不验证云平台是否接受这把 Key。预检中的 `credential_state=ready` 仅代表进程已持有凭据。

默认从当前源码启动 Agent。若需核对某份配套构建，可在预检和联调命令后都添加：

    --bundle F:\Program\Agent\.run\s6-patch-feedback-f6b09996597d484298ee16e99614deb0\bundle

此路径是本机现有 9 月 15 日修复构建，跨机器不保证存在。运行器核对源码清单与 sidecar/宿主摘要；不一致时停止。旧安装的版本号相同并不能替代摘要核对。旧 `s6-phase-d-*/bundle-rechecked` 对应补丁参数反馈修复前的来源，当前复验使用上面的配套构建。

## 4. 实际云 API / Coding 联调

用户已在仓库根目录成功执行以下完整命令，沿用原配置与构建；本节保留为复现参考，当前无需重复执行：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_local_probe.py probe `
  --config .run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/retry-model.json `
  --bundle .run/s6-patch-feedback-f6b09996597d484298ee16e99614deb0/bundle `
  --authorize-model-calls
```

该命令再次显示范围，随后隐藏输入 Key，完成预检后才启动调用。缺少授权参数时在读取凭据之前停止。`Ctrl+C` 可取消；运行器会尝试关闭所属 IPC 进程和临时账号服务，未确认完成的尝试保留失败记录。

API Key 通过现有启动注入通道传入专属子进程内存，子进程入口随即移除该环境字段，工具不能继承它；父进程的环境变量不变。进程结束时释放引用，不承诺语言运行时对历史内存副本进行密码学擦除。不要将真实 Key 用于自动化测试。

运行器会把命令审批条件直接写入模型任务：`argv` 严格按题面验证命令，`cwd="."`、`retention="run"`、`execution_mode="restricted"`、`network_policy="none"`，`timeout_ms` 大于 0 且不超过 60000。若命令仍在运行，模型需要用 `read_execution` 等待终态。用户不需要手工代跑题内测试；超范围请求继续拒绝，旧运行的拒绝记录不会被重放或改写。

## 5. 查看结果和边界

每次预检/联调生成新的 `.run/coding-local-probe/preflight-*` 或 `probe-*` 目录，保留：

- `manifest.json`：配置摘要、临时身份来源、源码/产物身份、预检及整场预算。
- `attempts.jsonl`、`starts.jsonl`：逐次启动、用量、终态及失败分类。
- `events/`、`artifacts/`：工具事件、批准关联、实际文件差异、验证结果和 IPC 进程身份。
- `metrics.json`、`report.md`：汇总与尚未完成的验收边界。

所有业务数据和临时模型元数据均在新建目录中。联调入口不读取已有客户端设置、生产数据库或 Windows 系统凭据。配置与元数据不含 Key，临时账号会话也不进入报告。

证据明确标识 `account_mode=isolated_local_test`，不能据此宣称真实服务器账号、原生桌面或最终候选验收通过。模拟供应商测试只证明执行链；真实云兼容性、模型质量和费用须以第 4 步的实际结果为准。B 的个人学习验收已完成，独立验收材料不再是本次联调前置条件。

命令执行结束不等于 C 通过。此前 `probe-162387237229424f84d7f0aa21d91a89` 因请求 300000 毫秒超出 60000 毫秒审批范围，Agent 内测试未执行；该失败记录保留。补齐任务中的超时条件后，最新 `probe-03f47eff5f7b4515a159047d2862a248` 已核对为 `completed / verified`：只修改允许文件，Agent 内 `python -m pytest` 退出 0，外置功能、范围、隔离和预算均通过。实际为 10 次模型请求、11 次工具调用、65401 tokens、13.187 秒活动时间；费用及不可变模型版本未知。本次公开单题个人学习联调通过，不能据此宣称完整模型质量、独立验收或原生桌面性能通过。后续使用同一组二进制进行候选冻结及本机取证，详见 [验证报告](s6-final-candidate-local-validation.md)。

## 自动化回归

    .venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite local-probe
    .venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite model-evaluation

自动化回归仅使用合成 Key 和受控供应商替身。完整 Coding 测试需要能启动 Windows IPC 宿主及 AppContainer 的本机权限；受限工具沙箱若返回 WinError 5，应按权限限制处理，不能把未启动的实验算作通过。

## 2026-09-15 准备验证结果

| 实际执行 | 观察结果 |
| --- | --- |
| `.venv/Scripts/python.exe -B scripts/run_coding_local_probe.py init` | 创建非敏感配置成功。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_local_probe.py check` | 空地址和空模型按预期拒绝，Python 退出 2；没有读取 Key。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite local-probe`，首次 | 41 passed / 1 failed；失败发生于既有隔离预检的临时租约读取，出现 PermissionError，模型任务未启动。 |
| 同一命令，修正租约读取边界后 | 47 passed，145.68 秒；包括正常 Coding、错误 Key、请求耗尽、配置冻结、凭据未落盘、临时服务回收及新增重读边界。证据目录 `.run/coding-agent-validation/local-probe-3181cd2f08c34097863481d564aa6431`。 |
| `.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite model-evaluation` | 128 passed，103.87 秒。证据目录 `.run/coding-agent-validation/model-evaluation-457e5ccd7f554458b7d41715a61e08da`。 |
| `.venv/Scripts/python.exe -B .run/local-probe-preparation-e65424f367184921a81b2c6a906de926/bundle_smoke.py` | 当前配套构建的模拟 `PY01` 通过；414 项源码匹配，实际 sidecar/执行宿主和 AppContainer 通过，5 次请求、600 个合成 token，费用未知。 |
| 下列定向 Ruff 命令及 `git diff --check` | 通过；首次发现的新导入排序和未使用导入已修正。 |

    .venv/Scripts/python.exe -B -m ruff check scripts/coding_acceptance_local.py scripts/coding_acceptance_models.py scripts/coding_acceptance_transport.py scripts/coding_acceptance_evidence.py scripts/coding_acceptance_isolation.py scripts/run_coding_acceptance.py scripts/run_coding_local_probe.py scripts/run_coding_validation.py tests/coding_acceptance/test_s6_local_probe.py

模型评测回归使用已有 Node，实际 PowerShell 包装为：

    $probeOriginalPath = $env:PATH
    try {
        $env:PATH = 'C:\ProgramSoftware\nodejs;' + $probeOriginalPath
        .venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite model-evaluation
        $probeTestExit = $LASTEXITCODE
    } finally {
        $env:PATH = $probeOriginalPath
    }
    exit $probeTestExit

上述 IPC/AppContainer 测试均经工具审批在普通本机权限下执行，没有安装依赖。首次租约修复针对 Windows 5/32/33 访问冲突进行最多 1 秒的重读；本日后续复验补充了 Windows 仅返回 `errno=13`、不带 `winerror` 的同类错误。持续拒绝访问仍失败，审批与授权目录的判定条件保持原样。后续失败与修复结果见 [交接记录第 9 节](s6-b-c-final-candidate-readiness.md#9-验证命令超时条件的修复与同范围复验)。

构建验证的独立摘要为 `.run/local-probe-preparation-e65424f367184921a81b2c6a906de926/bundle-smoke-summary.json`，原始账本位于同目录 `bundle-smoke/probe-ec110ca5700f4371a8a37680baabcb26`。这是合成供应商验证，没有真实云 API、真实账号或原生桌面验收。旧指标 `real_model_called` 按模型请求计数，不能单独作为真实云调用证明；本次独立摘要明确记录 `actual_cloud_api_called=false`。

已阅读历史 `docs/project-state.md` 并与当前源码核对；该文件保留 8 月 31 日的历史状态。按仓库入口要求，本轮未获更新历史项目记忆的请求，因此不改写它。当前隔离入口、schema 3、凭据生命周期及预算边界记录在本文；交接清单已注明服务器账号流程暂不适用于本次联调。源码比对确认原有用户改动被保留，无产品源码、安装、依赖或服务器配置变更。
