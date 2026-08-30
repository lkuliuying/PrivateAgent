# 远程 Windows 客户端更新

远程安装版支持“检查更新 → 确认下载并安装 → 重新启动”。更新客户端不会更新服务器；后端仍按部署流程独立升级，并保持旧客户端所需接口兼容。

## 版本与渠道隔离

| 项目 | 远程安装版 |
|---|---|
| 应用标识 | `com.personal-assistant.desktop.remote` |
| 安装名称 | `PrivateAgentRemote` |
| 可执行文件 | `privateagent-remote.exe` |
| 更新清单平台键 | `remote-windows-x86_64` |
| 默认清单地址 | `https://<API 域名>/updates/remote/latest.json` |
| 本地后端 | 1.0.3 起捆绑轻量本机执行器，项目和工具在本机运行；不启动普通版完整后端，也不执行停止普通版 sidecar 的安装钩子 |

1.0.3 的服务端接口、日志权限和第二台电脑验收步骤见 [联网客户端部署指南](./connected-desktop-rollout.md)。账号与模型仍连接服务器，项目文件不自动同步到服务器或其他电脑。

本地安装版的标识、发布工作流、更新地址不变。不要把远程包覆盖到现有通用 GitHub `latest.json`：旧客户端使用相同默认平台键，无法安全区分本地版与远程便携版。

以前发送的便携 EXE 需要先手动安装一次远程安装版，并从新快捷方式启动；关闭旧便携进程，不再运行旧 EXE。由于远程安装版使用独立应用标识，首次可能需要重新登录或重新设置客户端偏好；服务器上的账号、会话和业务数据不因安装包替换而删除。之后远程安装版之间的更新保持相同应用标识及数据目录，不需要卸载。

## 构建与验证

在已有 Node、Rust、MSVC 和桌面依赖的 Windows 开发环境中，从仓库根目录执行。命令中的域名和版本均为示例；每次正式发布必须使用比已发布版本更大的 `major.minor.patch` 版本号，不修改或复用已发布的版本目录。

先预览配置，不构建、不访问签名材料、不上传：

```powershell
.\scripts\build-remote-client.cmd "https://api.example.com" --release --version 1.0.1 --dry-run
```

不使用签名密钥的安装包验证：

```powershell
.\scripts\build-remote-client.cmd "https://api.example.com" --preview-installer --version 1.0.1
```

预览包没有 `.sig` 或 `latest.json`，不能作为在线更新发布；Windows 可能显示未签名应用提示。Tauri 更新签名与 Windows Authenticode 是不同机制，不应要求用户关闭安全软件。

正式构建须从干净 Git 工作区执行，并使用已有受控签名环境提供 `TAURI_SIGNING_PRIVATE_KEY` 及所需密码。脚本只传递签名构建所需变量，不加载密钥文件到源码、不打印密钥、不更换公钥。不要把密钥粘贴到聊天、命令参数或仓库。签名公钥沿用 `tauri.conf.json`，生成清单前会使用项目验签工具验证安装包与公钥匹配。

```powershell
.\scripts\build-remote-client.cmd "https://api.example.com" --release --version 1.0.1
```

也可以独立托管下载服务：

```powershell
.\scripts\build-remote-client.cmd "https://api.example.com" --release --version 1.0.1 --update-url "https://downloads.example.com/remote/latest.json" --download-base-url "https://downloads.example.com/remote"
```

更新地址会写入安装包，后续构建应保持一致。若需要变更渠道，必须安排旧地址兼容和迁移，不能只改新包的地址。构建参数不包含令牌、用户名、密码或查询串，不把 GitHub PAT 或服务令牌嵌入客户端。

每次输出位于唯一 `.run/remote-client-*` 目录：

```text
build-info.json                 # 版本、提交、是否有未提交修改、API/更新地址
SHA256SUMS.txt                  # EXE 和安装包校验值
publish/
  latest.json                  # 仅签名及验签成功后生成
  1.0.1/
    PrivateAgentRemote_1.0.1_x64-setup.exe
    PrivateAgentRemote_1.0.1_x64-setup.exe.sig
```

只有 `publish/` 的内容属于在线更新发布物。不要上传整个 `.run`、仓库、环境文件或签名材料。默认便携构建方式不变，但便携测试包不支持此独立安装版升级链路。

## 托管与发布

脚本不会修改服务器、上传文件、创建 Git 标签或发布 GitHub Release。现有 `.github/workflows/signpath-release.yml` 仍构建本地版，排除 `remote-v*` 标签，不用于发布远程版；发布标签应包含该排除条件。

更新清单和安装包必须可由终端用户通过 HTTPS 读取；不能被 API 登录校验重定向成 HTML。更新包可以公开下载而源码保持私有。若需要鉴权下载，需要另行实现更新客户端鉴权，不能嵌入共享凭据。

在现有 HTTPS 站点中可按需加入独立静态目录，例如：

```nginx
location = /updates/remote/latest.json {
    alias /var/www/private-agent-updates/remote/latest.json;
    default_type application/json;
    add_header Cache-Control "no-store" always;
}

location ^~ /updates/remote/ {
    alias /var/www/private-agent-updates/remote/;
    autoindex off;
}
```

这是供管理员审查后部署的示例，不是已生效配置。发布时先上传新的不可变版本目录和安装包，核对下载哈希，再原子替换 `latest.json`，避免用户先看到清单却下载不到包。保留旧版本下载文件和原清单用于故障处置，不强制降级已有客户端。

## 验收

在专用测试更新地址上至少执行一次旧版到新版的真实升级，确认：

1. 检查更新显示正确版本；重复点击不会并发安装；取消确认不会下载。
2. 安装包下载完成且验签成功后才退出客户端；断网或无效签名时不启动安装程序。
3. 错误上传本地版清单时，远程版因缺少 `remote-windows-x86_64` 条目而拒绝升级。
4. 检查后发布版本变化时，安装拒绝继续并要求重新检查。
5. 升级后仍连接原 API，版本已变化，登录和客户端偏好按预期保留。
6. 本地版可以共存，不被远程安装程序停止、覆盖或卸载。

本地回归命令：

```powershell
node --test scripts/build-remote-client.test.cjs
cd apps/desktop
npm.cmd test -- src/components/UpdateChecker.spec.ts
npm.cmd run build
```

这些单元检查不能替代真实签名安装和线上升级验收。未完成托管与验收之前，不应声称用户已经可以在线更新。
