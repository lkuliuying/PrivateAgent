# 发布检查清单（第五阶段 M4）

> 对应 `docs/phase5-plan.md` M4 与 `docs/phase5-requirements.md` 5.7。
> 每次发布按本清单逐项执行并留存结果。发布失败时按 §7 回滚。

---

## 1. 发布前置（代码与构建）

| 步骤 | 命令 | 期望 |
|---|---|---|
| 快速检查 | `scripts\release-check.bat`（pytest / npm build / Tauri Rust gate / alembic current） | 全部 OK |
| 完整证据（phase8） | `scripts\release-check-full.bat`（+ npm test / e2e / 诊断包脱敏 / latest.json 校验） | 输出 `dist\release-check-<version>.json+.md`，无 blocker |
| 性能基线（phase8） | `uv run python scripts\measure_perf_baseline.py` | `dist\perf-baseline.md`，无 blocker |
| 健康检查 | 启动后端，`GET /health` | API / Ollama / MySQL / ChromaDB 四项全绿 |
| 迁移 head | `uv run alembic current` | 与代码模型一致（当前 `0012 (head)`） |

> `release-check-full.bat` 将 pytest、前端构建、Vitest、Playwright、Cargo、Alembic 与诊断包脱敏都视为发布阻断项；缺失工具也会失败。`latest.json` 在尚未生成发布资产时仍是可选检查。

### 1.1 测试数据隔离

- pytest 与完整发布检查会在当前 MySQL 服务上创建唯一的 `pa_test_*` 数据库，并把运行时文件放到 `.run/pytest/` 或 `.run/release-check/`；不会复用开发库 `personal_assistant`。
- 自动清理只有在“数据库名、运行令牌、连接 URL”三项同时匹配时才允许执行 `DROP DATABASE`。无法证明归属时会失败关闭，不会回退到开发库。
- 默认连接账号需要 `CREATE DATABASE` / `DROP DATABASE` 权限。CI 也可显式设置 `PA_TEST_DB_URL`，但数据库名必须严格以 `pa_test_` 开头；显式数据库只验证和使用，不由测试进程删除。

## 1.2 第八阶段发布检查（phase8）

- 桌面 E2E：`cd apps\desktop && npm run test`（Vitest 组件）+ `npm run e2e`（Playwright smoke）。
- Windows 视觉回归：`cd apps\desktop && npm run e2e:visual`；覆盖 Light/Dark、高对比、
  900×600 到 1920×1080 响应式、Today/任务/对话关键区，并与受控基线逐像素比较。
- 生产代码签名：`scripts\build-release.bat --production`；缺证书、证书链/时间戳验证失败或 updater 私钥缺失均阻断。无证书模式仅允许开发构建，不得发布。
- Windows 生命周期：手动运行 GitHub Actions `Windows release assurance` 的 `production` lane，并保存 `windows-lifecycle.json`；自签名 lane 只证明机制，不代表生产身份。
- 真实服务发布压力门禁：按 `docs/real-service-stress-testing.md` 运行 15 分钟稳态配置；
  大文档/夜间配置另行留存 `dist/stress/*.json` 与 `.md`，清理证明必须全部为 true。
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

- `私人助手_<version>_x64-setup.exe`（NSIS 安装包）
- `私人助手_<version>_x64-setup.exe.sig`（updater 签名；需 `%USERPROFILE%\.tauri\personal-assistant.key`）
- `dist\release-manifest-<version>.md`（自动生成，含 sha256 / git commit / 校验清单）

> 仓库与品牌使用 `PrivateAgent`，但 Windows `productName` 固定为“私人助手”。它同时决定
> NSIS 卸载注册键、安装目录和快捷方式，是从 v0.1.1 覆盖升级的稳定身份；不得仅为改名而修改。

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
   - `私人助手_<version>_x64-setup.exe`
   - `私人助手_<version>_x64-setup.exe.sig`
   - `latest.json`
3. Release 说明写入 changelog 与 SmartScreen 风险提示（未代码签名时）。

> updater endpoint（`tauri.conf.json`）指向 `.../releases/latest/download/latest.json`，所以**最新** Release 的 `latest.json` 即生效版本。发布新版只需让新 Release 成为 latest；回滚只需让旧 Release 重新成为 latest 或覆盖 `latest.json`。

## 5. 安装 / 升级 / 卸载 QA 矩阵

在干净 Windows 机器（或已重命名 `%APPDATA%\personal-assistant` 的机器）逐项验证：

### 5.1 干净安装（自动化证据）
- [ ] `windows-release-assurance.yml` 在 GitHub 托管的全新 `windows-2025` VM 通过。
- [ ] `windows-lifecycle.json` 显示 preflight/install/upgrade/uninstall 全部 passed。
- [ ] 生产 lane 的两个安装包均为受信 CA Authenticode `Valid` 且包含可信时间戳。
- [ ] 双击安装包，安装成功（`installMode: currentUser`，无需管理员）。
- [ ] 开始菜单出现“私人助手”。
- [ ] 首启进入配置向导（`ConfigWizard.vue`）。

### 5.2 首启配置向导
- [ ] 环境检测：MySQL（127.0.0.1:3306）/ Ollama（127.0.0.1:11434）可达性正确。
- [ ] 填写连接 -> 测试连接：MySQL TCP + Ollama `/api/tags` + 模型已拉取校验。
- [ ] 模型缺失时提示 `ollama pull <model>`。
- [ ] 保存并启动后端 -> 轮询 `/health` -> 四项全绿进入主界面。
- [ ] `.env` 写入 `%APPDATA%\personal-assistant\.env`，字段为 `PA_` 前缀。
- [ ] `.env`、localStorage 与日志均不含 `PA_API_TOKEN`；无 Bearer token 请求安装版 API 返回通用 401，合法桌面请求正常。

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
- ✅ **发布级自动化验证**：2026-07-26 的 `release-check-full.bat` 已完成 11/11 门禁：后端 `pytest` 401 项、前端 Vitest 141 项、Playwright Chromium E2E 27 项、Rust 单测 2 项全部通过，生产构建满足包体预算，`alembic current -> 0012 (head)`，诊断包逐成员脱敏与 updater 清单校验通过。证据输出为 `dist/release-check-0.1.2.json` 与 `.md`。
- 当前开发机没有生产 Authenticode 私钥证书，也没有 Hyper-V/Windows Sandbox；生产发布必须在配置 Actions secrets 后通过 `windows-release-assurance.yml` 的 `production` lane。自签名 lane 不可作为生产签名证据。
- macOS / Linux 仅有构建脚本与差异清单，未实测（见 `docs/cross-platform.md`）。
- onefile sidecar 真冷首启（重启后首次）较慢，主要成本是 ChromaDB lifespan 初始化（非解压）；onedir 评估见 `docs/phase5-plan.md` M5，结论暂不切换。
