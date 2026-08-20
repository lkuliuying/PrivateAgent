# PrivateAgent v0.5.0-rc.4 观察 Day 10（2026-08-20）

> 观察区间：Day 1 = 2026-08-11，Day 10 = 2026-08-20，计划 Day 14 = 2026-08-24。
> 冻结提交：`9250da68d4c018c676ec5ab38d5eb08103e8ed2d`（tag `0.5.0-rc.4`）。
> 记录性质：观察期只读检查、测试和报告，不属于候选功能代码。
> 路线更新：自本记录完成后停止 v0.5 自然日观察；最终观察移至 `v1.0.0-rc.1`，见 [观察期顺延决策](../observation-policy-20260820.md)。

## 1. 当日结论

截至 Day 10，冻结候选代码、数据库 schema、公开 updater 和四类可信工作流均未发现阻断性回归。原计划要求继续到 Day 14；后续路线决策已停止本轮计时，因此本文只作为 `v0.6.0` 的工程基线证据，不产生 v0.5 观察 pass/fail 结论。

当前状态：

- 候选代码保持在冻结提交，工作区变化仅为 `docs/` 下的后续规划和观察文档。
- 六处版本源和两个 lock 文件仍为 `0.5.0-rc.4`。
- Alembic 当前为 `0026 (head)`。
- 公开 updater 的 `latest.json` 仍匿名返回 `0.5.0-rc.4`，安装包 URL 与签名字段非空。
- 真实可信工作流 smoke 为 6/6，通过后未残留 sidecar、Ollama 或模型子进程。
- 未发现 P0/P1；性能门禁的并发负载抖动已按既有政策隔离复核。

## 2. 版本与候选代码完整性

| 检查项 | 结果 |
|---|---|
| Git HEAD | `9250da6` |
| HEAD tag | `0.5.0-rc.4` |
| Python / pyproject / package / Tauri / Cargo | 全部为 `0.5.0-rc.4` |
| package-lock / Cargo.lock | 全部为 `0.5.0-rc.4` |
| schema | `0026 (head)` |
| 非文档代码相对冻结提交的变化 | 无 |
| 当日工作区状态 | 仅后续规划和观察文档未提交；不属于候选代码 |

冻结时原始 `qa-evidence` 在复跑前已备份，并在复跑后恢复：

| 证据 | SHA-256 |
|---|---|
| 冻结基线 `dist/qa-evidence-0.5.0-rc.4.json` | `78DFCEFDFCE0D1F4BE3871A855857ACB278B81B602CDB069FA6ECD771E0F3568` |
| Day 10 `dist/observation/day10-20260820/qa-evidence-day10.json` | `B3BE3990CBC0DB162804228E8C3F1E0D18BFCC2568E8F945733D6E91EE0EC80E` |

## 3. 当日自动化门禁

| 门禁 | 结果 | 说明 |
|---|---:|---|
| pytest | 739 passed / 1 skipped | 4 分 38 秒 |
| Ruff | 通过 | `src tests scripts` 无问题 |
| Vue build | 通过 | `vue-tsc --noEmit` + Vite production build |
| Vitest | 104 passed | 22 个测试文件 |
| Cargo check | 通过 | Tauri/Rust dev profile |
| Cargo test | 15 passed | 0 failed |
| Alembic current | 通过 | `0026 (head)` |
| Playwright 主套件 | 51 passed / 1 performance failed | 与 Cargo 全量编译并发时长任务 p95 为 53–56ms |
| Playwright 性能文件隔离复核 | 3 passed | 无并发编译负载；longtasks=0，资源计数无增长 |

Playwright 首轮与 Rust 编译并行执行，不是正式串行 release-check 运行条件。该轮唯一失败与 rc.4 检查点已记录的“后台负载下 51–57ms 临界抖动”一致；停止并发编译后单独复核 3/3 通过。因此本次不修改候选代码或测试门槛，也不把并发负载下的失败隐藏为首轮通过。

## 4. 公开 updater 检查

2026-08-20 直接读取：

```text
https://github.com/lkuliuying/PrivateAgent-updates/releases/latest/download/latest.json
```

检查结果：

- `version = 0.5.0-rc.4`
- `windows-x86_64.signature` 非空
- 安装包 URL 指向 `PrivateAgent_0.5.0-rc.4_x64-setup.exe`
- 未发现通道版本漂移

## 5. 数据稳定性快照

通过 `scripts/upgrade_smoke.py --snapshot` 只读采集：

| 表 | 行数 |
|---|---:|
| sessions | 1001 |
| documents | 1120 |
| memory_items | 3 |
| agent_tasks | 158 |
| inbox_items | 40 |
| reminders | 3 |
| personal_goals | 3 |
| app_notifications | 327 |
| capture_items | 3 |
| ocr_jobs | 68 |

本快照保留为 v0.6.0 开工基线，不单独证明整个观察区间没有数据变化。数据保留的升级/回退证据继续以 rc.4 检查点中的隔离库与实机演练为准。

## 6. 真实可信工作流 smoke

执行：`uv run python scripts/v050_workflow_smoke.py`

| 场景 | 结果 | 事实 |
|---|---|---|
| Patch + command | 通过 | run completed；Patch verified；命令 succeeded；模型重试 2 次后形成完整同轮结果 |
| 命令取消 | 通过 | run cancelled；残留进程 0 |
| 只读 SQL | 通过 | run completed；read_only_confirmed=true |
| allowlist HTTP | 通过 | run completed；HTTP 200 |
| 总检查 | 6/6 | `passed=true` |

证据绑定冻结提交，运行耗时 354 秒。复跑使用临时项目目录和测试数据库；运行后恢复冻结证据并停止本次启动的 Ollama、模型和 sidecar 进程。

## 7. 本轮观察收口

原 Day 11–14、v0.5 observation report 和“观察通过后发布 v0.5 stable”任务已由顺延决策取消，不再继续勾选。Day 1/Day 10 证据保留，但不折算到最终 v1.0 观察；最终观察必须在 `v1.0.0-rc.1` 冻结后从 Day 1 重新计时。

## 8. 与 v0.6.0 的关系

`0.5.0-rc.4` 已转为 v0.6.0 工程基线，允许在独立开发分支提交 `v0.6.0` 业务实现。开工结论见 [`v0.6.0 开工就绪报告`](../v0.6.0/v0.6.0-readiness-20260820.md)。
