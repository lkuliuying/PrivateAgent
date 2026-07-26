# 真实服务长稳与大文档压力测试

`scripts/stress_real_services.py` 使用生产代码路径测试真实 Ollama、MySQL 与本地持久化 Chroma：

```text
大文档生成 → 文档解析/切片 → Ollama embedding
                         ├→ MySQL doc_chunks + FULLTEXT
                         └→ Chroma 向量
查询 → Ollama embedding → Chroma + MySQL 混合召回/重排 → Ollama chat
```

生产导入按 32 个切片做有界 embedding 与双索引增量写入；任一批失败或任务取消都会清理该文档已经写入的 MySQL/Chroma 数据。压力门禁执行真实 MySQL `MATCH ... AGAINST`，并要求混合结果同时证明 `vector`、`bm25` 和 embedding rerank 路径，不能以单路降级结果冒充成功。

它是显式 opt-in 的独立门禁，不属于日常 pytest。未提供 `--confirm-real-services` 时不会连接服务或创建数据。

## 数据安全边界

- 不会使用或清理 `personal_assistant` 等现有数据库。每次运行只创建一个由随机 run id 派生的 `pa_stress_*` 数据库。
- 建库后会把随机 ownership nonce 同时写入数据库内的专用表和临时目录 marker；删除前重新校验数据库名、run id、文件 marker 与库内 nonce，任何一项不一致都会失败关闭。
- 清理授权同时绑定业务 `database_url` 与 `admin_url`：两者的 driver、账号、密码、host、port 和 query 必须完全一致，业务 URL 必须指向本次 `pa_stress_*` 库，admin URL 必须指向同一服务器的 `mysql` 库。替换管理端服务器、端口或数据库都会拒绝清理。
- Chroma、生成文档和运行文件只写入本次运行独占的 `pa-stress-data-*` 临时目录。
- 正常或失败退出都会先停止资源采样、关闭 Provider、后台任务、Chroma 和 SQLAlchemy，再删除本次数据库和临时目录。周期资源采样受 `operation-timeout-seconds` 约束；退出时先做有界等待，超时后取消 sampler，无法按清理期限停止会成为 blocker。
- MySQL 删除失败时保留带所有权标记的临时目录，不扩大清理范围，并把失败记录为 blocker。
- 凭据只从 `.env` 的现有配置或 `PA_STRESS_MYSQL_URL` 环境变量读取，禁止通过命令行参数传递；JSON/Markdown 报告不会写入凭据。
- 默认只允许 loopback MySQL/Ollama。远程目标必须分别显式增加 `--allow-remote-mysql` 或 `--allow-remote-ollama`。
- 建库前执行磁盘预检：要求可用空间至少为 512 MiB，且不少于原始测试文档总大小的 4 倍；预检值和实际运行前可用空间都会写入报告。空间不足时不会创建测试数据库。

运行账号需要 `CREATE DATABASE`、`DROP DATABASE` 和迁移所需权限。

## 运行前准备

确认真实模型已经存在：

```powershell
ollama list
```

如需启动 Ollama：

```powershell
ollama serve
```

可以明确提供专用 MySQL 凭据，脚本仍会忽略 URL 中的数据库名并创建隔离库：

```powershell
$env:PA_STRESS_MYSQL_URL = "mysql+aiomysql://stress_user:PASSWORD@127.0.0.1:3306/mysql?charset=utf8mb4"
```

也可以使用项目 `.env` 中的账号权限，但绝不会复用其数据库：

```powershell
scripts\stress-real-services.bat --confirm-real-services --use-configured-mysql-credentials
```

## 推荐配置

低资源真实 smoke（只确认强化后的链路和证据字段可工作）：

```powershell
scripts\stress-real-services.bat `
  --confirm-real-services `
  --use-configured-mysql-credentials `
  --llm-model qwen2 `
  --embed-model bge-m3 `
  --duration-seconds 5 `
  --concurrency 1 `
  --document-count 1 `
  --document-size-mb 0.02 `
  --sample-interval-seconds 1
```

15 分钟发布候选门禁：

```powershell
scripts\stress-real-services.bat `
  --confirm-real-services `
  --use-configured-mysql-credentials `
  --duration-seconds 900 `
  --concurrency 4 `
  --document-count 2 `
  --document-size-mb 4
```

夜间长稳与大文档配置：

```powershell
scripts\stress-real-services.bat `
  --confirm-real-services `
  --use-configured-mysql-credentials `
  --duration-seconds 28800 `
  --concurrency 8 `
  --document-count 4 `
  --document-size-mb 25 `
  --sample-interval-seconds 10 `
  --max-rss-mb 12288
```

`duration-seconds` 只计算导入完成后的稳态阶段；文档生成、迁移、导入、完整性检查和清理时间另外统计。以上 8 小时命令是可重复配置，不代表仓库已经取得 8 小时实测结果。

## 阈值、完整性与证据

默认 blocker 阈值：

| 路径 | p95 上限 |
|---|---:|
| 大文档导入 | 600000 ms |
| MySQL 查询 | 750 ms |
| Ollama embedding | 30000 ms |
| Chroma 查询 | 2000 ms |
| 混合 RAG | 60000 ms |
| Ollama chat | 120000 ms |

默认最大错误率为 1%，最大进程 RSS 为 8192 MiB，稳态阶段首末 RSS 增量上限为 256 MiB。五条稳态查询路径还必须分别达到最低 `0.01` 次/秒，可用 `--min-steady-throughput-per-second` 调整。可以用 `--thresholds-json path.json` 覆盖已知路径的 p95；未知键、非正数或非有限值会被拒绝。

完整性门禁不只比较数量：

- MySQL 切片数必须等于 Chroma 向量数；
- MySQL 与 Chroma 的精确 chunk ID 集合必须一致；
- 每份生成文档都有独立 marker，该 marker 必须存在于对应 MySQL 切片，并能通过真实混合 RAG 检索回对应文档；
- 任一数量、ID 集合或逐文档 marker 检查失败都会成为 blocker。

每次运行在 `dist/stress/` 生成时间戳化 JSON 和 Markdown，包含：

- 每条路径的请求数、成功/失败数、错误率、吞吐量、p50/p95/p99/max；
- 进程 RSS、Python 分配峰值、CPU 时间、隔离目录大小；
- 文档导入与稳态阶段的资源采样、稳态首末 RSS 增量及小时折算值；样本不足、无法取得 RSS、采样失败或 sampler 无法在清理期限内停止都会阻断；
- SQLAlchemy 连接池与应用后台任务 queued/running；
- MySQL/Chroma 数量、精确 chunk ID 集合和逐文档 marker 检查；
- Git commit、已跟踪工作树 dirty 状态，以及 `uv.lock`、桌面端 `package-lock.json`、updater verifier `Cargo.lock` 的 SHA-256；
- Ollama/Chroma/MySQL 版本、LLM 与 embedding 模型 tag 和 Ollama digest；
- Windows/CPU 架构、处理器、逻辑核心数、磁盘预检、参数、阈值、blocker 和逐项清理结果。

正式发布证据应来自最终提交，`git_dirty` 应为 `false`，并把 JSON/Markdown 作为受控构建 artifact 留存。`dist/` 默认不入库，因此只保留本机路径不能替代发布证据。

退出码 `0` 表示所有阈值、完整性和清理门禁均通过，`1` 表示压力测试或清理出现 blocker，`2` 表示没有显式授权或安全配置不成立。

## 2026-07-26 证据状态

以下结果必须按产生它们时的门禁版本解释：

- `real-services-20260726t060158_08b365f119.*`：历史 schema v1 大文档结果。它曾完成真实 `qwen2`、`bge-m3`、MySQL 8.0.41、Chroma 1.5.9 的 1 × 4 MiB Markdown 导入，共 9,987 个切片，导入约 259.7 秒，随后并发 2 运行约 300 秒且清理成功。但 schema v1 不包含当前的采样 phase/稳态 RSS、来源绑定、模型 digest、精确 ID、逐文档 marker 和最低吞吐门禁，只能作为历史性能参考，不能作为当前实现的最终大文档验收证据。
- `real-services-20260726t062028_f6d5aab1d1.*`：历史 15 分钟结果。它记录并发 4 稳态运行约 900.6 秒、查询路径零错误和清理成功，但产生于本轮来源绑定、精确 ID、逐文档 marker、磁盘预检与吞吐门禁加入之前，同样不能单独作为当前强化实现的最终发布证据。
- `real-services-20260726t074119_ad6bc04457.*`：当前强化机制 smoke。它使用 1 × 0.02 MiB 文档、并发 1、稳态约 5.2 秒，验证了模型 digest、Git/锁文件来源、磁盘预检、精确 chunk ID、逐文档 marker、最低吞吐和清理字段均能产出并通过。该报告记录 `git_dirty: true`，只证明实现链路可工作，不是长稳、大文档或发布验收证据。

当前尚未生成基于最终干净提交、同时满足现行强化门禁的大文档和长时间运行报告，也没有可宣称的 1 小时或 8 小时实测结果。完成正式运行后，应留存新的 schema v2 JSON/Markdown、对应 Git commit 和受控 artifact 地址，再更新本节。
