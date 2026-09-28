# API Key 单模式与桌面账号移除交付记录

> 同日后续打包：用户随后要求提供测试安装包，已生成 `PrivateAgentCandidate_1.0.14_x64-setup.exe`。构建、打包执行器启动及 stdio-v2 本机任务验证通过；未安装、发布或调用真实模型。安装包和完整验证记录保存在 `.run/unified-client-IwE2WL/`，见其中的 `测试说明.md`。下文“未打包”描述的是先前源码交付阶段，不代表此次后续打包结果。

日期：2026-09-19（Asia/Shanghai）。工作区 `F:\Program\Agent`，分支 `dev/1.0.0`，HEAD `1dde393e29f3dbacd3647d11834b39824ac8323f`。本次以任务开始前的文件快照区分已有大量未提交工作；未提交、推送、安装、发布或部署。

## 任务总结

当前桌面客户端和本机轻量执行器只保留 API Key 使用入口，启动自动建立本机会话；删除登录、注册、管理员页面与专用服务、状态、原生账号源站命令及旧平台身份绑定。自动化页面、主导航及专用接口/类型移除，插件页显示“开发中”。技术文档 MCP 保留项目配置、工具发现/启用、逐次审批及结果记录，并通过本机会话执行。

401 修复基于实际调用链：先保存本机令牌再加载工作区；设置不再请求旧服务器全局配置、备份或 MCP 管理；删除旧平台历史导出。旧功能请求明确返回 410。只有标记本机会话过期的 401 才重新连接，不重放失败写请求；供应商 401 保留工作区，显示密钥/权限问题。

构建与验收调用方同步到新契约。执行器不接收 `--server`；构建不接收平台源站位置参数。模型评测不索取平台会话，不再启动本机联调临时账号服务。项目数据、模型 Key、工具审批和系统凭据边界保持原规则。

用户已明确要求同时删除旧服务器账号模块。`personal_assistant` 的登录、注册、账号管理、管理员日志和账号历史导出接口，以及密码、登录会话、验证码/SMTP 服务均已移除。独立后端仅接受配置的服务令牌，保留 Host/Origin 防护和审计；模型供应商 Key 不能充当服务令牌。历史表映射、外键及迁移保留以避免删除数据，审计清理不再操作账号表。旧 1.0.3 补丁工具只适用于历史归档，不能对当前源码生成账号补丁；本次未执行任何服务器操作。安装副本及真实供应商未验收。

## 变更文件

以下 142 个文件仅列本轮相对各阶段修改前快照的变化，不把其他会话的 Git 差异计入本轮。旧后端扩展范围在用户确认后单独保存基线。

| 文件 | 操作 | 变化 |
| --- | --- | --- |
| `.env.container.example` | 修改 | 移除账号注册、登录会话及 SMTP 配置；桌面不注入服务令牌。 |
| `.env.example` | 修改 | 移除账号注册、登录会话及 SMTP 配置；桌面不注入服务令牌。 |
| `README.md` | 修改 | 同步 API Key 单模式、构建方式、验证结果和历史边界。 |
| `apps/desktop/.env.example` | 修改 | 移除账号注册、登录会话及 SMTP 配置；桌面不注入服务令牌。 |
| `apps/desktop/e2e/button-tooltips.spec.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/e2e/coding-auth-fixture.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/e2e/coding-run.spec.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/e2e/diagnostics-access.spec.ts` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `apps/desktop/e2e/documentation-mcp.spec.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/e2e/local-access.spec.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/src-tauri/src/lib.rs` | 修改 | 执行器启动移除平台源站和 --server 参数。 |
| `apps/desktop/src-tauri/src/local_executor.rs` | 修改 | 执行器启动移除平台源站和 --server 参数。 |
| `apps/desktop/src-tauri/src/server.rs` | 删除 | 移除固定平台账号源站命令。 |
| `apps/desktop/src/App.vue` | 修改 | 移除平台/自动化入口及账号文案，统一使用本机工作区。 |
| `apps/desktop/src/RootApp.spec.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/src/RootApp.vue` | 修改 | 启动自动绑定本机会话，移除登录跳转，支持明确的连接失败与恢复。 |
| `apps/desktop/src/api.ts` | 修改 | 删除自动化专用 API/类型及已删除模块的引用。 |
| `apps/desktop/src/api/http.spec.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/src/api/http.ts` | 修改 | 内部请求只走本机 IPC，已删除接口返回 410，区分会话与供应商 401。 |
| `apps/desktop/src/api/modelProviders.ts` | 修改 | 密钥更新错误明确描述本机会话变化。 |
| `apps/desktop/src/api/modelSecrets.spec.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/src/auth/session.ts` | 修改 | 仅保存本机会话并清理旧平台令牌偏好。 |
| `apps/desktop/src/components/AdminLogsPanel.spec.ts` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `apps/desktop/src/components/AdminLogsPanel.vue` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `apps/desktop/src/components/CommandPalette.vue` | 修改 | 移除平台/自动化入口及账号文案，统一使用本机工作区。 |
| `apps/desktop/src/components/ExtensionRegistryPanel.spec.ts` | 新增 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/src/components/ExtensionRegistryPanel.vue` | 修改 | 插件页显示“开发中”，不请求旧扩展接口。 |
| `apps/desktop/src/components/HistoryMigration.vue` | 修改 | 删除旧平台导出入口，保留本机历史导入与导出。 |
| `apps/desktop/src/components/ProfileSettingsPanel.spec.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/src/components/ProfileSettingsPanel.vue` | 修改 | 移除平台/自动化入口及账号文案，统一使用本机工作区。 |
| `apps/desktop/src/components/SettingsView.spec.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/src/components/SettingsView.vue` | 修改 | 移除平台/自动化入口及账号文案，统一使用本机工作区。 |
| `apps/desktop/src/components/TaskWorkspace.vue` | 删除 | 移除自动化工作区。 |
| `apps/desktop/src/components/UserMenu.spec.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/src/components/UserMenu.vue` | 修改 | 移除平台/自动化入口及账号文案，统一使用本机工作区。 |
| `apps/desktop/src/config/uiFlags.spec.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/src/config/uiFlags.ts` | 修改 | 移除平台/自动化入口及账号文案，统一使用本机工作区。 |
| `apps/desktop/src/features/coding/components/CodingSidebar.spec.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/src/features/coding/components/CodingSidebar.vue` | 修改 | 移除平台/自动化入口及账号文案，统一使用本机工作区。 |
| `apps/desktop/src/models/settingsSections.ts` | 修改 | 移除平台/自动化入口及账号文案，统一使用本机工作区。 |
| `apps/desktop/src/pages/AdminPage.spec.ts` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `apps/desktop/src/pages/AdminPage.vue` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `apps/desktop/src/pages/AuthPage.spec.ts` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `apps/desktop/src/pages/AuthPage.vue` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `apps/desktop/src/router/index.spec.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/src/router/index.ts` | 修改 | 启动自动绑定本机会话，移除登录跳转，支持明确的连接失败与恢复。 |
| `apps/desktop/src/services/admin.ts` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `apps/desktop/src/services/adminLogs.ts` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `apps/desktop/src/services/auth.spec.ts` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `apps/desktop/src/services/auth.ts` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `apps/desktop/src/services/backendStartup.spec.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/src/services/backendStartup.ts` | 修改 | 启动自动绑定本机会话，移除登录跳转，支持明确的连接失败与恢复。 |
| `apps/desktop/src/services/connectionProfile.ts` | 修改 | 移除平台/自动化入口及账号文案，统一使用本机工作区。 |
| `apps/desktop/src/services/localAccess.integration.spec.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/src/services/localExecutor.spec.ts` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `apps/desktop/src/services/localExecutor.ts` | 修改 | 启动自动绑定本机会话，移除登录跳转，支持明确的连接失败与恢复。 |
| `apps/desktop/src/services/serverLogin.integration.spec.ts` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `apps/desktop/src/stores/admin.spec.ts` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `apps/desktop/src/stores/admin.ts` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `apps/desktop/src/stores/auth.spec.ts` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `apps/desktop/src/stores/auth.ts` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `apps/desktop/src/types.ts` | 修改 | 删除自动化专用 API/类型及已删除模块的引用。 |
| `apps/desktop/src/types/auth.ts` | 删除 | 删除平台账号/管理员页面、服务、状态或相应旧测试；入口缺失由新路由与页面回归覆盖。 |
| `compose.yaml` | 修改 | 移除账号注册、登录会话及 SMTP 配置；桌面不注入服务令牌。 |
| `deploy/centos-stream9/private-agent.env.example` | 修改 | 移除账号注册、登录会话及 SMTP 配置；桌面不注入服务令牌。 |
| `docs/README.md` | 修改 | 同步 API Key 单模式、构建方式、验证结果和历史边界。 |
| `docs/archive/legacy/admin-service-logs.md` | 修改 | 同步账号功能退役、本机 API Key 方式与历史部署边界。 |
| `docs/archive/legacy/connected-desktop-rollout.md` | 修改 | 同步账号功能退役、本机 API Key 方式与历史部署边界。 |
| `docs/archive/legacy/deployment-guide.md` | 修改 | 同步账号功能退役、本机 API Key 方式与历史部署边界。 |
| `docs/direct-model-execution.md` | 修改 | 同步 API Key 单模式、构建方式、验证结果和历史边界。 |
| `docs/archive/legacy/new-computer-development.md` | 修改 | 同步账号功能退役、本机 API Key 方式与历史部署边界。 |
| `docs/project-state.md` | 修改 | 同步 API Key 单模式、构建方式、验证结果和历史边界。 |
| `docs/archive/legacy/remote-client-updates.md` | 修改 | 同步 API Key 单模式、构建方式、验证结果和历史边界。 |
| `docs/archive/legacy/server-code-update-workflow.md` | 修改 | 同步账号功能退役、本机 API Key 方式与历史部署边界。 |
| `docs/solutions/2026-09-19-api-key-only.md` | 新增 | 同步 API Key 单模式、构建方式、验证结果和历史边界。 |
| `scripts/build-remote-client.cjs` | 修改 | 构建不再接收平台源站，保持现有更新渠道与发布保护。 |
| `scripts/build-remote-client.test.cjs` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `scripts/coding_acceptance_identity.py` | 修改 | 候选来源清单排除已删除文件，记录本机使用方式。 |
| `scripts/coding_acceptance_isolation.py` | 修改 | 验收改用本机身份与模型目录，不依赖平台登录。 |
| `scripts/coding_acceptance_local.py` | 修改 | 验收改用本机身份与模型目录，不依赖平台登录。 |
| `scripts/coding_acceptance_models.py` | 修改 | 验收改用本机身份与模型目录，不依赖平台登录。 |
| `scripts/coding_acceptance_transport.py` | 修改 | 验收改用本机身份与模型目录，不依赖平台登录。 |
| `scripts/run_coding_acceptance.py` | 修改 | 验收改用本机身份与模型目录，不依赖平台登录。 |
| `scripts/run_coding_legacy_validation.py` | 修改 | 增加隔离鉴权和历史补丁验证套件，不读取业务配置或连接生产数据库。 |
| `scripts/run_coding_validation.py` | 修改 | 增加隔离鉴权和历史补丁验证套件，不读取业务配置或连接生产数据库。 |
| `scripts/verify-local-executor.py` | 修改 | 验收改用本机身份与模型目录，不依赖平台登录。 |
| `scripts/verify-unified-client.py` | 修改 | 验收改用本机身份与模型目录，不依赖平台登录。 |
| `smtp.env.example` | 删除 | 删除退役的注册邮件配置示例。 |
| `src/personal_assistant/api/audit.py` | 修改 | 审计只记录服务/匿名访问，保留策略不再清理历史账号表。 |
| `src/personal_assistant/api/auth_dependencies.py` | 删除 | 删除旧平台账号认证、管理、注册邮件或账号历史导出实现。 |
| `src/personal_assistant/api/routes_admin.py` | 删除 | 删除旧平台账号认证、管理、注册邮件或账号历史导出实现。 |
| `src/personal_assistant/api/routes_admin_logs.py` | 删除 | 删除旧平台账号认证、管理、注册邮件或账号历史导出实现。 |
| `src/personal_assistant/api/routes_auth.py` | 删除 | 删除旧平台账号认证、管理、注册邮件或账号历史导出实现。 |
| `src/personal_assistant/api/routes_desktop_history.py` | 删除 | 删除旧平台账号认证、管理、注册邮件或账号历史导出实现。 |
| `src/personal_assistant/api/routes_desktop_model.py` | 修改 | 使用服务令牌身份替代账号依赖，保留模型和健康接口功能。 |
| `src/personal_assistant/api/routes_health.py` | 修改 | 使用服务令牌身份替代账号依赖，保留模型和健康接口功能。 |
| `src/personal_assistant/api/security.py` | 修改 | 只接受服务令牌，删除数据库登录会话回退，保留来源与上下文校验。 |
| `src/personal_assistant/config.py` | 修改 | 删除账号和 SMTP 配置，不再读取 smtp.env。 |
| `src/personal_assistant/core/admin_logs.py` | 删除 | 删除旧平台账号认证、管理、注册邮件或账号历史导出实现。 |
| `src/personal_assistant/core/auth.py` | 删除 | 删除旧平台账号认证、管理、注册邮件或账号历史导出实现。 |
| `src/personal_assistant/core/email_verification.py` | 删除 | 删除旧平台账号认证、管理、注册邮件或账号历史导出实现。 |
| `src/personal_assistant/core/models.py` | 修改 | 标记历史账号表映射已退役，保留表结构和外键，不执行数据迁移。 |
| `src/personal_assistant/core/smtp_email.py` | 删除 | 删除旧平台账号认证、管理、注册邮件或账号历史导出实现。 |
| `src/personal_assistant/core/tenant.py` | 修改 | 说明历史数据归属兼容边界，保持内部维护上下文。 |
| `src/personal_assistant/main_api.py` | 修改 | 删除账号、管理和账号历史导出路由注册。 |
| `src/private_agent_local/app.py` | 修改 | 运行时只绑定本机身份，模型直连不创建平台账号客户端；同步错误契约和入口。 |
| `src/private_agent_local/cloud.py` | 修改 | 运行时只绑定本机身份，模型直连不创建平台账号客户端；同步错误契约和入口。 |
| `src/private_agent_local/direct_models.py` | 修改 | 运行时只绑定本机身份，模型直连不创建平台账号客户端；同步错误契约和入口。 |
| `src/private_agent_local/entry.py` | 修改 | 运行时只绑定本机身份，模型直连不创建平台账号客户端；同步错误契约和入口。 |
| `src/private_agent_local/local_models.py` | 修改 | 运行时只绑定本机身份，模型直连不创建平台账号客户端；同步错误契约和入口。 |
| `tests/coding_acceptance/test_s6_acceptance.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/coding_acceptance/test_s6_delivery.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/coding_acceptance/test_s6_direct_evaluation.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/coding_acceptance/test_s6_external.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/coding_acceptance/test_s6_local_probe.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/coding_acceptance/test_s6_models.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/coding_acceptance/test_s6_phase_d.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/test_admin_time_serialization.py` | 删除 | 删除已退役账号、验证码、管理及账号导出功能的旧用例；退役行为由新接口与权限回归覆盖。 |
| `tests/test_api_security.py` | 修改 | 验证服务令牌、退役接口、健康信息、配置与审计边界，使用隔离数据。 |
| `tests/test_config_secret_files.py` | 修改 | 验证服务令牌、退役接口、健康信息、配置与审计边界，使用隔离数据。 |
| `tests/test_email_verification.py` | 删除 | 删除已退役账号、验证码、管理及账号导出功能的旧用例；退役行为由新接口与权限回归覆盖。 |
| `tests/test_health.py` | 修改 | 验证服务令牌、退役接口、健康信息、配置与审计边界，使用隔离数据。 |
| `tests/test_health_visibility.py` | 修改 | 验证服务令牌、退役接口、健康信息、配置与审计边界，使用隔离数据。 |
| `tests/test_multi_user_auth.py` | 删除 | 删除已退役账号、验证码、管理及账号导出功能的旧用例；退役行为由新接口与权限回归覆盖。 |
| `tests/unit/test_admin_logs.py` | 删除 | 删除已退役账号、验证码、管理及账号导出功能的旧用例；退役行为由新接口与权限回归覆盖。 |
| `tests/unit/test_connected_backend_bundle.py` | 修改 | 历史修复测试固定到经过摘要核验的旧源码，保持升级、回滚与拒绝覆盖断言。 |
| `tests/unit/test_connected_runtime_repair.py` | 修改 | 历史修复测试固定到经过摘要核验的旧源码，保持升级、回滚与拒绝覆盖断言。 |
| `tests/unit/test_desktop_history.py` | 删除 | 删除已退役账号、验证码、管理及账号导出功能的旧用例；退役行为由新接口与权限回归覆盖。 |
| `tests/unit/test_desktop_model.py` | 修改 | 验证服务令牌、退役接口、健康信息、配置与审计边界，使用隔离数据。 |
| `tests/unit/test_direct_models.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/unit/test_documentation_mcp.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/unit/test_local_access.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/unit/test_local_executor.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/unit/test_local_ipc.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/unit/test_local_model_routing.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/unit/test_local_models.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/unit/test_local_patchsets.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/unit/test_local_permissions.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/unit/test_local_recovery.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/unit/test_model_evaluation.py` | 修改 | 同步本机会话契约及相关回归或测试夹具。 |
| `tests/unit/test_server_access.py` | 新增 | 验证服务令牌、退役接口、健康信息、配置与审计边界，使用隔离数据。 |
| `tests/unit/test_server_retirement.py` | 新增 | 验证服务令牌、退役接口、健康信息、配置与审计边界，使用隔离数据。 |

## 验证结果

Python 使用 `scripts/run_coding_validation.py` 的独立工作目录、配置守卫与合成供应商，不加载生产数据库或真实模型密钥。没有付费模型调用。桌面测试使用真实组件/路由，浏览器仅模拟原生 IPC。

| 实际命令（仓库根目录，另有说明除外） | 观察结果 |
| --- | --- |
| `.venv/Scripts/python.exe -X utf8 scripts/run_coding_validation.py --suite tool-evolution` | 449 passed、1 skipped；真实符号链接用例因 Windows 创建权限跳过；包含 API Key 下 MCP 批准/拒绝的新增覆盖 |
| `.venv/Scripts/python.exe -X utf8 scripts/run_coding_validation.py --suite local` | 88 passed，包含无需 --server 的真实执行器子进程 IPC |
| `.venv/Scripts/python.exe scripts/run_coding_validation.py --suite streaming` | 32 passed |
| `.venv/Scripts/python.exe scripts/run_coding_validation.py --suite phase-d` | 19 passed，来源清单、删除文件和 IPC 证据路径可用 |
| `.venv/Scripts/python.exe scripts/run_coding_validation.py --suite direct-models` | 59 passed、1 failed；失败是最终回答完成证据断言，修改前快照也能复现 |
| `.venv/Scripts/python.exe scripts/run_coding_validation.py --suite model-evaluation` | 126 passed、3 failed；失败进入任务执行后得到 output_validation_failed，不是平台认证失败 |
| `.venv/Scripts/python.exe scripts/run_coding_validation.py --suite local-probe` | 56 passed、33 failed；30 项需求解析一致性断言、3 项 context_limit 导致的端到端断言；本机会话、凭据释放、模型快照冻结的 3 个协议/流式组合通过 |
| `.venv/Scripts/python.exe -X utf8 scripts/run_coding_validation.py --suite server-access` | 16 passed；无配置/数据库导入的服务令牌、Host/Origin、重复头与历史 owner 边界 |
| `.venv/Scripts/python.exe -X utf8 scripts/run_coding_legacy_validation.py --suite server-access` | 63 passed；真实旧后端路由、退役接口 404、模型接口、健康权限、SMTP 退役和审计清理；无业务数据库连接 |
| `.venv/Scripts/python.exe -X utf8 scripts/run_coding_validation.py --suite retired-tooling` | 34 passed、1 skipped；历史补丁/回滚和当前源码拒绝生成旧补丁；Windows 符号链接权限不足跳过 |
| `npm test -- src/components/UserMenu.spec.ts`（`apps/desktop`） | 2 passed；最后清理菜单 CSS 后复核 |
| `git -c core.safecrlf=false diff --check -- <上表文件列表>` | 通过；仅检查本轮文件，保留仓库原有其他修改 |
| 变更文档的本地链接核对 | 无缺失目标；历史已删除模块路径改为明确的历史记录 |
| `yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))` 并检查环境键 | 解析通过，不再注入退役账号/SMTP 配置；未启动 Compose 或读取真实环境文件 |
| `node --test scripts/build-remote-client.test.cjs` | 12 passed；无平台源站、预览/发布参数、环境过滤、来源清单和更新渠道保护 |
| 下方 Vitest 命令（`apps/desktop`） | 17 个文件、99 passed |
| `npm run e2e -- local-access.spec.ts documentation-mcp.spec.ts button-tooltips.spec.ts coding-run.spec.ts --grep '首次启动\|本机文档\|侧栏\|功能提示\|窗口缩放\|闭环：' --retries=0`（`apps/desktop`） | 7 passed；MCP、插件占位、账号入口缺失、窗口交互与 Coding 发送闭环 |
| `npm run e2e -- local-access.spec.ts --retries=0`（`apps/desktop`，最后补充历史入口检查） | 1 passed；本机历史入口可见，无平台导出按钮或外部账号请求 |
| `npm run build`（`apps/desktop`） | vue-tsc 与 Vite 通过；Ant Design 分包约 771 kB 的已有体积警告保留 |
| `cargo check --offline --manifest-path apps/desktop/src-tauri/Cargo.toml` | 通过；10 项既有完整后端 dead-code 警告保留 |
| 下方 Ruff 命令 | 50 个实际变动 Python 文件，语法与 Ruff 检查通过 |

```powershell
npm test -- src/api/http.spec.ts src/services/backendStartup.spec.ts src/services/localAccess.integration.spec.ts src/services/localExecutor.spec.ts src/router/index.spec.ts src/RootApp.spec.ts src/components/SettingsView.spec.ts src/components/ProfileSettingsPanel.spec.ts src/components/UserMenu.spec.ts src/components/ExtensionRegistryPanel.spec.ts src/components/CommandPalette.spec.ts src/features/coding/components/CodingSidebar.spec.ts src/api/documentationMcp.spec.ts src/components/DocumentationMcpPanel.spec.ts src/api/modelProviders.spec.ts src/api/modelSecrets.spec.ts src/config/uiFlags.spec.ts
```

```powershell
.venv/Scripts/python.exe -m ruff check scripts/coding_acceptance_identity.py scripts/coding_acceptance_isolation.py scripts/coding_acceptance_local.py scripts/coding_acceptance_models.py scripts/coding_acceptance_transport.py scripts/run_coding_acceptance.py scripts/run_coding_legacy_validation.py scripts/run_coding_validation.py scripts/verify-local-executor.py scripts/verify-unified-client.py src/personal_assistant/api/audit.py src/personal_assistant/api/routes_desktop_model.py src/personal_assistant/api/routes_health.py src/personal_assistant/api/security.py src/personal_assistant/config.py src/personal_assistant/core/models.py src/personal_assistant/core/tenant.py src/personal_assistant/main_api.py src/private_agent_local/app.py src/private_agent_local/cloud.py src/private_agent_local/direct_models.py src/private_agent_local/entry.py src/private_agent_local/local_models.py tests/coding_acceptance/test_s6_acceptance.py tests/coding_acceptance/test_s6_delivery.py tests/coding_acceptance/test_s6_direct_evaluation.py tests/coding_acceptance/test_s6_external.py tests/coding_acceptance/test_s6_local_probe.py tests/coding_acceptance/test_s6_models.py tests/coding_acceptance/test_s6_phase_d.py tests/test_api_security.py tests/test_config_secret_files.py tests/test_health.py tests/test_health_visibility.py tests/unit/test_connected_backend_bundle.py tests/unit/test_connected_runtime_repair.py tests/unit/test_desktop_model.py tests/unit/test_direct_models.py tests/unit/test_documentation_mcp.py tests/unit/test_local_access.py tests/unit/test_local_executor.py tests/unit/test_local_ipc.py tests/unit/test_local_model_routing.py tests/unit/test_local_models.py tests/unit/test_local_patchsets.py tests/unit/test_local_permissions.py tests/unit/test_local_recovery.py tests/unit/test_model_evaluation.py tests/unit/test_server_access.py tests/unit/test_server_retirement.py
```

失败分类与验证限度：

- 直接模型最终文案断言在原始文件快照中复现，同样因“列出目录”缺适用完成证据而没有得到测试期望的最终文案；未放宽断言或修改完成规则。
- 旧验收 `task_prompt` 对 30 道公开题也复现需求解析差异。原模型夹具还在拒绝工具返回 `output: null` 时崩溃，本次增加空输出处理后，剩余端到端失败进一步暴露完成判定问题。对照只用于定位失败，不作为候选身份或发布证据。
- 3 个 local-probe 端到端用例在模型请求前触发 `context_limit`；本轮没有修改上下文策略。其完整归因及其余端到端失败没有全部完成，因此不能宣称扩展模型验收通过。
- 新增退役接口检查最初假设 FastAPI 路由列表均有 path 属性，已改为检查真实请求与 OpenAPI 路径。历史修复测试最初固定到早于升级修复的版本，已根据工具允许摘要核实并固定到 `fe21c54a802212d24bccb6b141417546f4cffa66`，保留全部原有断言后通过。
- 早期浏览器失败来自已删除自动化入口，以及任务完成后过程折叠。已改用插件入口、实际设置导航和展开执行过程，保留原行为断言后复跑通过。
- 早期模型验收出现旧身份目录、旧 profile ID、记录时间影响冻结摘要及临时服务残留；这些迁移问题已修正，未用跳过用例或增加预算获得通过。
- 已查看 API Key 工作区及窄窗口 MCP 截图。未运行全仓库测试，未新打包安装器，未检查已安装客户端、真实供应商 Key 或生产 401。

## 项目记忆

接手已读取 `AGENTS.md`、`docs/project-state.md`、模型直连与当前工具文档，并与 Git、启动链、HTTP 分流、原生参数及测试核对。更新 `docs/project-state.md` 的同日后续状态，同步本机单模式、401 区分、MCP、自动化/插件状态、构建与评测契约、旧后端账号退役、历史数据兼容及验证限制。

此前 README 和直连/更新说明仍描述可选平台登录、服务器账号绑定和旧构建参数。已依据最终源码修正当前说明，保留历史章节并注明适用时间，不将旧服务器故障记录改写为已上线。未建立新记忆系统。

## 风险、限制与假设

- 独立旧后端仅接受原有服务令牌；旧客户端依赖的登录、注册、账号管理及账号导出接口不再可用。历史表映射和迁移保留，不自动清空任何数据。
- 扩展模型验收存在上述失败；发布前仍需独立解决需求解析、上下文和完成判定问题，不能把本次通过项当作完整 Agent 质量验收。
- API Key 供应商的真实 401 仍须由用户配置有效密钥及权限；程序不会绕过供应商鉴权。
- MCP 当前仅为公开 HTTPS 无认证技术文档服务，不包含 stdio、OAuth 或私有文档库。
- 旧平台数据空间不自动并入本机空间，也不自动复制旧 Key。已有本机空间保持原路径及数据。
- 本次仅交付源码和验证结果；已安装的旧客户端不会自动变化，前端与执行器必须同批构建。

## 用户需执行的操作

1. 若使用已经安装的客户端，需要从本次源码重新构建并安装匹配的客户端/执行器。具体构建入口和版本规则见 `docs/archive/legacy/remote-client-updates.md`，本次没有创建安装包或发布更新。
2. 启动后在“设置 → 模型设置”配置供应商、端点、Key 和模型；已有本机配置可继续使用。
3. 需要文档检索时在“设置 → MCP 外部能力”选择项目，配置公开服务并启用选定工具；调用时按原规则审批。
4. 本次未部署旧服务器。如仍维护独立后端，后续部署需使用匹配版本并保留既有服务令牌和数据库；不要套用 1.0.3 账号补丁。无需提供账号密码、API Key 或其他秘密。
