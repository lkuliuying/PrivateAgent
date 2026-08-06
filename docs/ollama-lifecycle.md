# Ollama 生命周期（Windows 交付模式：外部 Ollama 由用户管理）

> **当前状态（2026-08-06）**：R2.2 选定 Windows 交付模式为**外部 Ollama 由用户管理**
> （不托管 CLI 子进程、不引入容器 GPU profile）。本页定义该模式的安装检测、启动、
> 故障分类、测量与退出残留检查，并如实记录边界。容器 GPU profile 的真实 GPU
> healthcheck 未完成前，不宣称容器 GPU 交付完成（`docs/remaining-work-plan-20260806.md` §9）。

## 1. 模式边界

- PrivateAgent 只作为 Ollama 的 **HTTP 客户端**（`PA_OLLAMA_BASE_URL`，默认 `http://127.0.0.1:11434`）；
  不启动、不停止、不升级 Ollama 进程。
- 后端在 Ollama 不可用时仍可启动：`/health` 的 `ollama` 项如实标红，API/MySQL/Chroma 不受影响。
- 不要混用外部应用、手工 `ollama serve` 后台进程与容器实例同时监听同一端口。

## 2. 安装与启动（用户侧，可重复）

1. 安装：`winget install --id Ollama.Ollama -e`（或官网安装包）。安装后默认开机自启并监听 `127.0.0.1:11434`。
2. 拉取模型：
   ```powershell
   ollama pull qwen2.5:14b-instruct-q4_K_M   # 对话模型（PA_LLM_MODEL）
   ollama pull bge-m3                        # embedding 模型（PA_EMBED_MODEL）
   ```
3. 校验：`ollama list` 应列出两个模型；`GET http://127.0.0.1:11434/api/tags` 返回 200。
4. 启动 PrivateAgent，首启配置向导的"测试连接"会校验 MySQL TCP + Ollama `/api/tags` + 模型已拉取。

自动验证脚本（幂等、只读、不启动 Ollama）：

```powershell
uv run python scripts/ollama_lifecycle_check.py --out data\rehearsals\ollama-lifecycle-<date>\report.json
```

输出：安装检测、进程/端口、服务与模型、embedding 冷/热耗时与 P95、模型常驻（`/api/ps`）。
退出码：`0` 健康 / `1` 模型缺失或测量失败 / `2` 服务未运行（按本文档启动后重试）。
最新证据：`data/rehearsals/ollama-lifecycle-20260806/report.json`（embed P50 87ms、P95 111ms、
bge-m3 常驻 1.6 GB）。

## 3. 诊断分类（`/health` 与诊断中心可区分）

| 症状 | 判定 | `/health` 字段 | 用户动作 |
|---|---|---|---|
| 服务未启动 | 连接被拒（未监听） | `ollama.error_code = ollama_not_running` | 启动 Ollama：`ollama serve` 或开始菜单"Ollama" |
| 请求超时 | 3s 无响应 | `ollama.error_code = ollama_timeout` | 检查负载/网络/杀毒软件；慢机器调大健康超时 |
| 模型缺失 | `/api/tags` 200 但缺模型 | `missing_models` + `error_code = ollama_model_missing` | `ollama pull <模型>`（状态页提示具体模型名） |
| HTTP 异常 | `/api/tags` 非 200 | `ollama.error_code = ollama_http_error` | 核对 `PA_OLLAMA_BASE_URL` |
| GPU 不可用 | **无法从 Ollama HTTP API 探测**（已知边界） | 不伪装通过；推理慢时表现为超时分类 | Ollama 自动 CPU fallback；GPU 状态由 `ollama ps` 查看 |

实现：`src/personal_assistant/core/provider.py::OllamaProvider.health()`。

## 4. 崩溃 / 重启 / 退出 / 升级

- **崩溃与重启**：Ollama 崩溃后由用户重启（桌面托盘图标或 `ollama serve`）；PrivateAgent 的下一次
  `/api/tags` 探测会自动恢复 `ok`，无需重启后端。
- **退出残留检查**：
  - 外部模式下 Ollama 进程属于用户管理范围；应用退出只负责清理自己的 sidecar 与子进程
    （已有自动化：`scripts/sidecar_smoke.py` 验证 `/health` 后 kill_tree 无残留；关闭窗口后
    `tasklist | findstr personal-assistant-server` 无结果）。
  - `scripts/ollama_lifecycle_check.py` 报告 `ollama.exe` 进程与端口现状，作为外部模式残留快照。
- **升级**：Ollama 升级后模型通常保留（`%USERPROFILE%\.ollama\models`）；升级后重新 `ollama list`
  校验，必要时重跑生命周期检查。PrivateAgent 侧无需动作。
- **CPU fallback**：Ollama 无 GPU 时自动用 CPU 加载模型（较慢）；后端不静默挂起——
  `PA_LLM_CONTEXT_LENGTH` 与推理超时按 CPU 环境调低，慢响应进入 `ollama_timeout` 分类并给出可读提示。

## 5. 冷/热启动与性能测量（2026-08-06 基线）

`data/rehearsals/ollama-lifecycle-20260806/report.json`：

| 指标 | 值 |
|---|---|
| embedding 冷调用（模型已常驻时首次） | 75 ms |
| embedding 热调用 P50 / P95 | 87 ms / 111 ms |
| 常驻模型 | `bge-m3:latest`（1.6 GB） |
| 对话模型 | `qwen2.5:14b-instruct-q4_K_M`（按需加载） |

模型常驻由 Ollama 管理（`/api/ps` 观察）；embedding P95 远低于 RAG 评测 2s 门禁。

## 6. 已知边界（如实记录）

- 外部模式无法从 Ollama HTTP API 探测 GPU 可用性；"GPU 不可用"不伪装为通过，
  以超时/慢响应分类呈现，GPU 状态由用户侧 `ollama ps` 查看。
- 本页证据不等于容器 GPU profile 交付；也未把本地镜像证据冒充 GitHub Release。
- 旧的 Desktop wrapper 曾出现 `0xC0000142`：该现象属于旧版托盘启动缺陷，
  当前模式以"用户启动 Ollama + 应用只做 HTTP 客户端 + 明确错误分类"规避，
  不再依赖任何应用内托管的 `ollama serve` 后台进程。
