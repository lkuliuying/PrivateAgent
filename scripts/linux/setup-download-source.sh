#!/usr/bin/env bash
# 只初始化 Ubuntu 24.04 上的新下载站点；已有站点和证书配置不覆盖。
set -euo pipefail

if [[ "$#" -ne 1 || "$EUID" -ne 0 ]]; then
    printf '%s\n' '用法：sudo bash setup-download-source.sh <已核验的上传包目录>' >&2
    exit 1
fi
source /etc/os-release
if [[ "${ID:-}" != ubuntu || "${VERSION_ID:-}" != 24.04 ]]; then
    printf '%s\n' '仅支持专用 Ubuntu 24.04 服务器。' >&2
    exit 1
fi
package=$(realpath -- "$1")
cd -- "$package"
sha256sum --check --strict SHA256SUMS
domain=$(cat DOMAIN)
if [[ ! "$domain" =~ ^[a-z0-9][a-z0-9.-]*\.[a-z][a-z0-9.-]*$ ]]; then
    printf '%s\n' '上传包中的下载域名无效。' >&2
    exit 1
fi
site=/etc/nginx/sites-available/privateagent-download
enabled=/etc/nginx/sites-enabled/privateagent-download
if [[ -e "$site" || -L "$site" || -e "$enabled" || -L "$enabled" ]]; then
    printf '%s\n' '下载站点已存在，拒绝覆盖；发布新版本请直接运行发布脚本。' >&2
    exit 1
fi
if [[ -L /srv/privateagent-download ]]; then
    printf '%s\n' '下载目录不能为符号链接。' >&2
    exit 1
fi

apt update
apt install -y nginx snapd python3
systemctl enable --now nginx
snap install --classic certbot
install -d -m 0755 /srv/privateagent-download
install -m 0644 privateagent-download.conf "$site"
ln -s "$site" "$enabled"
nginx -t
systemctl reload nginx

# DNS 与公网 80 端口必须就绪；证书工具会交互询问联系邮箱和服务条款。
/snap/bin/certbot --nginx -d "$domain" --redirect
nginx -t
/snap/bin/certbot renew --dry-run
python3 "$package/publish_download_source.py" "$package"
printf '%s\n' "站点文件已发布。请从用户电脑验收 https://$domain/latest.json 和完整安装包下载。"
