# 故障排查

## 1. sidecar 拒绝启动

症状：`database migration failed; refusing to start (<ErrorType>)`。

处理：

1. 不要反复启动或绕过迁移。
2. 核对 MySQL 可达、Credential Manager 中凭据和数据库名称。
3. 对目标库只读执行 `uv run alembic current`。
4. 如果不是期望 revision，先查看 `docs/database-upgrade-runbook.md` 并在 clone 上复现。
5. 不要在生产主库上运行 `prepare_test_database.py` 或测试 fixture。

日志只给异常类型是刻意的，驱动正文可能包含 DSN 或 SQL 参数。

## 2. API 返回 401 或 403

- 确认请求携带本次 sidecar 启动生成的 Bearer token；旧 token 在重启后失效。
- 确认 Host 是 `127.0.0.1`/`localhost` 和实际动态端口。
- 确认 Origin 在 `PA_API_ALLOWED_ORIGINS` 的精确列表中。
- 不要为了临时调试把 API bind 到 `0.0.0.0`。
- 浏览器直接访问受保护端点不会自动拥有 Tauri launch token。

## 3. Ollama 不可用

先检查：

```powershell
ollama list
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

确认已有 `qwen2.5:14b-instruct-q4_K_M` 和 `bge-m3`，然后启动 `ollama serve`。

本机旧版 Ollama Desktop 若以 `0xC0000142` 退出，说明 GUI wrapper/DLL 初始化失败，不等同于模型损坏。可在受控终端直接运行安装目录中的 `ollama.exe serve` 验证服务；长期应升级或修复 Ollama 安装，不能把临时后台进程当成已部署服务。

## 4. RAG 有质量但门禁失败

查看评测报告中的 `status`、`reviewed`、`failures` 和 P95：

- `dependency_unavailable`：embedding 服务或模型不可用。
- `gate_failed` 且质量指标好：常见原因是 P95 超阈值或 case 未人工复核。
- `rollout_ready=false`：不得打开 versioned retrieval，即使 Recall@K 为 1。

2026-08-02 首次隔离演练 P95 为 13.4 秒，但 Ollama server 端热态请求仅约 40–370 ms。根因是 `OllamaProvider` 每次调用都重建 embedding client；缓存后 legacy/versioned P95 分别降至 452/438 ms 并通过 2 秒技术阈值。若再次回退到秒级，先确认 provider 实例和 embedder 是否被复用，再检查模型常驻、GPU offload 和冷/热启动；不要降低阈值掩盖问题。4 个 case 仍需人工复核。

## 5. 文档、chunk 和向量不一致

先运行只读 profile/validation，避免直接 reindex-all：

```powershell
uv run python scripts/profile_rag_data_quality.py --output data/analysis/rag-profile.json
uv run python scripts/validate_rag_data_quality.py `
  --profile data/analysis/rag-profile.json `
  --output data/analysis/rag-validation.json
```

版本化索引检查 active head、manifest、DB chunk count、vector count 和 Chroma collection。构建失败应保留旧 active/legacy；不要先删除旧 collection。

## 6. `uv` 缓存拒绝访问

把缓存指向当前用户或工作区可写目录：

```powershell
$env:UV_CACHE_DIR = "F:\Program\Agent\.uv-cache"
uv run pytest -q
```

路径应按实际工作区调整，不要复用系统目录或提升整个终端权限。

## 7. 测试数据库保护触发

症状：fixture 或脚本拒绝连接，因为数据库名不像专用测试库。

处理：设置 `PA_TEST_DB_URL` 指向独立、可清理的数据库；不要修改守卫来接受 `personal_assistant`。迁移演练使用来源专属 `_preupgrade_<UTC timestamp>` clone，不使用测试 fixture 清理。

## 8. MCP server 无法启用或发现

- 确认 `PA_MCP_ENABLED=true` 仅用于受控验收。
- server 必须分别 trusted、enabled，并设置工具 allowlist。
- stdio executable 必须是已存在的绝对路径，不能是 shell 命令字符串。
- HTTP 默认必须 HTTPS，不能含 URL 凭据、重定向或解析到私网/环回地址。
- 带认证连接必须使用 MCP 面板的原生凭据窗口；不要把 token 写入 URL、普通 env 或 server JSON。
- `credential_unavailable`：确认别名与引用一致、系统凭据仍存在，并在新增/替换凭据后重启桌面 sidecar。删除共享凭据不会静默删除数据库引用，引用会保持失败关闭。
- 静态认证当前支持 stdio secret env、HTTP Bearer 和受限 API-key header；OAuth 服务尚不能完成授权生命周期。

## 9. Tauri / Rust 构建失败

- `link.exe not found`：安装 MSVC Build Tools，使用 `scripts\run-tauri-dev.bat` 或 `scripts\cargo-check-tauri.bat`。
- 首次 NSIS 下载超时：检查 GitHub 网络；代理只在当前终端按组织策略设置。
- sidecar 文件占用：正常退出 Tauri 后确认 watchdog 已清理；不要盲目终止所有 Python/Ollama 进程。

## 10. Playwright 用例通过但发布检查不退出

旧路径由 Playwright 通过 `npm → cmd → Vite` 多层进程启动开发服务器，Windows 上可能在 13 个用例全部通过后卡在子进程回收。完整发布检查现会直接启动随机 loopback 端口上的 Vite、把地址通过 `PA_E2E_BASE_URL` 传给 Playwright，并在结束时验证服务进程已退出。若再次发生，检查 `run_managed_e2e_step` 的 Vite 启动日志和 `managed Vite process did not exit`，不要把超时报告当成通过，也不要批量终止系统中的所有 Node 进程。

## 11. Docker / Compose 启动失败

- `docker compose config` 提示 secret path 缺失：先复制 `.env.container.example`，再运行 `scripts/generate_container_secrets.py --yes`；不要把值直接写回 env 文件。
- `failed to connect to docker API`：Docker CLI 已安装但 daemon 未启动。启动 Docker Desktop 后先重跑 `docker version`，不要把配置解析通过误写成镜像已构建。
- API 因 bind 策略退出：容器必须同时设置 `PA_API_HOST=0.0.0.0`、`PA_API_ALLOW_NON_LOOPBACK_BIND=true` 和有效的 32 字符以上 Bearer secret；源码/Tauri 模式不应设置该开关。
- API healthcheck 401：确认 `api_token` secret 已挂载且没有在生成后单独替换文件。轮换 token 应停止 stack 后作为独立操作执行。
- 容器无法访问宿主 Ollama：检查 `host.docker.internal`/`host-gateway`；或启用 `ollama-gpu` profile 并把 URL 改为 `http://ollama:11434`。
- 不要用 `down --volumes` 排障。它会删除 MySQL、Chroma 和模型卷；只有完成备份/恢复验证并明确授权后才可删除。

## 12. 收集安全诊断

优先使用应用诊断中心导出脱敏包。共享前检查包内只有 health、版本、迁移、脱敏 settings 和错误摘要，不含 API key、数据库密码、完整聊天、文档正文或敏感记忆。

若仍无法定位，记录：应用版本、schema revision、平台、错误类型、相关 feature flag、复现步骤和报告路径；不要粘贴 `.env`、DSN 或凭据窗口截图。
