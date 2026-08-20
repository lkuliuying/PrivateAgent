# PrivateAgent v0.5.0-rc.4 观察 Day 1（2026-08-11）

> 路线更新（2026-08-20）：本轮观察在 Day 10 后停止继续计时，统一顺延到 `v1.0.0-rc.1` 功能开发完成后重新开始。本文保留为历史事实，见 [观察期顺延决策](../observation-policy-20260820.md)。

> 观察起点：唯一一次 14 天整体观察的第 1 天。
> 冻结提交：见 `git rev-parse HEAD`（本提交；冻结声明见
> `docs/releases/v0.5.0/v0.5.0-rc.4-checkpoint-20260810.md`）。

## 1. 冻结基线

| 项 | 值 |
|---|---|
| 冻结提交 | 本提交（checkpoint 文档同提交） |
| 版本 | 0.5.0-rc.4 |
| 安装包 SHA-256 | `6189ba9bc85cae93f142b27f0cc99c70e69cdf44ddfacc7bd6b855fedc575449` |
| updater 端点 | `https://github.com/lkuliuying/PrivateAgent-updates/releases/latest/download/latest.json`（匿名可达） |
| 公开通道 latest | 0.5.0-rc.4（非 prerelease） |
| 源仓库 rc.4 状态 | Release 标记 prerelease；`0.5.0-rc.4` 标签指向冻结提交 |
| 机器基线 | 本机安装 rc.4（DisplayVersion=0.5.0-rc.4）；数据目录 `.env` 恢复 `PA_DB_NAME=personal_assistant` |
| 门禁 | release-check-full 14/14 `ok=True`；pytest 739 / Vitest 104 / E2E 52 / Cargo 15 |
| 安装版运行时 smoke | 6/6（qa-evidence 绑定冻结提交；run A completed 且无 failed execution） |
| 数据保留 | 升级/回退演练 preserved=true（upgrade_e2e 隔离库）；in-app 演练 preserved=true |

## 2. 观察期间每日检查（Day 2..14）

1. **版本/基线稳定**：本机安装版仍为 0.5.0-rc.4；应用可正常启动，诊断页 schema 0026 / 67 表。
2. **updater 通道稳定**：`releases/latest/download/latest.json` 仍匿名返回 rc.4 清单；
   安装版「检查更新」显示已是最新。
3. **数据稳定**：`scripts/upgrade_smoke.py --snapshot`（PA_DB_NAME=personal_assistant）
   无异常丢失/剧增；日志 `%APPDATA%/personal-assistant/logs/personal_assistant.log`
   无 ERROR 风暴。
4. **可信工作流**：运行 `scripts/v050_workflow_smoke.py` 保持 6/6（若环境 LLM 波动，
   重试 ≤5 轮后仍须 6/6）。
5. **进程/资源**：无孤儿 sidecar、无异常内存增长。

> 每日检查记录建议追加到本文件或 `docs/releases/v0.5.0/` 下独立日志；
> 观察结论在 Day 14 汇总，决定是否升版 0.5.0。

## 3. 已知环境事实（不属于发布物缺陷）

- 本机 github.com 直连被重置，需 WinINET 代理 `127.0.0.1:10808`
  （项目既有约定，见 `scripts/build-release.bat` 注释）。
- 本机 Ollama 曾出现孤儿 `ollama_llama_server` 占用 VRAM 导致模型退回 CPU 推理
  （smoke 相应放宽了 run limits 与超时；恢复正常后全量上 GPU）。
- 安装包未做 Authenticode 签名（无证书），SmartScreen 可能提示；
  属已知限制（`dist/unsigned-note-0.5.0-rc.4.md`）。
