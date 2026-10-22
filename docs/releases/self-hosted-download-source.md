# 自有 HTTPS 下载源

适用环境：香港专用服务器、Ubuntu 24.04 LTS、独立下载子域名和 Nginx。本页提供可执行的搭建与发布流程；脚本存在、离线验签成功和服务器上线是不同状态。

执行服务器步骤前，需购买服务器、建立 SSH/SFTP 连接，并确定实际下载子域名。域名、公网 IP 和连接方式尚未提供时，只准备本机材料，不能宣称下载源已上线。不要发送密码、私钥或云平台令牌。

## 1. 服务器与 DNS

小规模试用从 1 核、2 GB 内存、20 GB 磁盘起步，购买前核对大陆方向线路、带宽和流量额度。1.0.1 安装包为 46,447,315 字节，1,000 次完整下载约消耗 46 GB 流量；并发下载需要共享服务器出口带宽。

为现有域名增加 `download` 的 A 记录，指向新服务器公网 IPv4。初期直接解析，不增加 CDN；只配置已确认可用的地址记录。安全组开放 TCP 80、443，SSH 按管理来源限制。如果系统防火墙已经启用，也需允许 80、443，调整时保留当前 SSH 入口。

## 2. 在 Windows 准备上传包

下载同一个正式 GitHub Release 的安装包、`.sig`、`latest.json` 和 `release-verification-<版本>.json`。不要使用示例清单、候选版或 Remote 安装包。首次复用 [1.0.1 正式资产](https://github.com/lkuliuying/PrivateAgent/releases/tag/v1.0.1)，验收摘要见 [1.0.1 发布记录](v1.0.1/github-release.md)。

在仓库根目录编译已有公钥验签器：

```powershell
cargo build --offline --locked --release --manifest-path scripts/windows/updater-signature-verifier/Cargo.toml
```

本工作区已下载的公开资产位于 `.run/release-1.0.1-20261006/public-curl-assets`。在其他机器上改为实际下载目录。将下面的域名变量替换成实际下载子域名，然后执行：

```powershell
$downloadDomain = "替换为实际下载子域名"
.venv/Scripts/python.exe -B scripts/prepare_download_source.py `
  --source .run/release-1.0.1-20261006/public-curl-assets `
  --domain $downloadDomain `
  --out .run/download-source-1.0.1 `
  --verifier scripts/windows/updater-signature-verifier/target/release/private-agent-updater-signature-verifier.exe
```

该命令核对正式版本、GitHub URL、目标、资产大小和 SHA-256，再用当前正式客户端的公钥对上传副本进行真实验签。只改变镜像清单中的安装包 URL；安装器和 `.sig` 原始字节不变，不读取私钥，不修改来源资产或客户端。

输出目录必须全新，不能放在来源目录内部。再次生成时使用另一个输出目录，不删除原包或覆盖同版本产物。输出包含：

```text
download-source-1.0.1/
├── DOMAIN
├── SHA256SUMS
├── mirror-verification.json
├── updater-public-key.txt
├── privateagent-download.conf
├── setup-download-source.sh
├── publish_download_source.py
└── site/
    ├── latest.json
    └── 1.0.1/
        ├── PrivateAgent_1.0.1_x64-setup.exe
        └── PrivateAgent_1.0.1_x64-setup.exe.sig
```

上传目录包含约 46 MB 的安装器，属于交付产物，不加入 Git。公钥是公开材料，镜像验收记录不包含私钥、凭据或服务器连接信息。

## 3. 上传并初始化服务器

通过已经建立的 SSH/SFTP 连接，将完整目录上传到登录用户的 `~/privateagent-upload-1.0.1`。不要直接把暂存文件上传到网站根目录。进入服务器后，在首次初始化的新站点执行：

```bash
sudo bash "$HOME/privateagent-upload-1.0.1/setup-download-source.sh" \
  "$HOME/privateagent-upload-1.0.1"
```

脚本先检查 Ubuntu 版本、上传摘要、实际域名和站点冲突，再安装 Nginx、Snap、Python 3 和 Certbot，创建 `/etc/nginx/sites-available/privateagent-download` 及启用链接。已有同名站点不会覆盖。

DNS 和公网 80 端口需提前就绪。Certbot 会交互询问联系邮箱与服务条款，为当前下载域名申请证书并配置 HTTPS 跳转。证书及私钥由 Certbot 管理，不能放入网站目录、上传包或仓库。

初始化最后执行 `nginx -t`、证书续期演练和发布脚本。实际站点根目录为 `/srv/privateagent-download`。安装或证书失败会停止，不能将部分步骤成功写成完整上线。若证书步骤失败，先解决 DNS/80 端口问题，再针对实际域名执行：

```bash
sudo /snap/bin/certbot --nginx -d 实际下载子域名 --redirect
sudo nginx -t
sudo /snap/bin/certbot renew --dry-run
sudo python3 "$HOME/privateagent-upload-1.0.1/publish_download_source.py" \
  "$HOME/privateagent-upload-1.0.1"
```

初始化参考：[Ubuntu Nginx](https://ubuntu.com/server/docs/how-to/web-services/install-nginx/)、[Certbot Nginx](https://certbot.eff.org/instructions?os=snap&tab=standard&ws=nginx)、[Nginx 静态目录](https://nginx.org/en/docs/http/ngx_http_core_module.html#root)。

## 4. 发布后续版本

每个正式版本重新准备完整上传包并使用独立上传目录；之后只执行：

```bash
sudo python3 "$HOME/privateagent-upload-版本/publish_download_source.py" \
  "$HOME/privateagent-upload-版本"
```

发布脚本先校验全部必要文件，拒绝额外站点文件、未知摘要路径和符号链接。取得独占发布锁后，在站点之外、同一文件系统暂存并再次核对实际副本；先使版本目录就位，最后原子替换 `latest.json`。

保留所有旧版本。已有同版本安装器、签名或清单内容不同则拒绝覆盖；相同包可以重复发布；更新清单不能降级。清单切换失败时旧清单仍保留，新版本目录若已完整就位可供重试。

正常退出会释放发布锁。如果进程被强制终止，确认没有其他发布进程后，才可用 `sudo rmdir /srv/privateagent-download.publish-lock` 移除遗留空锁目录；不能在运行中的发布任务旁清锁。初始化脚本不用于重复部署，也不覆盖 Certbot 调整后的 HTTPS 配置。

服务器上的 SHA-256 校验用于检测上传及复制损坏，不是新的公钥验签；公钥复验在本机生成上传包时完成。上传使用可信 SSH/SFTP，验收时保留本机生成的 `mirror-verification.json` 作为对照。

## 5. 公网验收

把以下命令中的下载域名替换成实际值：

```bash
sudo nginx -t
sudo /snap/bin/certbot renew --dry-run
curl -fsS https://实际下载子域名/latest.json
curl -fSI https://实际下载子域名/latest.json
curl -fSI https://实际下载子域名/1.0.1/PrivateAgent_1.0.1_x64-setup.exe
curl -sSI https://实际下载子域名/nonexistent-file.exe
```

要求：清单和安装包返回 200；缺失文件返回 404；证书有效；清单响应包含 `Cache-Control: no-store`；清单版本为 1.0.1、目标为 `unified-windows-x86_64`，安装器 URL 指向同一下载域名。

在用户 Windows 电脑关闭代理后，完整下载 `.exe` 和 `.sig`，使用 `Get-FileHash -Algorithm SHA256 <下载文件>` 对照正式发布记录。再次用现有验签器和上传包里的公开公钥核验下载后的原始文件：

```powershell
scripts/windows/updater-signature-verifier/target/release/private-agent-updater-signature-verifier.exe `
  <下载的安装包路径> <下载的签名路径> <上传包中的updater-public-key.txt路径>
```

仅服务器本机访问成功、HEAD 成功或摘要正确不能替代用户电脑完整下载和公钥验签。保留下载大小、摘要、验签结果及使用的网络条件，不记录凭据或完整服务器日志。

## 6. 与现有客户端和项目状态的边界

当前正式 1.0.0/1.0.1 客户端仍内置 GitHub 更新地址，不会自动发现这个新下载站。复制现有 1.0.1 安装器到新站点不会改变该安装器的内置配置。后续正式版本接入新地址、GitHub 备用切换和旧用户手动升级是独立工作，本次不修改客户端、签名密钥、CI 或原有 GitHub 发布验收脚本。

现有 `verify_update_release.py` 严格验证 GitHub 发布契约，不能用于接受改过 URL 的镜像清单；原契约不放宽。本页和新生成入口独立验证镜像材料，维护下载站的持久操作约定。已读取历史 `docs/project-state.md`，旧安装及服务器状态不代表该新站点；按约定不自动改写其历史记录。

## 7. 本机脚本回归

先按第 2 节编译公钥验签器，再运行以下定向验证。临时目录使用全新名称，避免 pytest 清理其他任务的文件。若沙箱无法创建或读取测试目录，应在正常权限终端重跑；不能将权限阻断计为通过。

```powershell
$env:PYTHONPATH = (Resolve-Path 'scripts').Path
New-Item -ItemType Directory -Path '.run/download-source-validation' -Force | Out-Null
$downloadCheckTemp = Join-Path '.run/download-source-validation' ('pytest-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -B -m pytest tests/packaging/test_download_source.py tests/packaging/test_update_release_verification.py --noconftest -p no:cacheprovider --basetemp $downloadCheckTemp -q
.venv/Scripts/python.exe -B -m ruff check scripts/prepare_download_source.py scripts/linux/publish_download_source.py tests/packaging/test_download_source.py
& 'C:\Program Files\Git\bin\bash.exe' -n scripts/linux/setup-download-source.sh
```

本机回归覆盖公开向量的真实验签、上传损坏、版本冲突、降级、发布锁和清单替换失败后的重试；不能替代 Ubuntu 服务器的 Nginx、Certbot、DNS 和公网下载验收。
