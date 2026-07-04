# 私人助手 Agent · M4 打包预研

> 对应 `docs/phase1-plan.md` M4（非硬验收）。目标：验证 Tauri 启动 Python sidecar 的方案、端口协商、依赖说明，形成可行性结论与操作文档。不要求产出完美安装包。

---

## 1. 目标与范围

M4 验收项：
1. 验证 Tauri 启动 Python sidecar 的方案。
2. 验证前端与 sidecar 的 localhost 端口协商。
3. 写清运行依赖：Ollama、MySQL、模型文件需单独安装/启动。
4. README 写开发启动、迁移、模型准备、常见问题。

结论：**机制可行**。Tauri 2 + `tauri-plugin-shell` sidecar + PyInstaller onefile 后端 + Tauri 分配端口协商，全链路打通。完整安装包（签名/卸载/依赖向导）留第五阶段。

---

## 2. 整体架构

```
┌──────────────────────────────────────────────────────┐
│  Tauri 桌面壳（apps/desktop/src-tauri，Rust）          │
│  · setup: 分配空闲端口 → spawn sidecar → 等端口就绪    │
│  · get_api_port 命令 → 前端                            │
│  · RunEvent::Exit → kill sidecar 子进程                │
└──────────────┬───────────────────────────────────────┘
               │ spawn + PA_API_PORT env
┌──────────────▼───────────────────────────────────────┐
│  personal-assistant-server.exe（PyInstaller onefile） │
│  server_entry.py: 自动迁移 + uvicorn(reload=False)    │
└──────────────┬───────────────────────────────────────┘
               │ HTTP + SSE（127.0.0.1:<port>）
┌──────────────▼───────────────────────────────────────┐
│  Vue 3 前端：ensureApiBase() → get_api_port → 动态 base │
└──────────────────────────────────────────────────────┘
```

---

## 3. 端口协商（Tauri 分配空闲端口）

**设计**：避免固定 8000 冲突，Tauri 全程掌握端口。

| 步骤 | 位置 | 实现 |
|---|---|---|
| 1. 分配端口 | `lib.rs` setup | `TcpListener::bind("127.0.0.1:0")` 让 OS 分配，立即释放供 sidecar 复用 |
| 2. 传给 sidecar | `lib.rs` spawn | `.env("PA_API_PORT", port.to_string())`，pydantic-settings 自动读 `PA_API_PORT` |
| 3. 等就绪 | `lib.rs` | `wait_for_port` 轮询 TCP 连通（30s 超时） |
| 4. 给前端 | `lib.rs` command | `get_api_port` 返回 `Option<u16>`，存于 `SidecarState` |
| 5. 前端取用 | `api.ts` | `ensureApiBase()` 调 `invoke("get_api_port")`，缓存 base |
| 6. dev 回退 | `api.ts` | `isTauri()` 为 false 或端口 None → 回退 `http://127.0.0.1:8000`（手动后端） |
| 7. 退出清理 | `lib.rs` RunEvent::Exit | `child.kill()` 终止 sidecar |

dev 模式下没有 PyInstaller 产物，`app.shell().sidecar()` 找不到二进制返回 Err，setup 降级为 `port: None`，前端回退 8000 —— 开发流不变。

---

## 4. Python 后端打包（PyInstaller）

### 4.1 模式：onefile
Tauri `externalBin` 要求单个二进制文件（`<name>-<target-triple>.exe`）。onefile 自包含，代价是启动时解压到临时 `_MEIPASS`（首启略慢，sidecar 全生命周期只启动一次，可接受）。产物约 **80 MB**（chromadb + onnxruntime + langchain + sqlalchemy + fastapi + uvicorn）。

### 4.2 spec：`personal_assistant.spec`
关键点：
- **`collect_submodules("personal_assistant")`**：`server_entry.py` 用 `uvicorn.run("personal_assistant.main_api:app", ...)` 是**字符串引用**，PyInstaller 静态分析看不到，必须显式收集整个包，否则运行时 `No module named 'personal_assistant.core'`。
- `collect_submodules("chromadb" / "onnxruntime" / "langchain*" / "langgraph")`：这些库大量动态 import。
- `datas`：`alembic/` + `alembic.ini`（进程内迁移需要），`chromadb` / `onnxruntime` 数据文件。
- `pathex=["src"]`。

### 4.3 已知无害 WARNING
- `chromadb.server.fastapi`：缺 `opentelemetry.instrumentation`（chromadb 可选 telemetry，不用服务端模式无影响）。
- `onnxruntime.quantization`：缺 `onnx`（量化工具，运行时不碰）。
- `_cffi_backend` / `MySQLdb` / `pysqlite2` / `tzdata`：可选，本项目用 aiomysql，不需要 MySQLdb。

### 4.4 数据目录（开发 vs 打包）
`config.py` 用 `sys.frozen` 判断：
- 开发（`python -m` / uvicorn）：`./data`（项目根，便于调试）。
- 打包（PyInstaller frozen）：`%APPDATA%/personal-assistant`（Windows）/ `~/.local/share/personal-assistant`（Unix）。
- `PA_DATA_DIR` 可强制覆盖；`chroma_dir` / `log_dir` 由 `data_dir` 派生。

### 4.5 数据库迁移（无 alembic CLI）
`server_entry.py` 启动前进程内调用 `alembic.command.upgrade(cfg, "head")`：
- `cfg.set_main_option("script_location", <_MEIPASS>/alembic)`。
- `env.py` 从 `settings.db_url` 注入 URL（无需在 ini 硬编码）。
- 迁移失败不阻断启动（MySQL 可能未就绪），前端状态页展示 MySQL 不可用。

### 4.6 打包脚本
`scripts/build-sidecar.bat`：`uv run pyinstaller personal_assistant.spec --noconfirm` → 复制 `dist/personal-assistant-server.exe` 到 `apps/desktop/src-tauri/binaries/personal-assistant-server-x86_64-pc-windows-msvc.exe`（覆盖 dev 占位）。

---

## 5. Tauri sidecar 配置

| 文件 | 改动 |
|---|---|
| `Cargo.toml` | 加 `tauri-plugin-shell = "2"` |
| `tauri.conf.json` | `bundle.externalBin: ["binaries/personal-assistant-server"]` |
| `capabilities/default.json` | 保持 `core:default`（sidecar 从 Rust 调用，不需前端 shell 权限） |
| `src/lib.rs` | `tauri_plugin_shell::init()` + setup 启动/端口/生命周期 + `get_api_port` 命令 |
| `src-tauri/binaries/` | dev 占位文件（让 build.rs 编译通过），打包时替换为 PyInstaller 产物 |

**关键坑**：Tauri 的 `externalBin` 在**编译时**（build.rs）强制检查 sidecar 二进制存在，dev 模式没产物会编译失败（`tauri dev` 退出）。解法：在 `binaries/` 放一个占位文件（内容任意，build.rs 只检查存在不验证 PE），dev 模式 setup spawn 占位失败 → fallback 8000；打包时用真实 exe 覆盖。

---

## 6. 运行依赖（用户单独安装）

sidecar 不打包这些，需用户本机具备：

| 依赖 | 说明 |
|---|---|
| **Ollama** | `ollama pull qwen2.5:14b-instruct-q4_K_M` + `ollama pull bge-m3` |
| **MySQL 8** | 建库 `CREATE DATABASE personal_assistant CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;` |
| **sidecar 配置** | `%APPDATA%/personal-assistant/.env`：至少 `PA_DB_URL=mysql+aiomysql://root:<pwd>@127.0.0.1:3306/personal_assistant?charset=utf8mb4`（首次运行需创建，第五阶段做配置 UI） |

---

## 7. 端到端验证

已验证（tauri dev + 真实 sidecar，2026-07-04）：

- **Tauri 拉起 sidecar**：setup 分配端口（实测 3828），`app.shell().sidecar()` spawn 真实 exe，传 `PA_API_PORT`。
- **自动迁移**：sidecar 启动时进程内 `alembic upgrade head` 跑通（`MySQLImpl`），MySQL 表就绪。
- **端口协商**：sidecar uvicorn 监听 3828；Tauri `wait_for_port` 确认就绪，打印 `[sidecar] 就绪 port=3828`。
- **前端动态连接**：`ensureApiBase()` → `invoke("get_api_port")` → 3828；webview 成功请求 `/sessions`（3 会话）、`/sessions/{id}/messages`（会话1=4条/2=3条/3=7条）、`/documents`、`/settings`、`/health`，全 200。
- **设置页轮询**：每 5s `/health` + `/settings`，SettingsView 挂载正常。
- **数据目录**：`%APPDATA%/personal-assistant/chroma` 正确。
- **Ollama**：`/api/tags` 连通，模型可用。

未在本轮单独验证（信任 M1–M3 已验证逻辑 + 动态端口已通）：
- 聊天流式 `streamChat`（用动态 base，逻辑同 M1–M3）。
- 退出时 `RunEvent::Exit` kill sidecar（关窗口触发，逻辑已实现）。

---

## 8. 可行性结论

- ✅ Tauri 2 + `tauri-plugin-shell` sidecar 机制可行，生命周期/端口协商/退出清理全链路打通。
- ✅ PyInstaller onefile 打包 FastAPI + chromadb + langchain 后端可行（~80MB），关键在 `collect_submodules("personal_assistant")` 处理字符串 import。
- ✅ 端口协商（Tauri 分配 + env + Tauri command）避免固定端口冲突，dev/build 行为一致降级。
- ⚠️ 外部依赖（Ollama/MySQL/模型）不能打包，需用户单独装 + 配置 `.env`，是分发的主要门槛。

## 9. 第五阶段建议

1. **完整安装包**：NSIS/MSI 安装器 + 代码签名 + 卸载。
2. **依赖检测向导**：首启检测 Ollama/MySQL/模型是否就绪，缺失给引导。
3. **配置 UI**：首次运行引导填写 `PA_DB_URL` 等，写入 `%APPDATA%/personal-assistant/.env`，免手动编辑。
4. **onedir + Tauri resources**：onefile 首启解压慢，第五阶段可切 onedir（启动快）+ Tauri `resources` 打包整个目录，sidecar 用绝对路径调起。
5. **跨平台**：macOS/Linux 的 sidecar target triple + PyInstaller 产物。
6. **体积优化**：排除 onnxruntime（若确认 chromadb 用 Ollama embedding 不触发默认 embedding）可显著减小体积，需运行时验证。
