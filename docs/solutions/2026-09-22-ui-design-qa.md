# PrivateAgent 全端视觉改造验收记录

> 归档说明（2026-09-22）：本文从项目根目录迁入，仅调整相对链接，以下测试结论仍属于原界面改造任务，本次目录清理没有重新运行这些界面断言。原始文件保存在 `.run/records/root/design-qa-20260922.md`。
> 原 `.tmp/ui-review-20260922/` 和 `.tmp/ui-redesign-20260922/` 的已归档截图分别位于 `.run/records/tmp/ui-review-20260922/` 和 `.run/records/tmp/ui-redesign-20260922/`。历史命令与输入路径保留原文；查找方式见[目录说明](../repository-layout.md#查找历史证据)。

日期：2026-09-22。范围：本机 Vue／Tauri 桌面前端。验收对象为当前已有未提交工作之上的增量改造。

final result: passed

## 2026-09-22 浏览器批注修订（当前状态）

本次依据用户在预览页的三条批注实施。批注对应的界面截图用于定位，图片内部文案不作为指令。以下修订覆盖首轮记录中有关品牌入口、首页间距和更新源表单的描述。

| 用户批注 | 当前实现 | 验证证据 |
| --- | --- | --- |
| 去掉左上角图标和名称 | Coding 与设置侧栏均移除品牌入口，删除无其他使用者的 `AppBrand.vue`；搜索、首页导航、返回应用和抽屉关闭保留。 | 首页、任务、资料和关于页截图；搜索、折叠、宽窄导航回归通过。 |
| 输入框下移，底部对齐并调整组件间距 | 就绪首页使用弹性纵向布局，输入区距窗口底部 16px；项目、快捷任务与输入区均衡分配剩余间距；中等高度压缩卡片，矮窗插画为 200px。 | 1488×1058、1280×720、1440×900、1920×1080 均断言底部间距；另通过 801／950／951 高度断点和 1120×986 抽屉布局检查。 |
| 删除更新源设置，用户直接检查更新 | 删除地址表单及本机地址覆盖逻辑。检查、安装均不传自定义地址，由原生层读取发布包配置；保留版本确认、签名校验和失败反馈。 | 单元测试覆盖无预设源、旧地址被忽略、配置失败、取消／重复安装及下载／重启失败；浏览器验证完整检查与确认安装流程。 |

已查看修订前后相同尺寸的首页，以及当前任务页、关于页、资料页、760／390 窄窗和 125%／150% 像素密度截图。没有待处理的 P0／P1／P2 问题。390px 宽度按现有单列布局滚动，底部对齐不以裁切项目或操作区域为代价。

本次截图根目录：`F:/Program/Agent/.tmp/ui-review-20260922/final/`。其中首页为 `visual-regression-设计稿对应尺寸预览-chromium/home-reference-size.png`，关于页为 `visual-regression-设置资料同步、插件、窄窗口与草稿往返-chromium/settings-about.png`。原预览页 <http://127.0.0.1:1431/index.html> 已同步这些真实 Vue 渲染截图。

### 本次验证命令与结果

命令在 `F:/Program/Agent/apps/desktop` 执行，使用隔离夹具，不访问真实模型或更新服务。

```powershell
node node_modules/vitest/vitest.mjs run src/components/UpdateChecker.spec.ts src/components/SettingsModuleNav.spec.ts src/features/coding/components/CodingHome.spec.ts src/features/coding/components/CodingSidebar.spec.ts
```

4 个测试文件、39 项通过。

```powershell
$env:PA_E2E_EXTERNAL_SERVER = '1'
node node_modules/@playwright/test/cli.js test e2e/coding-workbench.spec.ts e2e/workbench-upgrade.spec.ts e2e/visual-regression.spec.ts --retries=0 --reporter=line --output=../../.tmp/ui-review-20260922/final
```

30 项通过，无重试、未更新基线。覆盖首次发送、无项目／工作区／模型、错误重试、侧栏滚动与抽屉、资料与草稿往返、快捷任务、暂停／继续和更新入口。设置截图用例再次确认 0 个未知请求、0 个非预期后端写请求、0 个浏览器错误。

```powershell
node node_modules/@playwright/test/cli.js test e2e/visual-regression.spec.ts --update-snapshots --retries=0 --reporter=line --output=../../.tmp/ui-review-20260922/baseline-update
node node_modules/@playwright/test/cli.js test e2e/visual-regression.spec.ts --grep 'coding 首页 1920|coding 任务页' --update-snapshots all --retries=0 --reporter=line --output=../../.tmp/ui-review-20260922/baseline-complete
npm run build
```

六张基线逐张查看后更新。第一条命令 9 项通过；第二条 3 项通过，将变化小于旧容差的其余截图也同步为当前界面。构建通过 `vue-tsc --noEmit` 和 Vite，共转换 5096 个模块；已有大于 500kB 的 chunk 提示仍存在。

初轮验证发现 1440×900 的底部边距仅 4px，已通过中等高度布局修正。随后三个旧截图比较按预期失败，人工检查后更新基线；最终 30 项复跑全部通过。没有通过放宽容差或跳过用例处理失败。

### 本次增量文件

本轮开始前已保存 15 个相关文件快照。以下清单不混入首轮改造或其他既有工作；生成的预览和测试输出仍在 Git 忽略的 `.tmp` 目录。

| 操作 | 文件 | 变更 |
| --- | --- | --- |
| 删除 | `apps/desktop/src/components/AppBrand.vue` | 移除已不再使用的品牌入口。 |
| 修改 | `apps/desktop/src/components/SettingsModuleNav.vue` | 设置侧栏取消品牌入口。 |
| 修改 | `apps/desktop/src/features/coding/components/CodingSidebar.vue` | 侧栏改为顶部搜索，保留抽屉关闭。 |
| 修改 | `apps/desktop/src/features/coding/components/CodingHome.vue` | 底部对齐、弹性间距及高度适配。 |
| 修改 | `apps/desktop/src/components/UpdateChecker.vue` | 删除更新源表单和地址覆盖，使用发布包配置。 |
| 修改 | `apps/desktop/src/components/UpdateChecker.spec.ts` | 更新预设地址、缺失配置与旧本机设置的测试。 |
| 修改 | `apps/desktop/e2e/workbench-upgrade.spec.ts` | 验证无需输入地址的检查和安装。 |
| 修改 | `apps/desktop/e2e/visual-regression.spec.ts` | 验证底部间距、布局断点和品牌／表单移除。 |
| 修改 | `apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-home-1280-chromium-win32.png` | 当前首页视觉基线。 |
| 修改 | `apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-home-1440-chromium-win32.png` | 当前首页视觉基线。 |
| 修改 | `apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-home-1920-chromium-win32.png` | 当前首页视觉基线。 |
| 修改 | `apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-home-1280-at-125-chromium-win32.png` | 当前 125% 视觉基线。 |
| 修改 | `apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-thread-1440-chromium-win32.png` | 去除品牌后的任务页基线。 |
| 修改 | `apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-thread-1440-at-150-chromium-win32.png` | 当前 150% 任务页基线。 |
| 修改 | `design-qa.md` | 记录此次批注修订及验证，标注被替代的首轮结论。 |

### 记忆核对与限制

重新读取根目录 `AGENTS.md`、完整 `docs/project-state.md` 和 `docs/solutions/2026-09-20-local-only-context.md`。指定记忆中“插件开发中”仍是旧记录；当前 Skills／MCP 能力已由源码和本次浏览器回归核实。按根目录专门约定，用户未要求改写项目状态记忆，本次不改动该文件，界面变更记录在本验收文档。

默认开发配置的更新地址为空，检查时显示“自动更新服务尚未就绪”。正式包仍需由发布方预设独立更新地址；部署后终端用户通过检查更新使用它。未部署服务、未修改发布脚本／原生协议，未执行真实安装更新或 WebView2／Windows 系统缩放验收。未新增依赖，未提交或推送。

## 首轮实施记录

以下保留首轮实施与测试证据；本次批注涉及的描述以上方“当前状态”为准。

## 设计比对结论与修正记录

没有未解决的 P0／P1／P2 视觉问题。该结论限于下列视口、交互与隔离浏览器验证，不等同于原生安装包或真实模型服务验收。

| 级别 | 发现与影响 | 修正 | 最终证据 |
| --- | --- | --- | --- |
| P1 | 1280×720 下大插画和项目卡挤压输入区，发送操作需要额外滚动。 | 矮窗使用 160px 欢迎区、80px 项目卡和紧凑输入区；保持四段顺序。 | `visual-final/visual-regression-coding-首页-1280-chromium/home-1280.png`，发送按钮可见断言通过。 |
| P1 | 编辑中缩窄窗口，项目和快捷任务换行后输入区离开视口。 | 仅在输入区持有焦点时，于 resize 后滚动保持输入与发送可见；卸载时取消 RAF 和监听。 | `workbench-upgrade.spec.ts` 的宽窄窗口快捷任务回归通过。 |
| P2 | 初版首页插画裁切角色头部，卡片和文字比例与选定图不一致。 | 使用独立插画的 contain／定位与遮罩，恢复人物和猫的主体；调整标题、项目卡、快捷任务及留白。 | 最终 1488×1058 首页与源图在同一工具输入中比对；另检查 hero 局部截图。 |
| P2 | 个人简介计数进入输入框的可访问名称，精确标签定位不稳定。 | 为简介和计数分别提供 aria-labelledby／aria-describedby。 | 资料保存和跨页面同步浏览器回归通过。 |
| P2 | 外观页保留旧“插件”标题和重复卡片留白，偏离其他设置页。 | 使用单层壁纸设置面板和明确的“图片与自动配色”说明。 | `appearance-final/visual-regression-设置资料同步、插件、窄窗口与草稿往返-chromium/settings-appearance.png`；受影响 7 项浏览器复测通过。 |

没有将测试夹具中的旧标签、菜单入口或接口数据形状当作产品行为修复。对照实施前快照核实：执行过程文字原本在可访问名称中，恢复入口原本位于任务菜单，变更页原本通过会话审阅接口读取。测试已按真实入口和契约更新，保留暂停、继续、审批、文件查看等断言。

## 对照来源与状态

- 已选概念图：`C:/Users/likecandy/.codex/generated_images/01a0c6fa-33ee-7eb1-9d09-10f06934dd03/exec-f91114af-d392-4020-93fd-ae4a38eac338.png`。
- 源图 1488×1058 像素；实际首页 CSS 视口 1488×1058，deviceScaleFactor=1，浅色主题、首页就绪状态、空草稿。
- 实现证据：`F:/Program/Agent/.tmp/ui-redesign-20260922/visual-final/visual-regression-设计稿对应尺寸预览-chromium/home-reference-size.png`。
- 源图与实际图已放在同一次视觉输入中比较；图集提供并排对照，不以仅检查文件名或启动服务代替视觉验收。
- 页面截图集：<http://127.0.0.1:1431/index.html>。这是实际 Vue 渲染截图的浏览页；交互验收由 Playwright 操作真实组件完成。
- 首页、资料横幅和默认头像使用独立 PNG；文字、按钮、表单、下拉框均为真实组件，图标使用现有 Phosphor。

## 五项视觉核查

| 项目 | 检查结果与允许差异 |
| --- | --- |
| 字体与文字层级 | 系统字体栈统一到 Segoe UI／Microsoft YaHei UI；CDP 确认中文实际使用 Microsoft YaHei UI。正文 14–16px、标题按层级缩放，窄窗允许换行。概念图的放大文字按实施计划转换为桌面应用密度。 |
| 布局与间距 | 欢迎插画 → 最多三个项目 → 三个快捷任务 → 输入区顺序一致。默认侧栏按已批准计划设为 240px，保留已有宽度记忆。卡片 14px、控件 8px。1920 宽度内容居中限宽；390／760 窄窗与 1280 矮窗已查看。 |
| 色彩与状态 | 青白背景、深蓝灰文字、浅青选中态和细边框统一。默认主按钮白字／#007c89 对比度约 4.95:1。错误、等待审批、禁用、焦点仍有独立状态。深浅壁纸使用既有语义令牌覆盖。 |
| 图片与图标 | 角色、猫、日光桌面和山景方向与源图一致；重新生成的独立素材并非逐像素复刻。主体不拉伸，窄窗降低图像存在感。品牌入口使用现有图标库的机器人图标；没有将整页截图用作界面。 |
| 文案与内容 | 保留首页核心标题和三项快捷任务。实际项目列表和分支来自既有 store；不把概念图虚构路径写入产品。未配置、无项目、加载／保存失败使用既有真实状态。资料保留 50 字称呼、240 字简介及 1MB 头像限制。 |

可接受的差异：源图大约 273px 的侧栏按照实施计划落为 240px；源图装饰性手写文字未作为产品文案；项目卡展示“本机项目”和真实分支，保持项目路径原有展示边界；空输入的发送按钮按现有逻辑禁用。以上不改变页面顺序或既有操作契约。

## 验证命令与观察结果

以下命令从 `F:/Program/Agent/apps/desktop` 执行。测试通过已有本机边界替身与隔离数据，不使用真实资料、密钥、数据库或付费模型。

```powershell
node node_modules/vitest/vitest.mjs run src/features/coding/components src/components/AppShell.spec.ts src/components/ProfileSettingsPanel.spec.ts src/components/SettingsModuleNav.spec.ts src/components/SettingsView.spec.ts src/components/UserMenu.spec.ts src/components/MemorySettingsPanel.spec.ts src/services/localProfile.spec.ts src/services/wallpaperTheme
```

43 个测试文件、337 项通过。覆盖任务组件、共享资料状态、设置项目选择、保存失败和壁纸状态。

```powershell
node node_modules/vitest/vitest.mjs run src/components/ExtensionRegistryPanel.spec.ts
```

外观页最后调整后，2 项通过。两次合计 44 个文件、339 项不同组件测试。

```powershell
$env:PA_E2E_EXTERNAL_SERVER = '1'
node node_modules/@playwright/test/cli.js test e2e/coding-workbench.spec.ts e2e/coding-run.spec.ts e2e/workbench-upgrade.spec.ts e2e/local-access.spec.ts e2e/project-management.spec.ts e2e/documentation-mcp.spec.ts e2e/memories.spec.ts e2e/wallpaper-theme.spec.ts --retries=0 --reporter=line --output=../../.tmp/ui-redesign-20260922/regression-final
```

40 项通过，无重试。包含首次发送、草稿与设置往返、流式完成／失败、审批同意／拒绝、停止与恢复、SSE 重连、文件查看、Skills 使用、MCP 文档管理、记忆、项目管理、更新入口及壁纸保存失败。

```powershell
node node_modules/@playwright/test/cli.js test e2e/visual-regression.spec.ts --update-snapshots --retries=0 --reporter=line --output=../../.tmp/ui-redesign-20260922/visual-baseline-update
node node_modules/@playwright/test/cli.js test e2e/visual-regression.spec.ts --retries=0 --reporter=line --output=../../.tmp/ui-redesign-20260922/visual-final
```

六张基线在逐张人工比对后更新；随后不更新基线复跑，8 项通过。覆盖 1280×720、1440×900、1920×1080、1488×1058、390／760 窄窗以及 125%／150% 像素密度。设置往返用例收集到 0 个未定义请求、0 个非预期后端写请求、0 个浏览器错误。

```powershell
node node_modules/@playwright/test/cli.js test e2e/wallpaper-theme.spec.ts e2e/visual-regression.spec.ts --grep '设置资料同步|预览隔离|首页、会话|JPG|损坏|存储不可用|事务中止' --retries=0 --reporter=line --output=../../.tmp/ui-redesign-20260922/appearance-final
```

外观页最后调整后，受影响 7 项复测通过。此轮仅改变外观面板，首页／任务页六张基线不受影响。

```powershell
npm run build
```

最终通过，实际包含 `vue-tsc --noEmit` 和 Vite 生产构建，转换 5099 个模块。仍有部分 JS chunk 超过 500kB 的体积提示；本轮未扩大范围拆包或调整依赖。

在仓库根目录针对本次变更文件执行 `git diff --check -- <本记录列出的文件>`：退出码 0，无空白错误。部分文件存在 Git 的 CRLF→LF 提示；没有执行全库格式化。文本逐一使用 UTF-8 解码并检查无 BOM。实施前的 280 个相关文件快照用于核对增量，未覆盖其他既有工作。

初轮受沙箱子进程权限影响的 Vitest 启动，在获准运行后通过；Playwright 自动服务器启动曾超时，改为显式启动本机 Vite 并使用 PA_E2E_EXTERNAL_SERVER 后完成。旧视觉基线在改造后按预期失配，未通过放宽容差或删除断言规避。最终没有待处理的测试失败。

## 实施边界与资料状态

- 新增 `services/localProfile.ts` 共享资料，继续使用 `pa.local-profile.local` 和 `{ avatarDataUrl, nickname, bio }`；先持久化成功再通知各入口，失败保留旧状态。
- 沿用 Vue、自建 Pa 控件、Ant Design 和 Phosphor，没有新增框架或依赖，没有改后端 API、IPC、数据库或权限契约。
- 读过 `AGENTS.md`、完整 `docs/project-state.md` 和本次相关的 `docs/solutions/2026-09-20-local-only-context.md`，并在交付时复核相关段落。
- 记忆的“插件开发中”与当前源码不一致。通过实施前 `CapabilityRegistryPanel.vue`、`SkillsPanel.vue`、`McpIntegrationsPanel.vue` 和相关浏览器用例确认已有 Skills／MCP 管理能力；本次保留这些能力。此记录明确注明差异。
- 按根目录 AGENTS.md 的专门约定，只有用户明确要求时才改写 `docs/project-state.md`。本轮未更新指定记忆文件，也未创建新的项目记忆系统；当前设计决定与证据记录在本验收文档。

## 限制

- Windows 125%／150% 使用 Chromium deviceScaleFactor 模拟，不等同于真实 Windows 桌面缩放或 Tauri WebView2 安装包验收。
- 没有构建／安装 Tauri 原生包，没有连接真实模型、MCP OAuth 服务、生产数据或更新服务器。浏览器接口替身只能证明前端交互与契约，不证明外部服务可用。
- 三张本地 PNG 约 5.07MB。它们随前端打包，没有网络图床依赖；进一步图片压缩属于可选 P3 体积优化。
- 没有执行 Git 提交、分支、推送、部署或发布。

## 完整增量文件清单

“修改”以本轮开始前的工作区快照为准，包含用户已有但尚未追踪的文件。下面不包含仅阅读的文件；截图图集和测试过程文件位于 Git 忽略的 `.tmp/ui-redesign-20260922`。

| 操作 | 文件 | 变更 |
| --- | --- | --- |
| 修改 | [apps/desktop/e2e/coding-run.spec.ts](../../apps/desktop/e2e/coding-run.spec.ts) | 按当前审阅接口和恢复菜单修正旧夹具，保留任务断言。 |
| 修改 | [apps/desktop/e2e/coding-workbench.spec.ts](../../apps/desktop/e2e/coding-workbench.spec.ts) | 菜单使用稳定定位；在真实本机请求边界验证失联和重试。 |
| 修改 | [apps/desktop/e2e/local-access.spec.ts](../../apps/desktop/e2e/local-access.spec.ts) | 适配外观与命令入口，保留 API Key 本机链断言。 |
| 新增 | [apps/desktop/e2e/redesign-fixture.ts](../../apps/desktop/e2e/redesign-fixture.ts) | 新增隔离视觉数据，收集未定义请求、写请求和浏览器错误。 |
| 修改 | [apps/desktop/e2e/visual-regression.spec.ts](../../apps/desktop/e2e/visual-regression.spec.ts) | 覆盖页面顺序、三个项目、全部设置、草稿往返及尺寸截图。 |
| 修改 | [apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-home-1280-at-125-chromium-win32.png](../../apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-home-1280-at-125-chromium-win32.png) | 经逐张检查后更新的视觉回归基线。 |
| 修改 | [apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-home-1280-chromium-win32.png](../../apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-home-1280-chromium-win32.png) | 经逐张检查后更新的视觉回归基线。 |
| 修改 | [apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-home-1440-chromium-win32.png](../../apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-home-1440-chromium-win32.png) | 经逐张检查后更新的视觉回归基线。 |
| 修改 | [apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-home-1920-chromium-win32.png](../../apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-home-1920-chromium-win32.png) | 经逐张检查后更新的视觉回归基线。 |
| 修改 | [apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-thread-1440-at-150-chromium-win32.png](../../apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-thread-1440-at-150-chromium-win32.png) | 经逐张检查后更新的视觉回归基线。 |
| 修改 | [apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-thread-1440-chromium-win32.png](../../apps/desktop/e2e/visual-regression.spec.ts-snapshots/coding-thread-1440-chromium-win32.png) | 经逐张检查后更新的视觉回归基线。 |
| 修改 | [apps/desktop/e2e/wallpaper-theme.spec.ts](../../apps/desktop/e2e/wallpaper-theme.spec.ts) | 适配外观页位置，保留真实浏览器存储与失败路径断言。 |
| 修改 | [apps/desktop/src/App.vue](../../apps/desktop/src/App.vue) | 接入统一顶栏与资料入口，保留工作区导航状态。 |
| 新增 | [apps/desktop/src/assets/companion/default-avatar.png](../../apps/desktop/src/assets/companion/default-avatar.png) | 独立默认角色头像。 |
| 新增 | [apps/desktop/src/assets/companion/home-hero.png](../../apps/desktop/src/assets/companion/home-hero.png) | 独立首页角色与桌面插画。 |
| 新增 | [apps/desktop/src/assets/companion/profile-cover.png](../../apps/desktop/src/assets/companion/profile-cover.png) | 独立资料页山景横幅。 |
| 首轮新增，后续删除 | `apps/desktop/src/components/AppBrand.vue` | 首轮的品牌入口已按后续浏览器批注移除，当前不再存在。 |
| 修改 | [apps/desktop/src/components/AppShell.vue](../../apps/desktop/src/components/AppShell.vue) | 默认侧栏 240px，接入共享顶栏，保留拖拽记忆。 |
| 修改 | [apps/desktop/src/components/CapabilityRegistryPanel.vue](../../apps/desktop/src/components/CapabilityRegistryPanel.vue) | 统一项目选择和 Skills／MCP 页签。 |
| 修改 | [apps/desktop/src/components/ExtensionRegistryPanel.vue](../../apps/desktop/src/components/ExtensionRegistryPanel.vue) | 外观页使用单层壁纸面板，移除旧插件标题。 |
| 修改 | [apps/desktop/src/components/McpIntegrationsPanel.vue](../../apps/desktop/src/components/McpIntegrationsPanel.vue) | 统一连接列表、授权控件与表单视觉。 |
| 修改 | [apps/desktop/src/components/MemorySettingsPanel.vue](../../apps/desktop/src/components/MemorySettingsPanel.vue) | 统一记忆开关、表单与列表视觉。 |
| 修改 | [apps/desktop/src/components/ModelProvidersPanel.vue](../../apps/desktop/src/components/ModelProvidersPanel.vue) | 统一供应商双栏、编辑区和反馈样式。 |
| 修改 | [apps/desktop/src/components/ProfileSettingsPanel.spec.ts](../../apps/desktop/src/components/ProfileSettingsPanel.spec.ts) | 验证保存同步与失败保留旧资料。 |
| 修改 | [apps/desktop/src/components/ProfileSettingsPanel.vue](../../apps/desktop/src/components/ProfileSettingsPanel.vue) | 横幅与头像资料表单，共享保存状态，取消过期图片读取。 |
| 修改 | [apps/desktop/src/components/SettingsModuleNav.spec.ts](../../apps/desktop/src/components/SettingsModuleNav.spec.ts) | 补齐真实下拉组件注册，保留导航断言。 |
| 修改 | [apps/desktop/src/components/SettingsModuleNav.vue](../../apps/desktop/src/components/SettingsModuleNav.vue) | 统一设置导航、搜索与底部本机资料入口。 |
| 修改 | [apps/desktop/src/components/SettingsView.spec.ts](../../apps/desktop/src/components/SettingsView.spec.ts) | 增加 MCP 项目选择和无项目边界回归。 |
| 修改 | [apps/desktop/src/components/SettingsView.vue](../../apps/desktop/src/components/SettingsView.vue) | 统一页面标题和卡片，为 MCP 显示所属项目选择。 |
| 修改 | [apps/desktop/src/components/SkillsPanel.vue](../../apps/desktop/src/components/SkillsPanel.vue) | 统一技能列表、编辑表单及检查内容视觉。 |
| 修改 | [apps/desktop/src/components/UserMenu.vue](../../apps/desktop/src/components/UserMenu.vue) | 同步本机头像与称呼，保留菜单入口。 |
| 新增 | [apps/desktop/src/components/WorkspaceHeader.vue](../../apps/desktop/src/components/WorkspaceHeader.vue) | 新增通知入口、共享头像和称呼。 |
| 修改 | [apps/desktop/src/design/components.css](../../apps/desktop/src/design/components.css) | 统一输入占位色、textarea 尺寸与勾选状态。 |
| 修改 | [apps/desktop/src/design/tokens.css](../../apps/desktop/src/design/tokens.css) | 青白语义色、字体、8／14px 圆角与 160ms 动效。 |
| 修改 | [apps/desktop/src/features/coding/components/CodingComposer.vue](../../apps/desktop/src/features/coding/components/CodingComposer.vue) | 统一输入区边框、焦点与发送操作样式。 |
| 修改 | [apps/desktop/src/features/coding/components/CodingHome.spec.ts](../../apps/desktop/src/features/coding/components/CodingHome.spec.ts) | 验证快捷任务顺序、聚焦和既有首次发送行为。 |
| 修改 | [apps/desktop/src/features/coding/components/CodingHome.vue](../../apps/desktop/src/features/coding/components/CodingHome.vue) | 欢迎插画、最多三个项目、快捷任务和真实输入区，适配矮窗与窄窗。 |
| 修改 | [apps/desktop/src/features/coding/components/CodingSidebar.vue](../../apps/desktop/src/features/coding/components/CodingSidebar.vue) | 首页与项目树布局、搜索、设置入口及明亮选中态。 |
| 修改 | [apps/desktop/src/features/coding/components/CodingThreadWorkspace.vue](../../apps/desktop/src/features/coding/components/CodingThreadWorkspace.vue) | 统一正文宽度和窄窗顶部留白。 |
| 修改 | [apps/desktop/src/features/coding/components/RunTranscript.vue](../../apps/desktop/src/features/coding/components/RunTranscript.vue) | 统一消息、工具审批与正文层级，保留执行逻辑。 |
| 修改 | [apps/desktop/src/features/coding/components/ThreadHeader.vue](../../apps/desktop/src/features/coding/components/ThreadHeader.vue) | 统一项目、分支和运行状态，适配窄窗换行。 |
| 新增 | [apps/desktop/src/services/localProfile.spec.ts](../../apps/desktop/src/services/localProfile.spec.ts) | 覆盖原格式、存储失败、无效资料和跨窗口同步。 |
| 新增 | [apps/desktop/src/services/localProfile.ts](../../apps/desktop/src/services/localProfile.ts) | 共享本机资料状态，写入成功后再同步，清理跨窗口监听。 |
| 修改 | [apps/desktop/src/services/wallpaperTheme/antTheme.ts](../../apps/desktop/src/services/wallpaperTheme/antTheme.ts) | Ant Design 与自建控件共享字体、圆角及默认主色。 |
| 新增 | [design-qa.md](2026-09-22-ui-design-qa.md) | 本次设计比对、验证命令、边界与完整增量文件清单。 |

## 最终检查

- [x] 已查看同尺寸源图和最终实现，并检查首页局部字体与插画。
- [x] 已修复本轮发现的 P1／P2 问题，重拍并复查受影响页面。
- [x] 已完成关键组件、浏览器交互、视觉基线与生产构建验证。
- [x] 已核对完整增量清单、UTF-8 与既有工作保留情况。
- [x] 已区分隔离测试、真实服务和原生桌面验收边界。
- [x] 已完成项目记忆核对并注明过期描述，遵守其更新范围。
