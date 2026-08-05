# 安全与隐私模型

> 目标：本地优先不等于默认可信。WebView、模型输出、RAG 文档、工具结果、MCP 服务、远程 endpoint 和备份都跨越不同信任边界。

## 1. 资产与威胁

需要保护的资产：数据库凭据、provider API key、会话和记忆、授权文件、文档原文、工具批准、更新签名密钥以及数据库/向量索引完整性。

主要威胁：

- 本机其他进程调用 loopback API；
- 恶意网页或被注入的 WebView 发起跨源请求；
- 文档或 MCP 返回中的提示注入诱导越权；
- 模型生成路径穿越、任意命令或危险数据库操作；
- 一次审批被替换参数、重放或跨 run 使用；
- 远程 endpoint 指向内网、元数据服务或重定向目标；
- 日志、诊断包、备份或前端 DTO 泄露秘密；
- 数据库迁移或 Chroma 部分失败造成不可恢复的不一致；
- 未签名安装包或 updater 清单被篡改。

## 2. 本地 API 边界

`src/personal_assistant/api/security.py` 和 `main_api.py` 实施：

- 桌面/源码模式只允许 loopback bind；容器模式仅在显式开关、unspecified wildcard 和强制认证同时满足时允许容器内 `0.0.0.0/::`；
- 非预检 HTTP/SSE 默认要求 Bearer token；
- 严格校验 `Host`；
- 只接受配置中的精确 `Origin`；
- CORS 不允许 credentials，并限制方法和 header；
- 错误响应不回显 token。

Tauri 主进程在每次 sidecar 启动时用 OS CSPRNG 生成 256-bit token，只通过子进程环境和当前 WebView 连接 DTO 传递。安装版不把 token 持久化；Vue 的共享 HTTP 封装统一附加 token。

`PA_API_AUTH_ENABLED=false` 只适合受控开发环境。即使设置容器开关，关闭认证时也不得把 `PA_API_HOST` 改为非 loopback。`compose.yaml` 只发布到宿主 `127.0.0.1`，不把“容器内 wildcard”解释为公网许可。

## 3. 秘密管理

Windows 安装版通过 `apps/desktop/src-tauri/src/credentials.rs` 和 `credential_prompt.rs` 直接与 Credential Manager 和原生凭据窗口交互。数据库密码、OpenAI/Claude key 不进入：

- Vue 状态；
- Tauri IPC payload；
- FastAPI settings 响应；
- 持久化 `.env`；
- 备份包；
- 诊断日志。

持久化配置只保存非敏感字段或固定 `secret://` 引用。源码开发的 `.env` 是兼容路径，已被 Git 忽略；不得提交真实秘密。

可选容器部署使用 Compose secret files。`Settings` 只在启动时读取 `PA_API_TOKEN_FILE` 和 `PA_DB_PASSWORD_FILE`，拒绝同一秘密同时由直接环境值和文件提供；数据库密码通过 SQLAlchemy URL 组件编码后只存在进程内 DSN。生成脚本拒绝覆盖和项目外路径，`.secrets/` 不进入 Git 或镜像。Compose 本地 secret file 仍依赖宿主 ACL，不等同于云端 KMS；正式编排平台应换用原生 secret provider。

自动会话摘要是独立的历史数据外发边界。worker 默认关闭，并且即使用户已配置远程聊天 provider，也只有再开启 `PA_CONVERSATION_SUMMARY_ALLOW_REMOTE_PROVIDER` 才能发送候选消息；本地 Ollama 不受此二次开关影响。来源中的疑似 token/password/private-key 会让生成记录标为 sensitive，默认 ContextBuilder 不选取。该检测是纵深防护，不替代用户对远程 provider 的明确许可。

签名私钥、PFX 和密码文件遵循 `docs/signing-and-keys.md`，不得进入仓库或发布包。

## 4. 工具与审批

工具安全由 `ToolSpec` Schema、capability 默认拒绝策略、风险级别、一次性审批和 durable execution 共同实现。审批绑定 run/step/call、工具版本和参数哈希；raw token 只在后端内存中出现。

文件能力还要经过可信根目录、路径解析和穿越校验。命令能力使用固定 allowlist，不把模型文本交给 shell。写入补丁校验 `expected_old_sha256`，防止过期内容覆盖。

详细规则见 `docs/tool-system.md`。

## 5. RAG 与上下文

文档正文、MCP 描述/资源/提示和工具输出全部是不可信数据。`ContextBuilder` 用带 trust/provenance 的 JSON envelope 注入；其中的“系统指令”“授权请求”或命令文本不能改变策略。

最终副作用仍由工具执行器重新校验，避免把 prompt injection 防护寄托在单一提示词上。引用必须指向实际召回片段；无可靠来源时不得生成伪引用。

敏感、过期、软删除或未确认的记忆默认不进入上下文，也不得在未获知情同意时发送远程 provider。

## 6. MCP 与网络

MCP 默认关闭，每个 server 初始不信任、不启用且没有 allowlist。stdio 只允许已存在的绝对可执行文件并绕过 shell。Streamable HTTP 默认要求 HTTPS，拒绝 URL 凭据、非法端口、重定向、环境代理和解析到私网/环回/链路本地/元数据地址的目标。所有解析结果先整体校验，再作为唯一可连接地址集钉到 TCP backend；backend 拒绝 hostname/port 换址，TLS SNI 和证书校验仍使用原域名。

发现的 MCP 工具统一转换成内部 `confirm` ToolSpec。调用日志只保存哈希、计数、状态、延迟和错误类型，不保存完整参数或结果。

MCP 凭据由原生系统窗口写入 OS keyring，数据库/Vue 只持有固定引用。打包启动时 Rust 只向 sidecar 注入有界引用映射，Python 立即从环境移除；stdio secret env、HTTP Bearer 和受限 API-key header 都在连接使用点解析，缺失或异常即失败关闭。真实官方 SDK Streamable HTTP server 已覆盖两种静态认证。

尚未完成：OAuth 生命周期、具体第三方生产服务验收、企业代理策略和证书 pinning。在这些边界及主库当前 head `0020` 授权迁移完成前 `PA_MCP_ENABLED` 保持 false；应用层 DNS pinning 也不能替代宿主出口 ACL。

## 7. CSP、桌面壳与更新

`apps/desktop/src-tauri/tauri.conf.json` 的 CSP 只开放本地资源、Tauri IPC、动态 loopback sidecar 和必要数据协议，拒绝外部脚本和对象。Rust 主进程负责 sidecar 端口、token、凭据注入和退出清理。

发布流程同时区分 Tauri updater 签名和 Windows Authenticode。没有正式证书时发布清单必须标记 unsigned，不能把生成安装包等同于可信发布。

## 8. 日志、诊断和备份

- 日志记录 trace、状态、耗时、计数和异常类型，不记录完整 DSN、token、API key、文档正文或模型隐式推理。
- 诊断包对 settings、日志和健康信息脱敏，不导出完整聊天、文档原文或敏感记忆。
- 未加密备份会清空环境秘密；恢复先 preview/drill，再由用户确认。
- 数据库 clone manifest 只含 schema、表计数和哈希，密码只进入短生命周期子进程环境。

## 9. 安全回归

```powershell
uv run pytest -q tests/test_api_security.py tests/test_tool_contracts.py `
  tests/test_tool_approvals.py tests/test_tool_executions.py tests/test_mcp.py `
  tests/test_phase8_backup.py tests/test_server_entry.py
```

发布前还必须执行诊断包脱敏、CSP、更新签名、路径穿越、SSRF、审批重放和迁移失败拒绝启动检查，见 `docs/testing-guide.md`。
