# PrivateAgent 签名政策

自 2026-09-22 的发布配置起，正式 GitHub Release 更新使用 **Tauri 更新单签名**。现行流程不使用 SignPath，也不提供 Windows Authenticode 签名。Tauri 验签保证更新包与客户端信任的公钥匹配，不证明 Windows 发布者身份；安装时可能出现系统安全提示。

此前的 SignPath 申请与审批方案保留在[历史申请记录](docs/signpath-application.md)，不代表该服务已获批或启用。当前操作入口为 [1.0.0 GitHub Release 发布说明](docs/releases/v1.0.0/github-release.md)。

## 签名范围与身份

- 正式源为公开仓库 `lkuliuying/PrivateAgent` 中经维护者审查的版本标签；1.0.0 使用 `v1.0.0`。
- 应用标识为 `com.personal-assistant.desktop`，更新目标为 `unified-windows-x86_64`，安装包为 `PrivateAgent_<version>_x64-setup.exe`。
- 保留客户端已有 Tauri 公钥，公钥 ID 为 `5E15775F7276641F`。不为构建便利更换公钥、关闭验签或混用 Remote/Candidate 产物。
- Tauri `.sig` 覆盖最终安装包字节。验签之后不得修改安装包；修改任何字节均须重新生成签名、清单并验收。
- 第三方依赖继续遵守各自许可证，不将其描述为由 PrivateAgent 提供 Windows 发布者签名。

## 维护与发布控制

维护者 [@lkuliuying](https://github.com/lkuliuying) 负责代码审查、受保护签名配置、草稿核对和最终发布。贡献者提交的变更须经维护者审查。

- 发布工作流保留 `.github/workflows/signpath-release.yml` 路径，仅接受手动触发；文件名不表示仍依赖 SignPath。
- 工作流检出指定标签，核对标签与源码版本，只接受已存在且非预发布的草稿 Release。
- 所有者在 GitHub Actions 的 Secrets 安全界面管理 `TAURI_SIGNING_PRIVATE_KEY` 及所需的 `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`。只向正式构建步骤注入，不写入仓库、命令参数、日志、文档或产物。自动化核对与离线验收仅使用公钥，不读取私钥。
- 签名和清单验证失败即停止。仅在验收通过后附加安装包、`.sig`、`latest.json` 及摘要证据；同名资产存在则失败，不覆盖。
- 工作流不自动发布草稿、不设置 Latest。维护者完成下载和隔离安装验收后，再人工发布并明确设置 Latest。
- 构建成功、签名通过、草稿资产就绪、已公开发布及真实升级通过分别记录，不互相替代。

## 隐私

密钥与供应商配置遵循[隐私说明](PRIVACY.md)。发布证据仅包含版本、公开身份、提交、文件名、摘要及验证结果，不包含用户数据或签名秘密。

## 故障与事故处理

发现产物、签名、凭据或工作流疑似遭篡改时停止发布，保留公开摘要和失败证据，由维护者调查后处理。已公开版本不覆盖同名资产、不将清单改为降级路径；修复后发布更高版本。若涉及密钥更换，须单独评估已安装客户端的信任兼容性，不临时替换配置中的公钥。
