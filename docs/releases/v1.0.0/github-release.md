# 1.0.0 GitHub Release 更新源与发布操作

本文记录 2026-09-22 确定的正式发布契约，替代此前 SignPath 双签名方案。当前任务只准备源码配置、文档和离线验证，不读取或生成私钥，不执行正式签名构建，不运行远程工作流，不上传、发布或修改远程资源。下文涉及 GitHub、正式构建及安装的步骤供维护者后续执行，不是已完成记录。

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

`--github-repo` 仅接受 `owner/repo`，仅用于正式 unified 构建，与 `--update-url`、`--download-base-url` 互斥。通过统一入口无需额外传 `--unified`。维护者未来在签名环境中执行正式构建时去掉 `--dry-run`，不要在命令行填写密钥。

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

## 维护者后续草稿与发布流程

以下操作会接触或修改 GitHub，须由维护者在准备完成后执行，本轮没有执行：

1. 审查并交付本次源码与工作流变更，确认 `v1.0.0` 指向包含这些实现的提交，标签与桌面源码版本完全一致。工作流需在 GitHub 默认分支可手动触发；不能从旧标签构建后仅修改清单版本。
2. 确认 Secrets 已安全配置。在主仓库准备指向 `v1.0.0` 的草稿 Release，保持非预发布，不提前公开。工作流不会创建 Release 或标签。
3. 在 Actions 手动运行 `.github/workflows/signpath-release.yml`，输入 `release_tag=v1.0.0`。工作流检出该标签，检查草稿身份及版本，再进行 Tauri 签名构建和最终离线验收。该历史文件名不表示使用 SignPath。
4. 核对工作流附加到草稿的五项资产：`PrivateAgent_1.0.0_x64-setup.exe`、`PrivateAgent_1.0.0_x64-setup.exe.sig`、`latest.json`、`release-verification-1.0.0.json`、`release-manifest-1.0.0.md`。JSON 验签证据记录实际发布文件的 SHA-256 和大小；本地 `SHA256SUMS.txt` 还覆盖未发布的本机运行文件，留在构建目录供验收。工作流禁止覆盖同名资产，不自动发布、不设置 Latest。完整构建来源和验签证据应与同一次工作流运行关联。
5. 下载草稿中实际将发布的资产，对照同次工作流 JSON 证据核对大小和 SHA-256。完整只读验收需要同次构建目录，仅下载五项发布文件不能替代 `--bundle`；工作流在上传前已经运行该验收。本地保留了同次构建目录时，可将 `--installer` 和 `--manifest` 指向下载文件再验一次。使用隔离 Windows 测试环境进行安装、启动、本机执行器及卸载验收，不使用生产用户数据或付费模型请求来替代这些检查。
6. 确认资产、签名及安装验收通过后，维护者人工发布并明确选择 **Set as latest release**。历史仓库中可能存在版本号更高的旧产品 Release，不依赖 GitHub 的默认 Latest 选择。见 [GitHub Release 管理说明](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)。
7. 公开后单独验证固定更新入口和清单内安装包 URL 可匿名下载、响应内容正确、下载摘要与草稿证据一致，再记录真实客户端检查与升级结果。草稿阶段的离线成功不能证明这些公开下载路径已可用。

## 失败处理与升级边界

- 标签与源码版本不同、目标或安装包名称不符、缺失签名、验签失败、摘要不匹配时停止，保留失败原因；不要修改客户端公钥或关闭验签来继续。
- 草稿内存在同名资产时停止。维护者先核对资产来源与摘要，再单独决定如何处理草稿；禁止使用 `--clobber` 或直接覆盖来掩盖部分上传或来源不明的问题。
- 工作流中途失败可能已向草稿附加部分资产。该草稿不能发布，重试前需重新核对完整资产集与同次构建证据，不能将不同构建的文件拼成一个发布。
- 已发布后发现问题时暂停后续推广，由维护者单独处理发布状态；保留既有资产和证据，修复后发布更高版本。当前客户端不实现强制降级，不通过覆盖 `latest.json` 或同名安装包回滚。
- 未配置更新入口的旧包不能靠更换远程清单获得入口，需手动安装正式版作为后续升级基线。Remote/Candidate 使用不同应用身份与更新目标，不自动跨身份迁移或合并数据。
- 现有 `1.0.20` 候选包不能自动降级为正式 `1.0.0`。已安装 `1.0.0` 查询同版本应无更新；后续更高正式版本才构成完整升级验收。

## 验收记录与项目记忆边界

2026-09-22 在 Windows 本机对本次实现执行了以下验证；Rust 命令在初始化 MSVC 后运行，依赖来自本机缓存：

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

本任务的源码配置和离线测试不代表正式 `1.0.0` 安装包已经生成或验签。当前尚需维护者提供同次正式构建目录与签名资产，完成草稿附加、真实安装、公开下载和真实升级验收。

本次已读取 `docs/project-state.md` 与 [2026-09-20 本机化说明](../../solutions/2026-09-20-local-only-context.md)。其中 SignPath 工作流的描述反映此前方案；当前源码和本页记录的 Tauri 单签名契约覆盖该发布方式。历史状态记忆按仓库约定保留不改写，持久发布知识同步到本页、README、文档入口和签名政策，原申请材料明确标为历史未启用方案。
