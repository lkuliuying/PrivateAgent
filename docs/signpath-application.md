# SignPath Foundation 免费 OSS 签名申请清单

本文记录 PrivateAgent 申请 SignPath Foundation 免费开源代码签名的可验证事实、已完成配置和必须由仓库所有者完成的外部步骤。

## 项目资料

| 字段 | 内容 |
|---|---|
| 项目 | PrivateAgent |
| 源码仓库 | <https://github.com/lkuliuying/PrivateAgent> |
| 许可证 | Apache License 2.0 |
| 维护者 | [@lkuliuying](https://github.com/lkuliuying) |
| 目标产物 | Windows x64 NSIS 安装包 `PrivateAgent_<version>_x64-setup.exe` |
| 构建系统 | GitHub Actions，GitHub 托管 `windows-latest` |
| 签名工作流 | `.github/workflows/signpath-release.yml` |
| Artifact configuration | `.signpath/artifact-configuration.xml`（在 SignPath 项目中导入/核对） |
| 更新源 | 主仓库 GitHub Releases |
| 隐私政策 | [`PRIVACY.md`](../PRIVACY.md) |
| Code signing policy | [`CODE_SIGNING_POLICY.md`](../CODE_SIGNING_POLICY.md) |

## SignPath 条件对应

- **公开源码**：主仓库已设为 Public。
- **OSI 许可证**：仓库根目录包含 Apache-2.0 `LICENSE` 和 `NOTICE`。
- **无商业双许可证**：PrivateAgent 源码仅以 Apache-2.0 发布。
- **已发布**：主仓库已有 Windows 安装包 Release；后续稳定产物统一迁移到主仓库。
- **功能文档**：README 包含产品能力、安装、构建、发布、安全和卸载说明。
- **可信来源**：签名请求只接受 GitHub 托管执行器构建并先上传的 GitHub Actions artifact。
- **人工批准**：工作流等待 SignPath 的 release signing policy 人工批准。
- **隐私与联网**：`PRIVACY.md` 说明本地数据、可选 Provider、更新检查和诊断导出。

## 申请说明草稿

> PrivateAgent is a local-first desktop personal agent built with Tauri, Vue, FastAPI and open-source local AI components. The repository and complete release build scripts are public under Apache-2.0. Windows NSIS installers are reproducibly built on GitHub-hosted runners. The checked-in workflow uploads the unsigned installer as a GitHub Actions artifact, submits that artifact through SignPath's GitHub trusted build connector, waits for manual approval, verifies the returned Authenticode signature, then creates the separate Tauri updater signature and publishes release evidence. The application does not transfer user information unless the user or operator explicitly enables a networked provider, integration, or update check.

## 外部步骤

1. 仓库所有者在 GitHub 账户启用双因素认证，并确认 SignPath 账户也启用 MFA。
2. 通过 <https://signpath.org/apply.html> 提交免费 OSS 订阅申请。表单中的姓名、邮箱和代表性声明必须由仓库所有者核对并最终提交。
3. 审核通过后，在 SignPath 中创建/确认 `PrivateAgent` 项目、Windows installer artifact configuration 和 `release-signing` 策略；导入 `.signpath/artifact-configuration.xml`，并以首次 unsigned artifact 验证生成结果。
4. 把预定义 `GitHub.com` Trusted Build System 链接到项目，并安装 SignPath GitHub App，仅授权 `lkuliuying/PrivateAgent`。
5. 在 GitHub 配置 SignPath 项目变量/API token，以及 Tauri updater 私钥 secrets；不要把任何私钥写入仓库、日志或 workflow artifact。
6. 在主仓库创建与应用版本一致的 Release/tag，触发 workflow；在 SignPath 审核来源信息后人工批准。
7. 验证 GitHub Release 中安装包 Authenticode 状态、时间戳、SHA-256、`.sig` 和 `latest.json` 一致，再执行安装/升级 smoke。

## 仍需外部证据

- SignPath Foundation 申请受理/批准记录。
- SignPath project、artifact configuration、trusted build system 和 signing policy 的实际 slug/ID。
- 首次签名请求 URL、审批记录及成功状态。
- 签名后安装包的 `Get-AuthenticodeSignature` / `signtool verify` 输出摘要。
- 基于该签名包重新执行的干净安装、旧版升级、回滚恢复和 updater 远程下载证据。
