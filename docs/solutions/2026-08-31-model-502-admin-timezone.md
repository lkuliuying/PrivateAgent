# 指令 HTTP 502 与管理员上海时间修复

记录日期：2026-08-31（Asia/Shanghai）。工作区：`E:\Program\Agent`。

本次完成本地代码修复、隔离回归和前端生产构建；本阶段未部署服务器、未重新构建客户端安装包、未调用真实模型。截图中的生产 502 尚未取得供应商错误类型或同账号模型验证回执，不能认定本文修复是生产故障的唯一原因。

后续交付：用户随后授权构建、上传、提交和推送。1.0.4 测试安装包与补充回归见[交付记录](../releases/remote-v1.0.4-test.1-20260831.md)；服务器更新工具新增独立备份目录参数，见[1.0.4 更新步骤](../connected-runtime-1.0.3-repair.md#104-修复复用拉取源码后同步运行包)。以下保留首次代码修复阶段的验证与交付边界。

## 问题与修复

### 指令请求返回 HTTP 502

实际链路为：本机 `Runtime` → `Cloud.complete` → 云端 `/desktop/model/complete` → 模型网关 → 供应商。

已复现的代码缺陷是：本机每轮请求都会发送工具定义，`DirectoryArgs.rel_path` 和 `SearchArgs.content` 因有默认值而没有全部列入 JSON Schema 的 `required`；OpenAI 适配器却会加上 `strict=true`。要求严格校验的服务会在模型执行前拒绝请求。[OpenAI 官方严格模式说明](https://developers.openai.com/api/docs/guides/function-calling#strict-mode)要求每个对象禁止额外属性，并把全部属性列入 `required`。

新增回归使用真实本机运行器、请求契约和 OpenAI 适配器，只模拟供应商 HTTP 端点。修复前 3 项失败、2 项通过，拒绝原因是目录工具定义不符合严格模式；修复后 5 项通过。

修复仅调整发送给云端的五个本机工具定义：列全必填属性，去掉默认值声明。本机参数验证器仍接受旧调用省略参数，仍拒绝非法空值，审批和只读限制不变；未修改其他服务的通用适配器。

同时修复错误诊断链路：

- 云端保留原有字符串 `detail`，附加白名单 `X-Model-Error-Code`，分别说明未配置密钥、供应商认证、模型不存在、参数拒绝、限流、网络、超时和响应格式等错误。
- 日志只记录固定错误码与 HTTP 状态，不输出供应商异常正文、提示词、凭据或堆栈。
- 本机只识别白名单错误码，生成固定中文提示，不读取错误响应正文，并把错误码保留到任务和事件。未知代码和旧服务器继续按状态码显示安全提示。
- 供应商认证失败使用 502，与应用会话的 401/403 分开，避免误提示重新登录。
- 无可用默认模型时明确返回 422，不再回落到服务器旧全局 Ollama；模型地址或参数初始化失败返回安全的配置提示。已选择的模型仍按既有账号范围解析。

旧修复工具增加本次模型路由文件的已核对摘要。补丁仍限五个原有文件，保留未知摘要拒绝、服务必须停止、0700 备份权限和回滚保护。已有备份不能被新补丁覆盖；若服务器已经应用过上一轮补丁，不应删除旧备份以强行重跑，需另行核对升级与回滚方案。

### 管理员时间显示

当前后端源码已把管理接口时间序列化为带 `Z` 的 UTC，前端也已有 `Asia/Shanghai` 常量；历史版本的管理接口会返回无时区 UTC。旧的 `new Date(value)` 会把这种字符串当作客户端本地时间解释，在上海时区客户端形成少 8 小时的显示。

本次新增管理员专用格式化函数：无时区的旧 UTC 字符串补齐 UTC 标识；带 `Z` 或显式偏移的时间保持原始时间点，然后统一按 `Asia/Shanghai` 展示。覆盖顶栏、操作审计、最近登录和日志快照更新时间，并标注时区；空值和无法解析的值显示 `--`。

例如 `2026-08-31T00:08:04` 按服务端 UTC 约定显示为 `2026年8月31日 08:08:04`。不改数据库值、API 存储约定、其他页面的通用解析逻辑或原始日志正文。截图对应服务器当前是否仍返回无时区字符串尚未直接检查。

## 本次变更文件

| 范围 | 文件 |
| --- | --- |
| 本机请求与错误传播 | `src/private_agent_local/runtime.py`、`src/private_agent_local/cloud.py` |
| 云端模型错误与配置边界 | `src/personal_assistant/api/routes_desktop_model.py` |
| 管理员显示 | `apps/desktop/src/services/timeDisplay.ts`、`apps/desktop/src/pages/AdminPage.vue`、`apps/desktop/src/components/AdminLogsPanel.vue` |
| 后端回归 | `tests/unit/test_local_model_contract.py`（新增）、`tests/unit/test_desktop_model.py`、`tests/unit/test_local_executor.py` |
| 前端回归 | 上述三个前端文件对应的 `.spec.ts` |
| 旧补丁兼容 | `scripts/repair-connected-runtime.py`、`tests/unit/test_connected_runtime_repair.py` |
| 文档 | 本文、`docs/README.md` |

保留任务开始前全部未提交改动，包括原有 ORM 字段修复、补丁工具和交接文档。没有修改依赖版本、锁文件、数据库、部署配置或更新通道。

## 实际验证

后端在无环境文件的隔离目录运行，使用仓库源码和模拟依赖。最终标准复跑没有加载临时测试插件；在获准的非受限执行环境中运行，解决了 Windows 沙箱对临时目录和命名管道的权限限制。

```powershell
Set-Location E:\Program\Agent\.tmp\fix-502-timezone
$env:PYTHONPATH='E:\Program\Agent\src'
$env:PYTHONDONTWRITEBYTECODE='1'
& E:\Program\Agent\.venv\Scripts\python.exe -m pytest E:\Program\Agent\tests\unit\test_desktop_model.py E:\Program\Agent\tests\unit\test_local_executor.py E:\Program\Agent\tests\unit\test_local_model_contract.py E:\Program\Agent\tests\test_model_gateway.py E:\Program\Agent\tests\test_admin_time_serialization.py E:\Program\Agent\tests\unit\test_connected_runtime_repair.py E:\Program\Agent\tests\unit\test_connected_backend_bundle.py E:\Program\Agent\tests\unit\test_admin_logs.py --noconftest -p no:cacheprovider --basetemp E:\Program\Agent\.tmp\fix-502-timezone\pytest-final-0831 -q -rs
```

结果：**117 passed、1 skipped**。跳过项为 `test_admin_logs.py` 中需要真实符号链接的既有测试，本机没有创建权限；未删除或放宽测试。专用 `--basetemp` 是一次性测试目录，复跑不得替换为项目或用户数据目录。隔离目录被 Git 忽略，其他机器需自行创建无环境文件的目录。

前端按已有锁文件安装依赖，未执行第三方安装脚本：

```powershell
Set-Location E:\Program\Agent\apps\desktop
npm ci --ignore-scripts --no-audit --no-fund --cache E:\Program\Agent\.tmp\npm-cache
npm run test -- src/services/timeDisplay.spec.ts src/pages/AdminPage.spec.ts src/components/AdminLogsPanel.spec.ts
npm run test
npm run build
```

结果：针对性 **27 passed**；完整 **78 个测试文件、454 passed**；类型检查及 Vite 生产构建通过。构建仍提示部分压缩后资源块超过 500 kB，本次未扩展到拆包优化。先前沙箱内 `esbuild spawn EPERM` 在获准执行后已消除，不计为业务失败。

静态检查：

```powershell
Set-Location E:\Program\Agent
.venv/Scripts/python.exe -m ruff check src/personal_assistant/api/routes_desktop_model.py src/private_agent_local/cloud.py src/private_agent_local/runtime.py scripts/repair-connected-runtime.py tests/unit/test_desktop_model.py tests/unit/test_local_executor.py tests/unit/test_local_model_contract.py tests/unit/test_connected_runtime_repair.py --no-cache
git diff --check
```

两项通过。未运行依赖真实数据库的全量 Python 集成测试、浏览器端到端测试、Tauri 构建或安装升级测试。

## 生效条件与记忆核对

完整修复需要云端加载新版模型路由，并重新构建和安装包含本机执行器及前端改动的联网版客户端。只更新服务器不会修复旧客户端发送的工具定义或管理员显示；只更新前端不会更新捆绑的执行器。必须检查服务实际加载的安装副本，不能仅凭源码目录更新判断上线。

本次未访问生产凭据、未修改服务器、未调用可能付费的真实模型，也没有提交、推送或发布。真实账号调用、供应商配置、反向代理状态及安装包生效仍待验收。

已读取并核对 `docs/project-state.md`、`docs/solutions/2026-08-31-privateagent-1-0-3.md` 和 `docs/connected-runtime-1.0.3-repair.md`。历史验证数字和缺依赖记录属于当时快照，不是本轮验证；生产“待确认”状态继续成立。按根 `AGENTS.md` 的要求，用户未明确要求更新项目记忆，本次不改写 `docs/project-state.md`，以本文记录本轮代码和验证事实。
