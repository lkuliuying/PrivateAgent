# PrivateAgentRemote 1.0.4 测试安装包交付记录

日期：2026-08-31（Asia/Shanghai）。本次按用户要求构建联网版安装包并上传 GitHub，相关修改提交到 `dev/1.0.0`；服务器由用户独立拉取更新，本机未执行服务器部署。

## 安装包与 GitHub

- 版本：`PrivateAgentRemote 1.0.4`，Windows x64，手动安装测试包。
- GitHub：[1.0.4 测试草稿](https://github.com/lkuliuying/PrivateAgent/releases/tag/untagged-9ce5587d254277200fef)，草稿 ID `379446339`，拟用标签 `remote-v1.0.4-test.1`。草稿附件仅仓库有权限的账号可访问，不是公开稳定版。
- 安装包：`PrivateAgentRemote_1.0.4_x64-setup.exe`，25,118,488 字节；同时上传 `SHA256SUMS.txt`。GitHub 返回的两个附件大小和 SHA256 均与本地一致。
- 本机产物：`E:\Program\Agent\.run\remote-client-bseYDI`，构建日志为 `.run/build-remote-1.0.4.log`；这些构建产物不进入 Git。
- 保留旧附件、普通版版本和正式更新源。当前环境没有配置 Tauri updater 签名，本包没有 `.sig` 或 `latest.json`，Windows Authenticode 状态为 `NotSigned`；不可用于应用内自动更新，不应关闭安全软件或绕过组织安全策略。

安装包 SHA256：

```text
ba21d36fb12aaab50831832356c2fa78224a23ec62cd335b3ca1b56bac43de63
```

```powershell
Get-FileHash .\PrivateAgentRemote_1.0.4_x64-setup.exe -Algorithm SHA256
```

## 包含的修复

1. 本机工具定义满足模型严格模式，保留原有本机参数默认值、审批和只读限制；云端与客户端传递固定安全错误码，区分配置、认证、限流、超时等失败，不输出供应商错误正文或凭据。
2. 管理员顶栏、审计、最近登录和日志快照按 `Asia/Shanghai` 展示，兼容历史无时区 UTC；不改变数据库值和原始日志正文。
3. 定向服务器修复工具新增 `--backup-dir`，允许保留 1.0.3 备份并单独备份 1.0.4 更新前的状态；五文件范围、摘要白名单、停服和回滚保护不变。仅允许部署根目录下不与源码及安装目录重叠的独立一级绝对路径。

原始缺陷、验证路径及修改文件见[修复说明](../solutions/2026-08-31-model-502-admin-timezone.md)。未增加依赖、改动锁文件、数据库迁移或发布流水线。

## 实际验证

后端在无环境文件的隔离目录执行，未连接生产数据库或真实模型：

```powershell
Set-Location E:\Program\Agent\.tmp\fix-502-timezone
$env:PYTHONPATH='E:\Program\Agent\src'
$env:PYTHONDONTWRITEBYTECODE='1'
& E:\Program\Agent\.venv\Scripts\python.exe -m pytest E:\Program\Agent\tests\unit\test_desktop_model.py E:\Program\Agent\tests\unit\test_local_executor.py E:\Program\Agent\tests\unit\test_local_model_contract.py E:\Program\Agent\tests\test_model_gateway.py E:\Program\Agent\tests\test_admin_time_serialization.py E:\Program\Agent\tests\unit\test_connected_runtime_repair.py E:\Program\Agent\tests\unit\test_connected_backend_bundle.py E:\Program\Agent\tests\unit\test_admin_logs.py --noconftest -p no:cacheprovider --basetemp E:\Program\Agent\.tmp\fix-502-timezone\pytest-release-104-final -q -rs
```

结果：**127 passed、2 skipped**。跳过项是运行包修复和管理员日志中需要真实符号链接的测试，原因均为当前 Windows 用户缺少创建权限。`--basetemp` 必须使用一次性测试目录，不可指向项目或用户数据目录。

前端改动后的回归：

```powershell
Set-Location E:\Program\Agent\apps\desktop
npm run test
npm run build
```

结果：**78 个测试文件、454 passed**；类型检查和 Vite 生产构建通过，仍有部分资源块大于 500 kB 的既有构建提示。

构建脚本、安装包和执行器验证：

```powershell
Set-Location E:\Program\Agent
node --test scripts/build-remote-client.test.cjs
& .\scripts\build-remote-client.cmd https://www.liuyingapi.top --preview-installer --version 1.0.4 *> .run/build-remote-1.0.4.log
& .venv\Scripts\python.exe scripts/verify-local-executor.py .run/remote-client-bseYDI/private-agent-local.exe
& .venv\Scripts\python.exe -m ruff check src/personal_assistant/api/routes_desktop_model.py src/private_agent_local/cloud.py src/private_agent_local/runtime.py tests/unit/test_desktop_model.py tests/unit/test_local_executor.py tests/unit/test_local_model_contract.py scripts/repair-connected-runtime.py tests/unit/test_connected_runtime_repair.py
git diff --check
```

结果：构建脚本 **8 passed**；PyInstaller、本机执行器、前端、Tauri 和 NSIS 构建成功。执行器在 PATH 无 Python 的环境通过启动、health、nonce/Origin 校验、账号门禁和优雅退出验证，生产请求为零。Ruff 与差异格式检查通过。沙箱对子进程/临时目录的权限限制通过获准的本机执行解决，没有放宽业务测试。

另外读取 PyInstaller 归档，核对 `cloud`、`runtime` 编译模块与当前源码一致，且没有打包完整 `personal_assistant` 后端；检查生成的 NSIS 安装脚本包含本次桌面主程序和本机执行器。这不是实际安装/升级验收。

文档本地链接扫描发现 `docs/README.md` 中 `vue-desktop-code/`、`webfront-code/` 两个历史目录链接失效；对比 `HEAD` 确认并非本次引入，本次新增链接均可定位。保留该无关问题，未扩展到旧文档整理。

安装包按用户要求先构建上传、后提交源码，构建记录保留基线 `0c1705570ed0b75940189d52708c59b0021c2034` 和 `dirty=true`。构建后记录 320 个客户端相关源文件的摘要，用于核对最终提交；GitHub 草稿说明记录最终核对结果和目标提交。不把该构建描述为干净提交构建。

## 服务器更新与验收边界

服务器在 `/opt/private-agent/current` 核对当前分支及未提交修改后，拉取 `dev/1.0.0`。不要强制覆盖服务器既有修改；出现冲突或非快进时停止处理。

**只拉取源码不保证运行副本生效。** 历史证据显示服务加载 `site-packages`，需按[服务器 1.0.4 更新步骤](../connected-runtime-1.0.3-repair.md#104-修复复用拉取源码后同步运行包)执行预检，必要时停止单个服务并应用五文件补丁。为本次更新使用 `--backup-dir /opt/private-agent/rollback-connected-runtime-1.0.4`，保留旧备份；遇到未知摘要、备份冲突、`BACKOFF` 或 `FATAL` 时停止，不绕过校验。

还需要在用户电脑安装新版联网客户端，并验证真实账号发送指令、模型配置和管理员时间。未执行本安装包的真实安装/升级、真实账号模型调用、生产服务器更新、Linux 运行权限验证或完整数据库集成测试。模拟测试不能证明生产 502 没有其他配置、供应商或代理原因。

## 记忆与历史记录

本次读取并核对 `docs/project-state.md`、1.0.3 修复总结及服务器操作说明。`docs/project-state.md` 是此前建立的历史快照，本次保留其正文，连同既有相关文档提交共享；未将生产待验收状态改写为完成。按仓库约定，用户未要求更新项目记忆，故本次不改写记忆文件。补充本文、修复说明的后续链接和操作文档，并修正文档索引中已经过时的“未更新安装包”导航说明。
