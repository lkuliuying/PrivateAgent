# Windows 截图视觉回归

桌面端使用 Playwright 像素断言维护 Windows Chromium 基线。视觉测试与动画行为测试分开：`animation.spec.ts` 验证动画会发生、能按 reduced-motion 降级并在视图切换时清理；`visual.spec.ts` 比较 reduced-motion 下的最终稳定状态，避免把过渡帧固化为基线。

## 覆盖矩阵

当前共有 11 个整页场景：

| 视图与模式 | 900×600 | 960×720 | 1440×900 | 1920×1080 |
|---|---:|---:|---:|---:|
| Today Light | ✓ | ✓ | ✓ | ✓ |
| Today Dark | — | — | ✓ | — |
| Today High contrast | — | — | ✓（Light + Dark） | — |
| Tasks Light | — | ✓ | ✓ | — |
| Chat Dark | ✓ | — | ✓ | — |

Tasks 与 Chat 的 1440×900 场景还分别对 `.task-main` 和 `.chat` 执行更严格的局部截图断言。因此基线目录共有 13 张 PNG：11 张整页图和 2 张关键区域图。

测试冻结在 `2026-07-15 10:30 Asia/Shanghai`，固定中文区域、时区、设备像素比、主题、对比度和 API 数据。视觉 fixture 使用生产 `/health` 契约（包括 `api: { ok: true }`）；所有会被当前页面请求的 API 都必须显式给出结构正确的响应，未登记的 API 路径会直接抛错并令测试失败，避免用空数组掩盖接口契约漂移。

截图前会等待接口、字体、图片及连续两帧渲染稳定，并把滚动容器归零。截图断言隐藏光标、关闭动画和 transition，全局最多允许 `0.1%` 的差异像素；Tasks 与 Chat 的关键区域最多允许 250 个差异像素。动画轨迹、状态切换和清理由 `animation.spec.ts` 单独阻断，截图只负责主题、排版、响应式断点和动画完成后的静态视觉结果。

## 运行与更新

在 `apps/desktop` 目录执行：

```powershell
npm run e2e:visual
```

基线位于 `e2e/visual-baselines/win32/chromium/`，必须纳入版本控制。失败时 Playwright 会在 `test-results/` 写入 expected、actual、diff 和 trace 等诊断材料。

只有确认 UI 变化符合设计意图后才能更新：

```powershell
npm run e2e:visual:update
git diff --stat -- e2e/visual-baselines
```

逐张检查更新后的 PNG，不要在测试失败时直接接受全部新基线。普通 `npm run e2e` 也会执行视觉断言，因此 `.github/workflows/windows-release-assurance.yml` 会同时运行截图、响应式和动画行为回归，并在失败时上传诊断 artifact。

## Windows runner 与证据

基线按 `{platform}/{projectName}` 隔离，目前只维护 `win32/chromium`。依赖通过锁文件安装，Playwright 使用与锁定版本匹配的 Chromium，设备像素比固定为 1。

GitHub Actions 的 `windows-2025` 是持续更新的托管 runner 标签，不是不可变镜像。每次接受或更新基线时，必须随 Actions run URL 留存作业 `Set up job` 中记录的 Image OS/Image Version；若 runner image 版本变化导致渲染差异，应先检查 actual/diff，记录旧、新 image 版本，再由人工确认是否更新基线。不能仅因 runner 更新而自动接受新截图。

当前发布范围只验证 Windows；非 Windows 环境会明确跳过这组基线。
