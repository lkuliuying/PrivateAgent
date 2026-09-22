# 1.0.0 GitHub Release 更新源与发布操作

本文定义 1.0.0 的 GitHub Release 发布契约与操作流程，替代此前 SignPath 双签名方案。正式流程由维护者从已审查的版本标签构建，在草稿中核验资产后发布并明确设置 Latest。私钥仅通过受保护的 GitHub Secrets 提供给构建步骤，不在对话、文档或日志中读取、展示或重新生成。操作说明不代表执行结果；源码验证和实际发布分别记录在文末。

## 发布契约

| 项目 | 固定值 |
| --- | --- |
| 仓库 | `lkuliuying/PrivateAgent` |
| 版本与标签 | `1.0.0`、`v1.0.0` |
| 应用标识 | `com.personal-assistant.desktop` |
| 更新目标 | `unified-windows-x86_64` |
| 最终安装包 | `PrivateAgent_1.0.0_x64-setup.exe` |
| 签名文件 | `PrivateAgent_1.0.0_x64-setup.exe.sig` |
| 更新入口 | `https://github.com/lkuliuying/PrivateAgent/releases/latest/download/latest.json` |
| 安装包 URL | `https://github.com/lkuliuying/PrivateAgent/releases/download/v1.0.0/PrivateAgent_1.0.0_x64-setup.exe` |
| 公钥 | 保留 `apps/desktop/src-tauri/tauri.conf.json` 中已有值，ID `5E15775F7276641F` |

`latest.json` 使用 Tauri 静态清单：`version` 为 `1.0.0`，`pub_date` 为 RFC 3339 时间；`platforms` 下使用客户端自定义目标 `unified-windows-x86_64`，其 `signature` 是最终 `.sig` 的内容，不是文件路径或 URL。安装包下载地址只含一次版本标签目录，不追加 `/1.0.0/`。参见 [Tauri 静态清单规范](https://v2.tauri.app/plugin/updater/#static-json-file)。

[清单示例](../../examples/updater-latest.json.example)含明确无效的签名占位符，只能阅读，不得上传。可部署清单必须由实际签名产物生成并通过下述验收。

Tauri 签名用于更新包校验；当前没有 Windows Authenticode 签名，安装可能出现系统安全提示。见[签名政策](../../../CODE_SIGNING_POLICY.md)。

## 构建准备与最小配置

正式构建需要 Windows x64、项目锁定依赖、Python 3.12、Node.js 20、Rust/MSVC、干净工作区和已有受保护的 Tauri 签名环境。当前默认源配置仍为空；正式 unified 构建通过 `--github-repo` 注入 GitHub 更新入口。便携版和独立候选版不配置更新源；普通预览默认也不配置，可按下节显式指定更新地址用于本机测试。

在仓库根核对参数，不构建、不签名、不读取私钥：

```powershell
scripts\build-client.cmd --release --version 1.0.0 --github-repo lkuliuying/PrivateAgent --dry-run
```

`--github-repo` 仅接受 `owner/repo`，仅用于正式 unified 构建，与 `--update-url`、`--download-base-url` 互斥。通过统一入口无需额外传 `--unified`。维护者在签名环境中执行正式构建时去掉 `--dry-run`，不要在命令行填写密钥。

发布配置只有两项签名 Secrets：由仓库所有者在 GitHub 的 `Settings → Secrets and variables → Actions` 安全界面配置 `TAURI_SIGNING_PRIVATE_KEY`，以及已有私钥需要时的 `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`。两者仅注入工作流的正式构建步骤。不要向对话、日志或文档展示其值，不导出既有 Secrets，不为验收重新生成密钥。无需 SignPath 配置或 `PRIVATEAGENT_UPDATE_URL`。

正式构建输出新的 `.run/unified-client-*` 目录，并打印 `Build output:`。后续步骤必须使用本次输出路径，不能自动选“最近一个”目录或复用旧包。目录内主要发布资产为：

```text
<构建目录>/
  build-info.json
  source-manifest.json
  tauri-build.json
  updater-public-key.txt
  SHA256SUMS.txt
  publish/
    latest.json
    1.0.0/
      PrivateAgent_1.0.0_x64-setup.exe
      PrivateAgent_1.0.0_x64-setup.exe.sig
```

本地目录中的 `publish/1.0.0/` 只是归档布局，上传到 GitHub Release 时使用资产文件名，不把本地层级追加到下载 URL。验签后不得再修改安装包字节。

## 本机更新测试包

需要安装当前未提交源码、同时测试更新检查时，使用正式 unified 身份的预览模式，并显式指定地址：

```powershell
scripts\build-client.cmd --preview-installer --version 1.0.0 --update-url https://github.com/lkuliuying/PrivateAgent/releases/latest/download/latest.json
```

该模式不读取签名材料，不生成 `.sig` 或 `latest.json`，构建记录如实保留 `mode=preview`、`dirty` 和 `signing=unsigned`。客户端继续使用已有公钥核验未来下载的更新；没有放宽正式发布的干净工作区或签名要求。默认预览仍无更新入口，独立 `--qa` 候选版继续拒绝更新地址。

安装包使用 `PrivateAgent` 正式身份和安装位置，适合验证 `unified-windows-x86_64` 更新目标；不会自动迁移独立 Candidate/Remote 的数据。不要把测试安装包上传为正式更新资产。检查更新需要远端已有兼容目标的清单；同版本不提示升级，完整升级还需要更高版本的签名产物。

## 本地只读离线验收

在与构建版本一致的源码副本中，从仓库根运行以下命令，将 `<构建目录>` 替换为本次正式输出路径。命令仅读取明确指定的构建目录、最终安装包、清单和现有公钥，不访问 GitHub 或签名服务，也不读取私钥：

```powershell
.venv\Scripts\python.exe -B scripts/verify_update_release.py --bundle "<构建目录>" --installer "<构建目录>\publish\1.0.0\PrivateAgent_1.0.0_x64-setup.exe" --manifest "<构建目录>\publish\latest.json" --repo lkuliuying/PrivateAgent
```

验收核对正式构建身份、版本、更新目标、清单格式、GitHub 下载 URL、`.sig` 与清单内容一致性、源码和产物摘要，再调用现有 Rust 验签器验证最终安装包。成功时 stdout 输出 JSON 证据；退出码非零即停止发布。安装包、签名、清单或摘要记录任一缺失或不一致均不能用旧文件补齐。

默认验签器由 `cargo run --offline --locked --release` 启动，需要已经缓存的依赖及可用 MSVC 环境；Cargo 可能写入编译缓存，但不会修改待验收资产。也可在命令末尾追加 `--verifier "<预编译验签器.exe>"`，使用从本仓库 `scripts/windows/updater-signature-verifier` 构建的验签器。缺少缓存或工具链时报告环境阻塞，不能把未执行的验签记为通过。

GitHub runner 的正式构建使用统一 Cargo 输出目录，验签器位于 `apps/desktop/src-tauri/target/release/private-agent-updater-signature-verifier.exe`；未覆盖 `CARGO_TARGET_DIR` 的独立本地编译输出位于 `scripts/windows/updater-signature-verifier/target/release/private-agent-updater-signature-verifier.exe`。两者均可通过 `--verifier` 明确指定，应使用本次源码生成的程序。

Node 构建入口自动生成清单；Python `scripts/generate-latest-json.py` 是同一契约下的辅助生成入口。它不能替代最终产物验签，也不得使用 Remote/Candidate 安装包生成正式 Windows 清单。

### 无私钥的离线回归

以下命令验证发布工具本身，使用公开消息、签名和公钥测试向量，不读取或生成私钥。在已初始化 MSVC 的终端中，从仓库根先编译验签器，再运行打包套件和 Rust 验签回归；需事先具备锁定依赖缓存：

```powershell
cargo build --offline --locked --release --manifest-path scripts/windows/updater-signature-verifier/Cargo.toml
.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite desktop-packaging
cargo test --offline --locked --manifest-path scripts/windows/updater-signature-verifier/Cargo.toml
```

Python 打包套件中的集成测试实际调用预编译 Rust 验签器，覆盖公开有效签名及篡改拒绝；Rust 套件另覆盖签名验证边界。公开向量中的 `test` 消息不是正式安装器，测试通过不能证明 `1.0.0` 产物已经签名或验签。命令写入构建缓存和隔离测试目录，不修改发布资产；实际结果应单独记录，不能将本操作说明视为测试已执行。

## 正式草稿与发布流程

以下步骤由维护者在具备发布授权后依次执行。工作流负责草稿资产准备，发布及 Latest 设置是独立的最终操作；任一门禁失败均停止，不将部分完成记录为正式发布：

1. 审查并交付本次源码与工作流变更，确认 `v1.0.0` 指向包含这些实现的提交，标签与桌面源码版本完全一致。工作流需已在 GitHub 注册为可手动触发的工作流；调度时明确指定包含有效控制配置的分支。工作流控制分支与应用构建标签分别记录，不能从旧标签构建后仅修改清单版本。
2. 确认 Secrets 已安全配置。在主仓库准备指向 `v1.0.0` 的草稿 Release，保持非预发布，不提前公开。工作流不会创建 Release 或标签。
3. 按下方命令从 `codex/release-1.0.0` 控制分支手动调度 `.github/workflows/signpath-release.yml`，输入 `release_tag=v1.0.0`。调度配置取自控制分支；构建步骤仍检出 `v1.0.0` 应用标签，检查草稿身份及版本，再进行 Tauri 签名构建和最终离线验收。该历史文件名不表示使用 SignPath。
4. 核对工作流附加到草稿的五项资产：`PrivateAgent_1.0.0_x64-setup.exe`、`PrivateAgent_1.0.0_x64-setup.exe.sig`、`latest.json`、`release-verification-1.0.0.json`、`release-manifest-1.0.0.md`。JSON 验签证据记录实际发布文件的 SHA-256 和大小；本地 `SHA256SUMS.txt` 还覆盖未发布的本机运行文件，留在构建目录供验收。工作流禁止覆盖同名资产，不自动发布、不设置 Latest。完整构建来源和验签证据应与同一次工作流运行关联。
5. 下载草稿中实际将发布的资产，对照同次工作流 JSON 证据核对大小和 SHA-256。完整只读验收需要同次构建目录，仅下载五项发布文件不能替代 `--bundle`；应确认上传前的工作流验收已成功。本地保留了同次构建目录时，可将 `--installer` 和 `--manifest` 指向下载文件再验一次。使用隔离 Windows 测试环境进行安装、启动、本机执行器及卸载验收，不使用生产用户数据或付费模型请求来替代这些检查。
6. 确认资产、签名及安装验收通过后，维护者人工发布并明确选择 **Set as latest release**。历史仓库中可能存在版本号更高的旧产品 Release，不依赖 GitHub 的默认 Latest 选择。见 [GitHub Release 管理说明](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)。
7. 公开后单独验证固定更新入口和清单内安装包 URL 可匿名下载、响应内容正确、下载摘要与草稿证据一致，再记录真实客户端检查与升级结果。草稿阶段的离线成功不能证明这些公开下载路径已可用。

手动调度必须选择 `codex/release-1.0.0` 控制分支，不能选择尚未合入控制配置修复的 `main`。1.0.0 的调度命令如下；该版本现已发布，重新执行会被“必须为草稿”门禁拒绝，不能用它覆盖已发布资产：

```powershell
gh workflow run 343378685 --repo lkuliuying/PrivateAgent --ref codex/release-1.0.0 --field release_tag=v1.0.0
```

`--ref` 选择工作流控制配置，不改变应用构建来源。`v1.0.0` 固定指向 `36c0a2446325cae041631c0abcc3f21327a96da5`；修复调度配置时只推进 `codex/release-1.0.0`，不移动该标签，不改动 `main` / `dev/1.0.0`。记录工作流运行时，应同时保留控制分支实际提交和应用标签解析提交，二者可能不同。

正式版和使用相同更新入口的 1.0.0 预览版查询 `version=1.0.0` 的清单时，预期结果均为“当前已是最新版本”或无可安装更新，不应触发同版本安装。应把入口请求成功、清单目标正确及无升级提示分别记录；下载和安装升级的完整链路需要更高正式版本，不能用本次同版本检查宣称已通过。

## 失败处理与升级边界

- 标签与源码版本不同、目标或安装包名称不符、缺失签名、验签失败、摘要不匹配时停止，保留失败原因；不要修改客户端公钥或关闭验签来继续。
- 草稿内存在同名资产时停止。维护者先核对资产来源与摘要，再单独决定如何处理草稿；禁止使用 `--clobber` 或直接覆盖来掩盖部分上传或来源不明的问题。
- 工作流中途失败可能已向草稿附加部分资产。该草稿不能发布，重试前需重新核对完整资产集与同次构建证据，不能将不同构建的文件拼成一个发布。
- 已发布后发现问题时暂停后续推广，由维护者单独处理发布状态；保留既有资产和证据，修复后发布更高版本。当前客户端不实现强制降级，不通过覆盖 `latest.json` 或同名安装包回滚。
- 未配置更新入口的旧包不能靠更换远程清单获得入口，需手动安装正式版作为后续升级基线。Remote/Candidate 使用不同应用身份与更新目标，不自动跨身份迁移或合并数据。
- 现有 `1.0.20` 候选包不能自动降级为正式 `1.0.0`。已安装 `1.0.0` 查询同版本应无更新；后续更高正式版本才构成完整升级验收。

## 验收记录与项目记忆边界

### 2026-09-22 发布准备阶段的历史离线验证

以下结果来自 `F:\Program\Agent` 原工作区的发布准备阶段，不是隔离发布工作树、GitHub runner 或正式安装包的验收结果。Rust 命令在初始化 MSVC 后运行，依赖来自本机缓存；后续源码变化需单独复验，不能直接沿用下表通过数：

| 命令 | 实际结果 |
| --- | --- |
| `scripts\build-client.cmd --release --version 1.0.0 --github-repo lkuliuying/PrivateAgent --dry-run` | 通过；标识、目标、标签和 GitHub URL 符合上述契约 |
| `node --test scripts/build-remote-client.test.cjs` | 19 项通过 |
| `cargo build --offline --locked --release --manifest-path scripts/windows/updater-signature-verifier/Cargo.toml` | 通过；生成本次集成测试使用的验签器 |
| `.venv\Scripts\python.exe -B scripts/run_coding_validation.py --suite desktop-packaging` | 129 项通过，无跳过；含真实验签与 PowerShell 草稿门禁 |
| 在 `apps/desktop` 执行 `node node_modules/vitest/vitest.mjs run src/components/UpdateChecker.spec.ts` | 12 项通过 |
| `cargo test --offline --locked --manifest-path apps/desktop/src-tauri/Cargo.toml --lib updater_config::tests` | 4 项通过 |
| `cargo test --offline --locked --manifest-path scripts/windows/updater-signature-verifier/Cargo.toml` | 6 项通过 |
| `cargo fmt --check --manifest-path scripts/windows/updater-signature-verifier/Cargo.toml` | 通过 |

工作流缓存从检出目录改到 `runner.temp` 后，另行复跑该工作流的 36 项离线回归并通过，避免缓存触发正式构建的干净工作区检查。Node/Vitest 的受限进程环境曾出现 `spawn EPERM`，上述结果来自获准普通本机进程权限的复验。测试没有访问签名服务或修改 GitHub，公开签名夹具也没有生成正式签名。

该次工作流复验使用现有隔离运行器，实际命令为：

```powershell
.venv\Scripts\python.exe -B -X utf8 -c "import sys;sys.path.insert(0,'scripts');import run_coding_validation as r;r.SUITES['release-workflow']=['tests/packaging/test_github_release_workflow.py'];raise SystemExit(r.run('release-workflow'))"
```

Python 变更通过 Ruff `E/F/I` 检查，工作流 YAML 与全部 7 段 PowerShell 语法通过检查，文档 UTF-8、68 个本地链接及清单示例通过检查，`git diff --check` 通过。首次 Ruff 检查发现的两处 `I001` 导入排序已修复并复验。

### 2026-09-22 隔离发布工作树复验

以下复验针对 `F:\Program\Agent\.run\release-worktree-1.0.0` 中的本次正式发布变更，独立于上面的原工作区历史记录：

| 验证项 | 实际结果 |
| --- | --- |
| Node 构建脚本回归 | 22 项通过 |
| Vitest `UpdateChecker.spec.ts` | 12 项通过 |
| Python `desktop-packaging` | 129 项通过 |
| Rust `updater_config::tests` | 4 项通过 |
| Rust 更新签名验签器回归 | 6 项通过 |
| 更新签名验签器 release 离线编译 | 通过 |
| 正式构建 `--dry-run` | 通过；应用标识、更新目标及 GitHub URL 符合发布契约 |
| `git diff --check` | 通过 |

该次复验完成时尚未创建发布提交或标签，也未执行 GitHub 正式构建。上述测试使用公开签名向量，不代表正式 `1.0.0` 安装包已经签名、验签或发布；发布后的运行链接和资产证据另行记录，不在版本提交中预填完成状态。

### 正式 1.0.0 发布执行记录

首次真实调度被 GitHub 返回 HTTP 422 拒绝：工作流在 `jobs.<job>.env` 中引用了该位置不允许使用的 `runner.temp` 上下文。拒绝发生于 GitHub 工作流解析阶段，未启动构建，也没有因此生成或验签正式安装包。此前本地 YAML、PowerShell 和门禁回归通过，不代表 GitHub 上下文语义已经验证通过。调度修复仅在隔离发布分支进行，应用标签保持不变；修复后工作流专项离线回归 **38 项通过**。

随后[首次构建运行](https://github.com/lkuliuying/PrivateAgent/actions/runs/35717721814)使用控制提交 `3cc0c170466045d557333574608201b7e27798ab`，正式安装器构建和签名步骤成功。最终验收函数已执行完签名验证，但在输出中文 JSON 证据时遇到 Windows `cp1252` 的 `UnicodeEncodeError`，整项验收步骤失败，未上传任何资产。控制配置因此显式设置 `PYTHONUTF8=1` 与 `PYTHONIOENCODING=utf-8`；本地回归使用真实 Python 子进程复现旧编码错误并验证新配置的中文管道输出，不降低验签要求。修复后工作流专项离线回归 **39 项通过**。

[成功运行 35720222129](https://github.com/lkuliuying/PrivateAgent/actions/runs/35720222129)使用工作流控制提交 `6a3d83b7cdf4689f3bbecd159688a81f677163cd`，应用仍从固定标签 `v1.0.0` 对应的 `36c0a2446325cae041631c0abcc3f21327a96da5` 构建。构建、签名、最终验签及五项草稿资产附加成功。随后完成草稿下载核对、正式发布、Latest 设置和公开匿名下载复验；实际安装及 GUI 检查未执行，没有将其记为发布完成的附带结论。

| 阶段 | 状态与需保留的证据 |
| --- | --- |
| 隔离发布工作树离线复验 | 已完成；结果见上节，尚不代表正式产物验收 |
| 发布源码提交与标签 | 应用标签 `v1.0.0` 已固定到 `36c0a2446325cae041631c0abcc3f21327a96da5`；后续控制配置修复不移动此标签 |
| 工作流控制分支 | `codex/release-1.0.0`；成功运行的控制提交为 `6a3d83b7cdf4689f3bbecd159688a81f677163cd`，与应用构建提交分别记录 |
| 历史草稿保留 | 旧草稿 ID `379045109` 已重命名为 `legacy-remote-v1.0.0-20260830`；附件 ID、名称、大小和摘要保持不变，仅 GitHub 临时下载 URL 随草稿名称重新生成 |
| GitHub 签名构建与验签 | 已完成；成功运行 `35720222129`，五项资产来自同次构建 |
| 草稿资产核对 | 已完成；五项资产实际下载，大小和 SHA-256 与 GitHub 元数据及 CI 记录一致，最终安装包用 Rust 验签器和客户端既有公钥复验通过 |
| 公开发布与 Latest 设置 | 已完成；[PrivateAgent 1.0.0](https://github.com/lkuliuying/PrivateAgent/releases/tag/v1.0.0)，Release ID `393643616`，非草稿、非预发布，Latest 指向 `v1.0.0` |
| 公开匿名下载 | 已完成；五项资产均在未发送认证信息的请求中返回 HTTP 200，大小和摘要与草稿阶段一致，Rust 公钥验签复验通过 |
| 固定更新入口 | HTTP 200；`version=1.0.0`，目标为 `unified-windows-x86_64` |
| Windows Authenticode | 实际状态为 `NotSigned`；Tauri 更新签名通过不等于 Windows 发布者签名 |
| 实际安装、本机执行器及 GUI 更新检查 | 未实测；同版本 1.0.0 应无升级只是版本比较的逻辑预期，尚无 GUI 验收证据 |
| 更高版本真实升级与真实模型 | 未实测；公开下载和验签不能替代安装、重启升级或模型调用验收 |

发布时远端分支核对结果为 `main` 仍在 `70e507d`、`dev/1.0.0` 仍在 `0ade0a7`，本次发布未合并或移动它们；不要把本地可能过期的同名引用当作该远端核对结果。

公开资产及其本次下载证据如下，均来自同一 Release：

| 资产 | 字节数 | SHA-256 |
| --- | ---: | --- |
| [PrivateAgent_1.0.0_x64-setup.exe](https://github.com/lkuliuying/PrivateAgent/releases/download/v1.0.0/PrivateAgent_1.0.0_x64-setup.exe) | 34870363 | `1783be1d1ea66270335b0b2875876594da81845900bcba31ccd0ed87faf61a2e` |
| [PrivateAgent_1.0.0_x64-setup.exe.sig](https://github.com/lkuliuying/PrivateAgent/releases/download/v1.0.0/PrivateAgent_1.0.0_x64-setup.exe.sig) | 424 | `fe983b0efdc6233526664a177d4047c70fb2f4c0884b56fb521b8696725ff6bb` |
| [latest.json](https://github.com/lkuliuying/PrivateAgent/releases/download/v1.0.0/latest.json) | 732 | `49c72ce22ec9e58efffef0cc5e2d74e9126f79b3ade4433f8928306356f853ef` |
| [release-verification-1.0.0.json](https://github.com/lkuliuying/PrivateAgent/releases/download/v1.0.0/release-verification-1.0.0.json) | 1039 | `4d858d612901a159981569955dbf66edb450c0ada8693bff557402d5fe484189` |
| [release-manifest-1.0.0.md](https://github.com/lkuliuying/PrivateAgent/releases/download/v1.0.0/release-manifest-1.0.0.md) | 1616 | `0d9ebeb2c8ef5433547457252a351ccb9519c69dab899ba97f0e8e56778f2929` |

长期查验从公开 Release、成功 CI 运行及上表资产进入。本次另以根工作区 `.run/release-1.0.0-20260922/` 下的 `draft-download-verification.json`、`public-download-verification.json`、`anonymous-downloads.json` 和 `public-ready-metadata.json` 核对草稿与公开下载结果；这些是本机临时证据，不随源码交付，不保证跨机器存在，也不能替代公开来源。

仅在取得相应执行证据后更新未完成项，保留失败或阻塞信息。正式发布、下载和签名验证已完成；安装、GUI 及更高版本升级仍按各自证据判断。

发布准备已核对 `docs/project-state.md` 与 [2026-09-20 本机化说明](../../solutions/2026-09-20-local-only-context.md)。其中 SignPath 工作流的描述反映此前方案；当前源码和本页记录的 Tauri 单签名契约覆盖该发布方式。历史状态记忆按仓库约定保留不改写，持久发布知识同步到本页、README、文档入口和签名政策，原申请材料明确标为历史未启用方案。
