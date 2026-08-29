# Run transcript design QA

## Comparison target

- Process source of truth: `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-edf9351d-8230-487b-84da-14074db94998.png`
- Result source of truth: `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-e66636c9-54ab-4940-87c1-036586b06d1e.png`
- Expanded-process implementation: `F:\Program\Agent\design-qa-run-process.jpg`
- Collapsed-result implementation: `F:\Program\Agent\design-qa-run-result.jpg`
- Local route: `http://127.0.0.1:1420/?ui=v2&coding=1&coding-preview=ready&coding-run-preview=completed`
- State: light theme, completed Coding run, process expanded and collapsed result variants.
- Process comparison density: source and implementation are both 1160 × 920 physical pixels.
- Result comparison density: source is an 845 × 934 focused reference crop; implementation is a 1160 × 920 full desktop shell capture, so transcript structure and content density were compared independently from the existing shell chrome.

## Findings

- No actionable P0/P1/P2 differences remain.
- The old technical event list and bordered `输出总结` card were removed from the primary presentation.
- Completed runs now default to a standalone result document. Clicking the Chinese duration row expands or collapses the public execution process.
- Process narration uses public durable decision summaries, plan state, tool activity, approvals, file changes and verification facts. It does not expose hidden chain-of-thought.
- Resolved approvals are compact activity rows; only pending approvals remain actionable cards.
- Final Markdown output is rendered without a status-card border, followed by distinct file-change and artifact result cards.
- Duration, activity and state labels use Chinese wording while exact tool identifiers remain secondary audit details.

## Comparison history

1. Baseline showed dense telemetry rows, a bordered terminal summary card and result content nested inside the audit panel.
2. First pass introduced a document-style duration header, natural-language process messages, lightweight activity rows and standalone result content.
3. Final pass compacted resolved approvals, hid the preview-only tag, preserved patch file counts and added result artifact cards.
4. Post-fix captures were compared side-by-side with both supplied references at the dimensions above.

## Primary interactions tested

- Opened the completed preview directly from its URL and verified it selects the sample task.
- Expanded and collapsed the process through the `用时 38 分钟 58 秒` control.
- Opened and closed the plan detail panel.
- Verified the collapsed state retains the final Markdown and result cards only.
- Verified no browser console warnings or errors were emitted.

## Follow-up polish

- P3: the implementation retains the product's existing desktop header, composer and status bar around the transcript; the supplied references show focused content from a different shell.

final result: passed

---

## 2026-08-29 · 普通用户权限修复与短横线指令索引

**Source visual truth paths**

- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-dafa9a10-fc84-4688-b94e-b9b1137b88b8.png`（修改前文字指令索引，2214 × 1268）
- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-b56f2ad1-9a05-49b8-af5b-4b95fc47c4ba.png`（短横线层级参考，521 × 297）
- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-5b0f2730-af84-414c-b3f7-b532c46e27fc.png`（普通用户 MCP 403 复现，2560 × 1377）
- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-9ef98d00-e93b-4dcb-b192-a81ab9116b41.png`（普通用户模型配置 403 复现，2220 × 1261）

**Implementation evidence**

- `F:\Program\Agent\design-qa-user-instruction-rail-final.png`（完成对话、激活短横线索引，2214 × 1268）
- Local route used during verification: `http://127.0.0.1:1420/?coding=1&coding-preview=ready&coding-run-preview=completed#/app`

**Viewport and comparison**

- 对话实现使用 2214 × 1268 CSS 视口，与修改前完整对话截图一致。
- 短横线参考图和完整实现截图已放入同一个视觉比较输入中检查；实现保留参考中的灰色短线、深色长激活线和无分割线关系，并沿用当前产品 token。
- 指令索引固定在对话页面最左侧，宽 44px；不再渲染标题或指令文字，不占用正文阅读列。

**State and interaction checks**

- 完成对话仅有一条用户指令，因此只渲染一条短横线；点击后按钮进入 `active` 状态，激活线为 34 × 3px。
- 点击索引后原始用户消息获得唯一的 `instruction-targeted` 高亮，定位与高亮行为保留。
- DOM 中仍有完整 `aria-label` 和 `title`，视觉精简没有移除键盘/辅助技术名称。
- 临时开发预览鉴权入口在截图完成后已删除，不进入生产代码或安装包。

**Permission and data checks**

- 普通用户定向后端测试确认 `/settings`、`/model-providers`、`/agent-model-profiles` 和 `/mcp/servers` 不再触发管理员权限拒绝。
- `/admin/overview` 与 `/internal/shutdown` 仍拒绝普通用户，管理员隔离未放宽。
- 当前模型各数据源改为独立失败处理；供应商列表暂时失败时，已加载 Profile 与基础设置仍可显示。
- 新 sidecar 构建时间晚于 `security.py` 和 `model_providers.py`，并通过独立 `/health` 200 检查。

**Findings**

- No actionable P0/P1/P2 differences remain.
- `[P3]` 参考局部图包含多条不同长度标记；当前验收会话只有一条用户指令，因此实现截图只出现一条激活标记，多指令排列由组件测试和 CSS 规则覆盖。

**Implementation checklist**

- [x] 文字索引改为左侧短横线索引。
- [x] 删除索引与正文之间的分割线。
- [x] 点击定位并高亮原指令。
- [x] 普通用户可读取 MCP、模型配置和当前模型所需接口。
- [x] 当前模型部分数据源失败时保留其余可用数据。
- [x] 重建并健康检查 Python sidecar。
- [x] 同视口截图、交互与源图对照完成。

final result: passed

## 2026-08-29 · 普通用户指令导航与对话布局

**Source visual truth paths**

- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-3f386324-61d3-4b86-970c-f9ee06378509.png`（底部状态栏删除目标，2560 × 1377）
- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-61ab4d38-d4ea-4e38-8b55-2cdface0c8cc.png`（用户指令索引参考，2560 × 1379）
- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-4574dab5-ef0b-4da1-8cd2-c40924c9266b.png`（回复与过程居中目标，2560 × 1379）
- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-a387517a-a71a-45db-8ac9-63b2c89efcf5.png`（空对话隐藏上下文状态，2220 × 1315）

**Implementation evidence**

- `F:\Program\Agent\design-qa-instruction-navigation.png`（完成对话、侧栏指令索引与居中回复，2048 × 1103）
- `F:\Program\Agent\design-qa-empty-thread.png`（空对话输入器，无上下文状态与底栏，2048 × 1103）

**Viewport and normalization**

- Browser CSS viewport: 2048 × 1103，与源图一/三同为宽屏桌面比例；比较关注布局关系、锚点位置和被删除区域，不作跨分辨率像素级误判。
- Implementation main area: left 272px, width 1776px。回复/过程列宽 1120px，left 600px；最终回复卡宽 900px，left 710px，位于主工作区水平中心。

**State and interaction checks**

- 完成对话：项目树的选中对话下显示用户指令标记；点击后目标消息获得 `instruction-targeted` 高亮，并执行平滑居中滚动。
- 空对话：`statusbarPresent = false`、`contextRingPresent = false`、`unavailableTextPresent = false`、输入器仍存在。
- 完成对话：`statusbarPresent = false`、用户指令标记存在、上下文用量仅在已有对话时保留。
- QA 临时入口产生的 router/Ant 注册警告仅来自精简测试壳；没有页面运行错误。临时入口已删除，不进入生产构建。

**Full-view comparison evidence**

- 源图一与空对话实现、源图三与完成对话实现在同一比较输入中检查：底部全宽状态栏已消失，正文与过程从靠左布局移动到中间阅读列。
- 指令索引使用项目树内的细轨道、节点和截断标题，保持现有侧栏密度；未复制参考产品中与本项目无关的菜单或装饰。
- 空对话输入器不再显示“上下文用量不可用/尚无会话”，模型、权限与发送入口不受影响。

**Findings**

- No actionable P0/P1/P2 differences remain.
- `[P3]` 参考图二的指令索引位于内容区左侧；根据用户明确要求，实现将其归入当前项目的选中对话节点下。

**Implementation Checklist**

- [x] 删除底部状态栏与空占位槽。
- [x] 从真实用户消息生成指令索引。
- [x] 点击指令滚动并高亮目标消息。
- [x] 回复、公开决策摘要和执行过程使用居中阅读列。
- [x] 空对话隐藏上下文用量状态。
- [x] 对比源图与实现截图并完成交互核验。
- [x] 删除临时 QA 入口。

final result: passed

---

## 2026-08-29 · 普通用户唯一 Coding 工作台

**Source visual truth path**

- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-107c0dbe-43b9-438e-a26f-17cebd3842e0.png`（目标图二，1647 × 1212）
- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-cba8c479-cca7-4494-a311-6d7171e9ef1e.png`（修复前普通用户旧壳，2560 × 1378）

**Implementation evidence**

- `F:\Program\Agent\design-qa-regular-coding-shell-final.png`（1647 × 1212）
- Local QA route used during verification: `http://127.0.0.1:1420/qa-coding-shell.html?coding-preview=ready`（临时入口在验证后删除，不进入生产构建）

**Viewport and density normalization**

- 目标图二与最终实现均为 1647 × 1212 像素。
- Browser CSS viewport: 1647 × 1212；`devicePixelRatio ≈ 1`；页面 `scrollWidth = 1647`、`scrollHeight = 1212`，无页面级溢出。

**State**

- 已认证普通用户、Coding 首页、项目树展开、`修复窄屏侧栏遮挡问题` 对话处于悬浮详情状态。
- 首条指令输入为 `检查首次指令标题生成`，尚未发送；项目为 `PrivateAgent`，工作区为 `根工作区`。

**Full-view comparison evidence**

- 最终实现只显示图二的信息架构：`新对话`、`项目`、`自动化`、`插件`、项目/对话树、底部账号与诊断入口、中央空态和底部输入器。
- 修复前截图中的深色旧导航、`今日`、`提醒`、`收件箱`、`长期目标`、`主动简报`、`快速捕获`、`Agent`、`任务活动`、`知识库`、`学习`、`记忆`均不再出现在普通用户 DOM 或渲染树。
- 目标和实现使用同一浅色工作台结构、同一项目层级、同一空态与输入器关系；页面无横向或纵向溢出。

**Focused region comparison evidence**

- 侧栏聚焦对照确认：项目/对话树、分支图标和悬浮详情卡均保留；详情卡显示真实项目、工作区和状态。
- 输入器聚焦对照确认：项目/工作区选择器、首条指令、权限、模型、推理强度、语音与发送入口均可见。

**Required fidelity surfaces**

- Fonts and typography: 继续使用现有字体与文本 token；导航、树、空态标题和输入层级清晰，无异常截断。
- Spacing and layout rhythm: 保留项目当前 272px rail 与 820px 输入 dock；它们比来源更紧凑，但不影响本次模块删减目标或交互可用性。
- Colors and visual tokens: 浅色背景、边框、文本、强调色和阴影全部沿用项目现有 token；旧深色导航不再加载。
- Image quality and asset fidelity: 页面无位图资产需求；可见图标继续使用项目现有 Phosphor 图标库，没有占位图或手绘图形。
- Copy and content: 顶层模块与图二一致；实现使用真实项目/工作区字段，没有保留图二之外的旧业务文案。

**Findings**

- 无剩余 P0/P1/P2。
- `[P3]` 项目现有 rail 与输入 dock 比来源更紧凑；本次用户明确要求删除图二不存在的模块，因此未扩大布局尺寸。

**Comparison history**

1. 初始状态 `[P1]`：普通用户被能力回退送入旧 Agent 壳，出现图二之外的十二个旧模块。
2. 修复：移除普通用户旧壳和 URL/localStorage 回退路径，并把 Coding 能力声明开放给已认证普通用户。
3. 最终同尺寸对照：旧模块计数全部为 0，图二四个顶层模块、项目树、空态、悬浮详情和输入器均存在，无 P0/P1/P2。

**Primary interactions tested**

- 折叠并重新展开项目树。
- 点击 `新对话` 后保持 Coding 首页。
- 输入首条指令并悬浮对话显示详情卡。
- Browser console warnings/errors checked: none.

**Implementation Checklist**

- [x] 普通用户不再加载 v1/旧 Agent 壳。
- [x] 旧 URL/localStorage 开关不再恢复旧模块。
- [x] 普通用户获得 Coding 创建链能力声明。
- [x] 图二四个顶层模块与项目树可见。
- [x] 旧模块 DOM 文案计数为 0。
- [x] 同尺寸截图、交互与控制台完成核对。

final result: passed

## 2026-08-29 · 项目内对话分组与悬浮详情

**Source visual truth path**

- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-4978174f-9f7e-42f0-9c4a-af542026f0ca.png`（783 × 585）

**Implementation evidence**

- `C:\Users\likecandy\.codex\visualizations\2026\08\29\01a04bac-79a8-7ed2-b600-b225ded0b317\coding-sidebar-grouped-hover-final.png`（1280 × 720）
- Local preview: `http://127.0.0.1:8796/?mode=coding`

**Viewport and normalization**

- Browser CSS viewport: 1280 × 720；`devicePixelRatio = 1.25`；浏览器截图输出为 1280 × 720。
- 参考图是侧栏与悬浮卡片的局部裁切，实现证据是完整桌面工作区；以左侧项目分组、对话行缩进、卡片锚点和卡片内部层级作为同状态聚焦比较，不对完整画布比例作虚假精确比较。

**State**

- 两个项目均展开；`PrivateAgent` 项目下的 `梳理 coding 模块依赖` 对话处于鼠标悬浮状态。
- 悬浮卡片显示该对话的真实项目、`feature/coding-workbench` 分支、工作区状态和更新时间。

**Full-view comparison evidence**

- 实现保持当前 PrivateAgent 工作台骨架，同时将原全局“最近”列表替换为项目分组；对话直接缩进显示在所属项目下，与参考图的层级关系一致。
- 悬浮卡片从侧栏右缘展开，不遮挡当前对话标题，并保持参考图中的白色抬升表面、细边框、圆角和轻阴影。
- 完整工作区无横向溢出，输入器与主区没有因详情卡出现而发生布局位移。

**Focused region comparison evidence**

- 参考图与最终实现截图已在同一个多图输入中对照。项目文件夹、对话行、悬浮卡片标题、右侧更新时间、项目行和分支行均清晰可读，无需额外裁切。
- 实现沿用现有 Phosphor 图标和设计 token；没有使用占位图、手绘 SVG、CSS 图形或表情符号替代参考中的界面图标。

**Required fidelity surfaces**

- Fonts and typography: 沿用产品字体和字号 token；项目名、对话标题、详情标题、元信息层级明确，长标题使用单行截断。
- Spacing and layout rhythm: 对话缩进、30 px 行高、卡片 360 px 宽度及三行信息节奏与参考密度接近；悬浮卡片固定定位并做视口边缘避让。
- Colors and visual tokens: 背景、边框、文本、强调色与阴影全部复用现有 token；卡片与当前工作台浅色主题一致。
- Image quality and asset fidelity: 此界面没有需要生成或复用的位图资产；所有可见图标来自项目现有图标库。
- Copy and content: 卡片只展示真实的对话标题、更新时间、项目名、分支/工作区和状态；没有虚构设备、版本或提交说明。

**Primary interactions tested**

- 折叠 `PrivateAgent` 项目后，其三个对话全部隐藏；再次展开后全部恢复。
- 鼠标移入对话后详情卡出现，移出后隐藏；组件测试同时覆盖键盘聚焦显示。
- 点击项目内对话会同步选择其项目、工作区和线程，并返回 Coding 工作台。
- 在全新浏览器标签页检查控制台：无 warning 或 error。

**Comparison history**

- Pass 1: 最终实现与参考的核心层级、悬浮位置和信息密度一致，没有发现需要返工的 P0/P1/P2 视觉差异。

**Findings**

- 无剩余 P0/P1/P2。
- `[P3]` 参考图的卡片包含设备/版本式元信息；当前数据契约没有这些事实，因此实现改为项目、分支和工作区状态，避免虚构内容。

**Open Questions**

- 无。

**Implementation Checklist**

- [x] 对话按项目分组并默认展开。
- [x] 项目可单独折叠与恢复。
- [x] 鼠标悬浮与键盘聚焦均可显示详情。
- [x] 详情卡内容来自现有真实数据。
- [x] 浏览器交互、控制台和视觉对照已检查。

final result: passed

---

# Workspace settings and project entry design QA

## Comparison target

- Settings source visual truth: `C:\Users\likecandy\.codex\attachments\b2eb8ab0-2578-4bcd-abb4-4f4b1b47fb94\image-4.png`
- New-project source visual truth: `C:\Users\likecandy\.codex\attachments\b2eb8ab0-2578-4bcd-abb4-4f4b1b47fb94\image-1.png`
- Account-menu source visual truth: `C:\Users\likecandy\.codex\attachments\b2eb8ab0-2578-4bcd-abb4-4f4b1b47fb94\image-3.png`
- Final settings implementation: `C:\Users\likecandy\.codex\visualizations\2026\08\29\01a04bac-79a8-7ed2-b600-b225ded0b317\settings-implementation-final.png`
- Narrow settings implementation: `C:\Users\likecandy\.codex\visualizations\2026\08\29\01a04bac-79a8-7ed2-b600-b225ded0b317\settings-narrow-implementation.png`
- Focused new-project implementation: `C:\Users\likecandy\.codex\visualizations\2026\08\29\01a04bac-79a8-7ed2-b600-b225ded0b317\new-project-dialog-focused.png`
- Focused account-menu implementation: `C:\Users\likecandy\.codex\visualizations\2026\08\29\01a04bac-79a8-7ed2-b600-b225ded0b317\account-menu-focused.png`
- Local route: `http://127.0.0.1:8796/?mode=settings`
- State: light theme; settings/status selected; account menu expanded; new-project dialog before directory selection.

## Viewport and density normalization

- Settings source: 2560 × 1376 physical pixels; the source is a Windows desktop capture whose CSS scale is not embedded in the file.
- Settings implementation: 2560 × 1376 CSS viewport; browser reported `devicePixelRatio = 1.25`; the browser capture was normalized to 2560 × 1376 pixels.
- Narrow implementation: 1100 × 760 CSS viewport and 1100 × 760 pixels.
- New-project source/focused implementation: 700 × 388 and 560 × 320 pixels. The focused regions were compared for hierarchy and control replacement rather than pixel identity because the requested design intentionally removes the editable absolute-path field.
- Account-menu source/focused implementation: 371 × 327 and 260 × 206 pixels. The focused regions were compared for placement, trigger/menu relationship, hierarchy and allowed actions; the requested two-action menu intentionally contains fewer rows.

## Full-view comparison evidence

- The final settings capture keeps the reference hierarchy: pale compact navigation on the left, a white top bar, centered page heading, and restrained bordered content surfaces.
- The settings navigation contains only the ten implemented project modules. It does not copy unrelated reference entries such as appearance, voice, billing, pets or browser settings.
- The 1100 × 760 capture shows the navigation as an overlay drawer with no horizontal overflow (`scrollWidth = innerWidth = 1100`).
- The account capture keeps the bottom-left identity trigger and opens the menu upward without covering the trigger.

## Focused region comparison evidence

- The new-project dialog preserves the supplied visual hierarchy and replaces the free-form absolute-path input with one resource-manager picker row. The primary action remains disabled until both a name and a selected directory exist.
- The account menu displays the actual username in both trigger and popover. It intentionally exposes only `设置` and `退出登录`, as requested.
- Phosphor icons from the project's existing icon family are used throughout; no raster placeholders, emoji, CSS drawings or handcrafted SVG substitutes were introduced.

## Required fidelity surfaces

- Fonts and typography: existing product font tokens and weight hierarchy are preserved; headings, muted descriptions, group labels and menu rows remain readable without clipping or awkward wrapping.
- Spacing and layout rhythm: sidebar density, centered content width, top spacing and card width now follow the reference proportions; modal and popover padding remain consistent with the existing design system.
- Colors and visual tokens: the final pass uses a white settings content canvas, muted navigation surface, subtle borders and the existing teal accent rather than introducing a new palette.
- Image quality and asset fidelity: the target screens contain no required product illustration. Existing icon-library components are retained, and the unavailable avatar feature is not imitated with a fake image.
- Copy and content: all visible setting entries map to implemented project features; the project picker, username, `设置` and `退出登录` labels match the requested behavior.

## Findings

- No actionable P0/P1/P2 differences remain.
- P3: the settings status module is intentionally much shorter than the reference's general-settings form because this project only renders its implemented status controls and data.
- P3: the account menu uses the project's existing user-circle icon rather than the reference application's photo avatar because this project has no avatar feature.

## Comparison history

1. The first full settings capture showed a muted page background, 900 px content width and slightly compressed top spacing compared with the supplied reference.
2. The settings canvas was changed to the surface token, content width to 1060 px, and top padding to 80 px.
3. The post-fix 2560 × 1376 capture was compared in the same multi-image input with the settings reference, dialog reference and account-menu reference; no P0/P1/P2 issue remained.

## Primary interactions tested

- Expanded the username menu and confirmed it exposes exactly `设置` and `退出登录`.
- Filtered settings with `数据库`, confirmed only `只读数据库` remained, selected it, and verified `aria-current="page"`.
- Opened the narrow settings drawer and confirmed it does not introduce page overflow.
- Inspected the new-project dialog DOM and confirmed there is no editable work-directory textbox; the directory control is a resource-manager picker button.
- Opened the final settings route in a fresh browser tab and found no console warnings or errors.

final result: passed
## 2026-08-29 · 新对话草稿态 / Ollama 参数合并 / 设置精简

**Source visual truth paths**

- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-bf97e466-75be-4a51-a6f4-649326f0d985.png`（新对话参考，2560 × 1380）
- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-c5801425-5edb-46d1-9dc6-ce5f75cd1af9.png`（模型参数参考，1413 × 571）
- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-2988241d-793d-4b44-86c3-bd8594fe76bd.png`（设置模块删减标注）

**Implementation evidence**

- `C:\Users\likecandy\.codex\visualizations\2026\08\29\01a04bac-79a8-7ed2-b600-b225ded0b317\new-conversation-implementation-final.png`（1599 × 862）
- `C:\Users\likecandy\.codex\visualizations\2026\08\29\01a04bac-79a8-7ed2-b600-b225ded0b317\settings-ollama-implementation.png`（1599 × 862）
- Local preview: `http://127.0.0.1:8796/?mode=coding`

**Viewport and normalization**

- Browser CSS viewport: 1600 × 862; `devicePixelRatio = 1.25`；浏览器截图输出为 1599 × 862。
- 新对话参考按完整桌面工作区构图比较；分辨率不同，因此以主区比例、输入器位置和信息层级归一化判断，不对单像素尺寸作虚假精确比较。
- 模型参数参考是独立模块，实现在用户要求下有意合并到 Ollama 供应商详情；比较重点为字段完整性、分组与可读性，而非保持原独立页面尺寸。

**State**

- 新对话：已有项目、根工作区、无选中会话、空白首轮输入状态。
- 模型设置：添加供应商表单切换到 `Ollama（本地）`，本地模型参数区域展开。
- 设置导航：仅保留运行状态、当前模型、模型设置、MCP 外部能力、备份与恢复、关于与更新。

**Full-view comparison evidence**

- 新对话实现保持参考图的核心关系：左侧项目/对话导航、中央空状态、底部主输入器；项目与分支选择位于输入器上沿，首条指令可直接输入。
- 设计系统沿用 PrivateAgent 现有字体、低饱和背景、边框、圆角与阴影，没有引入新的视觉语言。参考图白底与本项目浅灰工作区的差异属于既有产品 token 约束。
- 设置页移除了标注的 HTTP 端点、只读数据库、连接配置入口；MCP 作为能力与数据组的唯一外部服务入口保留。

**Focused region comparison evidence**

- `settings-ollama-implementation.png` 的 Ollama 参数卡清晰呈现温度、上下文长度、默认启用知识库三项，字段在一个紧凑分组内且与 Base URL/API 格式保持同一保存上下文，因此无需额外裁剪。
- 新对话输入器在完整视图中已足够清晰；DOM 检查同时确认项目、工作区、权限、模型和推理强度均有可访问名称。

**Required fidelity surfaces**

- Fonts and typography: 使用现有 `--font-sans` 与文本 token；标题、说明、选择器和工具栏层级清晰，无异常换行或截断。
- Spacing and layout rhythm: 空态垂直居中，输入器固定在主区底部；选择器与输入器共用一个 dock，最终无拥挤或标签折行。
- Colors and visual tokens: 背景、边框、文本和强调色全部复用项目 token；对比度与现有工作台一致。
- Image quality and asset fidelity: 页面无位图资产需求；空态与项目/分支使用现有 Phosphor 图标，没有手绘 SVG、CSS 图形或占位图。
- Copy and content: 文案明确说明先选项目/分支再输入首条指令；Ollama 参数与 MCP 授权说明符合当前行为。

**Primary interactions tested**

- 项目从 `PrivateAgent` 切换到 `网站重构` 后，中心标题和工作区列表同步更新。
- 首条指令输入后发送按钮可用；单元测试验证首次发送创建会话、提取标题并暂存完整首轮指令。
- 添加供应商切换为 `Ollama（本地）` 后，本地模型参数区域立即出现。
- Browser console errors/warnings checked: none.

**Comparison history**

- Pass 1: `[P2]` 项目和工作区的辅助标签未在父组件内隐藏，导致标签窄列折行并挤压选择器。证据：`new-conversation-implementation.png`。
- Fix: 在 `CodingHome.vue` 增加局部 visually-hidden 规则，并为两个紧凑选择器设置稳定最小宽度。
- Pass 2: `new-conversation-implementation-final.png` 中选择器恢复单行、输入器对齐，无剩余 P0/P1/P2 问题。

**Findings**

- 无剩余 P0/P1/P2。
- `[P3]` 参考图的中心品牌符号与本项目现有图标不同；当前使用同一图标库中的对话图标，属于既有产品资产约束，可接受。

**Open Questions**

- 无。

**Implementation Checklist**

- [x] 新对话直接进入空白输入状态。
- [x] 项目与分支选择器位于输入器上方并可切换。
- [x] Ollama 本地参数集中到模型设置。
- [x] 标注的三个设置模块已移除。
- [x] 浏览器控制台与主要交互已检查。

final result: passed

## 2026-08-29 · 管理员后台双模块改版

**Source visual truth paths**

- `C:\Users\likecandy\.codex\attachments\a5e61841-a080-474e-837e-e58476f460cd\image-1.png`（现状与红框问题，2560 × 1378）
- `C:\Users\likecandy\.codex\attachments\a5e61841-a080-474e-837e-e58476f460cd\image-2.png`（后台布局目标，1580 × 877）

**Implementation evidence**

- Local preview: `http://127.0.0.1:1420/#/admin`
- `C:\Users\likecandy\.codex\visualizations\2026\08\29\01a04ccb-b5d9-7f81-b31c-9a2841b56e4f\admin-system-qa-final.png`（系统模块，1580 × 876）
- `C:\Users\likecandy\.codex\visualizations\2026\08\29\01a04ccb-b5d9-7f81-b31c-9a2841b56e4f\admin-users-qa.png`（用户模块，1580 × 876）
- `C:\Users\likecandy\.codex\visualizations\2026\08\29\01a04ccb-b5d9-7f81-b31c-9a2841b56e4f\admin-create-modal-qa.png`（创建用户弹窗，1580 × 876）

**Viewport and normalization**

- Browser CSS viewport: 1580 × 876; `devicePixelRatio ≈ 1`。参考图为 1580 × 877，1px 高度差按相同桌面视口归一化，不作虚假单像素判断。
- Source target pixels: 1580 × 877. Implementation screenshots: 1580 × 876. No density resampling was required.

**State**

- 实现截图使用临时只读 QA 入口挂载正式 `AdminPage.vue`、正式样式与 Ant Design 组件，并注入真实结构的模拟统计、用户和审计数据。
- 系统模块、用户模块、创建用户弹窗、修改角色弹窗和停用确认均已检查。临时入口已删除，不进入正式路由或生产构建。

**Full-view comparison evidence**

- `image-2.png` 与 `admin-system-qa-final.png` 在同一比较输入中检查：实现保留蓝色顶栏、深色左侧导航、浅色内容画布、统计卡、状态面板和数据表格的后台信息层级。
- 左侧仅有 `系统` 与 `用户` 两个模块，符合用户明确要求；未复制参考图中与本项目无关的多层菜单、图表或日历。
- 系统和用户截图的 `bodyScrollWidth = pageScrollWidth = innerWidth = 1580`，没有页面级横向溢出；密集用户表仅在表格内部保留可控横向滚动。

**Focused region comparison evidence**

- `image-1.png`、`admin-users-qa.png` 与 `admin-create-modal-qa.png` 在同一比较输入中检查。原红框中的页外表单已完全消失；关闭弹窗时 `visibleDialogs = 0` 且 `rawCreateFormOutsideModal = 0`。
- 打开创建用户后，仅出现一个居中的标准对话框：520 × 440，横向中心误差小于 2px，表单位于 `.ant-modal .ant-form` 内，页面仍无横向溢出。
- 用户表展示角色、状态、会话、项目、文档、操作数、最近登录及管理操作；角色修改和停用确认均能打开。

**Required fidelity surfaces**

- Fonts and typography: 沿用产品 `--font-sans` 字体栈；标题、说明、统计值、表头和辅助文字层级清楚，无异常截断或换行。
- Spacing and layout rhythm: 220px 导航、56px 顶栏、42px 面包屑和内容间距形成稳定后台框架；卡片、面板和表格对齐一致。
- Colors and visual tokens: 顶栏使用现有信息蓝、侧栏使用现有 rail 深色 token，内容区和状态色全部复用项目语义 token。
- Image quality and asset fidelity: 页面无需位图资产；全部图标来自现有 Ant Design 图标库，没有手绘 SVG、CSS 图形、emoji 或占位图。
- Copy and content: `系统` / `用户`、监控指标、审计、创建用户、角色和状态文案均对应已实现功能，没有复制参考模板中的无关业务。

**Findings**

- No actionable P0/P1/P2 differences remain.
- `[P3]` 参考模板包含图表、日历和多级菜单；实现有意使用当前项目真实的系统健康、审计和用户数据，并按用户要求把左栏收敛为两个一级模块。

**Comparison history**

- Initial attempt: 正式路由停在管理员登录页，无法取得实现截图，QA 暂记 blocked。
- Resolution: 创建未进入正式路由的临时只读入口，挂载同一个 `AdminPage.vue` 和正式组件栈，完成三种状态截图后删除入口。
- Visual pass 1: 参考图和实现图在同一比较输入中检查，未发现 P0/P1/P2；因此无需视觉修复迭代。
- Post-cleanup verification: 临时入口删除后，管理员相关 6 项测试与生产构建再次通过。

**Primary interactions tested**

- 切换 `系统` 与 `用户` 两个模块。
- 打开创建用户弹窗，确认表单仅位于弹窗内部。
- 打开修改角色弹窗和停用确认弹窗，再取消操作。
- Browser console warnings/errors checked: none.

**Implementation Checklist**

- [x] Production build completed.
- [x] Page-level regression verifies only two navigation modules.
- [x] Page-level regression verifies the form is absent before the modal opens.
- [x] Capture system, user and create-modal states at the normalized 1580px reference viewport.
- [x] Check modal placement, overflow, primary interactions and browser console.
- [x] Compare the target and implementation in the same visual input.
- [x] Remove the temporary QA entry and re-run production verification.

final result: passed

## 2026-08-29 · 普通用户指令索引、模型权限与个人资料

**Source visual truth paths**

- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-2eb48802-d14e-488f-a54e-7e8d60350265.png`（指令索引目标位置，2559 × 1379）
- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-96bb9dea-5ca2-4be6-9ff5-6ccbe1096e17.png`（当前模型无数据现状，2220 × 1261）
- `C:\Users\LIKECA~1\AppData\Local\Temp\codex-clipboard-cd26b109-7806-40fd-a40a-07385fa4f200.png`（模型设置管理员权限错误现状，2220 × 1261）

**Implementation evidence**

- `design-qa-user-instruction-rail.png`：正式 `CodingSidebar.vue` 与 `CodingThreadWorkspace.vue` 组合，指令索引位于侧栏右侧、对话正文左侧。
- `design-qa-current-model.png`：正式 `SettingsModuleNav.vue` 与 `SettingsView.vue` 组合，四项当前模型数据均已显示。
- `design-qa-model-settings-user.png`：普通用户模型设置页未出现管理员权限错误。
- `design-qa-mcp-user.png`：普通用户 MCP 页可加载空态，未出现管理员权限错误。
- `design-qa-profile-settings.png`：新增个人资料导航、头像入口、称呼、简介和账号信息。

**State and method**

- 使用临时只读 QA 入口挂载正式组件，并以真实接口结构模拟普通用户、当前模型、Provider 与 MCP 空态数据；临时入口不进入正式路由或生产构建，验收后删除。
- 源图与实现截图在同一视觉比较输入中检查；默认内置浏览器视口用于桌面布局验证，不对截图做密度拉伸或伪造像素级结论。

**Required fidelity surfaces**

- Fonts and typography: 沿用现有字体和文本 token；指令索引、模型信息和个人资料层级清晰，无异常截断。
- Spacing and layout rhythm: 指令索引使用独立窄栏，不再挤占项目树；正文仍保持居中阅读宽度；设置卡片与现有模块间距一致。
- Colors and visual tokens: 索引激活态、模型信息卡、资料表单及反馈均复用项目语义 token。
- Image quality and asset fidelity: 无新增位图 UI 资产；头像占位和功能图标使用现有 Phosphor 图标，上传头像保留真实图片预览能力。
- Copy and content: 当前模型显示服务、模型 ID、嵌入模型和请求地址；个人资料明确说明首版仅保存在当前设备。

**Primary interactions tested**

- 点击指令索引后，索引项获得 `active` 状态且原指令节点获得 `instruction-targeted` 高亮，定位链路生效。
- 当前模型 DOM 显示 `DeepSeek`、`deepseek-chat`、`nomic-embed-text` 与请求地址，不再是 `—`。
- 模型设置与 MCP 页面中 `Administrator access is required` 匹配数均为 0。
- 个人资料模块可编辑简介并保存，本机保存成功反馈出现。
- Browser console errors/warnings checked after QA harness registration correction: none.

**Findings**

- 无剩余 P0/P1/P2。
- `[P3]` 个人资料首版使用本机 `localStorage`，不跨设备同步；这是本次“先把模块加上”的明确范围限制，并已在页面提示。
- 模型与 MCP 配置仍是共享后端配置；普通用户开放访问后，多用户之间会看到同一套配置，这是当前产品架构的既有语义。

**Implementation Checklist**

- [x] 指令索引从项目树移入对话内侧栏。
- [x] 点击索引可定位并高亮原指令。
- [x] 当前模型显示真实配置数据。
- [x] 普通用户模型设置与 MCP 访问不再被管理员前缀拦截。
- [x] 设置导航新增个人资料与头像入口。
- [x] 源图和实现图在同一比较输入中检查。
- [x] 主要交互和浏览器控制台已检查。

final result: passed
