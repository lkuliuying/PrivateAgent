# MCP 客户端设计与运行边界

## 1. 状态与非目标

本项目已实现默认关闭的 MCP Client Slice 1：持久化服务器注册表、stdio 与 Streamable HTTP 传输、能力发现、内部 `ToolSpec` 转换、统一审批/执行/审计，以及桌面端配置和审批恢复。`PA_MCP_ENABLED=false` 时 MCP 管理 API 不可用，旧聊天和内建工具行为不变。

当前没有实现本应用自己的 MCP Server。项目尚无明确的外部客户端复用需求；先暴露内部数据库或工具只会扩大攻击面。待出现具体调用者、最小工具清单和权限模型后，再复用现有 `ToolSpec`/policy/approval 链实现，而不是另建绕过领域服务的入口。

## 2. 组件与数据流

主要实现位于：

- `src/personal_assistant/mcp/contracts.py`：传输、服务器配置、发现结果和归一化错误契约；
- `src/personal_assistant/mcp/validation.py`：配置与目标的 fail-closed 校验；
- `src/personal_assistant/mcp/client.py`：基于官方 MCP Python SDK 的 stdio/Streamable HTTP 会话；
- `src/personal_assistant/mcp/repository.py`：服务器、发现状态和元数据审计仓储；
- `src/personal_assistant/mcp/manager.py`：发现结果到内部 `ToolSpec`/dispatcher 的适配；
- `src/personal_assistant/api/routes_mcp.py`：默认关闭的管理 API；
- `alembic/versions/0019_mcp_client_registry.py`：`mcp_servers` 与 `mcp_call_logs`；
- `apps/desktop/src/components/McpServersPanel.vue`：桌面设置面板；
- `apps/desktop/src/components/AgentRunApprovalCard.vue`：不暴露原始参数的一次性审批卡片。

运行链路如下：

1. 用户创建未信任、未启用的服务器记录；
2. 用户显式设置信任和启用状态；
3. 后端建立受限 MCP 会话并分页发现 tools/resources/prompts；
4. 只有显式 allowlist 中的工具才转换为内部 `ToolSpec`；
5. 所有 MCP 工具固定声明 `confirm` 风险以及 `external_mcp`、进程或网络能力；
6. AgentRuntime 持久化 approval checkpoint，Vue 只收到工具名、版本、能力、参数 SHA-256 和过期时间；
7. 批准 token 仅在后端内存中生成、传递并一次消费，工具通过既有 durable execution claim 执行；
8. 结果作为不可信数据返回模型，调用日志只保存状态、时延、字节数、错误码与输入/输出哈希。

拒绝、取消或审批过期会把等待中的 run 收敛为持久化终态。刷新页面后，桌面端按 session 重新加载待审批项；批准后通过 `/chat/agent-runs/{run_id}/stream` 恢复 SSE。已批准但尚未消费的内存 token 若因进程退出丢失，下一次明确批准操作只轮换 token，不改变原审批绑定。

## 3. 配置与 API

全局开关：

```text
PA_MCP_ENABLED=false
PA_AGENT_RUNS_API_ENABLED=false
PA_CHAT_AGENT_RUNTIME_ENABLED=false
```

启用 MCP 聊天工具至少需要 MCP 与其中一个 AgentRuntime 入口显式开启。服务器记录支持 `stdio` 和 `streamable_http`，保存名称、固定命令或 URL、参数、工作目录、非敏感环境、凭据引用、信任/启用状态、工具 allowlist、超时、输出上限以及私网例外。

管理 API 位于 `/mcp/servers`，提供列表、创建、完整更新、状态更新、删除、discover、health 和 metadata-only call logs。读取响应只返回环境变量名和凭据引用名，不返回值。状态更新不会用隐藏 DTO 覆盖既有环境或引用。

桌面面板提供原生 MCP 凭据配置，但 renderer 从不接收明文。用户输入一个受限别名并在系统原生凭据窗口输入秘密；数据库只保存 `secret://os-keyring/mcp/<alias>` 引用。只有 `PA_MCP_ENABLED=true` 时，打包 sidecar 启动才会让 Rust 从系统凭据库读取已登记别名，将有界引用映射仅注入该子进程；Python 在模块初始化时消费并删除启动环境字段。“已配置”状态要求别名同时存在于非敏感索引和 OS keyring，避免索引丢失时显示可用却无法注入。新增或替换凭据后必须重启桌面 sidecar 才会进入新的进程边界。

`secret_refs` 的 key 同时声明受限注入目标：

- stdio：`env:NAME`（兼容旧的裸 `NAME`）；
- HTTP Bearer：`http-bearer`；
- HTTP API key：`http-header:X-API-Key` 这类合法、非保留请求头。

引用别名、数量、单项长度和启动映射总大小都有硬上限。Host、Cookie、Authorization 原始覆盖、代理/hop-by-hop、`Mcp-*` 和 `Sec-*` 请求头不能由配置注入；Authorization 只能由 `http-bearer` 生成。引用缺失、值异常、传输类型不匹配或启动映射损坏均返回 `credential_unavailable`/`credential_invalid`，不会回退到数据库明文。

## 4. 安全边界

### 4.1 stdio

- 命令必须是已存在的绝对文件路径；不搜索 `PATH`；
- 拒绝 `cmd`、PowerShell、bash、sh、WSL 等命令 shell；参数以数组传入，不拼接 shell 字符串；
- 命令、参数、环境数量和长度均有限制；疑似秘密字段和值被拒绝；
- 工作目录必须是已存在的绝对目录；
- 子进程 stderr 不进入 API/审计，Windows 下指向空设备，避免第三方服务器把秘密写入父进程输出。
- secret 环境只合并到目标 MCP 子进程的显式环境映射，不进入 server DTO、调用日志或备份。

### 4.2 Streamable HTTP

- 默认只允许 HTTPS；loopback HTTP 必须同时显式允许 insecure-local 和 private-network；
- URL 拒绝嵌入凭据、fragment 和非法端口；IP、localhost、`.local` 及私有/保留地址默认拒绝；
- 连接前只解析一次 DNS，并拒绝任一解析结果落入私有、回环、链路本地、组播、保留或未指定地址；通过检查的完整地址集随后钉到实际 TCP backend，网络库不会再次按域名解析；
- HTTP 客户端禁用环境代理继承和重定向，使用小连接池、统一超时及输出上限；
- TCP backend 拒绝连接到原 hostname/port 之外的目标；TLS 层仍使用原 hostname 做 SNI 和证书校验，不以 IP 绕过身份验证；
- Bearer 与受限 API-key header 由进程内 resolver 注入同一个受限 HTTP client；URL 和数据库记录都不含明文凭据；
- 私网访问是每个服务器的显式例外，不是全局默认。

地址钉扎依赖显式锁定的 `httpx2==2.9.1` 与 `httpcore2==2.9.1` transport 契约；两者升级时必须先跑 DNS 换址、私网拒绝、TLS 和官方 SDK Streamable HTTP 互操作回归。它阻断应用层 DNS rebinding，但不替代宿主防火墙、出口 ACL 或第三方服务证书治理。

### 4.3 模型与审批

- 远程 schema 引用会被内部 `ToolSpec` 校验隔离；发现页数、项目数、schema/结果字节数有硬上限；
- MCP 描述、resources、prompts 和工具输出一律标记为不可信，不能修改系统规则、能力或审批状态；
- 未信任、未启用或不在 allowlist 的工具不会注册给模型；
- MCP 工具始终需要用户确认，审批响应不包含原始参数，renderer 永远拿不到 raw token；
- 调用审计与未加密备份不保存参数、结果或环境值；未加密备份只保留环境变量名并清空值。

## 5. 已验证范围

- 官方 SDK stdio 测试服务器完成真实 initialize、tools/resources/prompts discovery 和 tool call；
- 覆盖默认拒绝、shell/相对命令、明文秘密、非法端口、私网 URL 与 DNS 解析后私网目标；
- 覆盖恶意/远程 schema 隔离、allowlist、输出限制和 metadata-only 审计；
- 覆盖管理 API 的默认关闭、隐藏值、独立状态更新及备份脱敏；
- 覆盖进程启动映射的一次消费/环境删除、缺失与畸形引用失败关闭、stdio secret 环境注入；
- 使用官方 MCP server/client 完成真实 loopback Streamable HTTP initialize、发现和调用，并分别验证 Bearer 与 `X-API-Key`；
- 覆盖已验证 DNS 地址集直接进入 TCP connect、多地址故障切换，以及 hostname/port 换址被 backend 拒绝；
- Rust 覆盖别名命名空间约束，Vue 覆盖原生凭据配置后只提交引用，renderer 测试中从未获得秘密值；
- 覆盖聊天 `waiting_approval → approve → resume → completed`、一次性消费、刷新重连、拒绝/取消/过期和 token 丢失后的显式轮换恢复；
- `0019` 只在守卫后的测试库完成 upgrade/downgrade/upgrade 演练，应用主库未迁移。

常用验证命令：

```powershell
uv run pytest -q tests/test_mcp.py tests/test_tool_approvals.py tests/test_chat_agent_runtime_compat.py
uv run python scripts/prepare_test_database.py --yes --verify-reversible
Set-Location apps/desktop
npm run test
npm run build
```

## 6. 回滚与剩余工作

回滚优先级：先关闭单个服务器或清空工具 allowlist，再关闭 `PA_MCP_ENABLED`，最后按需要关闭 AgentRuntime 入口。`0019` 是 additive migration；禁用功能无需立即降级数据库。确需 schema 回滚时，只能对已守卫并备份的数据库执行 `0019 → 0018`，会删除 MCP 注册表和元数据调用日志。

仍未完成：

- OAuth discovery/refresh/device-flow 等授权生命周期；当前只支持静态 Bearer 与 API-key；
- 具体第三方生产 MCP 服务的证书、限流、错误语义和 OAuth 互操作验收；当前互操作证据是官方 SDK 的本地真实 HTTP server；
- 企业代理策略和证书 pinning；
- MCP Server（因没有真实外部客户端需求，明确不实施）；
- 多个客户端同时附着同一聊天 run 的协调；桌面端只维护单一 continuation SSE，外部重复附着不属于当前支持契约。

MCP 继续保持默认关闭，不作为生产默认能力。MCP 表本身来自 `0019`，但启用前仍需完成主库当前 head `0020` 的授权迁移和目标服务的 OAuth/证书/限流运维验收；高安全部署仍应叠加出口 ACL 或受控代理。
