# PrivateAgent 1.0.1 正式发布

本文记录 2026-10-06 的正式发布契约。源码采用当前工作区全部改动，包含 1.0.23 候选版之后的备份、模型恢复和连接恢复修复。1.0.23 是独立候选版编号；正式产品版本为 1.0.1，必须从正式身份重新构建并签名。

发布准备已完成；构建、资产复验和公开状态以 [GitHub Release](https://github.com/lkuliuying/PrivateAgent/releases/tag/v1.0.1) 及对应工作流证据为准。

## 固定契约

| 项目 | 值 |
| --- | --- |
| 标签 | `v1.0.1` |
| 正式身份 | `com.personal-assistant.desktop` |
| 更新目标 | `unified-windows-x86_64` |
| 安装包 | `PrivateAgent_1.0.1_x64-setup.exe` |
| 签名 | `PrivateAgent_1.0.1_x64-setup.exe.sig` |
| 更新入口 | `https://github.com/lkuliuying/PrivateAgent/releases/latest/download/latest.json` |
| 安装包 URL | `https://github.com/lkuliuying/PrivateAgent/releases/download/v1.0.1/PrivateAgent_1.0.1_x64-setup.exe` |
| 公钥 | 保留客户端已有公钥，ID `5E15775F7276641F` |

正式发布使用已有 GitHub Actions Secrets 进行 Tauri 更新签名，不导出或重建密钥。本版未配置 Windows Authenticode 发布者签名，相关边界见 [签名政策](../../../CODE_SIGNING_POLICY.md)。Candidate 与 Remote 保留独立应用身份和数据目录；安装正式版不会自动迁移它们的数据，也不构成候选版的版本降级。

## 来源与发布步骤

1. 在 `dev/1.0.0` 完成分批提交和正常推送，核对工作区干净，五处应用版本均为 1.0.1，依赖锁定记录只改变应用自身版本。
2. 为核验后的正式源码提交创建并推送 `v1.0.1`，建立同标签的非预发布草稿。
3. 手动选择 `dev/1.0.0` 的 `Windows Tauri draft release` 工作流，输入 `v1.0.1`。该分支包含已验证的工作流上下文与 UTF-8 修复；构建步骤检出标签源码。
4. 工作流正式构建、生成清单并用已有公钥验签，上传安装包、`.sig`、`latest.json`、`release-verification-1.0.1.json`、`release-manifest-1.0.1.md` 五项资产。草稿内同名资产禁止覆盖。
5. 下载草稿实际资产，对照 GitHub 和 CI 的大小、SHA-256、源码提交、更新目标，检查清单签名与 `.sig` 一致，并使用客户端公钥重新验签。
6. 复验通过后发布为非预发布版本并明确设为 Latest；再匿名下载固定更新入口及全部五项资产，复核清单版本、URL、摘要和签名。

无需私钥的参数检查：

```powershell
scripts\build-client.cmd --release --version 1.0.1 --github-repo lkuliuying/PrivateAgent --dry-run
```

正式签名构建由工作流执行；不要在命令行填写密钥。完整构建目录的离线验收、输入约束、部分上传处理和不可覆盖规则沿用 [1.0.0 发布操作说明](../v1.0.0/github-release.md)，使用时将版本及本次构建目录替换为 1.0.1 的实际记录。

## 验证边界

发布准备时，当前源码前端 831 项、后端 391 项和浏览器回归 7 项通过。后端另有 1 项因 Windows 符号链接创建权限跳过；打包套件 130 项及 Node 构建入口 22 项通过。前端构建、Ruff 和协议代码同步检查通过。

浏览器备份回归使用隔离后端与测试数据；连接恢复使用 IPC 和凭据替身。正式安装、真实 GUI 更新提示、生产数据迁移和真实模型调用未包含在这些回归中。安装包构建与验签成功不代表上述行为已实测。1.0.0 正式客户端可按相同目标检查 1.0.1 更新；完整安装升级仍需对应环境实测。

已读取历史 `docs/project-state.md`，其旧安装与发布记录不代表本次结果。该记忆按仓库约定保留，持久发布契约同步在本页及文档入口。
