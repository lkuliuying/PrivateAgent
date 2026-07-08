# 私人助手 Agent · 第五阶段安装包与更新机制（历史入口）

> 本文件保留为历史入口，避免旧链接失效。第五阶段已经拆分为两份正式文档：
>
> - 需求文档：`docs/phase5-requirements.md`
> - 开发计划书：`docs/phase5-plan.md`

---

## 当前状态

第五阶段当前定位为“安装包、自动更新与发布工程化”。仓库已经具备 NSIS 安装包、首启配置向导、sidecar 生命周期管理和 Tauri updater 命令接线，但仍需继续完成：

- updater 发布源端到端验证；
- Windows 代码签名方案；
- 可复现 release build；
- 安装、升级、卸载 QA 矩阵；
- onefile/onedir 体积与启动性能评估；
- macOS/Linux 跨平台预研。

后续请以 `docs/phase5-requirements.md` 与 `docs/phase5-plan.md` 为准。
