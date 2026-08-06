# 发布检查清单（第五阶段 M4）

> 对应 `docs/phase5-plan.md` M4 与 `docs/phase5-requirements.md` 5.7。
> 每次发布按本清单逐项执行并留存结果。发布失败时按 §7 回滚。

> **0.2.1 候选 QA 记录（2026-08-06）**：升级 smoke run #27 `0.2.0 → 0.2.1` passed
> （数据保留 `preserved=true`）；run #28 回滚往返（卸载 0.2.1 数据保留 → 重装 0.2.0 → 再升级回 0.2.1）；
> updater 签名正向 `OK`、篡改 1 字节 `FAILED`。安装包 unsigned（`dist/codesign-status-0.2.1.json`）。

---

## 1. 发布前置（代码与构建）

| 步骤 | 命令 | 期望 |
|---|---|---|
| 快速检查 | `scripts\release-check.bat`（pytest / npm build / cargo check / alembic current） | 全部 OK |
| 完整证据（phase8） | `scripts\release-check-full.bat`（pytest / ruff / compileall / npm build+test / e2e / cargo check+test / sidecar smoke / alembic current / git diff / 诊断脱敏 / Compose 配置 / latest.json 校验） | 输出 `dist\release-check-<version>.json+.md`，`failed=0`、`ok=true`、无 blocker |
| 发布 manifest | `uv run python scripts\generate_release_manifest.py --write`（在完整检查**之后**执行；checklist 由报告步骤生成） | `dist\release-manifest-<version>.md` 与报告同一 commit 且摘要一致 |
| 性能基线（phase8） | `uv run python scripts\measure_perf_baseline.py` | `dist\perf-baseline.md`，无 blocker |
| 健康检查 | 启动后端，`GET /health` | API / Ollama / MySQL / ChromaDB 四项全绿 |
| 迁移 head | `uv run alembic current` | `0021 (head)`（与代码模型一致） |

> `release-check.bat` 中 cargo check 在无 MSVC 时 SKIP（不记为失败）；发布 Windows 安装包前必须确保 MSVC 可用。
> 完整 release check 的顺序固定：先跑 `release-check-full.bat`，再刷新 manifest，避免 manifest 固化旧报告。sidecar 未构建时 `sidecar_smoke` 如实标记 skipped，不伪装通过。

## 1.1 第八阶段发布检查（phase8）

- 桌面 E2E：`cd apps\desktop && npm run test`（Vitest 组件）+ `npm run e2e`（Playwright smoke）。
- 代码签名：`scripts\sign_installer.py`（有证书走 signtool sign/verify + 重签 .sig；无证书写 unsigned 说明 + `code_signed: no`）。
- 备份恢复演练：`POST /backup/restore/drill`（manifest 校验 + Chroma/MySQL 一致性）；`GET /backup/migration-runbook`。
- 升级 smoke：`scripts\upgrade_smoke.py --runbook`（真实 vN->vN+1 待真实环境执行）。
- 扩展注册表：`GET /extensions`（command/diagnostic/maintenance 三类可见）。
- 本地集成：`POST /integrations/preview` + `/integrations/import` + `DELETE /integrations/imports/{id}`（可撤销）。

## 2. 构建 NSIS 安装包

```bash
# 首次 tauri build 需从 GitHub 下载 NSIS 工具链；不可达时先设代理：
set HTTPS_PROXY=http://127.0.0.1:10808

scripts\build-release.bat
```

产出（`apps\desktop\src-tauri\target\release\bundle\nsis\`）：

- `PrivateAgent_<version>_x64-setup.exe`（NSIS 安装包）
- `PrivateAgent_<version>_x64-setup.exe.sig`（updater 签名；需 `%USERPROFILE%\.tauri\personal-assistant.key`）
- `dist\release-manifest-<version>.md`（自动生成，含 sha256 / git commit / 校验清单）

## 3. 生成 updater 发布清单

```bash
uv run python scripts\generate-latest-json.py --notes "<发布说明>" --out dist\latest.json
```

自动从 `tauri.conf.json` 读版本号、从 git remote 读 repo、从 `.sig` 读签名、对安装包文件名做百分号编码（updater 的 HTTP 客户端要求 ASCII URL）。校验：

- `version` 与 `tauri.conf.json` 一致。
- `signature` 与磁盘 `.sig` 一致。
- `url` 指向 `https://github.com/<owner>/<repo>/releases/download/v<version>/<encoded-installer>`。

## 4. 上传 GitHub Release 资产

1. 在 GitHub 创建 Release，tag = `v<version>`（与 `latest.json` 的 tag 一致）。
2. 上传**三个**资产：
   - `PrivateAgent_<version>_x64-setup.exe`
   - `PrivateAgent_<version>_x64-setup.exe.sig`
   - `latest.json`
3. Release 说明写入 changelog 与 SmartScreen 风险提示（未代码签名时）。

> updater endpoint（`tauri.conf.json`）指向 `.../releases/latest/download/latest.json`，所以**最新** Release 的 `latest.json` 即生效版本。发布新版只需让新 Release 成为 latest；回滚只需让旧 Release 重新成为 latest 或覆盖 `latest.json`。

## 5. 安装 / 升级 / 卸载 QA 矩阵

在干净 Windows 机器（或已重命名 `%APPDATA%\personal-assistant` 的机器）逐项验证：

### 5.1 干净安装
- [ ] 双击安装包，安装成功（`installMode: currentUser`，无需管理员）。
- [ ] 开始菜单出现 `PrivateAgent`。
- [ ] 首启进入配置向导（`ConfigWizard.vue`）。

### 5.2 首启配置向导
- [ ] 环境检测：MySQL（127.0.0.1:3306）/ Ollama（127.0.0.1:11434）可达性正确。
- [ ] 填写连接 -> 测试连接：MySQL TCP + Ollama `/api/tags` + 模型已拉取校验。
- [ ] 模型缺失时提示 `ollama pull <model>`。
- [ ] 保存并启动后端 -> 轮询 `/health` -> 四项全绿进入主界面。
- [ ] `.env` 写入 `%APPDATA%\personal-assistant\.env`，字段为 `PA_` 前缀。

### 5.3 重新配置
- [ ] 设置页"重新配置连接"重新打开向导，保存后重启生效。

### 5.4 依赖异常提示
- [ ] MySQL 不可达：状态页 MySQL 红，提示启动 MySQL / 检查账号。
- [ ] Ollama 不可达：状态页 Ollama 红，提示 `ollama serve`。
- [ ] 模型未拉取：向导测试连接提示 `ollama pull`。

### 5.5 功能 smoke
- [ ] 普通聊天：流式输出、停止生成、会话历史持久化。
- [ ] 导入一份小文档（PDF/MD/TXT）：状态 ready，RAG 引用正确。

### 5.5.1 第七阶段可信日常路径 smoke
- [ ] 今日页：空数据不显示固定演示日程/文档/洞察；有数据时显示真实提醒、收件箱、目标、简报、维护健康和最近来源。
- [ ] 全局搜索：搜索文档名、任务关键词、记忆关键词能返回对应对象并可跳转。
- [ ] 命令面板：可创建收件箱项、创建提醒、打开诊断中心、运行健康检查。
- [ ] 快速捕获：剪贴板或手动文本可转收件箱/提醒/记忆候选。
- [ ] OCR 队列：OCR 未安装或失败时显示明确原因、任务状态和降级动作。
- [ ] 通知中心：导入、提醒、任务、备份、Provider 失败等结果可回看，危险操作走统一确认。
- [ ] 诊断中心：展示 health、版本、迁移 head、最近错误、Provider 失败、维护健康和数据完整性摘要。
- [ ] 诊断包：导出包包含 `diagnostics.json` / `health.json` / `settings.redacted.json` / `recent-errors.log` / `version.txt` / `migration.txt`，且不含 API key、数据库密码、完整聊天、文档原文或敏感记忆。
- [ ] 数据完整性：至少能展示软引用悬空和索引不一致检查结果；修复计划先预览再执行。
- [ ] Provider 治理：缺 key、认证失败、网络、超时、限流、模型不存在和服务错误有明确分类，审计记录包含耗时和失败原因。

### 5.6 退出与进程清理
- [ ] 关闭窗口后 `tasklist | findstr personal-assistant-server` 无残留（`RunEvent::Exit` kill sidecar）。
- [ ] 连续启动/退出 3 次无孤儿进程。

### 5.7 自动更新（v0.1.0 -> v0.1.1 升级 smoke）
- [ ] 旧版本（如 v0.1.0）已安装并配置可用。
- [ ] 发布 v0.1.1（构建 + 签名 + `latest.json` + 上传 Release）。
- [ ] 旧版本设置页"检查更新"发现 v0.1.1，展示版本/时间/说明。
- [ ] "下载并安装"：sidecar 被终止 -> 安装 -> 重启。
- [ ] 重启后版本号为 v0.1.1，旧会话 / 知识库 / 设置 / 记忆 / 任务仍在。
- [ ] 签名错误场景：篡改 `latest.json` 的 signature -> 更新被拒绝，`UpdateChecker.vue` 显示"签名验证失败"，当前版本仍可用。
- [ ] 无更新场景：已是最新时显示"当前已是最新版本"。

### 5.8 覆盖安装
- [ ] 不卸载直接双击新版本安装包 -> 升级，配置与数据保留。

### 5.9 卸载
- [ ] 卸载后应用程序文件移除。
- [ ] `%APPDATA%\personal-assistant\` **保留**（默认不删用户数据；见 §6）。

## 6. 用户数据目录行为

打包模式用户数据目录：`%APPDATA%\personal-assistant\`

| 内容 | 卸载 | 覆盖安装 / 自动更新 |
|---|---|---|
| `.env`（连接配置） | 保留 | 保留（不覆盖） |
| `chroma/`（向量库） | 保留 | 保留 |
| `logs/`（后端日志） | 保留 | 保留（追加） |
| 备份导出文件 | 保留 | 保留 |
| MySQL 业务数据 | 不受影响（外部 MySQL） | sidecar 启动时 `alembic upgrade head` 迁移 |

> NSIS `installMode: currentUser` 默认不删 `%APPDATA%`。若需卸载清空，须显式配置 NSIS 脚本——当前**故意保留**，避免误删知识库与配置。

## 7. 数据迁移与回滚

### 7.1 升级迁移测试
- [ ] 旧版本数据库 schema（如 v0.1.0 的 head）-> 新版本 sidecar 启动 `alembic upgrade head` 成功。
- [ ] 迁移失败不崩溃：MySQL 未就绪时 `server_entry.py` 捕获异常继续启动，状态页暴露 MySQL 不可用。
- [ ] 重大迁移（破坏性变更）前在发布说明提示用户先备份（设置页"导出备份"）。

### 7.2 回滚
- **应用层回滚**：撤回 GitHub Release 资产，或把旧 Release 重新设为 latest（覆盖 `latest.json` 指回稳定版本）。
- **用户层回滚**：卸载新版 -> 重装旧版安装包；用户数据目录未删，配置与数据可直接复用。
- **数据库回滚**：若迁移破坏数据，用发布前备份（`%APPDATA%\personal-assistant` 下的备份导出 + MySQL dump）恢复；Alembic downgrade 仅在迁移提供 downgrade 时可用。

## 8. 发布清单模板

每次发布填写（`scripts\generate_release_manifest.py --write` 自动生成大部分字段）：

```text
version:
date:
git_commit:
branch:

backend_tests:        release-check.bat 结果
frontend_build:
cargo_check:
alembic_current:
phase7_smoke:
health_check:

sidecar_path:
sidecar_sha256:
installer_path:
installer_sha256:
signature_path:       (.sig)
latest_json_path:     dist/latest.json

release_url:          https://github.com/<owner>/<repo>/releases/tag/v<version>
updater_smoke:        vN -> vN+1 结果
install_smoke:
upgrade_smoke:
uninstall_smoke:

code_signed:          是 / 否（未签名则发布说明含 SmartScreen 提示）
known_issues:
rollback_plan:
```

## 9. 当前已知限制

- ✅ **打包 sidecar 连 MySQL 8**：旧构建的 sidecar 缺 `cryptography`，连 MySQL 8 默认 `caching_sha2_password` 认证会失败（状态页 MySQL 红）。已在 `personal_assistant.spec` 显式加入 `hiddenimports += ["cryptography"]`，并于 2026-07-08 重新构建 v0.1.1 sidecar 后验证 `/health` API / Ollama / MySQL / ChromaDB 全绿。后续发布仍需按 §5.2 复测。
- ✅ **第七阶段自动化验证**：2026-07-08 已验证 `pytest -q` 197 通过、`npm run build` 通过、`cargo check` 通过、`alembic current -> 0010 (head)`。桌面窗口级 Playwright/Tauri E2E 尚未接入，发布前按 §5.5.1 做人工 smoke 或补自动化脚本。
- 安装包未代码签名：SmartScreen 拦截，需手动绕过（见 `docs/signing-and-keys.md` §2）。
- macOS / Linux 仅有构建脚本与差异清单，未实测（见 `docs/cross-platform.md`）。
- onefile sidecar 真冷首启（重启后首次）较慢，主要成本是 ChromaDB lifespan 初始化（非解压）；onedir 评估见 `docs/phase5-plan.md` M5，结论暂不切换。
