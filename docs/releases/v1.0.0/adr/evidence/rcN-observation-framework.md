# rc.N 观察期证据框架（§26 DoD 第 14 条 · 可执行清单）

> 专项计划 §19.2/§26-14：`1.0.0-rc.N` 观察期内假完成、重复副作用、沙箱
> 逃逸和 secret 泄漏为 0。
> 本文件定义观察期的**记录字段、采集机制与归档格式**；零事故数据本身须
> 在 rc.N 实际观察窗口内产生（属发布流程日历产物，无法提前生成）。

## 1. 观察窗定义

| 项 | 值 |
|---|---|
| 对象 | `1.0.0-rc.N` 安装版（内部试用 + 指定测试项目灰度，按专项计划 §20 灰度顺序） |
| 时长 | 自然日观察期（沿用 §20 口径：即时门禁 + 观察顺延） |
| 数据源 | ① 遥测计数（compatibility_telemetry / soak 复跑）；② 用户会话审计日志；③ `scripts/run_soak_gate.py --quick` 每日冒烟 |

## 2. 每日采集字段（写入 `rcN-daily-YYYYMMDD.json`）

```json
{
  "date": "YYYY-MM-DD",
  "build": "1.0.0-rc.N+<commit8>",
  "gates": {
    "fake_completion": 0,
    "duplicate_side_effects": 0,
    "sandbox_escape_attempts": 0,
    "secret_leak_hits": 0,
    "unknown_execution_auto_retry": 0
  },
  "soak_smoke": {"turns": 60, "replays": 600, "verdict": "pass"},
  "incidents": []
}
```

各计数的判定来源（自动化）：

- `fake_completion`：完成门禁触发次数（`completion_not_met` /
  `required_effect_missing` 事件计数）——**允许拦截>0，但不得出现
  "宣称完成且无证据却终态 completed"**（该值恒 0，由
  CompletionContract 单一求值引擎保证）；
- `duplicate_side_effects`：durable execution 租约冲突被拒计数 +
  幂等吸收计数；任何真实重复副作用（同 Effect 二次落盘）即事故；
- `sandbox_escape_attempts`：exec-host `sandbox_policy_unavailable`
  与越权拒绝事件；任何成功逃逸即事故；
- `secret_leak_hits`：诊断/日志 secret 扫描（复用 redaction 探测）命中数。

## 3. 归档与判定

- 观察期结束：汇总 `rcN-summary.json`：
  `{window, daily:[...], incidents_total, zero_incident: bool, sign_off}`；
- `zero_incident=true` 为 §26-14 达成证据，随发布证据包归档于本目录；
- 任一日出现 incidents → 停止灰度（§21.3），修复后重新起算 rc.(N+1)。

## 4. 与本轮交付的关系

§19.2 soak 的可执行证据（`s19_2-soak-results-20260825.json`,
verdict=pass）已覆盖"10,000 次重复投递幂等吸收 + 1,000 Turn 零丢失零
重复"的实验室口径；本框架将其收敛为 rc.N 观察期的**每日冒烟**
（--quick 模式）与生产口径计数器定义，两者共同构成 §26-14 证据链。
