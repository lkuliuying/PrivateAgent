# Coding S0 可复现验收入口

在仓库根目录使用现有 Python 环境，无需安装依赖：

```powershell
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite all
.venv/Scripts/python.exe -B scripts/run_coding_validation.py --suite duration
```

每次自动新建 `.run/coding-agent-validation/<suite>-<uuid>`，保留 `invocation.json`、`pytest-result.json` 和 `observations/*.json`。不复用或递归删除旧目录，不使用 pytest 会清理目标目录的 `--basetemp`。

`all` 包含 local、contracts、baseline、host、tooling；`duration` 是独立约 120 秒的真实超时探针。每个子套件都可单独运行。首轮启动失败、收集错误和用例失败均非零退出；严格 xfail 和 PTY 不可用单独列出，不能计入产品通过率。意外 XPASS 会失败，要求后续修复阶段重新审查基线。

## 测试隔离

启动器显式加载 `pytest_asyncio.plugin` 和 `coding_validation_plugin`，设置 `--noconftest`、禁用自动插件发现、清除外部 pytest 选项。插件拒绝导入业务配置、数据库及主 API；本机专用 API 使用临时 SQLite 和 MockTransport。子进程只继承必要系统环境，不继承 `PA_*`、模型凭据、Python/Node 注入选项；测试路径、配置文件和源码路径均为绝对路径。

专用 `tmp_path` 使用新 UUID 和继承 ACL，绕过 pytest 私有目录 ACL 的 Windows 问题。命名管道的 `WinError 5` 与目录 ACL 是不同限制：受限运行环境若仍阻止子进程，应在获准的开发终端重跑相同命令，不修改业务代码或放宽测试断言。进程采用 Windows Job/其他平台进程组回收；这不构成对恶意候选代码的 OS 沙箱。

只使用已审查的固定套件，不是通用任意测试执行入口。真实宿主测试需要先 `cargo build --release --locked --offline --manifest-path apps/exec-host/Cargo.toml`；缺少宿主按失败处理。宿主探针只写临时项目及其临时兄弟文件，仅连接自己创建的回环监听器，不访问外部网络。未运行会修改系统解释器目录 ACL 的旧 AppContainer spike。

## 30 个固定任务

`tasks.json` 是唯一任务来源，内含起始代码、提示词、可编辑文件、JSON 判定用例和判定器正对照参考实现。三类项目各 10 项：Python 小型包、Node ESM 小型包、Python/Node 混合工作区。PY07 的目标位于约 2000 行的大文件尾部；每份夹具带须保留的用户内容。没有虚构 git 提交：这些是可重建的合成项目树，实际 Git dirty 行为由单独本机回归覆盖。

固定划分为 24 开发任务、6 留出任务（每类 09/10）；留出集不用于修改提示词。参考答案和判定器不复制到候选项目，但它们在本仓库可读，因此这不是防作弊的盲评环境。S6 若用于正式质量结论，应先将留出判定器交给独立评测环境，并扩大真实项目工作流覆盖，不能将这 30 个小任务等同复杂仓库独立完成率。

预算记录：每次最多 24 模型请求、48 工具调用、3600 秒、120000 总 token，每模型 3 次。前面三个上限依据现有 Runtime；token 是评测预算，当前 Runtime 尚未执行该 token 门禁。S0 不调用模型，所有模型结果为 `not_run`，正对照仅验证任务可判定。

```powershell
.venv/Scripts/python.exe -X utf8 -B scripts/coding_task_baseline.py list
.venv/Scripts/python.exe -X utf8 -B scripts/coding_task_baseline.py rebuild --task PY01 --directory F:/Program/Agent/.run/s0-py01
.venv/Scripts/python.exe -X utf8 -B scripts/coding_task_baseline.py judge --task PY01 --directory F:/Program/Agent/.run/s0-py01
```

`rebuild` 的父目录须已存在，目标必须是新目录；复跑更换目录。初始实现应判定失败并返回 1；修改目标文件后用同一 `judge` 再判定。判定器执行候选函数、核对输出并保护非编辑文件，不采用模型自评。候选代码按当前用户权限执行，存在 10 秒超时及进程树回收；只对受信任的隔离测试项目使用。实际账号数据和生产仓库不能作为夹具目录。

`test_tooling.py` 对每个任务验证“起始实现失败、参考实现通过、用户文件被改则拒绝”，不把这些正对照算作 Agent 完成。

## 契约维护

从 `private_agent_core/coding_contracts.py` 修改类型，再运行 `scripts/protocol_codegen.py`。`--check` 校验旧协议与新 Coding 生成物，`test_contracts.py` 校验 Schema、实例及业务不变量。新类型尚未接入业务 DTO；准确接入责任见 [S0 契约决议](../../docs/analysis/coding-agent-upgrade-20260908/s0-contract-decisions.md)。
