# CentOS Stream 9 源码部署

> 本文是早期通用模板，示例端口和目录不代表现有部署。2026-08-30 已实施部署的差异、验证结果与升级注意事项见 [部署交接总结](./deployment-handoff-20260830.md)，换电脑开发见 [开发交接指南](./new-computer-development.md)。不要用本模板覆盖正在运行的配置。

本文面向一台 CentOS Stream 9 服务器，使用以下拓扑：

```text
桌面客户端
  └─ HTTPS https://agent.example.com:6000
       └─ Nginx :6000（TLS、SSE 反向代理）
            └─ Uvicorn 127.0.0.1:8000（FastAPI/ASGI）
                 ├─ MySQL 127.0.0.1:3306
                 ├─ Chroma /var/lib/private-agent/chroma
                 └─ Ollama 127.0.0.1:11434

Supervisor ──管理──> 单个 Uvicorn 进程
```

示例域名统一为 `agent.example.com`，部署前必须替换。Nginx 的公网监听端口是 `6000`，后端 `8000` 不开放防火墙。

## 1. 为什么不用 uWSGI

该项目是 FastAPI 应用，入口 `personal_assistant.main_api:app` 遵循 ASGI，并使用应用 lifespan、异步 SQLAlchemy 和 SSE 流式响应。uWSGI 的 Python 快速入门及应用加载接口面向 WSGI；用 WSGI/ASGI 转接器会丢失或削弱 lifespan、流式取消和长连接语义，因此不能作为本项目的生产应用服务器。

这里保留 Supervisor + Nginx 运维结构，只把不兼容的 uWSGI 换为项目已经依赖的 Uvicorn。FastAPI 官方也明确要求远程部署使用 Uvicorn、Hypercorn 等 ASGI server。

参考：

- [FastAPI：ASGI Servers](https://fastapi.tiangolo.com/deployment/manually/)
- [uWSGI：Python/WSGI Quickstart](https://uwsgi-docs.readthedocs.io/en/latest/WSGIquickstart.html)
- [Supervisor program 配置](https://supervisord.org/configuration.html#program-x-section-settings)
- [RHEL 9：Nginx 安装与反向代理](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html/deploying_web_servers_and_reverse_proxies/setting-up-and-configuring-nginx_deploying-web-servers-and-reverse-proxies)

## 2. 前置条件

- 已将本地提交推送到服务器可访问的 Git 远程。
- 域名 `agent.example.com` 已解析到服务器。
- 已取得该域名的 TLS 证书。由于公网端口是 `6000`，可使用 DNS-01 签发，或在其他入口完成证书签发后复制证书。
- 服务器建议至少 4 核、8 GB 内存；若本机运行 14B Ollama 模型，需要按模型和并发增加内存/GPU。
- 以下命令由具有 `sudo` 权限的账号执行。

## 3. 安装系统服务

```bash
sudo dnf install -y git curl ca-certificates openssl nginx mysql-server firewalld policycoreutils-python-utils
sudo dnf install -y epel-release
sudo dnf install -y supervisor

sudo systemctl enable --now firewalld mysqld
sudo systemctl enable nginx supervisord
```

如果 `supervisor` 不在当前仓库中，先检查 `dnf repolist` 是否已启用 EPEL 9，不要改用项目虚拟环境安装 Supervisor；Supervisor 应独立于应用虚拟环境，避免 `uv sync` 时被删除。

## 4. 创建服务账号并克隆项目

将 Git 地址替换为自己的远程仓库：

```bash
sudo useradd --system --create-home --home-dir /var/lib/private-agent --shell /sbin/nologin privateagent
sudo install -d -o privateagent -g privateagent /opt/private-agent /var/lib/private-agent /var/log/private-agent

sudo git clone --branch dev/1.0.0 --single-branch YOUR_GIT_REMOTE /opt/private-agent/current
sudo chown -R privateagent:privateagent /opt/private-agent/current
```

不要把 Windows 上的 `.venv`、`data` 或 `.env` 复制到服务器。

## 5. 安装 uv、Python 3.12 与依赖

项目要求 Python 3.12+。使用 uv 的独立安装器可以避开 CentOS Stream 9 系统 Python 版本：

```bash
curl -LsSf https://astral.sh/uv/0.12.7/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
/usr/local/bin/uv --version

sudo -u privateagent env HOME=/var/lib/private-agent /usr/local/bin/uv python install 3.12
sudo -u privateagent env HOME=/var/lib/private-agent /usr/local/bin/uv sync \
  --directory /opt/private-agent/current \
  --frozen \
  --no-dev \
  --no-editable \
  --python 3.12
```

`--frozen` 确保服务器按已提交的 `uv.lock` 安装，不在部署时改写锁文件。生产进程直接使用 `/opt/private-agent/current/.venv/bin/python`，不依赖登录 Shell 的 PATH。

## 6. 初始化 MySQL

先执行 MySQL 安全初始化：

```bash
sudo mysql_secure_installation
sudo mysql
```

在 MySQL 控制台创建 UTF-8 数据库和仅限 loopback 的应用用户。把示例密码替换为强密码，并在下一步把同一个密码写入 secret 文件：

```sql
CREATE DATABASE personal_assistant
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'privateagent'@'127.0.0.1'
  IDENTIFIED BY 'REPLACE_WITH_A_STRONG_PASSWORD';

GRANT ALL PRIVILEGES ON personal_assistant.*
  TO 'privateagent'@'127.0.0.1';

FLUSH PRIVILEGES;
EXIT;
```

不要让 MySQL 监听公网，也不要开放 `3306/tcp`。

## 7. 配置环境变量和 secret

```bash
sudo install -d -m 0750 -o root -g privateagent /etc/private-agent
sudo install -m 0640 -o root -g privateagent \
  /opt/private-agent/current/deploy/centos-stream9/private-agent.env.example \
  /etc/private-agent/private-agent.env

sudo sh -c 'umask 0027; openssl rand -hex 32 > /etc/private-agent/api-token'
sudo chown root:privateagent /etc/private-agent/api-token

sudo install -m 0640 -o root -g privateagent /dev/null /etc/private-agent/mysql-password
sudo bash -c 'read -rsp "MySQL privateagent password: " value; printf "%s" "$value" > /etc/private-agent/mysql-password; echo'

sudo ln -s /etc/private-agent/private-agent.env /opt/private-agent/current/.env
sudo chown -h privateagent:privateagent /opt/private-agent/current/.env
```

编辑 `/etc/private-agent/private-agent.env`：

```bash
sudo vi /etc/private-agent/private-agent.env
```

至少替换以下内容：

- `agent.example.com`：真实 API 域名。
- `PA_DB_URL`：数据库名、用户名或地址有变化时同步修改，但密码继续放 secret 文件。
- `PA_OLLAMA_BASE_URL`、模型名称：按真实模型服务调整。
- 日志、审计和会话保留期。

首次注册管理员前保留 `PA_ALLOW_PUBLIC_REGISTRATION=true`；首个账号注册成功后必须改成 `false` 并重启后端。

## 8. 准备 Ollama

如果 Ollama 已运行在另一台可信服务器，只需修改 `PA_OLLAMA_BASE_URL` 并限制其网络访问。若运行在本机，确认以下探测成功并提前拉取环境文件中声明的模型：

```bash
curl --fail http://127.0.0.1:11434/api/version
ollama pull qwen2.5:14b-instruct-q4_K_M
ollama pull bge-m3
```

不要把未认证的 Ollama `11434` 端口暴露到公网。

## 9. 安装 Supervisor 配置

```bash
sudo install -m 0644 \
  /opt/private-agent/current/deploy/centos-stream9/private-agent.ini \
  /etc/supervisord.d/private-agent.ini

sudo systemctl start supervisord
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status private-agent
```

`personal_assistant.server_entry` 会在启动前执行 `alembic upgrade head`，迁移失败时拒绝启动。该项目的 Agent runtime 使用进程级所有权保护，因此模板固定只启动一个 Uvicorn 进程；不要设置 `numprocs > 1` 或 Uvicorn `--workers`。

查看日志：

```bash
sudo tail -f /var/log/private-agent/supervisor.log
sudo find /var/lib/private-agent/logs -maxdepth 1 -type f -printf '%f\n'
```

## 10. 配置 Nginx TLS 与 6000 端口

先把证书和私钥放到模板声明的路径，或者修改模板路径。私钥必须只允许 root 读取。

```bash
sudo install -m 0644 \
  /opt/private-agent/current/deploy/centos-stream9/private-agent.nginx.conf \
  /etc/nginx/conf.d/private-agent.conf
sudo vi /etc/nginx/conf.d/private-agent.conf

sudo semanage port -a -t http_port_t -p tcp 6000 2>/dev/null || \
  sudo semanage port -m -t http_port_t -p tcp 6000
sudo setsebool -P httpd_can_network_connect 1

sudo firewall-cmd --permanent --add-port=6000/tcp
sudo firewall-cmd --reload

sudo nginx -t
sudo systemctl restart nginx
```

模板已关闭代理缓冲并将读取超时设为一小时，以支持 SSE；Nginx 只代理到 loopback `127.0.0.1:8000`。不要在 firewalld 中开放 `8000`、`3306` 或 `11434`。

## 11. 验证

```bash
sudo supervisorctl status private-agent
sudo ss -lntp | grep -E ':(6000|8000|3306|11434)\b'
curl --silent --show-error --output /dev/null --write-out '%{http_code}\n' \
  https://agent.example.com:6000/
```

根端点没有用户会话时返回 `401` 属于正常鉴权行为；这证明 TLS/Nginx/API 链路可达。然后在桌面客户端登录页填写：

```text
https://agent.example.com:6000
```

注册首个账号并确认管理员页可打开。完成后：

```bash
sudo vi /etc/private-agent/private-agent.env
# PA_ALLOW_PUBLIC_REGISTRATION=false
sudo supervisorctl restart private-agent
```

再次打开注册页应得到服务端拒绝，现有账号登录和 SSE 对话应正常。

## 12. 更新、备份和回退

更新前至少备份 MySQL 与数据目录：

```bash
sudo mysqldump --single-transaction --routines --triggers personal_assistant > personal_assistant.sql
sudo tar -C /var/lib -czf private-agent-data.tar.gz private-agent
```

更新代码：

```bash
sudo supervisorctl stop private-agent
sudo -u privateagent git -C /opt/private-agent/current pull --ff-only
sudo -u privateagent env HOME=/var/lib/private-agent /usr/local/bin/uv sync \
  --directory /opt/private-agent/current --frozen --no-dev --no-editable --python 3.12
sudo supervisorctl start private-agent
sudo supervisorctl status private-agent
sudo nginx -t
```

代码回退只能切换到兼容当前数据库 revision 的提交。不要执行 `alembic downgrade`，除非已经验证迁移的可逆性、完成备份并明确接受数据风险。

## 13. 常见故障

- Nginx 返回 `502`：检查 `supervisorctl status private-agent` 和 `/var/log/private-agent/supervisor.log`。
- Nginx 无法连接 `127.0.0.1:8000`：确认 `setsebool -P httpd_can_network_connect 1`。
- Nginx 无法监听 `6000`：检查 `semanage port -l | grep http_port_t` 和 firewalld。
- API 启动后立刻退出：通常是 `.env`、secret 权限、MySQL 连接或 Alembic 迁移失败。
- 客户端拒绝服务器地址：远程生产地址必须是有效 HTTPS URL，并带上非默认端口 `:6000`。
- 流式回答延迟聚合：确认 Nginx 配置中 `proxy_buffering off` 没有被其他配置覆盖。
