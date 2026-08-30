# 管理员服务日志

管理员客户端左侧按「系统 → 用户 → 日志」排列。日志页提供 Supervisor 应用输出、Supervisor 进程管理、Nginx 访问和错误日志；普通用户不能调用对应接口。

## 服务器接入

后端更新并重启后，管理员访问 `GET /admin/logs` 获取固定来源，再以 `GET /admin/logs/{source_id}` 查看尾部。源码默认路径与 `deploy/centos-stream9` 的部署模板一致；实际部署（包括宝塔）路径可能不同，必须由部署管理员核对后配置以下设置：

| 设置 | 固定来源 ID | 默认路径 |
|---|---|---|
| `PA_ADMIN_SUPERVISOR_LOG` | `supervisor` | `/var/log/private-agent/supervisor.log` |
| `PA_ADMIN_SUPERVISORD_LOG` | `supervisord` | `/var/log/supervisord.log` |
| `PA_ADMIN_NGINX_ACCESS_LOG` | `nginx-access` | `/var/log/nginx/private-agent-access.log` |
| `PA_ADMIN_NGINX_ERROR_LOG` | `nginx-error` | `/var/log/nginx/private-agent-error.log` |

这些值只允许在服务端配置，不接受客户端传入任意路径。不要指向环境文件、密钥文件、目录、FIFO 或符号链接；不要让不可信用户写入这些日志目录。配置不同路径后，按部署流程重启应用服务；读取日志本身不会重启 Supervisor/Nginx，也不会执行 shell 命令。

后端运行账号（标准部署为 `privateagent`）需要父目录的遍历权限和指定日志文件的只读权限。不要为此改成 root 运行、放开整个 `/var/log`、设置 777 或赋予日志写权限。由管理员按照服务器既有分组或 ACL 策略授权具体文件，并验证日志轮转后新文件仍可读。无法读取时页面显示对应原因，不自动修改权限。

## 安全与行为

- 使用既有管理员身份校验；匿名返回 401，普通用户返回 403。读取文件发生在鉴权之后。
- 每次最多读取尾部 256 KB，返回 1–1,000 行；关键字只搜索此次读取并脱敏后的尾部，不是全文搜索。
- 路径不可由请求指定；非普通文件和符号链接会被拒绝。返回值不携带服务器绝对路径。
- 凭据关键字所在行、私钥块、URL 用户信息和查询参数会隐藏。过滤是保守防护，不能替代服务端从源头禁止记录秘密；禁止将请求正文、密码或完整认证头写入生产日志。
- 响应标记 `Cache-Control: no-store`；客户端不将日志写入持久缓存，不执行日志中的 HTML。
- 自动刷新默认关闭，开启后最多每 5 秒请求一次；切换来源取消旧请求，离开日志模块清除定时器并中止请求。
- 提供查看能力，不提供清空日志、任意文件下载、命令执行或服务控制。

## 验证

前端：

```powershell
cd apps/desktop
npm.cmd test -- src/components/AdminLogsPanel.spec.ts src/pages/AdminPage.spec.ts
npm.cmd run build
```

后端独立测试使用 `tests/unit/test_admin_logs.py`，只生成测试日志，不连接数据库，也不读取真实 Supervisor/Nginx 文件。应从不含环境文件的独立临时工作目录运行，并把仓库 `src` 加入 `PYTHONPATH`：

```text
python -X utf8 -B -m pytest <仓库>/tests/unit/test_admin_logs.py --noconftest -p no:cacheprovider -q
```

Windows 没有创建符号链接权限时，真实符号链接用例会明确跳过；仍应在 Linux 验收该边界。上线后分别用管理员与普通账号验证，再触发一次日志轮转确认读取权限没有失效。此文档不表示服务器配置或客户端安装包已经更新。
